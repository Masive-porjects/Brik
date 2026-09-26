"""Mix Metadata contract for inter-engine handshake (Mix → Master)."""

from pydantic import BaseModel, Field
from typing import Literal


class MixMetadata(BaseModel):
    """Contexto de mezcla exportado por Mix Engine para Master adaptativo."""
    schema_version: int = Field(default=1, ge=1, description="Versión del esquema para migraciones futuras")
    applied_spatial_width: float = Field(
        default=1.0, ge=0.5, le=3.0,
        description="Factor de ancho estéreo efectivo aplicado en el mix (1.0 = neutral)"
    )
    side_energy_ratio: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Relación RMS(Side) / RMS(Mid) en el bus final de la mezcla"
    )
    stem_lufs: dict[str, float] = Field(
        default_factory=dict,
        description="LUFS integrado por stem: {'drums': -18.2, 'bass': -14.5, 'other': -20.1, 'vocals': -16.8}"
    )
    transient_headroom_db: float = Field(
        default=3.0, ge=-10.0, le=20.0,
        description="Headroom transitorio previo al limiter (True Peak - ceiling, dBTP)"
    )
    mix_status: Literal["none", "processing", "completed", "failed"] = "none"

    model_config = {"extra": "allow"}  # Extensibilidad sin breaking changes