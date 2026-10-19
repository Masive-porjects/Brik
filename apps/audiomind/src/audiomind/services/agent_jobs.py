"""Async agentic mix+master job orchestration.

Separates *submitting* the Productor IA from *running* it, so the HTTP response
returns immediately with a job id instead of holding a proxy connection open for
the whole loop. One run is Demucs plus the mix chain plus N LLM turns: minutes,
not seconds, which is exactly the shape ``mix_jobs`` was written for.

Same contract as ``mix_jobs`` on purpose: ``GET /jobs/agent/{job_id}`` mirrors
``GET /jobs/mix/{job_id}`` (``processing | completed | error``), so the frontend
keeps ONE polling client and one state machine for every job kind.

Progress honesty
----------------
``progress`` here is REAL: 0 while the loop runs, 100 once the outputs exist. It
is not a per-phase ticker. ``agentic_loop.run`` exposes no phase callback, so any
per-stage percentage would be invented by this layer -- the same reasoning
``mix_jobs`` documents. Wiring a phase callback into the loop is the real fix.

Evidence, not inference
-----------------------
``tools_executed`` is ``AgentState.tool_log``: the actual ``ToolResult`` objects,
in execution order. "Separation ran" is proven by its result, never deduced from
``state.stems`` happening to be non-empty.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from audiomind.config import settings
from audiomind.processing import agentic_loop
from audiomind.processing.agentic_loop import AgentState, ToolResult
from audiomind.services import demo_guard, storage
from audiomind.services.job_store import JobRecord, JobStatus, get_job_store

logger = logging.getLogger(__name__)

#: Progress while the loop runs. Not a guess at a percentage: the run is
#: genuinely not finished, so it reports nothing accomplished.
_RUNNING_PROGRESS = 0
_DONE_PROGRESS = 100

#: The loop reports no stage, so the job reports the only one it can prove.
_RUNNING_STAGE = "agent"


def ensure_transport_available() -> None:
    """Preflight: fail at submit time, not in the background.

    Building the transport performs no network I/O -- it validates
    configuration (known provider, host/model/credential present). Discarding
    the instance is cheap; without this check a deployment with no usable
    credential would answer 202 and then die in the background, while the client
    polls a job that could never have run.

    Raises ``TransportUnavailableError`` (``GeminiUnavailableError`` inherits
    from it), which the API turns into a 503.
    """
    agentic_loop.default_transport()


def submit_agent_job(session_id: str, *, prompt: str | None = None) -> JobRecord:
    """Register an agent job and return it in ``processing`` state.

    The caller is responsible for having validated the session and its audio
    first; this function only records intent durably. ``prompt`` is stored as
    job meta for observability -- the runner receives the value itself, so the
    job never depends on reading it back.
    """
    store = get_job_store()
    record = store.create("agent", session_id=session_id, meta={"prompt": prompt})
    logger.info("Agent job %s queued for session %s", record.job_id, session_id)
    return record


def run_agent_job(
    job_id: str,
    session_id: str,
    prompt: str | None = None,
    *,
    transport: Any | None = None,
) -> None:
    """Execute a submitted agent job. Runs as the background task.

    Never raises: a failure is recorded on the job so the poller learns about
    it, because an exception escaping into a BackgroundTask would be logged and
    dropped, leaving the client waiting on a job that already died.

    ``transport`` is injectable so tests can drive the whole HTTP surface with
    no network call. When omitted the loop builds the real one from
    ``LLM_PROVIDER``.
    """
    store = get_job_store()
    stop = threading.Event()
    store.update(job_id, progress=_RUNNING_PROGRESS, stage=_RUNNING_STAGE)
    heartbeat = threading.Thread(
        target=_heartbeat_loop, args=(store, job_id, stop), daemon=True
    )
    heartbeat.start()

    try:
        state = _execute(session_id, job_id=job_id, prompt=prompt, transport=transport)
        store.update(
            job_id,
            status=JobStatus.COMPLETED,
            progress=_DONE_PROGRESS,
            stage="done",
            result=build_agent_result(state, _deliver(state)),
        )
        logger.info("Agent job %s completed", job_id)
    except Exception as exc:  # noqa: BLE001 -- the job record is the report
        logger.exception("Agent job %s failed", job_id)
        store.update(
            job_id,
            status=JobStatus.ERROR,
            error=str(exc) or exc.__class__.__name__,
        )
    finally:
        stop.set()


def _execute(
    session_id: str,
    *,
    job_id: str,
    prompt: str | None,
    transport: Any | None,
) -> AgentState:
    """Resolve the session's audio and run the loop on the gated DSP pool.

    ``get_or_create_flight`` is reused for the POOL, not for de-duplication: the
    key carries the job id, so two runs for the same session never share a
    Future (they may carry different prompts). Waiting on the Future is safe
    because a Starlette background task runs in its own threadpool, never in the
    (possibly single-worker) DSP pool.
    """
    input_path = _original_path(session_id)
    captured: dict[str, AgentState] = {}

    def _work() -> None:
        captured["state"] = agentic_loop.run(
            session_id=session_id,
            input_path=input_path,
            transport=transport,
            prompt=prompt,
        )

    future = demo_guard.get_or_create_flight(session_id, f"job:{job_id}", _work)
    future.result()  # re-raises whatever the loop raised (e.g. no transport)

    state = captured.get("state")
    if state is None:
        raise RuntimeError("The agent loop produced no state")
    return state


def _original_path(session_id: str) -> str:
    """Resolve the session's source audio at RUN time, not at submit time.

    Twin of ``mix_jobs._original_path``: the job outlives the request, so the
    path is re-read here. A session that vanished between submit and run must
    fail with a reason, not mix an empty path.
    """
    from audiomind.api.upload import sessions

    session = sessions.get(session_id)
    if not session or not session.original_path:
        raise RuntimeError(f"Session {session_id} has no audio to mix")
    if not Path(session.original_path).exists():
        raise RuntimeError(f"Audio for session {session_id} is missing on disk")
    return str(session.original_path)


def _heartbeat_loop(store: Any, job_id: str, stop: threading.Event) -> None:
    """Refresh the job lease until the job finishes.

    The lease is what lets a reader tell "still running" from "the worker died".
    Without it an OOM kill mid-loop looks identical to a slow loop.

    Twin of ``mix_jobs._heartbeat_loop``: kept local rather than imported so the
    two services stay independent.
    """
    interval = max(5, settings.job_lease_seconds // 3)
    while not stop.wait(interval):
        store.heartbeat(job_id)


def build_agent_result(
    state: AgentState, assets: dict[str, dict[str, Any] | None]
) -> dict[str, Any]:
    """The client-facing payload: what the agent decided, did, measured, left.

    Every field comes from recorded evidence:

    * ``diagnosis`` -- the model's phase-1 text;
    * ``tools_executed`` -- the real ``tool_log``, in order;
    * ``mix_metrics`` -- ``agentic_loop.bus_metrics``, the same helper the
      ``analyze_mix_bus`` tool uses, so the payload cannot drift from it;
    * ``master_metrics`` -- the payload of the successful ``send_to_master``;
    * ``analysis`` / ``intent`` -- the measurements and the 9 semantic axes.

    Nothing is inferred from a field being populated. ``intent`` and ``analysis``
    are dumped in JSON mode so the payload is safe for the durable store.
    """
    master_runs = [
        result
        for result in state.tool_log
        if result.tool == "send_to_master" and result.ok
    ]

    return {
        "session_id": state.session_id,
        "diagnosis": state.diagnosis,
        "iterations": state.iteration,
        "intent": state.intent.model_dump(mode="json"),
        "analysis": (
            state.analysis.model_dump(mode="json") if state.analysis else None
        ),
        # A report only exists when a render did; `bus_metrics` on a missing
        # render would describe a bus nobody built.
        "mix_metrics": agentic_loop.bus_metrics(state) if state.render else None,
        "master_metrics": _master_metrics(master_runs[-1]) if master_runs else None,
        "tools_executed": [
            {
                "tool": result.tool,
                "ok": result.ok,
                "detail": result.detail,
                "payload": result.payload,
                "error": result.error,
            }
            for result in state.tool_log
        ],
        "audio": assets,
    }


#: Keys of the ``send_to_master`` payload that describe where the file sat, not
#: how it measures. They are ephemeral on Railway and already delivered as an
#: asset, so advertising them inside the metrics is the same mistake the mix job
#: avoids by dropping ``mix_path``.
_MASTER_LOCATION_KEYS = frozenset({"master_path", "source_path"})


def _master_metrics(result: ToolResult) -> dict[str, Any]:
    """The measured numbers from a successful master, without its locations."""
    return {
        key: value
        for key, value in result.payload.items()
        if key not in _MASTER_LOCATION_KEYS
    }


def _deliver(state: AgentState) -> dict[str, dict[str, Any] | None]:
    """Upload the agent's outputs to R2 and describe how to fetch them.

    Mirrors ``mix_jobs._deliver``: the LOCAL path never travels as the
    deliverable, because it is ephemeral on Railway -- advertising it is how a
    completed job ends up pointing at a file that no longer exists.

    R2 absent is NOT fatal here, unlike the mix job. The diagnosis and the
    metrics are this job's primary deliverable and are already computed, so
    failing the run over an unconfigured bucket would throw away minutes of DSP.
    The asset degrades to a local path explicitly labelled as ephemeral.
    """
    return {
        "mix": _upload("mix", state.mix_path, state.session_id),
        "master": _upload("master", state.master_path, state.session_id),
    }


def _upload(
    kind: str, local_path: str | None, session_id: str
) -> dict[str, Any] | None:
    """Upload one agent output; ``None`` when the loop never produced it."""
    if not local_path:
        return None

    path = Path(local_path)
    if not path.exists():
        logger.warning(
            "Agent %s output vanished before upload: %s", kind, local_path
        )
        return None

    prefix = "mixes" if kind == "mix" else "masters"
    try:
        key = storage.build_key(prefix, session_id, path.name)
        storage.upload_file(str(path), key, content_type="audio/wav")
        url = storage.presigned_url(key)
    except storage.StorageError as exc:
        logger.warning(
            "R2 unavailable for the agent %s (%s); the payload carries an "
            "ephemeral local path instead. Configure R2 for a durable URL.",
            kind,
            exc,
        )
        return {
            "r2_key": None,
            "url": None,
            "local_path": str(path),
            "durable": False,
            "note": (
                "R2 is not configured: this path lives on the backend and does "
                "not survive a redeploy."
            ),
        }

    return {
        "r2_key": key,
        "url": url,
        "local_path": None,
        "durable": True,
        "note": None,
    }
