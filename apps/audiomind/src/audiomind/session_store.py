"""Durable session store: in-memory dict, one durable backend behind it.

LAYERS
------
``api.upload.sessions`` is the in-memory dict and the source of truth for
READS. This module is the write-behind: it decides what actually has to reach
the durable backend and does so through ``services.session_backend``.

The public surface is deliberately unchanged -- ``load_sessions()`` and
``save_sessions(sessions)`` keep their exact signatures -- because seven
modules import that dict and call ``save_sessions`` with the whole store
(``mastering.py`` alone does it ten times). Nothing outside this file had to
change when the backend moved from a JSON file to Postgres.

WHY DIGESTS
-----------
``save_sessions`` receives the ENTIRE dict, so it cannot tell what changed. A
JSON file has no alternative -- it is rewritten whole -- but a database would
turn every one of those ~20 call sites into N upserts, one per session. Hashing
each session's serialized form and comparing it against the last written value
means a typical save persists exactly the session that actually changed.

The digest map is also what makes deletion safe: an id present in the last
written set but absent from the current dict is a session the app dropped (the
TTL janitor in ``services.demo_guard`` does exactly that), so its row is
deleted instead of being resurrected by the next load.

A digest is advanced only once the backend CONFIRMS the write. A session whose
upsert failed keeps its stale digest, so the next ``save_sessions`` re-sends it
rather than assuming it landed. The same holds for a refused delete: it is
deferred, not forgotten.

THE PRUNING GUARD
-----------------
``load_all()`` distinguishes "empty" from "unreadable", and this module
propagates that distinction into a ``_load_complete`` flag. If the last full
load did not succeed, the in-memory dict may be missing sessions that still
exist in the backend -- so ``save_sessions`` refuses to delete anything and
only upserts. Deleting on an incomplete view is how a single Supabase timeout
would wipe the whole table; there is no undo for that and no exception to catch
it, because the delete would itself succeed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
from typing import Any

from audiomind.models.audio import SessionData
from audiomind.services.session_backend import get_session_backend

logger = logging.getLogger(__name__)

#: Serializes reconcile+write so two threads cannot interleave an upsert with
#: a delete, which is exactly the pair that could resurrect a pruned session.
_save_lock = threading.Lock()

#: session_id -> digest of the last form we handed to the backend. The authority
#: on "what is already persisted".
_last_digests: dict[str, str] = {}

#: False when the last ``load_sessions()`` could not actually read the backend.
#: While False, deletion is refused.
_load_complete = False


def _digest(payload: dict[str, Any]) -> str:
    """Stable content hash of a serialized session.

    ``sort_keys`` because dict ordering is not part of the value: two payloads
    that differ only in key order must not read as "changed" and trigger a
    pointless write.
    """
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_sessions() -> dict[str, SessionData]:
    """Load every persisted session.

    Returns ``{}`` when the backend cannot be read, but records that the load
    was incomplete so ``save_sessions`` will not prune on this view. That is
    the behaviour the old implementation had for a corrupt file, now carried
    over to a backend that can also be unreachable.

    A failed load leaves the digest map alone on purpose -- see the branch
    below.
    """
    global _last_digests, _load_complete

    backend = get_session_backend()
    loaded = backend.load_all()
    if loaded is None:
        # Deliberately KEEPING _last_digests. A failed read is not new
        # information: what we believed was persisted still is, because
        # nothing was written or deleted to change it. Clearing the map here
        # would erase the only evidence of what exists, and pruning would then
        # have nothing left to defer -- turning the guard below into decoration.
        _load_complete = False
        logger.warning(
            "Session load failed; the in-memory view may be incomplete. "
            "Writes will upsert but NOT delete until a load succeeds."
        )
        return {}

    _last_digests = {
        sid: _digest(session.model_dump(mode="json"))
        for sid, session in loaded.items()
    }
    _load_complete = True
    return loaded


def save_sessions(sessions: dict[str, SessionData]) -> None:
    """Persist the sessions that changed since the last write.

    Best-effort by contract: a persistence failure is logged, never raised,
    because it must not be the reason an audio request fails. What the backends
    report back decides whether a change is considered done, though -- see the
    digest docstring above.
    """
    global _last_digests

    backend = get_session_backend()

    with _save_lock:
        changed: dict[str, dict[str, Any]] = {}
        digests: dict[str, str] = {}
        for sid, session in sessions.items():
            payload = session.model_dump(mode="json")
            current = _digest(payload)
            digests[sid] = current
            if _last_digests.get(sid) != current:
                changed[sid] = payload

        dropped = set(_last_digests) - set(sessions)

        # `settled` is what we will BELIEVE is persisted once this call returns.
        # Anything unconfirmed keeps its previous digest so the next save
        # retries it, instead of being written off as done.
        settled = dict(digests)

        if changed and not backend.upsert_many(changed):
            for sid in changed:
                settled.pop(sid, None)

        if not dropped:
            _last_digests = settled
            return

        if not _load_complete:
            # The in-memory view may be missing sessions that are still stored.
            # Deleting on that evidence is how one timeout wipes the table.
            logger.warning(
                "Deferring the removal of %d session(s) (%s): the last full "
                "load did not succeed, so this in-memory view cannot prove "
                "they are really gone. Retried on a later save.",
                len(dropped),
                ", ".join(sorted(dropped)),
            )
        elif not backend.delete_many(dropped):
            for sid in dropped:
                settled[sid] = _last_digests[sid]

        _last_digests = settled