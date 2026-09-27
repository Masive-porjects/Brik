"""Tempo-locked dimension (Mix Engine Paso 04) — delay + reverb per stem.

The DAW chain (fader → pan → EQ → compresor → sends,
``VIABILIDAD_MOTOR_DE_MEZCLA.md`` línea 214) grows its SENDS stage: a
tempo-locked delay and a Schroeder reverb, applied AFTER the Paso 02 EQ
and BEFORE the bus pad/sum. The compressor is NOT part of this step: it
arrives in Paso 05, inserted before the sends.

Tempo delays (book, *The Mixing Engineer's Handbook*): ``60000 / BPM`` is
the quarter note in ms (págs. 39–40); dotted ×1.5, triplet ×0.667, half
×2, eighth ÷2, sixteenth ÷4 (table reference in the apéndice, págs.
216–217). "Si los delays están a tempo, agregan profundidad sin notarse"
(pág. 38). ``tempo_delay_table`` sweeps BPM 60–160 as the reference.

Reverb per stem (``reverb.py`` Schroeder: 4 comb + 2 allpass, mix-0
neutral = bit-exact): decay time per layering, ``size`` mapping as
documented in ``reverb.py`` (0.1 → small room, 1.0 → huge hall). The
PRE-DELAY separates the source from the reverb (pág. 214) and the early
reflections stay under 40 ms (Swedien, pág. 39) — every profile in
``DIMENSION_PROFILES`` carries a pre-delay in (0, 40) ms. The RETURN EQ
shapes the wet signal by layering role (págs. 37–38): bright stands out,
dark blends in; the LONGEST reverb is the BRIGHTEST and the SHORTEST is
the DARKEST; dense content (drums) cuts low end out of the effect.

ALEX GUARD (tempo): the BPM comes from the analyzer path
(``librosa.beat.beat_track``, the same measurement ``analysis/analyzer.py``
uses). Dimension is applied ONLY when a valid tempo exists (``bpm > 0``):
an invalid/missing tempo (None, ≤ 0, unmeasurable file) turns the whole
stage into a bit-exact neutral no-op reported as ``no_tempo`` — never a
crash.

Neutrality contract (spec 08): a profile with ``mix == 0.0`` (delay AND
reverb), an empty profile, or an invalid tempo return THE SAME array
object — bit-exact passthrough, the backend equivalent of a bypass
(same policy as ``delay.py``/``reverb.py``).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.signal import butter, sosfilt

from audiomind.processing.delay import (
    MAX_DELAY_MS,
    MIN_DELAY_MS,
    DelayParams,
    delay_pass,
)
from audiomind.processing.reverb import ReverbParams, reverb_pass

#: Subdivision → quarter-note multiplier (book págs. 39–40 + apéndice
#: págs. 216–217: dotted ×1.5, triplet ×0.667, others by halves).
SUBDIVISION_MULTIPLIERS: dict[str, float] = {
    "half": 2.0,
    "quarter": 1.0,
    "eighth": 0.5,
    "sixteenth": 0.25,
    "dotted_quarter": 1.5,
    "triplet_quarter": 0.667,
}

#: Book apéndice reference sweep (págs. 216–217) — defaults of the table.
BPM_REFERENCE_MIN = 60
BPM_REFERENCE_MAX = 160

#: Return-EQ voicings (book págs. 37–38): bright = stands out (lead), dark
#: = blends in (bed). The longest reverb is brightest, the shortest is
#: darkest (layering).
RETURN_EQ_BRIGHT = "bright"
RETURN_EQ_DARK = "dark"
RETURN_EQ_NEUTRAL = "neutral"
#: Approximate +3 dB shelf: the dry signal plus ``BRIGHT_GAIN`` × the
#: 10 kHz highpass energy above the shelf corner. ``10**(3/20) − 1``.
BRIGHT_GAIN = 0.4125
#: Shelf/HP corner for the bright voicing (shelf ~8–12 kHz, +3 dB approx).
BRIGHT_HP_HZ = 10000.0
#: Dark voicing corner: LP < 6 kHz approx ("oscuro = se funde", pág. 37–38).
DARK_LP_HZ = 6000.0
#: Butterworth order of the explicit HP/LP return cuts (gentle, musical
#: slopes; scipy ``butter``/``sosfilt`` — same choice as
#: ``processing/mono.py``).
RETURN_EQ_ORDER = 2
#: Order of the BRIGHT shelf highpass: order 1 on purpose — above the
#: corner the phase aligns fast enough for the dry+gain mix to actually
#: BOOST the 8–12 kHz band (order 2 sums nearly in quadrature at the
#: corner: the boost collapses to ~0.4 dB there). The shelf approximates
#: +3 dB with an asymptote toward the top; measured in-band ~+2 dB.
BRIGHT_SHELF_ORDER = 1


def tempo_delay_ms(bpm: float, subdivision: str) -> float:
    """Quarter-note based delay time for a BPM + subdivision (in ms).

    ``60000 / BPM`` is the quarter note (book págs. 39–40); the
    subdivision multiplier follows the apéndice table (págs. 216–217):
    ``half`` ×2, ``dotted_quarter`` ×1.5, ``quarter`` ×1, ``eighth`` ×0.5,
    ``sixteenth`` ×0.25, ``triplet_quarter`` ×0.667. Rounded to 2
    decimals.

    Args:
        bpm: Tempo in beats-per-minute (must be > 0).
        subdivision: One of ``SUBDIVISION_MULTIPLIERS``.

    Returns:
        Delay time in ms.

    Raises:
        ValueError: When ``bpm <= 0`` or the subdivision is unknown.
    """
    if not (np.isfinite(bpm) and bpm > 0.0):
        raise ValueError(f"bpm must be finite and > 0, got {bpm!r}")
    if subdivision not in SUBDIVISION_MULTIPLIERS:
        raise ValueError(
            f"unknown subdivision {subdivision!r}; expected one of "
            f"{sorted(SUBDIVISION_MULTIPLIERS)}"
        )
    return round(60000.0 / bpm * SUBDIVISION_MULTIPLIERS[subdivision], 2)


def tempo_delay_table(
    bpm_min: int = BPM_REFERENCE_MIN, bpm_max: int = BPM_REFERENCE_MAX,
) -> dict[int, dict[str, float]]:
    """Reference BPM sweep (book apéndice págs. 216–217).

    Maps every BPM in ``[bpm_min, bpm_max]`` to its subdivision delay
    times in ms (rounded to 2 decimals) — the table tests validate ±1 ms.

    Args:
        bpm_min: First BPM of the sweep (default 60).
        bpm_max: Last BPM of the sweep (inclusive, default 160).
    """
    return {
        bpm: {sub: tempo_delay_ms(float(bpm), sub) for sub in SUBDIVISION_MULTIPLIERS}
        for bpm in range(int(bpm_min), int(bpm_max) + 1)
    }


#: Per-role dimension profiles (book págs. 37–40, 214; Swedien pág. 39).
#: Each stem: ``reverb`` (size/mix/pre_delay_ms/return_eq/hp_hz/lp_hz)
#: + ``delay`` (subdivision/feedback/mix). ``size`` maps through
#: ``reverb.py``: 0.1 → small room, 1.0 → huge hall (~1.7 s tail).
DIMENSION_PROFILES: dict[str, dict[str, Any]] = {
    # ── Vocals: the LONGEST, brightest reverb — the lead voice stands in
    #    its own space (etéreo) and STANDS OUT (pág. 37–38: brillante =
    #    destaca; longest → brightest). Pre-delay 30 ms separates the
    #    voice from the tail (pág. 214) inside the < 40 ms early-reflection
    #    budget (Swedien pág. 39). Quarter-note delay at tempo pulses the
    #    echo in the beat grid (págs. 39–40).
    "vocals": {
        "reverb": {
            "size": 0.85,
            "mix": 0.25,
            "pre_delay_ms": 30.0,
            "return_eq": RETURN_EQ_BRIGHT,
            "hp_hz": None,
            "lp_hz": None,
        },
        "delay": {
            "subdivision": "quarter",
            "feedback": 0.35,
            "mix": 0.18,
        },
    },
    # ── Drums: MEDIUM reverb with the low end CUT OUT OF THE RETURN —
    #    the dense kit does not need lows in the effect (pág. 37–38:
    #    "mucho contenido → cortar graves del efecto"; HP 150–200).
    #    Neutral voicing: no extreme shelf on an already-busy spectrum.
    #    No tempo delay: the kit provides the pulse.
    "drums": {
        "reverb": {
            "size": 0.5,
            "mix": 0.15,
            "pre_delay_ms": 20.0,
            "return_eq": RETURN_EQ_NEUTRAL,
            "hp_hz": 180.0,
            "lp_hz": None,
        },
        "delay": {
            "subdivision": None,
            "feedback": 0.0,
            "mix": 0.0,
        },
    },
    # ── Bass: the SHORTEST, darkest reverb — conservative dimension that
    #    BLENDS IN instead of moving the center bass (pág. 37–38: oscuro =
    #    se funde; shortest → darkest). Dark LP softens the top and a low
    #    HP (90 Hz) keeps sub-rumble out of the wash. No delay: the bass
    #    already anchors the rhythm pocket.
    "bass": {
        "reverb": {
            "size": 0.3,
            "mix": 0.12,
            "pre_delay_ms": 20.0,
            "return_eq": RETURN_EQ_DARK,
            "hp_hz": 90.0,
            "lp_hz": None,
        },
        "delay": {
            "subdivision": None,
            "feedback": 0.0,
            "mix": 0.0,
        },
    },
    # ── Other: MEDIUM reverb, neutral-mid return voicing — neither
    #    extreme bright nor extreme dark (pág. 37–38); the accompaniment
    #    sits in the middle layer. Optional eighth-note delay adds motion
    #    inside the beat grid without pulling focus.
    "other": {
        "reverb": {
            "size": 0.55,
            "mix": 0.18,
            "pre_delay_ms": 20.0,
            "return_eq": RETURN_EQ_NEUTRAL,
            "hp_hz": None,
            "lp_hz": None,
        },
        "delay": {
            "subdivision": "eighth",
            "feedback": 0.25,
            "mix": 0.12,
        },
    },
}


def _butter_filter(
    audio: np.ndarray, sr: int, cutoff_hz: float, kind: str,
    order: int = RETURN_EQ_ORDER,
) -> np.ndarray:
    """One Butterworth pass (``butter``/``sosfilt``, same choice as
    ``processing/mono.py`` — vectorized per channel, axis=-1)."""
    cutoff = max(1.0, min(float(cutoff_hz), float(sr) / 2.0 - 1.0))
    sos = butter(order, cutoff, btype=kind, fs=sr, output="sos")
    return np.asarray(sosfilt(sos, audio, axis=-1))


def apply_return_eq(
    audio: np.ndarray, profile: dict[str, Any], sr: int,
) -> np.ndarray:
    """Shape the REVERB RETURN (wet signal) for the layering role.

    EQ order (documented): explicit ``hp_hz`` then ``lp_hz`` cuts first,
    then the semantic voicing — ``bright`` ≈ +3 dB shelf above 8–12 kHz
    (dry + ``BRIGHT_GAIN`` × a 10 kHz highpass, pág. 37–38), ``dark`` =
    LP < 6 kHz approx. Implemented with ``scipy.signal`` Butterworth
    filters (same as ``processing/mono.py``) instead of pedalboard: the
    return path needs 2–3 cheap poles per stem.

    Neutrality contract: no cuts and a ``neutral`` voicing return the
    INPUT ARRAY UNTOUCHED (same object — bit-exact bypass); engaged
    passes run in float64 and land back in the input dtype.
    """
    reverb_cfg = profile.get("reverb") or {}
    eq = str(reverb_cfg.get("return_eq", RETURN_EQ_NEUTRAL))
    hp_hz = reverb_cfg.get("hp_hz")
    lp_hz = reverb_cfg.get("lp_hz")
    if eq == RETURN_EQ_NEUTRAL and hp_hz is None and lp_hz is None:
        return audio  # same object — bit-exact bypass

    x = np.asarray(audio)
    work = x.astype(np.float64)
    if hp_hz is not None:
        work = _butter_filter(work, sr, float(hp_hz), "highpass")
    if lp_hz is not None:
        work = _butter_filter(work, sr, float(lp_hz), "lowpass")
    if eq == RETURN_EQ_BRIGHT:
        # Approximate high shelf: dry + g·HP(10 kHz) — ~+2 dB in the
        # 8–12 kHz band, +3 dB asymptote at the top (pág. 37–38:
        # brillante = destaca). Order-1 HP keeps the sum in phase.
        highs = _butter_filter(
            work, sr, BRIGHT_HP_HZ, "highpass", order=BRIGHT_SHELF_ORDER
        )
        work = work + BRIGHT_GAIN * highs
    elif eq == RETURN_EQ_DARK:
        # Dark: LP < 6 kHz approx (pág. 37–38: oscuro = se funde).
        work = _butter_filter(work, sr, DARK_LP_HZ, "lowpass")
    return work.astype(x.dtype)


def apply_stem_dimension(
    audio: np.ndarray, sr: int, bpm: float | None, profile: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply the tempo dimension (delay + reverb with pre-delay and return
    EQ) to one stem, reporting exactly what was engaged.

    Chain (per stem, AFTER the EQ, BEFORE the bus pad/sum):
    ``delay`` (tempo subdivision → ``delay.py`` circular buffer) →
    ``reverb`` (``reverb.py`` Schroeder, mix-0 neutral) with a PRE-DELAY
    that shifts the reverb input (pág. 214) and the RETURN EQ applied to
    the WET only (págs. 37–38) — the dry path is never re-EQ'd.

    Args:
        audio: ``(channels, samples)`` float audio (stereo or mono).
        sr: Sample rate.
        bpm: Tempo of the source (Alex guard: dimension only applies with
            a valid tempo). ``None`` or ``<= 0`` → neutral no-op reported
            ``no_tempo``, never a crash.
        profile: One ``DIMENSION_PROFILES`` entry (``reverb``/``delay``).
            Empty profile or all-``mix``-0 → neutral no-op.

    Returns:
        ``(audio_or_processed, report)``. The neutral paths return THE
        SAME array object (bit-exact). Engaged paths return a new array
        with input shape/dtype preserved.

        ``report``:
        ``{"delay_ms": float|None, "reverb_size": float|None,
        "pre_delay_ms": float|None, "return_eq": str, "applied": bool}``
        — all ``None`` when that stage did not engage. With an invalid
        tempo the report is the ``no_tempo`` shape: ``{"bpm_used": None,
        "applied": False, "reason": "no_tempo"}``.
    """
    no_tempo_report: dict[str, Any] = {
        "bpm_used": None,
        "applied": False,
        "reason": "no_tempo",
    }
    if bpm is None or bpm <= 0.0 or not np.isfinite(float(bpm)):
        return audio, no_tempo_report

    reverb_cfg = profile.get("reverb") or {}
    delay_cfg = profile.get("delay") or {}

    delay_mix = float(delay_cfg.get("mix", 0.0))
    subdivision = delay_cfg.get("subdivision")
    delay_ms: float | None = None
    shaped = audio

    # ── Tempo delay on the source (60000/BPM, book págs. 39–40) ────────
    if subdivision is not None and delay_mix > 0.0:
        raw_ms = tempo_delay_ms(float(bpm), str(subdivision))
        # Safety clamp for out-of-table tempos: DelayParams would reject
        # anything outside [MIN_DELAY_MS, MAX_DELAY_MS] (never crash).
        delay_ms = float(np.clip(raw_ms, MIN_DELAY_MS, MAX_DELAY_MS))
        shaped = delay_pass(
            shaped,
            sr,
            DelayParams(
                time_ms=delay_ms,
                mix=delay_mix,
                feedback=float(delay_cfg.get("feedback", 0.0)),
            ),
        )

# ── Reverb return: pre-delay (pág. 214) → Schroeder (reverb.py) →
    #    return EQ on the wet (págs. 37–38) ──────────────────────────────
    reverb_mix = float(reverb_cfg.get("mix", 0.0))
    size = reverb_cfg.get("size")
    pre_delay_ms: float | None = None
    reverb_size: float | None = None
    if reverb_mix > 0.0 and size is not None:
        reverb_size = float(size)
        pre_delay = float(reverb_cfg.get("pre_delay_ms") or 0.0)
        if pre_delay > 0.0:
            pre_delay = float(np.clip(pre_delay, MIN_DELAY_MS, MAX_DELAY_MS))
            pre_delay_ms = pre_delay
            # mix=1.0 + feedback=0.0 → pure single-repeat delay: the
            # reverb input starts pre_delay ms after the direct sound.
            shaped = delay_pass(
                shaped,
                sr,
                DelayParams(time_ms=pre_delay, mix=1.0, feedback=0.0),
            )
        wet = reverb_pass(
            shaped, sr, ReverbParams(mix=1.0, size=reverb_size)
        )
        wet = apply_return_eq(wet, profile, sr)
        shaped = (shaped * (1.0 - reverb_mix) + wet * reverb_mix).astype(
            np.asarray(audio).dtype
        )

    return_eq = str(reverb_cfg.get("return_eq", RETURN_EQ_NEUTRAL))
    applied = delay_ms is not None or reverb_size is not None
    return shaped, {
        "delay_ms": delay_ms,
        "reverb_size": reverb_size,
        "pre_delay_ms": pre_delay_ms,
        "return_eq": return_eq,
        "applied": applied,
    }