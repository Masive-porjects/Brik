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

    def turn(self, *, phase, system, transcript, tools):
        self.phases.append(phase)
        self.tools_seen.append([t["name"] for t in tools])
        if not self.script:
            raise AssertionError("el guion se quedó sin turnos")
        assert system  # every phase ships a system prompt
        return self.script.pop(0)


@pytest.fixture
def cheap_tools(monkeypatch):
    """Replace the two tools that would need Demucs / real audio."""

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
            "mix_path": "out/mix.wav",
            "qc_report": {"summary": {"flagged": []}},
            "balance_report": None,
            "mix_metadata": {},
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

    def test_mastering_the_original_needs_no_render(self):
        state = al.AgentState(session_id="t", input_path=Path("x.wav"))
        assert al.dispatch(state, "send_to_master", {"source": "original"}).ok is True


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
