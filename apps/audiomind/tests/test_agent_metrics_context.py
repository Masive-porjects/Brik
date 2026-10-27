"""Fase B: the metrics contract reaches the agent's context.

Why this module exists
----------------------
The agent can only diagnose with numbers it actually receives. Fase A
published ``GET /api/session/{id}/metrics``; these tests pin that the same
measured values (bands in dBFS + the loudness standard) ride along in the
``/api/agent/chat`` context, and that the system prompt demands receipts:
every cited number must come from that context, never from imagination.

Pinned behaviors:

1. ``_snapshot_to_context_text`` publishes the measured bands and the
   loudness standard exactly as Fase A stores them (aligned, signed).
2. Legacy analyses (pre-contract payloads) render the same old text without
   any band block - the diagnosis layer never fabricates empties.
3. The chat system prompt carries the metrics block to the LLM.
4. ``DIAGNOSIS_SYSTEM_PROMPT`` requires the DIAGNOSTICO + RECETA structure
   with real metric citations and the honesty clause on the standard.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import audiomind.api.agent as agent_api
import audiomind.session_store as session_store
from audiomind.main import app
from audiomind.models.audio import AnalysisResult, SessionData
from audiomind.processing import prompts
from audiomind.session_store import load_sessions, save_sessions

client = TestClient(app)

SESSION_ID = "metrics-context-session"
CHAT_PATH = "/api/agent/chat"

EXPECTED_BANDS = [60, 150, 400, 1000, 2500, 6000, 10000, 15000]
EXPECTED_ENERGIES = [-10.2, -6.4, -3.9, -7.5, -8.8, -11.1, -14.7, -16.3]


class _RecordingTransport:
    """Stand-in for the real LLM transport: records calls, returns fixed text."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    def turn(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.text)


def _analysis() -> AnalysisResult:
    return AnalysisResult(
        integrated_lufs=-18.4,
        true_peak_db=-3.1,
        dynamic_range_db=12.5,
        spectral_centroid=2450.7,
        tempo_bpm=120.0,
        duration_seconds=180.0,
        sample_rate=44100,
        channels=2,
        detected_genre="pop",
        genre_confidence=0.55,
        crest_factor_db=14.2,
        is_already_mastered=False,
        mastering_confidence=0.2,
        bands_hz=EXPECTED_BANDS,
        band_energies_db=EXPECTED_ENERGIES,
    )


def test_context_text_publishes_the_measured_bands_and_standard() -> None:
    """The diagnosis context carries the same numbers the metrics endpoint does."""
    snapshot = agent_api.SessionSnapshot(analysis=_analysis())

    text = agent_api._snapshot_to_context_text(snapshot)

    assert "ITU-R BS.1770-4" in text
    # Aligned, signed, per band - and the 150 Hz value is the measured one.
    assert "150 Hz: -6.4" in text
    assert "60 Hz: -10.2" in text
    # dBFS on the label: the agent must not attribute values to a scale
    # that is not declared.
    assert "dBFS" in text


def test_context_text_stays_compatible_with_legacy_analyses() -> None:
    """Pre-contract payloads render the old text without a fabricated band block."""
    legacy = _analysis().model_dump()
    legacy.pop("bands_hz", None)
    legacy.pop("band_energies_db", None)
    snapshot = agent_api.SessionSnapshot(
        analysis=AnalysisResult.model_validate(legacy)
    )

    text = agent_api._snapshot_to_context_text(snapshot)

    # The old analysis lines survive verbatim in meaning...
    assert "LUFS integrado: -18.4" in text
    # ...and no empty band block is fabricated.
    assert "dBFS" not in text
    assert "ITU-R BS.1770-4" not in text


def test_the_chat_prompt_carries_the_metrics_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The LLM call receives the measured bands, not a stripped-down context."""
    monkeypatch.setattr(session_store, "_last_digests", {})
    sessions = load_sessions()
    sessions[SESSION_ID] = SessionData(
        session_id=SESSION_ID, analysis=_analysis()
    )
    save_sessions(sessions)

    transport = _RecordingTransport("Diagnostico: medios limpios. Receta: master auto.")
    monkeypatch.setattr(agent_api, "default_transport", lambda: transport)

    response = client.post(
        CHAT_PATH,
        json={"session_id": SESSION_ID, "message": "¿Por qué el veredicto pide más aire?"},
    )

    assert response.status_code == 200
    assert len(transport.calls) == 1
    system = transport.calls[0]["system"]

    assert "ITU-R BS.1770-4" in system
    assert "150 Hz: -6.4" in system
    assert "dBFS" in system


def test_the_diagnosis_prompt_demands_real_metric_citations() -> None:
    """The prompt rules pin the diagnosis + receipt structure and its honesty."""
    prompt = prompts.DIAGNOSIS_SYSTEM_PROMPT

    # The two labeled blocks exist as a contract...
    assert "DIAGNOSTICO" in prompt
    assert "RECETA" in prompt
    # ...and the honesty clause forbids numbers outside the context.
    assert "numeros que aparecieron en el contexto" in prompt
    # The LUFS standard may only be named as the context declares it.
    assert "estandar" in prompt
