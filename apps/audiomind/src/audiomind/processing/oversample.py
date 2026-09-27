"""Reusable polyphase oversampling for nonlinear DSP stages.

Oversampling raises the Nyquist frequency of the working signal so that
nonlinearities (limiting, clipping, saturation) generate far fewer in-band
aliasing products. Both directions use the SAME matched windowed-sinc FIR
through :func:`scipy.signal.resample_poly`, which keeps the up/down pair
complementary: upsampling and then downsampling with identical filters
returns a signal of the original length on the original grid.

Window choice — ``("kaiser", 8.6)``:
  ``resample_poly`` builds a polyphase anti-aliasing FIR from a windowed
  sinc (``sinc(2*fc*n)``, ``fc = 1/factor``) tapered by the requested
  Kaiser window. A Kaiser beta of 8.6 yields ~80 dB stopband attenuation,
  i.e. interpolation images and aliases land at least ~80 dB below the
  passband — well below the ~ -60 dBFS noise floor of a 16-bit master,
  while keeping the filter short enough (a few ``factor`` taps) to stay
  cheap at 8x oversampling. Higher betas sharpen the cutoff at the cost of
  longer filters; 8.6 is the standard "quality" point (the default used by
  most pro-audio resamplers).

Usage:
  Sprint 2 (True Peak Limiter) oversamples 8x through these helpers.
  Sprint 3 (Clipper) reuses the same module at 16x.
"""

import numpy as np
from scipy.signal import resample_poly

#: Default anti-aliasing window for the polyphase FIR. See module docstring.
DEFAULT_WINDOW: tuple[str, float] = ("kaiser", 8.6)


def oversample_up(
    audio: np.ndarray,
    factor: int,
    window: tuple[str, float] | np.ndarray = DEFAULT_WINDOW,
) -> np.ndarray:
    """Upsample ``audio`` by ``factor`` along the last axis.

    The interpolation is a quality polyphase windowed-sinc FIR; inter-sample
    values are accurate enough to expose true-peak overshoot that a plain
    sampled measurement hides.

    Args:
        audio: Audio array ``(channels, samples)`` or ``(samples,)``.
        factor: Oversampling factor (e.g. 8 for true-peak work, 16 for the
                soft-clipper).
        window: Kaiser window for the anti-aliasing FIR (module default is
                the quality choice, see module docstring).

    Returns:
        Upsampled audio of length ``ceil(n * factor)``.
    """
    return np.asarray(resample_poly(audio, factor, 1, axis=-1, window=window))


def oversample_down(
    audio: np.ndarray,
    factor: int,
    original_length: int,
    window: tuple[str, float] | np.ndarray = DEFAULT_WINDOW,
) -> np.ndarray:
    """Downsample ``audio`` back to the original sample grid.

    Uses the SAME FIR as :func:`oversample_up` (matched filters), so the
    pair is complementary. Output is trimmed/padded to exactly
    ``original_length`` samples along the last axis.

    Args:
        audio: Oversampled audio array ``(channels, samples)`` or
               ``(samples,)``.
        factor: Oversampling factor used on the way up.
        original_length: Number of samples to return (the pre-upsample
                         length).
        window: Kaiser window for the anti-aliasing FIR.

    Returns:
        Downsampled audio with ``original_length`` samples.
    """
    out = np.asarray(resample_poly(audio, 1, factor, axis=-1, window=window))
    if out.shape[-1] == original_length:
        return out
    if out.shape[-1] > original_length:
        return out[..., :original_length]
    pad = np.zeros(
        out.shape[:-1] + (original_length - out.shape[-1],), dtype=out.dtype
    )
    return np.concatenate([out, pad], axis=-1)
