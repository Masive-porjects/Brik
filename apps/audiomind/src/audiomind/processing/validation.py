"""Post-master validation gate (Layer 2) — pure comparison logic.

Compares the MEASURED master metrics against the active preset chain
targets. No DSP, no I/O — trivially unit-testable. The caller decides
whether to retry processing; this module only judges.
"""
from __future__ import annotations

from audiomind.models.audio import AnalysisResult, MasterResultMetrics
from typing import Any

# ── Layer 2 tolerances ────────────────────────────────────────────────
LUFS_TOLERANCE_DB = 1.5      # |measured − target| above this → issue
CREST_MINIMUM_DB = 6.0       # below this → over-compressed
TRUE_PEAK_MARGIN_DB = 0.1    # measured above ceiling + margin → issue
LOW_CONFIDENCE_THRESHOLD = 0.6  # below → suggest "universal" on warning

# ── Phase A delivery QC ────────────────────────────────────────────────
# Stereo correlation floor for the final master (Phase A, A2): values
# below this indicate phase/imaging problems that can cancel in mono
# (widely used as the "correlation meter red zone" floor — e.g. Ozone's
# correlation meter and ITU-style mono-compat guidance treat < 0.3..0.4
# as risky; 0.35 is a defensible middle point). WARNING only — never a
# strict rejection.
STEREO_CORRELATION_MINIMUM = 0.35
# Dynamic-range floor for the delivered master (Phase A, A3): the output
# LRA must stay above half of the input dynamic range (a delivered master
# that collapses more than 50% of the source's dynamics is over-normalized)
# AND above an absolute floor of 3.0 LU (EBU 3342's percentile spread
# floor for "flat" program material). Both thresholds are conservative:
# the gate only warns, never rejects, so genuine loud masters are informed
# but not blocked.
DR_COLLAPSE_RATIO = 0.5       # output_lra < input_dr * this → issue
DR_MINIMUM_LU = 3.0           # absolute loudness-range floor for delivery


def _lufs_issue(measured: float, target: float) -> dict[str, Any]:
    delta = measured - target
    direction = "bajo" if delta < 0 else "alto"
    return {
        "metric": "lufs",
        "measured": float(measured),
        "expected": f"{target:g} LUFS ±{LUFS_TOLERANCE_DB:g}",
        "message_es": (
            f"El master quedó {abs(delta):.1f} LUFS más {direction} "
            "que el objetivo"
        ),
    }


def _crest_issue(measured: float) -> dict[str, Any]:
    return {
        "metric": "crest",
        "measured": float(measured),
        "expected": f"≥ {CREST_MINIMUM_DB:g} dB",
        "message_es": (
            f"El master está sobre-comprimido "
            f"(crest {measured:.1f} dB)"
        ),
    }


def _true_peak_issue(measured: float, ceiling: float) -> dict[str, Any]:
    excess = measured - ceiling
    return {
        "metric": "true_peak",
        "measured": float(measured),
        "expected": f"≤ {ceiling:g} dB",
        "message_es": (
            f"El pico real superó el techo del preset en {excess:.1f} dB"
        ),
    }


def _correlation_issue(measured: float) -> dict[str, Any]:
    return {
        "metric": "correlation",
        "measured": float(measured),
        "expected": f"≥ {STEREO_CORRELATION_MINIMUM:g}",
        "message_es": (
            f"El master tiene problemas de fase/imagen estéreo "
            f"(correlación {measured:.2f}; puede cancelarse en mono)"
        ),
    }


def _dr_issue(output_lra: float, input_dr_db: float) -> dict[str, Any]:
    return {
        "metric": "dr",
        "measured": float(output_lra),
        "expected": (
            f"≥ {DR_MINIMUM_LU:g} LU y ≥ {DR_COLLAPSE_RATIO:g}× "
            f"del rango dinámico de entrada ({input_dr_db:g} dB)"
        ),
        "message_es": (
            f"El master colapsó la dinámica "
            f"(LRA de salida {output_lra:.1f} LU vs {input_dr_db:.1f} dB "
            "de entrada)"
        ),
    }


def validate_master(
    master_result: MasterResultMetrics | None,
    preset: dict[str, Any],
    analysis: AnalysisResult | None = None,
) -> dict[str, Any] | None:
    """Judge the measured master against the active preset targets.

    Args:
        master_result: Measured output metrics (may be None or hold null
            fields when measurement failed — never treated as an issue).
        preset: Active ``PRESET_CHAINS`` entry (target_lufs,
            limiter_ceiling_db).
        analysis: Input analysis, used for the genre-confidence
            fallback suggestion and the Phase A dynamic-range ratio
            check (input ``dynamic_range_db`` vs output ``lra``).

    Returns:
        Verdict dict with ``status``, ``issues``, ``retry_recommended``
        and ``suggested_preset_id`` — or None when there is nothing
        measurable to validate (callers keep ``validation`` null).
    """
    if master_result is None:
        return None

    issues: list[dict[str, Any]] = []

    target_lufs = preset.get("target_lufs")
    ceiling = preset.get("limiter_ceiling_db")

    lufs = master_result.integrated_lufs
    crest = master_result.crest_factor_db
    peak = master_result.true_peak_db
    correlation = master_result.stereo_correlation
    output_lra = master_result.lra
    input_dr_db = analysis.dynamic_range_db if analysis is not None else None

    if lufs is not None and target_lufs is not None:
        if abs(lufs - target_lufs) > LUFS_TOLERANCE_DB:
            issues.append(_lufs_issue(lufs, target_lufs))

    if crest is not None and crest < CREST_MINIMUM_DB:
        issues.append(_crest_issue(crest))

    if peak is not None and ceiling is not None:
        if peak > ceiling + TRUE_PEAK_MARGIN_DB:
            issues.append(_true_peak_issue(peak, ceiling))

    # Phase A (A2): stereo-correlation QC — warning only, mono has no
    # correlation (None) and is never flagged.
    if correlation is not None and correlation < STEREO_CORRELATION_MINIMUM:
        issues.append(_correlation_issue(correlation))

    # Phase A (A3): dynamic-range QC — an absolute floor AND a collapse
    # ratio anchored on the INPUT dynamics. Only emitted when both the
    # output LRA and the input DR are actually measurable.
    if output_lra is not None and input_dr_db is not None and input_dr_db > 0:
        if output_lra < DR_MINIMUM_LU or output_lra < input_dr_db * DR_COLLAPSE_RATIO:
            issues.append(_dr_issue(output_lra, input_dr_db))

    # Nothing measurable at all (failed best-effort measurement)
    if lufs is None and crest is None and peak is None:
        return None

    status = "warning" if issues else "ok"

    confidence = (
        analysis.genre_confidence
        if analysis is not None and analysis.genre_confidence is not None
        else 0.0
    )
    suggested_preset_id = (
        "universal" if status != "ok" and confidence < LOW_CONFIDENCE_THRESHOLD else None
    )

    return {
        "status": status,
        "issues": issues,
        "retry_recommended": status != "ok",
        "suggested_preset_id": suggested_preset_id,
    }
