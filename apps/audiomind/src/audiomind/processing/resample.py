"""Sample-rate conversion via the maintained ``soxr`` binding (libsoxr).

``soxr`` 1.x is the actively maintained libsoxr binding (``pysoxr`` is the
legacy one — do not use it). Quality "VHQ" = 95% bandwidth, high-quality
mode: transparent for delivery while keeping the filter short enough to be
cheap.

Channels-first audio (``(channels, samples)``) is transposed around
``soxr.resample`` (which works channel-last or 1D) so no channel data is
ever mixed. Output length follows libsoxr: ``round(n * dst / src)``.

The import is lazy on purpose: resampling is only needed when
``output_sr`` differs from the input rate, so heavy native bindings load
only in that branch. If the binding is missing the caller gets a loud,
clear ``RuntimeError`` — never a silent fallback.
"""

import numpy as np

#: libsoxr quality preset for delivery-grade resampling.
SOXR_QUALITY = "VHQ"


def resample_audio(audio: np.ndarray, src_sr: int, dst_sr: int) -> np.ndarray:
    """Resample ``audio`` from ``src_sr`` to ``dst_sr`` at VHQ quality.

    Args:
        audio: Audio array ``(channels, samples)`` or ``(samples,)``.
        src_sr: Source sample rate.
        dst_sr: Destination sample rate.

    Returns:
        Resampled audio with ``round(n * dst_sr / src_sr)`` samples on the
        last axis, same dimensionality as the input. Identity when
        ``src_sr == dst_sr`` (returns the input unchanged).

    Raises:
        RuntimeError: If the ``soxr`` binding cannot be imported.
    """
    if src_sr == dst_sr:
        return audio
    try:
        import soxr
    except ImportError as exc:  # pragma: no cover — defensive
        raise RuntimeError(
            "output_sr resampling requires 'soxr>=1.0.0' (libsoxr binding)"
        ) from exc

    x = np.asarray(audio)
    if x.ndim == 1:
        return np.asarray(soxr.resample(
            x.astype(np.float64), src_sr, dst_sr, quality=SOXR_QUALITY
        ))
    return np.asarray(soxr.resample(
        x.T.astype(np.float64), src_sr, dst_sr, quality=SOXR_QUALITY
    )).T