"""Async mix job orchestration.

Separates *submitting* a mix from *running* it, so the HTTP response returns
immediately with a job id instead of holding a proxy connection open for the
whole DSP chain (the 502/504 that made long mixes unusable).

The work itself still runs in a ``BackgroundTasks`` entry. That is a
deliberate, bounded choice: the point of this module is the response, and the
*state* durability lives in ``job_store`` (Supabase), not in the task. If the
container dies mid-mix the row keeps its lease, the reader notices the lease
expired, and the job is reported as ``error`` instead of spinning forever.

Progress honesty
----------------
``progress`` here is REAL: 0 while the chain runs, 100 once the bytes exist
in R2. It is not a per-stage ticker. ``build_mix`` is a single 700-line call
with no progress callback, so any per-stage percentage would be invented by
this layer -- and the UI already used to invent one (``stageMsForDuration``).
Reporting a number nobody measured is how a progress bar becomes a lie, so
this module reports only what it can prove. Wiring a stage callback into the
DSP engine is the real fix and is tracked as follow-up work.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from audiomind.config import settings
from audiomind.processing.mix_engine import build_mix
from audiomind.services import demo_guard, storage
from audiomind.services.job_store import JobRecord, JobStatus, get_job_store

logger = logging.getLogger(__name__)

#: One heartbeat thread per running job would be wasteful; a single daemon
#: per process keeps every job's lease fresh while the DSP is in flight.

#: Progress reported while the chain is running. Not a guess at a percentage:
#: the job is genuinely not finished, so it reports nothing accomplished.
_RUNNING_PROGRESS = 0
_DONE_PROGRESS = 100


class MixJobOptions:
    """The validated mix options captured at submit time.

    Frozen at submit time on purpose: the job outlives the request, so it must
    not read from a Pydantic request model that is about to be freed.
    """

    __slots__ = ("dimension_enabled", "auto_balance", "stem_trims")

    def __init__(
        self,
        *,
        dimension_enabled: bool = True,
        auto_balance: bool = False,
        stem_trims: dict[str, float] | None = None,
    ) -> None:
        self.dimension_enabled = dimension_enabled
        self.auto_balance = auto_balance
        self.stem_trims = dict(stem_trims) if stem_trims else None


def submit_mix_job(
    session_id: str,
    options: MixJobOptions,
    *,
    original_path: str,
) -> JobRecord:
    """Register a mix job and return it in ``processing`` state.

    The caller is responsible for having validated the session and its audio
    first; this function only records intent durably.
    """
    store = get_job_store()
    record = store.create("mix", session_id=session_id)
    logger.info("Mix job %s queued for session %s", record.job_id, session_id)
    return record


def run_mix_job(job_id: str, session_id: str, options: MixJobOptions) -> None:
    """Execute a submitted mix job. Runs as the background task.

    Never raises: a failure is recorded on the job so the poller learns about
    it, because an exception escaping into a BackgroundTask would be logged
    and dropped, leaving the client waiting on a job that already died.
    """
    store = get_job_store()
    stop = threading.Event()
    store.update(job_id, progress=_RUNNING_PROGRESS)
    heartbeat = threading.Thread(
        target=_heartbeat_loop, args=(store, job_id, stop), daemon=True
    )
    heartbeat.start()
    try:
        _delivered = _execute(job_id, session_id, options)
        store.update(
            job_id,
            status=JobStatus.COMPLETED,
            progress=_DONE_PROGRESS,
            result=_delivered,
        )
        logger.info("Mix job %s completed", job_id)
    except Exception as exc:
        logger.exception("Mix job %s failed", job_id)
        _mark_mix_failed(session_id)
        store.update(
            job_id,
            status=JobStatus.ERROR,
            error=str(exc) or exc.__class__.__name__,
        )
    finally:
        stop.set()


def _heartbeat_loop(store: Any, job_id: str, stop: threading.Event) -> None:
    """Refresh the job lease until the job finishes.

    The lease is what lets a reader tell "still running" from "the worker
    died". Without it, an OOM kill during a mix looks identical to a slow mix.
    """
    interval = max(5, settings.job_lease_seconds // 3)
    while not stop.wait(interval):
        store.heartbeat(job_id)


def _execute(job_id: str, session_id: str, options: MixJobOptions) -> dict[str, Any]:
    """Run the DSP chain on the gated pool, then upload the result.

    ``get_or_create_flight`` is reused so a double-click submits ONE DSP run
    instead of two: concurrent jobs for the same session share a single
    Future. Waiting on that Future is safe because a Starlette background task
    runs in its own threadpool, never in the (possibly single-worker) DSP
    pool -- otherwise the wait would deadlock against its own gate.

    Returns the deliverable payload (R2 key + download URL + analysis).
    """
    outcome: dict[str, Any] = {}

    def _work() -> None:
        dimension_profiles: dict[str, dict[str, Any]] | None = (
            None if options.dimension_enabled else {}
        )
        outcome["result"] = build_mix(
            session_id,
            _original_path(session_id),
            dimension_profiles=dimension_profiles,
            auto_balance=options.auto_balance,
            stem_trims=options.stem_trims,
        )

    future = demo_guard.get_or_create_flight(session_id, f"job:{job_id}", _work)
    future.result()  # re-raises whatever the DSP raised
    result = outcome.get("result")
    if not result:
        raise RuntimeError("Mix pipeline produced no result")
    delivered = _deliver(result, session_id)
    _record_mix_on_session(
        session_id,
        local_path=result.get("mix_path"),
        r2_key=delivered["r2_key"],
        analysis=delivered["analysis"],
    )
    return delivered


def _original_path(session_id: str) -> str:
    from audiomind.api.upload import sessions

    session = sessions.get(session_id)
    if not session or not session.original_path:
        raise RuntimeError(f"Session {session_id} has no audio to mix")
    if not Path(session.original_path).exists():
        raise RuntimeError(f"Audio for session {session_id} is missing on disk")
    return str(session.original_path)


def _deliver(result: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Upload the mix to R2 and describe how to fetch it.

    The local ``mix_path`` is kept out of the job result on purpose: it is
    ephemeral on Railway, so advertising it as the deliverable is how a
    completed job ends up pointing at a file that no longer exists.
    """
    local_path = result.get("mix_path")
    if not local_path:
        raise RuntimeError("Mix pipeline produced no output file")

    key = storage.build_key("mixes", session_id, f"{session_id}_mix.wav")
    storage.upload_file(local_path, key, content_type="audio/wav")

    payload = {k: v for k, v in result.items() if k != "mix_path"}
    return {
        "r2_key": key,
        "download_url": storage.presigned_url(key),
        "content_type": "audio/wav",
        "analysis": payload,
        "mix_status": "completed",
    }


def _record_mix_on_session(
    session_id: str,
    *,
    local_path: str | None,
    r2_key: str,
    analysis: dict[str, Any],
) -> None:
    """Publish the delivered mix onto the session so mastering can consume it.

    This is the async twin of the writes at the end of the sync mix endpoint
    (``api/mix.py``). Without it the session keeps ``mix_status="processing"``
    forever: the client gate never opens, ``GET /audio/mix`` 404s, and
    ``_resolve_master_input`` silently falls back to mastering the ORIGINAL
    instead of the mix -- a wrong-output bug that reports no error.

    ``r2_key`` is the durable half. ``mix_path`` is a local path and Railway
    has no persistent disk, so the key is what lets a redeployed container
    re-fetch the bytes.

    Never raises: the audio is already in R2 by the time this runs, so failing
    the job over session bookkeeping would throw away a finished mix. The key
    is in the job payload regardless, so the client can still fetch it.
    """
    try:
        from audiomind.api.upload import sessions
        from audiomind.session_store import save_sessions

        session = sessions.get(session_id)
        if session is None:
            logger.warning(
                "Mix for session %s was delivered but the session is gone", session_id
            )
            return
        # Only record a local pointer that actually resolves. The container can
        # be replaced between the upload and this write, and a dead path would
        # send the resolver into a guaranteed 400 instead of falling back to R2.
        if local_path and Path(local_path).exists():
            session.mix_path = str(local_path)
        session.mix_r2_key = r2_key
        session.mix_metadata = analysis.get("mix_metadata")
        session.mix_analysis = {**analysis, "mix_status": "completed"}
        session.mix_status = "completed"
        demo_guard.touch(session_id)
        save_sessions(sessions)
        logger.info(
            "Session %s registered the delivered mix (r2_key=%s, local=%s)",
            session_id,
            r2_key,
            "yes" if session.mix_path else "no",
        )
    except Exception:
        logger.exception(
            "Mix for session %s is in R2 but could not be registered on the "
            "session; mastering will need source='mix' with a re-hydration",
            session_id,
        )


def _mark_mix_failed(session_id: str) -> None:
    """Record a failed mix on the session so the client gate stops waiting.

    ``mix_path`` / ``mix_analysis`` / ``mix_r2_key`` are intentionally left
    alone: they describe the last DELIVERED mix, which stays downloadable after
    a failed re-mix. Same contract as the sync endpoint's failure branch.

    Never raises -- it runs inside the job's own ``except``.
    """
    try:
        from audiomind.api.upload import sessions
        from audiomind.session_store import save_sessions

        session = sessions.get(session_id)
        if session is None:
            return
        session.mix_status = "failed"
        save_sessions(sessions)
    except Exception:
        logger.exception(
            "Could not mark the mix failed on session %s", session_id
        )
