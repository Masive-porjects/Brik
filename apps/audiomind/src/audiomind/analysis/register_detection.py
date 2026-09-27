"""Vocal register / f0 detection over the (vocal) signal — measurement only.

Feature: Eje A adaptive voice treatment (odd/tasks/voz-registro-f0-deteccion.md).
This is ONLY the detection/measurement stage — it never applies treatment, so
the master's neutral/bypass chain is untouched by construction.

Pipeline: ``librosa.pyin`` over the signal → f0 per frame → median f0 per
voiced phrase → register classification (grave/medio/agudo).

Honesty rules (product restriction, PROPUESTA_VOZ_ETEREA_VINTAGE_MOJADA.md):
- Every threshold here is a HIPOTHESIS to calibrate with real material, NOT a
  closed value. The f0 depends on the real signal that enters.
- When no credible voice is detected (silence, noise, instrumental), the
  result carries ``median_f0_hz=None`` and ``register=None`` — the backend
  NEVER invents a register.
- The register is reported as musical range (grave/medio/agudo), never as a
  gender label: f0 does not determine gender ("no sesgar").
- To keep pyin affordable, the analysis downsamples to
  ``REGISTER_ANALYSIS_SR_HZ`` (human voice f0 lives in 70–600 Hz; the higher
  the sample rate, the slower pyin grows — measured ~13 s vs ~0.2 s per 10 s).
"""
import librosa
import numpy as np

# ── HIPOTHESIS constants (a calibrar con material real — sin fuente) ─────
# Register cutoffs: classic speaking-f0 range of sung/spoken voices (very
# roughly male ~85–180 Hz, female ~165–255 Hz) plus the ~200 Hz cut floated
# in the product proposal. None of this is a closed value.
REGISTER_LOW_CUTOFF_HZ = 165.0  # HIPOTHESIS: below -> "grave"
REGISTER_HIGH_CUTOFF_HZ = 255.0  # HIPOTHESIS: above -> "agudo"

# pyin analysis band for the voice fundamental (70 Hz C#2 .. 600 Hz D#5).
PYIN_FMIN_HZ = 70.0
PYIN_FMAX_HZ = 600.0

# Internal analysis rate: enough for voice f0 and keeps pyin fast.
REGISTER_ANALYSIS_SR_HZ = 11025

# Voice-presence guard (HIPOTHESIS): below this voiced-frame ratio the signal
# carries no credible voice. Measured evidence (2026-09-22): white noise
# ~0.14 float, ~0.31 after 16-bit PCM quantization (pyin locks onto the
# periodic quantization pattern); a synthetic voiced signal ~1.0, a real
# voice with silent gaps ~0.8. The 0.5 cut separates them with margin and
# stays a calibratable bound, not a closed value.
MIN_VOICED_RATIO = 0.50

# Shortest phrase kept (~230 ms at hop 512 / 11025 Hz): pyin blips are not
# phrases. HIPOTHESIS bound, calibratable.
MIN_PHRASE_FRAMES = 5

_REGISTER_LABELS = ("grave", "medio", "agudo")


class RegisterDetection:
    """Result of measuring the vocal register of a signal.

    Attributes:
        median_f0_hz: Median of the per-phrase f0 medians (dominant f0), or
            None when no credible voice is present.
        phrase_medians_hz: Median f0 of each voiced phrase (robust to
            octave jumps and frame-level pyin errors).
        voiced_ratio: Fraction of frames pyin marked voiced (0..1).
        register: "grave" | "medio" | "agudo" or None (no voice detected).
    """

    def __init__(
        self,
        median_f0_hz: float | None,
        phrase_medians_hz: list[float],
        voiced_ratio: float,
        register: str | None,
    ) -> None:
        self.median_f0_hz = median_f0_hz
        self.phrase_medians_hz = phrase_medians_hz
        self.voiced_ratio = voiced_ratio
        self.register = register


def median_f0_per_phrase(
    f0_hz: np.ndarray, voiced: np.ndarray, min_frames: int = MIN_PHRASE_FRAMES
) -> list[float]:
    """Median f0 of each contiguous voiced phrase.

    A phrase is a run of voiced frames (``voiced`` True and finite f0) of at
    least ``min_frames`` frames. Within a phrase, the MEDIAN (not the mean)
    is used, so occasional octave-jump frames (2x/0.5x f0) or single-frame
    pyin errors cannot drag the reported value.

    Args:
        f0_hz: Per-frame fundamental (NaN = unvoiced/undefined).
        voiced: Per-frame voicing decision from pyin.
        min_frames: Minimum phrase length in frames.

    Returns:
        One median per detected phrase; empty when nothing credible exists.
    """
    valid = voiced & np.isfinite(f0_hz)
    medians: list[float] = []
    start: int | None = None

    for idx, is_valid in enumerate(valid):
        if is_valid and start is None:
            start = idx
        elif not is_valid and start is not None:
            segment = f0_hz[start:idx]
            if len(segment) >= min_frames:
                medians.append(float(np.nanmedian(segment)))
            start = None

    if start is not None:
        segment = f0_hz[start:]
        if len(segment) >= min_frames:
            medians.append(float(np.nanmedian(segment)))

    return medians


def classify_register(median_f0_hz: float | None) -> str | None:
    """Classify register from the dominant f0 median (HIPOTHESIS thresholds).

    None in, None out: no credible voice -> no invented register.
    """
    if median_f0_hz is None:
        return None
    if median_f0_hz < REGISTER_LOW_CUTOFF_HZ:
        return _REGISTER_LABELS[0]  # grave
    if median_f0_hz <= REGISTER_HIGH_CUTOFF_HZ:
        return _REGISTER_LABELS[1]  # medio
    return _REGISTER_LABELS[2]  # agudo


def detect_vocal_register(y: np.ndarray, sr: int) -> RegisterDetection:
    """Measure the vocal register of an audio signal.

    Runs pyin over the signal (the vocal stem when the mix engine analyzes
    per-stem files), aggregates per phrase, and classifies the register.
    Silence, noise or any signal without a credible voice yields
    ``register=None`` — never an invented value.

    Args:
        y: Mono audio samples.
        sr: Sample rate of ``y``.

    Returns:
        RegisterDetection with the measured values.
    """
    if y.size == 0 or not np.any(y):
        return RegisterDetection(None, [], 0.0, None)

    if sr != REGISTER_ANALYSIS_SR_HZ:
        y_analysis = librosa.resample(
            y, orig_sr=sr, target_sr=REGISTER_ANALYSIS_SR_HZ
        )
    else:
        y_analysis = y

    f0, voiced, _ = librosa.pyin(
        y_analysis,
        fmin=PYIN_FMIN_HZ,
        fmax=PYIN_FMAX_HZ,
        sr=REGISTER_ANALYSIS_SR_HZ,
    )
    voiced = voiced & np.isfinite(f0)

    voiced_ratio = float(np.mean(voiced)) if len(voiced) > 0 else 0.0
    if voiced_ratio < MIN_VOICED_RATIO or not np.any(voiced):
        # No credible voice: honest None instead of a guessed register.
        return RegisterDetection(None, [], voiced_ratio, None)

    phrase_medians = median_f0_per_phrase(f0, voiced)
    if not phrase_medians:
        return RegisterDetection(None, [], voiced_ratio, None)

    # Median-of-medians: one dominant f0 per signal, robust to octave jumps
    # and to a single anomalous phrase.
    dominant_f0 = float(np.median(phrase_medians))
    return RegisterDetection(
        median_f0_hz=dominant_f0,
        phrase_medians_hz=phrase_medians,
        voiced_ratio=voiced_ratio,
        register=classify_register(dominant_f0),
    )