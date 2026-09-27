"""True Peak Limiter with 8x oversampling, explicit lookahead and adaptive release.

Prevents inter-sample clipping that occurs during D/A conversion and
lossy codec encoding (MP3, AAC, OGG).

The sampled peak lies: the true inter-sample peak of a digital signal can
exceed the largest sample by up to ~3 dB. This limiter therefore enforces
its ceiling on an 8x oversampled copy of the signal (via the reusable
``audiomind.processing.oversample`` FIR pair), so the delivered master
never exceeds the requested dBTP ceiling.

Architecture (standard pro-limiter topology):
  - Stage 1 — the sustained "body" limiter with a long, PROGRAM-DEPENDENT
    release. The release is picked from the input crest factor
    (:func:`calculate_crest_factor`): high crest (percussive material)
    selects a short release, low crest (dense tails/pads) a long one.
  - Stage 2 — the transient catcher: a fast lookahead limiter (L = 4 ms,
    ~30 ms release) that bounds any edge the slow stage lets through.
  - Hard clipper at 0 dBFS as the final safety net.

The lookahead is explicit and time-aligned. For every output sample the
gain is computed from a window that LOOKS AHEAD ``L`` samples, and that
gain is applied to the current sample::

    y[n] = x[n] * g[n]
    g[n] = min(1, c / max|x[n .. n+L]|, g[n-1] * decay)

where ``c`` is the ceiling in linear and ``decay`` is the per-sample
exponential release factor. Because the future window pre-attenuates
transients (instead of overshooting them), the ceiling is enforced without
clicking, the output stays time-aligned with the input, and the output
length equals the input length. Below the ceiling the gain is exactly 1 and
the limiter returns the input untouched (bit-stable null behavior).

Includes:
  - Codec pre-matching: automatically lowers ceiling for loud,
    heavily compressed tracks to prevent inter-sample clipping
    during lossy encoding (Spotify, Apple Music).
  - Crest factor analysis for dynamic ceiling decisions.

Target: -14 LUFS integrated with adaptive ceiling (-1.0 to -2.0 dBTP).
"""

import numpy as np
from scipy.ndimage import maximum_filter1d

from .oversample import oversample_up, oversample_down

#: Canonical true-peak oversampling factor (matches the 8x limiter).
TP_OVERSAMPLE = 8
#: Alias kept for backward compatibility with internal references.
OVERSAMPLE = TP_OVERSAMPLE
#: Lookahead of the fast stage in milliseconds (Sprint 2 spec: 3-5 ms).
LOOKAHEAD_MS = 4.0
#: Release time of the fast stage in milliseconds.
FAST_STAGE_RELEASE_MS = 30.0
#: dB recovered per release time during exponential gain recovery.
RELEASE_DB = 6.0
#: Crest-factor bounds (dB) of the adaptive-release mapping.
CREST_HIGH_DB = 14.0
CREST_LOW_DB = 6.0
#: Below this gain reduction the limiter counts as "not triggered" and the
#: input is passed through untouched (keeps the null path bit-exact).
BYPASS_GAIN_EPS = 1e-9
#: Internal safety margin (dB) below the requested ceiling.
#
# The ceiling is enforced on the oversampled (8x) signal; after downsampling
# back to the original rate and re-measuring at 8x, the delivered signal can
# still show up to ~0.12 dB of inter-sample ripple for dense, near-Nyquist
# content (e.g. full-scale noise). Limiting to ``ceiling - 0.15 dB`` absorbs
# that ripple so the delivered true peak never exceeds the REQUESTED ceiling.
CEILING_MARGIN_DB = 0.15


def true_peak_limit(
    audio: np.ndarray,
    sr: int,
    ceiling_db: float = -1.0,
    release_ms: int = 100,
) -> np.ndarray:
    """Apply true peak limiting with 8x oversampling and explicit lookahead.

    The two-stage gain (see module docstring) is computed per original-rate
    sample from the oversampled signal, so the interpolated peak is bounded
    by the ceiling, and is applied uniformly across channels to preserve the
    stereo image. When the material never reaches the ceiling the input is
    returned unchanged (bit-stable null path).

    Args:
        audio: Audio array (channels, samples) or (samples,).
        sr: Sample rate.
        ceiling_db: True peak ceiling in dB (default -1.0 dBTP).
        release_ms: Nominal release time in ms. Acts as the anchor for the
            program-dependent release: percussive material (high crest)
            uses ~90% of it, dense/tail material (low crest) scales it up
            to 4x. Adaptive release is always the effective behavior.

    Returns:
        Peak-limited audio, same shape and dtype as the input.
    """
    x = np.asarray(audio)
    if x.ndim == 1:
        x2 = x[np.newaxis, :]
    else:
        x2 = x
    n = x2.shape[-1]
    if n == 0:
        return audio.copy()

    work = x2.astype(np.float64)

    # Program-dependent release time from the input crest factor.
    effective_release_ms = _adaptive_release_ms(work, release_ms)

    sr_up = int(sr) * OVERSAMPLE
    ceiling = 10.0 ** ((ceiling_db - CEILING_MARGIN_DB) / 20.0)

    x_up = oversample_up(work, OVERSAMPLE)
    lookahead_up = max(1, int(round(LOOKAHEAD_MS * sr_up / 1000.0)))

    # Stage 1: long adaptive-release limiter (the "body").
    y_up, g1 = _lookahead_gain_stage(
        x_up, sr_up, ceiling, effective_release_ms, lookahead_up
    )
    # Stage 2: fast lookahead limiter (transient catcher).
    y_up, g2 = _lookahead_gain_stage(
        y_up, sr_up, ceiling, FAST_STAGE_RELEASE_MS, lookahead_up
    )

    # Streaming-safe route never hard-clips at 0 dBFS. Instead the final
    # safety net clamps at the REQUESTED ceiling level: for ceiling == 0 dB
    # this is identical to the old 0 dBFS clip; for negative ceilings it
    # enforces the requested ceiling (never 0 dBFS) so the delivered audio
    # cannot exceed the target dBTP.
    ceiling_lin = 10.0 ** (ceiling_db / 20.0)
    y_up = np.clip(y_up, -ceiling_lin, ceiling_lin)

    min_gain = min(float(np.min(g1)), float(np.min(g2)))
    if min_gain >= 1.0 - BYPASS_GAIN_EPS:
        # No measurable limiting was ever applied: return the input as-is so
        # the below-ceiling path is bit-exact (null test).
        return audio.copy()

    out = oversample_down(y_up, OVERSAMPLE, n)
    out = out.astype(work.dtype)
    return out.reshape(audio.shape)


def _adaptive_release_ms(audio: np.ndarray, nominal_ms: float) -> float:
    """Map the input crest factor to an exponential release time (ms).

    High crest (percussive) -> short release; low crest (tails, dense
    masters) -> long release, per the Sprint 2 spec (80-150 ms percussive,
    300 ms+ tails).
    """
    crest = calculate_crest_factor(audio)
    short_ms = nominal_ms * 0.9
    long_ms = nominal_ms * 4.0
    t = np.clip((CREST_HIGH_DB - crest) / (CREST_HIGH_DB - CREST_LOW_DB), 0.0, 1.0)
    return float(short_ms + t * (long_ms - short_ms))


def _lookahead_gain_stage(
    x_up: np.ndarray,
    sr_up: int,
    ceiling: float,
    release_ms: float,
    lookahead_up: int,
) -> tuple[np.ndarray, np.ndarray]:
    """One aligned-lookahead peak limiter stage on the oversampled signal.

    The gain recursion runs at the ORIGINAL sample rate (per oversampled
    segment) to keep it cheap: the per-segment target gain comes from the
    max of the oversampled lookahead window over that segment, so applying
    the constant segment gain to all 8 interpolated samples still bounds
    every interpolated peak by the ceiling.

    Returns ``(limited_signal, gain_trajectory)`` where the gain is one
    value per original sample.
    """
    factor = OVERSAMPLE
    window_max = _oversampled_lookahead_max(x_up, lookahead_up)  # (n,)
    target = ceiling / np.maximum(window_max, 1e-30)  # silence -> huge -> recover

    decay = 10.0 ** (RELEASE_DB / (20.0 * release_ms * sr_up / 1000.0))
    decay_seg = decay ** factor  # per original-rate sample

    n = target.shape[0]
    g = np.empty(n, dtype=np.float64)
    g[0] = min(1.0, target[0])
    for i in range(1, n):
        g[i] = min(1.0, target[i], g[i - 1] * decay_seg)

    gain_up = np.repeat(g, factor)
    return x_up * gain_up, g


def _oversampled_lookahead_max(x_up: np.ndarray, lookahead_up: int) -> np.ndarray:
    """Max |x| over each aligned lookahead window, one value per segment.

    For oversampled index ``m`` the window is ``[m, m + lookahead_up]``;
    the value returned per original-rate segment ``j`` is the max over the
    windows of its 8 interpolated samples, i.e. the max over
    ``|x|[8j .. 8j + 7 + lookahead_up]``. Signals beyond the end of the
    array count as zero (the lookahead shrinks at the tail). Implemented
    with a C ``maximum_filter1d`` (O(n) regardless of lookahead length).

    Returns:
        ``(n,)`` array, one ceiling target per original sample.
    """
    joint = np.abs(x_up).max(axis=0)  # joint across channels, (n_up,)
    size = lookahead_up + 1
    origin = -((size) // 2)
    padded = np.concatenate([joint, np.zeros(lookahead_up, dtype=joint.dtype)])
    slidemax = maximum_filter1d(padded, size=size, origin=origin, mode="constant")
    slidemax = slidemax[: joint.shape[0]]
    segments = np.lib.stride_tricks.sliding_window_view(slidemax, OVERSAMPLE)[:: OVERSAMPLE, :]
    return segments.max(axis=-1)


def measure_true_peak(
    audio: np.ndarray, sr: int, oversample: int = OVERSAMPLE
) -> float:
    """Measure true peak with oversampling for accurate inter-sample peak detection.

    Args:
        audio: Audio array (channels, samples) or (samples,).
        sr: Sample rate.
        oversample: Oversampling factor (default 8x).

    Returns:
        True peak in dBTP (``-inf`` for silence).
    """
    audio_up = oversample_up(np.asarray(audio), oversample)
    peak_linear = float(np.max(np.abs(audio_up)))
    if peak_linear <= 0:
        return -np.inf
    return float(20 * np.log10(peak_linear))


# ── Codec Pre-Matching ────────────────────────────────────────────────


def calculate_crest_factor(audio: np.ndarray) -> float:
    """Calculate crest factor (peak-to-RMS ratio) in dB.

    The crest factor indicates how "compressed" a signal is:
      - > 12 dB: highly dynamic (jazz, classical)
      - 8-12 dB: moderate dynamics (pop, rock)
      - < 6 dB:  heavily compressed, dense (EDM, modern trap)

    A low crest factor (< 6 dB) combined with a high-loudness target
    means the lossy codec will likely clip — the ceiling needs to
    be lowered to provide headroom for AAC/MP3 encoding.

    Args:
        audio: Audio array (channels, samples).

    Returns:
        Crest factor in dB. Larger values = more dynamic range.
    """
    peak = float(np.max(np.abs(audio)))
    if peak <= 0:
        return 0.0

    rms = float(np.sqrt(np.mean(audio**2)))
    if rms <= 0:
        return 40.0  # effectively silence, return safe high value

    return float(20.0 * np.log10(peak / rms))


def compute_codec_safe_ceiling(
    target_lufs: float,
    crest_factor_db: float,
    default_ceiling_db: float = -1.0,
    aggressive_threshold_lufs: float = -12.0,
    crest_threshold_db: float = 6.0,
) -> float:
    """Dynamically adjust the True Peak ceiling for lossy codec safety.

    When a track is mastered to high loudness (low LUFS target like -12)
    AND has low crest factor (heavily compressed), lossy encoders
    (AAC, Ogg Vorbis, MP3) introduce inter-sample clipping during
    the time/frequency domain transform.

    This function detects the dangerous combination and reduces the
    ceiling to provide extra headroom — matching the delivery specs
    from Spotify, Apple Music, and Tidal.

    Args:
        target_lufs: Target LUFS from the preset (e.g., -12, -13, -14).
        crest_factor_db: Measured crest factor in dB.
        default_ceiling_db: Default ceiling when no adjustment is needed.
        aggressive_threshold_lufs: LUFS threshold for "aggressive" loudness
                                   (default -12 LUFS — the loudest target
                                   the delivery now ever uses).
        crest_threshold_db: Crest factor threshold in dB.
                            Below this = heavily compressed (default 6.0 dB).

    Returns:
        Adjusted ceiling in dBTP (e.g., -1.0, -1.5, -2.0).
    """
    # Only adjust for loud targets (<= -12 LUFS is "aggressively loud")
    if target_lufs > aggressive_threshold_lufs:
        return default_ceiling_db

    # Only adjust for heavily compressed content
    if crest_factor_db >= crest_threshold_db:
        return default_ceiling_db

    # Scale ceiling reduction based on how compressed AND how loud
    # More compression + louder target = more ceiling reduction
    lufs_excess = aggressive_threshold_lufs - target_lufs  # e.g., -8 - (-10) = 2 dB
    crest_deficit = crest_threshold_db - crest_factor_db   # e.g., 6 - 4 = 2 dB

    # Combined reduction: at most -1.0 dB extra (ceiling goes to -2.0 dBTP)
    reduction = min(1.0, 0.3 * lufs_excess + 0.15 * crest_deficit)
    adjusted = default_ceiling_db - reduction

    return max(-2.5, adjusted)  # never go below -2.5 dBTP


def measure_lufs(audio: np.ndarray, sr: int) -> float:
    """
    Measure integrated LUFS per ITU-R BS.1770-4.

    Delegates to the compliant meter in ``audiomind.processing.loudness``
    (K-weighting, 400 ms blocks with 75% overlap, channel weights,
    absolute + relative gating). Returns a finite floor of -70 LKFS for
    silence/empty input so callers never receive ``-inf``.

    Args:
        audio: Audio array (channels, samples)
        sr: Sample rate

    Returns:
        Integrated LUFS (BS.1770-4)
    """
    from .loudness import measure_lufs as _compliant_measure_lufs

    return _compliant_measure_lufs(audio, sr)
