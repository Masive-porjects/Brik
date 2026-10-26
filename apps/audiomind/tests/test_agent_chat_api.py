"""HTTP contract for ``POST /api/agent/chat``.

Why this module exists
----------------------
The chat endpoint was covered only by unit tests on the heuristic router
(``tests/test_chat_router.py``) and by nothing that exercised the ASGI surface.
That gap is why a production build without the route (an image older than
``9da4688``) passed the whole suite while the frontend got a 404: no test ever
asked the app whether ``/api/agent/chat`` exists.

These tests pin the three things that actually broke or could break:

1. The route is registered at the exact coordinate the frontend calls
   (``API_BASE`` ends in ``/api``, so ``client.ts`` requests
   ``/api/agent/chat``).
2. An explanation is answered in chat and the turn is persisted.
3. An action request escalates to a job *without* spending an LLM call.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import audiomind.api.agent as agent_api
import audiomind.session_store as session_store
from audiomind.main import app
from audiomind.models.audio import SessionData
from audiomind.session_store import load_sessions, save_sessions

client = TestClient(app)

SESSION_ID = "chat-api-session"
CHAT_PATH = "/api/agent/chat"


class _RecordingTransport:
    """Stand-in for the real LLM transport: records calls, returns fixed text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def turn(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.text)


@pytest.fixture(autouse=True)
def _session_in_the_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Persist one session the way the app reads it.

    ``chat_with_brik`` loads sessions through ``session_store.load_sessions``,
    not through the ``api.upload`` dict, so the session has to be written to the
    backend the harness pins per test (``conftest._sessions_never_leave_tmp_path``).

    ``_last_digests`` is reset first: it is process-global and survives between
    tests, so a session whose digest a previous test already recorded would be
    skipped by the write-behind and silently never persist.
    """
    monkeypatch.setattr(session_store, "_last_digests", {})

    sessions = load_sessions()
    sessions[SESSION_ID] = SessionData(session_id=SESSION_ID)
    save_sessions(sessions)


def test_the_chat_route_is_registered_under_the_api_prefix() -> None:
    """A missing route answers ``{"detail": "Not Found"}``; the handler does not.

    The handler's own 404 for an unknown session is the cheap proof that the
    request reached ``chat_with_brik`` instead of Starlette's 404 fallback.
    """
    response = client.post(
        CHAT_PATH, json={"session_id": "no-existe", "message": "hola"}
    )

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail != "Not Found"
    assert "no encontrada" in detail


def test_the_openapi_schema_publishes_the_chat_path() -> None:
    """Guards the registry itself, which is what the deployed build lacked."""
    assert CHAT_PATH in app.openapi()["paths"]


def test_an_explanation_is_answered_in_chat_and_the_turn_is_persisted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _RecordingTransport("Subo un toque el aire en los agudos.")
    monkeypatch.setattr(agent_api, "default_transport", lambda: transport)

    response = client.post(
        CHAT_PATH,
        json={
            "session_id": SESSION_ID,
            "message": "¿Por qué el veredicto pide más aire?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Subo un toque el aire en los agudos."
    assert body["escalation"]["action"] == "answer_in_chat"

    # One LLM call, chat phase, no tools: the endpoint is not allowed to run the
    # agentic tool loop from a chat turn.
    assert len(transport.calls) == 1
    assert transport.calls[0]["phase"] == "chat"
    assert transport.calls[0]["tools"] == []
    assert transport.calls[0]["transcript"][-1] == {
        "role": "user",
        "text": "¿Por qué el veredicto pide más aire?",
    }

    stored = load_sessions()[SESSION_ID]
    assert [entry.role for entry in stored.chat_transcript[-2:]] == [
        "user",
        "assistant",
    ]
    assert stored.chat_transcript[-1].text == "Subo un toque el aire en los agudos."


def test_an_action_escalates_without_calling_the_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _RecordingTransport("esta respuesta no debería existir")
    monkeypatch.setattr(agent_api, "default_transport", lambda: transport)

    response = client.post(
        CHAT_PATH, json={"session_id": SESSION_ID, "message": "mezcla la pista"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["escalation"]["action"] == "escalate_to_job"
    # No verdict on the session: the direct master job is the documented choice.
    assert body["escalation"]["job_kind"] == "master"
    assert body["escalation"]["job_payload"] == {"source": "original"}
    assert "master" in body["reply"]
    assert transport.calls == []
