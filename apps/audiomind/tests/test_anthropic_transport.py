"""S3: the Anthropic adapter.

Anthropic's Messages API is not OpenAI-shaped: the system prompt is a top-level
field, tools carry ``input_schema``, tool calls are ``tool_use`` content blocks
and their results come back inside a ``user`` turn as ``tool_result`` blocks.
That is exactly why it needs its own adapter rather than reusing the
OpenAI-compatible one.

No network: ``httpx.MockTransport`` runs the real httpx code path.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from audiomind.processing.agentic_loop import TransportUnavailableError
from audiomind.processing.anthropic_transport import AnthropicTransport

BASE_URL = "https://api.anthropic.com/v1"
MODEL = "claude-3-5-sonnet"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "render_mix",
        "description": "Render the current faders.",
        "parameters": {
            "type": "object",
            "properties": {"vocal_focus": {"type": "number"}},
            "required": [],
        },
    }
]


def _capture(seen: list[httpx.Request], body: dict[str, Any], status: int = 200) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return handler


def _transport(handler: Any, **overrides: Any) -> AnthropicTransport:
    overrides.setdefault("api_key", "fake")
    overrides.setdefault("model", MODEL)
    overrides.setdefault("base_url", BASE_URL)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return AnthropicTransport(client=client, **overrides)


def _wire(seen: list[httpx.Request]) -> dict[str, Any]:
    return json.loads(seen[0].content.decode("utf-8"))


def _empty(seen: list[httpx.Request], transport: AnthropicTransport) -> None:
    with pytest.raises(TransportUnavailableError):
        transport.turn(phase="phase1", system="s", transcript=[], tools=[])


class TestRefusals:
    def test_it_will_not_start_without_a_key(self) -> None:
        with pytest.raises(TransportUnavailableError):
            AnthropicTransport(api_key="", model=MODEL, base_url=BASE_URL)

    def test_it_will_not_start_without_a_model(self) -> None:
        with pytest.raises(TransportUnavailableError):
            AnthropicTransport(api_key="k", model="", base_url=BASE_URL)

    def test_an_http_error_is_a_typed_failure(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"error": "boom"}, status=400))
        _empty(seen, transport)

    def test_an_empty_reply_is_a_typed_failure(self) -> None:
        seen: list[httpx.Request] = []
        _empty(seen, _transport(_capture(seen, {"content": []})))


class TestTheWireBody:
    def test_it_posts_to_the_messages_route(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"content": []}))
        _empty(seen, transport)
        assert str(seen[0].url) == f"{BASE_URL}/messages"

    def test_it_sends_the_api_key_and_the_version_header(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"content": []}), api_key="sk-ant-1")
        _empty(seen, transport)
        assert seen[0].headers["x-api-key"] == "sk-ant-1"
        assert seen[0].headers["anthropic-version"] == "2023-06-01"

    def test_the_system_prompt_is_a_top_level_field(self) -> None:
        """Anthropic rejects a ``system`` message inside ``messages``."""
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"content": []}))
        with pytest.raises(TransportUnavailableError):
            transport.turn(
                phase="phase1",
                system="SOS UN INGENIERO",
                transcript=[{"role": "user", "text": "hola"}],
                tools=[],
            )
        body = _wire(seen)
        assert body["system"] == "SOS UN INGENIERO"
        assert body["messages"] == [
            {"role": "user", "content": [{"type": "text", "text": "hola"}]}
        ]

    def test_max_tokens_is_always_sent(self) -> None:
        """The API rejects a request without it."""
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"content": []}))
        _empty(seen, transport)
        assert _wire(seen)["max_tokens"] > 0

    def test_the_tool_schema_travels_as_input_schema(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"content": []}))
        with pytest.raises(TransportUnavailableError):
            transport.turn(phase="phase1", system="s", transcript=[], tools=TOOLS)
        tools = _wire(seen)["tools"]
        assert tools[0]["name"] == "render_mix"
        assert tools[0]["input_schema"] == TOOLS[0]["parameters"]

    def test_no_tools_key_is_sent_when_there_are_none(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"content": []}))
        _empty(seen, transport)
        assert "tools" not in _wire(seen)


class TestTheTranscript:
    def test_a_tool_response_becomes_a_tool_result_block(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"content": []}))
        with pytest.raises(TransportUnavailableError):
            transport.turn(
                phase="phase3",
                system="s",
                transcript=[
                    {
                        "role": "model",
                        "function_call": {"name": "render_mix", "args": {"a": 1}},
                    },
                    {"role": "tool", "name": "render_mix", "response": {"ok": True}},
                ],
                tools=TOOLS,
            )
        messages = _wire(seen)["messages"]
        call = messages[-2]
        assert call["role"] == "assistant"
        assert call["content"][0]["type"] == "tool_use"
        assert call["content"][0]["name"] == "render_mix"
        assert call["content"][0]["input"] == {"a": 1}
        result = messages[-1]
        assert result["role"] == "user"
        assert result["content"][0]["type"] == "tool_result"
        assert result["content"][0]["tool_use_id"] == call["content"][0]["id"]
        assert json.loads(result["content"][0]["content"]) == {"ok": True}

    def test_a_model_text_turn_becomes_assistant_text(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"content": []}))
        with pytest.raises(TransportUnavailableError):
            transport.turn(
                phase="phase1",
                system="s",
                transcript=[{"role": "model", "text": "listo"}],
                tools=[],
            )
        assert _wire(seen)["messages"][-1] == {
            "role": "assistant",
            "content": [{"type": "text", "text": "listo"}],
        }


class TestParsingTheReply:
    def test_a_tool_use_block_becomes_a_model_turn(self) -> None:
        seen: list[httpx.Request] = []
        body = {
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "render_mix",
                    "input": {"vocal_focus": 0.6},
                }
            ]
        }
        turn = _transport(_capture(seen, body)).turn(
            phase="phase3", system="s", transcript=[], tools=TOOLS
        )
        assert turn.text == ""
        assert turn.tool_calls[0].name == "render_mix"
        assert turn.tool_calls[0].args == {"vocal_focus": 0.6}

    def test_a_text_block_becomes_a_model_turn(self) -> None:
        seen: list[httpx.Request] = []
        body = {"content": [{"type": "text", "text": "  la voz esta tapada  "}]}
        turn = _transport(_capture(seen, body)).turn(
            phase="phase1", system="s", transcript=[], tools=[]
        )
        assert turn.text == "la voz esta tapada"

    def test_text_blocks_are_joined(self) -> None:
        seen: list[httpx.Request] = []
        body = {
            "content": [
                {"type": "text", "text": "primera"},
                {"type": "text", "text": "segunda"},
            ]
        }
        turn = _transport(_capture(seen, body)).turn(
            phase="phase1", system="s", transcript=[], tools=[]
        )
        assert turn.text == "primera segunda"

    def test_text_and_tool_use_can_travel_together(self) -> None:
        seen: list[httpx.Request] = []
        body = {
            "content": [
                {"type": "text", "text": "voy a medir"},
                {"type": "tool_use", "id": "t1", "name": "render_mix", "input": {}},
            ]
        }
        turn = _transport(_capture(seen, body)).turn(
            phase="phase3", system="s", transcript=[], tools=TOOLS
        )
        assert turn.text == "voy a medir"
        assert turn.tool_calls[0].name == "render_mix"
