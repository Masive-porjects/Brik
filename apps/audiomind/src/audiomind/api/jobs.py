"""Stateless mastering jobs API router (Fase 6).

Provides endpoints to trigger background or synchronous DSP mastering jobs
that read from and write to Supabase Cloud Storage and PostgreSQL.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from audiomind.api.license import require_license
from audiomind.services.dsp_worker import (
    MasterJobPayload,
    execute_master_job,
    get_job_status,
    run_async_master_job,
)

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
    """
    job_id = f"job_{uuid.uuid4().hex[:12]}"

    if payload.is_async:
        background_tasks.add_task(run_async_master_job, payload, job_id)
        return {
            "job_id": job_id,
            "track_id": payload.track_id,
            "status": "processing",
            "message": "Mastering job queued in background",
        }

    # Synchronous execution
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
