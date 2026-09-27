"""Smart gating decision (Phase A — "menos es más").

Decides, from the INPUT ANALYSIS alone, whether corrective tone-shaping
modules of the mastering chain can be skipped because the source already
satisfies the delivery targets.

Policy
------
The gate is strictly evidence-based and conservative:

* It requires ALL THREE metric conditions to hold (conjunction), every
  threshold anchored in the existing Layer 2 validation gate:

  1. ``|input LUFS − target LUFS| ≤ LUFS_TOLERANCE_DB`` (validation.py,
     currently 1.5 dB);
  2. ``input crest ≥ CREST_MINIMUM_DB`` (validation.py, currently 6.0 dB —
     the same "healthy" floor the Layer 2 crest check enforces);
  3. ``input true peak ≤ effective ceiling + TRUE_PEAK_MARGIN_DB``
     (validation.py, currently 0.1 dB — the input is already deliverable
     under the limiter ceiling without corrective loudness work).

  The conjunction itself IS the "dense / already-mastered-like" profile:
  it mirrors the feature set the analyzer's ``_detect_already_mastered``
  scores (LUFS near target, true peak near 0 dBFS, tight crest). Genre /
  spectral confidence is recorded in the evidence for the report but is not
  a hard requirement — requiring it would skip gating exactly the
  unknown-genre dense masters that benefit most, and the match EQ toward an
  uncertain genre profile is the riskiest corrective move.

* Character safety: the engine has no preset id, so an explicitly chosen
  creative character is inferred from ``MasteringParameters`` (a knob moved
  away from its pristine default = the user engaged that signature). When
  any signature is engaged the gate drops to "conservative" tier and only
  reduces modules whose job is purely corrective/normalizing — the analysis-
  derived match EQ, and the fixed compressor only when compression knobs are
  pristine (otherwise the compressor itself is the engaged signature, e.g.
  ``fuego``/``empuje`` punch). Signature modules are NEVER gated.
"""
from __future__ import annotations

from typing import Literal, TypedDict

from audiomind.models.audio import AnalysisResult, MasteringParameters
from audiomind.processing.validation import (
    CREST_MINIMUM_DB,
    LUFS_TOLERANCE_DB,
    TRUE_PEAK_MARGIN_DB,
)

#: Effective-neutral value of the clarity brilliance shelf (module off).
_BRIGHTNESS_OFF = 0.0
#: Pristine-default value of the clarity brilliance shelf (product baseline).
_BRIGHTNESS_DEFAULT = 1.0
#: Pristine-default clarity wet/dry (product baseline reverb tail).
_CLARITY_WET_DEFAULT = 0.15
#: Pristine-default compression ratio (product baseline squeeze).
_COMP_RATIO_DEFAULT = 2.0

#: Full-gate module list (input already meets target, no character chosen):
#: every corrective/normalizing tone-shaping stage is bypassed. The HPF,
#: spatial block, mono-compat, saturation, loudness alignment, soft-clip,
#: final limiter and dither always run (delivery-critical).
FULL_GATE_MODULES = ["match_eq", "clarity_shelf", "warmth_tilt", "compressor"]
#: Conservative-gate module list (character chosen): only the analysis-
#: derived corrective match EQ is always reducible; the fixed compressor is
#: added only when compression knobs are pristine (see decide_smart_gate).
CONSERVATIVE_GATE_MODULES = ["match_eq"]


#: Default limiter ceiling used when the smart gate resolves targets.
_DEFAULT_CEILING_DB = -1.0


def _resolve_target_lufs(params: MasteringParameters) -> float:
    """Resolve the loudness target exactly as the engine does.

    Explicit ``target_lufs_db`` wins; otherwise the automatic platform target
    derived from the limiter ceiling (``-14 + (1 − ceiling/−0.3) · 6``,
    clamped to [-14, -12]) applies.
    """
    if params.target_lufs_db is not None:
        return params.target_lufs_db
    target = -14.0 + (1.0 - params.limiter_ceiling_db / -0.3) * 6.0
    return max(-14.0, min(-12.0, target))


def _signature_engaged(params: MasteringParameters) -> list[str]:
    """Which creative character groups the user explicitly engaged.

    A group is "engaged" when any of its knobs sits away from the pristine
    default value — the user lifted it, so gating that group could silently
    change the character they chose. ``clarity_brightness_db`` and
    ``clarity_wet`` are special: the product's pristine defaults (1.0 dB /
    0.15) are the baseline character, not an explicit choice, so those exact
    values do not count as engaged; ``0.0`` (module off) neither.
    """
    engaged: list[str] = []
    if (
        params.saturation_drive_db != 0.0
        or params.tape_enabled
        or params.saturation_warmth_db != 0.0
    ):
        engaged.append("saturation")
    if params.clarity_brightness_db not in (_BRIGHTNESS_OFF, _BRIGHTNESS_DEFAULT):
        engaged.append("clarity_shelf")
    if (
        params.clarity_wet != _CLARITY_WET_DEFAULT
        or params.stereo_width != 1.0
        or params.haas_delay_ms != 0.0
        or params.stereo_imaging_enabled
    ):
        engaged.append("spatial")
    if (
        params.compression_ratio != _COMP_RATIO_DEFAULT
        or params.transient_boost_db != 0.0
        or params.adaptive_comp_enabled
    ):
        engaged.append("compression")
    for name, flag in (
        ("multiband", params.multiband_enabled),
        ("dyn_eq", params.dyn_eq_enabled),
        ("exciter", params.exciter_enabled),
        ("delay", params.delay_enabled),
        ("echo", params.echo_enabled),
        ("reverb", params.reverb_enabled),
    ):
        if flag:
            engaged.append(name)
    return engaged


class SmartGateReport(TypedDict):
    """Decision report of ``decide_smart_gate`` (engine result conventions)."""

    applied: bool
    tier: Literal["full", "conservative", "none"]
    gated_modules: list[str]
    evidence: dict[str, object]


def decide_smart_gate(
    params: MasteringParameters,
    analysis: AnalysisResult | None,
    effective_ceiling_db: float = _DEFAULT_CEILING_DB,
) -> SmartGateReport:
    """Decide whether (and which) chain modules can be gated.

    Returns a report-dict following the engine result conventions:

    ``{"applied": bool, "tier": "full"|"conservative"|"none",
       "gated_modules": list[str], "evidence": dict}``

    ``applied`` is True when the gate is active; ``tier`` describes the
    depth: "full" (no explicit character — bypass match EQ, clarity shelf,
    warmth tilt and the fixed compressor) or "conservative" (a creative
    signature is engaged — bypass only the analysis-derived match EQ, plus
    the fixed compressor when compression knobs are pristine). ``evidence``
    carries the measured-vs-target values for the report payload.
    """
    if analysis is None:
        return {
            "applied": False,
            "tier": "none",
            "gated_modules": [],
            "evidence": {"reason": "no analysis available"},
        }

    target_lufs = _resolve_target_lufs(params)
    lufs_delta_db = analysis.integrated_lufs - target_lufs
    evidence: dict[str, object] = {
        "input_lufs": round(analysis.integrated_lufs, 2),
        "target_lufs": round(target_lufs, 2),
        "lufs_delta_db": round(lufs_delta_db, 2),
        "input_crest_db": round(analysis.crest_factor_db, 2),
        "input_true_peak_db": round(analysis.true_peak_db, 2),
        "effective_ceiling_db": round(effective_ceiling_db, 2),
        "lufs_within_tolerance": abs(lufs_delta_db) <= LUFS_TOLERANCE_DB,
        "crest_healthy": analysis.crest_factor_db >= CREST_MINIMUM_DB,
        "peak_deliverable": (
            analysis.true_peak_db <= effective_ceiling_db + TRUE_PEAK_MARGIN_DB
        ),
        "genre_confidence": round(analysis.genre_confidence, 2),
        "mastering_confidence": round(analysis.mastering_confidence, 2),
        "is_already_mastered": analysis.is_already_mastered,
    }
    if not (
        evidence["lufs_within_tolerance"]
        and evidence["crest_healthy"]
        and evidence["peak_deliverable"]
    ):
        return {
            "applied": False,
            "tier": "none",
            "gated_modules": [],
            "evidence": evidence,
        }

    engaged = _signature_engaged(params)
    if engaged:
        gated = list(CONSERVATIVE_GATE_MODULES)
        # Compression knobs are pristine → the fixed 2:1 stage is the
        # corrective/normalizing default, safe to gate. If compression is the
        # engaged signature (fuego/empuje punch) the compressor is character
        # and stays.
        if "compression" not in engaged:
            gated.append("compressor")
        tier: Literal["conservative", "full"] = "conservative"
    else:
        gated = list(FULL_GATE_MODULES)
        tier = "full"
    return {
        "applied": True,
        "tier": tier,
        "gated_modules": gated,
        "evidence": evidence,
    }