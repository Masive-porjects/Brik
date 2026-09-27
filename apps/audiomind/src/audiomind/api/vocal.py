"""Vocal Chain API endpoints.

POST /api/session/{id}/vocal       — apply vocal processing
GET  /api/session/{id}/vocal/audio — serve processed vocal audio

The vocal chain writes to its OWN pointer (``SessionData.vocal_path``), never
to ``mastered_path``: a processed vocal is a stem artifact, so the master
pointers served by ``/audio/mastered``, ``/raw-mastered`` and ``/download`` keep
describing the real master (unchanged, or ``None`` when the session was never
mastered).
"""

from pathlib import Path
from typing import Any
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse

from audiomind.config import settings
from audiomind.api.upload import sessions
from audiomind.api.license import require_license
from audiomind.models.audio import ProcessingStatus
from audiomind.session_store import save_sessions

router = APIRouter()


class VocalParamsModel(BaseModel):
    """Vocal chain request body — 3 control knobs mapped to 0-1 range."""

    deesser_amount: float = Field(0.3, ge=0, le=1.0, description="De-Esser intensity. 0 = off, 1 = max sibilance reduction.")
    pitch_shift_semitones: float = Field(0.0, ge=-3, le=3, description="Pitch shift in semitones. 0 = off. Positive = up, negative = down.")
    cohesion_amount: float = Field(0.4, ge=0, le=1.0, description="Optical compression amount. 0 = off, 1 = max glue/presence.")


@router.post("/session/{session_id}/vocal")
def process_vocal_endpoint(
    session_id: str,
    params: VocalParamsModel,
    _: object = Depends(require_license),
) -> dict[str, Any]:
    """Run the VoiceChain Pro on a session's audio.

    Applies De-Esser → Pitch Shift → Optical Compressor in series. The result
    is recorded on ``session.vocal_path``; the master pointer is left exactly
    as it was (the vocal is a stem artifact, not a master).
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.original_path or not Path(session.original_path).exists():
        raise HTTPException(
            status_code=400, detail="No audio file found for this session"
        )

    output_path = settings.output_dir / f"{session_id}_vocal.wav"

    session.status = ProcessingStatus.PROCESSING
    session.progress = 0.0

    try:
        from audiomind.processing.vocal import process_vocal, VocalParameters

        vp = VocalParameters(
            deesser_amount=params.deesser_amount,
            pitch_shift_semitones=params.pitch_shift_semitones,
            cohesion_amount=params.cohesion_amount,
        )

        def update_progress(pct: float) -> None:
            session.progress = pct

        result = process_vocal(
            input_path=session.original_path,
            output_path=output_path,
            params=vp,
            progress_cb=update_progress,
        )

        session.vocal_path = result["output_path"]
        session.status = ProcessingStatus.COMPLETED
        session.progress = 1.0
        save_sessions(sessions)

        return {
            "session_id": session_id,
            "status": "completed",
            "gain_reduction_db": result["gain_reduction_db"],
            "output_path": result["output_path"],
        }
    except Exception as e:
        session.status = ProcessingStatus.ERROR
        session.error = f"Vocal processing failed: {str(e)}"
        raise HTTPException(status_code=500, detail=session.error)


def _vocal_output_path(session_id: str) -> Path:
    """Resolve the session's processed-vocal WAV, pointer first.

    ``session.vocal_path`` is what ``POST /vocal`` recorded, so it is
    authoritative; the ``{session_id}_vocal.wav`` convention is only the
    fallback for sessions persisted before the field existed (the file is on
    disk but untracked). Both resolve to the SAME file — the chain writes that
    exact name — so the served bytes never change.
    """
    session = sessions[session_id]
    if session.vocal_path:
        return Path(session.vocal_path)
    return settings.output_dir / f"{session_id}_vocal.wav"


@router.get("/session/{session_id}/vocal/audio")
async def get_vocal_audio(session_id: str) -> FileResponse:
    """Serve the processed vocal WAV file."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    path = _vocal_output_path(session_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="No vocal-processed audio found. Run /vocal first.")

    return FileResponse(
        str(path.resolve()),
        media_type="audio/wav",
        filename=f"{session_id}_vocal.wav",
    )
