"""Dynamic de-esser (Phase B — sibilance 3-8 kHz in the master chain).

The legacy sibilance treatment (``vocal.py``) is STATIC and lives only in
the /vocal path: a fixed -12 dB peak cut at 7.2 kHz blended by a constant
amount. This module adds a DYNAMIC master-chain de-esser: the 3-8 kHz
"ess" band is only attenuated while sibilance is actually present, and the
reduction ramps in/out with attack/release smoothing so the master never
"pumps" on consecutive sibilants.

Band — 3-8 kHz, anchored on the existing analysis band table
(``TARGET_BANDS_HZ``: presence = 6 kHz, air = 10 kHz) and the vocal-path
de-esser (5-8 kHz, center 7.2 kHz). The 3-8 kHz window spans upper-mids
to presence, where fricatives ("s", "ch", "sh") concentrate their noise.

Detector — the energy ratio of the sibilance band vs the broadband
signal: ``ratio_db = band_env_db - total_env_db`` with the shared one-pole
attack/release envelope (``multiband.detect_envelope``, 15 ms / 150 ms).
A sibilant burst concentrates most of the frame's energy into the band
(ratio → ≈0 dB); a clean tone leaves the band near its noise floor (ratio
→ very negative).

A ratio detector alone would dull a permanently-bright program (hi-hat
heavy or sibilant-by-design mixes keep the ratio high constantly), so the
reduction is gated by TWO further conditions (``_detection_gate``):

  * the band must be AUDIBLE (``band_db > -55 dBFS``) — silence/noise
    floors never pump the gain, and
  * the band must SPIKE above its own rolling reference level (a slow
    one-pole average, 500 ms): sibilance is a TRANSIENT event on top of
    the program's average band level, so a band that sits permanently at
    its reference (bright pads, hats, sizzle) stays untouched.

Gain computer — linear ramp ``gr_db = -amount_db * clip(excess/range, 0, 1)``
over a 10 dB detector range: threshold → no cut, threshold + 10 dB → the
full ``amount_db`` cut. Cuts only; below threshold the band contributes
exactly 0 dB (bit-exact no-op on clean material).

Topology — the band is isolated with a 4th-order Butterworth band-pass
(``scipy.signal.butter``, 24 dB/oct), and the output is the parallel
attenuation ``y = x + (g_lin - 1) * x_band`` — exactly at ``g_lin = 1``
the contribution is zero, so a below-threshold pass can short-circuit to
the untouched input (bit-exact), mirroring the static-EQ discipline of
``dyn_eq.py``.

Neutral mode: ``amount_db == 0`` (or the engine gate ``deesser_enabled``
off) makes the stage a bit-exact no-op. The engine inserts this stage
gated by ``params.deesser_enabled`` right after gain staging — BEFORE the
tonal/dynamics chain — so existing masters pass through unchanged.
"""

from dataclasses import dataclass

import numpy as np
from scipy.signal import butter, sosfilt
from typing import Any

from audiomind.processing.multiband import (
    DEFAULT_ATTACK_MS,
    DEFAULT_RELEASE_MS,
    _alpha_from_tau_ms,
    _level_to_db,
    detect_envelope,
)

#: Sibilance band edges (Hz) — the "ess" region. Anchored on the analysis
#: band table (``TARGET_BANDS_HZ`` presence = 6 kHz, air = 10 kHz) and the
#: vocal-path de-esser range (5-8 kHz, center 7.2 kHz).
DEESSER_BAND_LOW_HZ = 3000.0
DEESSER_BAND_HIGH_HZ = 8000.0
#: Detector threshold (dB): the band must EXCEED this ratio (band energy
#: vs broadband energy) before reduction starts. -4 dB ≈ the band holds
#: ~40% of the instantaneous energy — a dominant spectral region.
DEESSER_THRESHOLD_DB = -4.0
#: Detector range (dB): sibilance excess over the threshold that drives
#: the reduction from zero to the full ``amount_db``.
DEESSER_RANGE_DB = 10.0
#: Detection-gate floor (dBFS): the band must be audible before any
#: reduction — silence and noise-floor material never moves the gain.
DEESSER_LEVEL_FLOOR_DB = -55.0
#: Detection-gate spike (dB): the band must rise at least this much above
#: its own rolling reference level — sibilance is a transient event, not
#: a permanent bright fixture of the program.
DEESSER_SPIKE_DB = 3.0
#: Rolling band-reference time constant (ms) — the per-track "average band
#: level" the transient spike is measured against.
DEESSER_REFERENCE_T_MS = 500.0
#: Default maximum gain reduction (dB).
DEFAULT_AMOUNT_DB = 6.0


@dataclass(frozen=True)
class DeesserParams:
    """Dynamic de-esser stage configuration.

    ``amount_db == 0`` makes the stage transparent (part of the bit-exact
    neutral path). The band edges default to the module anchors; only the
    max reduction and the detector threshold are engine-exposed.
    """

    amount_db: float = DEFAULT_AMOUNT_DB
    threshold_db: float = DEESSER_THRESHOLD_DB
    band_low_hz: float = DEESSER_BAND_LOW_HZ
    band_high_hz: float = DEESSER_BAND_HIGH_HZ
    attack_ms: float = DEFAULT_ATTACK_MS
    release_ms: float = DEFAULT_RELEASE_MS

    def is_neutral(self) -> bool:
        """True when the stage is a bit-exact no-op (no reduction possible)."""
        return self.amount_db <= 0.0


def _smooth_db(x_db: np.ndarray, tau_ms: float, sr: int) -> np.ndarray:
    """Slow one-pole moving average of a dB trajectory (rolling reference)."""
    alpha = _alpha_from_tau_ms(tau_ms, sr)
    y = np.empty_like(x_db)
    acc = 0.0
    for i in range(x_db.shape[0]):
        acc = alpha * acc + (1.0 - alpha) * x_db[i]
        y[i] = acc
    return y


def detection_gate(band_db: np.ndarray, sr: int) -> np.ndarray:
    """Audibility + transient gate: 1.0 where reduction is allowed, else 0.0.

    Both conditions must hold — the sibilance band is audible above the
    -55 dBFS floor AND spiking at least ``DEESSER_SPIKE_DB`` over its own
    rolling reference level (500 ms average). The spike condition is what
    keeps a permanently-bright program (hats, sizzle, sibilant-by-design)
    from being dulled: sibilance is a transient on top of the program's
    average band level, so a band that sits at its own reference stays
    untouched even when the ratio detector would engage.
    """
    band = np.asarray(band_db, dtype=np.float64)
    if band.shape[0] == 0:
        return np.zeros(0, dtype=np.float64)
    reference = _smooth_db(band, DEESSER_REFERENCE_T_MS, sr)
    floor_ok = band > DEESSER_LEVEL_FLOOR_DB
    spike_ok = band - reference > DEESSER_SPIKE_DB
    return np.asarray(floor_ok & spike_ok, dtype=np.float64)


def deesser_gain(
    sibilance_db: np.ndarray,
    threshold_db: float,
    amount_db: float,
    gate: np.ndarray | None = None,
) -> np.ndarray:
    """Detector (dB sibilance ratio) -> gain reduction (dB), cuts only.

    Linear ramp from 0 dB at ``threshold_db`` to ``-amount_db`` at
    ``threshold_db + DEESSER_RANGE_DB``, multiplied by the detection gate
    (0/1). Below threshold — or with the gate closed — the output is
    exactly -0.0 / 0.0 (the band contributes 0 dB), so a pass that never
    engages can short-circuit to the untouched input.
    """
    excess = np.asarray(sibilance_db, dtype=np.float64) - threshold_db
    fraction = np.clip(excess / DEESSER_RANGE_DB, 0.0, 1.0)
    if gate is not None:
        fraction = fraction * np.asarray(gate, dtype=np.float64)
    return -amount_db * fraction


class Deesser:
    """Orchestrates band filter -> joint detect -> dynamic cut -> parallel mix.

    The detector runs on the joint ``(L+R)/2`` mix so both channels share
    the same gain trajectory (stereo image preserved). In the neutral
    configuration the input is returned untouched, bit-exactly.
    """

    def __init__(self, sr: int, params: DeesserParams | None = None) -> None:
        self.sr = int(sr)
        self.params = params if params is not None else DeesserParams()
        nyquist = float(self.sr) / 2.0
        low = float(self.params.band_low_hz)
        high = float(self.params.band_high_hz)
        if not (0.0 < low < high < nyquist):
            raise ValueError(
                f"Band edges must satisfy 0 < low < high < sr/2, got "
                f"low={low}, high={high}, sr={self.sr}"
            )
        self._sos = butter(
            4, [low / nyquist, high / nyquist], btype="band", output="sos"
        )

    def _is_neutral(self) -> bool:
        """True when the stage is a bit-exact no-op (amount 0)."""
        return self.params.is_neutral()

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply the de-esser, returning audio with input shape/dtype."""
        out, _ = self._process(audio)
        return out

    def process_with_diagnostics(
        self, audio: np.ndarray,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Like :meth:`process` but also returns the gain-reduction and
        detector trajectories (used by the Phase B verification)."""
        return self._process(audio)

    def _process(self, audio: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        x = np.asarray(audio)
        mono = x.ndim == 1
        x2 = x[np.newaxis, :] if mono else x
        n = x2.shape[-1]
        empty_diag = {
            "gr_db": np.zeros(0),
            "gr_mean_db": 0.0,
            "sibilance_db": np.zeros(0),
            "band_db": np.zeros(0),
        }
        if n == 0:
            return audio.copy(), empty_diag

        if self._is_neutral():
            # The parallel mix cannot be bit-identical to the input in
            # general; with no reduction possible we skip the filtering
            # pass entirely so the neutral path is exactly the input
            # (null test), mirroring the multiband/dyn-eq shortcuts.
            return audio.copy(), empty_diag

        orig_dtype = x2.dtype
        work = x2.astype(np.float64)
        band = sosfilt(self._sos, work, axis=-1)

        # Joint (L+R)/2 detector: one envelope, both channels.
        joint_band = band.mean(axis=0)
        joint = work.mean(axis=0)
        band_env = detect_envelope(
            joint_band, self.sr, self.params.attack_ms, self.params.release_ms
        )
        total_env = detect_envelope(
            joint, self.sr, self.params.attack_ms, self.params.release_ms
        )
        band_db = _level_to_db(band_env)
        sibilance_db = band_db - _level_to_db(total_env)

        gate = detection_gate(band_db, self.sr)
        gr_db = deesser_gain(
            sibilance_db, self.params.threshold_db, self.params.amount_db, gate
        )
        if not np.any(gr_db < 0.0):
            # Never above threshold (or gate fully closed) — the reduction
            # stays exactly 0 dB; return the untouched input (bit-exact
            # no-op on clean material, mirroring the "transparent when
            # below threshold" contract).
            return audio.copy(), {
                "gr_db": gr_db,
                "gr_mean_db": 0.0,
                "sibilance_db": sibilance_db,
                "band_db": band_db,
            }

        g_lin = 10.0 ** (gr_db / 20.0)
        y = work + (g_lin - 1.0)[np.newaxis, :] * band

        out = y.astype(orig_dtype)
        if mono:
            out = out[0]

        diag = {
            "gr_db": gr_db,
            "gr_mean_db": float(np.mean(gr_db)),
            "sibilance_db": sibilance_db,
            "band_db": band_db,
        }
        return out, diag


def deesser(
    audio: np.ndarray, sr: int, params: DeesserParams | None = None,
) -> np.ndarray:
    """Full dynamic de-esser pass (convenience wrapper).

    Neutral by default: with no ``params`` the input is returned
    bit-identical (``amount_db == 0``), so the stage is a safe no-op unless
    explicitly configured with a positive reduction. Mirrors the neutral
    defaults of ``adaptive_compress`` / ``dynamic_eq``.
    """
    if params is None:
        params = DeesserParams(amount_db=0.0)
    return Deesser(sr, params).process(audio)