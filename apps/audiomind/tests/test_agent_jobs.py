"""Agentic mix+master job: HTTP surface + result contract.

Covers what the frontend bridge exists for:

1. ``POST /jobs/agent/{session_id}`` returns immediately (202 + job id) instead
   of holding the connection open for Demucs + the mix chain + N LLM turns.
2. The poll payload carries the diagnosis, the tools that ACTUALLY ran, the bus
   metrics and a playable asset -- all from recorded evidence.
3. The failure modes are honest: 404/400/503 at submit, and ``error`` (never a
   hung ``processing``) when the run dies.

The loop is driven by a scripted transport and cheap tool stubs, so nothing here
touches Demucs, the network or R2. ``conftest`` already breaks
``storage.get_s3_client``, so the unconfigured-R2 path is the default.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import audiomind.api.upload as upload_mod
from audiomind.config import settings
from audiomind.main import app
from audiomind.models.audio import AnalysisResult, SessionData
from audiomind.models.intent_profile import IntentProfile
from audiomind.processing import agentic_loop as al
from audiomind.services import agent_jobs, storage
from audiomind.services.job_store import InMemoryJobStore, JobStatus, set_job_store

client = TestClient(app)

_SR = 44100
_STEMS = ("vocals", "drums", "bass", "other")


class _ScriptedTransport:
    """Replays turns and records the transcript each phase saw."""

    def __init__(self, script: list[al.ModelTurn]) -> None:
        self.script = list(script)
        self.transcripts: list[list[dict]] = []

    def turn(self, *, phase, system, transcript, tools):
        self.transcripts.append(list(transcript))
        if not self.script:
            raise AssertionError("el guion se quedó sin turnos")
        return self.script.pop(0)


class _BoomTransport:
    def turn(self, **kwargs):
        raise RuntimeError("proveedor caído")


def _script() -> list[al.ModelTurn]:
    """diagnose -> adjust -> render -> inspect -> master (QC clean, so it ends)."""
    return [
        al.ModelTurn(text="La voz está tapada y falta pegada."),
        al.ModelTurn(
            tool_calls=[
                al.ToolCall(
                    name="adjust_stem_parameters",
                    args={
                        "intent": IntentProfile(vocal_focus=0.8).model_dump(),
                        "rationale": "voz al frente",
                    },
                )
            ]
        ),
        al.ModelTurn(tool_calls=[al.ToolCall(name="render_mix", args={})]),
        al.ModelTurn(tool_calls=[al.ToolCall(name="analyze_mix_bus", args={})]),
        al.ModelTurn(
            tool_calls=[al.ToolCall(name="send_to_master", args={"source": "mix"})]
        ),
    ]


def _analysis(**overrides) -> AnalysisResult:
    base = {
        "integrated_lufs": -9.5,
        "true_peak_db": -1.0,
        "dynamic_range_db": 9.0,
        "spectral_centroid": 2000.0,
        "tempo_bpm": 120.0,
        "duration_seconds": 1.0,
        "sample_rate": _SR,
        "channels": 2,
        "detected_genre": "pop",
        "genre_confidence": 0.9,
    }
    base.update(overrides)
    return AnalysisResult(**base)


def _register_session(tmp_path: Path) -> str:
    """A real (tiny) audio file plus its session record."""
    session_id = str(uuid.uuid4())
    audio = tmp_path / f"{session_id}_orig.wav"
    sf.write(audio, np.zeros((_SR, 2), dtype=np.float32), _SR)
    upload_mod.sessions[session_id] = SessionData(
        session_id=session_id,
        original_path=str(audio),
        original_filename="orig.wav",
        analysis=_analysis(),
    )
    return session_id


@pytest.fixture
def agent_env(monkeypatch, tmp_path):
    """Temp dirs + in-memory job store + cheap DSP + offline LLM."""
    outputs = tmp_path / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "output_dir", outputs)
    monkeypatch.setattr(settings, "license_key", "")
    monkeypatch.setattr(settings, "demo_max_duration_seconds", 0.0)

    store = InMemoryJobStore()
    set_job_store(store)

    mix_file = outputs / "mix.wav"
    mix_file.write_bytes(b"RIFF")

    def fake_analyze(state, args):
        state.analysis = _analysis()
        return al.ToolResult(
            ok=True,
            tool="analyze_original_audio",
            detail="Métricas del original listas.",
            payload={"integrated_lufs": -9.5, "detected_genre": "pop"},
        )

    def fake_separate(state, args):
        state.stems = {name: f"{name}.wav" for name in _STEMS}
        return al.ToolResult(
            ok=True,
            tool="trigger_stem_separation",
            detail="4 stems.",
            payload={"stems": dict(state.stems), "stems_dir": str(state.stems_dir)},
        )

    def fake_render(state, args):
        state.render = {
            "mix_path": str(mix_file),
            # Clean QC: the loop converges instead of asking for another turn.
            "qc_report": {"summary": {"flagged": []}},
            "balance_report": {"ok": True},
            "trim_report": None,
            "stem_presence": {"vocals": 0.4},
            "mix_metadata": {"stem_lufs": {"vocals": -18.0}},
            "tempo_bpm": 120.0,
            "genre": "pop",
        }
        state.pending_settings = None
        state.iteration += 1
        state.mix_path = str(mix_file)
        return al.ToolResult(
            ok=True,
            tool="render_mix",
            detail="Bus renderizado.",
            payload={"mix_path": state.mix_path, "iteration": state.iteration},
        )

    def fake_process_audio(**kwargs):
        output = Path(kwargs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"RIFF")
        return {
            "output_path": str(output),
            "integrated_lufs": -14.0,
            "true_peak_db": -1.0,
            "crest_factor_db": 9.0,
            "lra": 5.0,
            "duration_seconds": 1.0,
            "output_bit_depth": kwargs["params"].output_bit_depth,
        }

    monkeypatch.setitem(al.TOOL_IMPLS, "analyze_original_audio", fake_analyze)
    monkeypatch.setitem(al.TOOL_IMPLS, "trigger_stem_separation", fake_separate)
    monkeypatch.setitem(al.TOOL_IMPLS, "render_mix", fake_render)
    monkeypatch.setattr(al, "process_audio", fake_process_audio)
    # The real factory would read LLM_PROVIDER; the stub keeps the run offline.
    monkeypatch.setattr(
        al, "default_transport", lambda **kwargs: _ScriptedTransport(_script())
    )

    yield SimpleNamespace(tmp_path=tmp_path, store=store, mix_file=mix_file)
    set_job_store(None)


class TestAgentJobRoute:
    def test_submit_returns_202_with_a_poll_url(self, agent_env):
        session_id = _register_session(agent_env.tmp_path)

        resp = client.post(f"/api/jobs/agent/{session_id}", json={})

        assert resp.status_code == 202
        body = resp.json()
        assert body["job_id"].startswith("agent_")
        assert body["session_id"] == session_id
        assert body["status"] == "processing"
        # The client must not have to know the route shape.
        assert body["poll_url"] == f"/api/jobs/agent/{body['job_id']}"

    def test_the_poll_payload_carries_the_whole_result(self, agent_env):
        session_id = _register_session(agent_env.tmp_path)
        job_id = client.post(
            f"/api/jobs/agent/{session_id}", json={"prompt": "voz al frente"}
        ).json()["job_id"]

        body = client.get(f"/api/jobs/agent/{job_id}").json()

        assert body["status"] == "completed"
        result = body["result"]

        # 1. The diagnosis in natural language.
        assert result["diagnosis"] == "La voz está tapada y falta pegada."

        # 2. The tools that actually ran, in execution order, with their output.
        assert [tool["tool"] for tool in result["tools_executed"]] == [
            "analyze_original_audio",
            "trigger_stem_separation",
            "adjust_stem_parameters",
            "render_mix",
            "analyze_mix_bus",
            "send_to_master",
        ]
        assert all(tool["ok"] for tool in result["tools_executed"])

        # 3. The final bus metrics, the 9-axis intent and the master metrics.
        assert result["mix_metrics"]["tempo_bpm"] == 120.0
        assert result["mix_metrics"]["stem_lufs"] == {"vocals": -18.0}
        assert result["intent"]["vocal_focus"] == 0.8
        assert result["analysis"]["integrated_lufs"] == -9.5
        assert result["master_metrics"]["integrated_lufs"] == -14.0
        assert result["iterations"] == 1

    def test_the_prompt_reaches_the_loop(self, agent_env, monkeypatch):
        seen: list[str] = []
        original = _ScriptedTransport.turn

        def recording(self, *, phase, system, transcript, tools):
            seen.append(transcript[0]["text"])
            return original(
                self, phase=phase, system=system, transcript=transcript, tools=tools
            )

        monkeypatch.setattr(_ScriptedTransport, "turn", recording)
        session_id = _register_session(agent_env.tmp_path)

        client.post(
            f"/api/jobs/agent/{session_id}", json={"prompt": "más aire en la voz"}
        )

        assert seen
        assert "más aire en la voz" in seen[0]

    def test_without_r2_the_audio_degrades_to_a_labelled_local_path(self, agent_env):
        """S5: an unconfigured bucket must not throw away a finished run."""
        session_id = _register_session(agent_env.tmp_path)
        job_id = client.post(f"/api/jobs/agent/{session_id}", json={}).json()["job_id"]

        audio = client.get(f"/api/jobs/agent/{job_id}").json()["result"]["audio"]

        assert audio["master"]["durable"] is False
        assert audio["master"]["url"] is None
        assert audio["master"]["local_path"]
        assert "does not survive a redeploy" in audio["master"]["note"]

    def test_with_r2_the_url_is_minted_on_every_read(self, agent_env, monkeypatch):
        monkeypatch.setattr(
            storage, "upload_file", lambda path, key, **kw: Path(path).read_bytes()
        )
        minted: list[str] = []

        def presign(key, **kw):
            minted.append(key)
            return f"https://r2.example/{key}?n={len(minted)}"

        monkeypatch.setattr(storage, "presigned_url", presign)

        session_id = _register_session(agent_env.tmp_path)
        job_id = client.post(f"/api/jobs/agent/{session_id}", json={}).json()["job_id"]

        first = client.get(f"/api/jobs/agent/{job_id}").json()["result"]["audio"]
        second = client.get(f"/api/jobs/agent/{job_id}").json()["result"]["audio"]

        assert first["master"]["durable"] is True
        assert first["master"]["r2_key"].startswith("masters/")
        assert first["mix"]["r2_key"].startswith("mixes/")
        # A stored URL would 403 an hour later; re-signing is the contract.
        assert first["master"]["url"] != second["master"]["url"]

    def test_unknown_session_is_404(self, agent_env):
        resp = client.post(f"/api/jobs/agent/{uuid.uuid4()}", json={})
        assert resp.status_code == 404

    def test_a_session_without_audio_is_400(self, agent_env):
        session_id = str(uuid.uuid4())
        upload_mod.sessions[session_id] = SessionData(session_id=session_id)

        resp = client.post(f"/api/jobs/agent/{session_id}", json={})

        assert resp.status_code == 400

    def test_no_usable_transport_is_503_not_a_doomed_job(self, agent_env, monkeypatch):
        def unavailable(**kwargs):
            raise al.TransportUnavailableError("no hay credencial del LLM")

        monkeypatch.setattr(al, "default_transport", unavailable)
        session_id = _register_session(agent_env.tmp_path)

        resp = client.post(f"/api/jobs/agent/{session_id}", json={})

        assert resp.status_code == 503
        assert "credencial" in resp.json()["detail"]
        # Nothing was queued: no job to poll for.
        assert agent_env.store._jobs == {}

    def test_an_unknown_body_field_is_rejected(self, agent_env):
        """`extra="forbid"`: a typo must be a 422, not a silently ignored order."""
        session_id = _register_session(agent_env.tmp_path)
        resp = client.post(f"/api/jobs/agent/{session_id}", json={"promt": "x"})
        assert resp.status_code == 422

    def test_an_unknown_job_is_404(self, agent_env):
        assert client.get(f"/api/jobs/agent/{uuid.uuid4()}").status_code == 404

    def test_a_dead_worker_is_reported_as_error(self, agent_env):
        # The worker is what normally writes the terminal state, so a worker
        # killed mid-run leaves `processing` behind. The lease is what makes
        # that orphan detectable instead of pollable forever.
        record = agent_env.store.create("agent", session_id="s1")
        record.lease_expires_at = datetime.now(UTC) - timedelta(hours=1)

        body = client.get(f"/api/jobs/agent/{record.job_id}").json()

        assert body["status"] == "error"
        assert "interrupted" in body["error"]


class TestAgentJobRunner:
    def test_submit_records_the_prompt_durably(self, agent_env):
        record = agent_jobs.submit_agent_job("s1", prompt="más graves")
        stored = agent_env.store.get(record.job_id)
        assert stored is not None
        assert stored.status is JobStatus.PROCESSING
        assert stored.kind == "agent"
        assert stored.meta["prompt"] == "más graves"

    def test_a_failing_loop_marks_the_job_as_error_and_never_raises(
        self, agent_env, monkeypatch
    ):
        monkeypatch.setattr(
            al, "default_transport", lambda **kwargs: _BoomTransport()
        )
        session_id = _register_session(agent_env.tmp_path)
        record = agent_jobs.submit_agent_job(session_id)

        agent_jobs.run_agent_job(record.job_id, session_id)  # must not raise

        stored = agent_env.store.get(record.job_id)
        assert stored is not None
        assert stored.status is JobStatus.ERROR
        assert "proveedor caído" in (stored.error or "")

    def test_a_missing_session_fails_with_a_reason(self, agent_env):
        record = agent_jobs.submit_agent_job("no-existe")

        agent_jobs.run_agent_job(record.job_id, "no-existe")

        stored = agent_env.store.get(record.job_id)
        assert stored is not None
        assert stored.status is JobStatus.ERROR
        assert "no-existe" in (stored.error or "")


class TestBuildAgentResult:
    def test_a_state_with_no_render_reports_no_bus_metrics(self):
        state = al.AgentState(session_id="s", input_path=Path("x.wav"))

        result = agent_jobs.build_agent_result(state, {"mix": None, "master": None})

        assert result["mix_metrics"] is None
        assert result["master_metrics"] is None
        assert result["tools_executed"] == []
        assert result["diagnosis"] is None
        assert result["audio"] == {"mix": None, "master": None}

    def test_master_metrics_come_from_the_recorded_tool_result(self):
        state = al.AgentState(session_id="s", input_path=Path("x.wav"))
        state.tool_log.append(
            al.ToolResult(
                ok=True,
                tool="send_to_master",
                detail="Master listo.",
                payload={"integrated_lufs": -14.0, "true_peak_db": -1.1},
            )
        )

        result = agent_jobs.build_agent_result(state, {"mix": None, "master": None})

        assert result["master_metrics"] == {
            "integrated_lufs": -14.0,
            "true_peak_db": -1.1,
        }

    def test_a_failed_master_is_not_reported_as_master_metrics(self):
        state = al.AgentState(session_id="s", input_path=Path("x.wav"))
        state.tool_log.append(
            al.ToolResult.fail("send_to_master", "mastering falló")
        )

        result = agent_jobs.build_agent_result(state, {"mix": None, "master": None})

        assert result["master_metrics"] is None
        assert result["tools_executed"][0]["ok"] is False
        assert result["tools_executed"][0]["error"] == "mastering falló"
