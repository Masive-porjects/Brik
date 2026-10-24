"""
PresetKnowledge — Modelo de datos para presets de mastering.

Representa el conocimiento canónico de un preset: qué hace, parámetros,
métricas esperadas, géneros ideales, y trazabilidad a experimentos.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class PluginRef(BaseModel):
    """Referencia a un plugin en la cadena con sus parámetros clave."""
    plugin_id: str = Field(..., description="ID canónico (ej: 'saturation', 'compressor', 'eq')")
    plugin_type: str = Field(..., description="Tipo: saturation|compressor|eq|limiter|stereo|dither|match_eq")
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Parámetros clave para este preset (subset de schema del plugin)"
    )
    order: int = Field(..., ge=0, description="Orden en la cadena de señal (0 = primero)")
    enabled: bool = Field(default=True, description="Si este plugin está activo en este preset")


class PresetMetrics(BaseModel):
    """Métricas objetivo esperadas post-procesamiento con este preset."""
    lufs_integrated_target: float = Field(..., description="LUFS integrated target (ej: -14.0)")
    lufs_tolerance_db: float = Field(default=0.5, ge=0.1, le=2.0, description="Tolerancia ±dB")
    true_peak_max_db: float = Field(default=-1.0, le=-0.1, description="True peak ceiling (ej: -1.0 dBTP)")
    dynamic_range_target_min: float = Field(default=6.0, ge=2.0, description="Dynamic range mínimo EBU (dB)")
    dynamic_range_target_max: float = Field(default=12.0, ge=6.0, description="Dynamic range máximo EBU (dB)")
    crest_factor_out_min: float = Field(default=8.0, ge=3.0, description="Crest factor salida mínimo (dB)")
    crest_factor_out_max: float = Field(default=12.0, ge=8.0, description="Crest factor salida máximo (dB)")
    spectral_centroid_shift_pct: float = Field(default=0.0, description="Shift espectral esperado (%)")


class PresetGenreCompatibility(BaseModel):
    """Compatibilidad de preset con un género."""
    genre_id: str = Field(..., description="ID del género (ej: 'trap', 'hip-hop', 'house')")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confianza 0-1")
    role: Literal["primary", "secondary", "fallback"] = Field(
        default="secondary",
        description="Rol: primary=recomendado principal, secondary=alternativa, fallback=seguro"
    )
    notes: str | None = Field(default=None, description="Cuándo preferir esta combinación")


class PresetKnowledge(BaseModel):
    """
    Conocimiento completo de un preset de mastering.

    Este modelo SOLO representa conocimiento — no conecta a BD,
    no ejecuta DSP, no tiene lógica de procesamiento.
    """
    # Identidad
    preset_id: str = Field(
        ...,
        pattern=r"^[a-z]+$",
        description="ID canónico lowercase: universal|fuego|claridad|cinta|natural|espacial|cinematico|empuje"
    )
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$", description="Semver del conocimiento")

    # Qué hace
    nombre: str = Field(..., min_length=1, max_length=50, description="Nombre display (ej: 'Brutal')")
    objetivo: str = Field(..., min_length=10, max_length=200, description="Una frase: qué logra")
    descripcion: str = Field(..., min_length=20, max_length=1000, description="Explicación para usuario final")

    # Cuándo usar / no usar
    problema_que_resuelve: str = Field(..., min_length=10, max_length=500)
    cuando_usar: str = Field(..., min_length=10, max_length=500, description="Condiciones de entrada")
    cuando_no_usar: str = Field(..., min_length=10, max_length=500, description="Contraindicaciones explícitas")

    # Cadena DSP
    plugins: list[PluginRef] = Field(
        ...,
        min_length=1,
        max_length=10,
        description="Cadena de plugins ordenada con parámetros por preset"
    )

    # Evaluación
    ventajas: list[str] = Field(default_factory=list, max_length=10)
    limitaciones: list[str] = Field(default_factory=list, max_length=10)
    metricas_esperadas: PresetMetrics = Field(...)

    # Géneros
    generos_ideales: list[PresetGenreCompatibility] = Field(
        default_factory=list,
        max_length=15,
        description="Géneros donde este preset destaca"
    )

    # Evolución
    futuras_mejoras: list[str] = Field(default_factory=list, max_length=10)
    referencias: list[str] = Field(
        default_factory=list,
        description="Links a experimentos (EXP-XXX), ADRs (DEC-XXX), papers, presets comerciales"
    )

    # Metadatos
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = Field(default="chief_audio_engineer")
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("plugins")
    @classmethod
    def validate_plugin_order(cls, v: list[PluginRef]) -> list[PluginRef]:
        """Validar que orders son únicos y secuenciales desde 0."""
        orders = [p.order for p in v]
        if len(orders) != len(set(orders)):
            raise ValueError("Plugin orders deben ser únicos")
        if sorted(orders) != list(range(len(v))):
            raise ValueError("Plugin orders deben ser 0, 1, 2... sin gaps")
        return sorted(v, key=lambda p: p.order)

    @field_validator("generos_ideales")
    @classmethod
    def validate_one_primary(cls, v: list[PresetGenreCompatibility]) -> list[PresetGenreCompatibility]:
        """Debe haber exactamente un primary."""
        primaries = [g for g in v if g.role == "primary"]
        if len(primaries) != 1:
            raise ValueError("Debe haber exactamente un género 'primary'")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "preset_id": "fuego",
                "version": "1.0.0",
                "nombre": "Brutal",
                "objetivo": "Punch y peso en graves para trap/hip-hop",
                "descripcion": "Diseñado para música urbana donde kick y 808 necesitan corte y presencia...",
                "problema_que_resuelve": "Kick y 808 se pierden al normalizar a -14 LUFS streaming",
                "cuando_usar": "Trap, Hip Hop, Drill, Reggaeton — crest factor >12dB, sub-bass energy alta",
                "cuando_no_usar": "Jazz, Classical, Acoustic, Ambient — destruye micro-dinámica",
                "plugins": [
                    {"plugin_id": "saturation", "plugin_type": "saturation", "parameters": {"type": "tube", "drive_db": 3.0, "mix": 0.5}, "order": 0, "enabled": True},
                    {"plugin_id": "compressor", "plugin_type": "compressor", "parameters": {"type": "fet", "ratio": 4.0, "attack_ms": 0.5}, "order": 1, "enabled": True},
                    {"plugin_id": "eq", "plugin_type": "eq", "parameters": {"low_shelf_db": 2.0, "high_shelf_db": 1.5}, "order": 2, "enabled": True},
                    {"plugin_id": "match_eq", "plugin_type": "match_eq", "parameters": {"target_curve": "trap"}, "order": 3, "enabled": True},
                    {"plugin_id": "limiter", "plugin_type": "limiter", "parameters": {"ceiling_db": -1.0, "oversample": 4}, "order": 4, "enabled": True},
                    {"plugin_id": "dither", "plugin_type": "dither", "parameters": {"type": "lipshitz_2nd"}, "order": 5, "enabled": True}
                ],
                "ventajas": ["Añade peso a 808 sin distorsión", "True peak safe para streaming"],
                "limitaciones": ["Low-shelf artificial si track carece de low-end", "No compensa problemas de fase"],
                "metricas_esperadas": {
                    "lufs_integrated_target": -14.0,
                    "true_peak_max_db": -1.0,
                    "dynamic_range_target_min": 6.0,
                    "dynamic_range_target_max": 8.0,
                    "crest_factor_out_min": 8.0,
                    "crest_factor_out_max": 10.0
                },
                "generos_ideales": [
                    {"genre_id": "trap", "confidence": 0.93, "role": "primary"},
                    {"genre_id": "hip-hop", "confidence": 0.85, "role": "secondary"},
                    {"genre_id": "drill", "confidence": 0.75, "role": "secondary"},
                    {"genre_id": "reggaeton", "confidence": 0.70, "role": "secondary"}
                ],
                "futuras_mejoras": ["Adaptive saturation based on 808 fundamental freq"],
                "referencias": ["EXP-001", "EXP-003", "DEC-001"]
            }
        }