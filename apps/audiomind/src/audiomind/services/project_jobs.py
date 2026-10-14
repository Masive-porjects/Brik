"""Project-native mix and mastering job orchestration (WU5 closure).

Separates *submitting* a project job from *running* it, exactly like the
separation job: ``POST /projects/{id}/jobs/{mix,master}`` returns a job id
with 202 Accepted and the client polls ``GET /jobs/mix/{job_id}`` /
``GET /jobs/master/{job_id}`` while the DSP runs in a background task.

Why this module exists (and why it is not the legacy ``dsp_worker``)
-------------------------------------------------------------------
The statutory mastering path (``execute_master_job``) is incompatible with the
multi-tenant project model: it consumes Supabase Storage and the
``tracks``/``masters`` tables, while project jobs consume R2
(``projects/{project_id}/...`` keys) and ``audio_assets``. The compiler's
``MixPlan`` is the same intent both workers execute, so these are the
R2-native twins: same call shapes (``process_audio``, ``build_mix``) and the
same parameters overlay logic as ``build_job_parameters``.

The worker never raises: a failure is recorded on the job (``store.update``
with ``status=ERROR``) because an exception escaping into a BackgroundTask
would be logged and dropped, leaving the client polling a job that already
died.
"""

from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path
from typing import Any

from audiomind.config import settings
from audiomind.models.audio import MasteringParameters
from audiomind.processing.engine import process_audio
from audiomind.processing.mix_engine import build_mix
from audiomind.services import demo_guard, storage
from audiomind.services.compile_project import MixPlan
from audiomind.services.dsp_worker import PLATFORM_DELIVERY_TARGETS
from audiomind.services.job_store import JobRecord, JobStatus, get_job_store

logger = logging.getLogger(__name__)

#: Progress reported while the chain runs. Not a guess at a percentage: the
#: job is genuinely not finished, so it reports nothing accomplished. Same
#: honesty contract as the separation, mix and mastering jobs.
_RUNNING_PROGRESS = 0
_DONE_PROGRESS = 100


def _plan_payload(plan: MixPlan) -> dict[str, Any]:
    """JSON-encode the compiled plan for the job's ``meta``.

    ``parameters`` is stored set-fields-only on purpose: ``compile()`` builds
    the instance from the document's PARTIAL parameter dict, so a full dump
    would mark every pydantic default as "explicitly set" and the worker's
    overlay would clobber the preset/platform values with defaults. Keeping
    the set-only dump carries the document's real intent through JSON, the
    same way the HTTP payload carries it into ``build_job_parameters``.
    """
    payload = plan.model_dump(mode="json")
    if plan.parameters is not None:
        payload["parameters"] = plan.parameters.model_dump(exclude_unset=True)
    return payload


def submit_project_mix_job(
    project_id: str,
    user_id: str,
    asset_id: str | None,
    client: Any,
    plan: MixPlan,
) -> JobRecord:
    """Register a project mix job and return it in ``processing`` state.

    Resolves the source original asset — the given ``asset_id`` when present,
    otherwise the project's most recent ``kind='original'`` — and pins the
    compiled plan into the job's ``meta`` so the worker is fully
    self-contained: it must not re-read any document or state that could have
    changed while the job was queued.

    ``ValueError`` is raised for a missing/unowned source so the endpoint can
    answer 422 before anything is queued.
    """
    asset = _resolve_original_asset(client, project_id, user_id, asset_id)
    r2_key = str(asset.get("r2_key") or "")
    if not r2_key:
        raise ValueError(f"original asset {asset.get('id', '')} has no R2 key")
    store = get_job_store()
    record = store.create(
        "mix",
        meta={
            "user_id": user_id,
            "project_id": project_id,
            "asset_id": asset.get("id"),
            "r2_key": r2_key,
            "plan": _plan_payload(plan),
        },
    )
    logger.info(
        "Project mix job %s queued for project %s asset %s",
        record.job_id,
        project_id,
        asset.get("id"),
    )
    return record


def submit_project_master_job(
    project_id: str,
    user_id: str,
    asset_id: str | None,
    client: Any,
    plan: MixPlan,
) -> JobRecord:
    """Register a project mastering job and return it in ``processing`` state.

    Same contract as :func:`submit_project_mix_job`: the original asset is
    resolved and pinned into ``meta``, and the plan carries the mastering
    intent the worker will turn into DSP parameters.
    """
    asset = _resolve_original_asset(client, project_id, user_id, asset_id)
    r2_key = str(asset.get("r2_key") or "")
    if not r2_key:
        raise ValueError(f"original asset {asset.get('id', '')} has no R2 key")
    store = get_job_store()
    record = store.create(
        "master",
        meta={
            "user_id": user_id,
            "project_id": project_id,
            "asset_id": asset.get("id"),
            "r2_key": r2_key,
            "plan": _plan_payload(plan),
        },
    )
    logger.info(
        "Project master job %s queued for project %s asset %s",
        record.job_id,
        project_id,
        asset.get("id"),
    )
    return record


def run_project_mix_job(job_id: str) -> None:
    """Execute a submitted project mix job. Runs as the background task."""
    store = get_job_store()
    stop = threading.Event()
    store.update(job_id, progress=_RUNNING_PROGRESS, stage="download")
    heartbeat = threading.Thread(
        target=_heartbeat_loop, args=(store, job_id, stop), daemon=True
    )
    heartbeat.start()
    try:
        result = _execute_mix(job_id)
        store.update(
            job_id,
            status=JobStatus.COMPLETED,
            progress=_DONE_PROGRESS,
            result=result,
        )
        logger.info("Project mix job %s completed", job_id)
    except Exception as exc:
        logger.exception("Project mix job %s failed", job_id)
        store.update(
            job_id,
            status=JobStatus.ERROR,
            error=str(exc) or exc.__class__.__name__,
        )
    finally:
        stop.set()


def run_project_master_job(job_id: str) -> None:
    """Execute a submitted project mastering job. Runs as the background task."""
    store = get_job_store()
    stop = threading.Event()
    store.update(job_id, progress=_RUNNING_PROGRESS, stage="download")
    heartbeat = threading.Thread(
        target=_heartbeat_loop, args=(store, job_id, stop), daemon=True
    )
    heartbeat.start()
    try:
        result = _execute_master(job_id)
        store.update(
            job_id,
            status=JobStatus.COMPLETED,
            progress=_DONE_PROGRESS,
            result=result,
        )
        logger.info("Project master job %s completed", job_id)
    except Exception as exc:
        logger.exception("Project master job %s failed", job_id)
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
    died"; without it an OOM kill looks identical to a slow run and the
    client polls forever.
    """
    interval = max(5, settings.job_lease_seconds // 3)
    while not stop.wait(interval):
        store.heartbeat(job_id)


def _execute_mix(job_id: str) -> dict[str, Any]:
    """Download the original, run the mix engine, upload + register the mix.

    Returns the deliverable payload that goes on the completed job row.
    """
    store = get_job_store()
    record = store.get(job_id)
    if record is None:
        raise RuntimeError(f"Project mix job {job_id} is not registered")
    meta = record.meta if isinstance(record.meta, dict) else {}
    user_id, project_id, r2_key, plan = _worker_context(meta, job_id)

    with tempfile.TemporaryDirectory(prefix="project_mix_") as tmp:
        source = Path(tmp) / f"original{Path(r2_key).suffix or '.wav'}"
        storage.download_to(r2_key, str(source))

        store.update(job_id, stage="mix", progress=_RUNNING_PROGRESS)
        # dimension_profiles={} disables the dimension stage (neutral bypass);
        # None keeps the engine default. Same contract as services/mix_jobs.
        dimension_profiles = None if plan.get("dimension_enabled", True) else {}
        with demo_guard.gate():
            result = build_mix(
                session_id=job_id,
                input_path=str(source),
                dimension_profiles=dimension_profiles,
                auto_balance=bool(plan.get("auto_balance", False)),
                stem_trims=plan.get("stem_trims"),
            )
        if not result or not isinstance(result, dict):
            raise RuntimeError("Mix engine produced no result")
        local_path = result.get("mix_path")
        if not local_path or not Path(local_path).exists():
            raise RuntimeError("Mix engine produced no output file")

        key = storage.build_key("projects", project_id, "masters", f"{job_id}.wav")
        storage.upload_file(str(local_path), key, content_type="audio/wav")
        asset = _register_master_asset(
            client=_service_client(),
            project_id=project_id,
            user_id=user_id,
            r2_key=key,
            sample_rate=result.get("sample_rate"),
            duration_seconds=result.get("duration_seconds"),
            channels=result.get("channels"),
            asset_format="wav",
            size_bytes=Path(local_path).stat().st_size,
        )
        return {
            "r2_key": key,
            "asset_id": asset.get("id"),
            "project_id": project_id,
            "format": "wav",
            "sample_rate": result.get("sample_rate"),
            "duration_seconds": result.get("duration_seconds"),
        }


def _execute_master(job_id: str) -> dict[str, Any]:
    """Download the original, run the mastering chain, upload + register it.

    Returns the deliverable payload that goes on the completed job row.
    """
    store = get_job_store()
    record = store.get(job_id)
    if record is None:
        raise RuntimeError(f"Project master job {job_id} is not registered")
    meta = record.meta if isinstance(record.meta, dict) else {}
    user_id, project_id, r2_key, plan = _worker_context(meta, job_id)
    params = _build_plan_parameters(plan)
    client = _service_client()

    with tempfile.TemporaryDirectory(prefix="project_master_") as tmp:
        source = Path(tmp) / f"original{Path(r2_key).suffix or '.wav'}"
        storage.download_to(r2_key, str(source))
        output = Path(tmp) / "master.wav"

        store.update(job_id, stage="master", progress=_RUNNING_PROGRESS)
        with demo_guard.gate():
            engine_result = process_audio(
                input_path=source,
                output_path=output,
                params=params,
            )
        if not output.exists():
            raise RuntimeError("Mastering pipeline produced no output file")
        if not isinstance(engine_result, dict):
            engine_result = {}

        key = storage.build_key("projects", project_id, "masters", f"{job_id}.wav")
        storage.upload_file(str(output), key, content_type="audio/wav")
        asset = _register_master_asset(
            client=client,
            project_id=project_id,
            user_id=user_id,
            r2_key=key,
            sample_rate=engine_result.get("sample_rate"),
            duration_seconds=engine_result.get("duration_seconds"),
            channels=engine_result.get("channels"),
            asset_format=plan.get("format") or "wav",
            size_bytes=output.stat().st_size,
        )
        return {
            "r2_key": key,
            "asset_id": asset.get("id"),
            "project_id": project_id,
            "format": plan.get("format") or "wav",
            "sample_rate": engine_result.get("sample_rate"),
            "duration_seconds": engine_result.get("duration_seconds"),
        }


def _build_plan_parameters(plan: dict[str, Any]) -> MasteringParameters:
    """Turn the compiled plan's mastering intent into DSP parameters.

    Mirrors ``build_job_parameters`` (services/dsp_worker) without its
    Supabase concerns, in the same order: preset chain as the base, platform
    delivery targets second, the user's explicit parameter overlay (only the
    fields the document actually set) third, and the top-level bit depth last.
    """
    preset_id = plan.get("preset_id")
    if preset_id:
        from audiomind.api.mastering import _build_preset_params

        base = _build_preset_params(preset_id)
    else:
        base = MasteringParameters()

    # 2. Platform targets: the 7-value payload set of the document, of which
    #    club/cd have no MasteringParameters.platform_target literal and are
    #    applied through their LUFS/ceiling targets instead.
    platform = plan.get("platform_target")
    if platform and platform in PLATFORM_DELIVERY_TARGETS:
        targets = PLATFORM_DELIVERY_TARGETS[platform]
        base = base.model_copy(
            update={
                "target_lufs_db": targets["target_lufs"],
                "limiter_ceiling_db": targets["limiter_ceiling_db"],
            }
        )

    # 3. Explicit overrides: only fields the document actually set. The stored
    #    dump is a full MasteringParameters-shaped JSON, so re-validating it
    #    restores pydantic's field-set tracking and exclude_unset keeps the
    #    preset/platform values for every untouched knob.
    raw_params = plan.get("parameters")
    if isinstance(raw_params, dict) and raw_params:
        try:
            compiled = MasteringParameters(**raw_params)
        except Exception as exc:
            raise RuntimeError(f"invalid mastering parameters in plan: {exc}") from exc
        overlay = {
            k: v
            for k, v in compiled.model_dump(exclude_unset=True).items()
            if v is not None
        }
        if overlay:
            base = base.model_copy(update=overlay)

    # 4. Top-level bit depth always wins (same as the worker's last write).
    bit_depth = plan.get("output_bit_depth")
    if isinstance(bit_depth, int) and not isinstance(bit_depth, bool):
        base = base.model_copy(update={"output_bit_depth": bit_depth})
    return base


def _resolve_original_asset(
    client: Any,
    project_id: str,
    user_id: str,
    asset_id: str | None,
) -> dict[str, Any]:
    """The source original: the given asset when valid, else the newest one.

    Ownership is enforced the same way the API does: the ``user_id`` filter
    makes "not yours" and "does not exist" the same answer, and only
    ``kind='original'`` carries the full-range audio the mix/master chains
    consume.
    """
    if asset_id:
        resp = (
            client.table("audio_assets")
            .select("*")
            .eq("id", asset_id)
            .eq("project_id", project_id)
            .eq("user_id", user_id)
            .eq("kind", "original")
            .limit(1)
            .execute()
        )
        rows = _data(resp)
        if not rows:
            raise ValueError(
                f"no original asset {asset_id} in project {project_id}"
            )
        return rows[0]

    resp = (
        client.table("audio_assets")
        .select("*")
        .eq("project_id", project_id)
        .eq("user_id", user_id)
        .eq("kind", "original")
        .execute()
    )
    rows = _data(resp)
    if not rows:
        raise ValueError(f"project {project_id} has no original asset to process")
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    return rows[0]


def _register_master_asset(
    *,
    client: Any,
    project_id: str,
    user_id: str,
    r2_key: str,
    sample_rate: int | None,
    duration_seconds: float | None,
    channels: int | None,
    asset_format: str | None,
    size_bytes: int,
) -> dict[str, Any]:
    """Insert one ``kind='master'`` asset row and return it."""
    row = {
        "project_id": project_id,
        "user_id": user_id,
        "kind": "master",
        "r2_key": r2_key,
        "duration_seconds": duration_seconds,
        "sample_rate": sample_rate,
        "channels": channels,
        "format": asset_format,
        "size_bytes": size_bytes,
    }
    resp = client.table("audio_assets").insert(row).execute()
    rows = _data(resp)
    if not rows:
        raise RuntimeError("Could not register the master asset")
    return rows[0]


def _worker_context(
    meta: dict[str, Any], job_id: str
) -> tuple[str, str, str, dict[str, Any]]:
    """Pull the worker's self-contained context out of a job's ``meta``."""
    user_id = meta.get("user_id")
    project_id = meta.get("project_id")
    r2_key = meta.get("r2_key")
    plan = meta.get("plan")
    if not (user_id and project_id and r2_key):
        raise RuntimeError(f"Project job {job_id} is missing its context (meta)")
    if not isinstance(plan, dict):
        raise RuntimeError(f"Project job {job_id} has no compiled plan (meta)")
    return str(user_id), str(project_id), str(r2_key), plan


def _service_client() -> Any:
    """Service-role Supabase client (the worker acts on the user's behalf).

    Read dynamically from the module so tests can inject a fake through
    ``supabase_client.get_supabase_client``; the harness seals that factory
    to ``None`` at session scope, which surfaces as an explicit error here
    rather than a silent no-op.
    """
    from audiomind.services import supabase_client

    client = supabase_client.get_supabase_client()
    if client is None:
        raise RuntimeError(
            "Supabase is not configured; project jobs cannot run."
        )
    return client


def _data(resp: Any) -> list[dict[str, Any]]:
    """Rows from a PostgREST response, tolerating an empty/None payload."""
    rows = getattr(resp, "data", None)
    if not rows:
        return []
    if isinstance(rows, dict):
        return [rows]
    return [row for row in rows if isinstance(row, dict)]