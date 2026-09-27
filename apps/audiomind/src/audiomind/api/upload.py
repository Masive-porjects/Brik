import asyncio
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, UploadFile, File, HTTPException

from audiomind.config import settings
from audiomind.models.audio import SessionData, ProcessingStatus
from audiomind.services import demo_guard
from audiomind.session_store import load_sessions, save_sessions

router = APIRouter()

# Session store — restored from disk so sessions survive restarts/redeploys
# when a Railway volume is mounted at /app/uploads.
sessions: dict[str, SessionData] = load_sessions()

# Strong references to background analysis tasks so they are never GC'd
_background_tasks: set[asyncio.Future[Any]] = set()


@router.post("/upload", response_model=SessionData)
async def upload_audio(file: UploadFile = File(...)) -> SessionData:
    """Upload an audio file for mastering analysis."""
    # Validate file type
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".wav", ".mp3"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{suffix}'. Only WAV and MP3 are supported.",
        )

    # Validate file size
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.max_file_size_mb:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_mb:.1f}MB). Maximum is {settings.max_file_size_mb}MB.",
        )

    # Create session
    session_id = str(uuid.uuid4())
    filename = f"{session_id}{suffix}"
    file_path = settings.upload_dir / filename

    # Ensure absolute path
    file_path = file_path.resolve()
    
    # Save file
    file_path.write_bytes(content)

    # Create session data
    session = SessionData(
        session_id=session_id,
        status=ProcessingStatus.UPLOADED,
        original_path=str(file_path),
        original_filename=file.filename,
    )
    sessions[session_id] = session

    # Demo duration guard: reject overlength uploads BEFORE any analysis or
    # DSP. WAV probes the header only (fast); MP3 uses librosa/audioread.
    # A failed probe never rejects — the defensive checks in /process and
    # /master catch it later (the backend is the authority in the end).
    if settings.demo_max_duration_seconds > 0.0:
        duration = demo_guard.probe_duration(file_path)
        if duration is not None and duration > settings.demo_max_duration_seconds:
            # Best-effort cleanup of what we just created, then reject.
            file_path.unlink(missing_ok=True)
            sessions.pop(session_id, None)
            raise HTTPException(
                status_code=422,
                detail=demo_guard.demo_duration_message(
                    settings.demo_max_duration_seconds
                ),
            )

    demo_guard.touch(session_id)

    # Auto-analyze the uploaded audio in the background so the upload
    # returns immediately and the event loop never blocks on librosa.
    session.status = ProcessingStatus.ANALYZING
    save_sessions(sessions)
    loop = asyncio.get_running_loop()

    def _analyze() -> None:
        try:
            from audiomind.analysis.analyzer import analyze_audio

            session.analysis = analyze_audio(str(file_path))
        except Exception:
            pass  # Analysis is optional on upload; process will do it if needed
        finally:
            session.status = ProcessingStatus.UPLOADED
            # Trigger pre-render of all presets once analysis is ready —
            # ONLY in the default "all" mode. Demo ("on_demand") uploads
            # finish with status "uploaded" and zero automatic preset DSP.
            # Lazy import to avoid circular dependency (mastering imports upload).
            if (
                session.analysis is not None
                and settings.prerender_mode == "all"
            ):
                try:
                    from audiomind.api.mastering import _prerender_all_presets
                    _prerender_all_presets(
                        session_id=session_id,
                        input_path=str(file_path),
                        analysis=session.analysis,
                    )
                except Exception:
                    pass  # Pre-render is best-effort; never break upload
            # Persist analysis + status so a restart doesn't lose the work
            save_sessions(sessions)

    task = loop.run_in_executor(None, _analyze)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return session


@router.post("/session/new")
async def create_session(data: dict[str, Any] | None = None) -> dict[str, str]:
    """Create a new processing session (used by SongStarter tests)."""
    session_id = str(uuid.uuid4())
    sessions[session_id] = SessionData(
        session_id=session_id,
        status=ProcessingStatus.UPLOADED,
    )
    save_sessions(sessions)
    return {"session_id": session_id}


@router.get("/session/{session_id}", response_model=SessionData)
async def get_session(session_id: str) -> SessionData:
    """Get session status and data."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    demo_guard.touch(session_id)
    return session
