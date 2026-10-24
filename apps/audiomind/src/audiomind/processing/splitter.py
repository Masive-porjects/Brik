"""Stem isolation module — Demucs ONNX source separation.

Splits a full mix into 4 stems: drums, bass, other, vocals.
Uses demucs-onnx (ONNX Runtime) so it does NOT require PyTorch.

Demucs runs in a **child process** by default. HTDemucs reserves a lot of
memory that neither ONNX Runtime nor numpy hands back to the OS, which made the
Uvicorn worker unable to serve a mastering job right after a mix: the kernel
SIGKILLed it (``Killed`` in the logs, HTTP 502 to the client) even though the
mastering chain only peaks at ~170 MB. A child process gets its memory
reclaimed on exit, so the web worker never grows.

Set ``AUDIOMIND_DEMUCS_ISOLATED=false`` to run in-process (local debugging, or
tests that stub the model). ``split_audio`` keeps its signature either way.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from audiomind.config import settings

logger = logging.getLogger(__name__)

STEM_NAMES = ("drums", "bass", "other", "vocals")

#: Stems cache. Separation costs ~28 s per 10 s of audio (measured), and
#: ``build_mix`` calls ``split_audio`` on EVERY render — without this, each
#: iteration of an agentic mix loop pays Demucs again from scratch.
_MANIFEST_NAME = "_stems_manifest.json"


def _sha256_file(path: Path) -> str:
    """Content hash of the input, chunked so a big file never lands in RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cached_result(
    input_path: Path, output_dir: Path, model: str
) -> dict[str, Any] | None:
    """Return a stored separation, or ``None`` when it cannot be trusted.

    Every doubt answers ``None``: absent or corrupt manifest, a different
    model or precision, a different input, or a stem that vanished from disk.
    Handing back another song's stems would be silent corruption, so the cache
    proves identity rather than assuming it from the output directory.
    """
    if not input_path.is_file():
        # Let the separator raise its own, better error.
        return None

    manifest_file = output_dir / _MANIFEST_NAME
    if not manifest_file.is_file():
        return None

    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Manifiesto de stems ilegible, se recalcula: %s", manifest_file)
        return None

    if manifest.get("model") != model:
        return None
    if manifest.get("precision") != settings.demucs_precision:
        return None

    # Cheap check before the hash so an unrelated large file is rejected fast.
    if manifest.get("input_size") != input_path.stat().st_size:
        return None
    if manifest.get("input_sha256") != _sha256_file(input_path):
        return None

    stems = manifest.get("stems") or {}
    for name in STEM_NAMES:
        if not (stems.get(name) and Path(stems[name]).is_file()):
            return None

    logger.info(
        "Stem cache HIT en %s: se reusan los 4 stems, Demucs NO vuelve a correr",
        output_dir,
    )
    return {**manifest, "cache_hit": True}


def _write_manifest(
    output_dir: Path, input_path: Path, model: str, result: dict[str, Any]
) -> None:
    """Record what was separated, from what, and with which settings."""
    manifest = {
        **result,
        "model": model,
        "precision": settings.demucs_precision,
        "input_path": str(input_path),
        "input_size": input_path.stat().st_size,
        "input_sha256": _sha256_file(input_path),
    }
    manifest.pop("cache_hit", None)
    try:
        (output_dir / _MANIFEST_NAME).write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        # A cache we cannot persist is a slow run, not a failed one.
        logger.warning("No se pudo escribir el manifiesto de stems en %s", output_dir)


def split_audio(
    input_path: str | Path,
    output_dir: str | Path | None = None,
    model: str = "htdemucs",
) -> dict[str, Any]:
    """Run Demucs source separation on an audio file.

    A previous separation is reused when the manifest proves it came from the
    same audio with the same model and precision; the returned dict then
    carries ``cache_hit: True``.

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
        plus ``"cache_hit": True`` on a reuse.
    """
    source = Path(input_path)
    target = _resolve_output_dir(source, output_dir)

    cached = _cached_result(source, target, model)
    if cached is not None:
        return cached

    if not settings.demucs_isolated:
        result = _split_audio_in_process(source, target, model)
    else:
        result = _split_audio_isolated(source, target, model)

    _write_manifest(target, source, model, result)
    return result


def _resolve_output_dir(input_path: str | Path, output_dir: str | Path | None) -> Path:
    """Same defaulting rule for both paths, so they agree on ``stem_audio_dir``."""
    if output_dir is None:
        return settings.output_dir / Path(input_path).stem / "stems"
    return Path(output_dir).resolve()


def _split_audio_isolated(
    input_path: str | Path,
    output_dir: str | Path | None,
    model: str,
) -> dict[str, Any]:
    """Run the separation in a child process so its memory is reclaimed.

    The parent waits for the child and then reads a small JSON result file. All
    audio leaves the process through the filesystem, so nothing large has to
    cross a pipe.
    """
    source = Path(input_path).resolve()
    target = _resolve_output_dir(input_path, output_dir)
    target.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as scratch:
        result_json = Path(scratch) / "result.json"
        cmd = [
            sys.executable,
            "-m",
            "audiomind.processing.demucs_worker",
            str(source),
            str(target),
            model,
            settings.demucs_precision,
            str(result_json),
            str(settings.demucs_threads),
        ]
        logger.info(
            "Running Demucs in an isolated process (pid-less, %s timeout): %s",
            settings.demucs_timeout_seconds,
            target,
        )
        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=settings.demucs_timeout_seconds,
            )
        except subprocess.TimeoutExpired as err:
            raise TimeoutError(
                f"Demucs isolation timed out after {settings.demucs_timeout_seconds}s"
            ) from err

        if completed.returncode != 0:
            tail = (completed.stderr or "").strip().splitlines()[-8:]
            raise RuntimeError(
                "Demucs isolation failed "
                f"(exit {completed.returncode}):\n" + "\n".join(tail)
            )

        if not result_json.exists():
            raise RuntimeError(
                "Demucs isolation produced no result file: " + str(result_json)
            )
        result = json.loads(result_json.read_text(encoding="utf-8"))

    # The child may have been killed between writing stems and the result file,
    # so verify what we are about to hand back to the caller.
    stems = result.get("stems") or {}
    missing = [name for name in STEM_NAMES if not (stems.get(name) and Path(stems[name]).exists())]
    if missing:
        raise RuntimeError(f"Demucs isolation returned no audio for: {missing}")

    logger.info("Demucs isolation finished: %d stems", len(stems))
    return result


def _split_audio_in_process(
    input_path: str | Path,
    output_dir: str | Path | None = None,
    model: str = "htdemucs",
) -> dict[str, Any]:
    """In-process separation. Used when isolation is disabled.

    Memory from this call is NOT returned to the OS, so it must not be used
    behind a long-lived worker: that is exactly what produced the OOM kills.
    """
    import demucs_onnx as demo

    input_path = Path(input_path).resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Same defaulting rule as the isolated path.
    output_dir = _resolve_output_dir(input_path, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Read source audio metadata before processing
    info = sf.info(str(input_path))
    sample_rate = int(info.samplerate)
    duration = info.duration

    # Run demucs-onnx separation — write stems to disk
    #
    # precision MUST match the weights baked into the image (see the prewarm
    # step in apps/audiomind/Dockerfile). demucs-onnx keys its download cache
    # by precision, so a mismatch here means a fresh ~300 MB download inside
    # the request — the request-time download that used to OOM the container.
    stems: dict[str, np.ndarray] = demo.separate(
        str(input_path),
        output_dir=str(output_dir),
        model=model,
        precision=settings.demucs_precision,
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
