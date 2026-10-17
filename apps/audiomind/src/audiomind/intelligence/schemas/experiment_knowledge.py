"""
ExperimentKnowledge — Modelo para experimentos I+D.

Registro estructurado, reproducible y auditable de experimentos DSP, ML, UX y producto.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class ExperimentDesign(BaseModel):
    """Diseño experimental."""
    groups: list[dict[str, Any]] = Field(..., min_length=2, max_length=5, description="Control, tratamiento, etc.")
    sample_size_per_group: int = Field(..., ge=10, description="N por grupo")
    total_samples: int = Field(..., ge=20, description="Total tracks/usuarios")
    stratification: list[str] = Field(default_factory=list, description="Vars para estratificar: genre, crest_bin, lufs_bin")
    randomization_method: str = Field(default="hash(track_id + exp_id) % n_groups")
    blinding: Literal["single", "double", "analyst_only", "none"] = Field(default="analyst_only")
    primary_metric: str = Field(..., description="Métrica primaria: ej '% tracks DR<4'")
    secondary_metrics: list[str] = Field(default_factory=list, max_length=10)
    success_criteria: dict[str, Any] = Field(..., description="Criterios de éxito cuantitativos")


class ExperimentChanges(BaseModel):
    """Cambios exactos realizados."""
    files_modified: list[dict[str, Any]] = Field(..., min_length=1, description="[{file, lines, change, commit_pr}]")
    config_changes: list[dict[str, Any]] = Field(default_factory=list)
    code_changes_summary: str = Field(..., min_length=20, max_length=500)


class TechnicalMetrics(BaseModel):
    """Métricas técnicas del experimento."""
    cpu_overhead_pct: float = Field(default=0.0, ge=0.0)
    latency_added_ms: float = Field(default=0.0, ge=0.0)
    memory_overhead_mb: float = Field(default=0.0, ge=0.0)
    true_peak_violations: int = Field(default=0, ge=0)
    dsp_chain_errors: int = Field(default=0, ge=0)


class ExperimentResults(BaseModel):
    """Resultados cuantitativos."""
    primary_metric: dict[str, Any] = Field(..., description="{control: val, treatment: val, delta_pct, p_value, significant}")
    secondary_metrics: list[dict[str, Any]] = Field(default_factory=list)
    subgroup_analysis: list[dict[str, Any]] = Field(default_factory=list, description="Análisis por sub-grupos")
    technical: TechnicalMetrics = Field(default_factory=TechnicalMetrics)
    qualitative_observations: list[str] = Field(default_factory=list, max_length=20)


class ExperimentKnowledge(BaseModel):
    """
    Conocimiento completo de un experimento I+D.

    ID: EXP-XXX (secuencial global, único, inmutable)
    Tipo: dsp | ml | ux | product
    """
    # Identidad
    experiment_id: str = Field(..., pattern=r"^EXP-\d{3}$", description="EXP-001, EXP-002...")
    experiment_type: Literal["dsp", "ml", "ux", "product"] = Field(...)
    title: str = Field(..., min_length=10, max_length=100)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")

    # Hipótesis y objetivo
    hypothesis: str = Field(..., min_length=20, max_length=500, description="Si X → Y porque Z")
    objective: str = Field(..., min_length=10, max_length=300, description="Métrica primaria a mover")

    # Diseño
    design: ExperimentDesign = Field(...)

    # Cambios
    changes: ExperimentChanges = Field(...)

    # Resultados
    results: ExperimentResults = Field(...)

    # Problemas
    problems_found: list[str] = Field(default_factory=list, max_length=15, description="Bugs, edge cases, limitaciones, sorpresas")

    # Conclusiones
    conclusion: Literal["confirmed", "rejected", "partial", "inconclusive"] = Field(...)
    conclusion_reasoning: str = Field(..., min_length=20, max_length=1000)

    # Próximos pasos
    next_steps: list[str] = Field(default_factory=list, max_length=10)
    follow_up_experiment_id: str | None = Field(default=None, pattern=r"^EXP-\d{3}$")

    # Artefactos
    artifacts: dict[str, str] = Field(
        default_factory=dict,
        description="{pr_url, dataset_path, model_path, audio_samples_dir, analysis_notebook, dashboard_url}"
    )

    # Metadatos
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = Field(default="research_agent")
    status: Literal["design", "running", "analyzing", "completed", "archived"] = Field(default="design")
    tags: list[str] = Field(default_factory=list, max_length=15)

    @field_validator("follow_up_experiment_id")
    @classmethod
    def validate_followup(cls, v: str | None) -> str | None:
        if v and not v.startswith("EXP-"):
            raise ValueError("Follow-up experiment ID must be EXP-XXX format")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "experiment_id": "EXP-003",
                "experiment_type": "dsp",
                "title": "Ceiling dinámico basado en crest factor vs ceiling fijo -1dBTP",
                "version": "1.1.0",
                "hypothesis": "Si usamos ceiling adaptativo (-2dBTP para crest<10, -1dBTP para crest>15), reducimos over-limiting en tracks ya masterizados sin penalizar dinámica en mixes crudos.",
                "objective": "Reducir % tracks con DR<4 post-mastering de 22% a <5% manteniendo loudness target ±0.5 LUFS.",
                "design": {
                    "groups": [
                        {"name": "control", "treatment": "ceiling_fijo_-1dBTP", "n": 250},
                        {"name": "treatment", "treatment": "ceiling_dinamico_histeresis", "n": 250}
                    ],
                    "sample_size_per_group": 250,
                    "total_samples": 500,
                    "stratification": ["genre", "crest_factor_bin", "lufs_in_bin"],
                    "randomization_method": "hash(track_id + exp_id) % 2",
                    "blinding": "analyst_only",
                    "primary_metric": "pct_tracks_DR_lt_4",
                    "secondary_metrics": ["lufs_error_db", "dr_mean", "cpu_overhead_pct"],
                    "success_criteria": {"pct_DR_lt_4": "<5%", "lufs_error": "<0.5dB", "cpu_overhead": "<5%"}
                },
                "changes": {
                    "files_modified": [
                        {"file": "processing/engine.py", "lines": "234-241", "change": "Nueva función calculate_ceiling(crest_factor) con histeresis ±1dB", "commit_pr": "PR #342"},
                        {"file": "processing/engine.py", "line": 594, "change": "Llamada a calculate_ceiling en lugar de constante", "commit_pr": "PR #342"},
                        {"file": "tests/test_ceiling.py", "lines": "1-80", "change": "Tests unitarios casos crest 8-18", "commit_pr": "PR #342"}
                    ],
                    "config_changes": [],
                    "code_changes_summary": "Ceiling fijo -1dBTP → dinámico basado en crest factor entrada. Histeresis ±1dB evita oscilación en zona gris 10-15dB."
                },
                "results": {
                    "primary_metric": {"control": 0.22, "treatment": 0.04, "delta_pct": -81.8, "p_value": 0.0001, "significant": True},
                    "secondary_metrics": [
                        {"metric": "lufs_error_db", "control": 0.12, "treatment": 0.08, "delta": -33, "p": 0.02},
                        {"metric": "dr_mean", "control": 5.2, "treatment": 6.8, "delta": 31, "p": 0.001}
                    ],
                    "subgroup_analysis": [
                        {"subgroup": "already_mastered_crest_lt_10", "control_dr": 3.1, "treatment_dr": 5.4, "delta": 74, "n": 89},
                        {"subgroup": "gray_zone_crest_10_15", "control_dr": 4.8, "treatment_dr": 5.9, "delta": 23, "n": 156},
                        {"subgroup": "raw_crest_gt_15", "control_dr": 6.8, "treatment_dr": 7.1, "delta": 4, "n": 255}
                    ],
                    "technical": {"cpu_overhead_pct": 2.0, "latency_added_ms": 0.0, "memory_overhead_mb": 1.0, "true_peak_violations": 0},
                    "qualitative_observations": ["Zona gris 10-15dB mostró inconsistencia inicial → histeresis fix aplicada"]
                },
                "problems_found": [
                    "Tracks con crest 9.5dB (borde) oscilaban control/tratamiento entre renders → fix: redondear crest a int antes de decisión",
                    "Windows CI: test_hysteresis flaky por float precision → tolerancia 1e-6 añadida",
                    "Noise tracks (crest ~3dB) → ceiling -2dBTP correcto pero LUFS -15.2 (debajo target) → known behavior documentado"
                ],
                "conclusion": "confirmed",
                "conclusion_reasoning": "Ceiling dinámico + histeresis reduce over-limiting drásticamente (22%→4% DR<4) sin penalizar loudness ni tracks crudos. Overhead CPU/latencia negligible. Hipótesis CONFIRMADA.",
                "next_steps": ["Deploy a staging (PR #342 merged)", "Monitor 1k tracks reales en staging", "Si metrics estables → production v1.3.0", "EXP-004: Test ceiling con ML already-mastered detector"],
                "follow_up_experiment_id": "EXP-004",
                "artifacts": {
                    "pr_url": "https://github.com/brikpaul569-cmd/BrikSound/pull/342",
                    "dataset_path": "experiments/data/exp003/",
                    "audio_samples": "outputs/exp003/",
                    "analysis_notebook": "experiments/notebooks/exp003_analysis.ipynb",
                    "dashboard": "grafana/audiomind/exp003"
                },
                "created_by": "research_agent",
                "status": "completed",
                "tags": ["dsp", "ceiling", "limiter", "crest-factor", "over-limiting", "validated"]
            }
        }