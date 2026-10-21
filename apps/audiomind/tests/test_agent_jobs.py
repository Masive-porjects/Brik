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
from audiomind.analysis.verdict import build_verdict
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


def _verdict(*, needs_mix: bool):
    """Un veredicto REAL, construido con ``build_verdict`` — no un stub.

    Pasarlo por la funcion de verdad mantiene honesto al test: si el contrato
    del veredicto cambia de forma, esto rompe en vez de pasar en silencio un
    objeto duck-typed que el job nunca fue diseñado para leer.
    """
    analysis = _analysis(crest_factor_db=20.0 if needs_mix else 14.0)
    return build_verdict(analysis)


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


# ══════════════════════════════════════════════════════════════════════════
# S6 — el job de analisis: el punto de quiebre
# ══════════════════════════════════════════════════════════════════════════


def _synthetic_audio(tmp_path: Path) -> str:
    """A real WAV whose spectrum has a real SHAPE to judge.

    Sines are the wrong tool here. A 80 Hz sine puts essentially nothing at
    400 Hz, so ``analyze_band_energies`` reports near-silence there, every band
    reads as a huge hole and the runaway-band guard skips all of them -- which
    is the guard working, not the audio being measurable.

    Music is broadband, so this is broadband noise with the ENERGY tilted per
    band: bass-forward, mids scooped, top rolled off. That is a real mix balance
    the verdict can name, and every band stays inside the runaway guard because
    no band is a hole.
    """
    session_id = str(uuid.uuid4())
    audio = tmp_path / f"{session_id}_orig.wav"

    rng = np.random.default_rng(seed=7)
    noise = rng.standard_normal(_SR)

    # Third-octave-ish tilt, applied in the frequency domain so the shape is
    # the shape and not a filter-design exercise.
    spectrum = np.fft.rfft(noise)
    freqs = np.fft.rfftfreq(len(noise), 1.0 / _SR)
    tilt_db = np.interp(
        freqs,
        [20, 60, 150, 400, 1000, 2500, 6000, 10000, 15000, 20000],
        [6.0, 4.0, 4.0, 0.0, -1.0, -2.0, -4.0, -6.0, -8.0, -10.0],
    )
    spectrum *= 10 ** (tilt_db / 20.0)
    shaped = np.fft.irfft(spectrum, n=len(noise))

    peak = float(np.max(np.abs(shaped))) or 1.0
    shaped = shaped / peak * 0.5
    stereo = np.stack([shaped, shaped], axis=1).astype(np.float32)
    sf.write(audio, stereo, _SR)
    return str(audio)


class TestAnalyzeJob:
    """``POST /jobs/agent/{session_id}/analyze`` — solo diagnóstico.

    Es el PRIMER punto de quiebre: le da al usuario el veredicto y las rutas, y
    el usuario decide qué corre después. Por eso este job tiene que ser RÁPIDO:
    sin Demucs, sin render, sin master. Si tocara cualquiera de los tres, el
    usuario esperaría minutos para que le muestren una pregunta.
    """

    def test_the_route_returns_202_with_its_own_poll_url(self, agent_env):
        session_id = _register_session(agent_env.tmp_path)

        resp = client.post(f"/api/jobs/agent/{session_id}/analyze")

        assert resp.status_code == 202
        body = resp.json()
        assert body["job_id"].startswith("agent_analyze_")
        assert body["status"] == "processing"
        # La URL de poll NO puede ser la del job completo.
        assert body["poll_url"] == f"/api/jobs/agent/{body['job_id']}"

    def test_the_job_kind_is_distinct_from_the_full_run(self, agent_env):
        """El store tiene que poder distinguirlos: son dos jobs distintos sobre
        la misma sesión y el frontend los reconcilia por kind."""
        session_id = _register_session(agent_env.tmp_path)
        job_id = client.post(f"/api/jobs/agent/{session_id}/analyze").json()["job_id"]

        record = agent_env.store.get(job_id)

        assert record is not None
        assert record.kind == "agent_analyze"

    def test_it_never_separates_never_renders_and_never_masters(
        self, agent_env, monkeypatch
    ):
        """LA garantía de velocidad. Si Demucs corriera, el "rápido" es mentira.

        Los tres tools caros se reemplazan por un espía que FALLA si lo llaman:
        que el test pase es la prueba de que el camino corto no los toca.
        """
        called: list[str] = []

        def spy(state, args):
            called.append("boom")
            raise AssertionError("el job de analisis llamo a un tool caro")

        for tool in (
            "trigger_stem_separation",
            "render_mix",
            "analyze_mix_bus",
            "send_to_master",
        ):
            monkeypatch.setitem(al.TOOL_IMPLS, tool, spy)

        session_id = _register_session(agent_env.tmp_path)
        job_id = client.post(f"/api/jobs/agent/{session_id}/analyze").json()["job_id"]
        body = client.get(f"/api/jobs/agent/{job_id}").json()

        assert body["status"] == "completed"
        assert called == []

    def test_no_audio_asset_is_produced(self, agent_env):
        """No hay master ni mix: el resultado no puede prometer archivos.

        Es la diferencia entre este job y el completo, y el frontend la usa para
        saber si tiene algo que reproducir.
        """
        session_id = _register_session(agent_env.tmp_path)
        job_id = client.post(f"/api/jobs/agent/{session_id}/analyze").json()["job_id"]

        audio = client.get(f"/api/jobs/agent/{job_id}").json()["result"]["audio"]

        assert audio == {"mix": None, "master": None}

    def test_only_the_diagnosis_tool_ran(self, agent_env):
        session_id = _register_session(agent_env.tmp_path)
        job_id = client.post(f"/api/jobs/agent/{session_id}/analyze").json()["job_id"]

        tools = client.get(f"/api/jobs/agent/{job_id}").json()["result"][
            "tools_executed"
        ]

        assert [tool["tool"] for tool in tools] == ["analyze_original_audio"]
        assert tools[0]["ok"] is True

    def test_the_payload_carries_the_verdict_and_the_routes(self, agent_env):
        """El artefacto que el usuario lee para decidir."""
        session_id = _register_session(agent_env.tmp_path)
        job_id = client.post(f"/api/jobs/agent/{session_id}/analyze").json()["job_id"]

        result = client.get(f"/api/jobs/agent/{job_id}").json()["result"]
        verdict = result["verdict"]

        assert verdict["recommended_path"] in ("mix_then_master", "master_only")
        assert verdict["reasoning_key"]
        assert isinstance(verdict["needs_mix"], bool)
        assert 0.0 <= verdict["confidence"] <= 1.0
        # Las rutas viajan con su copy en español: la UI no la inventa.
        assert [route["id"] for route in verdict["routes"]] == [
            "mix_then_master",
            "master_only",
        ]
        assert sum(route["recommended"] for route in verdict["routes"]) == 1
        assert all(route["label_es"] for route in verdict["routes"])

    def test_the_verdict_is_persisted_on_the_session(self, agent_env):
        """Sobrevive al reload: la UI no tiene que re-pedir el analisis."""
        session_id = _register_session(agent_env.tmp_path)
        job_id = client.post(f"/api/jobs/agent/{session_id}/analyze").json()["job_id"]
        client.get(f"/api/jobs/agent/{job_id}")

        session = upload_mod.sessions[session_id]

        assert session.verdict is not None
        assert session.verdict.recommended_path in ("mix_then_master", "master_only")

    def test_it_carries_per_band_deficiencies(self, agent_env):
        """El analisis mide el espectro: el veredicto explica QUÉ le falta.

        El routing NO depende de esto (se decide por crest); las carencias son
        la explicación que el usuario lee al lado de la ruta.

        El audio es de banda ancha con tilt real: con senos puros cada banda
        fuera de la frecuencia del seno es un agujero, y el guard de 20 dB las
        salta todas — con razón.
        """
        audio = _synthetic_audio(agent_env.tmp_path)
        session_id = str(uuid.uuid4())
        upload_mod.sessions[session_id] = SessionData(
            session_id=session_id,
            original_path=audio,
            original_filename="shaped.wav",
            analysis=None,  # sin análisis previo: el job mide de cero
        )
        job_id = client.post(f"/api/jobs/agent/{session_id}/analyze").json()["job_id"]

        verdict = client.get(f"/api/jobs/agent/{job_id}").json()["result"]["verdict"]

        assert verdict["deficiencies"], "un audio con forma real tiene carencias"
        for item in verdict["deficiencies"]:
            assert item["direction"] in ("lacks", "excess")
            # Solo el delta audible: por debajo del umbral es ruido.
            assert abs(item["delta_db"]) > 2.0

    def test_unknown_session_is_404(self, agent_env):
        assert client.post(f"/api/jobs/agent/{uuid.uuid4()}/analyze").status_code == 404

    def test_a_session_without_audio_is_400(self, agent_env):
        session_id = str(uuid.uuid4())
        upload_mod.sessions[session_id] = SessionData(session_id=session_id)

        resp = client.post(f"/api/jobs/agent/{session_id}/analyze")

        assert resp.status_code == 400

    def test_no_usable_transport_is_503_not_a_doomed_job(self, agent_env, monkeypatch):
        def unavailable(**kwargs):
            raise al.TransportUnavailableError("no hay credencial del LLM")

        monkeypatch.setattr(al, "default_transport", unavailable)
        session_id = _register_session(agent_env.tmp_path)

        resp = client.post(f"/api/jobs/agent/{session_id}/analyze")

        assert resp.status_code == 503
        assert agent_env.store._jobs == {}

    def test_a_dead_llm_does_not_cost_the_user_the_decision(
        self, agent_env, monkeypatch
    ):
        """El veredicto YA está calculado: un LLM caído no puede borrarlo.

        Mismo razonamiento que el R2 ausente en el job de mezcla: el entregable
        principal ya existe. Fallar el job entero acá tiraría una medición que
        salió bien para castigar un resumen que no salió — y el usuario se
        quedaría SIN decisión que tomar. Lo que falta es la prosa, y el payload
        lo dice con `diagnosis: None` en vez de inventar una.
        """
        monkeypatch.setattr(al, "default_transport", lambda **kwargs: _BoomTransport())
        session_id = _register_session(agent_env.tmp_path)

        job_id = client.post(f"/api/jobs/agent/{session_id}/analyze").json()["job_id"]
        body = client.get(f"/api/jobs/agent/{job_id}").json()

        assert body["status"] == "completed"
        assert body["result"]["diagnosis"] is None
        # Y la decisión sigue estando.
        assert body["result"]["verdict"]["recommended_path"] in (
            "mix_then_master",
            "master_only",
        )

    def test_a_failure_that_loses_the_verdict_still_marks_the_job_as_error(
        self, agent_env, monkeypatch
    ):
        """La otra cara: si SÍ no hay veredicto, el job NO puede decir completed.

        Sin esto, un job que murió antes de medir reportaría un veredicto nulo
        como si fuera un resultado.
        """
        def boom(*args, **kwargs):
            raise RuntimeError("el motor de análisis explotó")

        monkeypatch.setattr(agent_jobs, "build_verdict", boom)
        session_id = _register_session(agent_env.tmp_path)

        job_id = client.post(f"/api/jobs/agent/{session_id}/analyze").json()["job_id"]
        stored = agent_env.store.get(job_id)

        assert stored is not None
        assert stored.status is JobStatus.ERROR
        assert "explotó" in (stored.error or "")

    def test_a_missing_audio_fails_with_a_reason(self, agent_env):
        """La sesion existe pero el archivo no: el error dice CUÁL."""
        session_id = str(uuid.uuid4())
        upload_mod.sessions[session_id] = SessionData(
            session_id=session_id,
            original_path=str(agent_env.tmp_path / "no-existe.wav"),
        )

        resp = client.post(f"/api/jobs/agent/{session_id}/analyze")

        assert resp.status_code == 400


class TestBuildVerifyAgentResult:
    """``build_analyze_result`` — un payload que dice la verdad sobre lo que pasó."""

    def test_a_verdict_rides_along_even_without_audio_assets(self):
        state = al.AgentState(session_id="s", input_path=Path("x.wav"))

        result = agent_jobs.build_analyze_result(state, {"mix": None, "master": None})

        assert result["verdict"] is None
        assert result["audio"] == {"mix": None, "master": None}
        assert result["mix_metrics"] is None
        assert result["master_metrics"] is None

    def test_the_applied_route_and_the_verdict_are_both_reported(self):
        """El frontend necesita las dos: qué propone Brik y qué se va a correr.

        Sin ``decision``, la UI no puede decir "Brik propone esto, y esto otro es
        lo que vas a ejecutar si no cambiás nada".
        """
        state = al.AgentState(session_id="s", input_path=Path("x.wav"))
        state.verdict = _verdict(needs_mix=True)

        result = agent_jobs.build_analyze_result(state, {"mix": None, "master": None})

        assert result["verdict"]["recommended_path"] == "mix_then_master"
        assert result["decision"]["requested"] == "auto"
        assert result["decision"]["applied"] == "mix_then_master"

    def test_the_applied_route_can_never_contradict_the_verdict(self):
        """LA invariante del payload de análisis: las dos rutas coinciden.

        Este job NO ejecuta nada: su entregable es la propuesta. Si ``applied``
        dijera una ruta y el veredicto recomendara otra, el usuario leería una
        contradicción en la misma pantalla — "Brik propone master_only" arriba y
        "se va a correr mix_then_master" abajo.

        El default de ``DecisionRecord`` es ``mix_then_master`` (la ruta
        histórica), así que un ``state`` que nunca pasó por resolución reportaba
        ese default sin importar lo que dijera el veredicto. El bug real: el
        payload se contradecía a sí mismo.
        """
        for needs_mix, expected in ((True, "mix_then_master"), (False, "master_only")):
            state = al.AgentState(session_id="s", input_path=Path("x.wav"))
            state.verdict = _verdict(needs_mix=needs_mix)

            result = agent_jobs.build_analyze_result(
                state, {"mix": None, "master": None}
            )

            assert result["verdict"]["recommended_path"] == expected
            assert result["decision"]["applied"] == expected

    def test_without_a_verdict_the_payload_falls_back_to_the_historical_route(self):
        """Sin veredicto no hay propuesta: la ruta histórica, explícita."""
        state = al.AgentState(session_id="s", input_path=Path("x.wav"))

        result = agent_jobs.build_analyze_result(state, {"mix": None, "master": None})

        assert result["verdict"] is None
        assert result["decision"]["requested"] == "auto"
        assert result["decision"]["applied"] == "mix_then_master"


class TestAnalyzeJobDecisionPropagation:
    """La última palabra del usuario TIENE que llegar al motor.

    Este es el punto central de toda la feature. Sin esto, la UI puede mostrarle
    al usuario dos rutas, el usuario puede elegir, y el backend corre las cuatro
    fases igual: la elección viaja hasta el DOM y muere ahí. El usuario cree que
    decidió y no decidió nada.

    ``resolve_decision`` ya existe y es pura; el defecto era que nadie la
    consultaba con datos reales fuera de ``run()``.
    """

    def test_the_analyze_payload_applied_route_matches_the_verdict(self, agent_env):
        """Ya cubierto arriba a nivel builder; acá se prueba end-to-end."""
        session_id = _register_session(agent_env.tmp_path)
        job_id = client.post(f"/api/jobs/agent/{session_id}/analyze").json()["job_id"]

        result = client.get(f"/api/jobs/agent/{job_id}").json()["result"]

        assert result["verdict"]["recommended_path"] == result["decision"]["applied"]

    def test_a_master_only_verdict_skips_separation_in_the_full_run(
        self, agent_env, monkeypatch
    ):
        """El fallo que esto previene: pagar Demucs por un audio ya masterizado.

        Con un veredicto ``master_only`` la cadena NO puede separar ni mezclar.
        Si separa, la feature entera no sirve: el ahorro más grande del sistema
        (Demucs: minutos y GB de RAM) se pierde en el último tramo.
        """
        session_id = _register_session(agent_env.tmp_path)

        # El veredicto dice ruta corta, como si el usuario ya lo hubiera visto.
        from audiomind.api.upload import sessions

        sessions[session_id].verdict = _verdict(needs_mix=False)

        job_id = client.post(
            f"/api/jobs/agent/{session_id}", json={"decision": "master_only"}
        ).json()["job_id"]
        body = client.get(f"/api/jobs/agent/{job_id}").json()

        assert body["status"] == "completed"
        tools = [tool["tool"] for tool in body["result"]["tools_executed"]]
        assert "trigger_stem_separation" not in tools
        assert "render_mix" not in tools
        assert "send_to_master" in tools

    def test_auto_follows_the_master_only_verdict_without_user_input(
        self, agent_env
    ):
        """``auto`` es el default: sigue al veredicto sin que el usuario pida nada."""
        session_id = _register_session(agent_env.tmp_path)

        from audiomind.api.upload import sessions

        sessions[session_id].verdict = _verdict(needs_mix=False)

        job_id = client.post(f"/api/jobs/agent/{session_id}", json={}).json()["job_id"]
        body = client.get(f"/api/jobs/agent/{job_id}").json()

        tools = [tool["tool"] for tool in body["result"]["tools_executed"]]
        assert "trigger_stem_separation" not in tools

    def test_the_user_can_force_the_long_route_over_the_verdict(self, agent_env):
        """La última palabra es del usuario: puede contradecir a Brik.

        Un veredicto ``master_only`` con ``decision="mix_then_master"`` explícito
        DEBE separar y mezclar. La elección del usuario gana siempre, incluso
        cuando el motor recomienda lo contrario.
        """
        session_id = _register_session(agent_env.tmp_path)

        from audiomind.api.upload import sessions

        sessions[session_id].verdict = _verdict(needs_mix=False)

        job_id = client.post(
            f"/api/jobs/agent/{session_id}", json={"decision": "mix_then_master"}
        ).json()["job_id"]
        body = client.get(f"/api/jobs/agent/{job_id}").json()

        tools = [tool["tool"] for tool in body["result"]["tools_executed"]]
        assert "trigger_stem_separation" in tools
        assert "render_mix" in tools

    def test_a_forged_decision_value_is_a_422_not_a_silent_ignore(self, agent_env):
        """Una ruta que no existe tiene que romper ahora, no correr otra cosa.

        ``extra="forbid"`` ya protege los nombres de campo; el valor también
        necesita un dominio cerrado. Un typo silencioso acá significa "el usuario
        eligió una ruta y el sistema corrió otra sin avisar".
        """
        session_id = _register_session(agent_env.tmp_path)

        resp = client.post(
            f"/api/jobs/agent/{session_id}", json={"decision": "solo_master_porfa"}
        )

        assert resp.status_code == 422

    def test_an_unknown_field_is_still_rejected(self, agent_env):
        session_id = _register_session(agent_env.tmp_path)

        resp = client.post(
            f"/api/jobs/agent/{session_id}", json={"decisionn": "master_only"}
        )

        assert resp.status_code == 422


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

    def test_master_metrics_carry_no_ephemeral_local_paths(self):
        """S5: a redeploy turns those paths into lies, and they are not metrics."""
        state = al.AgentState(session_id="s", input_path=Path("x.wav"))
        state.tool_log.append(
            al.ToolResult(
                ok=True,
                tool="send_to_master",
                detail="Master listo.",
                payload={
                    "source": "mix",
                    "source_path": "C:/tmp/mix.wav",
                    "master_path": "C:/tmp/master.wav",
                    "integrated_lufs": -14.0,
                },
            )
        )

        result = agent_jobs.build_agent_result(state, {"mix": None, "master": None})

        assert result["master_metrics"] == {
            "source": "mix",
            "integrated_lufs": -14.0,
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
