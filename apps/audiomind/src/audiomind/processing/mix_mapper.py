"""Map a high-level intent onto the Mix Engine request knobs.

Mix-side twin of ``audiomind.processing.mapper`` (which targets the
mastering chain). The SAME ``IntentProfile`` the agent produces drives
both mappers, so one user request ("voz más al frente, más punch") moves
the mix AND the master coherently.

This module only emits the knobs ``POST /session/{id}/mix`` already
exposes (``MixRequest``): per-stem faders (``stem_trims``), the adaptive
vocal treatment and the spatial dimension stage. It never reaches into the
DSP internals of ``mix_engine`` — the engine owns HOW, the mapper only
decides WHAT the user asked for.

Axes consumed here: ``vocal_focus`` → vocal fader (+ adaptive vocal
treatment when strongly engaged), ``punch`` → drums fader,
``bass_weight`` → bass fader. The remaining axes (warmth, clarity,
brightness, width, vintage, loudness) are mastering concerns and leave the
mix untouched.

Neutrality contract (spec 08, neutral = bypass): ``IntentProfile.neutral()``
maps onto ``MixSettings()``, whose fields equal the ``MixRequest``
defaults — ``stem_trims=None`` keeps the exact previous payload, with no
``trim_report`` key.

The fader anchors (±3 dB at the axis extremes) are PROVISIONAL: half of
the ±6 dB fader band (``TRIM_STEM_RANGE``), so the intent never saturates
the band on its own. They must be validated with the DSP owner before
being treated as canonical values.
"""
from pydantic import BaseModel

from audiomind.models.intent_profile import IntentProfile
from audiomind.processing.mapper import _lerp
from audiomind.processing.stem_balance import TRIM_STEM_RANGE

# Fader swing at the axis extremes (0.0 / 1.0). Neutral 0.5 is 0 dB.
_TRIM_SWING_DB = 3.0

# Same engage level the mastering mapper uses for vocal_focus (dyn EQ):
# above it the voice is a clear priority, so the adaptive vocal
# treatment (register-driven EQ on the vocal stem) is switched on.
_VOCAL_TREATMENT_ENGAGE = 0.6

assert _TRIM_SWING_DB <= min(abs(TRIM_STEM_RANGE[0]), TRIM_STEM_RANGE[1])


class MixSettings(BaseModel):
    """Mix Engine knobs derived from an intent.

    Field names and defaults mirror ``api.mix.MixRequest`` exactly, so
    ``MixRequest(**settings.model_dump())`` is a valid request body.
    """

    dimension_enabled: bool = True
    vocal_treatment: bool = False
    auto_balance: bool = False
    stem_trims: dict[str, float] | None = None


def _fader(axis: float) -> float:
    """-3 dB @ 0.0, 0 dB @ 0.5 (exact), +3 dB @ 1.0."""
    return _lerp(axis, [(0.0, -_TRIM_SWING_DB), (0.5, 0.0), (1.0, _TRIM_SWING_DB)])


def map_intent_to_mix(intent: IntentProfile) -> MixSettings:
    """Translate a semantic intent into Mix Engine request knobs.

    Only non-zero faders are emitted; when every fader is 0 dB the
    ``stem_trims`` field stays ``None`` (exact previous routing, no
    ``trim_report``). ``auto_balance`` stays off: the faders express the
    user's intent explicitly, and the engine's genre auto-balance remains
    an independent opt-in.
    """
    settings = MixSettings()

    trims = {
        "vocals_db": _fader(intent.vocal_focus),
        "drums_db": _fader(intent.punch),
        "bass_db": _fader(intent.bass_weight),
    }
    active = {key: db for key, db in trims.items() if db != 0.0}
    settings.stem_trims = active or None

    settings.vocal_treatment = intent.vocal_focus > _VOCAL_TREATMENT_ENGAGE

    return settings
