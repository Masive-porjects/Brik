"""Character stage (Mix Engine, P3): the texture return.

Applies the P2 primitives to the mix as *character* — the deliberate, bounded
imperfection a stylized production is built from, not a defect to be cleaned up
later. Spec: ``odd/tasks/character-integration.md``.

The profile (``commercial_alt_pop``):

* ``vocals`` — a BPM-synced slapback delay.
* ``other`` — wow/flutter, then a chorus.
* ``bass`` — parallel saturation.
* *the bus* — a hiss and crackle bed under the whole mix.

Why the bed is a BUS stage and not a stem stage
-----------------------------------------------

Measured: a naked bed has a crest factor of **29.81 dB** against a QC ceiling of
18 dB that no budget may relax. It is only safe because the program dominates the
sum — measured 6.22 dB for a clean bus against 6.35 dB with the bed at
``-48 dBFS``. A bed summed under one stem would spend the whole mix's headroom on
that stem alone.

Two compensations, because a character stage still has to stay in tune with the
band
------

* **Head spacing (wow/flutter).** The stage reads the signal through a delay of
  ``base_delay_ms + LFO``. The static part is pure latency and would misalign the
  stem against its neighbours in the mix sum. It is removed *sample-exactly*: the
  head spacing is forced to a whole number of samples and the output is read from
  that offset. Measured: removing it moves the cross-correlation lag by exactly the
  head spacing (133 → 66 samples at a 67-sample spacing), and what is left is the
  LFO, which is the effect and is deliberately *not* removed.
* **Comb loss (chorus).** A moving delay summed with its own dry signal is a comb,
  and a comb cancels as much as it adds. Measured −3.095 dB at ``mix=0.4`` and
  −3.440 dB at ``mix=0.5``. The make-up is measured per application rather than
  assumed, because the loss depends on the mix and the material.

The interpolator's high-frequency droop is measured on what survives those
compensations, and paid back with a bounded first-order shelf only when it exceeds
``HF_DROOP_MIN_DB``. Measured residual for the configured wow/flutter: **−0.164 dB**,
under the threshold, so the shelf stays off for this profile. The slapback takes a
whole-sample delay so it takes ``fractional_delay``'s direct-index path and has no
interpolation error at all (measured ``max|out - shift| = 0.0``).

Nothing here mutates its input: the mix engine's processed stems are aliased by
several consumers (``render_versions.render_version_buses`` re-sums them), so an
in-place stage would leak texture into the alternative renders.
"""

from __future__ import annotations

from typing import Any, Final

import numpy as np
from scipy.signal import butter, sosfilt

from audiomind.processing.modulation import (
    CHORUS_BASE_DELAY_MS,
    CHORUS_RATE_HZ,
    ChorusParams,
    WowFlutterParams,
    chorus_pass,
    fractional_delay,
    wow_flutter_delays,
)
from audiomind.processing.quality_checks import CREST_OK_MIN_DB, MAX_QC_RELAX_DB
from audiomind.processing.tape import TapeParams, tape_saturate
from audiomind.processing.texture import crackle, pink_hiss, stereo_bed

#: The only profile implemented. An unknown name raises (S2) — a typo is a bug,
#: not a silent no-op.
CHARACTER_PROFILE: Final[str] = "commercial_alt_pop"

#: Which stems the profile treats, and with which stages (S1). The bus bed is
#: not listed here: it is a bus stage (see the module docstring).
CHARACTER_STAGES: Final[dict[str, tuple[str, ...]]] = {
    "vocals": ("slapback",),
    "other": ("wow_flutter", "chorus"),
    "bass": ("saturation",),
}

#: Default seed for the deterministic bed. A caller-supplied seed overrides it;
#: same seed, same bed.
CHARACTER_DEFAULT_SEED: Final[int] = 20261016

# ── Slapback (vocals) ────────────────────────────────────────────────────────
#: Delay time as a share of one beat: a 16th note. At 120 BPM that is 125 ms, the
#: classic slapback; it stays in that territory from roughly 60 to 240 BPM.
SLAPBACK_BEAT_FRACTION: Final[float] = 0.25
#: The reflection is ADDED to the dry signal, not crossfaded with it: a slapback is
#: a reflection arriving after the voice, and the voice itself does not get quieter.
SLAPBACK_WET_GAIN: Final[float] = 0.35

# ── Wow/flutter (other) ──────────────────────────────────────────────────────
#: Deep enough to hear the transport move, shallow enough that the stem still sums
#: with the drums. The P2 ceiling is 2.0 ms.
WOW_FLUTTER_DEPTH_MS: Final[float] = 1.5

# ── Chorus (other) ───────────────────────────────────────────────────────────
CHORUS_DEPTH_MS: Final[float] = 4.0
CHORUS_MIX: Final[float] = 0.4
#: Bound on the comb make-up. The loudest measured case is +3.454 dB at mix 0.6;
#: anything past this bound is capped AND reported as capped, never silently.
CHORUS_MAX_MAKEUP_DB: Final[float] = 6.0

# ── Parallel saturation (bass) ───────────────────────────────────────────────
SATURATION_DRIVE_DB: Final[float] = 6.0
#: Share of the harmonic path blended onto the dry bass (New York parallel).
SATURATION_MIX: Final[float] = 0.35

# ── The bed (bus) ────────────────────────────────────────────────────────────
BED_HISS_LEVEL_DBFS: Final[float] = -48.0
BED_CRACKLE_LEVEL_DBFS: Final[float] = -54.0
BED_CRACKLE_RATE_PER_S: Final[float] = 12.0
#: Near-mono: inside ``texture.MAX_STEREO_SPREAD``, so the bed cannot walk the bus
#: out of the QC phase floor.
BED_SPREAD: Final[float] = 0.2

# ── High-frequency droop ─────────────────────────────────────────────────────
#: The band the droop is measured in — the same region the QC's sibilance check
#: watches, so the two speak about the same neighbourhood.
HF_BAND_HZ: Final[tuple[float, float]] = (4000.0, 10000.0)
HF_SHELF_HZ: Final[float] = 6000.0
#: Below this the droop is left alone: measured −0.164 dB for the configured
#: wow/flutter, so this keeps the shelf off for a negligible loss instead of
#: filtering a signal over a fifth of a decibel.
HF_DROOP_MIN_DB: Final[float] = 0.5
HF_DROOP_MAX_COMP_DB: Final[float] = 3.0

# ── The declared QC budget (S7) ──────────────────────────────────────────────
#: The bed lifts the 4–7 kHz share; this is the declared tolerance, bounded by
#: ``MAX_QC_RELAX_DB``. ``low_level_listen`` is NOT declared here: its tolerance is
#: measured from the bus the bed actually produced (``character_budget``), because
#: the bed can move the crest either way depending on how dynamic the program is.
TONE_RELAX_DB: Final[float] = 1.5
#: Provenance. ``intentional_deviations`` is only legible if it can say who asked.
BUDGET_PROVENANCE: Final[tuple[str, ...]] = ("commercial_alt_pop", "texture_bed")


def _rms(audio: np.ndarray) -> float:
    """RMS of the whole array in float64 (``0.0`` for silence)."""
    x = np.asarray(audio)
    if x.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(x.astype(np.float64)))))


def _band_energy_db(audio: np.ndarray, sr: int, band_hz: tuple[float, float]) -> float:
    """Absolute band energy in dB, floored so silence stays comparable."""
    x = np.asarray(audio)
    if x.size == 0:
        return -300.0
    low, high = band_hz
    sos = butter(2, [low, high], btype="bandpass", fs=sr, output="sos")
    filtered = sosfilt(sos, x, axis=-1)
    energy = float(np.sum(np.square(filtered.astype(np.float64))))
    return float(10.0 * np.log10(max(energy, 1e-300)))


def _level_match_db(audio: np.ndarray, reference: np.ndarray) -> float:
    """Gain in dB that brings ``audio`` to ``reference``'s RMS.

    ``0.0`` when either side is silent, so a silent input can never earn an
    infinite correction.
    """
    rms_audio = _rms(audio)
    rms_reference = _rms(reference)
    if rms_audio <= 0.0 or rms_reference <= 0.0:
        return 0.0
    return float(20.0 * np.log10(rms_reference / rms_audio))


def hf_shelf(audio: np.ndarray, sr: int, gain_db: float) -> np.ndarray:
    """First-order high shelf: the band below ``HF_SHELF_HZ`` is passed untouched.

    Built as ``low + g·(x − low)`` rather than as a designed IIR shelf, because the
    low band is then *by construction* exactly the lowpassed input — the property the
    suite checks, instead of a property we hope the coefficients have.

    ``gain_db == 0.0`` returns the input unchanged; non-zero returns a new array.
    """
    arr = np.asarray(audio)
    if gain_db == 0.0:
        return arr.copy()
    sos = butter(1, HF_SHELF_HZ, btype="lowpass", fs=sr, output="sos")
    signal = arr.astype(np.float64)
    low = sosfilt(sos, signal, axis=-1)
    gain = 10.0 ** (gain_db / 20.0)
    return np.asarray(low + gain * (signal - low), dtype=arr.dtype)


def droop_makeup_db(hf_droop_db: float) -> float:
    """The bounded make-up a measured droop earns (``0.0`` when under the threshold).

    Measured droop for the configured wow/flutter is −0.164 dB, so the threshold keeps
    the shelf off rather than filtering a signal over a fifth of a decibel. Past it, the
    make-up is capped: a comb null is not a droop and cannot be shelved away, so the
    bound is what stops this from turning into an uncontrolled treble lift.
    """
    if not np.isfinite(hf_droop_db) or hf_droop_db >= -HF_DROOP_MIN_DB:
        return 0.0
    return float(min(-hf_droop_db, HF_DROOP_MAX_COMP_DB))


def head_spacing_samples(depth_ms: float, sr: int) -> int:
    """Whole-sample head spacing for a wow/flutter depth (S4).

    Whole by construction, so the compensation that removes it is exact rather than
    arithmetic-lucky; ``ceil`` so ``base >= depth`` also holds in samples and no tap
    can go negative.
    """
    return max(1, int(np.ceil(depth_ms * sr / 1000.0)))


def wow_flutter_aligned(
    audio: np.ndarray, sr: int, *, depth_ms: float
) -> tuple[np.ndarray, int]:
    """Wow/flutter with its static head spacing removed, sample-exactly.

    Returns ``(aligned, base_samples)``. The input is padded with ``base_samples``
    zeros at the end so the tail reads the pad instead of running off the buffer, and
    the output is taken from ``base_samples`` length-preserving.

    The residual deviation is the LFO. That is the effect: what is removed here is the
    static offset that would have misaligned the stem, not the drift that was asked for.
    """
    arr = np.asarray(audio)
    if arr.size == 0:
        return arr.copy(), 0
    base = head_spacing_samples(depth_ms, sr)
    params = WowFlutterParams(depth_ms=depth_ms, base_delay_ms=base * 1000.0 / sr)
    n_samples = arr.shape[-1]
    pad: list[tuple[int, int]] = [(0, 0)] * (arr.ndim - 1) + [(0, base)]
    padded = np.pad(arr, pad)
    delays = wow_flutter_delays(padded.shape[-1], sr, params)
    delayed = fractional_delay(padded, delays)
    return delayed[..., base : base + n_samples], base


def slapback_delay_samples(bpm: float | None, sr: int) -> int | None:
    """Whole-sample slapback delay for a tempo, or ``None`` without a usable tempo.

    Whole-sample on purpose: at an integer offset ``fractional_delay`` takes its
    direct-index path, so the slapback is a shift and a sum with no interpolation
    error and no high-frequency droop — a requirement met by construction instead of
    by compensation. The cost is under half a sample (≈ 0.011 ms at 44.1 kHz).
    """
    if bpm is None or not np.isfinite(bpm) or bpm <= 0.0:
        return None
    delay_samples = (60000.0 / bpm) * SLAPBACK_BEAT_FRACTION * sr / 1000.0
    return max(1, int(round(delay_samples)))


def apply_slapback(
    audio: np.ndarray, sr: int, *, bpm: float | None
) -> tuple[np.ndarray, dict[str, Any]]:
    """BPM-synced slapback. Returns the input unchanged without a usable tempo."""
    delay = slapback_delay_samples(bpm, sr)
    if delay is None:
        return audio, {
            "stage": "slapback",
            "status": "no_tempo",
            "note": "no usable tempo: the slapback cannot lock to the grid",
        }
    delays = np.full(audio.shape[-1], float(delay))
    delayed = fractional_delay(audio, delays).astype(audio.dtype)
    wet_gain = np.asarray(SLAPBACK_WET_GAIN, dtype=audio.dtype)
    out = audio + delayed * wet_gain
    return out, {
        "stage": "slapback",
        "status": "active",
        "delay_samples": delay,
        "delay_ms": round(delay * 1000.0 / sr, 3),
        "bpm": round(float(bpm), 2) if bpm is not None else None,
        "beat_fraction": SLAPBACK_BEAT_FRACTION,
        "wet_gain": SLAPBACK_WET_GAIN,
        "integer_delay": True,
    }


def apply_saturation(
    audio: np.ndarray,
    sr: int,
    *,
    drive_db: float = SATURATION_DRIVE_DB,
    mix: float = SATURATION_MIX,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Parallel saturation: the dry bass plus a level-matched harmonic path.

    The saturated copy is matched to the dry RMS BEFORE the blend. Without that the
    blend is a fader move with extra steps: the tape stage's own output level would
    decide how loud the bass gets, which is not something a saturation control should
    be allowed to do.

    ``mix == 0.0`` returns the input unchanged, so the blend is neutral at its own
    zero rather than only at the profile's zero.
    """
    arr = np.asarray(audio)
    if mix == 0.0:
        return arr.copy(), {
            "stage": "saturation",
            "status": "neutral",
            "drive_db": drive_db,
            "mix": mix,
        }
    saturated = tape_saturate(arr, sr, TapeParams(drive_db=drive_db))
    match_db = _level_match_db(saturated, arr)
    matched = saturated.astype(np.float64) * (10.0 ** (match_db / 20.0))
    dry = arr.astype(np.float64)
    blended = dry + mix * (matched - dry)
    return blended.astype(arr.dtype), {
        "stage": "saturation",
        "status": "active",
        "drive_db": drive_db,
        "mix": mix,
        "level_match_db": round(match_db, 4),
    }


def apply_chorus(
    audio: np.ndarray,
    sr: int,
    *,
    depth_ms: float = CHORUS_DEPTH_MS,
    mix: float = CHORUS_MIX,
    max_makeup_db: float = CHORUS_MAX_MAKEUP_DB,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Chorus with the comb loss measured and paid back (S5).

    The make-up is measured per application rather than assumed, because the loss is a
    function of ``mix`` and material. Measured on this repo's module at
    ``depth_ms=3.0, base_delay_ms=15.0, rate_hz=0.6``: −2.489 dB at ``mix=0.3``,
    −3.095 at 0.4, −3.440 at 0.5, −3.454 at 0.6.

    Over ``max_makeup_db`` the applied value is capped AND the report says it was
    capped. A compensation the code chose not to apply must never look like one it did.
    """
    arr = np.asarray(audio)
    wet_dry = chorus_pass(
        arr,
        sr,
        ChorusParams(
            depth_ms=depth_ms,
            base_delay_ms=CHORUS_BASE_DELAY_MS,
            rate_hz=CHORUS_RATE_HZ,
            mix=mix,
        ),
    )
    needed_makeup_db = _level_match_db(wet_dry, arr)
    applied_db = float(min(max(needed_makeup_db, 0.0), max_makeup_db))
    out = wet_dry
    if applied_db > 0.0:
        out = (wet_dry.astype(np.float64) * (10.0 ** (applied_db / 20.0))).astype(
            arr.dtype
        )
    return out, {
        "stage": "chorus",
        "status": "active",
        "depth_ms": depth_ms,
        "mix": mix,
        "comb_loss_db": round(-needed_makeup_db, 4),
        "gain_compensation_db": round(applied_db, 4),
        "gain_compensation_clamped": bool(needed_makeup_db > max_makeup_db),
    }


def apply_stem_character(
    name: str,
    audio: np.ndarray,
    sr: int,
    *,
    bpm: float | None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """One stem through the profile's stages. Returns ``(new array, report)``.

    The input is never mutated: a fresh array always comes back, so the caller can
    keep summing the untouched stems into the alternative renders.

    A stem the profile does not treat — and any stem whose stages are all neutral —
    comes back as a plain copy.

    Deterministic by construction: no stage of this profile draws a random number.
    The stochastic part of the character is the bed, and only ``apply_bed`` takes a
    seed.
    """
    stages = CHARACTER_STAGES.get(name, ())
    if not stages:
        return np.asarray(audio).copy(), {
            "stem": name,
            "stages": [],
            "status": "untreated",
        }
    reference = np.asarray(audio)
    shaped = reference
    reports: list[dict[str, Any]] = []
    latency_samples = 0

    if "wow_flutter" in stages:
        shaped, base = wow_flutter_aligned(shaped, sr, depth_ms=WOW_FLUTTER_DEPTH_MS)
        latency_samples += base
        reports.append(
            {
                "stage": "wow_flutter",
                "status": "active",
                "depth_ms": WOW_FLUTTER_DEPTH_MS,
                "head_spacing_samples": base,
                "head_spacing_ms": round(base * 1000.0 / sr, 4),
                "latency_compensated": True,
            }
        )
    if "chorus" in stages:
        shaped, chorus_report = apply_chorus(shaped, sr)
        reports.append(chorus_report)

    # The droop belongs to the interpolating stages, and the module order runs them
    # first, so `reference` is exactly the signal they were handed. The slapback is
    # deliberately outside this window: a whole-sample tap is a shift, and measuring a
    # band across a shift reports where the content moved, not what the interpolator
    # took out of it.
    droop_db = 0.0
    makeup_db = 0.0
    if any(stage in stages for stage in ("wow_flutter", "chorus")):
        droop_db = _band_energy_db(shaped, sr, HF_BAND_HZ) - _band_energy_db(
            reference, sr, HF_BAND_HZ
        )
        makeup_db = droop_makeup_db(droop_db)
        if makeup_db > 0.0:
            shaped = hf_shelf(shaped, sr, makeup_db)

    if "saturation" in stages:
        shaped, sat_report = apply_saturation(shaped, sr)
        reports.append(sat_report)
    if "slapback" in stages:
        shaped, slap_report = apply_slapback(shaped, sr, bpm=bpm)
        reports.append(slap_report)

    return shaped, {
        "stem": name,
        "stages": list(stages),
        "status": "active",
        "latency_compensated_samples": latency_samples,
        "hf_droop_db": round(droop_db, 4),
        "hf_makeup_db": round(makeup_db, 4),
        "hf_shelf_hz": HF_SHELF_HZ,
        "stages_report": reports,
    }


def apply_bed(
    bus: np.ndarray,
    sr: int,
    *,
    seed: int,
    authorized: bool,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Add the hiss/crackle bed under the mix. Returns ``(new array, report)``.

    ``authorized`` comes from the phase-1 inspector's ``NegativeSpace``: a bed under
    material with no room in it is mud, and the measurement that says there is room
    already exists. Unauthorized is not an error — it is a decision, and it is
    reported as one.
    """
    arr = np.asarray(bus)
    n_samples = arr.shape[-1]
    if not authorized:
        return arr.copy(), {
            "status": "skipped",
            "reason": "no_negative_space",
            "note": (
                "the input has no measured room for a bed "
                "(negative_space.bed_authorized is false)"
            ),
        }
    if n_samples == 0:
        return arr.copy(), {"status": "skipped", "reason": "empty_bus"}
    hiss = stereo_bed(
        pink_hiss(n_samples, sr, seed=seed, level_dbfs=BED_HISS_LEVEL_DBFS),
        spread=BED_SPREAD,
        seed=seed,
    )
    crackle_bed = stereo_bed(
        crackle(
            n_samples,
            sr,
            seed=seed + 1,
            rate_per_s=BED_CRACKLE_RATE_PER_S,
            level_dbfs=BED_CRACKLE_LEVEL_DBFS,
        ),
        spread=BED_SPREAD,
        seed=seed + 1,
    )
    bed = (hiss + crackle_bed).astype(arr.dtype)
    return (arr + bed).astype(arr.dtype), {
        "status": "active",
        "hiss_level_dbfs": BED_HISS_LEVEL_DBFS,
        "crackle_level_dbfs": BED_CRACKLE_LEVEL_DBFS,
        "crackle_rate_per_s": BED_CRACKLE_RATE_PER_S,
        "spread": BED_SPREAD,
        "seed": seed,
    }


def crest_db(bus: np.ndarray) -> float:
    """Crest factor of a bus in dB (``0.0`` for silence)."""
    x = np.asarray(bus)
    if x.size == 0:
        return 0.0
    peak = float(np.max(np.abs(x)))
    rms = _rms(x)
    if peak <= 0.0 or rms <= 0.0:
        return 0.0
    return float(20.0 * np.log10(peak / rms))


def crest_relax_needed_db(bus_crest_db: float) -> float:
    """The crest relax a bus needs to reach the QC floor.

    ``0.0`` when the bus is already at or above the floor.
    """
    return float(max(0.0, CREST_OK_MIN_DB - float(bus_crest_db)))


def character_budget(*, bus_crest_db: float) -> dict[str, Any]:
    """The QC budget the profile declares (S7), in the P2.5 contract.

    Two tolerances, and they are not the same kind of thing:

    * the tone tolerance is a declared ceiling — the bed legitimately lifts the 4–7 kHz
      share, and the number says by how much;
    * the crest tolerance is MEASURED from the bus the bed actually produced. The bed
      fills the quiet parts, so it lowers the crest of a dynamic program and raises it
      on an already-flat one; only a measurement can tell which happened.

    Both are capped at ``MAX_QC_RELAX_DB``. When the cap bites, the budget declares what
    it can — the check keeps flagging rather than the budget silently overstepping its
    contract or the render dying on a loud bed. ``crest_relax_needed_db`` is what lets
    the caller report that the cap bit; it cannot live in here, because
    ``validate_budget`` admits ``allowed_intentional`` as the *only* non-check key.
    """
    budget: dict[str, Any] = {
        "sibilance_5k": {"relax_db": TONE_RELAX_DB},
        "allowed_intentional": list(BUDGET_PROVENANCE),
    }
    applied_crest_db = min(crest_relax_needed_db(bus_crest_db), MAX_QC_RELAX_DB)
    if applied_crest_db > 0.0:
        budget["low_level_listen"] = {"relax_db": applied_crest_db}
    return budget


def is_known_profile(character: str | None) -> bool:
    """True when ``character`` names a profile this module implements."""
    return character == CHARACTER_PROFILE
