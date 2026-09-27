"""
GenreKnowledge — Modelo de datos para perfiles de género musical.

Define características técnicas medibles de un género para guiar:
- Detección automática (Genre Classifier ML)
- Recomendación de preset (Preset Recommender)
- Diseño de cadena DSP género-específica
- Match EQ target curves
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from pydantic import BaseModel, Field, field_validator


class BPMRange(BaseModel):
    """Rango de BPM típico del género."""
    min: int = Field(..., ge=40, le=300)
    max: int = Field(..., ge=40, le=300)
    typical: int = Field(..., ge=40, le=300)
    notes: str | None = Field(default=None, max_length=100)


class EnergyProfile(BaseModel):
    """Perfil energético del género."""
    level: int = Field(..., ge=1, le=10, description="Escala 1-10")
    description: str = Field(..., min_length=10, max_length=200)
    spectral_density: Literal["sparse", "moderate", "dense", "very_dense"] = Field(...)
    transient_character: Literal["soft", "moderate", "sharp", "very_sharp"] = Field(...)


class TonalBalance(BaseModel):
    """Balance tonal característico."""
    sub_bass_30_80hz: Literal["dominant", "present", "moderate", "recessed", "absent"] = Field(...)
    bass_80_250hz: Literal["boosted", "present", "moderate", "cut", "scooped"] = Field(...)
    low_mid_250_500hz: Literal["boosted", "present", "moderate", "cut", "scooped"] = Field(...)
    mid_500_2000hz: Literal["boosted", "present", "moderate", "cut", "scooped"] = Field(...)
    upper_mid_2_5khz: Literal["boosted", "present", "moderate", "cut", "scooped"] = Field(...)
    presence_5_8khz: Literal["boosted", "present", "moderate", "cut", "scooped"] = Field(...)
    air_8khz_plus: Literal["bright", "present", "moderate", "dark", "rolled_off"] = Field(...)
    spectral_tilt_db_per_oct: float = Field(..., description="Pendiente espectral típica dB/oct (ej: -3.0 pink noise)")
    notes: str | None = Field(default=None, max_length=300)


class DynamicsProfile(BaseModel):
    """Perfil dinámico típico en masters comerciales."""
    crest_factor_in_db: tuple[float, float] = Field(..., description="(min, max) crest factor entrada típica")
    crest_factor_out_db: tuple[float, float] = Field(..., description="(min, max) crest factor target salida")
    dynamic_range_ebu_db: tuple[float, float] = Field(..., description="(min, max) Dynamic Range EBU target")
    lufs_integrated_commercial: tuple[float, float] = Field(..., description="(min, max) LUFS integrated releases comerciales")
    true_peak_commercial_db: tuple[float, float] = Field(..., description="(min, max) True Peak releases comerciales")
    compression_style: Literal["heavy", "moderate", "light", "transparent"] = Field(...)


class DSPRecommendation(BaseModel):
    """Recomendación DSP específica para este género."""
    stage: Literal[
        "safety", "corrective_eq", "character", "match_eq", "limiting", "dither", "stereo"
    ] = Field(..., description="Etapa en pipeline canónico")
    plugin_type: str = Field(..., description="Tipo de plugin: saturation, compressor, eq, limiter, etc.")
    rationale: str = Field(..., min_length=10, max_length=300, description="Por qué esta recomendación")
    typical_settings: dict[str, Any] = Field(default_factory=dict, description="Settings típicos")
    priority: Literal["critical", "high", "medium", "low", "optional"] = Field(default="high")


class PresetCompatibility(BaseModel):
    """Compatibilidad con presets de AudioMind."""
    preset_id: str = Field(..., pattern=r"^[a-z]+$")
    confidence: float = Field(..., ge=0.0, le=1.0)
    role: Literal["primary", "secondary", "fallback"] = Field(...)
    when_to_prefer: str | None = Field(default=None, max_length=200)


class DetectionFeatures(BaseModel):
    """Features clave para detección automática (ML/heurística)."""
    spectral_centroid_range: tuple[float, float] = Field(..., description="(min, max) Hz")
    spectral_rolloff_95_range: tuple[float, float] = Field(..., description="(min, max) Hz")
    mfcc_1_mean_range: tuple[float, float] = Field(..., description="(min, max) — bass energy")
    zero_crossing_rate_range: tuple[float, float] = Field(..., description="(min, max)")
    tempo_bpm_range: tuple[int, int] = Field(..., description="(min, max)")
    crest_factor_range: tuple[float, float] = Field(..., description="(min, max) dB")
    sub_bass_energy_percentile: float = Field(..., ge=0.0, le=1.0, description="Percentil energía 30-80Hz vs all genres")
    spectral_flatness_range: tuple[float, float] = Field(..., description="(min, max)")
    key_features: list[str] = Field(default_factory=list, description="Features más discriminativas")


class ReferenceTrack(BaseModel):
    """Track de referencia calibrado."""
    track_id: str = Field(..., pattern=r"^[a-z0-9_-]+$")
    artist_type: str = Field(..., max_length=100, description="Ej: 'Metro Boomin type', 'Travis Scott type'")
    lufs_integrated: float = Field(..., ge=-20, le=0)
    true_peak_db: float = Field(..., ge=-3, le=0)
    genre: str = Field(..., max_length=50)
    notes: str | None = Field(default=None, max_length=200)


class SubgenreVariant(BaseModel):
    """Variante/subgénero con ajustes."""
    name: str = Field(..., max_length=50)
    key_difference: str = Field(..., min_length=10, max_length=200)
    preset_adjust: str = Field(..., min_length=10, max_length=200, description="Cómo ajustar preset base")
    bpm_range: tuple[int, int] | None = Field(default=None)


class GenreKnowledge(BaseModel):
    """
    Perfil técnico completo de un género musical.

    SOLO conocimiento — sin audio, sin ML, sin procesamiento.
    """
    # Identidad
    genre_id: str = Field(..., pattern=r"^[a-z-][a-z0-9-]*$", description="ID único: trap, hip-hop, deep-house, ambient-drone")
    display_name: str = Field(..., min_length=1, max_length=50, description="Nombre legible: 'Trap', 'Deep House'")
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")

    # Caracterización
    caracteristicas: str = Field(..., min_length=20, max_length=1000, description="Descripción cualitativa del sonido")
    rango_bpm: BPMRange = Field(...)
    energia: EnergyProfile = Field(...)
    balance_tonal: TonalBalance = Field(...)
    dinamica: DynamicsProfile = Field(...)

    # Loudness comercial
    loudness_promedio_lufs: float = Field(..., ge=-20, le=0, description="LUFS integrated típico releases comerciales")
    true_peak_promedio_db: float = Field(..., ge=-3, le=0, description="True Peak típico releases comerciales")

    # Recomendaciones DSP
    recomendaciones_dsp: list[DSPRecommendation] = Field(..., min_length=1, max_length=15)

    # Presets
    presets_compatibles: list[PresetCompatibility] = Field(..., min_length=1, max_length=8)

    # Match EQ
    target_curve_ref: str = Field(..., description="Path a knowledge/mastering/target_curves/<genre>_target_curve.md")

    # Referencias
    reference_tracks: list[ReferenceTrack] = Field(default_factory=list, max_length=10)

    # Detección
    detection_features: DetectionFeatures = Field(...)

    # Variantes
    subgenres_variants: list[SubgenreVariant] = Field(default_factory=list, max_length=10)

    # Edge cases
    edge_cases: dict[str, str] = Field(
        default_factory=dict,
        description="Situaciones especiales: {'melodic_trap': 'menos saturation, más claridad vocal'}"
    )

    # Metadatos
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: str = Field(default="chief_audio_engineer")
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("presets_compatibles")
    @classmethod
    def validate_one_primary_preset(cls, v: list[PresetCompatibility]) -> list[PresetCompatibility]:
        primaries = [p for p in v if p.role == "primary"]
        if len(primaries) != 1:
            raise ValueError("Debe haber exactamente un preset 'primary'")
        return v

    @field_validator("recomendaciones_dsp")
    @classmethod
    def validate_critical_stages(cls, v: list[DSPRecommendation]) -> list[DSPRecommendation]:
        stages = [r.stage for r in v]
        required = ["safety", "limiting", "dither"]
        for req in required:
            if req not in stages:
                raise ValueError(f"Etapa '{req}' requerida en recomendaciones DSP")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "genre_id": "trap",
                "display_name": "Trap",
                "version": "1.0.0",
                "caracteristicas": "Kick/808 fused, sub-bass 30-60Hz sustain, rolling hi-hats 1/32-1/64, snare/clap on 3, vocal ad-libs, half-time feel",
                "rango_bpm": {"min": 130, "max": 150, "typical": 140, "notes": "Half-time feel = 65-75 BPM percusivo"},
                "energia": {"level": 9, "description": "Alta densidad espectral, transientes agresivos, sustain largo en 808", "spectral_density": "very_dense", "transient_character": "very_sharp"},
                "balance_tonal": {"sub_bass_30_80hz": "dominant", "bass_80_250hz": "boosted", "low_mid_250_500hz": "scooped", "mid_500_2000hz": "moderate", "upper_mid_2_5khz": "boosted", "presence_5_8khz": "present", "air_8khz_plus": "bright", "spectral_tilt_db_per_oct": -3.0, "notes": "Bass boost +6-10dB vs mid, scooped 200-500Hz para espacio 808"},
                "dinamica": {"crest_factor_in_db": [12.0, 18.0], "crest_factor_out_db": [8.0, 10.0], "dynamic_range_ebu_db": [5.0, 7.0], "lufs_integrated_commercial": [-8.0, -6.0], "true_peak_commercial_db": [-1.0, -0.3], "compression_style": "heavy"},
                "loudness_promedio_lufs": -7.0,
                "true_peak_promedio_db": -0.5,
                "recomendaciones_dsp": [
                    {"stage": "character", "plugin_type": "saturation", "rationale": "Armónicos 2º-6º a 808 para audibilidad en móvil", "typical_settings": {"type": "tube", "drive_db": 3.0, "mix": 0.5}, "priority": "critical"},
                    {"stage": "character", "plugin_type": "compressor", "rationale": "FET fast attack controla transiente kick/808 sin matar punch", "typical_settings": {"type": "fet", "ratio": 4.0, "attack_ms": 0.5}, "priority": "critical"},
                    {"stage": "corrective_eq", "plugin_type": "eq", "rationale": "HP 30Hz, low-shelf +2dB@50Hz, dip 250Hz, high-shelf +1.5dB@10kHz", "typical_settings": {"hp_hz": 30, "low_shelf_db": 2.0, "dip_250hz_db": -2.0, "high_shelf_db": 1.5}, "priority": "high"},
                    {"stage": "match_eq", "plugin_type": "match_eq", "rationale": "Curva objetivo: pink noise -3dB/oct + bass shelf +6dB 30-80Hz + presence +2dB 3-5kHz", "typical_settings": {"target_curve": "trap"}, "priority": "critical"},
                    {"stage": "limiting", "plugin_type": "limiter", "rationale": "True peak -1dBTP obligatorio, ceiling dinámico si ya comprimido", "typical_settings": {"ceiling_db": -1.0, "oversample": 4, "dynamic_ceiling": True}, "priority": "critical"},
                    {"stage": "dither", "plugin_type": "dither", "rationale": "Lipshitz 2nd order para export 16-bit", "typical_settings": {"type": "lipshitz_2nd"}, "priority": "critical"},
                    {"stage": "safety", "plugin_type": "ceiling_limiter", "rationale": "Ceiling dinámico: crest<10dB → -2dBTP", "typical_settings": {}, "priority": "high"}
                ],
                "presets_compatibles": [
                    {"preset_id": "fuego", "confidence": 0.93, "role": "primary", "when_to_prefer": "Trap estándar, 808 sustain heavy"},
                    {"preset_id": "empuje", "confidence": 0.70, "role": "secondary", "when_to_prefer": "Drill, trap agresivo, más loudness"},
                    {"preset_id": "claridad", "confidence": 0.35, "role": "fallback", "when_to_prefer": "Trap melódico, vocal lead"}
                ],
                "target_curve_ref": "knowledge/mastering/target_curves/trap_target_curve.md",
                "reference_tracks": [
                    {"track_id": "trap_ref_01", "artist_type": "Metro Boomin type", "lufs_integrated": -7.2, "true_peak_db": -0.3, "genre": "Trap", "notes": "808 sustain heavy"},
                    {"track_id": "trap_ref_02", "artist_type": "Travis Scott type", "lufs_integrated": -6.8, "true_peak_db": -0.1, "genre": "Trap", "notes": "Vocal loud, kick clicky"}
                ],
                "detection_features": {
                    "spectral_centroid_range": [2500.0, 3500.0],
                    "spectral_rolloff_95_range": [6000.0, 8000.0],
                    "mfcc_1_mean_range": [-500.0, -200.0],
                    "zero_crossing_rate_range": [0.08, 0.15],
                    "tempo_bpm_range": [130, 150],
                    "crest_factor_range": [12.0, 18.0],
                    "sub_bass_energy_percentile": 0.9,
                    "spectral_flatness_range": [0.05, 0.15],
                    "key_features": ["sub_bass_energy", "mfcc_1", "tempo", "crest_factor", "spectral_centroid"]
                },
                "subgenres_variants": [
                    {"name": "Drill (UK)", "key_difference": "Slide 808, darker, 140-145 BPM", "preset_adjust": "fuego + más low-shelf, menos high-shelf", "bpm_range": [140, 145]},
                    {"name": "Melodic Trap", "key_difference": "Más melodía, vocal processed, 130-140", "preset_adjust": "fuego o claridad si vocal lead", "bpm_range": [130, 140]},
                    {"name": "Trap Latino", "key_difference": "Dembow influence, 130-140, español", "preset_adjust": "fuego + empuje blend", "bpm_range": [130, 140]}
                ],
                "edge_cases": {"melodic_trap": "menos saturation, más claridad vocal", "cloud_rap": "más dinámica, menos limiting → natural/cinta"}
            }
        }