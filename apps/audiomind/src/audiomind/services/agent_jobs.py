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

import json
import logging
import os
import tempfile
import threading
from contextlib import suppress
from pathlib import Path
from typing import Any

from audiomind.analysis.analyzer import analyze_audio
from audiomind.analysis.verdict import build_verdict
from audiomind.config import settings
from audiomind.processing import agentic_loop, prompts
from audiomind.processing.agentic_loop import (
    AgentState,
    Decision,
    DecisionRecord,
    ToolResult,
)
from audiomind.services import demo_guard, storage
from audiomind.services.job_store import JobRecord, JobStatus, get_job_store

logger = logging.getLogger(__name__)

#: Progress while the loop runs. Not a guess at a percentage: the run is
#: genuinely not finished, so it reports nothing accomplished.
_RUNNING_PROGRESS = 0
_DONE_PROGRESS = 100

#: The loop reports no stage, so the job reports the only one it can prove.
_RUNNING_STAGE = "agent"

#: Stage label of the analysis job. A distinct label because it is a distinct
#: stage: the frontend shows it while the user waits for the DECISION, not for
#: the audio.
_ANALYZING_STAGE = "analyzing"


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


def submit_analyze_job(session_id: str) -> JobRecord:
    """Register the analysis job — the FIRST breakpoint of the decision layer.

    A distinct ``kind`` (``agent_analyze``) rather than a flavour of ``agent``:
    the poller reconciles two different things over the same session, and a
    reader that cannot tell "the diagnosis is ready" from "the master is ready"
    would report a finished file for a job that never produced one.
    """
    store = get_job_store()
    record = store.create("agent_analyze", session_id=session_id)
    logger.info("Analyze job %s queued for session %s", record.job_id, session_id)
    return record


def run_analyze_job(
    job_id: str, session_id: str, *, transport: Any | None = None
) -> None:
    """Execute an analysis job. Runs as the background task.

    Never raises, for the same reason as ``run_agent_job``: an exception into a
    ``BackgroundTask`` is logged and dropped, leaving the client polling a job
    that already died.

    This run is SHORT by design -- one LLM turn plus the verdict. No Demucs, no
    render, no master. The user is waiting to be asked a question, so the job
    that asks it must not cost minutes.
    """
    store = get_job_store()
    stop = threading.Event()
    store.update(job_id, progress=_RUNNING_PROGRESS, stage=_ANALYZING_STAGE)
    heartbeat = threading.Thread(
        target=_heartbeat_loop, args=(store, job_id, stop), daemon=True
    )
    heartbeat.start()

    try:
        state = _execute_analyze(session_id, job_id=job_id, transport=transport)
        store.update(
            job_id,
            status=JobStatus.COMPLETED,
            progress=_DONE_PROGRESS,
            stage="done",
            result=build_analyze_result(state, {"mix": None, "master": None}),
        )
        logger.info("Analyze job %s completed", job_id)
    except Exception as exc:  # noqa: BLE001 -- the job record is the report
        logger.exception("Analyze job %s failed", job_id)
        store.update(
            job_id,
            status=JobStatus.ERROR,
            error=str(exc) or exc.__class__.__name__,
        )
    finally:
        stop.set()


def _execute_analyze(
    session_id: str, *, job_id: str, transport: Any | None
) -> AgentState:
    """Diagnose only: measure, build the verdict, persist it, one LLM turn.

    Deliberately does NOT call ``agentic_loop.run``. That function is the full
    chain and, even in ``master_only``, it ends by mastering the audio. Here the
    deliverable is a QUESTION for the user, so the run stops at the diagnosis.

    The measurable work is two steps and they are cheap compared with Demucs:

    1. ``analyze_audio`` -- loudness/crest/genre (the analysis phase the session
       may already have paid for).
    2. ``analyze_band_energies`` -- the per-band spectrum the deficiencies are
       derived from. This is what turns the verdict from "which route" into "and
       here is what is missing".

    The verdict is persisted on the session before the model speaks, so the user
    keeps it even if the LLM turn fails afterwards.
    """
    input_path = _original_path(session_id)
    captured: dict[str, AgentState] = {}

    def _work() -> None:
        from audiomind.api.upload import sessions

        state = AgentState(session_id=session_id, input_path=Path(input_path))
        session = sessions.get(session_id)

        analysis = session.analysis if session else None
        if analysis is None:
            # Re-measure only when the session has nothing. The submit path
            # already validates the file exists, so this is the reload case.
            analysis = analyze_audio(input_path)

        band_energies = _band_energies(input_path, analysis.sample_rate)
        verdict = build_verdict(analysis, band_energies)

        state.analysis = analysis
        state.verdict = verdict
        state.decision = DecisionRecord(
            requested="auto",
            applied=agentic_loop.resolve_decision("auto", verdict),
        )
        state.tool_log.append(
            ToolResult(
                ok=True,
                tool="analyze_original_audio",
                detail="Métricas del original listas.",
                payload=analysis.model_dump(mode="json"),
            )
        )

        if session is not None:
            session.analysis = analysis
            session.verdict = verdict

        state.diagnosis = _diagnose(state, transport)
        captured["state"] = state

    future = demo_guard.get_or_create_flight(session_id, f"job:{job_id}", _work)
    future.result()  # re-raises whatever the work raised

    state = captured.get("state")
    if state is None:
        raise RuntimeError("Analyze job produced no state")
    return state


def _band_energies(input_path: str, sample_rate: int) -> list[float] | None:
    """Per-band levels of the ORIGINAL, or ``None`` when they cannot be read.

    ``None`` (not ``[]``) on failure, because the two mean different things to
    ``build_verdict``: ``None`` = "the spectrum was not measured", so the verdict
    carries no deficiencies; an empty list would claim a measurement that came
    back empty. The verdict still ships -- the ROUTE never depends on the
    spectrum, so a decode failure here must not cost the user the decision.
    """
    try:
        import librosa
        import numpy as np

        from audiomind.analysis.analyzer import (
            TARGET_BANDS_HZ,
            analyze_band_energies,
        )

        y, sr = librosa.load(input_path, sr=None, mono=True)
        sr = int(sr) if sr else sample_rate
        return analyze_band_energies(np.asarray(y), sr, list(TARGET_BANDS_HZ))
    except Exception as exc:  # noqa: BLE001 -- the verdict must still ship
        logger.warning(
            "No se pudo medir el espectro de %s (%s); el veredicto viaja sin "
            "carencias por banda.",
            input_path,
            exc,
        )
        return None


def _diagnose(state: AgentState, transport: Any | None) -> str | None:
    """One LLM turn: the model verbalises the verdict. Never fatal.

    The verdict IS the deliverable and it is already computed. If the provider
    is unreachable or the credential is dead, the user still gets the route and
    the deficiencies; only the prose is missing. Failing the whole job here
    would throw away a measurement that succeeded in order to punish a summary
    that did not -- and the user would be left with no decision to make at all.

    Returns ``None`` when there is nothing to say, and the result builder then
    reports an absent diagnosis instead of an invented one.
    """
    try:
        if transport is None:
            transport = agentic_loop.default_transport()
        turn = transport.turn(
            phase="phase1",
            system=prompts.DIAGNOSIS_SYSTEM_PROMPT,
            transcript=_diagnosis_transcript(state),
            tools=[],
        )
        return turn.text or None
    except Exception as exc:  # noqa: BLE001 -- the verdict already shipped
        logger.warning(
            "El diagnóstico del análisis falló (%s); el veredicto igual viaja.",
            exc,
        )
        return None


def _diagnosis_transcript(state: AgentState) -> list[dict[str, Any]]:
    """The first turn of the loop, without running the loop.

    Same shape ``phase1_diagnose`` builds -- context block, verdict block,
    measurements -- so the model sees what it would see in a full run and its
    prose does not disagree with the verdict the user is reading.
    """
    measurements = (
        state.analysis.model_dump(mode="json") if state.analysis else {}
    )
    return [
        {
            "role": "user",
            "text": (
                prompts.context_block(state.intent.model_dump(), measurements)
                + prompts.verdict_block(state.verdict, applied="auto")
                + "\n\n<mediciones>\n"
                + json.dumps(measurements, indent=2, ensure_ascii=False)
                + "\n</mediciones>"
            ),
        }
    ]


def build_analyze_result(
    state: AgentState, assets: dict[str, dict[str, Any] | None]
) -> dict[str, Any]:
    """The analysis payload: the verdict, its explanation, and honest gaps.

    Distinct from ``build_agent_result`` in exactly the fields that differ:

    * ``verdict`` + ``decision`` -- what Brik proposes and what would run, so the
      UI can say "Brik propone esto, y esto es lo que va a correr".
    * no ``mix_metrics`` / ``master_metrics`` -- nothing was mixed or mastered,
      and reporting metrics for a bus nobody built would be a fabrication.

    ``assets`` is passed in rather than derived: this job uploads nothing, so the
    caller states that plainly (``{"mix": None, "master": None}``) instead of the
    builder pretending to deliver files.

    ``decision`` is RESOLVED here, not read off the state. This job never calls
    ``agentic_loop.run`` -- deliberately, since that function ends by mastering --
    so the state never passed through resolution and still carries
    ``DecisionRecord``'s default (``mix_then_master``, the historical route). That
    default would then sit next to a verdict recommending the short route and the
    payload would contradict itself on one screen. Resolving it here from the same
    verdict the payload ships is what keeps "Brik proposes X" and "X is what runs
    if you change nothing" from ever disagreeing.
    """
    applied = (
        agentic_loop.resolve_decision(
            state.decision.requested,
            state.verdict,
            state.reference_is_mastered,
        )
        if state.verdict is not None
        else state.decision.applied
    )

    return {
        "session_id": state.session_id,
        "diagnosis": state.diagnosis,
        "verdict": (
            state.verdict.model_dump(mode="json") if state.verdict else None
        ),
        "decision": {
            "requested": state.decision.requested,
            "applied": applied,
        },
        "analysis": (
            state.analysis.model_dump(mode="json") if state.analysis else None
        ),
        "mix_metrics": None,
        "master_metrics": None,
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


def run_agent_job(
    job_id: str,
    session_id: str,
    prompt: str | None = None,
    decision: Decision = "auto",
    *,
    transport: Any | None = None,
) -> None:
    """Execute a submitted agent job. Runs as the background task.

    Never raises: a failure is recorded on the job so the poller learns about
    it, because an exception escaping into a BackgroundTask would be logged and
    dropped, leaving the client waiting on a job that already died.

    ``decision`` is the user's final word, forwarded unchanged. It is read here
    rather than from job meta on purpose: the value the user chose is part of the
    call, so a job can never run a route the user did not pick because a meta row
    was stale or missing.

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
        state = _execute(
            session_id,
            job_id=job_id,
            prompt=prompt,
            decision=decision,
            transport=transport,
        )
        result = build_agent_result(state, _deliver(state))
        result["change_report"] = _change_report_block(state)
        store.update(
            job_id,
            status=JobStatus.COMPLETED,
            progress=_DONE_PROGRESS,
            stage="done",
            result=result,
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
    decision: Decision,
    transport: Any | None,
) -> AgentState:
    """Resolve the session's audio and run the loop on the gated DSP pool.

    The decision is resolved from EVIDENCE, not from what the request declared:
    the session's own verdict and reference are read here, at run time, and handed
    to ``agentic_loop.run`` so it can honour them. Passing the user's ``decision``
    without the verdict would leave every ``auto`` request on the historical
    four-phase path, because ``resolve_decision`` needs a verdict to follow.

    ``get_or_create_flight`` is reused for the POOL, not for de-duplication: the
    key carries the job id, so two runs for the same session never share a
    Future (they may carry different prompts). Waiting on the Future is safe
    because a Starlette background task runs in its own threadpool, never in the
    (possibly single-worker) DSP pool.
    """
    input_path = _original_path(session_id)
    captured: dict[str, AgentState] = {}

    def _work() -> None:
        from audiomind.api.upload import sessions

        session = sessions.get(session_id)
        verdict = session.verdict if session else None
        reference = session.reference_comparison if session else None
        # ``reference_is_mastered`` is NOT derivable from anything the session
        # stores today: ``ReferenceComparison`` measures bands, LUFS, crest and
        # LRA, and none of those says whether the reference is already mastered.
        # Inventing a heuristic here would be a second, parallel diagnosis -- the
        # exact thing this feature forbids. So it stays False and the resolver's
        # step 2 remains dormant until a real signal exists. Reported, not hidden.
        reference_is_mastered = False

        captured["state"] = agentic_loop.run(
            session_id=session_id,
            input_path=input_path,
            transport=transport,
            prompt=prompt,
            decision=decision,
            verdict=verdict,
            reference_comparison=reference,
            reference_is_mastered=reference_is_mastered,
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


def _change_report_block(state: AgentState) -> dict[str, Any]:
    """Compute, publish and mirror the before/after change report (S6).

    The job's completion never depends on the report: measurement and the
    R2 asset both degrade to honest statuses, mirroring ``_upload``'s
    degrade-not-fail contract. The block goes into ``result`` under
    ``change_report`` and the report itself is mirrored on the session so
    later chat turns can read it.
    """
    from audiomind.analysis.change_report import build_change_report
    from audiomind.api.upload import sessions as runtime_sessions
    from audiomind.session_store import save_sessions

    session = runtime_sessions.get(state.session_id)
    block: dict[str, Any] = {
        "report": {
            "status": "error",
            "message": "The change report was not available",
        },
        "r2_key": None,
        "url": None,
        "durable": False,
        "note": None,
    }
    try:
        report = build_change_report(
            before=session.analysis if session else None,
            input_path=(
                str(session.original_path)
                if session and session.original_path
                else None
            ),
            output_path=state.master_path,
        )
        payload = report.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001 -- the job record is the report
        logger.warning(
            "Agent job %s: change report could not be built: %s",
            state.session_id,
            exc,
        )
        payload = dict(block["report"])
    block["report"] = payload

    if session is not None:
        try:
            session.change_report = payload
            save_sessions(runtime_sessions)
        except Exception:  # noqa: BLE001 -- the mirror is best-effort
            logger.warning(
                "Agent job %s: the session mirror of the change report failed",
                state.session_id,
                exc_info=True,
            )

    if payload.get("status") == "ready":
        tmp_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".json", delete=False, mode="w", encoding="utf-8"
            ) as fh:
                tmp_name = fh.name
                json.dump(payload, fh)
            key = storage.build_key("reports", state.session_id, "change-report.json")
            storage.upload_file(tmp_name, key, content_type="application/json")
            block.update(
                r2_key=key, url=storage.presigned_url(key), durable=True
            )
        except storage.StorageError as exc:
            logger.warning(
                "R2 unavailable for the agent %s change report (%s); the "
                "inline payload still travels in the job result.",
                state.session_id,
                exc,
            )
            block["note"] = (
                "R2 is not configured: the inline report is served from the "
                "job result, this asset is not durable."
            )
        finally:
            if tmp_name:
                with suppress(OSError):
                    os.unlink(tmp_name)

    return block
