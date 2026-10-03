"""Disk-persisted session store (survives Railway restarts/redeploys).

Sessions live in memory for speed, but are mirrored to a JSON file inside
the upload directory. When a Railway volume is mounted at ``/app/uploads``
(see the deploy notes), both the uploaded audio files AND ``sessions.json``
survive container restarts, so a demo user never loses their session.

The mirror is best-effort: a persistence failure never breaks a request.

Write safety
------------
``save_sessions`` serializes the WHOLE store, and it is called from request
handlers *and* from background threads (the async mix job registers the
finished mix from a ``BackgroundTasks`` thread). Without a lock, two writers
interleave and one truncates the other's file; the result is invalid JSON, and
``load_sessions`` answers ``{}`` on any parse error -- so one lost write would
silently drop EVERY session, not just one. So the snapshot+write is serialized
with a lock and published with ``Path.replace``, which is atomic on POSIX and
on Windows. A reader therefore sees either the previous file or the new one,
never a half-written one.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from audiomind.config import settings
from audiomind.models.audio import SessionData

logger = logging.getLogger(__name__)

# Lives inside the (volume-mounted) upload dir so both the audio and the
# session metadata ride the same persistent disk.
SESSION_FILE: Path = settings.upload_dir / "sessions.json"

#: Serializes snapshot+write so two threads cannot interleave the dump.
_save_lock = threading.Lock()


def load_sessions() -> dict[str, SessionData]:
    """Load persisted sessions from disk (empty dict on any failure)."""
    if not SESSION_FILE.exists():
        return {}
    try:
        raw = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
        return {
            sid: SessionData.model_validate(data)
            for sid, data in raw.items()
        }
    except Exception:
        return {}


def save_sessions(sessions: dict[str, SessionData]) -> None:
    """Best-effort mirror of the in-memory session store to disk.

    Written to a sibling ``.tmp`` and published with ``Path.replace`` so a
    concurrent reader never observes a truncated file. The failure is logged
    rather than swallowed: an invisible save failure is how a whole session
    store disappears on the next restart.
    """
    with _save_lock:
        tmp_file = SESSION_FILE.with_name(SESSION_FILE.name + ".tmp")
        try:
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {
                sid: session.model_dump(mode="json")
                for sid, session in sessions.items()
            }
            tmp_file.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            tmp_file.replace(SESSION_FILE)
        except Exception as exc:  # pragma: no cover - best-effort mirror
            logger.warning("Could not persist sessions to %s: %s", SESSION_FILE, exc)
            tmp_file.unlink(missing_ok=True)