"""Per-stem dynamics + mix-bus compressor (Mix Engine Paso 05).

The DAW chain (fader → pan → EQ → compresor → sends,
``VIABILIDAD_MOTOR_DE_MEZCLA.md`` línea 214) grows its COMPRESSOR stage:
Paso 05 inserts the compressor BETWEEN the Paso 02 EQ and the Paso 04
dimension/sends, and compresses the stereo bus AFTER the stem sum (plan
maestro paso 05; pipeline §4.8 "Dinámica" + §4.9 "Mix buss").

Recipes per stem (book *The Mixing Engineer's Handbook*, pág. 56–57,
quoted in ``VIABILIDAD_MOTOR_DE_MEZCLA.md``):
  * vocals → 4:1, 4–6 dB GR — transparent, the lead voice is not squashed
    ("Voz lead: 4:1, attack/release medios, 4–6 dB GR").
  * bass → ∞:1 (dbx 160X), 3–4 dB GR — the bass stays solid and immobile
    ("Bajo: ∞:1 (dbx 160X), 3–4 dB GR — bajo sólido, inmóvil"). The
    infinite ratio is implemented as ratio >= 20:1 (plan maestro: "el
    plan dice ∞" — 20:1 is the implementable floor for "hard limiting").
  * other (guitarra/acompañamiento) → 8:1–10:1 with attack/release AT
    TEMPO ("Guitarra: 8:1–10:1, attack/release a tempo") — the profile
    uses the 9:1 midpoint with beat-locked release.
  * drums → BY SPECTRAL SEGMENT ("drums por segmento espectral, recetas
    del libro por rol"; plan: kick 50–100 Hz, snare 120–240 Hz/5k, hats
    8–10 kHz). Paso 05 splits the drums stem with the EXISTING
    ``LinkwitzRiley4`` crossover (``multiband.py``, 150 Hz / 3 kHz edges)
    and compresses ONLY the kick low band (punchy recipe); the mid
    (snare body) and high (hats) bands stay bit-intact — "segmentos de
    drums procesan solo su banda" (criterio de aceptación del paso 05).

Mix bus (pág. 53–56): 2–3 dB total GR with the Jerry Finn technique —
attack as slow as possible, release as fast as possible ("los
transitorios pasan, el punch queda"; SSL bus compressor = the sound of
most 80s/90s records). ``gr_ok`` = GR ≤ 3.1 dB (3 dB recipe + 0.1 dB
measurement tolerance, documented). Tape glue (saturación) stays OPTIONAL
for a future step — NOT implemented here (plan: "glue de cinta opcional").

Breathing at tempo (pág. 55: "El compresor debe respirar a tempo", setup
con el snare): ``tempo_release_ms(bpm, divisor)`` = ``60000 / bpm /
divisor`` ms — 1/8 of the beat for the stems, 1/16 for the bus. A release
constant of 1/8 beat recovers ~95 % in ≈ 2.3× the constant (~0.29 beats
at ANY tempo), so the compressor is back to 90–100 % before the next hit
exactly as the book describes. Invalid/missing BPM → the profile's static
release, never a crash (Alex guard, same policy as the Paso 04 dimension).

Engine reuse: the profiles load into ``AdaptiveCompParams`` and run
through ``AdaptiveCompressor`` (``adaptive_comp.py`` — the engine's
program-dependent compressor: causal windowed-RMS threshold + crest-
adaptive timing + sidechain + makeup). Its crest-adaptive timing IS the
Jerry Finn rule: smooth material (low crest) maps to LONG attack — the
transients pass; percussive material (high crest) maps to SHORT attack —
the transients are caught. GR comes from the per-frame DIAGNOSTICS
(actual applied reduction, reported as positive dB).

Neutrality contract (spec 08): a ``None``/empty profile or ratio <= 1:1
returns THE SAME array object (bit-exact bypass — the backend equivalent
of a bypass). ``adaptive_comp`` returns a *copy* in ratio-1 mode, so the
same-object guarantee is enforced HERE, before the compressor is reached,
and documented.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from audiomind.processing.adaptive_comp import (
    AdaptiveCompParams,
    AdaptiveCompressor,
)
from audiomind.processing.multiband import (
    DEFAULT_CROSSOVER_HIGH_HZ,
    DEFAULT_CROSSOVER_LOW_HZ,
    LinkwitzRiley4,
)

#: Program-dependent threshold clamp (dB FS) — the roadmap clamp of the
#: adaptive compressor (``adaptive_comp.py``: ``threshold_min_db`` /
#: ``threshold_max_db``), reused verbatim so every stem profile obeys the
#: engine's threshold envelope.
PROFILE_THRESHOLD_MIN_DB = -30.0
PROFILE_THRESHOLD_MAX_DB = -4.0
#: Crest-detection window (ms) — the ``adaptive_comp`` default, reused.
PROFILE_CREST_WINDOW_MS = 100.0
#: Fallback detector timings when a profile omits ``attack_ms``/``release_ms``.
_FALLBACK_ATTACK_MS = 10.0
_FALLBACK_RELEASE_MS = 60.0
#: Safe clamps against out-of-range profile timings/gains (never crash —
#: same policy as ``dimension.py`` clamping delays into the engine range).
_MIN_TIME_MS = 1.0
_MAX_TIME_MS = 10000.0
_MIN_OFFSET_DB = 0.05
_MAX_OFFSET_DB = 30.0
_MAX_MAKEUP_DB = 12.0
#: Jerry Finn bus technique label (págs. 53–56) — carried in the reports.
BUS_TECHNIQUE_NOTE = "jerry_finn_slow_attack_fast_release"
#: Bus GR ceiling: 3 dB recipe ("2–3 dB totales", págs. 53–56) + 0.1 dB
#: measurement tolerance. ``gr_ok`` = GR ≤ this ceiling.
BUS_GR_MAX_DB = 3.1


def tempo_release_ms(bpm: float, beat_divisions: int) -> float:
    """Release time locked to the beat: ``60000 / bpm / beat_divisions`` ms.

    The book's "el compresor debe respirar a tempo" (pág. 55) with a
    musical floor: a release constant of 1/8 of the beat (``60000/BPM/8``
    ms) recovers ~95 % in ≈ 2.3× the constant (~0.29 beats at ANY tempo)
    — the compressor is back to 90–100 % before the next hit, whatever
    the BPM. The bus uses 1/16 of the beat (Jerry Finn's "release lo más
    rápido", págs. 53–56, with the tempo floor).

    Args:
        bpm: Tempo in beats-per-minute (must be > 0, finite).
        beat_divisions: Beat fraction divisor — 8 → 1/8 of the beat
            (stems), 16 → 1/16 of the beat (bus). Must be > 0.

    Returns:
        Release time in ms rounded to 2 decimals.

    Raises:
        ValueError: When ``bpm`` is not finite/positive or
            ``beat_divisions`` is not a positive integer.
    """
    if not (np.isfinite(bpm) and bpm > 0.0):
        raise ValueError(f"bpm must be finite and > 0, got {bpm!r}")
    if not (isinstance(beat_divisions, int) and beat_divisions > 0):
        raise ValueError(
            f"beat_divisions must be a positive integer, got {beat_divisions!r}"
        )
    return round(60000.0 / bpm / float(beat_divisions), 2)


#: Per-role stem compressor recipes (book págs. 56–57 + plan maestro paso
#: 05). ``threshold_offset_db`` is the calibrated margin BELOW the
#: program's windowed RMS at which the adaptive threshold sits; the values
#: were calibrated so steady tones (crest ≈ 3 dB, the project's synthetic
#: fixtures) land the MEAN gain reduction inside the recipe's
#: ``target_gr_db`` (verified empirically in the venv, same detector path
#: the engine ships). ``target_gr_db`` is the book range — metadata for
#: tests/reporting, the numbers each cite their source in comments.
STEM_COMPRESSOR_PROFILES: dict[str, dict[str, Any]] = {
    # ── Vocals: 4:1, 4–6 dB GR, medium attack/release (pág. 56–57: "Voz
    #    lead: 4:1, attack/release medios, 4–6 dB GR"). Transparent: the
    #    voice is never squashed. Offset 4.0 → steady-tone mean GR ≈ 4.4
    #    (probe: ratio 4, crest ≈ 3 dB).
    "vocals": {
        "ratio": 4.0,
        "target_gr_db": [4.0, 6.0],
        "threshold_offset_db": 4.0,
        "attack_ms": 12.0,   # "attack/release medios" (pág. 56–57)
        "release_ms": 90.0,
        "makeup_db": 2.0,    # safe: ≤ the GR target floor, never hotter
    },
    # ── Bass: ∞:1 (dbx 160X), 3–4 dB GR (pág. 56–57: "bajo sólido,
    #    inmóvil"). Ratio 20.0 = the implementable floor of ∞:1 (plan
    #    maestro: "el plan dice ∞"; ratio ≥ 20:1 ≈ hard limiting, pág.
    #    49). Offset 1.75 → steady-tone mean GR ≈ 3.5.
    "bass": {
        "ratio": 20.0,
        "target_gr_db": [3.0, 4.0],
        "threshold_offset_db": 1.75,
        "attack_ms": 18.0,   # medium-slow: the string stays solid
        "release_ms": 120.0,
        "makeup_db": 2.0,
    },
    # ── Other (guitarra/acompañamiento): 8:1–10:1 AT TEMPO (pág. 56–57:
    #    "Guitarra: 8:1–10:1, attack/release a tempo") — 9:1 midpoint,
    #    release locked to 1/8 of the beat (pág. 55). Offset 5.5 →
    #    steady-tone mean GR ≈ 6.5 (recipe envelope 6–9 dB).
    "other": {
        "ratio": 9.0,
        "target_gr_db": [6.0, 9.0],
        "threshold_offset_db": 5.5,
        "attack_ms": 10.0,
        "release_ms": 60.0,
        "release_beat_divisor": 8,  # 1/8 del beat (60000/BPM/8 ms)
        "makeup_db": 1.5,
    },
    # ── Drums: BY SPECTRAL SEGMENT (plan maestro: kick 50–100,
    #    snare 120–240/5k, hats 8–10k — "segmentos de drums procesan solo
    #    su banda"). The LR4 150 Hz / 3 kHz edges (``multiband.py``
    #    defaults) approximate the segments: low ≈ kick body 50–100 Hz,
    #    mid ≈ snare body 120–240 Hz (the 120 Hz edge sits slightly below
    #    the 150 Hz corner — straddle accepted and documented), high ≈
    #    hats 8–10 kHz. Paso 05 compresses ONLY the low band (punchy kick
    #    recipe); mid/high stay at ratio 1:1 — INTACT (snare/hats
    #    treatment is out of this step's scope). Slow-ish attack on the
    #    kick so the transient passes (Jerry Finn rule applied to the
    #    kick, págs. 53–56).
    "drums": {
        "band": "low",
        "crossover_low_hz": DEFAULT_CROSSOVER_LOW_HZ,   # 150 Hz
        "crossover_high_hz": DEFAULT_CROSSOVER_HIGH_HZ,  # 3 kHz
        "band_compressor": {
            "ratio": 4.0,
            "target_gr_db": [3.0, 7.0],
            "threshold_offset_db": 4.0,
            "attack_ms": 15.0,
            "release_ms": 60.0,
            "release_beat_divisor": 8,  # breathing at tempo (pág. 55)
            "makeup_db": 2.0,
        },
        # Other bands: ratio 1:1 → transparent (no gain path, intact).
    },
}

#: Mix-bus compressor profile — Jerry Finn technique (págs. 53–56):
#: 2–3 dB total GR, attack as slow as possible, release as fast as
#: possible ("los transitorios pasan, el punch queda"). Ratio 2:1 (the
#: classic glue); release locked to 1/16 of the beat (fastest, with the
#: pág. 55 tempo floor). Offset 2.5 → the hot 2-tone fixture lands the
#: mean GR ≈ 2.7 (probe, same detector path). Makeup +1 dB: safe glue,
#: the bus stays close to its pre-compression level.
BUS_COMPRESSOR_PROFILE: dict[str, Any] = {
    "ratio": 2.0,
    "target_gr_db": [2.0, 3.0],
    "threshold_offset_db": 2.5,
    "attack_ms": 30.0,   # slow: the transients pass (Jerry Finn)
    "release_ms": 60.0,
    "release_beat_divisor": 16,  # 1/16 del beat (60000/BPM/16 ms)
    "makeup_db": 1.0,
}


def _nominal_times(
    profile: dict[str, Any], bpm: float | None,
) -> tuple[float, float]:
    """(attack, release) of a profile: tempo override on the release when
    ``release_beat_divisor`` is set AND the BPM is valid; otherwise the
    profile's static values. Alex guard: invalid BPM (None/≤ 0/NaN) →
    static release, never a crash (dimension-style policy)."""
    attack = float(profile.get("attack_ms", _FALLBACK_ATTACK_MS))
    release = float(profile.get("release_ms", _FALLBACK_RELEASE_MS))
    divisor = profile.get("release_beat_divisor")
    valid_bpm = bpm is not None and np.isfinite(float(bpm)) and float(bpm) > 0.0
    if divisor is not None and valid_bpm and bpm is not None:
        release = tempo_release_ms(float(bpm), int(divisor))
    # Safe clamps: the engine validates attack/release > 0 (never crash).
    return (
        float(np.clip(attack, _MIN_TIME_MS, _MAX_TIME_MS)),
        float(np.clip(release, _MIN_TIME_MS, _MAX_TIME_MS)),
    )


def _params_from_profile(
    profile: dict[str, Any], bpm: float | None,
) -> AdaptiveCompParams:
    """Load a recipe profile into the engine's ``AdaptiveCompParams``
    (``adaptive_comp.py``: program-dependent windowed-RMS threshold +
    crest-adaptive timing + makeup — the shared detector/envelope
    family, documented). Assumes the profile is ENGAGED (ratio > 1)."""
    attack, release = _nominal_times(profile, bpm)
    offset = float(np.clip(profile.get("threshold_offset_db", 6.0),
                           _MIN_OFFSET_DB, _MAX_OFFSET_DB))
    makeup = float(np.clip(profile.get("makeup_db", 0.0), 0.0, _MAX_MAKEUP_DB))
    return AdaptiveCompParams(
        threshold_offset_db=offset,
        threshold_min_db=PROFILE_THRESHOLD_MIN_DB,
        threshold_max_db=PROFILE_THRESHOLD_MAX_DB,
        ratio=float(profile.get("ratio", 1.0)),
        attack_ms=attack,
        release_ms=release,
        crest_window_ms=PROFILE_CREST_WINDOW_MS,
        makeup_db=makeup,
    )


def _neutral_report(
    ratio: float, attack_ms: float | None, release_ms: float | None,
) -> dict[str, Any]:
    """Report of a bit-exact bypass: zero GR, neutral status, and the
    nominal timings the profile would have used (None when the profile
    carries none)."""
    return {
        "gr_db": 0.0,
        "ratio": ratio,
        "status": "neutral",
        "attack_ms": attack_ms,
        "release_ms": release_ms,
        "makeup_db": 0.0,
    }


def _applied_report(
    diag: dict[str, Any], params: AdaptiveCompParams,
) -> dict[str, Any]:
    """Report of an engaged pass: the ACTUAL mean gain reduction from the
    per-frame diagnostics (positive dB, the recipe language) plus the
    nominal timings."""
    return {
        "gr_db": round(abs(float(diag["mean_gr_db"])), 2),
        "ratio": params.ratio,
        "status": "applied",
        "attack_ms": params.attack_ms,
        "release_ms": params.release_ms,
        "makeup_db": params.makeup_db,
    }


def _profile_ratio(
    profile: dict[str, Any], band_params: dict[str, Any] | None = None,
) -> float:
    """Effective ratio of a profile: the band compressor's for drums,
    the plain ``ratio`` otherwise (1.0 when absent → neutral)."""
    src = band_params if band_params is not None else profile
    return float(src.get("ratio", 1.0))


def _apply_drum_band_compression(
    audio: np.ndarray, sr: int, profile: dict[str, Any], bpm: float | None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Drums path: split with the existing ``LinkwitzRiley4`` (150 Hz /
    3 kHz edges), compress ONLY the requested band, recompose.

    The other bands are NOT passed through any gain path — they are the
    LR4 band-splits of the input, recombined verbatim ("segmentos de
    drums procesan solo su banda"; plan maestro). A neutral band
    compressor (ratio ≤ 1:1) is a bit-exact bypass (same object)."""
    band = str(profile.get("band", "low"))
    if band not in ("low", "mid", "high"):
        raise ValueError(
            f"drums profile band must be 'low'|'mid'|'high', got {band!r}"
        )
    band_idx = {"low": 0, "mid": 1, "high": 2}[band]
    band_cfg = profile.get("band_compressor") or {}
    ratio = _profile_ratio(profile, band_cfg)
    attack, release = _nominal_times(band_cfg, bpm)
    if ratio <= 1.0:
        return audio, _neutral_report(ratio, attack, release)

    params = _params_from_profile(band_cfg, bpm)
    x = np.asarray(audio)
    work = x.astype(np.float64)
    crossover = LinkwitzRiley4(
        sr,
        float(profile.get("crossover_low_hz", DEFAULT_CROSSOVER_LOW_HZ)),
        float(profile.get("crossover_high_hz", DEFAULT_CROSSOVER_HIGH_HZ)),
    )
    bands = crossover.split(work)
    comp, diag = AdaptiveCompressor(sr, params).process_with_diagnostics(
        bands[band_idx]
    )
    bands[band_idx] = comp
    out = np.sum(bands, axis=0).astype(x.dtype)
    report = _applied_report(diag, params)
    report["band"] = band
    return out, report


def apply_stem_compression(
    audio: np.ndarray, sr: int, profile: dict[str, Any] | None,
    bpm: float | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply the per-stem compressor recipe to one stem.

    Chain (per stem, AFTER the EQ, BEFORE the Paso 04 dimension/sends —
    plan maestro: fader → pan → EQ → compresor → sends): single-band
    profiles run through ``AdaptiveCompressor`` (the engine's program-
    dependent compressor, ``adaptive_comp.py``); drums profiles split the
    stem with ``LinkwitzRiley4`` (``multiband.py``) and compress ONLY the
    configured spectral band, leaving the rest bit-intact.

    Args:
        audio: ``(channels, samples)`` float audio (stereo or mono).
        sr: Sample rate.
        profile: One recipe dict. ``None``/empty/ratio ≤ 1:1 → NEUTRAL:
            the SAME array object is returned (bit-exact bypass). A drums
            profile carries ``band`` + ``band_compressor`` (+ optional
            ``crossover_*_hz``); any other profile is a plain compressor.
        bpm: Tempo of the source for the beat-locked release (pág. 55:
            "el compresor debe respirar a tempo"). Invalid (None/≤ 0/NaN)
            → the profile's static release, never a crash (Alex guard).

    Returns:
        ``(audio_or_same, report)``. Neutral paths return THE SAME array
        object; engaged paths return a new array with input shape/dtype
        preserved.

        ``report``: ``{"gr_db": float (positive dB, actual mean
        reduction), "ratio": float, "status": "applied"|"neutral",
        "attack_ms": float, "release_ms": float, "makeup_db": float}`` —
        drums engaged reports additionally carry ``"band":
        "low"|"mid"|"high"`` (the processed segment).
    """
    if profile is None or not profile:
        return audio, _neutral_report(1.0, None, None)
    if "band" in profile:
        return _apply_drum_band_compression(audio, sr, profile, bpm)

    ratio = _profile_ratio(profile)
    attack, release = _nominal_times(profile, bpm)
    if ratio <= 1.0:
        return audio, _neutral_report(ratio, attack, release)

    params = _params_from_profile(profile, bpm)
    out, diag = AdaptiveCompressor(sr, params).process_with_diagnostics(audio)
    return out, _applied_report(diag, params)


def apply_bus_compression(
    bus: np.ndarray, sr: int, bpm: float | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Jerry Finn mix-bus compressor (págs. 53–56): 2–3 dB total GR,
    attack as slow as possible, release as fast as possible.

    Runs AFTER the stem sum (the "2-bus"; plan §4.9). The profile's
    release locks to 1/16 of the beat when a valid BPM is available
    (pág. 55 breathing + Jerry Finn's fastest release); invalid BPM →
    static release, never a crash (Alex guard). A silent/empty bus is a
    bit-exact no-op (same object).

    Args:
        bus: ``(channels, samples)`` float stereo bus.
        sr: Sample rate.
        bpm: Tempo of the source for the beat-locked release.

    Returns:
        ``(bus_or_same, report)`` with
        ``{"gr_db": float (positive dB, actual mean reduction), "gr_ok":
        bool (GR ≤ ``BUS_GR_MAX_DB`` = 3.1 dB — 3 dB recipe + 0.1 dB
        measurement tolerance), "technique":
        "jerry_finn_slow_attack_fast_release", "ratio": float,
        "attack_ms": float, "release_ms": float}``.
    """
    x = np.asarray(bus)
    if x.size == 0 or not np.any(x):
        attack, release = _nominal_times(BUS_COMPRESSOR_PROFILE, bpm)
        return bus, {
            "gr_db": 0.0,
            "gr_ok": True,
            "technique": BUS_TECHNIQUE_NOTE,
            "ratio": float(BUS_COMPRESSOR_PROFILE.get("ratio", 1.0)),
            "attack_ms": attack,
            "release_ms": release,
        }

    params = _params_from_profile(BUS_COMPRESSOR_PROFILE, bpm)
    out, diag = AdaptiveCompressor(sr, params).process_with_diagnostics(x)
    gr_db = round(abs(float(diag["mean_gr_db"])), 2)
    return out, {
        "gr_db": gr_db,
        "gr_ok": bool(gr_db <= BUS_GR_MAX_DB),
        "technique": BUS_TECHNIQUE_NOTE,
        "ratio": params.ratio,
        "attack_ms": params.attack_ms,
        "release_ms": params.release_ms,
    }