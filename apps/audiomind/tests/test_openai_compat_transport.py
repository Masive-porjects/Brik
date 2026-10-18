"""S2/S3: the OpenAI-compatible adapter covers DeepSeek and Ollama with one shape.

Both vendors — and every self-hosted server that speaks
``POST /v1/chat/completions`` — share this protocol, so one adapter covers them.
That is why the feature ships two adapters and not three.

No network: ``httpx.MockTransport`` runs the real httpx code path with a canned
response, so serialisation and parsing are exercised for real.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from audiomind.processing.agentic_loop import TransportUnavailableError
from audiomind.processing.openai_compat_transport import OpenAICompatTransport

BASE_URL = "https://api.deepseek.com/v1"

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


def _capture(
    seen: list[httpx.Request], body: dict[str, Any], status: int = 200
) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=body)

    return handler


def _transport(handler: Any, **overrides: Any) -> OpenAICompatTransport:
    overrides.setdefault("api_key", "fake")
    overrides.setdefault("model", "deepseek-chat")
    overrides.setdefault("base_url", BASE_URL)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAICompatTransport(client=client, **overrides)


def _wire(seen: list[httpx.Request]) -> dict[str, Any]:
    return json.loads(seen[0].content.decode("utf-8"))


class TestRefusals:
    def test_it_will_not_start_without_a_key(self) -> None:
        with pytest.raises(TransportUnavailableError):
            OpenAICompatTransport(api_key="", model="m", base_url=BASE_URL)

    def test_it_will_not_start_without_a_model(self) -> None:
        with pytest.raises(TransportUnavailableError):
            OpenAICompatTransport(api_key="k", model="", base_url=BASE_URL)

    def test_an_http_error_is_a_typed_failure(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"error": "boom"}, status=401))
        with pytest.raises(TransportUnavailableError):
            transport.turn(phase="phase1", system="s", transcript=[], tools=[])

    def test_an_empty_reply_is_a_typed_failure(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"choices": []}))
        with pytest.raises(TransportUnavailableError):
            transport.turn(phase="phase1", system="s", transcript=[], tools=[])


class TestTheWireBody:
    def test_it_posts_to_the_chat_completions_route(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"choices": []}))
        with pytest.raises(TransportUnavailableError):
            transport.turn(phase="phase1", system="s", transcript=[], tools=[])
        assert str(seen[0].url) == f"{BASE_URL}/chat/completions"

    def test_it_sends_the_bearer_token(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"choices": []}), api_key="sk-xyz")
        with pytest.raises(TransportUnavailableError):
            transport.turn(phase="phase1", system="s", transcript=[], tools=[])
        assert seen[0].headers["authorization"] == "Bearer sk-xyz"

    def test_the_system_prompt_leads_the_messages(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"choices": []}))
        with pytest.raises(TransportUnavailableError):
            transport.turn(
                phase="phase1",
                system="SOS UN INGENIERO",
                transcript=[{"role": "user", "text": "hola"}],
                tools=[],
            )
        messages = _wire(seen)["messages"]
        assert messages[0] == {"role": "system", "content": "SOS UN INGENIERO"}
        assert messages[1] == {"role": "user", "content": "hola"}

    def test_the_tool_schema_travels_as_plain_json_schema(self) -> None:
        """S2: the Pydantic schema goes on the wire untouched, no SDK type."""
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"choices": []}))
        with pytest.raises(TransportUnavailableError):
            transport.turn(phase="phase1", system="s", transcript=[], tools=TOOLS)
        tools = _wire(seen)["tools"]
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "render_mix"
        assert tools[0]["function"]["parameters"] == TOOLS[0]["parameters"]

    def test_no_tools_key_is_sent_when_there_are_none(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"choices": []}))
        with pytest.raises(TransportUnavailableError):
            transport.turn(phase="phase1", system="s", transcript=[], tools=[])
        assert "tools" not in _wire(seen)

    def test_the_model_and_temperature_are_sent(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(
            _capture(seen, {"choices": []}), model="deepseek-chat", temperature=0.2
        )
        with pytest.raises(TransportUnavailableError):
            transport.turn(phase="phase1", system="s", transcript=[], tools=[])
        body = _wire(seen)
        assert body["model"] == "deepseek-chat"
        assert body["temperature"] == 0.2


class TestTheTranscript:
    def test_a_tool_response_carries_its_call_id(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"choices": []}))
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
        assert call["tool_calls"][0]["function"]["arguments"] == json.dumps({"a": 1})
        result = messages[-1]
        assert result["role"] == "tool"
        assert result["tool_call_id"] == call["tool_calls"][0]["id"]
        assert json.loads(result["content"]) == {"ok": True}

    def test_a_model_text_turn_maps_to_assistant(self) -> None:
        seen: list[httpx.Request] = []
        transport = _transport(_capture(seen, {"choices": []}))
        with pytest.raises(TransportUnavailableError):
            transport.turn(
                phase="phase1",
                system="s",
                transcript=[{"role": "model", "text": "listo"}],
                tools=[],
            )
        assert _wire(seen)["messages"][-1] == {"role": "assistant", "content": "listo"}


class TestParsingTheReply:
    def test_a_tool_call_becomes_a_model_turn(self) -> None:
        seen: list[httpx.Request] = []
        body = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "render_mix",
                                    "arguments": '{"vocal_focus": 0.6}',
                                },
                            }
                        ],
                    }
                }
            ]
        }
        turn = _transport(_capture(seen, body)).turn(
            phase="phase3", system="s", transcript=[], tools=TOOLS
        )
        assert turn.text == ""
        assert len(turn.tool_calls) == 1
        assert turn.tool_calls[0].name == "render_mix"
        assert turn.tool_calls[0].args == {"vocal_focus": 0.6}

    def test_plain_text_becomes_a_model_turn(self) -> None:
        seen: list[httpx.Request] = []
        body = {"choices": [{"message": {"role": "assistant", "content": "  la voz "}}]}
        turn = _transport(_capture(seen, body)).turn(
            phase="phase1", system="s", transcript=[], tools=[]
        )
        assert turn.text == "la voz"
        assert turn.tool_calls == []

    def test_parallel_tool_calls_are_all_returned(self) -> None:
        seen: list[httpx.Request] = []
        calls = [
            {
                "id": "a",
                "type": "function",
                "function": {"name": "render_mix", "arguments": "{}"},
            },
            {
                "id": "b",
                "type": "function",
                "function": {"name": "analyze_mix_bus", "arguments": "{}"},
            },
        ]
        message = {"role": "assistant", "content": None, "tool_calls": calls}
        body = {"choices": [{"message": message}]}
        turn = _transport(_capture(seen, body)).turn(
            phase="phase3", system="s", transcript=[], tools=TOOLS
        )
        assert [c.name for c in turn.tool_calls] == ["render_mix", "analyze_mix_bus"]

    def test_malformed_tool_arguments_are_not_silently_empty(self) -> None:
        """Falling back to ``{}`` would move faders with no intent behind them."""
        seen: list[httpx.Request] = []
        body = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "render_mix",
                                    "arguments": "{no-es-json",
                                },
                            }
                        ],
                    }
                }
            ]
        }
        with pytest.raises(TransportUnavailableError):
            _transport(_capture(seen, body)).turn(
                phase="phase3", system="s", transcript=[], tools=TOOLS
            )

    def test_a_text_reply_wins_over_an_empty_tool_list(self) -> None:
        seen: list[httpx.Request] = []
        body = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "ya esta",
                        "tool_calls": [],
                    }
                }
            ]
        }
        turn = _transport(_capture(seen, body)).turn(
            phase="phase4", system="s", transcript=[], tools=[]
        )
        assert turn.text == "ya esta"
