"""Durable job store for long-running DSP work.

Why this module exists
----------------------
``FastAPI BackgroundTasks`` solves exactly one problem: the HTTP response
leaves before the heavy work finishes, so an edge proxy (Vercel/Railway) no
longer kills the connection with a 502/504. It solves nothing about
*survival*. The task lives in the worker process, so when the container is
restarted -- deploy, OOM, autoscaler scale-down -- the task is gone. The job
is still ``processing`` in whatever asked about it, and the client polls a
promise no process is keeping.

So the authoritative job state lives OUTSIDE the process:

* ``SupabaseJobStore`` writes to a Postgres table. State survives restarts,
  redeploys and scale events, and the worker running on a different replica
  can still read it.
* ``InMemoryJobStore`` keeps the same contract for local dev and tests.

Both are selected by ``get_job_store()`` from the environment, so a
misconfigured deployment degrades to an explicit warning instead of a
silent data-loss path.

Stale jobs
----------
Durability alone is not enough. A worker that dies mid-task still leaves a
``processing`` row behind, because the code that would have written
``completed`` died with it. Every job therefore carries a ``lease_expires_at``
and is heartbeated while it runs. A reader whose lease has expired treats the
job as abandoned and reports ``error`` (with a reason) instead of an eternal
``processing``. That is what stops the frontend from spinning forever.

Contract
--------
Status vocabulary is intentionally the same as the existing mastering jobs
(``dsp_worker``): ``processing`` | ``completed`` | ``error``. One vocabulary
for every job kind means one polling client and one UI state machine, instead
of two incompatible job systems in the same backend.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from audiomind.config import settings

logger = logging.getLogger(__name__)


class JobStatus(StrEnum):
    """Lifecycle of a durable job.

    Mirrors the mastering job vocabulary in ``dsp_worker`` on purpose:
    ``processing`` covers queued-and-running so the client has one branch for
    "not finished yet".
    """

    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"


TERMINAL_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.ERROR})


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def new_job_id(prefix: str = "job") -> str:
    """Opaque job identifier. Short and unguessable enough to poll, and
    carries its kind so a log line is self-describing."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class JobRecord(BaseModel):
    """A job as persisted. Field names are the Postgres column names."""

    job_id: str
    kind: str
    status: JobStatus = JobStatus.PROCESSING
    #: 0..100, best-effort. Only meaningful as UI feedback, never as truth.
    progress: int = 0
    #: Free-form stage label mirroring the DSP chain (see ``mixI18n``).
    stage: str | None = None
    #: Session this job belongs to, so a reload can reattach to its job.
    session_id: str | None = None
    #: Submit-time metadata that is *not* output. Kept separate from
    #: ``result`` so a reader can tell what the job was asked to do from what
    #: it produced: the mastering job needs its ``track_id`` back to answer
    #: ``GET /jobs/master/{id}``, and that is input, not a deliverable.
    meta: dict[str, Any] = Field(default_factory=dict)
    #: Kind-specific output (R2 key, download URL, analysis payload...).
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    #: Worker heartbeat. A reader past this instant considers the job dead.
    lease_expires_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


def _with_lease(record: JobRecord) -> JobRecord:
    """Stamp a fresh lease on a record that is about to be stored."""
    record.lease_expires_at = _now() + timedelta(seconds=settings.job_lease_seconds)
    record.updated_at = _now()
    return record


class JobStore(Protocol):
    """The persistence contract. Implementations must be safe to call from a
    request handler and from a background task."""

    def create(
        self,
        kind: str,
        *,
        session_id: str | None = None,
        result: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> JobRecord: ...

    def get(self, job_id: str) -> JobRecord | None: ...

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        progress: int | None = None,
        stage: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> JobRecord | None: ...

    def heartbeat(self, job_id: str) -> None: ...


class InMemoryJobStore:
    """Process-local store for local development and unit tests.

    NOT production-safe: everything dies with the process. It exists so the
    test suite and a laptop dev server exercise the same code path as
    production without requiring Supabase.
    """

    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}

    def create(
        self,
        kind: str,
        *,
        session_id: str | None = None,
        result: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> JobRecord:
        # An explicit id lets a worker that was handed a job_id register the
        # record under THAT id. Generating a fresh one would orphan it: the
        # poller would look up the caller's id and find nothing.
        record = _with_lease(
            JobRecord(
                job_id=job_id or new_job_id(kind),
                kind=kind,
                session_id=session_id,
                result=result or {},
                meta=meta or {},
            )
        )
        self._jobs[record.job_id] = record
        return record

    def get(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        progress: int | None = None,
        stage: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> JobRecord | None:
        record = self._jobs.get(job_id)
        if record is None:
            return None
        if status is not None:
            record.status = status
        if progress is not None:
            record.progress = max(0, min(100, progress))
        if stage is not None:
            record.stage = stage
        if result is not None:
            record.result = {**record.result, **result}
        if error is not None:
            record.error = error
        if record.is_terminal:
            # A finished job holds no lease: nothing is left to keep alive.
            record.lease_expires_at = None
        else:
            _with_lease(record)
        return record

    def heartbeat(self, job_id: str) -> None:
        record = self._jobs.get(job_id)
        if record is not None and not record.is_terminal:
            _with_lease(record)


class SupabaseJobStore:
    """Durable store backed by the ``dsp_jobs`` Postgres table.

    Reads and writes go through PostgREST. Every failure is logged and turned
    into a ``None``/no-op rather than an exception: job bookkeeping must never
    be the reason a user's audio request fails.
    """

    TABLE = "dsp_jobs"

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def probe(cls, client: Any) -> None:
        """Raise unless the job table is actually queryable.

        Deliberately a real read rather than a metadata check: Supabase
        reports a missing table, a revoked key and a disabled project
        differently, and this only needs to distinguish "usable" from
        "not usable" before we commit to the durable path. One row at
        startup is cheaper than a job that answers 202 and then 404s.
        """
        response = client.table(cls.TABLE).select("job_id").limit(1).execute()
        # A row-less result is fine: the table exists, it is just empty.
        if getattr(response, "data", None) is None:
            raise RuntimeError(f"Supabase returned no data for {cls.TABLE}")

    def _row(self, data: Any) -> JobRecord | None:
        if not data:
            return None
        row = data[0] if isinstance(data, list) else data
        if not isinstance(row, dict):
            return None
        try:
            return JobRecord.model_validate(row)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Unreadable job row dropped: %s", exc)
            return None

    def create(
        self,
        kind: str,
        *,
        session_id: str | None = None,
        result: dict[str, Any] | None = None,
        meta: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> JobRecord:
        # An explicit id lets a worker that was handed a job_id register the
        # record under THAT id. Generating a fresh one would orphan it: the
        # poller would look up the caller's id and find nothing.
        record = _with_lease(
            JobRecord(
                job_id=job_id or new_job_id(kind),
                kind=kind,
                session_id=session_id,
                result=result or {},
                meta=meta or {},
            )
        )
        payload = record.model_dump(mode="json")
        # mode="json" already renders every timestamp as an ISO-8601 string,
        # which is what the timestamptz columns expect; PostgREST casts it.
        # The lease has to go in the payload explicitly because ``_with_lease``
        # stamps the record after the model was built.
        payload["lease_expires_at"] = _iso(record.lease_expires_at)
        try:
            response = (
                self._client.table(self.TABLE)
                .insert(payload)
                .execute()
            )
            stored = self._row(getattr(response, "data", None))
            if stored is not None:
                return stored
        except Exception as exc:
            logger.error("Could not persist job %s: %s", record.job_id, exc)
        return record

    def get(self, job_id: str) -> JobRecord | None:
        try:
            response = (
                self._client.table(self.TABLE)
                .select("*")
                .eq("job_id", job_id)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            logger.error("Could not read job %s: %s", job_id, exc)
            return None
        return self._row(getattr(response, "data", None))

    def update(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        progress: int | None = None,
        stage: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> JobRecord | None:
        current = self.get(job_id)
        if current is None:
            return None

        patch: dict[str, Any] = {"updated_at": _iso(_now())}
        if status is not None:
            patch["status"] = status.value
        if progress is not None:
            patch["progress"] = max(0, min(100, progress))
        if stage is not None:
            patch["stage"] = stage
        if result is not None:
            patch["result"] = {**current.result, **result}
        if error is not None:
            patch["error"] = error

        if status is not None and status in TERMINAL_STATUSES:
            patch["lease_expires_at"] = None
        else:
            patch["lease_expires_at"] = _iso(
                _now() + timedelta(seconds=settings.job_lease_seconds)
            )

        try:
            response = (
                self._client.table(self.TABLE)
                .update(patch)
                .eq("job_id", job_id)
                .execute()
            )
        except Exception as exc:
            logger.error("Could not update job %s: %s", job_id, exc)
            return current
        return self._row(getattr(response, "data", None)) or current

    def heartbeat(self, job_id: str) -> None:
        try:
            self._client.table(self.TABLE).update(
                {
                    "updated_at": _iso(_now()),
                    "lease_expires_at": _iso(
                        _now() + timedelta(seconds=settings.job_lease_seconds)
                    ),
                }
            ).eq("job_id", job_id).execute()
        except Exception as exc:
            logger.warning("Heartbeat for job %s failed: %s", job_id, exc)


_store: JobStore | None = None


def get_job_store() -> JobStore:
    """Return the process-wide job store.

    Prefers Supabase (durable) and falls back to in-memory with a loud
    warning, because a laptop dev server has no Supabase credentials and
    should still work. A production deployment that forgot to configure
    Supabase therefore gets an obvious log line rather than silent job loss.

    Supabase is *already* configured in production for ``tracks`` and
    ``masters``, so "credentials present" says nothing about the job table.
    Without the probe below, a deployment missing ``dsp_jobs`` would pick the
    durable store, fail every write, still answer ``202`` on submit (the
    record is returned even when the insert failed) and then ``404`` on the
    first poll -- while the DSP happily ran and uploaded a mix nobody could
    ever fetch. Probing turns that into a log line and a working in-memory
    store, which is the correct behaviour when the table has not been
    created yet.
    """
    global _store
    if _store is not None:
        return _store

    if settings.supabase_url and (
        settings.supabase_service_role_key or settings.supabase_anon_key
    ):
        try:
            from audiomind.services.supabase_client import get_supabase_client

            client = get_supabase_client()
            if client is not None:
                SupabaseJobStore.probe(client)
                _store = SupabaseJobStore(client)
                logger.info(
                    "Durable job store: Supabase table %s", SupabaseJobStore.TABLE
                )
                return _store
        except Exception as exc:
            logger.warning(
                "Supabase job store unusable (%s); using the in-memory store. "
                "Job state will not survive a backend restart until the %s "
                "table exists. Supabase credentials alone are not enough: "
                "see supabase/migrations/ for the schema.",
                exc,
                SupabaseJobStore.TABLE,
            )

    logger.warning(
        "Falling back to the in-memory job store. Jobs will NOT survive a "
        "backend restart. Configure AUDIOMIND_SUPABASE_URL and "
        "AUDIOMIND_SUPABASE_SERVICE_ROLE_KEY for durable job state."
    )
    _store = InMemoryJobStore()
    return _store



def set_job_store(store: JobStore | None) -> None:
    """Override the process-wide store. Used by tests and by the app factory."""
    global _store
    _store = store


def is_stale(record: JobRecord) -> bool:
    """True when a non-terminal job outlived its lease.

    A worker that died mid-task cannot write ``error`` itself, so the reader
    detects the orphan. Without this the frontend would poll forever.
    """
    if record.is_terminal or record.lease_expires_at is None:
        return False
    return record.lease_expires_at < _now()


def public_view(record: JobRecord) -> dict[str, Any]:
    """The client-facing job payload.

    Deliberately flat and small: the frontend polls this every couple of
    seconds, and it must not have to know about leases or internal columns.
    """
    return {
        "job_id": record.job_id,
        "kind": record.kind,
        "status": record.status.value,
        "progress": record.progress,
        "stage": record.stage,
        "session_id": record.session_id,
        "result": record.result,
        "error": record.error,
        "created_at": _iso(record.created_at),
        "updated_at": _iso(record.updated_at),
    }
