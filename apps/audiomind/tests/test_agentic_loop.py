"""Tests for the agentic mix loop.

The loop is driven by a scripted transport and the two expensive tools
(``trigger_stem_separation``, ``render_mix``) are replaced in ``TOOL_IMPLS``,
so nothing here touches Demucs, the network or a real audio file.

Contracts pinned:

* tool arguments reject out-of-range axes and unknown fields;
* ``dispatch`` always answers with an envelope — never an exception;
* the phase order is the one the spec demands, and the guards that make it
  meaningful hold (no report without a render, no master without a mix);
* ``search_knowledge`` only exists when a RAG callable is injected;
* the Gemini transport walks its model chain and refuses to guess without a key.
"""
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.genai import types
from pydantic import ValidationError

from audiomind.analysis.analyzer import TARGET_BANDS_HZ
from audiomind.analysis.verdict import build_verdict
from audiomind.models.audio import (
    AnalysisResult,
    MasteringParameters,
    ReferenceComparison,
)
from audiomind.models.intent_profile import IntentProfile
from audiomind.processing import agentic_loop as al
from audiomind.processing import prompts
from audiomind.processing.gemini_transport import (
    GeminiTransport,
    GeminiUnavailableError,
    _to_contents,
)

STEM_NAMES = ("vocals", "drums", "bass", "other")


def _rag(query: str, k: int) -> list[dict]:
    return [{"citation": "Owsinski p.32", "text": "…", "book_id": "owsinski"}]


class StubTransport:
    """Replays a scripted list of turns and records how it was called."""

    def __init__(self, script: list[al.ModelTurn]) -> None:
        self.script = list(script)
        self.phases: list[str] = []
        self.tools_seen: list[list[str]] = []
        #: Snapshot of the transcript as each phase saw it. Copied because the
        #: loop mutates the real list in place.
        self.transcripts: list[list[dict]] = []

    def turn(self, *, phase, system, transcript, tools):
        self.phases.append(phase)
        self.tools_seen.append([t["name"] for t in tools])
        self.transcripts.append(list(transcript))
        if not self.script:
            raise AssertionError("el guion se quedó sin turnos")
        assert system  # every phase ships a system prompt
        return self.script.pop(0)


@pytest.fixture
def fake_engine(monkeypatch, tmp_path):
    """Reemplaza `engine.process_audio`: acá se prueba el cableado, no el DSP.

    También redirige ``settings.output_dir`` para que el master que estos tests
    escriben caiga en el tmp de pytest y no en el ``outputs/`` real.
    """
    monkeypatch.setattr(al.settings, "output_dir", tmp_path)

    def fake_process_audio(**kwargs):
        output = Path(kwargs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"RIFF")
        fake_process_audio.calls.append(kwargs)
        return {
            "output_path": str(output),
            "integrated_lufs": -14.0,
            "true_peak_db": -1.0,
            "output_bit_depth": kwargs["params"].output_bit_depth,
        }

    fake_process_audio.calls = []
    monkeypatch.setattr(al, "process_audio", fake_process_audio)
    return fake_process_audio.calls


@pytest.fixture
def cheap_tools(monkeypatch, tmp_path, fake_engine):
    """Replace every tool that would need Demucs, real audio or the DSP engine."""

    mix_file = tmp_path / "mix.wav"
    mix_file.write_bytes(b"RIFF")

    # ``send_to_master`` exige que el archivo fuente exista. En la ruta corta
    # ese archivo es el INPUT (no un render), así que tiene que estar en disco
    # igual que el mix del camino largo.
    input_file = tmp_path / "original.wav"
    input_file.write_bytes(b"RIFF")

    def fake_analyze(state, args):
        return al.ToolResult(
            ok=True,
            tool="analyze_original_audio",
            detail="",
            payload={"integrated_lufs": -9.5, "detected_genre": "pop"},
        )

    def fake_separate(state, args):
        state.stems.update({name: f"{name}.wav" for name in STEM_NAMES})
        return al.ToolResult(
            ok=True,
            tool="trigger_stem_separation",
            detail="",
            payload={"stems": state.stems, "stems_dir": str(state.stems_dir)},
        )

    def fake_render(state, args):
        state.render = {
            "mix_path": str(mix_file),
            "qc_report": {"summary": {"flagged": []}},
            "balance_report": None,
            "mix_metadata": {"stem_lufs": {"vocals": -18.0}},
        }
        state.pending_settings = None
        state.iteration += 1
        state.mix_path = state.render["mix_path"]
        return al.ToolResult(
            ok=True,
            tool="render_mix",
            detail="",
            payload={"mix_path": state.mix_path, "iteration": state.iteration},
        )

    monkeypatch.setitem(al.TOOL_IMPLS, "analyze_original_audio", fake_analyze)
    monkeypatch.setitem(al.TOOL_IMPLS, "trigger_stem_separation", fake_separate)
    monkeypatch.setitem(al.TOOL_IMPLS, "render_mix", fake_render)

    return SimpleNamespace(mix_file=mix_file, input_file=input_file)


def _script(**overrides) -> list[al.ModelTurn]:
    return [
        al.ModelTurn(text="Falta pegada y la voz queda tapada."),
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


class TestToolContracts:
    def test_out_of_range_axis_is_rejected(self):
        with pytest.raises(ValidationError):
            al.AdjustStemParametersArgs(intent={"warmth": 1.4})

    def test_unknown_argument_is_rejected(self):
        with pytest.raises(ValidationError):
            al.AnalyzeOriginalAudioArgs(file_path="x.wav", extra=1)

    def test_adjust_takes_an_intent_profile_not_raw_knobs(self):
        """The LLM never emits dB: the tool takes the nine semantic axes."""
        schema = al.AdjustStemParametersArgs.model_json_schema()
        assert "intent" in schema["properties"]
        assert schema.get("additionalProperties") is False


class TestToolDefinitions:
    def test_spec_tools_are_exactly_the_six_requested(self):
        assert [t["name"] for t in al.tool_definitions()] == [
            "analyze_original_audio",
            "trigger_stem_separation",
            "render_mix",
            "analyze_mix_bus",
            "adjust_stem_parameters",
            "send_to_master",
        ]

    def test_knowledge_tool_only_appears_with_a_rag(self):
        with_rag = al.tool_definitions(include_rag=True)
        assert len(with_rag) == 7
        assert with_rag[-1]["name"] == "search_knowledge"

    def test_every_definition_carries_a_json_schema(self):
        for definition in al.tool_definitions(include_rag=True):
            assert definition["description"]
            assert definition["parameters"].get("properties") is not None


class TestDispatch:
    def test_unknown_tool_returns_a_failure_envelope(self):
        state = al.AgentState(session_id="t", input_path=Path("x.wav"))
        result = al.dispatch(state, "no_existe", {})
        assert result.ok is False
        assert result.error

    def test_invalid_arguments_never_escape_as_an_exception(self):
        state = al.AgentState(session_id="t", input_path=Path("x.wav"))
        result = al.dispatch(state, "render_mix", {"with_versions": "si"})
        assert result.ok is False

    def test_mix_bus_cannot_be_analyzed_without_a_render(self):
        state = al.AgentState(session_id="t", input_path=Path("x.wav"))
        assert al.dispatch(state, "analyze_mix_bus", {}).ok is False

    def test_mastering_a_mix_requires_a_render(self):
        state = al.AgentState(session_id="t", input_path=Path("x.wav"))
        assert al.dispatch(state, "send_to_master", {"source": "mix"}).ok is False

    def test_mastering_the_original_needs_no_render(self, tmp_path, fake_engine):
        source = tmp_path / "original.wav"
        source.write_bytes(b"RIFF")
        state = al.AgentState(session_id="t", input_path=source)

        result = al.dispatch(state, "send_to_master", {"source": "original"})

        assert result.ok is True
        assert result.payload["source_path"] == str(source)


class TestMasterWiring:
    """S2.5 dejó de ser un stub: el bus llega de verdad a `engine.process_audio`."""

    def _rendered_state(self, tmp_path, source_freq: float = 220.0):
        source = tmp_path / "original.wav"
        source.write_bytes(b"RIFF")
        mix = tmp_path / "mix.wav"
        mix.write_bytes(b"RIFF")

        state = al.AgentState(session_id="t", input_path=source)
        state.render = {"mix_metadata": {"stem_lufs": {"vocals": -18.0}}}
        state.mix_path = str(mix)
        return state

    def test_the_mixed_bus_reaches_the_engine(self, tmp_path, fake_engine):
        state = self._rendered_state(tmp_path)

        result = al.dispatch(state, "send_to_master", {"source": "mix"})

        assert result.ok is True
        assert len(fake_engine) == 1
        assert str(fake_engine[0]["input_path"]) == state.mix_path

    def test_the_mix_metadata_travels_for_the_adaptive_handshake(
        self, tmp_path, fake_engine
    ):
        state = self._rendered_state(tmp_path)

        al.dispatch(state, "send_to_master", {"source": "mix"})

        assert fake_engine[0]["mix_metadata"] == {"stem_lufs": {"vocals": -18.0}}

    def test_mastering_the_original_sends_no_mix_metadata(self, tmp_path, fake_engine):
        state = self._rendered_state(tmp_path)

        al.dispatch(state, "send_to_master", {"source": "original"})

        assert fake_engine[0]["mix_metadata"] is None

    def test_a_neutral_intent_masters_with_the_default_parameters(
        self, tmp_path, fake_engine
    ):
        """El contrato 'neutral = bypass' tiene que llegar hasta el motor."""
        state = self._rendered_state(tmp_path)

        al.dispatch(state, "send_to_master", {"source": "mix"})

        assert fake_engine[0]["params"] == MasteringParameters()

    def test_the_mix_intent_moves_the_master_too(self, tmp_path, fake_engine):
        state = self._rendered_state(tmp_path)
        state.intent = IntentProfile(vocal_focus=0.8)

        al.dispatch(state, "send_to_master", {"source": "mix"})

        assert fake_engine[0]["params"].dyn_eq_enabled is True

    def test_the_call_overrides_lufs_and_bit_depth(self, tmp_path, fake_engine):
        state = self._rendered_state(tmp_path)

        result = al.dispatch(
            state,
            "send_to_master",
            {"source": "mix", "target_lufs_db": -11.0, "output_bit_depth": 16},
        )

        params = fake_engine[0]["params"]
        assert params.target_lufs_db == -11.0
        assert params.output_bit_depth == 16
        assert result.payload["output_bit_depth"] == 16

    def test_a_failing_engine_becomes_an_envelope_not_an_exception(
        self, tmp_path, monkeypatch
    ):
        def exploding(**kwargs):
            raise RuntimeError("limiter explotó")

        monkeypatch.setattr(al, "process_audio", exploding)
        state = self._rendered_state(tmp_path)

        result = al.dispatch(state, "send_to_master", {"source": "mix"})

        assert result.ok is False
        assert "limiter explotó" in (result.error or "")
        assert state.master_path is None

    def test_the_written_master_is_reported(self, tmp_path, fake_engine):
        state = self._rendered_state(tmp_path)

        result = al.dispatch(state, "send_to_master", {"source": "mix"})

        assert state.master_path == result.payload["master_path"]
        assert Path(state.master_path).is_file()

    def test_stem_separation_refuses_a_file_that_is_not_the_session_input(
        self, tmp_path
    ):
        """Separar otro archivo pagaría Demucs y no alimentaría el render."""
        session_input = tmp_path / "session.wav"
        session_input.write_bytes(b"RIFF")
        otro = tmp_path / "otro.wav"
        otro.write_bytes(b"RIFF")
        state = al.AgentState(session_id="t", input_path=session_input)

        result = al.dispatch(
            state, "trigger_stem_separation", {"file_path": str(otro)}
        )

        assert result.ok is False
        assert "build_mix" in (result.error or "")


class TestKnowledgeTool:
    def test_refuses_when_no_rag_is_injected(self):
        state = al.AgentState(session_id="t", input_path=Path("x.wav"))
        result = al.dispatch(state, "search_knowledge", {"query": "voz al frente"})
        assert result.ok is False
        assert "RAG" in (result.error or "")

    def test_returns_citations_when_a_rag_is_injected(self):
        state = al.AgentState(session_id="t", input_path=Path("x.wav"), rag=_rag)
        result = al.dispatch(state, "search_knowledge", {"query": "voz al frente"})
        assert result.ok is True
        assert "Owsinski" in result.detail

    def test_a_broken_rag_does_not_break_the_loop(self):
        def exploding(query: str, k: int) -> list[dict]:
            raise RuntimeError("índice caído")

        state = al.AgentState(session_id="t", input_path=Path("x.wav"), rag=exploding)
        result = al.dispatch(state, "search_knowledge", {"query": "x"})
        assert result.ok is False


class TestPhaseMachine:
    def test_the_four_phases_run_in_the_spec_order(self, cheap_tools):
        transport = StubTransport(_script())
        state = al.run(
            session_id="probe", input_path=Path("x.wav"), transport=transport, rag=_rag
        )
        assert transport.phases == ["phase1", "phase3", "phase3", "phase3", "phase4"]
        assert state.diagnosis
        assert len(state.stems) == 4
        assert state.iteration == 1
        assert state.can_master is True

    def test_the_diagnosis_phase_offers_no_tools(self, cheap_tools):
        transport = StubTransport(_script())
        al.run(session_id="probe", input_path=Path("x.wav"), transport=transport)
        assert transport.tools_seen[0] == []

    def test_the_loop_offers_the_knowledge_tool_only_with_a_rag(self, cheap_tools):
        with_rag = StubTransport(_script())
        al.run(
            session_id="probe", input_path=Path("x.wav"), transport=with_rag, rag=_rag
        )
        assert len(with_rag.tools_seen[1]) == 7

        without_rag = StubTransport(_script())
        al.run(session_id="probe", input_path=Path("x.wav"), transport=without_rag)
        assert len(without_rag.tools_seen[1]) == 6

    def test_the_user_intent_reaches_the_mix_mapper(self, cheap_tools):
        transport = StubTransport(_script())
        state = al.run(
            session_id="probe", input_path=Path("x.wav"), transport=transport
        )
        assert state.intent.vocal_focus == 0.8

    def test_the_loop_stops_once_the_qc_reports_clean(self, cheap_tools):
        """Three render turns are offered; a clean QC closes the loop early."""
        transport = StubTransport(_script())
        al.run(session_id="probe", input_path=Path("x.wav"), transport=transport)
        assert transport.phases.count("phase3") == al.MAX_MIX_ITERATIONS

    def test_every_function_call_is_recorded_before_its_response(self, cheap_tools):
        transport = StubTransport(_script())
        al.run(session_id="probe", input_path=Path("x.wav"), transport=transport)
        transcript: list[dict] = []
        al._record_exchange(
            transcript,
            al.ToolCall(name="render_mix", args={}),
            al.ToolResult(ok=True, tool="render_mix", detail=""),
        )
        assert transcript[0]["function_call"]["name"] == "render_mix"
        assert transcript[1]["role"] == "tool"


class TestToolLog:
    """S2 — "las herramientas ejecutadas" se REGISTRAN, no se deducen.

    Deducir "se separó" de que ``state.stems`` tiene 4 entradas es una
    inferencia; el ``ToolResult`` es la evidencia de qué corrió y cómo salió.
    """

    def test_every_executed_tool_is_recorded_in_order(self, cheap_tools):
        transport = StubTransport(_script())
        state = al.run(
            session_id="probe", input_path=Path("x.wav"), transport=transport
        )
        assert [r.tool for r in state.tool_log] == [
            "analyze_original_audio",
            "trigger_stem_separation",
            "adjust_stem_parameters",
            "render_mix",
            "analyze_mix_bus",
            "send_to_master",
        ]

    def test_a_failed_tool_is_recorded_with_its_error(self):
        state = al.AgentState(session_id="t", input_path=Path("x.wav"))
        result = al.dispatch(state, "search_knowledge", {"query": "x"})

        assert result.ok is False
        assert [r.tool for r in state.tool_log] == ["search_knowledge"]
        assert state.tool_log[0].ok is False
        assert state.tool_log[0].error

    def test_an_unknown_tool_is_recorded_too(self):
        state = al.AgentState(session_id="t", input_path=Path("x.wav"))
        al.dispatch(state, "no_existe", {})
        assert [r.tool for r in state.tool_log] == ["no_existe"]

    def test_a_rejected_argument_set_is_recorded(self):
        state = al.AgentState(session_id="t", input_path=Path("x.wav"))
        al.dispatch(state, "adjust_stem_parameters", {"intent": "no-es-un-perfil"})
        assert [r.tool for r in state.tool_log] == ["adjust_stem_parameters"]
        assert state.tool_log[0].ok is False


class TestUserPrompt:
    """S7 — un prompt que se recibe y no llega al modelo es decorativo."""

    def test_the_prompt_reaches_the_first_user_turn(self, cheap_tools):
        transport = StubTransport(_script())
        al.run(
            session_id="probe",
            input_path=Path("x.wav"),
            transport=transport,
            prompt="quiero la voz más al frente",
        )

        first = transport.transcripts[0][0]
        assert first["role"] == "user"
        assert "quiero la voz más al frente" in first["text"]

    def test_without_a_prompt_the_initial_turn_is_unchanged(self, cheap_tools):
        transport = StubTransport(_script())
        al.run(session_id="probe", input_path=Path("x.wav"), transport=transport)
        assert transport.transcripts[0][0]["text"] == "Mezclar y masterizar: x.wav"

    def test_a_blank_prompt_does_not_add_an_empty_directive(self, cheap_tools):
        transport = StubTransport(_script())
        al.run(
            session_id="probe",
            input_path=Path("x.wav"),
            transport=transport,
            prompt="   ",
        )
        assert transport.transcripts[0][0]["text"] == "Mezclar y masterizar: x.wav"


class TestBusMetrics:
    def test_bus_metrics_are_the_single_source_for_the_tool_payload(
        self, cheap_tools
    ):
        """La herramienta y el armado del resultado HTTP deben coincidir.

        Si la lista de campos se duplicara, el frontend vería métricas que la
        herramienta nunca midió y nada fallaría.
        """
        transport = StubTransport(_script())
        state = al.run(
            session_id="probe", input_path=Path("x.wav"), transport=transport
        )

        recorded = next(r for r in state.tool_log if r.tool == "analyze_mix_bus")
        assert al.bus_metrics(state) == recorded.payload


# ══════════════════════════════════════════════════════════════════════════
# S5 / S7 — la compuerta condicional
# ══════════════════════════════════════════════════════════════════════════


def _verdict(*, needs_mix: bool):
    """A real verdict, built from a real analysis — never a hand-rolled stub.

    Building it through ``build_verdict`` keeps the gate test honest: if the
    verdict contract changes shape, this test breaks instead of silently
    passing a duck-typed object the gate was never designed to read.
    """
    analysis = AnalysisResult(
        integrated_lufs=-18.0,
        true_peak_db=-1.0,
        dynamic_range_db=17.0 if needs_mix else 12.0,
        spectral_centroid=3000.0,
        tempo_bpm=120.0,
        duration_seconds=180.0,
        sample_rate=44100,
        channels=2,
        detected_genre="pop",
        genre_confidence=0.8,
        crest_factor_db=20.0 if needs_mix else 14.0,
        is_already_mastered=False,
        mastering_confidence=0.0,
    )
    return build_verdict(analysis)


def _verdict_with_deficiencies():
    """A verdict whose per-band measurement really does report gaps.

    A flat measurement reports NOTHING against a near-flat target (everything
    falls under the 2 dB threshold), so a test that wants deficiencies has to
    supply a real spectral shape. This shape is mid-recessed and top-light, the
    classic "needs a mix" profile, and it passes the 20 dB runaway guard per
    band — so every band is a legitimate, measurable gap.
    """
    analysis = AnalysisResult(
        integrated_lufs=-18.0,
        true_peak_db=-1.0,
        dynamic_range_db=17.0,
        spectral_centroid=3000.0,
        tempo_bpm=120.0,
        duration_seconds=180.0,
        sample_rate=44100,
        channels=2,
        detected_genre="pop",
        genre_confidence=0.8,
        crest_factor_db=20.0,
        is_already_mastered=False,
        mastering_confidence=0.0,
    )
    # Sub/bass heavy, scooped mids, weak top: real gaps vs the pop profile.
    band_energies = [-14.0, -16.0, -26.0, -32.0, -30.0, -34.0, -38.0, -40.0]
    return build_verdict(analysis, band_energies_db=band_energies)


class TestDecisionGate:
    """S7 — la compuerta condicional del orquestador.

    ``master_only`` tiene que saltarse la separación (Demucs) y el bucle de
    mezcla ENTEROS, y masterizar el original. El motor soporta
    ``SendToMasterArgs.source="original"`` desde antes de esta feature; el
    orquestador es lo que nunca lo ofrecía.
    """

    def test_master_only_skips_phases_two_and_three(self, cheap_tools):
        """Ni una llamada a Demucs ni un turno de bucle: ese es el ahorro."""
        transport = StubTransport(
            [
                al.ModelTurn(text="Ya viene mezclado; masterizar directo."),
                al.ModelTurn(tool_calls=[al.ToolCall(name="send_to_master")]),
            ]
        )
        state = al.run(
            session_id="probe",
            input_path=cheap_tools.input_file,
            transport=transport,
            decision="master_only",
        )

        assert transport.phases == ["phase1", "phase4"]
        assert state.stems == {}
        assert state.render is None
        assert state.mix_path is None
        assert state.master_path

    def test_master_only_masters_the_original(self, cheap_tools, fake_engine):
        """El master sale del INPUT, no de un render de mezcla."""
        transport = StubTransport(
            [
                al.ModelTurn(text="Ya viene mezclado; masterizar directo."),
                al.ModelTurn(tool_calls=[al.ToolCall(name="send_to_master")]),
            ]
        )
        al.run(
            session_id="probe",
            input_path=cheap_tools.input_file,
            transport=transport,
            decision="master_only",
        )

        assert len(fake_engine) == 1
        call = fake_engine[0]
        assert Path(call["input_path"]) == cheap_tools.input_file
        # El handshake adaptativo solo aplica cuando lo masterizado ES la mezcla.
        assert call["mix_metadata"] is None

    def test_master_only_forces_source_original_even_if_the_model_says_mix(
        self, cheap_tools, fake_engine
    ):
        """El modelo no puede reabrir la compuerta pidiendo ``source='mix'``.

        Un turno que insiste con ``mix`` sin render fallaría con un envelope de
        error; la decisión del usuario es la que manda, así que la fase 4 la
        aplica y el modelo no tiene voto.
        """
        transport = StubTransport(
            [
                al.ModelTurn(text="Ya viene mezclado; masterizar directo."),
                al.ModelTurn(
                    tool_calls=[
                        al.ToolCall(name="send_to_master", args={"source": "mix"})
                    ]
                ),
            ]
        )
        state = al.run(
            session_id="probe",
            input_path=cheap_tools.input_file,
            transport=transport,
            decision="master_only",
        )

        assert state.master_path
        recorded = next(r for r in state.tool_log if r.tool == "send_to_master")
        assert recorded.ok is True
        assert recorded.payload["source"] == "original"

    def test_mix_then_master_runs_the_four_phases(self, cheap_tools):
        """La ruta larga explícita es EXACTAMENTE la de siempre."""
        transport = StubTransport(_script())
        state = al.run(
            session_id="probe",
            input_path=Path("x.wav"),
            transport=transport,
            decision="mix_then_master",
        )

        assert transport.phases == ["phase1", "phase3", "phase3", "phase3", "phase4"]
        assert len(state.stems) == 4
        assert state.master_path

    def test_the_user_decision_beats_briks_own_verdict(self, cheap_tools):
        """El usuario tiene la última palabra, incluso contra el veredicto.

        Brik dice ``needs_mix=False`` y el usuario pide mezclar igual: se corre
        la ruta larga. Es la garantía de "la última palabra la decide el
        usuario", y es lo que impide que la IA decida sola por accidente.
        """
        transport = StubTransport(_script())
        state = al.run(
            session_id="probe",
            input_path=Path("x.wav"),
            transport=transport,
            decision="mix_then_master",
            verdict=_verdict(needs_mix=False),
        )

        assert transport.phases == ["phase1", "phase3", "phase3", "phase3", "phase4"]
        assert len(state.stems) == 4


class TestAutoDecision:
    """S5 — ``auto`` es el default y resuelve con el veredicto."""

    def test_auto_without_a_verdict_is_the_historical_run(self, cheap_tools):
        """Cero veredicto, cero cambio de comportamiento: compatibilidad total."""
        transport = StubTransport(_script())
        state = al.run(
            session_id="probe", input_path=Path("x.wav"), transport=transport
        )

        assert transport.phases == ["phase1", "phase3", "phase3", "phase3", "phase4"]
        assert len(state.stems) == 4
        assert state.decision.requested == "auto"
        assert state.decision.applied == "mix_then_master"

    def test_auto_follows_a_verdict_that_needs_a_mix(self, cheap_tools):
        transport = StubTransport(_script())
        state = al.run(
            session_id="probe",
            input_path=Path("x.wav"),
            transport=transport,
            verdict=_verdict(needs_mix=True),
        )

        assert state.decision.applied == "mix_then_master"
        assert len(state.stems) == 4

    def test_auto_follows_a_verdict_that_only_needs_mastering(self, cheap_tools):
        """El caso que hasta hoy era imposible: el orchestrator ofrece la ruta
        corta por sí solo, sin que nadie lo pida a mano."""
        transport = StubTransport(
            [
                al.ModelTurn(text="Veredicto: solo masterizar."),
                al.ModelTurn(tool_calls=[al.ToolCall(name="send_to_master")]),
            ]
        )
        state = al.run(
            session_id="probe",
            input_path=cheap_tools.input_file,
            transport=transport,
            verdict=_verdict(needs_mix=False),
        )

        assert transport.phases == ["phase1", "phase4"]
        assert state.decision.requested == "auto"
        assert state.decision.applied == "master_only"
        assert state.stems == {}
        assert state.master_path

    def test_an_explicit_decision_is_reported_as_applied(self, cheap_tools):
        transport = StubTransport(
            [
                al.ModelTurn(text="Solo masterizar."),
                al.ModelTurn(tool_calls=[al.ToolCall(name="send_to_master")]),
            ]
        )
        state = al.run(
            session_id="probe",
            input_path=cheap_tools.input_file,
            transport=transport,
            decision="master_only",
        )

        assert state.decision.requested == "master_only"
        assert state.decision.applied == "master_only"

    def test_an_invalid_decision_is_refused_at_the_contract(self):
        """La decisión viaja de la UI: un valor basura se rechaza, no se asume."""
        with pytest.raises(ValidationError):
            al.DecisionRecord(requested="hacer-lo-que-quieras", applied="auto")


class TestVerdictArtifact:
    """S1/S10 — el veredicto se adjunta al estado para que el job lo devuelva."""

    def test_a_passed_verdict_lands_on_the_state(self, cheap_tools):
        transport = StubTransport(_script())
        verdict = _verdict(needs_mix=True)
        state = al.run(
            session_id="probe",
            input_path=Path("x.wav"),
            transport=transport,
            verdict=verdict,
        )

        assert state.verdict is verdict

    def test_without_a_verdict_the_state_stays_empty(self, cheap_tools):
        transport = StubTransport(_script())
        state = al.run(
            session_id="probe", input_path=Path("x.wav"), transport=transport
        )

        assert state.verdict is None

    def test_the_verdict_reaches_the_diagnosis_turn(self, cheap_tools):
        """Un veredicto que no llega al modelo es un adorno.

        El diagnóstico tiene que poder VER de dónde salió la ruta: si no, Brik
        explica un audio que no es el que se está procesando.
        """
        transport = StubTransport(_script())
        al.run(
            session_id="probe",
            input_path=Path("x.wav"),
            transport=transport,
            verdict=_verdict(needs_mix=False),
        )

        # transcripts[0] es el estado del transcript cuando se pidió el turno de
        # fase 1: el último elemento es el bloque de mediciones+veredicto.
        phase1_turn = transport.transcripts[0][-1]["text"]
        assert "<veredicto>" in phase1_turn
        assert "master_only" in phase1_turn


# ══════════════════════════════════════════════════════════════════════════
# S8 — la referencia entra al prompt
# ══════════════════════════════════════════════════════════════════════════


def _reference_comparison() -> ReferenceComparison:
    return ReferenceComparison(
        status="ready",
        target_bands_hz=list(TARGET_BANDS_HZ),
        master_band_levels_db=[-20.0] * 8,
        reference_band_levels_db=[-18.0] * 8,
        band_deltas_db=[2.0] * 8,
        master_lufs_db=-16.0,
        reference_lufs_db=-14.0,
        lufs_delta_db=2.0,
    )


class TestReferenceReachesThePrompt:
    """S8 — la referencia que el usuario sube hoy muere en la sesión."""

    def test_the_reference_block_reaches_the_diagnosis_turn(self, cheap_tools):
        transport = StubTransport(_script())
        al.run(
            session_id="probe",
            input_path=Path("x.wav"),
            transport=transport,
            reference_comparison=_reference_comparison(),
        )

        phase1_turn = transport.transcripts[0][-1]["text"]
        assert "<referencia>" in phase1_turn
        assert "-14.0" in phase1_turn

    def test_without_a_reference_the_turn_is_unchanged(self, cheap_tools):
        """Sin referencia, el turno de fase 1 queda EXACTAMENTE como estaba."""
        transport = StubTransport(_script())
        al.run(
            session_id="probe", input_path=Path("x.wav"), transport=transport
        )

        phase1_turn = transport.transcripts[0][-1]["text"]
        assert "<referencia>" not in phase1_turn
        assert "<veredicto>" not in phase1_turn

    def test_an_unready_reference_is_not_shown_as_evidence(self, cheap_tools):
        """``status != "ready"`` es una comparación que no corrió o falló.

        Mostrarla sería presentar como medición algo que nunca se midió.
        """
        transport = StubTransport(_script())
        al.run(
            session_id="probe",
            input_path=Path("x.wav"),
            transport=transport,
            reference_comparison=ReferenceComparison(
                status="error", message="decode falló"
            ),
        )

        assert "<referencia>" not in transport.transcripts[0][-1]["text"]

    def test_a_mastered_reference_forces_master_only(self, cheap_tools):
        """Una referencia ya masterizada cierra la ruta corta.

        Comparar dos masters no justifica re-mezclar: la referencia ES el
        estándar al que se quiere llegar, y ya viene masterizada.
        """
        transport = StubTransport(
            [
                al.ModelTurn(text="La referencia ya está masterizada."),
                al.ModelTurn(tool_calls=[al.ToolCall(name="send_to_master")]),
            ]
        )
        state = al.run(
            session_id="probe",
            input_path=cheap_tools.input_file,
            transport=transport,
            reference_comparison=_reference_comparison(),
            reference_is_mastered=True,
        )

        assert transport.phases == ["phase1", "phase4"]
        assert state.decision.applied == "master_only"

    def test_the_reference_alone_does_not_force_the_short_route(self, cheap_tools):
        """Una referencia NO masterizada no cambia la ruta por sí sola.

        La referencia dice a dónde ir, no en qué estado está el audio del
        usuario. Forzar ``master_only`` ahí sería saltarse una mezcla que el
        audio sí necesita.
        """
        transport = StubTransport(_script())
        state = al.run(
            session_id="probe",
            input_path=Path("x.wav"),
            transport=transport,
            reference_comparison=_reference_comparison(),
        )

        assert transport.phases == ["phase1", "phase3", "phase3", "phase3", "phase4"]
        assert state.decision.applied == "mix_then_master"


class TestPromptContext:
    def test_context_block_lists_every_axis(self):
        block = prompts.context_block(IntentProfile.neutral().model_dump())
        for axis in prompts._AXIS_KEYS:
            assert f"{axis}:" in block

    def test_context_block_warns_against_announcing_the_genre(self):
        block = prompts.context_block(
            IntentProfile.neutral().model_dump(), {"detected_genre": "pop"}
        )
        assert "NO le anuncies el genero detectado" in block

    def test_the_loop_prompt_carries_the_iteration_budget(self):
        assert str(al.MAX_MIX_ITERATIONS) in prompts.mix_loop_system_prompt(
            al.MAX_MIX_ITERATIONS
        )


# ══════════════════════════════════════════════════════════════════════════
# S9 — el prompt es VOCERO del DSP, no autor de un diagnostico paralelo
# ══════════════════════════════════════════════════════════════════════════


class TestDiagnosisPromptIsAVoice:
    """El modelo NO calcula el veredicto: lo verbaliza.

    El veredicto lo produce ``build_verdict`` con numeros medidos. Si el prompt
    dejara al modelo calcular el suyo, tendriamos DOS diagnosticos sobre el
    mismo audio, y el que el usuario lee (texto) podria contradecir al que el
    motor aplica (DSP). Eso es peor que no decir nada: el usuario deja de poder
    confiar en lo que lee.
    """

    def test_the_prompt_forbids_recomputing_the_verdict(self):
        """El prompt le dice al modelo que VERBALICE, no que calcule."""
        assert "verbaliz" in prompts.DIAGNOSIS_SYSTEM_PROMPT.lower()
        assert "no recalcules" in prompts.DIAGNOSIS_SYSTEM_PROMPT.lower()

    def test_the_prompt_names_the_motor_as_the_source_of_truth(self):
        """El prompt tiene que decir de dónde sale el veredicto.

        Normalizo el whitespace antes de buscar: el texto está refloweado a 80
        columnas y una frase puede partirse en dos líneas. Buscar el literal
        crudo haría que el test falle por un salto de línea, no por contenido.
        """
        flat = " ".join(prompts.DIAGNOSIS_SYSTEM_PROMPT.lower().split())
        assert "ya lo midio sobre el audio real" in flat

    def test_the_prompt_keeps_the_anti_invention_rule(self):
        """Sigue prohibido afirmar una medicion que no existe."""
        assert "no inventes" in prompts.DIAGNOSIS_SYSTEM_PROMPT.lower()

    def test_the_prompt_keeps_the_hard_rule_about_promises(self):
        """Hard rule 7 intacta: proponer rutas del motor no es prometer humo."""
        assert "no prometas lo que no puedes" in prompts.DIAGNOSIS_SYSTEM_PROMPT.lower()

    def test_the_prompt_still_carries_the_role_and_voice_rules(self):
        """El rol y las reglas de voz no se pierden al reescribir la fase."""
        assert "ingeniero de mezcla" in prompts.DIAGNOSIS_SYSTEM_PROMPT.lower()
        assert "no recomiendas presets" in prompts.DIAGNOSIS_SYSTEM_PROMPT.lower()


class TestVerdictBlockInThePrompt:
    """``verdict_block`` traduce el veredicto a lenguaje de sensaciones."""

    def test_without_a_verdict_the_block_is_empty(self):
        """Vacio EXACTO cuando no hay veredicto: el prompt no cambia."""
        assert prompts.verdict_block(None) == ""

    def test_the_block_shows_the_applied_route(self):
        verdict = _verdict(needs_mix=False)
        block = prompts.verdict_block(verdict, applied="master_only")
        assert "master_only" in block
        assert "Solo masterizar" in block

    def test_the_block_names_the_deficiencies_in_sensations_not_numbers(self):
        """El usuario lee sensaciones; el prompt no le escupe dB crudos.

        Uso un veredicto CON carencias reales: una medicion plana no reporta
        ninguna contra un target casi plano (todo cae bajo el umbral de 2 dB),
        asi que un test que espere carencias tiene que aportar una forma
        espectral de verdad.
        """
        verdict = _verdict_with_deficiencies()
        assert verdict.deficiencies, "el fixture tiene que producir carencias reales"
        block = prompts.verdict_block(verdict, applied="mix_then_master")

        # Las bandas se nombran en lenguaje humano, no como "60 Hz".
        assert "graves" in block.lower() or "sub" in block.lower()
        # Y la direccion importa: "le falta" y "le sobra" son opuestos.
        assert "le falta" in block.lower() or "le sobra" in block.lower()
        # El numero en Hz no se le muestra al usuario.
        for item in verdict.deficiencies:
            assert f"{item.band_hz} Hz" not in block

    def test_the_block_marks_the_recommended_route(self):
        verdict = _verdict(needs_mix=True)
        block = prompts.verdict_block(verdict, applied="auto")
        assert "recomendada" in block.lower()

    def test_the_block_states_that_the_user_has_the_last_word(self):
        """El modelo tiene que saber que la ruta NO esta cerrada.

        Si el prompt presentara la ruta como definitiva, Brik le diria al
        usuario que ya decidio, cuando en realidad la decision es suya.
        """
        verdict = _verdict(needs_mix=True)
        block = prompts.verdict_block(verdict, applied="auto")
        lowered = block.lower()
        assert "usuario" in lowered
        assert "ultima palabra" in lowered or "última palabra" in lowered


class TestGeminiTransport:
    def test_refuses_to_start_without_a_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(GeminiUnavailableError):
            GeminiTransport()

    def test_default_chain_is_primary_plus_fallbacks(self):
        transport = GeminiTransport(api_key="fake")
        assert transport.models == (
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.5-flash",
        )

    def test_a_custom_primary_that_is_also_a_fallback_is_not_retried(self):
        transport = GeminiTransport(api_key="fake", model="gemini-3.6-flash")
        assert transport.models == ("gemini-3.6-flash", "gemini-3.5-flash")

    def test_function_responses_travel_on_a_user_turn(self):
        """The SDK only accepts 'user' or 'model': there is no 'tool' role."""
        contents = _to_contents(
            [
                {"role": "user", "text": "hola"},
                {"role": "model", "function_call": {"name": "render_mix", "args": {}}},
                {"role": "tool", "name": "render_mix", "response": {"ok": True}},
            ]
        )
        assert [c.role for c in contents] == ["user", "model", "user"]

    def test_empty_text_entries_are_dropped(self):
        assert _to_contents([{"role": "model", "text": ""}]) == []


class TestTheThoughtSignatureSurvivesTheRoundTrip:
    """The ``400 Function call is missing a thought_signature``.

    A thinking model marks its function-call part with an opaque signature and
    rejects any later turn whose history repeats that call without it. The
    neutral transcript carried only name/args, so the rebuilt part always lost
    the signature. These tests pin it on both ends and through the recorder.
    """

    SIGNATURE = b"\x01\x9f\xf2opaque"

    def _response(self) -> SimpleNamespace:
        part = types.Part(
            function_call=types.FunctionCall(
                name="adjust_stem_parameters", args={"stem": "vocals"}
            ),
            thought_signature=self.SIGNATURE,
        )
        return SimpleNamespace(
            candidates=[
                SimpleNamespace(content=types.Content(role="model", parts=[part]))
            ],
            function_calls=[
                types.FunctionCall(
                    name="adjust_stem_parameters", args={"stem": "vocals"}
                )
            ],
            text="",
        )

    def _transport(self, response: SimpleNamespace) -> GeminiTransport:
        models = SimpleNamespace(generate_content=lambda **_: response)
        return GeminiTransport(client=SimpleNamespace(models=models))

    def test_the_turn_hands_the_signature_to_the_loop(self):
        turn = self._transport(self._response()).turn(
            phase="phase3", system="s", transcript=[], tools=[]
        )
        assert turn.tool_calls[0].name == "adjust_stem_parameters"
        assert turn.tool_calls[0].thought_signature == base64.b64encode(
            self.SIGNATURE
        ).decode("ascii")

    def test_a_rebuilt_history_carries_the_signature(self):
        encoded = base64.b64encode(self.SIGNATURE).decode("ascii")
        contents = _to_contents(
            [
                {
                    "role": "model",
                    "function_call": {
                        "name": "adjust_stem_parameters",
                        "args": {"stem": "vocals"},
                        "thought_signature": encoded,
                    },
                }
            ]
        )
        assert contents[0].parts[0].thought_signature == self.SIGNATURE

    def test_a_call_without_a_signature_rebuilds_as_before(self):
        """Non-thinking providers never set it; the part stays valid."""
        contents = _to_contents(
            [{"role": "model", "function_call": {"name": "render_mix", "args": {}}}]
        )
        assert contents[0].parts[0].thought_signature is None

    def test_the_loop_records_what_it_has_to_echo(self):
        transport = self._transport(self._response())
        turn = transport.turn(phase="phase3", system="s", transcript=[], tools=[])
        transcript: list[dict] = []
        al._record_exchange(
            transcript,
            turn.tool_calls[0],
            al.ToolResult(ok=True, tool="adjust_stem_parameters", detail="ok"),
        )
        assert _to_contents(transcript)[0].parts[0].thought_signature == self.SIGNATURE

    def test_assign_call_ids_keeps_the_signature(self):
        encoded = base64.b64encode(self.SIGNATURE).decode("ascii")
        out = al.assign_call_ids(
            [
                {
                    "role": "model",
                    "function_call": {
                        "name": "render_mix",
                        "args": {},
                        "thought_signature": encoded,
                    },
                }
            ]
        )
        assert out[0]["function_call"]["thought_signature"] == encoded
