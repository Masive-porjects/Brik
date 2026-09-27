"""SongStarter API endpoints.

POST /api/session/{session_id}/beat/generate  — generate a beat
GET  /api/session/{session_id}/beat/{beat_id}/audio — serve WAV (optional stem= param)
POST /api/beat/save  — save beat to projects/
GET  /api/beats  — list saved beats
GET  /api/beat/{beat_id}  — load saved beat metadata
GET  /api/beat/{beat_id}/audio  — serve saved beat WAV
DELETE /api/beat/{beat_id}  — delete saved beat
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from audiomind.config import settings
from audiomind.models.audio import BeatData

router = APIRouter()

# ── Validation sets ────────────────────────────────────────────────────────
VALID_SCALES: set[str] = {
    "major",
    "natural_minor",
    "harmonic_minor",
    "melodic_minor",
    "dorian",
    "phrygian",
    "lydian",
    "mixolydian",
    "locrian",
    "blues",
    "pentatonic_major",
    "pentatonic_minor",
}

VALID_ROOT_NOTES: set[str] = {
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B",
}

# ── Request models ─────────────────────────────────────────────────────────


class BeatGenParams(BaseModel):
    """Parameters for beat generation."""

    bpm: float = Field(120, ge=60, le=180)
    scale: str = "major"
    root_note: str = "C"
    swing_amount: float = Field(0.3, ge=0.0, le=1.0)


class SaveBeatParams(BaseModel):
    """Payload to save a generated beat to persistent storage."""

    session_id: str
    beat_id: str
    name: str | None = None
    bpm: float = 120
    scale: str = "major"
    root_note: str = "C"
    swing_amount: float = 0.3
    duration: float = 0.0


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.post("/session/{session_id}/beat/generate")
async def generate_beat(session_id: str, params: BeatGenParams) -> BeatData:
    """Generate a beat using the SongStarter engine.

    Args:
        session_id: Session UUID for output scoping.
        params: Generation parameters (BPM, scale, root note, swing).

    Returns a ``BeatData`` object with beat metadata and stem paths.
    """
    if params.scale not in VALID_SCALES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scale '{params.scale}'. "
            f"Valid: {', '.join(sorted(VALID_SCALES))}",
        )
    if params.root_note not in VALID_ROOT_NOTES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid root note '{params.root_note}'. "
            f"Valid: {', '.join(VALID_ROOT_NOTES)}",
        )

    beat_id = uuid.uuid4().hex[:12]
    output_dir = settings.output_dir / session_id / beat_id

    try:
        from audiomind.processing.songstarter import BeatGenerator

        gen = BeatGenerator()
        result = gen.generate_beat(
            bpm=params.bpm,
            scale=params.scale,
            root_note=params.root_note,
            swing_amount=params.swing_amount,
            output_dir=output_dir,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Beat generation failed: {e}",
        )

    return BeatData(
        beat_id=beat_id,
        bpm=result["bpm"],
        scale=result["scale"],
        root_note=result["root_note"],
        swing_amount=params.swing_amount,
        duration=result["duration"],
        output_path=result["output_path"],
        stems=result["stems"],
    )


@router.get("/session/{session_id}/beat/{beat_id}/audio")
async def get_beat_audio(
    session_id: str,
    beat_id: str,
    stem: str | None = Query(None),
) -> FileResponse:
    """Serve beat audio WAV from the outputs directory.

    Without ``stem``: returns the full mix.
    With ``stem``: returns the individual stem WAV (kick, snare, bass, ...).
    """
    beat_dir = settings.output_dir / session_id / beat_id

    if stem:
        stem_path = beat_dir / "stems" / f"{stem}.wav"
        if not stem_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Stem '{stem}' not found for beat {beat_id}",
            )
        return FileResponse(
            str(stem_path.resolve()),
            media_type="audio/wav",
            filename=f"{beat_id}_{stem}.wav",
        )

    mix_path = beat_dir / "mix.wav"
    if not mix_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Beat {beat_id} not found. Generate it first.",
        )

    return FileResponse(
        str(mix_path.resolve()),
        media_type="audio/wav",
        filename=f"{beat_id}_mix.wav",
    )


@router.post("/beat/save")
async def save_beat(params: SaveBeatParams) -> dict[str, str]:
    """Save a generated beat to the projects directory.

    Copies the WAV files from ``outputs/{session_id}/{beat_id}/`` to
    ``projects/{beat_id}/`` and writes a ``beat.json`` metadata file.
    """
    src_dir = settings.output_dir / params.session_id / params.beat_id
    if not src_dir.exists() or not (src_dir / "mix.wav").exists():
        raise HTTPException(
            status_code=404,
            detail=f"Beat {params.beat_id} not found in outputs. "
            "Generate it first.",
        )

    dest_dir = settings.projects_dir / params.beat_id
    if dest_dir.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Beat {params.beat_id} is already saved.",
        )

    shutil.copytree(str(src_dir), str(dest_dir))

    metadata = {
        "id": params.beat_id,
        "name": params.name,
        "bpm": params.bpm,
        "scale": params.scale,
        "root_note": params.root_note,
        "swing_amount": params.swing_amount,
        "duration": params.duration,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    beat_json_path = dest_dir / "beat.json"
    try:
        beat_json_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as e:
        # Clean up partial copy if metadata write fails
        shutil.rmtree(str(dest_dir))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to write beat metadata: {e}",
        )

    return {"message": "Beat saved successfully", "beat_id": params.beat_id}


@router.get("/beats")
async def list_beats() -> list[dict[str, Any]]:
    """List all saved beats.

    Scans the ``projects/`` directory for ``beat.json`` files and returns
    their metadata in reverse chronological order.
    """
    if not settings.projects_dir.exists():
        return []

    beats: list[dict[str, Any]] = []
    for beat_dir in sorted(settings.projects_dir.iterdir(), reverse=True):
        if not beat_dir.is_dir():
            continue
        beat_json = beat_dir / "beat.json"
        if not beat_json.exists():
            continue
        try:
            data = json.loads(beat_json.read_text(encoding="utf-8"))
            beats.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    return beats


@router.get("/beat/{beat_id}")
async def get_beat(beat_id: str) -> dict[str, Any]:
    """Load a saved beat's metadata from ``beat.json``."""
    beat_json = settings.projects_dir / beat_id / "beat.json"
    if not beat_json.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Saved beat {beat_id} not found.",
        )

    try:
        data = json.loads(beat_json.read_text(encoding="utf-8"))
        return dict(data)
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to read beat metadata: {e}",
        )


@router.get("/beat/{beat_id}/audio")
async def get_saved_beat_audio(
    beat_id: str,
    stem: str | None = Query(None),
) -> FileResponse:
    """Serve a saved beat's audio from the projects directory.

    Without ``stem``: returns the full mix.
    With ``stem``: returns the individual stem WAV.
    """
    beat_dir = settings.projects_dir / beat_id

    if stem:
        stem_path = beat_dir / "stems" / f"{stem}.wav"
        if not stem_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Stem '{stem}' not found for saved beat {beat_id}",
            )
        return FileResponse(
            str(stem_path.resolve()),
            media_type="audio/wav",
            filename=f"{beat_id}_{stem}.wav",
        )

    mix_path = beat_dir / "mix.wav"
    if not mix_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Saved beat {beat_id} audio not found.",
        )

    return FileResponse(
        str(mix_path.resolve()),
        media_type="audio/wav",
        filename=f"{beat_id}_mix.wav",
    )


@router.delete("/beat/{beat_id}")
async def delete_beat(beat_id: str) -> dict[str, str]:
    """Delete a saved beat and its directory from ``projects/``."""
    beat_dir = settings.projects_dir / beat_id
    if not beat_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Saved beat {beat_id} not found.",
        )

    shutil.rmtree(str(beat_dir))
    return {"message": f"Beat {beat_id} deleted successfully"}
