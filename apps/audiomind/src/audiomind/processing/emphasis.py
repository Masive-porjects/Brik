"""Genre emphasis hook (Mix Engine Paso 06) — vocal/groove balance.

The last mix element of the book (*The Mixing Engineer's Handbook*, Ch8
"Interest", pág. 58–60) is the least automatable: direction, groove,
emotion — "que suene como un evento". The plan maestro's honest
mitigation (``VIABILIDAD_MOTOR_DE_MEZCLA.md``, §Elemento 6) is exactly
what this module encodes: **el énfasis por género** —
"Dance/Rap → énfasis en groove (kick/bajo); Country/Pop → énfasis en
vocal" (pág. 122). WaveIA proposes a "dirección" inicial, the human
decides; without a detectable genre the mix keeps the balanced neutral
profile (universal genres, ``ARQUITECTURA_WAVEIA_DETALLE.md`` §10.1).

Geometry: every detected genre resolves into two scalar weights in
[0, 1] that sum to 1.0 — ``vocal_forward`` (how much the voice is
pushed: more vocal dimension/reverb, drier bed) versus
``groove_forward`` (how much the rhythm is pushed: more drum/bass
presence, more bus glue). The direction driver used by the scalers is

    d = vocal_forward − groove_forward   (∈ [−1, 1])

positive = vocal direction, negative = groove direction, 0 = balanced.
A weight pair of exactly 0.5/0.5 (``d == 0``) is the NEUTRALIZER: every
scaled value stays exactly at its base, so the routing is identical to
Paso 05 (neutrality contract, spec 08 — same backend behaviour, values
bit-identical).

The scalers never invent parameters: they move MIX amounts and the bus
GR target INSIDE the standard ranges the engine already defines
(``reverb.py`` ``Reverb._validate``: mix ∈ [0, 1], size ∈ [0.1, 1.0];
``delay.py`` ``DelayParams._validate``: mix ∈ [0, 1]; the Paso 05 bus
recipe 2–3 dB total, ``dynamics.py``), clamped at the extremes. The
tempo subdivision, pre-delay, return EQ, HP/LP and feedback values stay
verbatim — only the direction knobs move.
"""

from __future__ import annotations

from typing import Any

import numpy as np

#: Confidence floor of the genre detection (documented): below
#: ``CONFIDENCE_THRESHOLD`` the label is reported but NOT followed — the
#: mix keeps the neutral 0.5/0.5 fallback (``neutral_fallback``). The
#: analyzer's rule-based scores (``analyzer._detect_genre``) sit at
#: 0.3–0.85; 0.5 separates "suggested" from "trusted direction".
CONFIDENCE_THRESHOLD: float = 0.5

#: The NEUTRAL weight pair: balanced interest, no direction (the
#: equivalent of "no detectable genre → balanced neutral profile").
NEUTRAL_WEIGHTS: dict[str, float] = {
    "vocal_forward": 0.5,
    "groove_forward": 0.5,
}

#: Per-genre emphasis profiles (book Ch8 "Interest", pág. 58–60 + plan
#: maestro: "Dance/Rap → énfasis en groove (kick/bajo); Country/Pop →
#: énfasis en vocal", ``VIABILIDAD_MOTOR_DE_MEZCLA.md`` §Elemento 6).
#: Every real analyzer genre (``analyzer._detect_genre``) has a profile;
#: each pair sums to exactly 1.0. Genres the manual does not anchor stay
#: balanced (0.5/0.5) or tilt mildly, each justified below.
GENRE_EMPHASIS_PROFILES: dict[str, dict[str, float]] = {
    # ── Vocal direction ──────────────────────────────────────────────
    # Pop: the manual's vocal rule verbatim ("Country/Pop → énfasis en
    # vocal") — the lead voice IS the hook of the genre.
    "pop": {"vocal_forward": 0.70, "groove_forward": 0.30},
    # Acoustic: singer-songwriter family — pop's vocal rule applied
    # gently (the accompanying instruments carry more of the interest
    # than in pop).
    "acoustic": {"vocal_forward": 0.60, "groove_forward": 0.40},
    # Rock: the anthem voice is central, but the back-beat/riff engine
    # shares the interest — a mild vocal lean, never an extreme.
    "rock": {"vocal_forward": 0.55, "groove_forward": 0.45},
    # ── Groove direction ─────────────────────────────────────────────
    # Electronic/Dance: the manual's groove rule verbatim ("Dance →
    # énfasis en groove (kick/bajo)").
    "electronic": {"vocal_forward": 0.30, "groove_forward": 0.70},
    # Hip-hop/Rap: the manual's groove rule verbatim ("Rap → énfasis en
    # groove (kick/bajo)").
    "hip_hop": {"vocal_forward": 0.30, "groove_forward": 0.70},
    # Reggaeton: same urban groove family as Dance/Rap — the dembow
    # kick/bajo pulse is the genre's engine (manual groove rule).
    "reggaeton": {"vocal_forward": 0.30, "groove_forward": 0.70},
    # Metal: double-kick/riff pulse is the engine — the manual's groove
    # rule extended to guitar-driven rhythm (vocals ride on top).
    "metal": {"vocal_forward": 0.45, "groove_forward": 0.55},
    # ── Balanced ─────────────────────────────────────────────────────
    # Jazz/classical/other: the manual anchors no direction — the
    # interest is shared. Jazz: swing section vs. solo voice, even split.
    # Classical: ensemble mix, no element to hype. "other": universal
    # balanced target (analyzer's catch-all), no direction.
    "jazz": {"vocal_forward": 0.50, "groove_forward": 0.50},
    "classical": {"vocal_forward": 0.50, "groove_forward": 0.50},
    "other": {"vocal_forward": 0.50, "groove_forward": 0.50},
}

#: Scale range clamps — the engine's OWN validation ranges (sourced,
#: never invented): ``reverb.py`` ``Reverb._validate`` (mix [0, 1],
#: size [0.1, 1.0]) and ``delay.py`` ``DelayParams._validate``
#: (mix [0, 1]).
REVERB_MIX_MIN, REVERB_MIX_MAX = 0.0, 1.0
REVERB_SIZE_MIN, REVERB_SIZE_MAX = 0.1, 1.0
DELAY_MIX_MIN, DELAY_MIX_MAX = 0.0, 1.0

#: Bus target swing per unit of direction (dB): the scaled GR target
#: moves ±0.5 dB across the full [−1, 1] direction range — "un pelín más
#: de GR" (groove) / "menos GR para dejar respirar la voz" (vocal),
#: inside the recipe's 2–3 dB band (págs. 53–56).
_BUS_TARGET_SWING_DB = 0.5

#: Reverb-mix multiplier slope of the LEAD stem (vocals): ``1 + d`` per
#: the report contract — pop (d = 0.4) lifts the vocals reverb mix from
#: 0.25 to 0.35. The BED stems mirror it with ``1 − d`` (vocal-forward
#: dries the accompaniment so the voice's space stands out, pág. 37–38
#: layering).
_REVERB_MIX_SLOPE = 1.0
#: Reverb-SIZE multiplier slope of the lead stem (``1 + 0.2·d``): the
#: house keeps growing toward the huge hall (size 1.0) under vocal
#: direction; the bed sizes never move.
_REVERB_SIZE_SLOPE = 0.2
#: Delay-mix multiplier slope (``1 ± 0.5·d``): the tempo delay presence
#: follows the direction at half the reverb-mix speed.
_DELAY_MIX_SLOPE = 0.5


def _direction(weights: dict[str, float]) -> float:
    """``vocal_forward − groove_forward`` — the signed direction driver
    in [−1, 1] (0 = balanced/neutral)."""
    return float(weights["vocal_forward"]) - float(weights["groove_forward"])


def resolve_emphasis(
    genre: str | None,
    confidence: float | None,
    profiles: dict[str, dict[str, float]] | None = None,
) -> dict[str, Any]:
    """Resolve the detected genre into its emphasis weights + status.

    The genre hook of the Paso 06 plan: the analyzer's ``_detect_genre``
    label (with its confidence) maps into the vocal-forward/groove-forward
    pair of the "Interest" balance (book Ch8, pág. 58–60). Degradation
    paths are never crashes (Alex guard, same policy as the BPM/dimension
    stages):

    * ``None`` / empty genre → ``{"genre": "unknown", "genre_confidence":
      None, ...}`` with NEUTRAL 0.5/0.5 weights —
      ``status="neutral_fallback"``.
    * label outside the profiles table → same neutral fallback (the genre
      is reported as ``"unknown"``: no direction known for it).
    * known label but ``confidence < CONFIDENCE_THRESHOLD`` (0.5,
      documented) → the label is reported but NOT followed: neutral
      weights, ``neutral_fallback`` status.
    * known label with ``confidence >= 0.5`` (or no confidence provided —
      the caller asserts the genre) → the table weights with
      ``status="active"``.

    Args:
        genre: The analyzer's detected genre (``AnalysisResult
            .detected_genre``) or an explicit caller label.
        confidence: The analyzer's ``genre_confidence``. ``None`` means
            "no confidence information" → the label is trusted.
        profiles: The genre → weights table (default
            ``GENRE_EMPHASIS_PROFILES``). A custom dict overrides the
            table (must map known labels to vocal/groove pairs in [0, 1]
            summing to 1.0 — out-of-range values are clamped downstream).

    Returns:
        ``{"genre": str, "genre_confidence": float|None,
        "vocal_forward": float, "groove_forward": float, "status":
        "active"|"neutral_fallback"}``.
    """
    table = GENRE_EMPHASIS_PROFILES if profiles is None else profiles
    label = str(genre).strip() if genre is not None else ""
    if not label:
        return {
            "genre": "unknown",
            "genre_confidence": None,
            "vocal_forward": NEUTRAL_WEIGHTS["vocal_forward"],
            "groove_forward": NEUTRAL_WEIGHTS["groove_forward"],
            "status": "neutral_fallback",
        }

    profile = table.get(label)
    trusted = confidence is None or float(confidence) >= CONFIDENCE_THRESHOLD
    if profile is None or not trusted:
        return {
            "genre": label if profile is not None else "unknown",
            "genre_confidence": confidence,
            "vocal_forward": NEUTRAL_WEIGHTS["vocal_forward"],
            "groove_forward": NEUTRAL_WEIGHTS["groove_forward"],
            "status": "neutral_fallback",
        }
    return {
        "genre": label,
        "genre_confidence": confidence,
        "vocal_forward": float(profile["vocal_forward"]),
        "groove_forward": float(profile["groove_forward"]),
        "status": "active",
    }


def _clamp(value: float, lo: float, hi: float) -> float:
    """Float clamp (numpy scalar → python float)."""
    return float(np.clip(value, lo, hi))


def scale_dimension_profile(
    profile: dict[str, Any],
    weights: dict[str, float],
    *,
    vocal_lead: bool = False,
) -> dict[str, Any]:
    """Scale one dimension profile along the vocal/groove direction.

    The Paso 06 direction applied to the Paso 04 sends: the LEAD stem
    (vocals) grows its reverb (mix + size) and its tempo-delay presence
    under vocal direction and shrinks under groove; the BED stems
    (drums/bass/other) mirror it (drier under vocal so the voice stands
    out, more present under groove). Multipliers are ``1 + k·d``
    (lead) / ``1 − k·d`` (bed) with the slopes in the module constants:
    at exactly 0.5/0.5 weights the multiplier is EXACTLY 1.0, so the
    scaled profile carries the base values unchanged (the Paso 05
    neutral routing, bit-identical behaviour).

    Only the direction knobs move — the tempo subdivision, pre-delay,
    return EQ, HP/LP and feedback stay verbatim — and everything is
    clamped INSIDE the engine's standard ranges (``reverb.py`` mix
    [0, 1] / size [0.1, 1.0], ``delay.py`` mix [0, 1]): no invented
    out-of-range values, extremes clamp instead of saturating.

    Args:
        profile: One ``DIMENSION_PROFILES`` entry (``reverb`` + ``delay``
            dicts).
        weights: The resolved emphasis weights (``vocal_forward`` /
            ``groove_forward`` keys — e.g. the ``resolve_emphasis``
            output).
        vocal_lead: True for the lead stem (the ``vocals`` role in this
            pipeline); False for the bed (drums/bass/other).

    Returns:
        A NEW profile dict with the scaled values (base profile never
        mutated).
    """
    d = _direction(weights)
    scaled = {
        "reverb": dict(profile.get("reverb") or {}),
        "delay": dict(profile.get("delay") or {}),
    }
    lead = 1.0 + _REVERB_MIX_SLOPE * d if vocal_lead else 1.0 - _REVERB_MIX_SLOPE * d
    scaled["reverb"]["mix"] = _clamp(
        float(scaled["reverb"].get("mix", 0.0)) * lead,
        REVERB_MIX_MIN,
        REVERB_MIX_MAX,
    )
    if vocal_lead:
        scaled["reverb"]["size"] = _clamp(
            float(scaled["reverb"].get("size", 0.5))
            * (1.0 + _REVERB_SIZE_SLOPE * d),
            REVERB_SIZE_MIN,
            REVERB_SIZE_MAX,
        )
    delay_mult = (
        1.0 + _DELAY_MIX_SLOPE * d if vocal_lead else 1.0 - _DELAY_MIX_SLOPE * d
    )
    scaled["delay"]["mix"] = _clamp(
        float(scaled["delay"].get("mix", 0.0)) * delay_mult,
        DELAY_MIX_MIN,
        DELAY_MIX_MAX,
    )
    return scaled


def scale_bus_profile(
    profile: dict[str, Any],
    weights: dict[str, float],
) -> dict[str, Any]:
    """Scale the mix-bus GR target along the vocal/groove direction.

    The Paso 06 direction applied to the Paso 05 bus compressor (Jerry
    Finn, 2–3 dB total, págs. 53–56): groove direction asks for "un
    pelín más de GR" (rítmico glue), vocal direction for "menos GR para
    dejar respirar la voz". The scaled GR target moves ±0.5 dB across the
    full direction range, always INSIDE the recipe's 2–3 dB band, and the
    profile's ``threshold_offset_db`` (the actual GR driver) follows it
    1:1 — the measured GR stays ≤ ``BUS_GR_MAX_DB`` (3.1 dB) at every
    weight in [0, 1] (verified empirically on the project's hot 2-tone
    fixture: offset 2.0 → GR 2.47, offset 3.0 → GR 2.91). Neutral
    0.5/0.5 → target and offset stay exactly at the base values.

    Args:
        profile: The bus profile (``dynamics.BUS_COMPRESSOR_PROFILE``).
        weights: The resolved emphasis weights.

    Returns:
        The scaled profile (same keys as the base; ``threshold_offset_db``
        adjusted) plus the ``"bus_gr_target_db"`` key — emphasis metadata
        with the scaled GR target inside [target_gr_db lo, hi] (ignored by
        the compressor loader ``dynamics._params_from_profile``, which
        reads its known keys only).
    """
    d = _direction(weights)
    lo, hi = map(float, profile.get("target_gr_db", [2.0, 3.0]))
    base_target = (lo + hi) / 2.0
    target = _clamp(base_target - _BUS_TARGET_SWING_DB * d, lo, hi)
    base_offset = float(profile.get("threshold_offset_db", base_target))
    scaled = dict(profile)
    scaled["threshold_offset_db"] = _clamp(
        base_offset + (target - base_target), lo, hi
    )
    scaled["bus_gr_target_db"] = round(target, 2)
    return scaled