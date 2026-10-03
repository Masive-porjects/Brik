"""Durable backends for the session store.

WHY A BACKEND INTERFACE
-----------------------
Sessions used to be mirrored to a single ``sessions.json`` file. That file
lives on Railway's ephemeral disk, so a redeploy erased every session even
though the audio itself was already durable in Cloudflare R2 (§3.1.2, §3.2.1).
The pointer was the fragile part. This module moves the record to Postgres
while keeping ``session_store.load_sessions()`` / ``save_sessions()`` exactly
as they were, so none of the seven modules that import the in-memory dict had
to change.

TWO BACKENDS, ONE ACTIVE
------------------------
``FileSessionBackend`` (current behaviour) and ``SupabaseSessionBackend``.
They are never both written: ``get_session_backend()`` picks ONE and the
process stays on it. Dual-writing would mean two sources of truth that drift,
which is the bug this whole change exists to remove.

READ FAILURE IS NOT "EMPTY"
---------------------------
``load_all()`` returns ``None`` -- never ``{}`` -- when it could not actually
read the store. The difference is load-bearing: ``session_store`` reconciles by
deleting the ids missing from its in-memory dict, so mistaking a network
timeout for an empty table would make the next ``save_sessions()`` delete
EVERY session row. A backend that cannot tell "empty" from "unreadable" must
not be plugged into that reconciliation.

SINGLE-PROCESS INVARIANT
-------------------------
The in-memory dict in ``api.upload`` remains the source of truth for READS;
the backend is the durable mirror. That is sound only while a single process
serves the sessions -- with two uvicorn workers each holds its own dict and the
two silently diverge. Railway runs one worker, so this holds today. It is the
first thing to break if the service is ever scaled horizontally.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from audiomind.config import settings
from audiomind.models.audio import SessionData

logger = logging.getLogger(__name__)


class SessionBackend(Protocol):
    """What ``session_store`` needs from a durable session store.

    Writes report success as a ``bool`` and never raise. Reporting it matters:
    ``session_store`` records a session as persisted only when the write is
    confirmed, so a failure is retried on the next save instead of being
    silently forgotten. That is what keeps an invisible write failure from
    becoming a lost session.
    """

    def load_all(self) -> dict[str, SessionData] | None:
        """Every stored session, or ``None`` if the store could not be read.

        ``None`` means "unknown", NOT "empty". An empty store is ``{}``.
        """

    def upsert_many(self, rows: dict[str, dict[str, Any]]) -> bool:
        """Create or replace the given ``session_id -> payload`` rows."""

    def delete_many(self, session_ids: Iterable[str]) -> bool:
        """Remove the given session ids. Missing ids are not an error."""


# ────────────────────────────── file mirror ──────────────────────────────


class FileSessionBackend:
    """The historical ``sessions.json`` mirror.

    Writes still rewrite the whole file, because a JSON document has no notion
    of a partial update. It stays as the fallback so a developer who clones the
    repo without Supabase credentials gets a working app on disk.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    def load_all(self) -> dict[str, SessionData] | None:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return {
                sid: SessionData.model_validate(data)
                for sid, data in raw.items()
            }
        except Exception as exc:
            # Unreadable file: report "unknown" so the caller never prunes on
            # the strength of a half-read store.
            logger.warning(
                "Could not read the session file %s (%s); treating the store "
                "as unknown rather than empty",
                self._path,
                exc,
            )
            return None

    def _rewrite(self, rows: dict[str, Any]) -> bool:
        """Publish the whole store atomically.

        Written to a sibling ``.tmp`` and published with ``Path.replace``, so a
        concurrent reader observes either the previous file or the new one and
        never a truncated one -- the guarantee the old whole-store dump had.
        """
        tmp_file = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_file.write_text(
                json.dumps(rows, ensure_ascii=False), encoding="utf-8"
            )
            tmp_file.replace(self._path)
            return True
        except Exception as exc:  # pragma: no cover - best-effort mirror
            logger.warning("Could not persist sessions to %s: %s", self._path, exc)
            tmp_file.unlink(missing_ok=True)
            return False

    def _read_rows(self) -> dict[str, Any] | None:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else None
        except Exception as exc:
            logger.warning(
                "Refusing to rewrite the session file %s: it could not be "
                "parsed (%s), so a merge would drop whatever is in it",
                self._path,
                exc,
            )
            return None

    def upsert_many(self, rows: dict[str, dict[str, Any]]) -> bool:
        if not rows:
            return True
        existing = self._read_rows()
        if existing is None:
            return False  # unparseable: refuse rather than overwrite with a subset
        existing.update(rows)
        return self._rewrite(existing)

    def delete_many(self, session_ids: Iterable[str]) -> bool:
        doomed = set(session_ids)
        if not doomed:
            return True
        existing = self._read_rows()
        if existing is None:
            return False
        remaining = {k: v for k, v in existing.items() if k not in doomed}
        if len(remaining) == len(existing):
            return True
        return self._rewrite(remaining)


# ─────────────────────────────── supabase ────────────────────────────────


class SupabaseSessionBackend:
    """Durable store backed by the ``sessions`` Postgres table.

    Reads and writes go through PostgREST. Mirrors ``SupabaseJobStore``: every
    failure is logged and turned into a no-op or a ``None``, never an exception,
    because session bookkeeping must never fail an audio request.
    """

    TABLE = "sessions"

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def probe(cls, client: Any) -> None:
        """Raise unless the session table is actually queryable.

        Deliberately a real read rather than a metadata check, for the reason
        ``SupabaseJobStore.probe`` gives: Supabase reports a missing table, a
        revoked key and a disabled project differently, and all we need to know
        before committing to the durable path is "usable" vs "not usable".
        """
        response = client.table(cls.TABLE).select("session_id").limit(1).execute()
        if getattr(response, "data", None) is None:
            raise RuntimeError(f"Supabase returned no data for {cls.TABLE}")

    def load_all(self) -> dict[str, SessionData] | None:
        try:
            response = (
                self._client.table(self.TABLE)
                .select("session_id, payload")
                .execute()
            )
        except Exception as exc:
            logger.error("Could not read the %s table: %s", self.TABLE, exc)
            return None

        rows = getattr(response, "data", None)
        if rows is None:
            logger.error("Supabase returned no data for %s", self.TABLE)
            return None

        sessions: dict[str, SessionData] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            sid = row.get("session_id")
            payload = row.get("payload")
            if not isinstance(sid, str) or not isinstance(payload, dict):
                continue
            try:
                sessions[sid] = SessionData.model_validate(payload)
            except Exception as exc:
                # One unreadable row must not hide every other session: that
                # would look like a mass data loss to the caller.
                logger.warning("Unreadable session row %s dropped: %s", sid, exc)
        return sessions

    def upsert_many(self, rows: dict[str, dict[str, Any]]) -> bool:
        if not rows:
            return True
        payload = [
            {
                "session_id": sid,
                "status": data.get("status") or "uploaded",
                "payload": data,
                "updated_at": now_iso(),
            }
            for sid, data in rows.items()
        ]
        try:
            self._client.table(self.TABLE).upsert(payload).execute()
            return True
        except Exception as exc:
            logger.error(
                "Could not persist %d session(s) to %s: %s",
                len(payload),
                self.TABLE,
                exc,
            )
            return False

    def delete_many(self, session_ids: Iterable[str]) -> bool:
        doomed = [sid for sid in session_ids]
        if not doomed:
            return True
        try:
            (
                self._client.table(self.TABLE)
                .delete()
                .in_("session_id", doomed)
                .execute()
            )
            return True
        except Exception as exc:
            logger.error(
                "Could not delete %d session(s) from %s: %s",
                len(doomed),
                self.TABLE,
                exc,
            )
            return False


def now_iso() -> str:
    """UTC timestamp in the ISO-8601 form PostgREST casts to ``timestamptz``."""
    return datetime.now(UTC).isoformat()


# ─────────────────────────────── selection ───────────────────────────────


_backend: SessionBackend | None = None
_backend_lock = threading.Lock()


def get_session_backend() -> SessionBackend:
    """Return the process-wide session backend.

    Precedence: the explicit ``session_store_backend`` setting wins, then real
    Supabase credentials, then the file mirror.

    The probe exists for the same reason ``get_job_store`` has one. Supabase is
    ALREADY configured in production for ``tracks`` and ``masters``, so
    "credentials present" says nothing about whether the new table exists.
    Without the probe, a deployment that has not applied the migration would
    pick the durable backend, fail every write, and silently lose every session
    on the next redeploy -- which is exactly the failure this change is meant
    to remove. Probing turns that into a log line plus a working file mirror.
    """
    global _backend
    if _backend is not None:
        return _backend

    with _backend_lock:
        if _backend is not None:
            return _backend

        choice = (settings.session_store_backend or "auto").strip().lower()

        if choice == "file":
            _backend = FileSessionBackend(settings.upload_dir / "sessions.json")
            logger.info("Session store: file mirror at %s", _backend.path)
            return _backend

        if choice in ("auto", "supabase"):
            if not (
                settings.supabase_url
                and (
                    settings.supabase_service_role_key
                    or settings.supabase_anon_key
                )
            ):
                if choice == "supabase":
                    raise RuntimeError(
                        "session_store_backend='supabase' but no Supabase "
                        "credentials are configured"
                    )
            else:
                try:
                    from audiomind.services.supabase_client import (
                        get_supabase_client,
                    )

                    client = get_supabase_client()
                    if client is not None:
                        SupabaseSessionBackend.probe(client)
                        _backend = SupabaseSessionBackend(client)
                        logger.info(
                            "Session store: durable Supabase table %s "
                            "(no backfill: sessions created before this switch "
                            "are gone)",
                            SupabaseSessionBackend.TABLE,
                        )
                        return _backend
                except Exception as exc:
                    if choice == "supabase":
                        raise
                    logger.warning(
                        "Supabase session store unusable (%s); using the file "
                        "mirror. Sessions will NOT survive a backend restart "
                        "until the %s table exists. Supabase credentials alone "
                        "are not enough: see supabase/migrations/ for the "
                        "schema.",
                        exc,
                        SupabaseSessionBackend.TABLE,
                    )
        else:
            raise ValueError(
                f"Unknown session_store_backend {choice!r}; expected one of "
                "'auto', 'supabase', 'file'"
            )

        _backend = FileSessionBackend(settings.upload_dir / "sessions.json")
        logger.warning(
            "Session store: falling back to the file mirror at %s. Sessions "
            "will NOT survive a backend restart.",
            _backend.path,
        )
        return _backend


def reset_session_backend() -> None:
    """Drop the cached backend so the next call re-selects.

    Tests and the settings pin need this; production never calls it.
    """
    global _backend
    with _backend_lock:
        _backend = None