"""Async stem-separation job orchestration (Moises-style).

Separates *submitting* a Demucs run from *running* it, exactly like the mix
job: ``POST /projects/{id}/separate`` returns a job id in milliseconds and the
client polls ``GET /jobs/separate/{job_id}`` while Demucs runs in a background
task. Holding the HTTP connection for the whole separation is what an edge
proxy answers with 502/504 once it outlasts the proxy timeout.

Idempotency
-----------
Separating the same audio twice must not run Demucs twice. A separation is
keyed by a SHA-256 ``media_hash`` of the source bytes: when a completed
``separate`` job already exists for this user + project + hash, the new job is
completed immediately by reusing the stems that job already delivered -- no
Demucs, no re-upload.

The hash is normally known at submit time because the browser reports it on
upload (``AssetComplete.media_hash``). When it is not, the worker computes it
from the downloaded bytes, backfills it onto the original asset (so the next
submit can probe without re-downloading) and onto its own job row (so after it
finishes the next probe finds *it*), then re-probes before spending Demucs
time.

Reuse is deliberately scoped to one project: the stems are registered under
that project, and reusing them for a different document would hand back assets
owned by the wrong project.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiomind.config import settings
from audiomind.processing.splitter import STEM_NAMES, split_audio
from audiomind.services import demo_guard, storage
from audiomind.services.job_store import JobStatus, get_job_store

logger = logging.getLogger(__name__)

#: Progress reported while the chain runs. Not a guess at a percentage: the
#: job is genuinely not finished, so it reports nothing accomplished. Same
#: honesty contract as the mix and mastering jobs.
_RUNNING_PROGRESS = 0
_DONE_PROGRESS = 100

_DEFAULT_MODEL = "htdemucs"


@dataclass(frozen=True)
class SeparateSubmitOutcome:
    """What the submit endpoint needs to answer the client."""

    reused: bool
    status: str
    job_id: str
    result: dict[str, Any] | None = None


def submit_separate_job(
    *,
    user_id: str,
    project_id: str,
    asset_id: str,
    media_hash: str | None,
    model: str = _DEFAULT_MODEL,
    background_tasks: Any,
) -> SeparateSubmitOutcome:
    """Register a separate job (or reuse a finished one) and enqueue the work.

    Called by the endpoint after ownership checks. Probes for an already
    completed separation of the same bytes first; only creates + enqueues a
    fresh job when there is nothing to reuse.
    """
    store = get_job_store()

    if media_hash:
        existing = store.find_completed_separate(user_id, project_id, media_hash, "")
        if existing is not None:
            logger.info(
                "Separate for project %s reused stems from job %s",
                project_id,
                existing.job_id,
            )
            return SeparateSubmitOutcome(
                reused=True,
                status="completed",
                job_id=existing.job_id,
                result=existing.result if isinstance(existing.result, dict) else None,
            )

    record = store.create(
        "separate",
        meta={
            "user_id": user_id,
            "project_id": project_id,
            "asset_id": asset_id,
            "media_hash": media_hash,
            "model": model,
        },
    )
    background_tasks.add_task(run_separate_job, record.job_id)
    logger.info(
        "Separate job %s queued for project %s asset %s",
        record.job_id,
        project_id,
        asset_id,
    )
    return SeparateSubmitOutcome(
        reused=False, status="processing", job_id=record.job_id
    )


def run_separate_job(job_id: str) -> None:
    """Execute a submitted separate job. Runs as the background task.

    Never raises: a failure is recorded on the job so the poller learns about
    it, because an exception escaping into a BackgroundTask would be logged and
    dropped, leaving the client waiting on a job that already died.
    """
    store = get_job_store()
    stop = threading.Event()
    store.update(job_id, progress=_RUNNING_PROGRESS, stage="download")
    heartbeat = threading.Thread(
        target=_heartbeat_loop, args=(store, job_id, stop), daemon=True
    )
    heartbeat.start()
    try:
        result = _execute(job_id)
        store.update(
            job_id,
            status=JobStatus.COMPLETED,
            progress=_DONE_PROGRESS,
            result=result,
        )
        logger.info("Separate job %s completed", job_id)
    except Exception as exc:
        logger.exception("Separate job %s failed", job_id)
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
    died". Without it, an OOM kill during Demucs looks identical to a slow
    separation, and the client polls forever.
    """
    interval = max(5, settings.job_lease_seconds // 3)
    while not stop.wait(interval):
        store.heartbeat(job_id)


def _execute(job_id: str) -> dict[str, Any]:
    """Download the original, reuse or run Demucs, upload + register the stems.

    Returns the deliverable payload that goes on the completed job row.
    """
    store = get_job_store()
    record = store.get(job_id)
    if record is None:
        raise RuntimeError(f"Separate job {job_id} is not registered")
    meta = record.meta if isinstance(record.meta, dict) else {}
    user_id = meta.get("user_id")
    project_id = meta.get("project_id")
    asset_id = meta.get("asset_id")
    model = meta.get("model") or _DEFAULT_MODEL
    if not (user_id and project_id and asset_id):
        raise RuntimeError(f"Separate job {job_id} is missing its context (meta)")

    client = _service_client()
    original = _read_asset(client, asset_id)
    if original is None:
        raise RuntimeError(f"Original asset {asset_id} no longer exists")

    media_hash = meta.get("media_hash") or original.get("media_hash")

    # Reuse a finished separation of these same bytes before spending any
    # bandwidth or Demucs time.
    if media_hash:
        existing = store.find_completed_separate(
            user_id, project_id, media_hash, exclude_job_id=job_id
        )
        if existing is not None:
            logger.info(
                "Separate job %s reused stems from job %s", job_id, existing.job_id
            )
            return existing.result if isinstance(existing.result, dict) else {}

    r2_key = str(original.get("r2_key") or "")
    if not r2_key:
        raise RuntimeError(f"Original asset {asset_id} has no R2 key")

    with tempfile.TemporaryDirectory(prefix="separate_") as tmp:
        source = Path(tmp) / f"original{Path(r2_key).suffix or '.wav'}"
        storage.download_to(r2_key, str(source))

        if not media_hash:
            # Authoritative hash of the bytes we are about to separate. Backfill
            # it everywhere so this run is discoverable by the next probe.
            media_hash = _sha256(source)
            store.update(job_id, meta={"media_hash": media_hash})
            _backfill_media_hash(client, asset_id, user_id, project_id, media_hash)
            existing = store.find_completed_separate(
                user_id, project_id, media_hash, exclude_job_id=job_id
            )
            if existing is not None:
                return existing.result if isinstance(existing.result, dict) else {}

        store.update(job_id, stage="separate", progress=_RUNNING_PROGRESS)
        output_dir = Path(tmp) / "stems"
        # The gate is the DSP concurrency policy: Demucs reserves a lot of
        # memory and unbounded parallel runs are how the container OOMs.
        with demo_guard.gate():
            separated = split_audio(str(source), str(output_dir), model)

        stems = _deliver_stems(
            separated=separated,
            client=client,
            project_id=project_id,
            user_id=user_id,
            job_id=job_id,
            source_media_hash=media_hash,
        )
        return {
            "media_hash": media_hash,
            "project_id": project_id,
            "original_asset_id": asset_id,
            "sample_rate": separated.get("sample_rate"),
            "duration_seconds": separated.get("duration_seconds"),
            "stems": stems,
        }


def _deliver_stems(
    *,
    separated: dict[str, Any],
    client: Any,
    project_id: str,
    user_id: str,
    job_id: str,
    source_media_hash: str | None,
) -> list[dict[str, Any]]:
    """Upload every stem to R2 and register it as a project asset."""
    stem_paths = separated.get("stems") or {}
    sample_rate = separated.get("sample_rate")
    duration = separated.get("duration_seconds")
    delivered: list[dict[str, Any]] = []

    for name in STEM_NAMES:
        local = stem_paths.get(name)
        if not local or not Path(local).exists():
            raise RuntimeError(f"Demucs produced no {name} stem")
        key = storage.build_key(
            "projects", project_id, "stems", job_id, f"{name}.wav"
        )
        storage.upload_file(str(local), key, content_type="audio/wav")
        size = Path(local).stat().st_size
        asset = _register_stem(
            client=client,
            project_id=project_id,
            user_id=user_id,
            stem_name=name,
            r2_key=key,
            sample_rate=sample_rate,
            duration_seconds=duration,
            size_bytes=size,
            media_hash=source_media_hash,
        )
        delivered.append(
            {
                "asset_id": asset.get("id"),
                "stem_name": name,
                "r2_key": key,
                "sample_rate": sample_rate,
                "duration_seconds": duration,
                "size_bytes": size,
            }
        )
    return delivered


def _register_stem(
    *,
    client: Any,
    project_id: str,
    user_id: str,
    stem_name: str,
    r2_key: str,
    sample_rate: int | None,
    duration_seconds: float | None,
    size_bytes: int,
    media_hash: str | None,
) -> dict[str, Any]:
    """Insert one stem asset row and return it."""
    row = {
        "project_id": project_id,
        "user_id": user_id,
        "kind": "stem",
        "stem_name": stem_name,
        "r2_key": r2_key,
        # The stem inherits the SOURCE media_hash: it is the lineage key that
        # ties every stem back to the audio it came from, and it is what makes
        # "find everything derived from these bytes" a single index lookup.
        "media_hash": media_hash,
        "duration_seconds": duration_seconds,
        "sample_rate": sample_rate,
        "size_bytes": size_bytes,
    }
    resp = client.table("audio_assets").insert(row).execute()
    rows = _data(resp)
    if not rows:
        raise RuntimeError(f"Could not register the {stem_name} stem asset")
    return rows[0]


def _backfill_media_hash(
    client: Any,
    asset_id: str,
    user_id: str,
    project_id: str,
    media_hash: str,
) -> None:
    """Record the computed hash on the original so the next submit can probe.

    Never raises: the audio is already downloaded and the hash lives on the job
    row regardless, so failing this bookkeeping must not take down a run whose
    stems are on their way to R2.
    """
    try:
        (
            client.table("audio_assets")
            .update({"media_hash": media_hash})
            .eq("id", asset_id)
            .eq("user_id", user_id)
            .eq("project_id", project_id)
            .execute()
        )
    except Exception:
        logger.warning("Could not backfill media_hash on asset %s", asset_id)


def _service_client() -> Any:
    """Service-role Supabase client (the worker acts on the user's behalf).

    Read dynamically from the module so tests can inject a fake through
    ``supabase_client.get_supabase_client``; the harness seals that factory to
    ``None`` at session scope, which surfaces as an explicit error here rather
    than a silent no-op.
    """
    from audiomind.services import supabase_client

    client = supabase_client.get_supabase_client()
    if client is None:
        raise RuntimeError(
            "Supabase no está configurado; no se pueden separar stems."
        )
    return client


def _read_asset(client: Any, asset_id: str) -> dict[str, Any] | None:
    resp = (
        client.table("audio_assets")
        .select("*")
        .eq("id", asset_id)
        .limit(1)
        .execute()
    )
    rows = _data(resp)
    return rows[0] if rows else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _data(resp: Any) -> list[dict[str, Any]]:
    """Rows from a PostgREST response, tolerating an empty/None payload."""
    rows = getattr(resp, "data", None)
    if not rows:
        return []
    if isinstance(rows, dict):
        return [rows]
    return [row for row in rows if isinstance(row, dict)]
