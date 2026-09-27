"""Mid/Side spatial processing and reverb (Section 5.7).

Handles M/S encoding, per-preset spatial effects on the Side channel,
and phase correlation safety enforcement.
"""
import numpy as np
import pedalboard
from pedalboard import HighpassFilter, LowpassFilter, PeakFilter, Reverb
from scipy.signal import butter, sosfilt, sosfiltfilt

# pedalboard's __init__ re-exports Pedalboard via a plain named import and
# defines no __all__; with implicit_reexport=False (mypy strict) the name is
# not treated as exported. Bind the module attribute explicitly — identical
# runtime behavior, satisfies mypy.
Pedalboard = pedalboard.Pedalboard

#: Default side-channel high-pass corner (Hz) — Phase B (B1) anchor: sits
#: BELOW the engine's 120 Hz mono-compat collapse (stage 9) and ABOVE the
#: corrective 30 Hz master HPF (stage 2). Side content below ~100 Hz is
#: almost never musical — room/ambience mud that the width/reverb stages
#: would otherwise spread — and the mono collapse would mono-ize it anyway.
SIDE_HPF_DEFAULT_HZ = 100.0


def mid_side_encode(audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Encode L/R to Mid/Side matrix.

    Mono input (1, samples) is upmixed to stereo by duplicating the single
    channel (left = right = audio[0]) before encoding, so a mono track yields
    mid = the original signal and side = 0 (correct — mono has no side content).

    Args:
        audio: Audio array of shape (channels, samples). Accepts mono (1, ...)
            and stereo (2, ...).

    Returns:
        Tuple of (mid, side) arrays, each of shape (samples,).
    """
    if audio.shape[0] == 1:
        # Mono: duplicate the channel so side is identically zero.
        left = audio[0]
        right = audio[0]
    elif audio.shape[0] == 2:
        left = audio[0]
        right = audio[1]
    else:
        # Unexpected channel count — fall back to the first channel on both
        # sides rather than crashing downstream.
        mono = audio[0]
        left = mono
        right = mono
    mid = (left + right) / np.sqrt(2)
    side = (left - right) / np.sqrt(2)
    return mid, side


def mid_side_decode(mid: np.ndarray, side: np.ndarray) -> np.ndarray:
    """Decode Mid/Side back to stereo L/R.

    Args:
        mid: Mid channel, shape (samples,).
        side: Side channel, shape (samples,).

    Returns:
        Stereo array of shape (2, samples).
    """
    left = (mid + side) / np.sqrt(2)
    right = (mid - side) / np.sqrt(2)
    return np.stack([left, right])


def apply_side_hpf(
    side: np.ndarray, sr: int, cutoff_hz: float = SIDE_HPF_DEFAULT_HZ
) -> np.ndarray:
    """High-pass the SIDE channel (M/S low-end clean, Phase B — B1).

    Removes sub-bass mud below ``cutoff_hz`` from the decorrelated signal
    ONLY — the mid channel is never touched, so the low-end weight of the
    master stays. 4th-order Butterworth (24 dB/oct — steep enough to be
    effective at one octave below the corner), the same high-pass topology
    the engine's mono-compat stage uses for its lows (``mono.py``).

    Complementary to — never competing with — the <120 Hz mono collapse:
    that stage forces L/R below 120 Hz to mono center (side → 0) anyway;
    this stage cleans the side EARLY so the spatial processing (reverb,
    Haas, width) never spreads the room rumble, while the late mono
    collapse still guarantees mono compatibility.

    The engine gates this stage (``side_hpf_enabled``), so this pure
    filter has no neutral branch: when the gate is off the function is
    never called and the signal passes through untouched (bit-exact).
    """
    corner = float(cutoff_hz) / (float(sr) / 2.0)
    sos = butter(4, corner, btype="high", output="sos")
    # Cast back to the input dtype: sosfilt promotes to the coefficient
    # dtype (float64), but the stage contract is shape/dtype preservation
    # (the same convention the de-esser and multiband stages follow).
    return np.asarray(sosfilt(sos, side, axis=-1)).astype(side.dtype, copy=False)


def apply_claridad_spatial(side: np.ndarray, sr: int) -> np.ndarray:
    """Claridad preset: parallel reverb on Side + high-freq shelf boost.

    1. HPF @ 500Hz + LPF @ 12kHz on Side before reverb
    2. Small room reverb (room_size=0.25, wet ~2%)
    3. Parallel mix: blend wet with dry
    4. Shelf boost +1dB at 8kHz on processed Side
    """
    side_1ch = side.reshape(1, -1).astype(np.float32)

    # Input filtering before reverb
    filter_board = Pedalboard([
        HighpassFilter(cutoff_frequency_hz=500),
        LowpassFilter(cutoff_frequency_hz=12000),
    ])
    filtered = filter_board(side_1ch, sr)

    # Reverb
    reverb_board = Pedalboard([
        Reverb(
            room_size=0.25,
            damping=0.5,
            wet_level=0.02,
            dry_level=0.98,
            width=0.8,
        )
    ])
    wet = reverb_board(filtered, sr)

    # Parallel mix: 98% dry + 2% wet (wet_level already at 0.02,
    # dry_level at 0.98 handles the blend, but we reinforce)
    mixed = 0.98 * side_1ch + 0.02 * wet

    # High-frequency shelf boost: +1dB at 8kHz
    boost_board = Pedalboard([
        PeakFilter(cutoff_frequency_hz=8000, gain_db=1.0, q=0.5),
    ])
    mixed = boost_board(mixed, sr)

    return mixed.flatten().astype(np.float64)


def apply_cinematico_spatial(side: np.ndarray, sr: int) -> np.ndarray:
    """Cinemático preset: phase decorrelation + large room reverb on Side.

    1. Micro-delay 10ms on Side, mix 50/50 with original
    2. HPF @ 400Hz on Side
    3. Large room reverb (room_size=0.6, wet ~2.5%, decay ~1.5s)
    """
    # Phase decorrelation: 10ms micro-delay
    delay_samples = int(sr * 0.010)
    delayed = np.pad(side[:-delay_samples], (delay_samples, 0))
    decorrelated = 0.5 * side + 0.5 * delayed
    decorrelated_1ch = decorrelated.reshape(1, -1).astype(np.float32)

    # HPF before reverb
    filter_board = Pedalboard([
        HighpassFilter(cutoff_frequency_hz=400),
    ])
    filtered = filter_board(decorrelated_1ch, sr)

    # Large room reverb
    reverb_board = Pedalboard([
        Reverb(
            room_size=0.6,
            damping=0.3,
            wet_level=0.025,
            dry_level=0.975,
            width=0.9,
        )
    ])
    processed = reverb_board(filtered, sr)

    return processed.flatten().astype(np.float64)


def check_phase_correlation(audio: np.ndarray) -> float:
    """Measure stereo phase correlation between L and R channels.

    Returns a value between -1.0 (fully out of phase) and 1.0 (identical).
    """
    left = audio[0]
    right = audio[1]
    norm = np.linalg.norm(left) * np.linalg.norm(right) + 1e-10
    return float(np.dot(left, right) / norm)


def measure_stereo_correlation(
    audio: np.ndarray, frame_size: int = 4096, hop_size: int = 1024
) -> float | None:
    """Windowed-average L/R Pearson correlation of a stereo master.

    A single full-signal correlation hides local phase drift (a reversed
    section between two correlated sections averages out), so this measures
    the correlation per overlapping frame and averages the per-frame
    values — the delivery-report statistic for mono-compat safety.

    Returns None for non-stereo input (mono has no correlation to judge);
    the values sit in [-1, 1], where 1.0 = identical channels and < 0
    = polarity inversion.
    """
    if audio.ndim != 2 or audio.shape[0] != 2 or audio.shape[1] < 2:
        return None
    left = audio[0].astype(np.float64)
    right = audio[1].astype(np.float64)
    n = left.shape[0]
    frame_size = max(64, min(frame_size, n))
    frame_corrs: list[float] = []
    for start in range(0, n - frame_size + 1, hop_size):
        lf = left[start : start + frame_size]
        rf = right[start : start + frame_size]
        norm = np.linalg.norm(lf) * np.linalg.norm(rf) + 1e-10
        frame_corrs.append(float(np.dot(lf, rf) / norm))
    if not frame_corrs:
        return check_phase_correlation(audio)
    return float(np.mean(frame_corrs))


def safety_enforce_correlation(audio: np.ndarray, sr: int) -> np.ndarray:
    """Reduce Side channel until phase correlation >= 0.2.

    Iteratively attenuates Side by 10% per pass (max 10 iterations).
    If attenuation alone cannot fix correlation (e.g. Mid ≈ 0),
    falls back to blending toward mono from the decoded Left channel.
    """
    mid, side = mid_side_encode(audio)
    side_gain = 1.0

    for _ in range(10):
        attenuated_side = side * side_gain
        reconstructed = mid_side_decode(mid, attenuated_side)
        corr = check_phase_correlation(reconstructed)
        if corr >= 0.2:
            return reconstructed
        side_gain *= 0.9

    # Edge case: Mid ≈ 0, Side attenuation alone can't fix correlation.
    # Blend the decoded output toward a mono copy of the Left channel.
    best = mid_side_decode(mid, side * side_gain)
    mono_left = np.stack([best[0], best[0]])
    for blend in np.arange(0.1, 1.05, 0.1):
        candidate = best * (1.0 - blend) + mono_left * blend
        corr = check_phase_correlation(candidate)
        if corr >= 0.2:
            return candidate

    return mono_left


def apply_frequency_dependent_width(
    audio: np.ndarray,           # (2, samples) estéreo
    sr: int,
    width_low: float = 0.0,      # < 120 Hz → mono absoluto
    width_mid: float = 1.0,      # 120 Hz – 2.5 kHz → natural/estrecho
    width_high: float = 1.3,     # > 2.5 kHz → expansivo
    crossover_low: float = 120.0,
    crossover_high: float = 2500.0,
) -> np.ndarray:
    """
    Stereo Shuffler 3-bandas con crossover Linkwitz-Riley 4to orden (fase cero).
    
    División:
      - LOW (< 120 Hz): width = 0.0 (mono estricto para bajo/kick)
      - MID (120 Hz – 2.5 kHz): width = width_mid (inteligibilidad vocal)
      - HIGH (> 2.5 kHz): width = width_high (apertura y aire inmersivo)
    
    Implementación: LR4 (butter 4to orden) + sosfiltfilt (fase cero, float64).
    """
    if audio.shape[0] != 2:
        raise ValueError("apply_frequency_dependent_width requiere audio estéreo (2, samples)")

    audio_proc = audio.astype(np.float64)  # Precisión extendida para IIR sub-graves
    mid, side = mid_side_encode(audio_proc)
    nyq = sr / 2.0

    # Crossover LR4 (4to orden = 2 cascadas de Butterworth 2do orden)
    sos_low = butter(4, crossover_low / nyq, btype='lowpass', output='sos')
    sos_mid_low = butter(4, crossover_low / nyq, btype='highpass', output='sos')
    sos_mid_high = butter(4, crossover_high / nyq, btype='lowpass', output='sos')
    sos_high = butter(4, crossover_high / nyq, btype='highpass', output='sos')

    # Filtrado fase-cero (forward-backward)
    mid_low = sosfiltfilt(sos_low, mid)
    side_low = sosfiltfilt(sos_low, side) * width_low  # width_low=0.0 → mono

    mid_mid = sosfiltfilt(sos_mid_high, sosfiltfilt(sos_mid_low, mid))
    side_mid = sosfiltfilt(sos_mid_high, sosfiltfilt(sos_mid_low, side)) * width_mid

    mid_high = sosfiltfilt(sos_high, mid)
    side_high = sosfiltfilt(sos_high, side) * width_high

    # Recombinación coherente
    mid_out = mid_low + mid_mid + mid_high
    side_out = side_low + side_mid + side_high

    output = mid_side_decode(mid_out, side_out)
    return output.astype(audio.dtype, copy=False)
