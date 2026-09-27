"""QC report on the final bus (Mix Engine Paso 07) — flags, never blockers.

The plan maestro (``odd/tasks/plan-motor-de-mezcla.md``, passo 07) asks
for five checks on the FINAL compressed bus before delivery: mono/fase,
sibilancia 5k, muddy 250, honky 500 and a "escucha a nivel bajo". This
module implements them as INFORMATIONAL flags — ``{"ok": bool,
"details": {...}}`` per check — that never raise and never block the
render (per the plan, blocking is a human decision).

The book gives the RULES, not dB numbers: "si suena muddy, cortar 250
Hz; si suena honky, cortar 500 Hz" (``VIABILIDAD_MOTOR_DE_MEZCLA.md``,
Reglas de oro, pág. 33) and the presence band "4–6 kHz Presence:
claridad/definición" with "dureza en 3–5k" listed as a frequency defect
(pág. 75 of the same analysis). The numeric thresholds below are
therefore documented CALIBRATIONS derived from the relative band-energy
share of the whole bus — reasonable starting points, kept in constants
so they are trivially tunable after a real A/B listening session.

Checks:
* mono — reuses ``panorama.mono_compat_loss_db`` (the EXACT helper
  ``validate_positions`` reports with); compatible when loss
  ≥ ``MONO_COMPAT_MIN_DB`` (−3 dB).
* phase — reuses ``panorama.measure_stereo_position`` correlation
  (Pearson L↔R, the same measurement the pan stage takes); flagged when
  correlation < ``CORRELATION_SAFETY_FLOOR`` (−0.1, from
  ``stereo_imaging``) — anti-phase content cancels in mono downmix.
* sibilance_5k — relative energy of the 4–7 kHz band vs the whole bus.
* muddy_250 — relative energy of the 200–300 Hz band.
* honky_500 — relative energy of the 450–600 Hz band.
* low_level_listen — the plan's "escucha a nivel bajo" is a PERCEPTUAL
  act (listening at low SPL); the measurable proxies implemented here
  are the crest factor (an over-smooth bus < 6 dB crest sounds muddy at
  low level — masking increases as SPL drops; a > 18 dB crest bus loses
  its quiet parts entirely) and the share of samples that still carry
  audible content at a −40 dBFS gate relative to the peak. The real
  listen stays human — the report says so.

The band filters are 2nd-order Butterworth bandpasses via scipy
``butter``/``sosfilt`` over ``axis=-1`` — the same filter family
``processing/dimension.py`` uses; simpler than an FFT and documented.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.signal import butter, sosfilt

from audiomind.processing.panorama import (
    MONO_COMPAT_MIN_DB,
    measure_stereo_position,
    mono_compat_loss_db,
)
from audiomind.processing.stereo_imaging import CORRELATION_SAFETY_FLOOR

#: Sibilance band (book Presence 4–6 kHz; the detector widens to the
#: full 4–7 kHz "sibilant" zone — hats/cymbals/excess 5k presence).
SIBILANCE_BAND_HZ = (4000.0, 7000.0)
#: Calibration: the 4–7 kHz band holding ≥ ~25 % of the bus energy
#: (−6 dB) reads as sibilant/edgy ("dureza en 3–5k" defect). Tune after
#: a real A/B listen.
SIBILANCE_FLAG_DB = -6.0

#: Muddy band (book: "si suena muddy, cortar 250 Hz", pág. 33).
MUDDY_BAND_HZ = (200.0, 300.0)
#: Calibration: ≥ ~16 % of bus energy in the 200–300 Hz band reads as
#: low-mid dominance (mud).
MUDDY_FLAG_DB = -8.0

#: Honky band (book: "si suena honky, cortar 500 Hz", pág. 33).
HONKY_BAND_HZ = (450.0, 600.0)
#: Calibration: ≥ ~12.5 % of bus energy in the 450–600 Hz band reads as
#: horn-like ("500–1k horn-like").
HONKY_FLAG_DB = -9.0

#: Low-level listen: gate 40 dB below the bus peak (a conservative "low
#: volume" listen) and the calibrated crest operating window.
LOW_LEVEL_GATE_DB = -40.0
LOW_LEVEL_ACTIVITY_MIN = 0.5
CREST_OK_MIN_DB = 6.0
CREST_OK_MAX_DB = 18.0

#: JSON-safe floor for a band that carries no energy (the true value is
#: −∞ — the report rides the ``X-Mix-Result`` header).
_BAND_RATIO_FLOOR_DB = -60.0
#: Butterworth order of the spectral bandpasses (same choice as
#: ``dimension.py``).
_QC_FILTER_ORDER = 2

#: The informational contract, spelled out in every report.
_QC_NOTE = (
    "informational QC — flags never block rendering "
    "(human decision, plan maestro paso 07)"
)

#: Low-level listen derivation, spelled out in every report.
_LOW_LEVEL_NOTE = (
    "the plan's 'escucha a nivel bajo' is a perceptual listen at low SPL "
    "(human); the measurable proxies reported here are the crest factor "
    "(6–18 dB calibrated window: below 6 dB = over-smooth → low-level mud; "
    "above 18 dB = too dynamic → quiet parts vanish) and the share of "
    "samples above a −40 dBFS gate relative to the bus peak"
)


def _band_energy_ratio_db(
    audio: np.ndarray, sr: int, band_hz: tuple[float, float]
) -> float:
    """Relative band energy ``10·log10(E_band / E_total)`` in dB.

    A 2nd-order Butterworth bandpass (``butter``/``sosfilt``, same
    family as ``dimension.py``) filters both channels; energies are
    summed over the whole array in float64. Silent bus → the JSON-safe
    floor; a pure tone inside the band reads ≈ 0 dB, outside ≈ floor.
    Returns dB ∈ [floor, 0].
    """
    x = np.asarray(audio)
    if x.size == 0:
        return _BAND_RATIO_FLOOR_DB
    low, high = band_hz
    sos = butter(
        _QC_FILTER_ORDER, [low, high], btype="bandpass", fs=sr, output="sos"
    )
    filtered = sosfilt(sos, x, axis=-1)
    total = float(np.sum(np.square(x.astype(np.float64))))
    if total <= 0.0:
        return _BAND_RATIO_FLOOR_DB
    band = float(np.sum(np.square(filtered.astype(np.float64))))
    if band <= 0.0:
        return _BAND_RATIO_FLOOR_DB
    ratio_db = float(10.0 * np.log10(band / total))
    return max(_BAND_RATIO_FLOOR_DB, min(0.0, ratio_db))


def _check_band(
    audio: np.ndarray, sr: int, band_hz: tuple[float, float], flag_db: float,
) -> dict[str, Any]:
    """One spectral flag: ``{"ok", "details"}`` with the documented band."""
    ratio_db = _band_energy_ratio_db(audio, sr, band_hz)
    return {
        "ok": bool(ratio_db < flag_db),
        "details": {
            "band_hz": list(band_hz),
            "band_ratio_db": round(ratio_db, 2),
            "flag_threshold_db": flag_db,
        },
    }


def _crest_db(audio: np.ndarray) -> float:
    """Crest factor ``20·log10(peak / rms)`` in dB (0.0 for silence)."""
    x = np.asarray(audio)
    if x.size == 0:
        return 0.0
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(np.square(x.astype(np.float64)))))
    if peak <= 0.0 or rms <= 0.0:
        return 0.0
    return float(20.0 * np.log10(peak / rms))


def _low_level_activity_ratio(audio: np.ndarray, gate_db: float) -> float:
    """Share of samples above ``gate_db`` relative to the bus peak.

    1.0 for silence (nothing to measure → vacuous full activity); a
    sparse transient-only bus scores low — its quiet parts fall below
    the low-listen gate.
    """
    x = np.asarray(audio)
    if x.size == 0:
        return 1.0
    peak = float(np.max(np.abs(x)))
    if peak <= 0.0:
        return 1.0
    gate = peak * (10.0 ** (gate_db / 20.0))
    return float(np.mean(np.abs(x) >= gate))


def run_qc_checks(
    bus: np.ndarray, sr: int, pan_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the Paso 07 QC report on the final (post-bus-compressor) bus.

    Args:
        bus: ``(2, N)`` float32 stereo bus (mono ``(N,)`` / ``(1, N)``
            accepted — trivially centered and mono-compatible). Measured
            AFTER the bus compression stage: the QC audits what will be
            delivered.
        sr: Sample rate.
        pan_info: Optional ``pan_report`` from ``panorama.validate_positions``
            — its ``mono_check`` rides along under ``pan_stage`` for a
            full audit trail (the pan stage measured the PRE-compression
            stems; this report measures the POST-compression bus).

    Returns:
        ``{
          "mono": {"ok", "details": {"bus_loss_db", "mono_compatible",
                    "threshold_db"}},
          "phase": {"ok", "details": {"correlation", "threshold"}},
          "sibilance_5k": {"ok", "details": {"band_hz", "band_ratio_db",
                    "flag_threshold_db"}},
          "muddy_250": ..., "honky_500": ... (same band shape),
          "low_level_listen": {"ok", "details": {"crest_db", "crest_ok",
                    "crest_ok_range_db", "low_level_activity_ratio",
                    "low_level_activity_ok", "gate_db", "note"}},
          "pan_stage": {"ok", "details": {"mono_check"}},   # only with pan_info
          "summary": {"all_ok": bool, "flagged": [check names]},
          "note": str
        }`` — every float is JSON-safe (the payload rides the
        ``X-Mix-Result`` header). Flags are informational; nothing here
        raises.
    """
    x = np.asarray(bus)
    checks: dict[str, Any] = {}

    # ── Mono: the EXACT panorama helper (no duplicated measurement) ────────
    loss_db = mono_compat_loss_db(x)
    checks["mono"] = {
        "ok": bool(loss_db >= MONO_COMPAT_MIN_DB),
        "details": {
            "bus_loss_db": round(loss_db, 2),
            "mono_compatible": bool(loss_db >= MONO_COMPAT_MIN_DB),
            "threshold_db": MONO_COMPAT_MIN_DB,
        },
    }

    # ── Phase: the EXACT panorama correlation (Pearson L↔R) ────────────────
    correlation = float(measure_stereo_position(x)["correlation"])
    checks["phase"] = {
        "ok": bool(correlation >= CORRELATION_SAFETY_FLOOR),
        "details": {
            "correlation": round(correlation, 4),
            "threshold": CORRELATION_SAFETY_FLOOR,
        },
    }

    checks["sibilance_5k"] = _check_band(x, sr, SIBILANCE_BAND_HZ, SIBILANCE_FLAG_DB)
    checks["muddy_250"] = _check_band(x, sr, MUDDY_BAND_HZ, MUDDY_FLAG_DB)
    checks["honky_500"] = _check_band(x, sr, HONKY_BAND_HZ, HONKY_FLAG_DB)

    crest_db = _crest_db(x)
    activity = _low_level_activity_ratio(x, LOW_LEVEL_GATE_DB)
    # A silent bus has nothing to listen to: the crest/activity metrics
    # are vacuous (crest 0.0, activity 0.0) — the check defaults to
    # ok with the silence documented, it never "flags" silence.
    # (Silence = exact-zero peak; a DC bus has crest 0.0 yet is NOT
    # silent — peak is the unambiguous test.)
    silent = bool(x.size == 0 or not np.any(x))
    crest_ok = silent or bool(CREST_OK_MIN_DB <= crest_db <= CREST_OK_MAX_DB)
    activity_ok = silent or bool(activity >= LOW_LEVEL_ACTIVITY_MIN)
    checks["low_level_listen"] = {
        "ok": bool(crest_ok and activity_ok),
        "details": {
            "crest_db": round(crest_db, 2),
            "crest_ok": crest_ok,
            "crest_ok_range_db": [CREST_OK_MIN_DB, CREST_OK_MAX_DB],
            "low_level_activity_ratio": round(activity, 4),
            "low_level_activity_ok": activity_ok,
            "gate_db": LOW_LEVEL_GATE_DB,
            "silent": silent,
            "note": _LOW_LEVEL_NOTE,
        },
    }

    if pan_info is not None and pan_info.get("mono_check") is not None:
        pan_mono = pan_info["mono_check"]
        checks["pan_stage"] = {
            "ok": bool(pan_mono.get("mono_compatible", True)),
            "details": {"mono_check": pan_mono},
        }

    flagged = [name for name, check in checks.items() if not check["ok"]]
    checks["summary"] = {"all_ok": not flagged, "flagged": flagged}
    checks["note"] = _QC_NOTE
    return checks