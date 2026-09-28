"""Smart gating decision — Advisory Mode.

Decides, from the INPUT ANALYSIS alone, intensity scales for tone-shaping
modules of the mastering chain. Instead of blocking modules (gate = 0.0),
it returns advisory intensity scales (0.3–1.0) per module so the engine can
proportionally reduce corrective processing while preserving character.

Policy
------
The advisory gate is evidence-based but never blocks:

* It evaluates THREE metric conditions (conjunction) with COMMERCIAL
  thresholds:
  1. ``|input LUFS − target LUFS| ≤ COMMERCIAL_LUFS_TOLERANCE_DB`` (0.8 dB);
  2. ``input crest ≥ COMMERCIAL_CREST_MINIMUM_DB`` (4.5 dB — lower floor for
     commercial material which is denser by design);
  3. ``input true peak ≤ effective ceiling + COMMERCIAL_TRUE_PEAK_MARGIN_DB``
     (0.3 dB — tighter margin for commercial delivery).

* When ALL THREE hold, the source is "commercial-ready" and the intensity
  scales drop toward the advisory floor for corrective modules. When ANY
  fails, every scale stays at 1.0 (full processing).

* Character safety: explicit creative signatures (knobs moved from pristine
  defaults) protect their modules — those modules never drop below
  ``SIGNATURE_SCALE_FLOOR``.

* Bypass mode: env var ``SMART_GATE_BYPASS=true`` forces advisory mode OFF,
  returning all scales at 1.0 with ``applied=False``.

Note on the advisory band: ``SCALE_FLOOR`` (0.3) documents the intended
lower bound of the advisory band. The scale table below never actually emits
that value — its lowest assignment is ``CORRECTIVE_SCALE`` (0.4). The floor
constant is the contract that a future branch must not cross toward 0.0.
"""
from __future__ import annotations

import os
from typing import Literal, TypedDict

from audiomind.models.audio import AnalysisResult, MasteringParameters

# ── Commercial Advisory Thresholds ───────────────────────────────────
COMMERCIAL_LUFS_TOLERANCE_DB = 0.8
COMMERCIAL_CREST_MINIMUM_DB = 4.5
COMMERCIAL_TRUE_PEAK_MARGIN_DB = 0.3

#: Bypass the advisory gate entirely (for A/B comparison or debugging).
SMART_GATE_BYPASS = os.getenv("SMART_GATE_BYPASS", "false").lower() == "true"

#: Documented lower bound of the advisory band. A module is never scaled to
#: 0.0 — the gate reduces corrective processing, it does not block it.
SCALE_FLOOR = 0.3
#: No-reduction scale: a module the gate leaves alone.
SCALE_MAX = 1.0
#: Minimum scale for a module whose creative signature the user engaged.
SIGNATURE_SCALE_FLOOR = 0.7
#: Scale for purely corrective/normalizing modules on commercial-ready input.
CORRECTIVE_SCALE = 0.4
#: Scale for the dynamics modules (multiband, dyn EQ, exciter).
DYNAMICS_SCALE = 0.5
#: Scale for the remaining creative tone stages (saturation, spatial).
CREATIVE_SCALE = 0.6

#: Effective-neutral value of the clarity brilliance shelf (module off).
_BRIGHTNESS_OFF = 0.0
#: Pristine-default value of the clarity brilliance shelf (product baseline).
_BRIGHTNESS_DEFAULT = 1.0
#: Pristine-default clarity wet/dry (product baseline reverb tail).
_CLARITY_WET_DEFAULT = 0.15
#: Pristine-default compression ratio (product baseline squeeze).
_COMP_RATIO_DEFAULT = 2.0

#: Modules that receive advisory intensity scales (never blocked to 0.0).
#: The engine looks these keys up in ``intensity_scales``.
ADVISORY_MODULES = [
    "match_eq",
    "clarity_shelf",
    "warmth_tilt",
    "compressor",
    "deesser",
    "multiband",
    "dyn_eq",
    "exciter",
    "saturation",
    "spatial",
]

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
    default value — the user lifted it, so reducing that group could silently
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


def _is_module_engaged(module: str, engaged_signatures: list[str]) -> bool:
    """Check if a module has an explicit creative signature engaged."""
    module_to_signature = {
        "match_eq": [],  # Always corrective, never a signature
        "clarity_shelf": ["clarity_shelf"],
        "warmth_tilt": ["saturation"],
        "compressor": ["compression"],
        "deesser": [],  # Corrective only
        "multiband": ["multiband"],
        "dyn_eq": ["dyn_eq"],
        "exciter": ["exciter"],
        "saturation": ["saturation"],
        "spatial": ["spatial", "delay", "echo", "reverb"],
    }
    signatures = module_to_signature.get(module, [])
    return any(sig in engaged_signatures for sig in signatures)


def _scale_for_module(module: str, engaged: bool) -> float:
    """Advisory scale for a single module on commercial-ready input."""
    if engaged:
        # An explicit creative choice is protected.
        return SIGNATURE_SCALE_FLOOR
    if module in ("match_eq", "clarity_shelf", "warmth_tilt", "compressor", "deesser"):
        return CORRECTIVE_SCALE
    if module in ("multiband", "dyn_eq", "exciter"):
        return DYNAMICS_SCALE
    return CREATIVE_SCALE


class SmartGateReport(TypedDict):
    """Decision report of ``decide_smart_gate`` (engine result conventions)."""

    applied: bool
    tier: Literal["advisory", "none"]
    gated_modules: list[str]
    intensity_scales: dict[str, float]
    evidence: dict[str, object]


def _full_scales() -> dict[str, float]:
    return {m: SCALE_MAX for m in ADVISORY_MODULES}


def decide_smart_gate(
    params: MasteringParameters,
    analysis: AnalysisResult | None,
    effective_ceiling_db: float = _DEFAULT_CEILING_DB,
) -> SmartGateReport:
    """Decide advisory intensity scales for tone-shaping modules.

    Returns a report-dict with advisory intensity scales per module:

    ``{"applied": bool, "tier": "advisory"|"none",
       "gated_modules": list[str], "intensity_scales": dict[str, float],
       "evidence": dict}``

    ``applied`` is True when the advisory mode is active (all three
    commercial-readiness conditions met); ``tier`` is "advisory" when active
    and "none" when bypassed or when the conditions are not met.
    ``intensity_scales`` provides a per-module factor that is never 0.0 —
    the gate reduces corrective processing proportionally, it never blocks a
    module outright. Modules with an engaged creative signature never drop
    below ``SIGNATURE_SCALE_FLOOR``. ``evidence`` carries the
    measured-vs-target values.
    """
    # Bypass mode: env var forces all scales to 1.0 (full processing).
    if SMART_GATE_BYPASS:
        return {
            "applied": False,
            "tier": "none",
            "gated_modules": [],
            "intensity_scales": _full_scales(),
            "evidence": {"reason": "SMART_GATE_BYPASS=true"},
        }

    if analysis is None:
        return {
            "applied": False,
            "tier": "none",
            "gated_modules": [],
            "intensity_scales": _full_scales(),
            "evidence": {"reason": "no analysis available"},
        }

    target_lufs = _resolve_target_lufs(params)
    lufs_delta_db = analysis.integrated_lufs - target_lufs
    lufs_within_tolerance = abs(lufs_delta_db) <= COMMERCIAL_LUFS_TOLERANCE_DB
    crest_healthy = analysis.crest_factor_db >= COMMERCIAL_CREST_MINIMUM_DB
    peak_deliverable = (
        analysis.true_peak_db <= effective_ceiling_db + COMMERCIAL_TRUE_PEAK_MARGIN_DB
    )
    evidence: dict[str, object] = {
        "input_lufs": round(analysis.integrated_lufs, 2),
        "target_lufs": round(target_lufs, 2),
        "lufs_delta_db": round(lufs_delta_db, 2),
        "input_crest_db": round(analysis.crest_factor_db, 2),
        "input_true_peak_db": round(analysis.true_peak_db, 2),
        "effective_ceiling_db": round(effective_ceiling_db, 2),
        "lufs_within_tolerance": lufs_within_tolerance,
        "crest_healthy": crest_healthy,
        "peak_deliverable": peak_deliverable,
        "genre_confidence": round(analysis.genre_confidence, 2),
        "mastering_confidence": round(analysis.mastering_confidence, 2),
        "is_already_mastered": analysis.is_already_mastered,
    }

    # Commercial readiness requires all three conditions.
    commercial_ready = lufs_within_tolerance and crest_healthy and peak_deliverable
    if not commercial_ready:
        return {
            "applied": False,
            "tier": "none",
            "gated_modules": [],
            "intensity_scales": _full_scales(),
            "evidence": evidence,
        }

    engaged = _signature_engaged(params)
    intensity_scales: dict[str, float] = {}
    reduced: list[str] = []
    for module in ADVISORY_MODULES:
        scale = _scale_for_module(module, _is_module_engaged(module, engaged))
        intensity_scales[module] = round(scale, 2)
        if scale < SCALE_MAX:
            reduced.append(module)

    return {
        "applied": True,
        "tier": "advisory",
        "gated_modules": reduced,
        "intensity_scales": intensity_scales,
        "evidence": evidence,
    }
