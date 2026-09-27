"""Adaptive vocal treatment by measured register (Eje A, entregable 2).

Feature: ``odd/tasks/voz-tratamiento-adaptativo.md`` — consumes the Eje B
measurement (``analysis/register_detection.py`` via
``AnalysisResult.vocal_register`` / ``vocal_median_f0_hz``) and treats the
vocal stem ADAPTIVELY to that register: per-register presence/sibilance EQ,
an optional LP for the ``agudo`` class and an OPTIONAL dimension (reverb)
refinement of the existing Paso 04 stage — never a second reverb.

Product restriction (``PROPUESTA_VOZ_ETEREA_VINTAGE_MOJADA.md``): the
treatment is adaptive by NECESSITY of the signal, optional (the master's
neutral/bypass chain is untouched — ``build_mix(vocal_treatment=False)``
never runs any of this), transparent (the report says QUÉ se aplicó and
which register drove it, in Spanish neutral) and master-safe (every value
stays inside the engine's validated ranges).

Honesty rules:
- No credible voice (``register is None``) or a label the classifier never
  emits → neutral ``no_voice`` plan: the backend NEVER invents a register.
- Every value without a source is a marked HIPÓTESIS; the continuous knobs
  (presence gain, LP corner) DERIVE from the measured median f0 by the
  documented hypothesis formulas below — calibrate with real material.
- The ``why`` text is product microcopy: Spanish neutral (no voseo).
"""

from __future__ import annotations

from typing import Any

import numpy as np

from audiomind.processing.magic_frequencies import apply_stem_eq

#: Registers the classifier emits (Eje B ``classify_register``). Anything
#: else resolves to the neutral ``no_voice`` plan (Alex guard).
VALID_REGISTERS: tuple[str, ...] = ("grave", "medio", "agudo")

#: Per-register refinement of the EXISTING Paso 04 dimension profile —
#: knobs only (HIPÓTESIS, calibrar con material real): the genre owns the
#: direction (Paso 06), the register fine-tunes the vocal reverb AFTER it
#: (propuesta §2.3). ``medio`` carries no shift (base preserved — the
#: honest default); the tempo delay never moves (genre owns it).
#: Pre-delays stay inside the < 40 ms early-reflection budget (Swedien).
REGISTER_DIMENSION_ADJUSTMENTS: dict[str, dict[str, Any]] = {
    "grave": {
        "size_mult": 0.8,      # HIPÓTESIS: shorter space, the voice is heavy
        "mix_mult": 0.9,       # HIPÓTESIS: a touch drier so lows don't mud
        "pre_delay_ms": 25.0,  # HIPÓTESIS: tighter source/tail separation
        "return_eq": "dark",   # HIPÓTESIS: dark = blends in (book pág. 37–38)
    },
    "medio": {},  # base preserved — no invented movement
    "agudo": {
        "pre_delay_ms": 35.0,  # HIPÓTESIS: more air between source and tail
        "return_eq": "dark",   # HIPÓTESIS: tame the wet layer of a bright voice
    },
}

#: Presence band per register (HIPÓTESIS): center freq and base gain. The
#: final gain DERIVES from the measured median f0 by
#: ``gain = base + (220 − f0) / 220`` clamped to [0.5, 3.0] dB — a deeper
#: measured voice gets a larger presence lift inside a sane envelope.
_PRESENCE_BASE_DB: dict[str, float] = {"grave": 1.5, "medio": 1.0, "agudo": 0.5}
_PRESENCE_FREQ_HZ: dict[str, float] = {
    "grave": 3500.0, "medio": 4000.0, "agudo": 3000.0,
}
_PRESENCE_GAIN_MIN_DB = 0.5
_PRESENCE_GAIN_MAX_DB = 3.0
#: Reference f0 of the presence formula (HIPÓTESIS ~median male voice).
_PRESENCE_F0_REFERENCE_HZ = 220.0

#: Sibilance cut per register (HIPÓTESIS): a brighter measured voice gets
#: the stronger cut (7k region), Q 2.5 stays musical on a peak.
_SIBILANCE_CUT_DB: dict[str, float] = {
    "grave": -1.0, "medio": -1.5, "agudo": -2.5,
}
_SIBILANCE_FREQ_HZ: dict[str, float] = {
    "grave": 7200.0, "medio": 7200.0, "agudo": 7000.0,
}
_SIBILANCE_Q = 2.5

#: Agudo LP corner: ``clip(f0 × 52, 11000, 15000)`` (HIPÓTESIS) — tracks the
#: measured median f0, tames the top of a bright voice, never eats the
#: presence band. Declared for every class (T1) but engaged for ``agudo``.
_AGUDO_LP_SLOPE = 52.0
_AGUDO_LP_MIN_HZ = 11000.0
_AGUDO_LP_MAX_HZ = 15000.0

#: Engine validation ranges the register refinement must never leave
#: (sourced: ``reverb.py`` mix [0, 1] / size [0.1, 1.0]; Swedien < 40 ms).
_REVERB_MIX_MIN, _REVERB_MIX_MAX = 0.0, 1.0
_REVERB_SIZE_MIN, _REVERB_SIZE_MAX = 0.1, 1.0
_PRE_DELAY_MIN_MS, _PRE_DELAY_MAX_MS = 1.0, 39.0
_RETURN_EQ_VOICINGS = frozenset({"bright", "dark", "neutral"})

#: Marker every hypothesis value carries in its ``source`` / ``why``.
HYPOTHESIS_TOKEN = "HIPÓTESIS"

_NO_VOICE_WHY = (
    "Sin voz creíble en el stem vocal: sin tratamiento "
    "(el backend nunca inventa un registro)."
)


def _presence_gain_db(register: str, median_f0_hz: float | None) -> float:
    """Presence boost derived from the measured median f0 (HIPÓTESIS).

    ``gain = base[register] + (220 − f0) / 220`` clamped to
    [0.5, 3.0] dB; ``f0 is None`` keeps the class base (defensive — no
    crash, no invented derivative).
    """
    base = _PRESENCE_BASE_DB[register]
    if median_f0_hz is None:
        gain = base
    else:
        gain = base + (_PRESENCE_F0_REFERENCE_HZ - float(median_f0_hz)) / (
            _PRESENCE_F0_REFERENCE_HZ
        )
    return float(np.clip(gain, _PRESENCE_GAIN_MIN_DB, _PRESENCE_GAIN_MAX_DB))


def _agudo_lp_hz(median_f0_hz: float | None) -> float | None:
    """Agudo LP corner derived from the measured median f0 (HIPÓTESIS).

    ``clip(f0 × 52, 11000, 15000)``; ``None`` f0 → no corner (nothing to
    derive from — the class base cannot invent a frequency).
    """
    if median_f0_hz is None:
        return None
    return float(
        np.clip(
            float(median_f0_hz) * _AGUDO_LP_SLOPE,
            _AGUDO_LP_MIN_HZ,
            _AGUDO_LP_MAX_HZ,
        )
    )


def resolve_vocal_treatment(
    register: str | None, median_f0_hz: float | None,
) -> dict[str, Any]:
    """Resolve the measured register/f0 into a vocal treatment plan (T1).

    Consumes the Eje B measurement: a known register (``grave``/``medio``/
    ``agudo``) resolves into the per-register chain — presence + sibilance
    EQ, the ``agudo`` LP corner and the dimension refinement table. No
    credible voice (``None``) or a label the classifier never emits →
    neutral ``no_voice`` plan (the backend never invents a register).

    Args:
        register: ``AnalysisResult.vocal_register`` (or ``None``).
        median_f0_hz: ``AnalysisResult.vocal_median_f0_hz`` (or ``None``).

    Returns:
        ``{"status": "applied"|"no_voice", "register", "median_f0_hz",
        "eq_bands", "lp_hz", "dimension_adjustment", "hypothesis",
        "why"}`` — ``why`` is Spanish-neutral product microcopy naming
        what ran, which register drove it and that the values are a
        HIPÓTESIS.
    """
    if register not in VALID_REGISTERS:
        return {
            "status": "no_voice",
            "register": None,
            "median_f0_hz": None,
            "eq_bands": [],
            "lp_hz": None,
            "dimension_adjustment": {},
            "hypothesis": False,
            "why": _NO_VOICE_WHY,
        }

    f0 = float(median_f0_hz) if median_f0_hz is not None else None
    presence_gain = _presence_gain_db(str(register), f0)

    # Golden rule: cuts first, boosts after (``magic_frequencies`` pág. 33).
    eq_bands: list[dict[str, Any]] = [
        {
            "type": "cut",
            "freq_hz": _SIBILANCE_FREQ_HZ[str(register)],
            "gain_db": _SIBILANCE_CUT_DB[str(register)],
            "q": _SIBILANCE_Q,
            "filter": "peak",
            "source": (
                f"{HYPOTHESIS_TOKEN} — sibilancia {register} "
                "(sin fuente; calibrar con material real)"
            ),
        },
        {
            "type": "boost",
            "freq_hz": _PRESENCE_FREQ_HZ[str(register)],
            "gain_db": round(presence_gain, 2),
            "q": 0.7,
            "filter": "peak",
            "source": (
                f"{HYPOTHESIS_TOKEN} — presencia {register}, fórmula "
                "base + (220 − f0)/220 sobre la f0 mediana medida"
            ),
        },
    ]

    lp_hz = _agudo_lp_hz(f0) if register == "agudo" else None

    f0_part = (
        f" con f0 mediana {f0:.0f} Hz" if f0 is not None else ""
    )
    why = (
        f"Tratamiento vocal {register} aplicado{f0_part}: EQ de "
        "presencia/sibilancia y ajuste de dimensión por registro; "
        f"valores {HYPOTHESIS_TOKEN} a calibrar."
    )
    return {
        "status": "applied",
        "register": register,
        "median_f0_hz": f0,
        "eq_bands": eq_bands,
        "lp_hz": lp_hz,
        "dimension_adjustment": REGISTER_DIMENSION_ADJUSTMENTS[str(register)],
        "hypothesis": True,
        "why": why,
    }


def apply_vocal_treatment(
    audio: np.ndarray, sr: int, plan: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply the plan's register EQ (+ ``agudo`` LP) to the vocal stem (T3).

    The treatment stage closes the vocal chain AFTER pan → EQ → compressor
    → dimension (``mix_engine``). Neutral contract: a ``no_voice`` plan
    returns THE SAME array object (honest bypass) with ``applied=False``;
    an engaged plan returns a new array with the input shape/dtype
    preserved and a report naming what ran and why (Spanish neutral).

    Args:
        audio: ``(channels, samples)`` float vocal stem.
        sr: Sample rate.
        plan: Output of ``resolve_vocal_treatment``.

    Returns:
        ``(audio_or_processed, report)`` where ``report`` is
        ``{"status", "register", "median_f0_hz", "applied", "eq_bands",
        "lp_hz", "hypothesis", "why"}``.
    """
    report: dict[str, Any] = {
        "status": plan["status"],
        "register": plan["register"],
        "median_f0_hz": plan["median_f0_hz"],
        "applied": False,
        "eq_bands": plan["eq_bands"],
        "lp_hz": plan["lp_hz"],
        "hypothesis": plan["hypothesis"],
        "why": plan["why"],
    }
    if plan["status"] != "applied" or not plan["eq_bands"]:
        return audio, report  # same object — honest neutral bypass

    out = apply_stem_eq(audio, sr, plan["eq_bands"])
    lp_hz = plan.get("lp_hz")
    if lp_hz is not None:
        # Gentle order-2 Butterworth (same scipy choice as ``mono.py`` /
        # ``dimension.py``) — the LP only runs for the ``agudo`` class.
        from scipy.signal import butter, sosfilt

        out = np.asarray(out)
        work = out.astype(np.float64)
        sos = butter(2, float(lp_hz), btype="lowpass", fs=int(sr), output="sos")
        out = sosfilt(sos, work, axis=-1).astype(out.dtype)
    else:
        out = np.asarray(out)
        in_dtype = np.asarray(audio).dtype
        if out.dtype != in_dtype:
            out = out.astype(in_dtype)
    if out is audio:  # defensive: engaged must never be a same-object no-op
        out = audio.copy()
    report["applied"] = True
    return out, report


def apply_register_dimension(
    profile: dict[str, Any], adjustment: dict[str, Any],
) -> dict[str, Any]:
    """Refine the vocal dimension profile by register AFTER genre scaling.

    Rides on the EXISTING Paso 04 profile (no second reverb): moves ONLY
    the vocal reverb knobs the register table names — size/mix multipliers,
    an absolute pre-delay and the return voicing — and never the tempo
    delay (genre owns the delay direction, propuesta §2.3). Every value
    clamps INSIDE the engine's validated ranges (``reverb.py`` mix [0, 1],
    size [0.1, 1.0]; pre-delay < 40 ms); an unknown voicing keeps the
    profile's own value (never crash). An empty adjustment (``medio``)
    returns the base profile unchanged.

    Args:
        profile: One dimension profile (``reverb`` + ``delay``), typically
            the genre-scaled vocals entry.
        adjustment: One ``REGISTER_DIMENSION_ADJUSTMENTS`` entry.

    Returns:
        A NEW profile dict (base never mutated); ``delay`` copied verbatim.
    """
    reverb = dict(profile.get("reverb") or {})
    delay = dict(profile.get("delay") or {})
    if not adjustment:
        return {"reverb": reverb, "delay": delay}

    if "size_mult" in adjustment:
        reverb["size"] = float(np.clip(
            float(reverb.get("size", 0.5)) * float(adjustment["size_mult"]),
            _REVERB_SIZE_MIN,
            _REVERB_SIZE_MAX,
        ))
    if "mix_mult" in adjustment:
        reverb["mix"] = float(np.clip(
            float(reverb.get("mix", 0.0)) * float(adjustment["mix_mult"]),
            _REVERB_MIX_MIN,
            _REVERB_MIX_MAX,
        ))
    if "pre_delay_ms" in adjustment:
        reverb["pre_delay_ms"] = float(np.clip(
            float(adjustment["pre_delay_ms"]),
            _PRE_DELAY_MIN_MS,
            _PRE_DELAY_MAX_MS,
        ))
    wanted_eq = adjustment.get("return_eq")
    if wanted_eq in _RETURN_EQ_VOICINGS:
        reverb["return_eq"] = wanted_eq
    return {"reverb": reverb, "delay": delay}
