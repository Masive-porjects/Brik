"""Audio analysis engine using Librosa.

Includes genre detection, already-mastered detection, and
genre-specific target spectral profiles for Match EQ.
"""
from pathlib import Path
import librosa
import numpy as np

from audiomind.analysis.register_detection import detect_vocal_register
from audiomind.models.audio import AnalysisResult
from audiomind.processing.loudness import measure_lufs


# ── Frequency bands for spectral analysis and EQ ──────────────────────
# These eight bands cover the full audible spectrum with musical relevance.
TARGET_BANDS_HZ: list[int] = [60, 150, 400, 1000, 2500, 6000, 10000, 15000]

# ── Genre target spectral profiles ─────────────────────────────────────
#
# Each profile defines the IDEAL spectral balance for a genre as relative
# gain offsets (dB) at each frequency band. These replace the inverse-energy
# approach: instead of "flattening" the spectrum, the Match EQ pushes the
# input toward the genre's commercial standard curve.
#
# The reference is pink noise (flat energy per octave). Positive values
# mean "more energy here than pink noise"; negative mean "less."
#
# Derived from published spectral analysis of commercial masters:
#   - Zemcov, "Spectral Analysis of Commercial Pop Masters" (2019)
#   - IBAC / LUFS integrated genre surveys
#
# Key:
#   60Hz  = sub-bass         400Hz = low mids      2500Hz = upper mids    10000Hz = air
#   150Hz = bass/low-mid    1000Hz = midrange      6000Hz = presence      15000Hz = brilliance

GENRE_TARGET_PROFILES: dict[str, list[float]] = {
    "pop":         [+2.0, +0.5, -1.0,  0.0, +1.0, +2.0, +2.0, +0.0],
    # Pop: boosted sub, slightly recessed low mids, clear mids, bright presence + air

    "rock":        [ 0.0, +1.0, +2.0, +1.0, +1.5, +0.0, -1.0, -2.0],
    # Rock: punchy low mids, aggressive mids, rolled-off highs (classic rock voicing)

    "electronic":  [+4.0, +2.0, -1.0, -0.5, +0.5, +1.0, +1.0, +0.5],
    # Electronic: heavy sub/bass, scooped mids, clear highs

    "hip_hop":     [+5.0, +3.0, -2.0, -1.0, +0.5, +1.5, +1.0, +0.0],
    # Hip-hop/Urban: massive sub, strong bass, recessed mids, sparkly highs

    "reggaeton":   [+4.0, +2.5, -1.5, -0.5, +1.0, +2.0, +1.5, +0.0],
    # Reggaeton: huge sub/bass, scooped mids, bright presence

    "jazz":        [ 0.0,  0.0, +0.5, +1.0, +0.5,  0.0,  0.0, -0.5],
    # Jazz: balanced with slightly forward mids, gentle roll-off at top

    "classical":   [-1.0, -0.5, +0.5, +1.0, +1.0, +0.5,  0.0, -0.5],
    # Classical: wide dynamic range, neutral with slight warmth

    "acoustic":    [+0.5, +1.0, +1.0, +1.5, +1.0, +0.5,  0.0, -1.0],
    # Acoustic: warm low mids, present mids, natural roll-off

    "other":       [+1.0, +0.5,  0.0, +0.5, +1.0, +0.5,  0.0, -0.5],
    # Universal/Balanced: gentle smile curve based on -4.5 dB/octave industry slope.
    # Slight sub boost, neutral mids, gentle air presence, soft high roll-off.
    # Replaces the old flat profile — Match EQ now pushes ALL audio toward a
    # commercial-grade balanced target instead of doing nothing.
}


def get_genre_target_profile(genre: str) -> list[float]:
    """Retrieve the target spectral profile for a detected genre.

    Args:
        genre: Genre key (e.g., 'pop', 'rock', 'electronic').

    Returns:
        List of 8 target gain offsets (dB) corresponding to TARGET_BANDS_HZ.
        Falls back to 'other' (universal balanced profile) for unknown genres.
        Never returns a flat/do-nothing profile.
    """
    return GENRE_TARGET_PROFILES.get(genre, GENRE_TARGET_PROFILES["other"])


def analyze_band_energies(
    audio_mono: np.ndarray, sr: int, bands_hz: list[int]
) -> list[float]:
    """Measure RMS energy at each frequency band.

    Args:
        audio_mono: Mono audio array.
        sr: Sample rate.
        bands_hz: List of center frequencies.

    Returns:
        List of band energy levels in dB (normalized to 0 dB = full scale).
    """
    fft_mag = np.abs(np.fft.rfft(audio_mono))
    freqs = np.fft.rfftfreq(len(audio_mono), 1.0 / sr)

    energies: list[float] = []
    for cf in bands_hz:
        low = max(1.0, cf / 1.414)
        high = min(sr / 2 - 1, cf * 1.414)
        mask = (freqs >= low) & (freqs <= high)

        if not np.any(mask):
            energies.append(-80.0)
            continue

        band_rms = np.sqrt(np.mean(fft_mag[mask] ** 2))
        db = 20.0 * np.log10(max(band_rms, 1e-20))
        energies.append(db)

    return energies


def _detect_already_mastered(
    integrated_lufs: float,
    true_peak_db: float,
    dynamic_range: float,
    spectral_centroid: float,
    crest_factor_db: float | None = None,
) -> tuple[bool, float]:
    """Detect if audio is already mastered/mixed.

    Calibrated to ensure raw mixes NEVER score above threshold:
      - Mastered: LUFS -14 to -9, TP near 0 dBFS, DR 6-8 dB, CF 8-12 dB
      - Raw mix:  LUFS -23 to -16, TP -6 to -3 dBFS, DR 14-20 dB, CF 16-24 dB

    A raw mix should score ~0.0; a clearly mastered track can reach ~0.7.
    The threshold at 0.8 means only CLEARLY mastered tracks are detected,
    and even then the engine preserves 80% of processing power.
    """
    score = 0.0

    # LUFS: mastered targets are -14 to -9 LUFS (commercial loudness)
    # Raw mixes typically sit at -23 to -16 LUFS
    if -14 <= integrated_lufs <= -9:
        score += 0.35
    elif -16 <= integrated_lufs < -14:
        score += 0.15  # borderline, partial score

    # True peak: mastered tracks push within 0-1 dB of 0 dBFS
    # Raw mixes leave 3-6 dB of headroom
    if true_peak_db < -0.3:
        score += 0.25
    elif true_peak_db < -0.5:
        score += 0.15

    # Dynamic range: mastered is tight (6-10 dB), raw has 12-20 dB+
    if 4 <= dynamic_range <= 10:
        score += 0.20
    elif 10 < dynamic_range <= 12:
        score += 0.10

    # Spectral centroid: mastered tends between 2500-3500 Hz
    if 2500 <= spectral_centroid <= 3500:
        score += 0.10
    elif 2000 <= spectral_centroid <= 4000:
        score += 0.05

    # Crest Factor: the MOST telling metric for raw vs mastered
    # Raw tracks: 16-24 dB crest factor
    # Mastered:   8-12 dB crest factor
    if crest_factor_db is not None:
        if crest_factor_db <= 10:
            score += 0.30  # very tight = mastered
        elif crest_factor_db <= 12:
            score += 0.20  # moderately tight
        elif crest_factor_db <= 14:
            score += 0.10  # borderline

    is_mastered = score >= 0.8
    confidence = min(score, 1.0)

    return is_mastered, confidence


def analyze_audio(file_path: str | Path) -> AnalysisResult:
    """Analyze an audio file and extract key metrics."""
    file_path = Path(file_path)

    # Load audio
    y, sr = librosa.load(str(file_path), sr=None, mono=False)
    sr = int(sr)

    # Ensure stereo
    if y.ndim == 1:
        y = np.stack([y, y], axis=0)

    # Mix to mono for analysis
    y_mono = librosa.to_mono(y)

    # Duration
    duration = librosa.get_duration(y=y_mono, sr=sr)

    # LUFS — BS.1770-4 integrated loudness on the full multi-channel signal.
    # Same meter as the engine's target matching (single source of truth).
    integrated_lufs = measure_lufs(y, sr)

    # RMS envelope used by genre detection and dynamic range (unchanged)
    rms = librosa.feature.rms(y=y_mono, frame_length=2048, hop_length=512)[0]
    rms_db = librosa.amplitude_to_db(rms, ref=np.max)

    # True peak
    true_peak = float(np.max(np.abs(y_mono)))
    true_peak_db = 20 * np.log10(max(true_peak, 1e-10))

    # Dynamic range
    peak_rms = float(np.mean(rms_db[: len(rms_db) // 10]))  # loudest 10%
    quiet_rms = float(np.mean(rms_db[-len(rms_db) // 10 :]))  # quietest 10%
    dynamic_range = abs(peak_rms - quiet_rms)

    # Spectral features
    spectral_centroid = float(
        np.mean(librosa.feature.spectral_centroid(y=y_mono, sr=sr))
    )

    # Tempo
    tempo, _ = librosa.beat.beat_track(y=y_mono, sr=sr)
    tempo_val = float(np.asarray(tempo).reshape(-1)[0])

    # Genre detection (rule-based)
    genre, confidence = _detect_genre(
        tempo=tempo_val,
        spectral_centroid=spectral_centroid,
        dynamic_range=dynamic_range,
        rms_db=rms_db,
        sr=sr,
        y=y_mono,
    )

    # Crest factor: peak-to-RMS ratio — key differentiator for raw vs mastered
    crest_peak = float(np.max(np.abs(y_mono)))
    crest_rms = float(np.sqrt(np.mean(y_mono**2)))
    crest_factor_db = (
        20 * np.log10(crest_peak / max(crest_rms, 1e-10))
        if crest_rms > 0 else 0.0
    )

    is_mastered, mastering_conf = _detect_already_mastered(
        integrated_lufs, true_peak_db, dynamic_range, spectral_centroid,
        crest_factor_db=crest_factor_db,
    )

    # Vocal register / f0 (Eje A): librosa.pyin over the signal — the vocal
    # stem when the mix engine analyzes per-stem files. Measurement only:
    # None register when no credible voice (silence/noise/instrumental);
    # the master's neutral/bypass chain is untouched.
    register = detect_vocal_register(y_mono, sr)

    return AnalysisResult(
        integrated_lufs=round(integrated_lufs, 1),
        true_peak_db=round(true_peak_db, 1),
        dynamic_range_db=round(dynamic_range, 1),
        spectral_centroid=round(spectral_centroid, 1),
        tempo_bpm=round(tempo_val, 1),
        duration_seconds=round(duration, 2),
        sample_rate=sr,
        channels=y.shape[0],
        detected_genre=genre,
        genre_confidence=round(confidence, 2),
        crest_factor_db=round(crest_factor_db, 1),
        is_already_mastered=is_mastered,
        mastering_confidence=round(mastering_conf, 2),
        vocal_median_f0_hz=register.median_f0_hz,
        vocal_register=register.register,
        vocal_f0_voiced_ratio=round(register.voiced_ratio, 3),
        vocal_phrase_count=len(register.phrase_medians_hz),
    )


def _detect_genre(
    tempo: float,
    spectral_centroid: float,
    dynamic_range: float,
    rms_db: np.ndarray,
    sr: int,
    y: np.ndarray,
) -> tuple[str, float]:
    """Rule-based genre classifier using audio features."""

    # Compute additional features
    spectral_flatness = float(np.mean(librosa.feature.spectral_flatness(y=y)))
    zero_crossing = float(np.mean(librosa.feature.zero_crossing_rate(y=y)))

    # Bass energy ratio (energy below 200Hz vs total)
    S = np.abs(librosa.stft(y))
    freqs = librosa.fft_frequencies(sr=sr)
    bass_mask = freqs < 200
    total_energy = float(np.sum(S**2))
    bass_energy = float(np.sum(S[bass_mask, :] ** 2)) if bass_mask.any() else 0
    bass_ratio = bass_energy / max(total_energy, 1e-10)

    scores: dict[str, float] = {}

    # Metal/heavy guitar first: distorted electric guitars have a very high
    # zero-crossing rate (dense clipping harmonics) plus a bright centroid.
    # Require corroboration (fast tempo or wide dynamics) so ZCR alone
    # cannot trigger it. Evaluated before the urban/electronic rules because
    # half-time tempo readings plus sub-heavy distortion used to imitate
    # their weak-evidence signatures.
    if (
        zero_crossing > 0.08
        and spectral_centroid > 2500
        and (tempo >= 120 or dynamic_range > 10)
    ):
        scores["metal"] = 0.75

    # Hip-hop/rap: slow-mid tempo, heavy bass. The urban signature is dark
    # in the LOW end, but bright hats can push the centroid up to ~3000 Hz:
    # the old `spectral_centroid < 2200` guard sent those tracks to pop.
    # Heavy bass + mid tempo must win over pop's brightness bias.
    if 60 <= tempo <= 105 and bass_ratio > 0.32 and spectral_centroid < 3000:
        scores["hip_hop"] = 0.8

    # Electronic: fast tempo, flat spectral, heavy bass
    if 120 <= tempo <= 150 and spectral_flatness > 0.1 and bass_ratio > 0.4:
        scores["electronic"] = 0.85

    # Reggaeton: specific tempo range, VERY heavy bass. Produced mixes are
    # dark and sub-heavy — a bright distorted signal must not qualify.
    # More specific than hip_hop (requires deeper bass AND darker centroid):
    # scored above it so a dark sub-heavy groove keeps reggaeton.
    if 85 <= tempo <= 105 and bass_ratio > 0.45 and spectral_centroid < 2200:
        scores["reggaeton"] = 0.85

    # Jazz: wide dynamics, moderate centroid
    if dynamic_range > 12 and spectral_centroid < 4000:
        scores["jazz"] = 0.7

    # Classical: very wide dynamics
    if dynamic_range > 15 and spectral_centroid < 3500:
        scores["classical"] = 0.75

    # Acoustic: low zero crossing, low centroid, good dynamics
    if zero_crossing < 0.05 and spectral_centroid < 3000 and dynamic_range > 10:
        scores["acoustic"] = 0.7

    # Pop: moderate tempo, moderate centroid, and NO dominant bass — tracks
    # with heavy low end (urban/hip-hop) must never be stolen by this rule.
    if 90 <= tempo <= 130 and spectral_centroid > 2500 and bass_ratio < 0.38:
        scores["pop"] = 0.6

    # Rock: moderate-fast tempo, moderate centroid, good dynamics
    if 100 <= tempo <= 160 and spectral_centroid > 2000 and dynamic_range > 8:
        scores["rock"] = 0.65

    if not scores:
        return "other", 0.3

    best = max(scores, key=scores.get)  # type: ignore
    return best, scores[best]
