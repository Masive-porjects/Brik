"""Intent-based mastering profile — semantic high-level goals.

The 9 axes describe WHAT the user wants the master to sound like, not the
DSP knobs that achieve it. The mapper in ``audiomind.processing.mapper``
translates an intent into exact ``MasteringParameters`` values, and
``audiomind.processing.mix_mapper`` into Mix Engine knobs.

Contract source of truth: ``packages/contracts/intent_profile.schema.json``
(the agent's Zod schema mirrors it too). Fields, enum and defaults here
must match it — ``tests/test_intent_profile_contract.py`` enforces it.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TargetPlatform = Literal["spotify", "apple", "youtube", "club", "none"]

# Canonical order of the 9 intent axes, shared by ``neutral()`` and tests.
INTENT_AXES = (
    "warmth",
    "punch",
    "clarity",
    "brightness",
    "width",
    "bass_weight",
    "vocal_focus",
    "vintage",
    "loudness",
)


class IntentProfile(BaseModel):
    """Semantic mastering intent.

    Every axis lives in [0.0, 1.0] and 0.5 is neutral: an all-0.5 intent
    maps bit-exactly onto ``MasteringParameters()`` (transparent master).

    Validation is STRICT: out-of-range axis values are REJECTED with a
    validation error, never silently clamped. A request asking for
    ``warmth=1.2`` is a bug in the caller, not a value to correct.
    Unknown fields are rejected too (``additionalProperties: false``).
    """

    model_config = ConfigDict(extra="forbid")

    warmth: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Analog warmth / tube saturation character. 0.5 = neutral.",
    )
    punch: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Transient emphasis and dynamic punch. 0.5 = neutral.",
    )
    clarity: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Mid/side reverb clarity and high-frequency definition. "
        "0.5 = neutral.",
    )
    brightness: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Air / high-frequency presence. 0.5 = neutral.",
    )
    width: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Stereo width. 0.5 = neutral, lower = narrower, higher = wider.",
    )
    bass_weight: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Low-end weight and low-band compression. 0.5 = neutral.",
    )
    vocal_focus: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Vocal presence via dynamic EQ at 2.5 kHz. 0.5 = neutral.",
    )
    vintage: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Tape saturation character (bias, hysteresis, roll-off). "
        "0.5 = neutral.",
    )
    loudness: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Loudness target and limiter ceiling. 0.5 = neutral (automatic).",
    )

    # ── Non-axis context ────────────────────────────────────────────
    target_platform: TargetPlatform = Field(
        "none",
        description="Delivery platform, used to pick platform loudness references. "
        '"none" when the user did not name one.',
    )
    reference_genre: str = Field(
        "",
        max_length=60,
        description="Optional genre reference for the master (informational).",
    )
    notes: str = Field(
        "",
        max_length=500,
        description="Free-form user notes about the intended sound (informational).",
    )

    @classmethod
    def neutral(cls) -> "IntentProfile":
        """Return the fully neutral intent (every axis at exactly 0.5).

        Mapping a neutral intent must reproduce ``MasteringParameters()``
        bit-exactly — the transparent master is the reference point the
        mapper is tested against.
        """
        return cls(**{axis: 0.5 for axis in INTENT_AXES})