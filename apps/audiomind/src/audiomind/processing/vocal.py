"""Vocal Sculptor Engine — VoiceChain Pro.

Professional vocal processing chain with 3 modules:
1. De-Esser — dynamic sibilance reduction (5-8 kHz)
2. Auto-Tune Pitch — formant-preserving pitch shift + shimmer
3. Optical Compressor — LA-2A-style compression (Cohesion)
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any
import numpy as np
import pedalboard
from pedalboard import (
    PeakFilter,
    HighShelfFilter,
    Compressor,
    PitchShift,
    Gain,
)
from pedalboard.io import AudioFile

# pedalboard's __init__ re-exports Pedalboard via a plain named import and
# defines no __all__; with implicit_reexport=False (mypy strict) the name is
# not treated as exported. Bind the module attribute explicitly — identical
# runtime behavior, satisfies mypy.
Pedalboard = pedalboard.Pedalboard

from audiomind.config import settings


class VocalParameters:
    """Vocal chain parameters — 3 control knobs.

    Each maps to a real-time control on the vintage rack UI.
    """

    def __init__(
        self,
        deesser_amount: float = 0.3,      # 0.0 - 1.0
        pitch_shift_semitones: float = 0.0,  # -3.0 - +3.0
        cohesion_amount: float = 0.4,      # 0.0 - 1.0
    ):
        self.deesser_amount = deesser_amount
        self.pitch_shift_semitones = pitch_shift_semitones
        self.cohesion_amount = cohesion_amount


def process_vocal(
    input_path: str | Path,
    output_path: str | Path,
    params: VocalParameters,
    progress_cb: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Process audio through the VoiceChain Pro vocal chain.

    Chain order: De-Esser → Pitch Shift → Optical Compressor

    Args:
        input_path: Source audio file (WAV/MP3).
        output_path: Where to write the processed WAV.
        params: Vocal chain parameters.

    Returns:
        ``{"output_path": str, "gain_reduction_db": float}``
    """
    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()

    def report(pct: float) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(min(1.0, max(0.0, pct / 100.0)))
        except Exception:
            pass

    # Read audio
    audio: np.ndarray
    sr: int
    with AudioFile(str(input_path)) as f:
        sr = int(f.samplerate)
        audio = f.read(f.frames)

    # Ensure stereo (channels, samples)
    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=0)

    original = audio.copy()
    report(5)

    # ── 1. De-Esser — Dynamic sibilance reduction ────────────────────
    if params.deesser_amount > 0.01:
        # Build a de-esser board: cut sibilant frequencies with a PeakFilter
        # Amount maps to gain reduction: 0 → 0 dB, 1 → -12 dB
        deesser_gain = -params.deesser_amount * 12
        deesser_board = Pedalboard([
            PeakFilter(
                cutoff_frequency_hz=7200,
                gain_db=deesser_gain,
                q=2.5,  # Narrow Q focuses on sibilance
            ),
        ])
        deessed = deesser_board(audio, sr)

        # Blend dry/wet based on amount (full band de-ess, mixed subtly)
        blend = params.deesser_amount * 0.6
        audio = audio * (1 - blend) + deessed * blend

    report(35)

    # ── 2. Pitch Shift / Auto-Tune Shimmer ─────────────────────────
    if abs(params.pitch_shift_semitones) > 0.05:
        pitch_board = Pedalboard([
            PitchShift(semitones=params.pitch_shift_semitones),
        ])
        shifted = pitch_board(audio, sr)

        # Blend: 50% wet/dry for natural shimmer (never 100% wet)
        blend = min(0.5, abs(params.pitch_shift_semitones) / 3 * 0.5)
        audio = audio * (1 - blend) + shifted * blend

    report(60)

    # ── 3. Optical Compressor — Cohesion ──────────────────────────
    if params.cohesion_amount > 0.01:
        # Map cohesion (0→1) to compressor parameters:
        #   0 → threshold=-30, ratio=1.5 (barely touching)
        #   1 → threshold=-18, ratio=4.0  (firm grip)
        threshold = -30 + params.cohesion_amount * 12
        ratio = 1.5 + params.cohesion_amount * 2.5

        comp_board = Pedalboard([
            Compressor(
                threshold_db=threshold,
                ratio=ratio,
                attack_ms=8,    # Optical-style: slower attack
                release_ms=180,  # Medium release for natural vocal glue
            ),
        ])
        audio = comp_board(audio, sr)

    report(85)

    # ── Safety — prevent clipping ─────────────────────────────────────
    peak = np.max(np.abs(audio))
    if peak > 0.99:
        audio = audio * (0.98 / peak)

    # ── Write output ──────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_f = AudioFile(str(output_path), "w", sr, audio.shape[0])
    out_f.write(audio)
    out_f.close()

    report(95)

    # Measure gain reduction (RMS difference)
    orig_rms = np.sqrt(np.mean(original ** 2))
    out_rms = np.sqrt(np.mean(audio ** 2))
    gr_db = 0.0
    if orig_rms > 1e-10 and out_rms > 1e-10:
        gr_db = 20 * np.log10(out_rms / orig_rms)

    return {
        "output_path": str(output_path.resolve()),
        "gain_reduction_db": float(round(gr_db, 1)),
    }
