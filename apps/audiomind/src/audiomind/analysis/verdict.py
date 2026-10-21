"""Brik's routing verdict — the decision layer over the analysis.

Brik already MEASURES like the reference tooling (LUFS, crest, DR, genre,
per-band energy). What was missing is the step that turns those numbers into a
DECISION the user can act on: *does this track need a mix, or only a master?*

This module is that step, and nothing more. It is a PURE function of an
already-measured :class:`AnalysisResult`: it decodes no audio, runs no DSP and
measures nothing. That is deliberate — the verdict can then be computed in the
cheap analysis phase, persisted on ``SessionData`` and shipped in a job result
without paying for a second decode.

The three regimes
-----------------
``analyzer._detect_already_mastered`` already documents the calibration this
verdict builds on (``analyzer.py`` module docstring of that function):

* raw mix:        crest 16-24 dB, DR 14-20 dB  -> needs a mix
* finished mix:   crest 12-16 dB, DR 10-14 dB  -> master it, do not re-balance
* already master: crest  8-12 dB              -> master it, never separate

Crest is the primary axis because it is the metric the detector itself weights
most, and the one that separates "a bounce someone balanced" from "a rough
export". Dynamic range corroborates it.

The mastered flag wins
----------------------
``is_already_mastered`` is a weighted score over five metrics, not a single
threshold. When the engine says a track is mastered, it is balanced: separating
it can only degrade it. So that flag OVERRIDES a raw-looking crest — see
``build_verdict``.

Neutral = bypass
----------------
Nothing here changes audio. The verdict only names a route; the orchestrator is
free to ignore it (``decision="auto"`` is the only path that consumes it, and an
unmeasurable track falls back to the historical four-phase run).
"""
from __future__ import annotations

from audiomind.models.audio import (
    AnalysisResult,
    AudioVerdict,
    Deficiency,
    ReasoningKey,
    Route,
    RouteId,
)

#: Re-exported so the existing import sites keep working: ``agentic_loop`` and
#: ``prompts`` import ``AudioVerdict`` from here, and the job service imports
#: ``build_verdict``. The MODELS themselves now live in ``models/audio.py``,
#: beside ``AnalysisResult`` and ``SessionData`` -- see the note there for why
#: that placement is load-bearing rather than cosmetic.
__all__ = [
    "AudioVerdict",
    "Deficiency",
    "ReasoningKey",
    "Route",
    "RouteId",
    "build_verdict",
    "compute_deficiencies",
]

#: Crest factor (dB) at or above which a track is treated as raw/unnmixed.
#: Anchor from ``_detect_already_mastered``: raw mixes sit at 16-24 dB.
RAW_MIX_CREST_DB = 16.0

#: Crest factor (dB) at or below which a track is treated as already mastered.
#: Anchor: mastered material sits at 8-12 dB.
MASTERED_CREST_DB = 12.0

#: How far a band must sit from the genre target before it is worth telling the
#: user. Below roughly 2 dB the gap is inaudible in a mix context, and reporting
#: it would bury the real problems in noise.
DEFICIENCY_THRESHOLD_DB = 2.0

#: How far a band may sit from the measurement's OWN mean before its delta stops
#: being a spectral gap and becomes a hole. If ``analyze_band_energies`` reports
#: a band 30 dB under its siblings, that is a bug or a gap in the material — the
#: ``target - shape`` arithmetic would happily fold it back as a huge "lacks",
#: which would be a lie about the audio. Mirrors the runaway-band guard the
#: mixture analysis already applies, and keeps the verdict conservative.
RUNAWAY_BAND_DB = 20.0


#: User-facing copy for each route. Kept here (not in the UI) so the agent's
#: chat message and the card cannot drift apart.
_ROUTE_COPY: dict[RouteId, tuple[str, str]] = {
    "mix_then_master": (
        "Separar y mezclar primero",
        "El audio viene sin mezclar. Se separa en stems, se balancea y después "
        "se masteriza.",
    ),
    "master_only": (
        "Solo masterizar",
        "El audio ya tiene una mezcla terminada. Se masteriza directo, sin "
        "tocarlo.",
    ),
}


def _routes_for(recommended: RouteId) -> list[Route]:
    """Both routes, in a stable order, with exactly one flagged recommended."""
    order: tuple[RouteId, ...] = ("mix_then_master", "master_only")
    return [
        Route(
            id=route_id,
            label_es=_ROUTE_COPY[route_id][0],
            description_es=_ROUTE_COPY[route_id][1],
            recommended=route_id == recommended,
        )
        for route_id in order
    ]


def compute_deficiencies(
    band_energies_db: list[float],
    genre: str | None = None,
) -> list[Deficiency]:
    """Name the bands sitting away from the genre's target curve.

    **This is deliberately the SAM triple the engine's Match EQ already uses**,
    so the sentence Brik says about the audio and the EQ that actually runs can
    never contradict each other (``engine.py``, ``_build_match_eq_plugins``):

    * the genre profile is relative to PINK NOISE;
    * the measurement is converted to the same reference by subtracting its own
      mean (the "shape" of the spectrum, not its absolute level);
    * ``delta = target − shape``: positive means the band is quieter than the
      standard and needs a boost.

    Two consequences that are not obvious and are pinned by tests:

    A **pure level change is not a deficiency.** A mix 6 dB quieter than the
    target still shows no gap, because both sides are relative. That is correct:
    level is the mastering stage's job, not a spectral problem.

    A band whose energy sits more than :data:`RUNAWAY_BAND_DB` from the
    measurement's own mean is skipped, never reported. At that separation the
    arithmetic stops describing a mix balance and starts describing a hole in
    the material, and reporting it would be a fabricated "lacks".

    Args:
        band_energies_db: Per-band levels from ``analyze_band_energies``, in the
            order of ``TARGET_BANDS_HZ``.
        genre: Detected genre key. Unknown values fall back to the universal
            ``other`` profile, exactly like the engine does.

    Returns:
        Deficiencies whose ``|delta_db|`` exceeds :data:`DEFICIENCY_THRESHOLD_DB`,
        largest magnitude first. Empty when the measurement is missing, silent,
        or has no band past the threshold — never an error.
    """
    # Imported here, not at module scope, to keep this module free of the
    # ``analyzer`` dependency at import time. ``analyzer`` imports
    # ``models.audio``, which rebuilds ``SessionData`` against ``AudioVerdict``
    # (see the note at the bottom of this file) -- importing it eagerly would
    # make ``verdict`` -> ``analyzer`` -> ``models.audio`` -> ``verdict`` a cycle
    # that raises ``ImportError`` whenever this module is imported first.
    from audiomind.analysis.analyzer import (
        TARGET_BANDS_HZ,
        get_genre_target_profile,
    )

    # A short list means the measurement never happened: judge no band rather
    # than guess the ones that are missing.
    if len(band_energies_db) < len(TARGET_BANDS_HZ):
        return []

    energies = [float(value) for value in band_energies_db]
    mean_db = sum(energies) / len(energies)
    profile = get_genre_target_profile(genre or "other")

    deficiencies: list[Deficiency] = []
    for band_hz, target, energy in zip(
        TARGET_BANDS_HZ, profile, energies, strict=False
    ):
        shape = energy - mean_db
        if abs(shape) > RUNAWAY_BAND_DB:
            continue

        delta = target - shape
        if abs(delta) <= DEFICIENCY_THRESHOLD_DB:
            continue

        deficiencies.append(
            Deficiency(
                band_hz=band_hz,
                delta_db=round(delta, 1),
                direction="lacks" if delta > 0 else "excess",
            )
        )

    # Biggest gap first: the UI shows them in order and the user should read
    # the real problem before the tail.
    deficiencies.sort(key=lambda item: abs(item.delta_db), reverse=True)
    return deficiencies


def build_verdict(
    analysis: AnalysisResult,
    band_energies_db: list[float] | None = None,
) -> AudioVerdict:
    """Derive the routing verdict from an already-measured analysis.

    Pure function: no decode, no DSP, no I/O. See the module docstring for the
    regime table and why the mastered flag wins.

    The order of the checks matters:

    1. **Unmeasurable** — a crest at or below zero means the meter could not
       produce a ratio (digital silence, or a field that defaulted to 0.0).
       Fail toward doing the work: assume the mix is needed.
    2. **Already mastered** — the engine's own weighted flag. It wins over
       crest because it is corroborated by four other metrics.
    3. **Crest regimes** — the anchors from ``_detect_already_mastered``.

    ``band_energies_db`` is optional on purpose: the routing decision is a pure
    function of the loudness metrics, so a caller that only needs *which path*
    never has to measure the spectrum. Pass the output of
    ``analyze_band_energies`` (order of ``TARGET_BANDS_HZ``) to also get the
    ``deficiencies`` list; omit it and the list stays empty.

    The routing decision NEVER depends on the spectral measurement. A track is
    routed by loudness dynamics, and the deficiencies are the explanation shown
    alongside — never a tie-breaker that could silently reroute the job.
    """
    deficiencies = (
        compute_deficiencies(band_energies_db, analysis.detected_genre)
        if band_energies_db is not None
        else []
    )
    crest = analysis.crest_factor_db or 0.0
    confidence = analysis.mastering_confidence or 0.0

    # 1. Unmeasurable: no crest ratio at all. Conservative, not optimistic.
    if crest <= 0.0:
        return AudioVerdict(
            needs_mix=True,
            confidence=0.0,
            recommended_path="mix_then_master",
            reasoning_key="unmeasurable",
            deficiencies=deficiencies,
            routes=_routes_for("mix_then_master"),
        )

    # 2. The engine's weighted mastered flag overrides a raw-looking crest.
    if analysis.is_already_mastered:
        return AudioVerdict(
            needs_mix=False,
            confidence=max(confidence, 0.5),
            recommended_path="master_only",
            reasoning_key="already_mastered",
            deficiencies=deficiencies,
            routes=_routes_for("master_only"),
        )

    # 3. Crest regimes.
    if crest >= RAW_MIX_CREST_DB:
        # The further past the anchor, the more certain the verdict.
        confidence_mix = min(1.0, 0.5 + (crest - RAW_MIX_CREST_DB) / 16.0)
        return AudioVerdict(
            needs_mix=True,
            confidence=round(confidence_mix, 2),
            recommended_path="mix_then_master",
            reasoning_key="raw_mix_detected",
            deficiencies=deficiencies,
            routes=_routes_for("mix_then_master"),
        )

    if crest <= MASTERED_CREST_DB:
        return AudioVerdict(
            needs_mix=False,
            confidence=0.7,
            recommended_path="master_only",
            reasoning_key="already_mastered",
            deficiencies=deficiencies,
            routes=_routes_for("master_only"),
        )

    # Between the anchors: crest 12-16 dB is a finished mix.
    return AudioVerdict(
        needs_mix=False,
        confidence=0.6,
        recommended_path="master_only",
        reasoning_key="finished_mix_detected",
        deficiencies=deficiencies,
        routes=_routes_for("master_only"),
    )

