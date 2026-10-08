"""Stateless mastering jobs API router (Fase 6).

Provides endpoints to trigger background or synchronous DSP mastering jobs
that read from and write to Supabase Cloud Storage and PostgreSQL.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    status,
)
from pydantic import BaseModel, field_validator

from audiomind.api.license import require_license
from audiomind.config import settings
from audiomind.services import demo_guard, storage
from audiomind.services.dsp_worker import (
    MasterJobPayload,
    execute_master_job,
    get_job_status,
    run_async_master_job,
)
from audiomind.services.job_store import get_job_store, is_stale, public_view
from audiomind.services.mix_jobs import MixJobOptions, run_mix_job, submit_mix_job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "/master",
    summary="Execute or enqueue a stateless mastering job",
    response_model=Any,
)
async def submit_master_job(
    payload: MasterJobPayload,
    background_tasks: BackgroundTasks,
    _: object = Depends(require_license),
) -> Any:
    """Submit a stateless DSP mastering job.

    Consumes audio from Supabase Storage or signed URL, executes AudioMind's
    13-stage mastering pipeline, uploads the final master to 'audio-masters',
    and updates 'public.masters' in Supabase PostgreSQL.

    If `is_async=True`, queues the job for background execution and immediately
    returns `{ job_id, status: 'processing' }` with HTTP 202.
    If `is_async=False`, runs synchronously and returns the complete `MasterJobResult`.

    For the async path the job record is written to the job store BEFORE the
    task is queued. The client polls as soon as it gets the response, so
    queueing first would leave a window where a fast poll 404s on a job that
    exists but has not been registered yet.
    """
    if payload.is_async:
        store = get_job_store()
        record = store.create("master", meta={"track_id": payload.track_id})
        logger.info(
            "Mastering job %s queued for track %s",
            record.job_id,
            payload.track_id,
        )
        background_tasks.add_task(run_async_master_job, payload, record.job_id)
        return {
            "job_id": record.job_id,
            "track_id": payload.track_id,
            "status": "processing",
            "message": "Mastering job queued in background",
        }

    # Synchronous execution
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    result = execute_master_job(payload, job_id=job_id)
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.error or "Mastering pipeline failed",
        )
    return result


@router.get(
    "/master/{job_id}",
    summary="Query status and result of a mastering job",
)
async def get_master_job(job_id: str) -> dict[str, Any]:
    """Retrieve the status and results of an asynchronous mastering job."""
    status_info = get_job_status(job_id)
    if not status_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mastering job '{job_id}' not found",
        )
    return status_info


@router.get(
    "/health",
    summary="Health check for the worker DSP subsystem",
)
async def jobs_health() -> dict[str, str]:
    """Worker health status."""
    return {"status": "ok", "subsystem": "dsp-worker"}


# ── Mix jobs ────────────────────────────────────────────────────────────
# Same shape as the mastering jobs above (``/jobs/<kind>`` submit +
# ``/jobs/<kind>/{job_id}`` poll, statuses processing|completed|error) so the
# frontend has ONE polling client and one state machine for every job kind.


class MixJobRequest(BaseModel):
    """Optional body of ``POST /jobs/mix``.

    Mirrors the options of the blocking ``POST /session/{id}/mix`` so the
    exact same mix can be requested either way, and the async path is a
    drop-in replacement that no longer holds the connection open.
    """

    dimension_enabled: bool = True
    auto_balance: bool = False
    stem_trims: dict[str, float] | None = None

    @field_validator("stem_trims")
    @classmethod
    def _validate_stem_trims(
        cls, value: dict[str, float] | None
    ) -> dict[str, float] | None:
        """Same strict contract as ``api.mix.MixRequest``: only the four
        ``{stem}_db`` keys inside the ±6 dB band, otherwise 422."""
        if value is None:
            return value
        from audiomind.api.mix import _STEM_TRIM_KEYS
        from audiomind.processing.stem_balance import TRIM_STEM_RANGE

        for key, db in value.items():
            if key not in _STEM_TRIM_KEYS:
                raise ValueError(
                    f"stem_trims key {key!r} not allowed; expected one of "
                    f"{', '.join(_STEM_TRIM_KEYS)}"
                )
            if not (TRIM_STEM_RANGE[0] <= db <= TRIM_STEM_RANGE[1]):
                raise ValueError(
                    f"stem_trims[{key}] must be in "
                    f"[{TRIM_STEM_RANGE[0]}, {TRIM_STEM_RANGE[1]}]"
                )
        return value


@router.post(
    "/mix/{session_id}",
    summary="Submit a mix job and return immediately (HTTP 202)",
    status_code=status.HTTP_202_ACCEPTED,
)
async def submit_mix(
    session_id: str,
    background_tasks: BackgroundTasks,
    payload: MixJobRequest | None = None,
    _: object = Depends(require_license),
) -> dict[str, Any]:
    """Queue the Mix Engine for a session and return a job id at once.

    This is the non-blocking twin of ``POST /api/session/{id}/mix``. The
    difference is not cosmetic: the blocking form holds the HTTP connection
    for the whole DSP chain, which is what an edge proxy answers with 502/504
    once the mix outlasts the proxy timeout. This returns in milliseconds and
    lets the client poll ``GET /jobs/mix/{job_id}`` for the real state.

    The heavy chain still runs in the same gated pool as the blocking
    endpoint, so the DSP concurrency policy is unchanged.
    """
    from audiomind.api.upload import sessions

    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.original_path or not Path(session.original_path).exists():
        raise HTTPException(
            status_code=400, detail="No audio file found for this session"
        )
    if demo_guard.duration_over_limit(
        session.analysis.duration_seconds if session.analysis else None
    ):
        raise HTTPException(
            status_code=422,
            detail=demo_guard.demo_duration_message(
                settings.demo_max_duration_seconds
            ),
        )

    request = payload or MixJobRequest()
    options = MixJobOptions(
        dimension_enabled=request.dimension_enabled,
        auto_balance=request.auto_balance,
        stem_trims=request.stem_trims,
    )
    record = submit_mix_job(
        session_id, options, original_path=str(session.original_path)
    )

    # Mark the session as mixing BEFORE the task starts so a concurrent
    # GET /session/{id} never reports a running mix as absent.
    session.mix_status = "processing"

    background_tasks.add_task(run_mix_job, record.job_id, session_id, options)
    return {
        "job_id": record.job_id,
        "session_id": session_id,
        "status": record.status.value,
        "poll_url": f"/api/jobs/mix/{record.job_id}",
    }


@router.get(
    "/mix/{job_id}",
    summary="Query status and result of a mix job",
)
async def get_mix_job(job_id: str) -> dict[str, Any]:
    """Report the state of a submitted mix job.

    A job whose worker died mid-mix is reported as ``error``: the worker is
    what normally writes the terminal state, so a dead worker would otherwise
    leave a ``processing`` row that the client polls forever. The lease is
    what makes that orphan detectable.
    """
    store = get_job_store()
    record = store.get(job_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Mix job '{job_id}' not found",
        )
    if is_stale(record):
        return {
            **public_view(record),
            "status": "error",
            "error": "The job was interrupted (the worker stopped before it finished)",
        }
    return {**public_view(record), **_fresh_download(record)}


def _fresh_download(record: Any) -> dict[str, Any]:
    """Re-sign the R2 URL on every read instead of persisting a dead one.

    The presigned URL minted when the job completed expires (1 h by
    default). If it were stored in the job row, any mix finished more than
    an hour ago would hand the client a 403 on a job that is perfectly
    valid — and there would be no way to recover it, because the only copy
    of the URL was the expired one. So the row keeps the stable ``r2_key``
    and the URL is minted per request:

    - ``r2_public_url`` configured → stable public URL, never expires.
    - otherwise → fresh presigned URL for the same key.
    """
    if getattr(record, "status", None) != "completed":
        return {}
    result = getattr(record, "result", None)
    if not isinstance(result, dict):
        return {}
    key = result.get("r2_key")
    if not key:
        # A completed row without a key has nothing to re-sign. Returning it
        # untouched is better than inventing a URL that 403s.
        return {}
    if settings.r2_public_url:
        url = f"{settings.r2_public_url.rstrip('/')}/{key}"
    else:
        try:
            url = storage.presigned_url(key)
        except storage.StorageError:
            # R2 unreachable right now: the row is still valid, we just
            # cannot sign for it. Better an absent URL the client can
            # re-request than a 500.
            logger.warning("Could not re-sign R2 url for %s", key, exc_info=True)
            return {}
    return {"result": {**result, "download_url": url}}


# ── Stem separation jobs ──────────────────────────────────────────────────
# Same /jobs/<kind>/{job_id} shape as mastering and mix so the frontend keeps
# one polling client and one state machine for every job kind.


#: Reported when a job outlived its lease. Same reason as the mix job: a
#: worker killed mid-Demucs cannot write the reason itself.
_STALE_SEPARATE_ERROR = (
    "The job was interrupted (the worker stopped before it finished)"
)


@router.get(
    "/separate/{job_id}",
    summary="Query status and result of a stem-separation job",
)
async def get_separate_job(job_id: str) -> dict[str, Any]:
    """Report the state of a submitted separation job.

    A job whose worker died is reported as ``error`` via the lease, exactly
    like the mix job. On completion every stem gets a freshly minted download
    URL: the R2 presigned URL is never persisted, because any separation older
    than its expiry would otherwise hand the client a 403 on a valid job.
    """
    store = get_job_store()
    record = store.get(job_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Separate job '{job_id}' not found",
        )
    if is_stale(record):
        return {
            **public_view(record),
            "status": "error",
            "error": _STALE_SEPARATE_ERROR,
        }
    return {**public_view(record), **_fresh_stem_urls(record)}


def _fresh_stem_urls(record: Any) -> dict[str, Any]:
    """Re-sign each stem's R2 URL on read instead of persisting dead ones.

    The result's ``stems`` list holds the stable ``r2_key`` for every stem; a
    presigned URL minted at completion expires, so it is minted per request
    here (the same reasoning as ``_fresh_download`` for the mix job).
    """
    if getattr(record, "status", None) != "completed":
        return {}
    result = getattr(record, "result", None)
    if not isinstance(result, dict):
        return {}
    stems = result.get("stems")
    if not isinstance(stems, list):
        return {}

    signed: list[Any] = []
    for stem in stems:
        if not isinstance(stem, dict):
            signed.append(stem)
            continue
        key = stem.get("r2_key")
        if not key:
            signed.append(stem)
            continue
        try:
            if settings.r2_public_url:
                url = f"{settings.r2_public_url.rstrip('/')}/{key}"
            else:
                url = storage.presigned_url(key)
            signed.append({**stem, "download_url": url})
        except storage.StorageError:
            logger.warning("Could not re-sign stem url for %s", key, exc_info=True)
            signed.append(stem)
    return {"result": {**result, "stems": signed}}

