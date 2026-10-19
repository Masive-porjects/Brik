"""S2: the parts of the contract that every provider shares.

The model must see plain JSON Schema built from the Pydantic models, never an
SDK's native tool type. That was already true — ``tool_definitions()`` emits
``model_json_schema()`` and the Gemini adapter hands it over as
``parameters_json_schema`` — so the first class here is a regression fence, not
a fix.

The second half pins ``assign_call_ids``: OpenAI and Anthropic both demand an id
linking a tool call to its result, and the neutral transcript does not carry
one. Deriving it in one shared place keeps each adapter from inventing its own
rule.
"""
from __future__ import annotations

from typing import Any

import pytest

from audiomind.config import settings
from audiomind.processing import agentic_loop as al
from audiomind.processing.anthropic_transport import AnthropicTransport
from audiomind.processing.gemini_transport import (
    GeminiTransport,
    GeminiUnavailableError,
)


class TestTheToolSchemaStaysNeutral:
    def test_tools_are_plain_json_schema(self) -> None:
        tools = al.tool_definitions()
        assert tools
        for tool in tools:
            assert set(tool) == {"name", "description", "parameters"}
            assert tool["parameters"]["type"] == "object"
            assert isinstance(tool["parameters"]["properties"], dict)

    def test_the_schema_is_a_dict_not_a_model_instance(self) -> None:
        for tool in al.tool_definitions(include_rag=True):
            assert type(tool["parameters"]) is dict


class TestErrorHierarchy:
    def test_the_gemini_error_is_a_transport_error(self) -> None:
        """Every adapter raises one kind of error so callers stay provider-blind."""
        assert issubclass(GeminiUnavailableError, al.TransportUnavailableError)


class TestCallIds:
    def test_a_call_and_its_response_share_an_id(self) -> None:
        out = al.assign_call_ids(
            [
                {"role": "user", "text": "hola"},
                {"role": "model", "function_call": {"name": "render_mix", "args": {}}},
                {"role": "tool", "name": "render_mix", "response": {"ok": True}},
            ]
        )
        call_id = out[1]["function_call"]["id"]
        assert call_id
        assert out[2]["id"] == call_id

    def test_repeated_tool_names_pair_in_order(self) -> None:
        out = al.assign_call_ids(
            [
                {
                    "role": "model",
                    "function_call": {"name": "render_mix", "args": {"i": 1}},
                },
                {"role": "tool", "name": "render_mix", "response": {"i": 1}},
                {
                    "role": "model",
                    "function_call": {"name": "render_mix", "args": {"i": 2}},
                },
                {"role": "tool", "name": "render_mix", "response": {"i": 2}},
            ]
        )
        first = out[0]["function_call"]["id"]
        second = out[2]["function_call"]["id"]
        assert first != second
        assert out[1]["id"] == first
        assert out[3]["id"] == second

    def test_two_calls_in_one_turn_get_distinct_ids(self) -> None:
        out = al.assign_call_ids(
            [
                {"role": "model", "function_call": {"name": "render_mix", "args": {}}},
                {
                    "role": "model",
                    "function_call": {"name": "analyze_mix_bus", "args": {}},
                },
                {"role": "tool", "name": "render_mix", "response": {}},
                {"role": "tool", "name": "analyze_mix_bus", "response": {}},
            ]
        )
        assert out[0]["function_call"]["id"] != out[1]["function_call"]["id"]
        assert out[2]["id"] == out[0]["function_call"]["id"]
        assert out[3]["id"] == out[1]["function_call"]["id"]

    def test_text_entries_pass_through_unchanged(self) -> None:
        entry: dict[str, Any] = {"role": "user", "text": "hola"}
        assert al.assign_call_ids([entry]) == [entry]

    def test_it_does_not_mutate_the_input(self) -> None:
        original: list[dict[str, Any]] = [
            {"role": "model", "function_call": {"name": "render_mix", "args": {}}},
            {"role": "tool", "name": "render_mix", "response": {}},
        ]
        al.assign_call_ids(original)
        assert "id" not in original[0]["function_call"]
        assert "id" not in original[1]

    def test_ids_are_stable_across_calls(self) -> None:
        """Rebuilding the same transcript must not reshuffle the ids."""
        transcript: list[dict[str, Any]] = [
            {"role": "model", "function_call": {"name": "render_mix", "args": {}}},
            {"role": "tool", "name": "render_mix", "response": {}},
        ]
        assert al.assign_call_ids(transcript) == al.assign_call_ids(transcript)


class TestTheLoopFactoryIsConfigDriven:
    """The seam between the loop and the registry: one line in ``.env``."""

    def test_it_builds_what_the_config_asks_for(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "llm_provider", "anthropic")
        monkeypatch.setattr(settings, "agent_model_name", "claude-3-5-sonnet")
        monkeypatch.setattr(settings, "llm_api_key", "k")

        assert isinstance(al.default_transport(), AnthropicTransport)

    def test_it_still_defaults_to_gemini(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "llm_provider", "gemini")
        monkeypatch.setattr(settings, "agent_model_name", "")
        monkeypatch.setattr(settings, "gemini_api_key", "fake")

        assert isinstance(al.default_transport(), GeminiTransport)
