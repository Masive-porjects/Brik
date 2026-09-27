"""Dynamic EQ (Sprint 5 — fixed bell/Q filters, level-dependent surgical cuts).

The inverse philosophy of the Sprint 4 multiband compressor: instead of
splitting the spectrum with LR4 crossovers and compressing each band, a
dynamic EQ keeps ONE fixed bell/Q band-pass filter per band and lets the
per-band gain depend on the band's input energy. The gain computer is the
roadmap formula

    G(t) = min(0, −(E(t) − T)·(1 − 1/R))

where E(t) is the band envelope level in dB, T the band threshold in dB and
R the ratio (≥ 1.0). It yields CUTS ONLY (gain ≤ 0) and only when the
problem exists: below threshold (E < T) the band is transparent (G = 0),
above threshold the band is attenuated in proportion to how far it exceeds
T.

Concrete use case — a 400 Hz resonance that appears only in dense chords:
a static EQ must cut that band constantly, dulling the whole tone; the
dynamic EQ leaves the note alone and attacks the ringing resonance only
while it is above threshold.

Detector — REUSED from the Sprint 4 multiband module (``detect_envelope``
with its one-pole attack/release recursion and ``_level_to_db`` conversion).
Per band the envelope is detected on the joint ``(L+R)/2`` mix so both
channels share the same gain trajectory and the stereo image is preserved.

Filter — one deterministic minimum-phase 2nd-order bell/band-pass biquad
per band (RBJ "constant 0 dB peak gain" band-pass around ``freq_hz / Q``,
built directly as an SOS section): unity gain exactly at the center
frequency, attenuating to silence away from it.

Topology — the fixed bell filter IS the static EQ; the dynamic part scales
its contribution. With ``x_band`` the band-pass output and the per-sample
linear gain ``g_lin = 10**(G/20)`` the output is

    y = x + (g_lin − 1)·x_band

so at the center frequency the net gain is exactly ``g_lin`` (a cut of
``−G`` dB), tapering to 0 dB away from it — a level-dependent peaking cut.

Neutral mode: when every band has ratio 1:1 the stage is a bit-exact no-op
(the whole split/filter pass is skipped and the input returned untouched).
The engine inserts this stage gated by ``params.dyn_eq_enabled`` with
ratio-1.0 defaults, so existing masters pass through unchanged.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.signal import sosfilt

from audiomind.processing.multiband import (
    DEFAULT_ATTACK_MS,
    DEFAULT_RELEASE_MS,
    _level_to_db,
    detect_envelope,
)

#: Default dynamic-EQ band center frequencies (Hz) — the roadmap's 400 Hz
#: resonance case plus the classic 2.5 kHz presence and 8 kHz air bands.
DEFAULT_BAND_FREQS_HZ = (400.0, 2500.0, 8000.0)
#: Default bell width (Q) shared by the bands.
DEFAULT_Q = 4.0
#: Default per-band threshold (dB).
DEFAULT_THRESHOLD_DB = -20.0


@dataclass(frozen=True)
class DynEqBandParams:
    """Per-band dynamic-EQ settings.

    ``ratio == 1.0`` makes the band transparent (part of the stage's
    bit-exact neutral path); ``ratio > 1.0`` cuts the band only above
    ``threshold_db``.
    """

    freq_hz: float
    q: float
    threshold_db: float = DEFAULT_THRESHOLD_DB
    ratio: float = 1.0
    attack_ms: float = DEFAULT_ATTACK_MS
    release_ms: float = DEFAULT_RELEASE_MS


@dataclass(frozen=True)
class DynEqParams:
    """Full dynamic-EQ stage configuration (one bell/Q band per entry).

    The defaults are NEUTRAL: all bands at ratio 1:1, so the stage is a
    bit-exact bypass unless engaged.
    """

    bands: tuple[DynEqBandParams, ...] = field(
        default_factory=lambda: tuple(
            DynEqBandParams(freq_hz=f, q=DEFAULT_Q)
            for f in DEFAULT_BAND_FREQS_HZ
        )
    )


def _build_bell_sos(sr: int, freq_hz: float, q: float) -> np.ndarray:
    """Deterministic minimum-phase 2nd-order bell/band-pass biquad (RBJ).

    RBJ "constant 0 dB peak gain" band-pass: unity gain exactly at
    ``freq_hz`` with bandwidth ``freq_hz / Q``. Minimum-phase: poles strictly
    inside the unit circle; zeros lie on the unit circle at DC/Nyquist, as
    any true band-pass (silent at DC and Nyquist) requires.
    """
    w0 = 2.0 * np.pi * float(freq_hz) / float(sr)
    alpha = np.sin(w0) / (2.0 * float(q))
    cos_w0 = np.cos(w0)
    b0, b1, b2 = alpha, 0.0, -alpha
    a0, a1, a2 = 1.0 + alpha, -2.0 * cos_w0, 1.0 - alpha
    return np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])


def dyn_eq_gain(
    level_db: np.ndarray, threshold_db: float, ratio: float,
) -> np.ndarray:
    """Dynamic-EQ gain computer: band level (dB) -> gain (dB), cuts only.

    Exact roadmap formula ``G = min(0, −(E − T)·(1 − 1/R))``: below
    threshold the band is transparent (G = 0), above threshold it is cut by
    ``(E − T)·(1 − 1/R)`` dB. With ``ratio == 1.0`` the output is all zeros
    (the band is a bit-exact no-op).
    """
    x = np.asarray(level_db, dtype=np.float64)
    if ratio == 1.0:
        return np.zeros_like(x)
    return np.minimum(0.0, -(x - threshold_db) * (1.0 - 1.0 / ratio))


class DynamicEQ:
    """Orchestrates per-band filter -> joint detect -> dynamic cut -> mix.

    The per-band envelope is detected on the joint ``(L+R)/2`` mix so both
    channels share the same gain trajectory (stereo image preserved). In
    the neutral configuration (all ratios 1:1) the input is returned
    untouched, bit-exactly.
    """

    def __init__(self, sr: int, params: DynEqParams | None = None) -> None:
        self.sr = int(sr)
        self.params = params if params is not None else DynEqParams()
        self._sos: list[np.ndarray] = []
        for band in self.params.bands:
            self._validate_band(band)
            self._sos.append(_build_bell_sos(self.sr, band.freq_hz, band.q))

    def _validate_band(self, band: DynEqBandParams) -> None:
        if not (0.0 < band.freq_hz < self.sr / 2.0):
            raise ValueError(
                f"Band center must satisfy 0 < freq_hz < sr/2, got "
                f"freq_hz={band.freq_hz}, sr={self.sr}"
            )
        if band.ratio < 1.0:
            raise ValueError(
                f"Band ratio must be >= 1.0, got ratio={band.ratio}"
            )
        if band.q <= 0.0:
            raise ValueError(f"Band Q must be > 0, got q={band.q}")

    def _is_neutral(self) -> bool:
        """True when every band is transparent (ratio 1:1)."""
        return all(b.ratio == 1.0 for b in self.params.bands)

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply dynamic EQ, returning audio with input shape/dtype."""
        out, _ = self._process(audio)
        return out

    def process_with_diagnostics(
        self, audio: np.ndarray,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Like :meth:`process` but also returns per-band gain-reduction and
        gain trajectories (used by the Sprint 5 A/B verification)."""
        return self._process(audio)

    def _process(self, audio: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        x = np.asarray(audio)
        mono = x.ndim == 1
        x2 = x[np.newaxis, :] if mono else x
        n = x2.shape[-1]
        empty_diag: dict[str, Any] = {"gr_db": [], "gr_mean_db": [], "gain_db": []}
        if n == 0:
            return audio.copy(), empty_diag

        if self._is_neutral():
            # Below-threshold samples are already bit-exact (G = 0 ⇒ g_lin
            # = 1), but with all bands at ratio 1:1 we skip the filtering
            # pass entirely so the neutral path is exactly the input (null
            # test), mirroring the multiband shortcut.
            return audio.copy(), empty_diag

        orig_dtype = x2.dtype
        work = x2.astype(np.float64)
        y = work.copy()

        gr_trajectories: list[np.ndarray] = []
        gr_means: list[float] = []

        for band, sos in zip(self.params.bands, self._sos, strict=True):
            x_band = sosfilt(sos, work, axis=-1)
            joint = x_band.mean(axis=0)  # (L+R)/2 — one envelope, both channels
            level_db = _level_to_db(
                detect_envelope(joint, self.sr, band.attack_ms, band.release_ms)
            )
            g_db = dyn_eq_gain(level_db, band.threshold_db, band.ratio)
            g_lin = 10.0 ** (g_db / 20.0)
            y += (g_lin - 1.0)[np.newaxis, :] * x_band
            gr_trajectories.append(g_db)
            gr_means.append(float(np.mean(g_db)))

        out = y.astype(orig_dtype)
        if mono:
            out = out[0]

        diag = {
            "gr_db": gr_trajectories,
            "gr_mean_db": gr_means,
            "gain_db": gr_trajectories,
        }
        return out, diag


def dynamic_eq(
    audio: np.ndarray, sr: int, params: DynEqParams | None = None,
) -> np.ndarray:
    """Full dynamic-EQ pass (convenience wrapper).

    Neutral by default: with no ``params`` (all ratios 1:1) the input is
    returned bit-identical, so the stage is a safe no-op unless configured.
    """
    return DynamicEQ(sr, params).process(audio)
