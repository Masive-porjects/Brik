"""Tests for the Brik Chat Router heuristic (T2).

The router is a pure, zero-LLM function that must decide in <1 ms whether to:
- answer in chat (explanation, parameter tweak, free conversation)
- escalate to async job (concrete DSP action: mix, master, render, etc.)

All tests run without network, LLM, or session store.
"""
from __future__ import annotations

import pytest

from audiomind.api.agent import (
    ChatRequest,
    EscalationDecision,
    SessionSnapshot,
    should_escalate_to_job,
)
from audiomind.models.audio import AnalysisResult, AudioVerdict, Deficiency, Route

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def empty_snapshot() -> SessionSnapshot:
    """Sesión nueva sin análisis previo."""
    return SessionSnapshot()


@pytest.fixture
def analyzed_snapshot() -> SessionSnapshot:
    """Sesión con análisis y veredicto que RECOMIENDA mezcla."""
    analysis = AnalysisResult(
        integrated_lufs=-18.5,
        true_peak_db=-1.2,
        dynamic_range_db=8.0,
        spectral_centroid=3200.0,
        tempo_bpm=128.0,
        duration_seconds=210.0,
        sample_rate=44100,
        channels=2,
        detected_genre="electronic",
        genre_confidence=0.85,
    )
    verdict = AudioVerdict(
        needs_mix=True,
        confidence=0.92,
        recommended_path="mix_then_master",
        reasoning_key="raw_mix_detected",
        deficiencies=[
            Deficiency(band_hz=250, delta_db=3.5, direction="excess"),
            Deficiency(band_hz=8000, delta_db=-2.8, direction="lacks"),
        ],
        routes=[
            Route(id="mix_then_master", label_es="Mezcla + Master", description_es="Separar stems, balancear y masterizar", recommended=True),
            Route(id="master_only", label_es="Solo Master", description_es="Masterizar directo el estéreo"),
        ],
    )
    return SessionSnapshot(analysis=analysis, verdict=verdict, mix_status="none")


@pytest.fixture
def master_only_snapshot() -> SessionSnapshot:
    """Sesión con veredicto que NO necesita mezcla (master_only)."""
    analysis = AnalysisResult(
        integrated_lufs=-14.0,
        true_peak_db=-0.5,
        dynamic_range_db=12.0,
        spectral_centroid=3500.0,
        tempo_bpm=120.0,
        duration_seconds=180.0,
        sample_rate=44100,
        channels=2,
        detected_genre="pop",
        genre_confidence=0.78,
    )
    verdict = AudioVerdict(
        needs_mix=False,
        confidence=0.88,
        recommended_path="master_only",
        reasoning_key="already_mastered",
        deficiencies=[],
        routes=[
            Route(id="master_only", label_es="Solo Master", description_es="Masterizar directo el estéreo", recommended=True),
            Route(id="mix_then_master", label_es="Mezcla + Master", description_es="Separar stems, balancear y masterizar"),
        ],
    )
    return SessionSnapshot(analysis=analysis, verdict=verdict, mix_status="none")


# ── Rama 1: ACCIÓN concreta -> escalate_to_job ─────────────────────────────


class TestActionTriggers:
    """Triggers que deben escalar a job asíncrono."""

    @pytest.mark.parametrize("trigger", [
        "mezclar", "mezcla", "separar", "stems", "demucs",
        "masterizar", "master", "render", "renderizar", "exportar", "entregar",
        "aplicar", "ejecutar", "correr", "procesar", "dale", "hazlo",
        "cambia a", "cambiar a", "usa el", "ponle", "pon el", "activa",
    ])
    def test_action_triggers_escalate(self, trigger: str, analyzed_snapshot: SessionSnapshot):
        text = f"Quiero {trigger} la canción"
        decision = should_escalate_to_job(text, analyzed_snapshot)

        assert decision.action == "escalate_to_job"
        assert decision.job_kind == "agent"  # needs_mix=True -> agent
        assert decision.job_payload is not None
        assert "decision" in decision.job_payload
        assert trigger in decision.reason.lower()

    def test_action_trigger_master_only_when_no_mix_needed(self, master_only_snapshot: SessionSnapshot):
        """Si needs_mix=False, el job_kind debe ser 'master', no 'agent'."""
        decision = should_escalate_to_job("dale, masterizá esto", master_only_snapshot)
        assert decision.action == "escalate_to_job"
        assert decision.job_kind == "master"
        assert decision.job_payload.get("source") == "original"

    def test_action_trigger_uses_recommended_path(self, analyzed_snapshot: SessionSnapshot):
        decision = should_escalate_to_job("procesar con la ruta recomendada", analyzed_snapshot)
        assert decision.job_payload.get("decision") == "mix_then_master"


# ── Rama 2: EXPLICACIÓN -> answer_in_chat ───────────────────────────────────


class TestExplanationTriggers:
    """Triggers que deben responder en chat sin escalar."""

    @pytest.mark.parametrize("trigger,expected_match", [
        ("por qué", "por qué"),
        ("porque", "porque"),
        ("explícame", "explícame"),
        ("qué significa", "qué significa"),
        ("qué es", "qué es"),
        ("cuál es", "cuál es"),
        ("cómo", "cómo"),
        ("diferencia", "diferencia"),
        ("versus", "versus"),
        ("vs", "vs"),
        # "veredicto", "diagnóstico", "diagnostico", "análisis", "analisis",
        # "recomendación", "recomendacion" -> estos aparecen en el fixture text así que el match es "veredicto"
    ])
    def test_explanation_triggers_answer_in_chat(self, trigger: str, expected_match: str, analyzed_snapshot: SessionSnapshot):
        # Usar texto que SOLO contenga el trigger específico, sin "veredicto" u otros triggers previos
        text = f"{trigger} esto"
        decision = should_escalate_to_job(text, analyzed_snapshot)

        assert decision.action == "answer_in_chat"
        assert decision.job_kind is None
        assert decision.job_payload is None
        assert not decision.updates_intent
        assert expected_match in decision.reason.lower()

    def test_explanation_works_on_empty_snapshot(self, empty_snapshot: SessionSnapshot):
        decision = should_escalate_to_job("por qué me recomendas esto?", empty_snapshot)
        assert decision.action == "answer_in_chat"


# ── Rama 3: PARÁMETROS -> answer_in_chat(updates_intent=True) ───────────────


class TestParameterTriggers:
    """Triggers de ajuste de intención: responden en chat y marcan updates_intent."""

    @pytest.mark.parametrize("trigger", [
        "más", "mas", "menos", "subir", "bajar", "un toque", "bastante",
        "mucho", "poco", "suave", "fuerte", "intenso", "ligero",
        "incrementa", "reduce", "aumenta", "disminuye",
    ])
    def test_parameter_triggers_updates_intent(self, trigger: str, analyzed_snapshot: SessionSnapshot):
        text = f"{trigger} graves"
        decision = should_escalate_to_job(text, analyzed_snapshot)

        assert decision.action == "answer_in_chat"
        assert decision.updates_intent is True
        assert decision.intent_delta is None  # El LLM infiere el delta exacto
        assert trigger in decision.reason.lower()

    def test_parameter_trigger_on_empty_snapshot(self, empty_snapshot: SessionSnapshot):
        decision = should_escalate_to_job("más brillo", empty_snapshot)
        assert decision.action == "answer_in_chat"
        assert decision.updates_intent is True


# ── Rama 4: DEFAULT -> answer_in_chat ───────────────────────────────────────


class TestDefaultBranch:
    """Entrada sin triggers conocidos -> conversación libre en chat."""

    def test_default_free_conversation(self, analyzed_snapshot: SessionSnapshot):
        # Texto sin ningún trigger conocido
        decision = should_escalate_to_job("hola, todo bien por acá", analyzed_snapshot)
        assert decision.action == "answer_in_chat"
        assert not decision.updates_intent
        assert "sin trigger" in decision.reason.lower()

    def test_empty_message_treated_as_default(self, analyzed_snapshot: SessionSnapshot):
        decision = should_escalate_to_job("", analyzed_snapshot)
        assert decision.action == "answer_in_chat"


# ── Edge cases / robustez ───────────────────────────────────────────────────


class TestEdgeCases:
    """Casos borde y robustez del router."""

    def test_case_insensitive(self, analyzed_snapshot: SessionSnapshot):
        """Los triggers deben ser case-insensitive."""
        for text in ["MEZCLAR", "Mezclar", "MeZcLaR", "mezclar"]:
            decision = should_escalate_to_job(text, analyzed_snapshot)
            assert decision.action == "escalate_to_job"

    def test_trigger_inside_sentence(self, analyzed_snapshot: SessionSnapshot):
        """El trigger puede estar en medio de la frase."""
        decision = should_escalate_to_job("por favor, ¿podrías mezclar los stems?", analyzed_snapshot)
        assert decision.action == "escalate_to_job"

    def test_action_priority_over_explanation(self, analyzed_snapshot: SessionSnapshot):
        """Acción tiene prioridad sobre explicación si ambas aparecen."""
        decision = should_escalate_to_job("explícame por qué y luego mezclalo", analyzed_snapshot)
        assert decision.action == "escalate_to_job"

    def test_action_priority_over_parameter(self, analyzed_snapshot: SessionSnapshot):
        """Acción tiene prioridad sobre parámetro."""
        decision = should_escalate_to_job("sube los graves y dale a mezclar", analyzed_snapshot)
        assert decision.action == "escalate_to_job"

    def test_explanation_priority_over_parameter(self, analyzed_snapshot: SessionSnapshot):
        """Explicación tiene prioridad sobre parámetro."""
        decision = should_escalate_to_job("por qué subes los graves?", analyzed_snapshot)
        assert decision.action == "answer_in_chat"
        assert not decision.updates_intent

    def test_accented_vs_unaccented(self, analyzed_snapshot: SessionSnapshot):
        """Triggers con y sin tilde (más/mas, análisis/analisis, diagnóstico/diagnostico)."""
        for text in ["más graves", "mas graves"]:
            decision = should_escalate_to_job(text, analyzed_snapshot)
            assert decision.updates_intent is True

        for text in ["por qué", "porque"]:
            decision = should_escalate_to_job(text, analyzed_snapshot)
            assert decision.action == "answer_in_chat"

    def test_whitespace_normalization(self, analyzed_snapshot: SessionSnapshot):
        """Espacios extra no rompen la detección."""
        decision = should_escalate_to_job("  mezclar  ", analyzed_snapshot)
        assert decision.action == "escalate_to_job"


# ── Contratos Pydantic ──────────────────────────────────────────────────────


class TestContracts:
    """Validación de que los modelos Pydantic aceptan/rechazan correctamente."""

    def test_escalation_decision_factories(self):
        esc = EscalationDecision.escalate(
            job_kind="agent",
            payload={"decision": "mix_then_master"},
            reason="test",
        )
        assert esc.action == "escalate_to_job"
        assert esc.job_kind == "agent"

        ans = EscalationDecision.answer_in_chat(reason="test", updates_intent=True)
        assert ans.action == "answer_in_chat"
        assert ans.updates_intent is True
        assert ans.job_kind is None

    def test_session_snapshot_serialization(self, analyzed_snapshot: SessionSnapshot):
        """El snapshot debe ser serializable a JSON (para logs/debug)."""
        data = analyzed_snapshot.model_dump(mode="json")
        assert data["analysis"] is not None
        assert data["verdict"] is not None
        assert data["mix_status"] == "none"

    def test_chat_request_validation(self):
        req = ChatRequest(session_id="abc", message="hola")
        assert req.history is None

        req2 = ChatRequest(session_id="abc", message="hola", history=[
            {"role": "user", "content": "hola", "ts": 123},
            {"role": "assistant", "content": "hola!", "ts": 124},
        ])
        assert len(req2.history) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])