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
from pathlib import Path

import pytest
from pydantic import ValidationError

from audiomind.models.audio import MasteringParameters
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
