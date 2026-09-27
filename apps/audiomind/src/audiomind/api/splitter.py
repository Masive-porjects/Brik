"""Stem Splitter API endpoints.

POST /api/session/{id}/split  — run Demucs separation
GET  /api/session/{id}/stems  — list stem metadata
GET  /api/session/{id}/stem/{stem} — serve individual stem WAV
"""

from pathlib import Path
from typing import Any
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse

from audiomind.config import settings
from audiomind.api.upload import sessions
from audiomind.api.license import require_license
from audiomind.processing.splitter import split_audio, STEM_NAMES

router = APIRouter()


@router.post("/session/{session_id}/split")
async def split_session(
    session_id: str,
    model: str = "htdemucs",
    _: object = Depends(require_license),
) -> dict[str, Any]:
    """Run stem isolation (Demucs source separation) on a session's audio.

    Args:
        session_id: Session UUID.
        model: Demucs model — ``"htdemucs"`` (fast, 4 stems) or
            ``"htdemucs_ft"`` (higher quality, 4 stems).

    Returns metadata about the separated stems.
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.original_path or not Path(session.original_path).exists():
        raise HTTPException(
            status_code=400, detail="No audio file found for this session"
        )

    try:
        result = split_audio(
            input_path=session.original_path,
            output_dir=settings.output_dir / session_id / "stems",
            model=model,
        )
        return {
            "session_id": session_id,
            "status": "completed",
            "stems": result["stems"],
            "sample_rate": result["sample_rate"],
            "duration_seconds": result["duration_seconds"],
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Stem separation failed: {str(e)}"
        )


@router.get("/session/{session_id}/stems")
async def list_stems(session_id: str) -> dict[str, Any]:
    """List available stems for a session."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    stems_dir = settings.output_dir / session_id / "stems"
    if not stems_dir.exists():
        return {
            "session_id": session_id,
            "status": "not_split",
            "stems": {},
        }

    # Discover which stem files exist
    available: dict[str, str] = {}
    for name in STEM_NAMES:
        wav = stems_dir / f"{name}.wav"
        if wav.exists():
            available[name] = str(wav)

    return {
        "session_id": session_id,
        "status": "completed" if available else "not_split",
        "stems": available,
    }


@router.get("/session/{session_id}/stem/{stem_name}")
async def get_stem_audio(session_id: str, stem_name: str) -> FileResponse:
    """Serve an individual stem WAV file."""
    if stem_name not in STEM_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown stem '{stem_name}'. Choose from: {', '.join(STEM_NAMES)}",
        )

    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    stem_path = settings.output_dir / session_id / "stems" / f"{stem_name}.wav"
    if not stem_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Stem '{stem_name}' not found. Run /split first.",
        )

    return FileResponse(
        str(stem_path.resolve()),
        media_type="audio/wav",
        filename=f"{session_id}_{stem_name}.wav",
    )
