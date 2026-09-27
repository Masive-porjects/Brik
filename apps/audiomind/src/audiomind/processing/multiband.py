"""Multiband compressor (Sprint 4 — Linkwitz-Riley LR4 crossovers + per-band detector).

The spectral-balance stage of the mastering chain (the "Ozone signature"):
splits the signal into three bands (low/mid/high) with fourth-order
Linkwitz-Riley crossovers, compresses each band independently against its
own threshold/ratio, and applies per-band makeup that compensates the
average gain reduction — so a muddy low-mid can be tamed without dulling
the highs, and vice-versa.

Crossover — Linkwitz-Riley 4th order (LR4):
  Each band edge is two identical 2nd-order Butterworth sections cascaded
  (``scipy.signal.butter``, Q = 1/√2). This is the definition of LR4: the
  LP and HP outputs are in phase at the corner and the magnitude sum is flat
  for every frequency (|H_LP + H_HP| = 1), verified by the Sprint 4
  acceptance test (sum flat within ±0.05 dB).

  Three bands (classic 150 Hz / 3 kHz, adjustable):
    low  = LR4-LP(f1)
    mid  = LR4-HP(f1) cascaded LR4-LP(f2)
    high = LR4-HP(f2)

Detector — per band, one-pole peak envelope with separate attack/release:
    env[n] = α·env[n−1] + (1−α)·|x[n]|        α = exp(−1/(τ·sr))
  rising uses the attack coefficient (short τ), falling uses the release
  one (long τ). The stereo pair is collapsed to a joint (L+R)/2 detector so
  both channels receive the same per-band gain and the image is preserved.

Gain computer — soft knee (standard compressor gain computer, the form of
the roadmap's ``G = T + (1/ratio − 1)·(x − T)``):
  below ``T − knee/2``  : ``G = x``                  (no reduction)
  inside the knee       : quadratic blend, continuous value and slope
  above ``T + knee/2``  : ``G = T + (x − T)/ratio``  (= ``x + (1/ratio − 1)(x − T)``)

Makeup — per-band constant gain equal to minus the band's mean gain
reduction (``makeup_db = −mean(GR_dB)``, clamped to ±12 dB), so each band
returns to its pre-compression average level instead of "shrinking".

Neutral mode: when every band has ratio 1:1 and no explicit makeup, the
stage is a bit-exact no-op (the input is returned untouched — the summed
band-split cannot be bit-identical to the input, so the split is skipped).
The engine inserts this stage gated by ``params.multiband_enabled`` with
ratio-1.0 defaults, so existing masters pass through unchanged.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.signal import butter, sosfilt

#: Default crossover frequencies (Hz) — the classic low/mid/high split.
DEFAULT_CROSSOVER_LOW_HZ = 150.0
DEFAULT_CROSSOVER_HIGH_HZ = 3000.0
#: Default per-band detector time constants (ms). Faster attack, slower
#: release so short transients are caught but the band breathes back.
DEFAULT_ATTACK_MS = 15.0
DEFAULT_RELEASE_MS = 150.0
#: Default soft-knee width in dB.
DEFAULT_KNEE_DB = 6.0
#: Detector level floor (dB) so silence never produces -inf.
FLOOR_DB = -120.0
#: Clamp (dB) on the automatic makeup gain per band.
MAKEUP_MAX_DB = 12.0


@dataclass(frozen=True)
class BandParams:
    """Per-band compressor settings.

    ``ratio == 1.0`` with ``makeup_db == 0.0`` makes the band transparent
    (part of the stage's bit-exact neutral path).
    """

    threshold_db: float = -20.0
    ratio: float = 1.0
    knee_db: float = DEFAULT_KNEE_DB
    attack_ms: float = DEFAULT_ATTACK_MS
    release_ms: float = DEFAULT_RELEASE_MS
    makeup_db: float = 0.0


@dataclass(frozen=True)
class MultibandParams:
    """Full multiband stage configuration (low/mid/high + crossovers).

    The defaults are NEUTRAL: all bands at ratio 1:1 with zero makeup, so
    the stage is a bit-exact bypass unless engaged.
    """

    crossover_low_hz: float = DEFAULT_CROSSOVER_LOW_HZ
    crossover_high_hz: float = DEFAULT_CROSSOVER_HIGH_HZ
    bands: tuple[BandParams, BandParams, BandParams] = field(
        default_factory=lambda: (BandParams(), BandParams(), BandParams())
    )
    auto_makeup: bool = True


class LinkwitzRiley4:
    """Fourth-order Linkwitz-Riley band-split filter bank.

    Each band edge is two identical 2nd-order Butterworth sections cascaded
    (this is exactly the LR4 definition — NOT a single 4th-order Butterworth,
    which is power-complementary but would NOT sum flat). See module docstring
    for the three-band topology.
    """

    def __init__(self, sr: int, low_hz: float, high_hz: float) -> None:
        nyquist = float(sr) / 2.0
        if not (0.0 < low_hz < high_hz < nyquist):
            raise ValueError(
                f"Crossovers must satisfy 0 < low < high < sr/2, got "
                f"low={low_hz}, high={high_hz}, sr={sr}"
            )
        self.sr = int(sr)
        self.low_hz = float(low_hz)
        self.high_hz = float(high_hz)
        self.band_sos = self._build_bands(low_hz / nyquist, high_hz / nyquist)

    @staticmethod
    def _lr4(edge_norm: float, btype: str) -> np.ndarray:
        """Cascade two 2nd-order Butterworth sections into one LR4 section."""
        section = butter(2, edge_norm, btype=btype, output="sos")
        return np.vstack([section, section])

    def _build_bands(self, f1: float, f2: float) -> list[np.ndarray]:
        """Build the low/mid/high SOS banks from normalized corner freqs."""
        lp1 = self._lr4(f1, "low")
        hp1 = self._lr4(f1, "high")
        lp2 = self._lr4(f2, "low")
        hp2 = self._lr4(f2, "high")
        mid = np.vstack([hp1, lp2])
        return [lp1, mid, hp2]

    def split(self, audio: np.ndarray) -> list[np.ndarray]:
        """Split audio into ``[low, mid, high]`` band signals.

        Input may be ``(samples,)`` or ``(channels, samples)``; bands are
        returned with the same number of dimensions.
        """
        x = np.asarray(audio)
        mono = x.ndim == 1
        work = x[np.newaxis, :] if mono else x
        bands = [sosfilt(sos, work, axis=-1) for sos in self.band_sos]
        if mono:
            return [b[0] for b in bands]
        return bands


def _alpha_from_tau_ms(tau_ms: float, sr: int) -> float:
    """One-pole smoothing coefficient for a time constant in milliseconds."""
    tau = max(tau_ms, 0.0) / 1000.0
    if tau <= 0.0:
        return 0.0
    return float(np.exp(-1.0 / (tau * float(sr))))


def detect_envelope(
    x: np.ndarray, sr: int, attack_ms: float = DEFAULT_ATTACK_MS,
    release_ms: float = DEFAULT_RELEASE_MS,
) -> np.ndarray:
    """One-pole peak envelope detector with separate attack/release.

    ``env[n] = α·env[n−1] + (1−α)·|x[n]|`` where ``α`` switches between the
    attack and release coefficients depending on whether the signal is rising
    or falling (fast attack, slow release per band). Runs sample-by-sample so
    the recursion matches the Sprint 4 spec exactly.
    """
    x = np.abs(np.asarray(x, dtype=np.float64))
    alpha_a = _alpha_from_tau_ms(attack_ms, sr)
    alpha_r = _alpha_from_tau_ms(release_ms, sr)
    b_a = 1.0 - alpha_a
    b_r = 1.0 - alpha_r
    env = np.empty_like(x)
    e = 0.0
    for i in range(x.shape[0]):
        xi = x[i]
        if xi >= e:
            e = alpha_a * e + b_a * xi
        else:
            e = alpha_r * e + b_r * xi
        env[i] = e
    return env


def _level_to_db(env: np.ndarray) -> np.ndarray:
    """Convert a linear envelope to dB with a floor at silence."""
    return np.asarray(np.maximum(20.0 * np.log10(np.maximum(env, 1e-12)), FLOOR_DB))


def gain_computer(
    level_db: np.ndarray, threshold_db: float, ratio: float, knee_db: float = DEFAULT_KNEE_DB,
) -> np.ndarray:
    """Soft-knee gain computer: detector level (dB) -> output level (dB).

    Below ``threshold_db - knee_db/2`` the output equals the input (no gain
    reduction). Above ``threshold_db + knee_db/2`` the hard-knee curve
    ``G = T + (x − T)/ratio`` applies — equivalent to the roadmap form
    ``G = x + (1/ratio − 1)·(x − T)``. Inside the knee a quadratic blend keeps
    both the value and the slope continuous. Gain reduction is ``G − x``
    (≤ 0 for ratio ≥ 1).

    With ``ratio == 1.0`` the output is returned bit-identical to the input.
    """
    x = np.asarray(level_db, dtype=np.float64)
    if ratio == 1.0:
        return x.copy()
    inv = 1.0 / ratio
    t_lo = threshold_db - 0.5 * knee_db
    t_hi = threshold_db + 0.5 * knee_db
    g = x.copy()
    if knee_db <= 0.0:
        mask = x > threshold_db
        g[mask] = threshold_db + (x[mask] - threshold_db) * inv
        return g
    hard = x >= t_hi
    soft = (x > t_lo) & (x < t_hi)
    g[hard] = threshold_db + (x[hard] - threshold_db) * inv
    if np.any(soft):
        d = x[soft] - t_lo
        g[soft] = x[soft] + (inv - 1.0) * d * d / (2.0 * knee_db)
    return g


def _makeup_from_gr(gr_db: np.ndarray) -> float:
    """Automatic makeup gain: minus the band's mean gain reduction, clamped.

    The exact rule: ``makeup_db = −mean(GR_dB)`` clamped to ``±MAKEUP_MAX_DB``.
    The band's average level returns to its pre-compression level, undoing
    the audible "shrink" of the master.
    """
    mean_gr = float(np.mean(gr_db))
    return float(np.clip(-mean_gr, -MAKEUP_MAX_DB, MAKEUP_MAX_DB))


class MultibandCompressor:
    """Orchestrates split -> per-band detect/compress/makeup -> recombine.

    The per-band envelope is detected on the joint ``(L+R)/2`` mix so both
    channels share the same gain trajectory (stereo image preserved). In the
    neutral configuration (all ratios 1:1, zero makeup) the input is returned
    untouched, bit-exactly.
    """

    def __init__(self, sr: int, params: MultibandParams | None = None) -> None:
        self.sr = int(sr)
        self.params = params if params is not None else MultibandParams()
        self.crossover = LinkwitzRiley4(
            self.sr, self.params.crossover_low_hz, self.params.crossover_high_hz
        )

    def _is_neutral(self) -> bool:
        """True when every band is transparent (ratio 1:1, no makeup)."""
        return all(b.ratio == 1.0 and b.makeup_db == 0.0 for b in self.params.bands)

    def process(self, audio: np.ndarray) -> np.ndarray:
        """Apply multiband compression, returning audio with input shape/dtype."""
        out, _ = self._process(audio)
        return out

    def process_with_diagnostics(self, audio: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        """Like :meth:`process` but also returns per-band gain-reduction and
        makeup data (used by the Sprint 4 A/B verification)."""
        return self._process(audio)

    def _process(self, audio: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
        x = np.asarray(audio)
        mono = x.ndim == 1
        x2 = x[np.newaxis, :] if mono else x
        n = x2.shape[-1]
        if n == 0:
            return audio.copy(), {"gr_db": [], "gr_mean_db": [], "makeup_db": []}

        if self._is_neutral():
            # The summed band-split can never be bit-identical to the input;
            # in the neutral configuration we skip the split entirely so the
            # ratio-1:1 path is bit-exact (null test).
            return audio.copy(), {"gr_db": [], "gr_mean_db": [], "makeup_db": []}

        orig_dtype = x2.dtype
        work = x2.astype(np.float64)
        bands = self.crossover.split(work)

        gr_trajectories: list[np.ndarray] = []
        gr_means: list[float] = []
        makeup: list[float] = []
        processed: list[np.ndarray] = []

        for band, bp in zip(bands, self.params.bands):
            joint = band.mean(axis=0)  # (L+R)/2 — one envelope, both channels
            level_db = _level_to_db(detect_envelope(joint, self.sr, bp.attack_ms, bp.release_ms))
            out_db = gain_computer(level_db, bp.threshold_db, bp.ratio, bp.knee_db)
            gr_db = out_db - level_db

            if self.params.auto_makeup:
                makeup_db = _makeup_from_gr(gr_db)
            else:
                makeup_db = bp.makeup_db

            gain = 10.0 ** ((gr_db + makeup_db) / 20.0)
            processed.append(band * gain[np.newaxis, :])
            gr_trajectories.append(gr_db)
            gr_means.append(float(np.mean(gr_db)))
            makeup.append(makeup_db)

        y = np.sum(processed, axis=0)
        out = y.astype(orig_dtype)
        if mono:
            out = out[0]

        diag = {
            "gr_db": gr_trajectories,
            "gr_mean_db": gr_means,
            "makeup_db": makeup,
        }
        return out, diag


def multiband_compress(
    audio: np.ndarray, sr: int, params: MultibandParams | None = None,
) -> np.ndarray:
    """Full multiband compression pass (convenience wrapper).

    Neutral by default: with no ``params`` (all ratios 1:1) the input is
    returned bit-identical, so the stage is a safe no-op unless configured.
    """
    return MultibandCompressor(sr, params).process(audio)
