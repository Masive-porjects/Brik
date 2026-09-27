"""16x oversampled soft-clipper (Sprint 3 — KClip/Ozone-style transient shaver).

Clipping generates harmonics; a hard or lightly-oversampled clip aliases them
back in-band. This clipper runs the shaper at 16x the input rate (via the
reusable :mod:`audiomind.processing.oversample` FIR pair) and applies a smooth
piecewise curve, so the delivered master's in-band aliasing stays below
``-90 dBFS`` for a full-scale 20 kHz sine.

Why 16x (roadmap corrected): at 4x the 9th harmonic of a 20 kHz full-scale
sine folds in-band at 3.6 kHz and no 4x filter can remove it — the floor for
any engaged clipper is ~ -60 to -65 dBFS. At 8x it moves to the 17th harmonic
fold (~ -87 dBFS). Only 16x (35th-harmonic fold, ~ -108 dBFS) reaches the
-90 dBFS pro standard with margin.

Shaper — piecewise erf knee:
  ``y(r) = r``                                    for ``|r| <= thr``
  ``y(r) = thr + (1 - thr) * erf(a*(r-thr)/(1-thr))``  for ``|r| > thr``

with ``a = sqrt(pi)/2`` so the slope matches the linear zone exactly at the
knee. ``erf`` is C-infinity, concave above the knee, and asymptotes to the
0 dBFS ceiling without any hard cap — fast harmonic roll-off (the key to low
aliasing) and no discontinuities. Below the threshold the curve is exactly
``y = x``: material that never reaches the knee is returned bit-identical
(bit-stable null path).

Placement: BEFORE the true-peak limiter. The clipper trims transient peaks
(2-4 dB) with controlled, band-safe distortion; the limiter then only has to
sustain the body — the KClip/Ozone "modern loudness" trick.

The sample rate is accepted for API parity with :func:`true_peak_limit`; the
memoryless shaper is sample-rate independent (the FIR cutoff is always
``sr/2`` at any rate).
"""

import numpy as np
from scipy.signal import firwin
from scipy.special import erf

from .oversample import oversample_up, oversample_down

#: Oversampling factor for the clipper (roadmap Sprint 3, corrected to 16x).
OVERSAMPLE = 16
#: Default knee threshold in dBFS when not specified by the caller.
DEFAULT_THRESHOLD_DB = -1.0
#: Above this the shaper counts as "engaged" even if the peak is marginal.
BYPASS_GAIN_EPS = 1e-9
#: Taps of the dedicated anti-aliasing FIR (per polyphase phase: 1537/16).
FIR_TAPS = 1537
#: Kaiser beta of the anti-aliasing FIR.
FIR_BETA = 16.0


def _antialiasing_fir(factor: int) -> np.ndarray:
    """High-quality windowed-sinc anti-aliasing FIR for ``factor`` oversampling.

    The module default (``("kaiser", 8.6)``) has only ~80 dB stopband, which
    caps the clipper's alias floor near -38 dBFS at 16x. This longer Kaiser-16
    FIR keeps the shaper's natural floor (~-108 dBFS) intact so the -90 dBFS
    acceptance passes with margin. Same FIR is used in both directions (the
    matched pair keeps the up/down round trip time-aligned).
    """
    return np.asarray(firwin(FIR_TAPS, 1.0 / factor, window=("kaiser", FIR_BETA)))


#: Cached FIR for the default factor.
_FIR = _antialiasing_fir(OVERSAMPLE)


def _erf_knee(up: np.ndarray, thr: float) -> np.ndarray:
    """Apply the piecewise erf knee in the oversampled domain.

    Below ``thr`` the output is exactly the input; above it the C-infinity
    erf blend rises toward the 0 dBFS ceiling. The knee slope at ``thr``
    equals 1 (continuous with the linear zone).
    """
    s = np.sign(up)
    m = np.abs(up)
    out = up.copy()
    mask = m > thr
    if not np.any(mask):
        return up
    a = np.sqrt(np.pi) / 2.0
    u = a * (m[mask] - thr) / (1.0 - thr)
    out[mask] = s[mask] * (thr + (1.0 - thr) * erf(u))
    return out


def soft_clip(
    audio: np.ndarray,
    sr: int,
    threshold_db: float = DEFAULT_THRESHOLD_DB,
    oversample: int = OVERSAMPLE,
) -> np.ndarray:
    """Apply the oversampled soft-clipper.

    The signal is oversampled by ``oversample`` (16x), shaped by the piecewise
    erf knee, and downsampled back to the original grid. When nothing exceeds
    ``threshold_db`` the input is returned untouched (bit-stable null path),
    so quiet material passes through bit-exactly.

    Args:
        audio: Audio array (channels, samples) or (samples,).
        sr: Sample rate (accepted for API parity with the limiter; the shaper
            is sample-rate independent).
        threshold_db: Knee threshold in dBFS. Must be below 0 dBFS (the shaper
            asymptotes to 0 dBFS). Below this level the curve is exactly
            ``y = x``; above it the erf knee engages.
        oversample: Oversampling factor (default 16x).

    Returns:
        Clipped audio, same shape and dtype as the input.
    """
    if threshold_db >= 0.0:
        raise ValueError(
            f"threshold_db must be < 0 dBFS (the shaper asymptotes to 0 dBFS), "
            f"got {threshold_db}"
        )
    x = np.asarray(audio)
    if x.ndim == 1:
        x2 = x[np.newaxis, :]
    else:
        x2 = x
    n = x2.shape[-1]
    if n == 0:
        return audio.copy()

    orig_dtype = x2.dtype
    work = x2.astype(np.float64)
    thr = 10.0 ** (threshold_db / 20.0)

    peak = float(np.max(np.abs(work)))
    if peak <= thr * (1.0 + BYPASS_GAIN_EPS):
        # Nothing reaches the knee: return the input as-is so the
        # below-threshold path is bit-exact (null test).
        return audio.copy()

    fir = _antialiasing_fir(oversample) if oversample != OVERSAMPLE else _FIR
    x_up = oversample_up(work, oversample, window=fir)
    y_up = _erf_knee(x_up, thr)
    y = oversample_down(y_up, oversample, n, window=fir)

    out = y.astype(orig_dtype)
    return out.reshape(audio.shape)
