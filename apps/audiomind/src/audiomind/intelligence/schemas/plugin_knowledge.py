"""
PluginKnowledge — Modelo de datos para plugins DSP.

Representa un módulo de procesamiento disponible en la cadena de mastering.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


class PluginParameter(BaseModel):
    """Definición de un parámetro del plugin."""
    name: str = Field(..., pattern=r"^[a-z_][a-z0-9_]*$")
    display_name: str = Field(..., min_length=1, max_length=50)
    param_type: Literal["float", "int", "enum", "bool"] = Field(...)
    unit: str | None = Field(default=None, max_length=20)
    min_value: float | int | None = Field(default=None)
    max_value: float | int | None = Field(default=None)
    default: float | int | str | bool = Field(...)
    enum_values: list[str] | None = Field(default=None)
    description: str = Field(..., min_length=10, max_length=300)
    automation_safe: bool = Field(default=True)


class SonicImpact(BaseModel):
    """Impacto sonoro medible y cualitativo."""
    qualitative: str = Field(..., min_length=20, max_length=500)
    measurable_changes: dict[str, str] = Field(default_factory=dict)


class PluginInteraction(BaseModel):
    """Interacción con otro plugin."""
    other_plugin_id: str = Field(...)
    interaction_type: Literal["before", "after", "conflict", "synergy"] = Field(...)
    description: str = Field(..., min_length=10, max_length=300)
    mitigation: str | None = Field(default=None, max_length=300)


class UsageExample(BaseModel):
    """Ejemplo de uso típico."""
    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field(..., min_length=10, max_length=200)
    settings: dict[str, Any] = Field(...)
    use_case: str = Field(..., min_length=5, max_length=100)


class PluginKnowledge(BaseModel):
    """
    Conocimiento completo de un plugin DSP.

    SOLO representa conocimiento — no instancia plugin, no procesa audio.
    """
    # Identidad
    plugin_id: str = Field(..., pattern=r"^[a-z_][a-z0-9_]*$", description="ID único: saturation|compressor|eq|limiter|stereo|dither|match_eq|ceiling_limiter")
    display_name: str = Field(..., min_length=1, max_length=50, description="Nombre para UI")
    plugin_type: Literal["saturation", "compressor", "eq", "limiter", "stereo", "dither", "match_eq", "ceiling_limiter", "other"] = Field(...)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")

    # Qué hace
    proposito: str = Field(..., min_length=10, max_length=200, description="Una frase: propósito sonoro")

    # Parámetros
    parametros: list[PluginParameter] = Field(..., min_length=1, max_length=15)

    # Impacto
    impacto_sonoro: SonicImpact = Field(...)

    # Evaluación
    ventajas: list[str] = Field(default_factory=list, max_length=10)
    desventajas: list[str] = Field(default_factory=list, max_length=10)

    # Ejemplos
    ejemplos_uso: list[UsageExample] = Field(default_factory=list, max_length=8)

    # Interacciones
    interacciones: list[PluginInteraction] = Field(default_factory=list, max_length=12)

    # Implementación
    implementation_notes: str | None = Field(default=None, max_length=1000, description="Notas para DSP Designer: Pedalboard mapping, Librosa fallback, oversample reqs, etc.")

    # Referencias
    referencias: list[str] = Field(default_factory=list, description="Links a EXP-XXX, presets que lo usan, papers")

    # Metadatos
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = Field(default="dsp_designer")
    tags: list[str] = Field(default_factory=list, max_length=15)

    @field_validator("interacciones")
    @classmethod
    def validate_interaction_types(cls, v: list[PluginInteraction]) -> list[PluginInteraction]:
        types = [i.interaction_type for i in v]
        if "conflict" in types and "synergy" in types:
            # Validar que no sea el mismo plugin en conflicto y sinergia
            conflicts = {i.other_plugin_id for i in v if i.interaction_type == "conflict"}
            synergies = {i.other_plugin_id for i in v if i.interaction_type == "synergy"}
            overlap = conflicts & synergies
            if overlap:
                raise ValueError(f"Plugin no puede ser conflict y synergy con mismo: {overlap}")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "plugin_id": "saturation",
                "display_name": "Saturación Armónica",
                "plugin_type": "saturation",
                "version": "1.0.0",
                "proposito": "Saturación armónica configurable (tube/tape/transistor) para color, compresión suave y perceived loudness",
                "parametros": [
                    {"name": "type", "display_name": "Modelo", "param_type": "enum", "unit": None, "default": "tube", "enum_values": ["tube", "tape", "transistor"], "description": "Modelo de saturación: tube=pares (calidez), tape=impares+comp, transistor=impares agresivos"},
                    {"name": "drive_db", "display_name": "Drive", "param_type": "float", "unit": "dB", "min_value": 0, "max_value": 12, "default": 3.0, "description": "Gain entrada al saturador — más drive = más armónicos y compresión"},
                    {"name": "mix", "display_name": "Mix", "param_type": "float", "unit": "%", "min_value": 0, "max_value": 1, "default": 0.5, "description": "Dry/wet blend"},
                    {"name": "tone_hz", "display_name": "Tone", "param_type": "float", "unit": "Hz", "min_value": 100, "max_value": 8000, "default": 2000, "description": "Low-pass post-saturación para evitar aliasing perceptual"},
                    {"name": "output_gain_db", "display_name": "Output Gain", "param_type": "float", "unit": "dB", "min_value": -6, "max_value": 6, "default": 0.0, "description": "Compensación gain post-mix"}
                ],
                "impacto_sonoro": {
                    "qualitative": "Tube: armónicos pares (2º, 4º) → calidez, 'glue', compresión natural. Tape: impares + compresión dependiente nivel → cohesión analógica, roll-off highs. Transistor: impares agresivos (3º, 5º) → grit, edge, perceived loudness.",
                    "measurable_changes": {"crest_factor_db": "-1 a -3 dB", "thd_percent": "+0.5% a +2%", "spectral_centroid_shift": "+5-25%", "perceived_loudness_lu": "+0.5 a +1.5 LU", "dynamic_range_db": "-1 a -2 dB"}
                },
                "ventajas": ["Musical en material dinámico", "Auto-limiting suave", "Añade perceived loudness sin limiting"],
                "desventajas": ["En material ya saturado → intermodulación fea", "Drive alto + bass-heavy → low-end buildup", "No reemplaza compresor para control intencional"],
                "ejemplos_uso": [
                    {"name": "Vocal warmth", "description": "Calidez sutil en vocal", "settings": {"type": "tube", "drive_db": 2.0, "mix": 0.25, "tone_hz": 3000}, "use_case": "Master bus, stems, tracks individuales"},
                    {"name": "Drum glue", "description": "Cohesión en bus de baterías", "settings": {"type": "tape", "drive_db": 4.0, "mix": 0.4, "tone_hz": 1500}, "use_case": "Drum bus, full mix"},
                    {"name": "Bass grit", "description": "Armónicos audibles en sub-bass", "settings": {"type": "transistor", "drive_db": 6.0, "mix": 0.2, "tone_hz": 800}, "use_case": "Bass tracks, 808s"}
                ],
                "interacciones": [
                    {"other_plugin_id": "eq", "interaction_type": "before", "description": "Limpiar resonancias/mud ANTES de colorear — saturación amplifica lo que hay", "mitigation": None},
                    {"other_plugin_id": "compressor", "interaction_type": "after", "description": "Saturación reduce picos → compresor trabaja menos/más suave", "mitigation": None},
                    {"other_plugin_id": "limiter", "interaction_type": "conflict", "description": "Saturación + limiter inmediato → intermodulación en techo", "mitigation": "Bajar drive, subir ceiling a -1dBTP, o separar en chain"},
                    {"other_plugin_id": "eq", "interaction_type": "synergy", "description": "Tube saturation + Pultec-style low boost = 'analog weight'", "mitigation": None}
                ],
                "implementation_notes": "Pedalboard: pedalboard.Saturation(drive_db=..., curve=...). Mapear type→curve enum. Librosa fallback: np.tanh(x*gain) + polynomial waveshaping. Oversample 2x mínimo para drive>6dB. Stateless (except tape wow/flutter LFO).",
                "referencias": ["EXP-001", "knowledge/presets/fuego.md", "knowledge/presets/cinta.md", "FabFilter Saturn whitepaper"]
            }
        }