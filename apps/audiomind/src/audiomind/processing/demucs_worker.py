"""Subprocess entry point that runs Demucs ONNX separation in isolation.

Why this module exists
----------------------
HTDemucs reserves a large amount of memory and ONNX Runtime / numpy do not
return it to the OS when the separation finishes. Measured on Railway (dev,
8 GB limit): the mastering chain peaks at ~170 MB, but after one mix job the
container is unable to serve another master — the kernel SIGKILLs it, which
surfaces as ``Killed`` in the logs and HTTP 502 to the client.

Running the separation in a child process fixes that at the root: when the
child exits, the kernel reclaims every byte it had. The parent (Uvicorn worker)
never grows.

This module is invoked as a module, never imported by the API:

    python -m audiomind.processing.demucs_worker INPUT OUTPUT_DIR MODEL PRECISION RESULT_JSON

The result travels through a JSON file rather than stdout, because ONNX Runtime
and demucs-onnx write progress noise to stdout and parsing it would be fragile.

The child imports nothing from the web layer on purpose: no FastAPI, no
Supabase client, no session store. Only numpy/soundfile/demucs_onnx.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

#: Contract mirrored by ``splitter._split_audio_in_process``. Keep both in sync.
STEM_NAMES = ("drums", "bass", "other", "vocals")


def separate(
    input_path: Path,
    output_dir: Path,
    model: str,
    precision: str,
) -> dict[str, Any]:
    """Do the heavy separation. Mirrors splitter._split_audio_in_process."""
    import demucs_onnx as demo
    import soundfile as sf

    input_path = input_path.resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    info = sf.info(str(input_path))
    sample_rate = int(info.samplerate)
    duration = info.duration

    # precision MUST match the weights baked into the image; a mismatch makes
    # demucs-onnx miss its cache and download ~300 MB inside the request.
    stems: dict[str, Any] = demo.separate(
        str(input_path),
        output_dir=str(output_dir),
        model=model,
        precision=precision,
        verbose=False,
        progress=False,
    )

    stem_paths: dict[str, str] = {}
    for name in STEM_NAMES:
        wav_path = output_dir / f"{name}.wav"
        if wav_path.exists():
            stem_paths[name] = str(wav_path)
        elif name in stems:
            # demucs-onnx may not have written it; write manually
            sf.write(str(wav_path), stems[name].T, sample_rate)
            stem_paths[name] = str(wav_path)

    return {
        "stems": stem_paths,
        "sample_rate": sample_rate,
        "duration_seconds": duration,
        "stem_audio_dir": str(output_dir),
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 5:
        print(
            "usage: python -m audiomind.processing.demucs_worker "
            "INPUT OUTPUT_DIR MODEL PRECISION RESULT_JSON",
            file=sys.stderr,
        )
        return 2

    input_path, output_dir, model, precision, result_json = args
    try:
        result = separate(Path(input_path), Path(output_dir), model, precision)
    except Exception:  # noqa: BLE001
        # Full traceback on stderr; the parent surfaces the tail to the log.
        traceback.print_exc()
        return 1

    Path(result_json).write_text(json.dumps(result), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())