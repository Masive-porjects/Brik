"""Map a high-level intent onto the Mix Engine request knobs.

Mix-side twin of ``audiomind.processing.mapper`` (which targets the
mastering chain). The SAME ``IntentProfile`` the agent produces drives
both mappers, so one user request ("voz más al frente, más punch") moves
the mix AND the master coherently.

This module only emits the knobs ``POST /session/{id}/mix`` already
exposes (``MixRequest``): per-stem faders (``stem_trims``) and the spatial
dimension stage. It never reaches into the DSP internals of
``mix_engine`` — the engine owns HOW, the mapper only decides WHAT the
user asked for.

Axes consumed here: ``punch`` → drums fader, ``bass_weight`` → bass
fader. The remaining axes (warmth, clarity, brightness, width, vintage,
loudness) are mastering concerns and leave the mix untouched.

Neutrality — scope it precisely. A fully neutral intent emits NO per-stem
dB offset: every fader is exactly 0 dB, so ``stem_trims`` stays ``None``
and the payload keeps the previous routing (no ``trim_report`` key). That
is the WHOLE of the "neutral = bypass" guarantee here, and it is a claim
about the fader contribution only — NOT about bit-identical audio.
``MixSettings()`` does equal the ``MixRequest`` defaults, but
``dimension_enabled`` is ``True``, so the engine's default dimension stage
(tempo delay + Schroeder reverb per stem) still runs. The mix-side twin
therefore does not inherit the mastering mapper's bit-exact transparency.

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

assert _TRIM_SWING_DB <= min(abs(TRIM_STEM_RANGE[0]), TRIM_STEM_RANGE[1])


class MixSettings(BaseModel):
    """Mix Engine knobs derived from an intent.

    Field names and defaults mirror ``api.mix.MixRequest`` exactly, so
    ``MixRequest(**settings.model_dump())`` is a valid request body.
    """

    dimension_enabled: bool = True
    # Deprecated on the request side: accepted and ignored. Mirrored only so
    # ``MixRequest(**settings.model_dump())`` stays a valid body — the mapper
    # deliberately never sets it.
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
        # No vocal fader axis: it was removed together with the Vocal Chain,
        # so the voice stays pinned at the neutral 0.0 dB.
        "vocals_db": 0.0,
        "drums_db": _fader(intent.punch),
        "bass_db": _fader(intent.bass_weight),
    }
    active = {key: db for key, db in trims.items() if db != 0.0}
    settings.stem_trims = active or None

    return settings
