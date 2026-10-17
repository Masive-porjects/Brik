"""Mix Metadata contract for inter-engine handshake (Mix → Master)."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class MixMetadata(BaseModel):
    """Contexto de mezcla exportado por Mix Engine para Master adaptativo.

    ``schema_version`` is ``1`` for the original five-field payload and ``2``
    when ``texture_recipe`` is present: the P4 mix-side recipe (spec
    ``odd/tasks/mastering-cohesion.md`` S1) measured on the character buses.
    ``texture_recipe`` is ``None`` on every pre-P4 flow, and the neutral payload
    stays textually identical because a ``None`` field is excluded from the
    serialised dict (``model_dump(exclude_none=True)`` at the one call site).
    """

    schema_version: int = Field(
        default=1, ge=1, description="Versión del esquema para migraciones futuras"
    )
    applied_spatial_width: float = Field(
        default=1.0,
        ge=0.5,
        le=3.0,
        description=(
            "Factor de ancho estéreo efectivo aplicado en el mix (1.0 = neutral)"
        ),
    )
    side_energy_ratio: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Relación RMS(Side) / RMS(Mid) en el bus final de la mezcla",
    )
    stem_lufs: dict[str, float] = Field(
        default_factory=dict,
        description=(
            "LUFS integrado por stem: {'drums': -18.2, 'bass': -14.5, "
            "'other': -20.1, 'vocals': -16.8}"
        ),
    )
    transient_headroom_db: float = Field(
        default=3.0,
        ge=-10.0,
        le=20.0,
        description=(
            "Headroom transitorio previo al limiter (True Peak - ceiling, dBTP)"
        ),
    )
    mix_status: Literal["none", "processing", "completed", "failed"] = "none"
    texture_recipe: dict[str, Any] | None = Field(
        default=None,
        description=(
            "P4 mix-side texture recipe (schema v2): the MEASURED effect of the "
            "character stage on the mix bus (S1). None on every pre-P4 flow."
        ),
    )

    model_config = {"extra": "allow"}  # Extensibilidad sin breaking changes
