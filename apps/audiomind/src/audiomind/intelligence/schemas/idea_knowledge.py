"""
IdeaKnowledge — Modelo de datos para ideas de producto/ingeniería.

Inbox estructurado: problema, beneficio, costo, prioridad, trazabilidad.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class IdeaReference(BaseModel):
    """Referencia a artefacto relacionado."""
    type: Literal["issue", "pr", "experiment", "document", "competitor", "paper", "user_feedback"]
    identifier: str = Field(..., description="Ej: 'EXP-003', 'PR #342', 'issue #127', 'bandlab.com/songstarter'")
    description: str | None = Field(default=None, max_length=200)


class IdeaKnowledge(BaseModel):
    """
    Idea capturada, evaluada y trazada.

    SOLO conocimiento — no ejecuta, no implementa.
    """
    # Identidad
    idea_id: str = Field(..., pattern=r"^IDEA-\d{3}$", description="IDEA-001, IDEA-002...")
    title: str = Field(..., min_length=5, max_length=120, description="Título descriptivo único")
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")

    # Qué es
    description: str = Field(..., min_length=20, max_length=500, description="2-3 frases: qué es")

    # Por qué
    problem: str = Field(..., min_length=10, max_length=500, description="Dolor que resuelve (user quote si existe)")
    benefit: str = Field(..., min_length=10, max_length=500, description="Valor para usuario y/o negocio (métrica si posible)")

    # Cuánto cuesta
    cost_estimate_dev_weeks: float = Field(..., ge=0.1, description="Semanas dev estimadas")
    cost_infra_monthly_usd: float | None = Field(default=None, ge=0.0, description="Costo infra mensual si aplica")
    maintenance_burden: Literal["low", "medium", "high"] = Field(default="medium")

    # Qué tan difícil
    complexity: Literal["low", "medium", "high"] = Field(...)
    technical_risks: list[str] = Field(default_factory=list, max_length=8, description="Riesgos técnicos principales")

    # Prioridad
    priority: Literal["P0", "P1", "P2", "P3", "P4"] = Field(
        ...,
        description="P0=crítico, P1=alto, P2=medio, P3=bajo, P4=nice-to-have"
    )
    priority_rationale: str = Field(..., min_length=10, max_length=300, description="Por qué esta prioridad")

    # Estado
    status: Literal[
        "new", "under_review", "approved", "in_roadmap",
        "in_development", "done", "discarded", "merged"
    ] = Field(default="new")
    status_reason: str | None = Field(default=None, max_length=300)

    # Trazabilidad
    inspiration: str = Field(..., min_length=10, max_length=300, description="Fuente: feedback, competidor, paper, hackathon, agente")
    references: list[IdeaReference] = Field(default_factory=list, max_length=10)

    # Contexto
    notes: str | None = Field(default=None, max_length=1000, description="Dependencias, open questions, blockers")
    dependencies: list[str] = Field(default_factory=list, max_length=8, description="IDs de ideas/experimentos requeridos")
    blocks: list[str] = Field(default_factory=list, max_length=8, description="IDs que esta idea desbloquea")

    # Metadatos
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = Field(default="innovation_agent")
    assignee: str | None = Field(default=None, description="Owner si aprobada")
    tags: list[str] = Field(default_factory=list, max_length=15)

    class Config:
        json_schema_extra = {
            "example": {
                "idea_id": "IDEA-001",
                "title": "Auto-selección de preset por género detectado",
                "version": "1.0.0",
                "description": "Tras análisis de audio, sistema detecta género y características técnicas, y sugiere/pre-selecciona preset óptimo basado en género+características track.",
                "problem": "\"No sé qué preset elegir — son 8 y suenan parecido\" (78% usuarios en onboarding survey Q3)",
                "benefit": "Reduce decision paralysis, mejora first-track success rate target +25%, aumenta activation. Diferenciador vs LANDR/BandLab (ellos no explican por qué).",
                "cost_estimate_dev_weeks": 3.0,
                "cost_infra_monthly_usd": 15.0,
                "maintenance_burden": "medium",
                "complexity": "medium",
                "technical_risks": ["Dataset etiquetado insuficiente para genre classifier", "Model serving latency <100ms", "Fallback heurístico si confidence <0.6"],
                "priority": "P1",
                "priority_rationale": "High impact (activation), differentiated vs competitors, feasible with current ML strategy (EXP-003 correlation data)",
                "status": "under_review",
                "status_reason": "Waiting for EXP-003 genre-preset correlation results to validate approach",
                "inspiration": "BandLab SongStarter genre detection + user interviews Q3",
                "references": [
                    {"type": "experiment", "identifier": "EXP-003", "description": "Genre-preset correlation analysis"},
                    {"type": "document", "identifier": "AUDIOMIND_AI_ML_STRATEGY.md#modelo-2", "description": "Preset recommender XGBoost architecture"},
                    {"type": "competitor", "identifier": "bandlab.com", "description": "SongStarter genre detection"},
                    {"type": "user_feedback", "identifier": "onboarding_survey_q3", "description": "78% preset confusion"}
                ],
                "notes": "Depende de EXP-003 confirming genre→preset correlation. Fallback: reglas heurísticas (crest factor, spectral centroid) si ML no ready. Integración con GenreGuide UI component.",
                "dependencies": ["EXP-003"],
                "blocks": ["IDEA-002_stem_remix_export", "IDEA-004_reference_match_eq"],
                "tags": ["ml", "activation", "differentiation", "onboarding", "genre-classifier", "preset-recommender"]
            }
        }