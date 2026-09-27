"""Stem isolation module — Demucs ONNX source separation.

Splits a full mix into 4 stems: drums, bass, other, vocals.
Uses demucs-onnx (ONNX Runtime) so it does NOT require PyTorch.
"""

from pathlib import Path
from typing import Any
import numpy as np
import soundfile as sf

from audiomind.config import settings

STEM_NAMES = ("drums", "bass", "other", "vocals")


def split_audio(
    input_path: str | Path,
    output_dir: str | Path | None = None,
    model: str = "htdemucs",
) -> dict[str, Any]:
    """Run Demucs source separation on an audio file.

    Args:
        input_path: Path to the audio file to separate.
        output_dir: Where to save stem WAV files. Defaults to
            ``settings.output_dir / {stemming_id}``.
        model: Demucs model name. ``"htdemucs"`` (4 stems, faster) or
            ``"htdemucs_ft"`` (bag-of-specialists, higher quality).

    Returns:
        ``{
            "stems": {"drums": "<path>", "bass": "<path>",
                      "other": "<path>", "vocals": "<path>"},
            "sample_rate": 44100,
            "duration_seconds": 123.0,
            "stem_audio_dir": "<path>",
        }``
    """
    import demucs_onnx as demo

    input_path = Path(input_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Determine output directory
    if output_dir is None:
        stem_id = input_path.stem
        output_dir = settings.output_dir / stem_id / "stems"
    else:
        output_dir = Path(output_dir).resolve()

    output_dir.mkdir(parents=True, exist_ok=True)

    # Read source audio metadata before processing
    info = sf.info(str(input_path))
    sample_rate = int(info.samplerate)
    duration = info.duration

    # Run demucs-onnx separation — write stems to disk
    stems: dict[str, np.ndarray] = demo.separate(
        str(input_path),
        output_dir=str(output_dir),
        model=model,
        verbose=False,
        progress=False,
    )

    # Build result paths
    stem_paths: dict[str, str] = {}
    for name in STEM_NAMES:
        wav_path = output_dir / f"{name}.wav"
        if wav_path.exists():
            stem_paths[name] = str(wav_path)
        elif name in stems:
            # demucs-onnx may not have written it; write manually
            wav_path = output_dir / f"{name}.wav"
            sf.write(str(wav_path), stems[name].T, sample_rate)
            stem_paths[name] = str(wav_path)

    return {
        "stems": stem_paths,
        "sample_rate": sample_rate,
        "duration_seconds": duration,
        "stem_audio_dir": str(output_dir),
    }
