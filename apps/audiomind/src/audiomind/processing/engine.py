"""Audio processing engine — Dynamic, proportional mastering pipeline.

Instead of applying fixed preset values, this engine:
1. Gain-stages input to a consistent level (-6 dBFS)
2. Analyzes frequency content and dynamics
3. Applies proportional processing based on what the input NEEDS
4. Targets final loudness per preset character
"""
import gc
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import pedalboard
import soundfile as sf
from pedalboard import (
    Compressor,
    HighpassFilter,
    HighShelfFilter,
    LowShelfFilter,
    PeakFilter,
)
from pedalboard.io import AudioFile

from audiomind.analysis.analyzer import (
    TARGET_BANDS_HZ,
    _detect_already_mastered,
    analyze_band_energies,
    get_genre_target_profile,
)
from audiomind.models.audio import AnalysisResult, MasteringParameters
from audiomind.processing.adaptive_comp import (
    AdaptiveCompParams,
    adaptive_compress,
)
from audiomind.processing.clipper import soft_clip
from audiomind.processing.deesser import DeesserParams, deesser
from audiomind.processing.delay import DelayParams, delay_pass
from audiomind.processing.dither import apply_dither_noise_shaping
from audiomind.processing.dyn_eq import (
    DynEqBandParams,
    DynEqParams,
    dynamic_eq,
)
from audiomind.processing.echo import EchoParams, echo_pass
from audiomind.processing.exciter import (
    ExciterBandParams,
    ExciterParams,
    excite,
)
from audiomind.processing.io_write import write_output
from audiomind.processing.loudness import (
    integrated_loudness,
    measure_lra,
    true_peak_db,
)
from audiomind.processing.mono import enforce_mono_compatibility
from audiomind.processing.multiband import (
    BandParams,
    MultibandParams,
    multiband_compress,
)
from audiomind.processing.resample import resample_audio
from audiomind.processing.reverb import ReverbParams, reverb_pass
from audiomind.processing.smart_gate import SIGNATURE_SCALE_FLOOR, decide_smart_gate
from audiomind.processing.spatial import measure_stereo_correlation
from audiomind.processing.stereo_imaging import (
    StereoImagingParams,
    apply_stereo_imaging,
)
from audiomind.processing.tape import TapeParams, tape_saturate
from audiomind.processing.truepeak import compute_codec_safe_ceiling, true_peak_limit

# pedalboard's __init__ re-exports Pedalboard via a plain named import and
# defines no __all__; with implicit_reexport=False (mypy strict) the name is
# not treated as exported. Bind the module attribute explicitly — identical
# runtime behavior, satisfies mypy.
Pedalboard = pedalboard.Pedalboard

measure_lufs = integrated_loudness


def _match_peak(ref, tgt):
    if np.max(np.abs(tgt)) == 0:
        return tgt
    return tgt * (np.max(np.abs(ref)) / np.max(np.abs(tgt)))


def measure_correlation(*args, **kwargs):
    return 0.0


def calculate_crest_factor(audio):
    peak = np.max(np.abs(audio))
    rms = np.sqrt(np.mean(np.square(audio))) + 1e-12
    return float(20 * np.log10(peak / rms)) if peak > 0 else 0.0

# ── Gain Staging ──────────────────────────────────────────────────────


#: Margin (dB) below the limiter ceiling at which the soft-clipper engages.
#: The clipper runs BEFORE the limiter and trims transients that come within
#: this margin of the ceiling; below the resulting knee it is exactly linear
#: (bit-stable), so the default stays neutral for non-peak material.
CLIPPER_HEADROOM_DB = 1.5

#: Base module intensity for corrective modules while the smart gate is in
#: advisory mode. The gate multiplies its per-module advisory scale by this
#: base, so a fully reduced corrective stage still runs at 40% strength.
#: It is applied ONLY while the gate is active: an inactive gate leaves the
#: chain at full strength (neutral = bypass).
BASE_MODULE_INTENSITY = 0.4

#: Advisory-scale floor below which a stage is skipped instead of scaled.
#: Kept well under BASE_MODULE_INTENSITY so no advisory reduction can ever
#: silently turn a stage into a bypass.
_ADVISORY_MIN_INTENSITY = 0.05


class InputQcError(Exception):
    """Input failed the pre-processing QC gate (``strict_mode`` rejection).

    Raised by the engine BEFORE any DSP runs when the source material
    shows hard clipping or a true peak at/above -0.3 dBTP. The API maps
    it to HTTP 422 (a request rejection) instead of the generic 500
    (a processing failure).
    """


def _strict_reject_message(hard_clip_count: int, input_true_peak: float) -> str:
    """Spanish (neutral Latin American) rejection detail surfaced by the API as a 422."""
    issues: list[str] = []
    if hard_clip_count > 0:
        issues.append(f"clipping duro ({hard_clip_count} samples)")
    if input_true_peak >= -0.3:
        issues.append("true peak >= -0.3 dBTP")
    return "Entrada rechazada por strict_mode: " + " y ".join(issues) + "."


def _run_input_qc(
    audio: np.ndarray, sr: int, strict_mode: bool
) -> list[str]:
    """Analyze the in-memory input and enforce the ``strict_mode`` gate.

    Returns delivery warnings (Spanish, professional). Raises
    :class:`InputQcError` when ``strict_mode`` is set and the source shows
    hard clipping or a high true peak.
    """
    sample_peak_db = 20.0 * np.log10(
        max(float(np.max(np.abs(audio))), 1e-12)
    )
    input_true_peak = true_peak_db(audio, sr)
    hard_clip_count = int(np.sum(np.abs(audio) >= 1.0 - 1e-9))

    warnings: list[str] = []
    if hard_clip_count > 0:
        warnings.append(
            f"Entrada con clipping duro: {hard_clip_count} samples "
            f"(pico {sample_peak_db:.1f} dBFS)"
        )
    if input_true_peak >= -0.3:
        warnings.append("True peak de entrada alto (>= -0.3 dBTP)")

    if strict_mode and (hard_clip_count > 0 or input_true_peak >= -0.3):
        raise InputQcError(_strict_reject_message(hard_clip_count, input_true_peak))
    return warnings


def _resolve_output_sr(output_sr: str | int, input_sr: int) -> int:
    """Normalize the ``output_sr`` parameter to an int sample rate.

    'same_as_input' (or an explicit rate equal to the source) keeps the
    input rate; explicit rates (int or str literals) pass through.
    """
    if output_sr == "same_as_input":
        return input_sr
    return int(output_sr)


def gain_stage(
    audio: np.ndarray, target_peak_db: float = -6.0
) -> tuple[np.ndarray, float]:
    """
    Normalize input to target peak level (default -6 dBFS).
    Returns (normalized_audio, gain_applied_db).

    This ensures ALL presets work with consistent headroom regardless
    of how hot or quiet the original mix is.
    """
    current_peak = np.max(np.abs(audio))
    if current_peak == 0:
        return audio, 0.0
    current_peak_db = 20 * np.log10(current_peak)
    gain_db = target_peak_db - current_peak_db
    gain_linear = 10 ** (gain_db / 20)
    return audio * gain_linear, gain_db


# ── P4 texture recipe: read, report, cohere (spec S2–S8) ──────────────
# The mix engine (P3) bakes a DELIBERATE texture into the principal render
# (slapback vocal, wow/flutter chorus, parallel bass saturation, hiss/crackle
# bed) and measures its effect into a ``texture_recipe`` (S1). Mastering
# receives that render and, without the recipe, reads the noise as a defect.
# Everything below is the master half of that handshake: a lenient reader (S2)
# and the bounded adaptations (S4–S7) that stop the chain correcting texture.

#: Recipe schema this reader accepts. Any other value discards the recipe
#: WHOLE (never a partial application) and warns (mirrors
#: ``texture_recipe.RECIPE_SCHEMA``).
TEXTURE_RECIPE_SCHEMA = 1

#: Band-centre split (Hz) at/above which the match EQ's measured energy is
#: reduced by the recipe's declared HF excess, so the matcher judges the
#: program instead of the deliberate top-end texture (S4.1).
MATCH_EQ_HF_BAND_HZ = 6000.0

#: The match EQ's own per-band authority (±2 dB). The HF texture offset is
#: clamped to it: texture-awareness narrows what the matcher sees and never
#: grants extra cut (S4.1).
MATCH_EQ_HF_OFFSET_LIMIT_DB = 2.0

#: Margin (dB) above the declared bed level at which a boothed HF stage
#: threshold is placed so the bed sits BELOW it (S4).
BED_THRESHOLD_MARGIN_DB = 3.0

#: Warning names appended to ``warnings`` when a present recipe is discarded.
TEXTURE_WARNING_UNKNOWN_SCHEMA = "texture_recipe_unknown_schema"
TEXTURE_WARNING_MALFORMED = "texture_recipe_malformed"


def _as_number(value: object) -> float | None:
    """Return ``value`` as a float, or None when it is not a real number.

    ``bool`` is an ``int`` subclass; a bool is not a number here, so a recipe
    that smuggled one in is rejected as malformed rather than silently read as
    0/1.

    Neither is ``NaN``/``±Inf`` a measurement, and ``isinstance`` alone cannot
    tell: they are floats, so the reader accepted them as valid (review findings
    ``R3-as-number-nan-inf`` / ``R4-recipe-nonfinite-values``). What that
    acceptance actually did, measured on the pre-fix revision rather than
    reasoned about:

    * a non-finite value is not inert. ``measured.loudness_delta_lu = inf``
      moved the applied loudness compensation to its ``+6 dB`` clamp and
      ``measured.hf_excess_db = inf`` drove the HF withdrawal to its full ±2 dB
      bound and the clarity shelf to ``0.0`` — the render changed, and neither
      number is what the peer could have meant;
    * it reaches the RETURNED payload: the same run reported
      ``loudness_compensation_lu: nan``, and ``NaN`` is not valid JSON, so the
      response the Studio parses breaks;
    * and it is silent: no warning, and a recipe reported as applied.

    Rejecting it here discards the recipe WHOLE with
    ``texture_recipe_malformed`` (S2) — the route every other wrong-typed value
    already takes. The emitter floors its meters today, so today's payload is
    finite; the reader's contract is that the recipe is DATA from another
    service (S2), and "the peer is correct" is not a type check.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if np.isfinite(number):
            return number
    return None


def _read_texture_recipe(
    mix_metadata: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    """Read and validate the P4 texture recipe once, at the top of the chain.

    Lenient by contract (spec S2): the recipe is data from another service, not
    configuration, so a bad one degrades with an explicit report instead of
    raising. It is accepted only when ``recipe_schema == 1`` and every consumed
    value has the expected type; on ANY failure the recipe is discarded WHOLE
    (never partially applied) and the returned reason string names why. The
    reader consumes only the keys the master chain uses — ``profile``, ``seed``,
    ``bed`` and ``measured`` — and returns a normalised copy of them.

    Args:
        mix_metadata: The mix handshake payload — a dict (the real path, from
            ``session.mix_metadata``) or a ``MixMetadata`` instance, or None.

    Returns:
        ``(recipe, None)`` when a valid recipe is present, ``(None, None)`` when
        none is present, and ``(None, reason)`` when one is present but rejected
        (``texture_recipe_unknown_schema`` / ``texture_recipe_malformed``).
    """
    if mix_metadata is None:
        return None, None
    if isinstance(mix_metadata, dict):
        raw = mix_metadata.get("texture_recipe")
    else:
        raw = getattr(mix_metadata, "texture_recipe", None)
    if raw is None:
        return None, None
    if not isinstance(raw, dict) or "recipe_schema" not in raw:
        return None, TEXTURE_WARNING_MALFORMED
    schema = raw["recipe_schema"]
    if not isinstance(schema, int) or isinstance(schema, bool):
        return None, TEXTURE_WARNING_MALFORMED
    if schema != TEXTURE_RECIPE_SCHEMA:
        return None, TEXTURE_WARNING_UNKNOWN_SCHEMA

    profile = raw.get("profile")
    seed = raw.get("seed")
    bed = raw.get("bed")
    measured_raw = raw.get("measured")
    if not isinstance(profile, str):
        return None, TEXTURE_WARNING_MALFORMED
    if not isinstance(seed, int) or isinstance(seed, bool):
        return None, TEXTURE_WARNING_MALFORMED
    if not isinstance(bed, dict) or not isinstance(measured_raw, dict):
        return None, TEXTURE_WARNING_MALFORMED

    bed_applied = bed.get("applied")
    bed_transient = bed.get("transient")
    hiss_dbfs = _as_number(bed.get("hiss_dbfs"))
    crackle_dbfs = _as_number(bed.get("crackle_dbfs"))
    crackle_rate = _as_number(bed.get("crackle_rate_per_s"))
    if not isinstance(bed_applied, bool) or not isinstance(bed_transient, bool):
        return None, TEXTURE_WARNING_MALFORMED
    if hiss_dbfs is None or crackle_dbfs is None or crackle_rate is None:
        return None, TEXTURE_WARNING_MALFORMED

    loudness_delta = _as_number(measured_raw.get("loudness_delta_lu"))
    hf_excess = _as_number(measured_raw.get("hf_excess_db"))
    crest_delta = _as_number(measured_raw.get("crest_delta_db"))
    centroid_delta = _as_number(measured_raw.get("centroid_delta_hz"))
    band_limited = measured_raw.get("band_limited_vocal")
    if (
        loudness_delta is None
        or hf_excess is None
        or crest_delta is None
        or centroid_delta is None
    ):
        return None, TEXTURE_WARNING_MALFORMED
    if not isinstance(band_limited, bool):
        return None, TEXTURE_WARNING_MALFORMED

    return {
        "profile": profile,
        "seed": int(seed),
        "bed": {
            "applied": bed_applied,
            "transient": bed_transient,
            "hiss_dbfs": hiss_dbfs,
            "crackle_dbfs": crackle_dbfs,
            "crackle_rate_per_s": crackle_rate,
        },
        "measured": {
            "loudness_delta_lu": loudness_delta,
            "hf_excess_db": hf_excess,
            "crest_delta_db": crest_delta,
            "centroid_delta_hz": centroid_delta,
            "band_limited_vocal": band_limited,
        },
    }, None


def _recipe_hf_excess_db(recipe: dict[str, Any] | None) -> float:
    """The declared HF texture excess (dB), never negative (S4.1 / S4.3).

    Texture-awareness may only WITHDRAW (a smaller boost, a narrower matcher
    view); a measured negative excess (the character removed top) is clamped to
    zero so a recipe can never make the chain brighten or cut more than today.
    """
    if recipe is None:
        return 0.0
    return max(0.0, float(recipe["measured"]["hf_excess_db"]))


def _texture_corrected_analysis(
    analysis: AnalysisResult | None,
    recipe: dict[str, Any] | None,
) -> AnalysisResult | None:
    """Correct the two bed-biased analysis numbers the gate consumers read (S7).

    The bed inflates ``spectral_centroid`` and deflates ``crest_factor_db``, and
    both ``_detect_already_mastered`` and ``decide_smart_gate`` read those two.
    The declared deltas are undone here — at the call site — and
    ``is_already_mastered`` is re-derived with the analyzer's own detector, so
    the gate judges the PROGRAM. ``analyzer.py``/``smart_gate.py`` are not
    touched and keep their single responsibility. With no analysis or no recipe
    the original object is returned untouched (neutral = bypass).
    """
    if analysis is None or recipe is None:
        return analysis
    measured = recipe["measured"]
    corrected_centroid = analysis.spectral_centroid - measured["centroid_delta_hz"]
    corrected_crest = analysis.crest_factor_db + measured["crest_delta_db"]
    is_mastered, confidence = _detect_already_mastered(
        analysis.integrated_lufs,
        analysis.true_peak_db,
        analysis.dynamic_range_db,
        corrected_centroid,
        crest_factor_db=corrected_crest,
    )
    return analysis.model_copy(
        update={
            "spectral_centroid": corrected_centroid,
            "crest_factor_db": corrected_crest,
            "is_already_mastered": is_mastered,
            "mastering_confidence": confidence,
        }
    )


def _bed_high_band_threshold_db(
    existing_threshold_db: float, recipe: dict[str, Any] | None
) -> float:
    """Raise an HF-band threshold so the declared bed sits BELOW it (S4).

    The recipe declares the bed's absolute level in dBFS (``hiss_dbfs`` /
    ``crackle_dbfs``); the loudest component is what can drive a per-band
    detector. The threshold is raised to that level plus
    ``BED_THRESHOLD_MARGIN_DB`` — never LOWERED, so a bed can only stop a stage
    responding to it, never make one respond more — and stays a valid ≤ 0 dBFS
    threshold. With no recipe, or a bed that never ran, the threshold is
    returned unchanged.

    Note: for the default −20 dBFS thresholds and a realistic bed (the profile
    declares ≈ −48 dBFS hiss), this is deliberately a no-op — the bed is
    already below the default threshold and the report says so.
    """
    if recipe is None or not recipe["bed"]["applied"]:
        return existing_threshold_db
    bed = recipe["bed"]
    bed_level_dbfs = max(float(bed["hiss_dbfs"]), float(bed["crackle_dbfs"]))
    required = bed_level_dbfs + BED_THRESHOLD_MARGIN_DB
    return float(
        np.clip(max(existing_threshold_db, required), -60.0, 0.0)
    )


def _report_threshold_decision(
    report: dict[str, Any] | None,
    key: str,
    base_db: float,
    new_db: float,
) -> None:
    """Record an HF-threshold raise (S4, boothed stages) only when it moved."""
    if report is None or new_db == base_db:
        return
    report[key] = {
        "threshold_db": round(new_db, 2),
        "offset_db": round(new_db - base_db, 2),
    }


# ── Match EQ (Genre Target Profiles) ──────────────────────────────────


def _freq_to_band_index(freq: float) -> int:
    """Find closest TARGET_BANDS_HZ index for a given frequency."""
    return min(range(len(TARGET_BANDS_HZ)), key=lambda i: abs(TARGET_BANDS_HZ[i] - freq))


def build_match_eq(
    audio: np.ndarray,
    sample_rate: int,
    eq_bands: list[dict[str, Any]],
    analysis_result: AnalysisResult | None = None,
    intensity_multiplier: float = 1.8,
    hf_texture_offset_db: float = 0.0,
) -> list[PeakFilter]:
    """Build EQ chain using genre target profiles (Match EQ).

    REPLACES the old `build_dynamic_eq`. Instead of applying fixed preset
    gains scaled inversely to band energy (which tries to "flatten" the
    spectrum), this function:

      1. Gets the genre-specific target profile (spectral ideal).
      2. Measures current band energy via FFT.
      3. Computes delta = target_level - current_level for each band.
      4. Applies corrective EQ to push the spectrum toward the target.

    The result: genres keep their character (sub-bass for reggaeton,
    aggressive mids for rock) while the overall balance is corrected
    toward commercial standards.

    Args:
        audio: Audio array (channels, samples) — pre-gain-staged.
        sample_rate: Sample rate in Hz.
        eq_bands: List of preset EQ band dicts (kept for structural
                  compatibility; used for frequency/Q reference).
        analysis_result: Optional analysis result with detected genre.
        intensity_multiplier: Corrective authority scaler.
        hf_texture_offset_db: The recipe's declared HF texture excess (S4.1).
                  It is added to the shape delta of every band whose centre is
                  ≥ ``MATCH_EQ_HF_BAND_HZ``, so the matcher judges the program
                  instead of the deliberate bed while every other band's gain
                  stays bit-identical. Clamped to the matcher's own ±2 dB
                  authority (``MATCH_EQ_HF_OFFSET_LIMIT_DB``); the neutral
                  default (0.0) leaves every existing caller and test
                  byte-for-byte unchanged.

    Returns:
        List of Pedalboard PeakFilter plugins.
    """
    # Determine target profile: genre-specific, universal fallback, or balanced
    if not analysis_result or not analysis_result.detected_genre:
        # No genre data at all → use universal balanced profile
        target_profile = get_genre_target_profile("other")
    else:
        genre = analysis_result.detected_genre
        confidence = analysis_result.genre_confidence

        if confidence < 0.3 or genre == "other":
            # Low confidence or unknown genre → universal balanced profile
            # (never fall back to the old "do nothing" dynamic EQ)
            target_profile = get_genre_target_profile("other")
        else:
            target_profile = get_genre_target_profile(genre)

    # Measure current band energies from input
    mono = np.mean(audio, axis=0) if audio.ndim == 2 else audio
    current_energies = analyze_band_energies(mono, sample_rate, TARGET_BANDS_HZ)

    # S4.1: the declared HF texture excess is applied to the DELTA of every band
    # whose centre is at/above the HF split (in the two delta sites below),
    # never to the energy before the mean. Subtracting it from the energy moved
    # the mean and shifted EVERY band's gain — adding cut to non-HF bands the
    # texture never touched; adding it to the HF delta is the same HF effect
    # while leaving every other band's gain bit-identical to offset 0.0. The
    # offset is clamped to the matcher's own ±2 dB authority so texture-
    # awareness narrows what it sees and never grants extra cut. With no recipe
    # (offset 0.0) the energies and every delta are untouched.
    hf_offset_db = float(
        np.clip(
            hf_texture_offset_db,
            -MATCH_EQ_HF_OFFSET_LIMIT_DB,
            MATCH_EQ_HF_OFFSET_LIMIT_DB,
        )
    )

    # Convert current energies to a relative offset from the average level
    # This gives us the SHAPE of the spectrum, not the absolute level
    avg_energy = np.mean(current_energies) if current_energies else -40.0
    current_shape = [e - avg_energy for e in current_energies]

    # Compute per-band delta: what gain to apply to reach the target shape
    #   delta > 0 → boost (band is quieter than target)
    #   delta < 0 → cut   (band is louder than target)
    plugins: list[PeakFilter] = []
    for _i, band in enumerate(eq_bands):
        band_freq = band["freq"]
        band_idx = _freq_to_band_index(band_freq)

        if band_idx >= len(target_profile):
            continue

        target_offset = target_profile[band_idx]
        current_offset = current_shape[band_idx]

        # Delta: what we need to add to get from current to target
        delta = (target_offset - current_offset) * intensity_multiplier

        # S4.1: HF bands gain the declared texture excess in their delta (the
        # matcher stops reading the deliberate top as material to cut). Only
        # bands at/above the HF split are touched, so non-HF gains are
        # bit-identical to the offset-0.0 run.
        if hf_offset_db != 0.0 and band_freq >= MATCH_EQ_HF_BAND_HZ:
            delta += hf_offset_db

        # Scale by the preset's max_gain_db as a confidence/authority factor
        preset_authority = band.get("max_gain_db", 3.0)
        if preset_authority == 0:
            continue

        # Normalize: if preset says +6dB on this band and delta says +3dB,
        # use +3dB (capped to what's reasonable). If preset says +2dB and
        # delta says +6dB, use +2dB (don't exceed preset's intent).
        gain = np.clip(delta, -abs(preset_authority), abs(preset_authority))

        # Don't create filters for negligible gain
        if abs(gain) < 0.3:
            # Still apply if there's a clear delta but the preset has no band here
            # (handled by the dynamic band below)
            continue

        plugins.append(
            PeakFilter(
                cutoff_frequency_hz=band_freq,
                gain_db=round(gain, 1),
                q=band.get("q", 1.0),
            )
        )

    # Additional bands from target profile not covered by preset eq_bands
    for i, band_freq in enumerate(TARGET_BANDS_HZ):
        if i >= len(target_profile):
            break

        # Skip if this band is already handled by the preset eq_bands
        already_handled = any(
            abs(b["freq"] - band_freq) < band_freq * 0.3 for b in eq_bands
        )
        if already_handled:
            continue

        target_offset = target_profile[i]
        current_offset = current_shape[i]
        delta = (target_offset - current_offset) * intensity_multiplier

        # S4.1: HF bands gain the declared texture excess (same rule as the
        # preset loop above) so the uncovered-band matcher judges the program.
        if hf_offset_db != 0.0 and band_freq >= MATCH_EQ_HF_BAND_HZ:
            delta += hf_offset_db

        # Gentle correction for uncovered bands (±2 dB max)
        gain = np.clip(delta, -2.0, 2.0)
        if abs(gain) < 0.5:
            continue

        plugins.append(
            PeakFilter(
                cutoff_frequency_hz=band_freq,
                gain_db=round(gain, 1),
                q=0.8,
            )
        )

    return plugins


def build_character_eq(
    eq_bands: list[dict[str, Any]], gain_scale: float = 1.0
) -> list[PeakFilter | LowShelfFilter | HighShelfFilter]:
    """Build preset character EQ plugins from PRESET_CHAINS band dicts.

    Each band follows the preset chain format:
    ``{"freq": float, "max_gain_db": float, "q": float,
       "type": "peak"|"low_shelf"|"high_shelf"}``. The ``type`` maps to
    the matching pedalboard filter class (verified against pedalboard
    0.9.25: ``PeakFilter`` / ``LowShelfFilter`` / ``HighShelfFilter`` all
    exist with ``cutoff_frequency_hz`` / ``gain_db`` / ``q``); any
    unknown type degrades to ``PeakFilter`` at the declared frequency so
    a future band type never crashes the chain.

    Gains are scaled by ``gain_scale`` (the engine's ``am_factor``,
    exactly like the 8 kHz clarity shelf) and clamped to the
    pedalboard-sanctioned default range (±24 dB gain, q in [0.1, 10]).
    """
    plugins: list[PeakFilter | LowShelfFilter | HighShelfFilter] = []
    for band in eq_bands:
        band_type = band.get("type", "peak")
        freq = float(band.get("freq", 1000.0))
        gain = float(band.get("max_gain_db", 0.0)) * gain_scale
        q = float(band.get("q", 1.0))
        gain = float(np.clip(gain, -24.0, 24.0))
        q = float(np.clip(q, 0.1, 10.0))
        if band_type == "low_shelf":
            plugin_cls: (
                type[PeakFilter] | type[LowShelfFilter] | type[HighShelfFilter]
            ) = LowShelfFilter
        elif band_type == "high_shelf":
            plugin_cls = HighShelfFilter
        else:  # "peak" (and unknown types → peak fallback)
            plugin_cls = PeakFilter
        plugins.append(
            plugin_cls(
                cutoff_frequency_hz=freq,
                gain_db=gain,
                q=q,
            )
        )
    return plugins


# ── Final Stages ──────────────────────────────────────────────────────


def target_lufs(
    audio: np.ndarray,
    sample_rate: int,
    target: float,
    loudness_delta_lu: float = 0.0,
) -> np.ndarray:
    """
    Adjust gain to hit target LUFS (BS.1770-4 measurement).
    Capped at -12/+6 dB to avoid excessive limiting or attenuation.

    ``loudness_delta_lu`` (P4, S5) is the recipe's declared texture loudness
    contribution. When present it is REMOVED from the measurement before the
    gain is computed — ``gain_db = clamp(target − (measure − delta), −12, +6)``
    — so the PROGRAM, not the bed, lands on ``target``. The stated consequence:
    the final integrated LUFS then reads higher than ``target`` by exactly
    ``loudness_delta_lu``, because the bed is legitimately part of the program.
    The default (0.0) is bit-identical to the original behaviour and every
    existing caller is unchanged.

    Robust to silence/empty input: the compliant meter floors at -70 LKFS,
    so the gain is always finite and clamped — never NaN/inf.
    """
    current = measure_lufs(audio, sample_rate)
    gain_db = target - (current - loudness_delta_lu)
    if not np.isfinite(gain_db):
        gain_db = 6.0  # never emit NaN gain
    gain_db = max(-12, min(6, gain_db))
    gain_linear = 10 ** (gain_db / 20)
    return audio * gain_linear


def final_limit(
    audio: np.ndarray, sample_rate: int, ceiling_db: float = -1.0
) -> np.ndarray:
    """True Peak limiter (8x oversampling, lookahead, adaptive release)."""
    return true_peak_limit(audio, sample_rate, ceiling_db=ceiling_db)


def _user_limiter_ceiling(
    limiter_ceiling_db: float, already_mastered: bool
) -> float:
    """User-facing limiter ceiling (dBTP) for the source material.

    Already-mastered tracks already sit close to 0 dBFS, so they need MORE
    headroom (a LOWER ceiling) than un-mastered material. The reduction is
    applied additively in dB. (The previous code multiplied the negative
    ceiling by 0.8 for already-mastered tracks, which RAISED it toward
    0 dBFS — the exact opposite of the intent.)
    """
    extra_headroom_db = 0.4 if already_mastered else 0.0
    return limiter_ceiling_db - extra_headroom_db


# ── Pipeline ──────────────────────────────────────────────────────────


def measure_dynamic_range(audio: np.ndarray, sr: int) -> float:
    """Measure dynamic range in dB."""
    frame_length = int(sr * 0.1)
    hop_length = frame_length // 2

    rms_values = []
    for ch in range(audio.shape[0]):
        for i in range(0, audio.shape[1] - frame_length, hop_length):
            frame = audio[ch, i : i + frame_length]
            rms = np.sqrt(np.mean(frame**2))
            rms_values.append(rms)

    if not rms_values:
        return 0.0

    rms_db = 20 * np.log10(np.array(rms_values) + 1e-10)
    return float(np.max(rms_db) - np.min(rms_db))


def _multiband_params_from_mastering(
    p: MasteringParameters, recipe: dict[str, Any] | None = None
) -> MultibandParams:
    """Map the MasteringParameters multiband fields onto the DSP stage config.

    Knee, attack and release use the module defaults; makeup is automatic
    (each band's average gain reduction is compensated so the master does
    not audibly "shrink"). The neutral defaults (ratio 1.0) keep the stage
    a bit-exact no-op even when enabled.

    ``recipe`` (P4, S4): with a bed declared the HIGH band's threshold is
    raised so the bed sits below it instead of driving the stage. With no
    recipe the parameters are exactly today's.
    """
    return MultibandParams(
        crossover_low_hz=p.multiband_crossover_low_hz,
        crossover_high_hz=p.multiband_crossover_high_hz,
        bands=(
            BandParams(
                threshold_db=p.multiband_low_threshold_db,
                ratio=p.multiband_low_ratio,
            ),
            BandParams(
                threshold_db=p.multiband_mid_threshold_db,
                ratio=p.multiband_mid_ratio,
            ),
            BandParams(
                threshold_db=_bed_high_band_threshold_db(
                    p.multiband_high_threshold_db, recipe
                ),
                ratio=p.multiband_high_ratio,
            ),
        ),
        auto_makeup=True,
    )


def _dyn_eq_params_from_mastering(
    p: MasteringParameters, recipe: dict[str, Any] | None = None
) -> DynEqParams:
    """Map the MasteringParameters dynamic-EQ fields onto the DSP stage config.

    Detector time constants use the module defaults (imported from the
    Sprint 4 multiband module). The neutral defaults (ratio 1.0) keep the
    stage a bit-exact no-op even when enabled.

    ``recipe`` (P4, S4): with a bed declared the HF band's (band 3) threshold
    is raised so the bed sits below it instead of driving the stage. With no
    recipe the parameters are exactly today's.
    """
    return DynEqParams(
        bands=(
            DynEqBandParams(
                freq_hz=p.dyn_eq_band1_freq_hz,
                q=p.dyn_eq_band1_q,
                threshold_db=p.dyn_eq_band1_threshold_db,
                ratio=p.dyn_eq_band1_ratio,
            ),
            DynEqBandParams(
                freq_hz=p.dyn_eq_band2_freq_hz,
                q=p.dyn_eq_band2_q,
                threshold_db=p.dyn_eq_band2_threshold_db,
                ratio=p.dyn_eq_band2_ratio,
            ),
            DynEqBandParams(
                freq_hz=p.dyn_eq_band3_freq_hz,
                q=p.dyn_eq_band3_q,
                threshold_db=_bed_high_band_threshold_db(
                    p.dyn_eq_band3_threshold_db, recipe
                ),
                ratio=p.dyn_eq_band3_ratio,
            ),
        )
    )


def _exciter_params_from_mastering(p: MasteringParameters) -> ExciterParams:
    """Map the MasteringParameters exciter fields onto the DSP stage config.

    The four Ozone-style bands (bass/tube/tape/air) map 1:1 onto the stage;
    ``harmonic_blend`` in "mix" mode uses the module default (0.5 = 50/50),
    which the model does not expose. The neutral defaults (amount 0.0) keep
    the stage a bit-exact no-op even when enabled.
    """
    return ExciterParams(
        bands=(
            ExciterBandParams(
                amount=p.exciter_band1_amount,
                drive_db=p.exciter_band1_drive_db,
                low_cut_hz=p.exciter_band1_low_cut_hz,
                mode=p.exciter_band1_mode,
            ),
            ExciterBandParams(
                amount=p.exciter_band2_amount,
                drive_db=p.exciter_band2_drive_db,
                low_cut_hz=p.exciter_band2_low_cut_hz,
                mode=p.exciter_band2_mode,
            ),
            ExciterBandParams(
                amount=p.exciter_band3_amount,
                drive_db=p.exciter_band3_drive_db,
                low_cut_hz=p.exciter_band3_low_cut_hz,
                mode=p.exciter_band3_mode,
            ),
            ExciterBandParams(
                amount=p.exciter_band4_amount,
                drive_db=p.exciter_band4_drive_db,
                low_cut_hz=p.exciter_band4_low_cut_hz,
                mode=p.exciter_band4_mode,
            ),
        )
    )


def _tape_params_from_mastering(p: MasteringParameters) -> TapeParams:
    """Map the MasteringParameters tape fields onto the DSP stage config.

    The six ``tape_*`` fields map 1:1 onto the real-tape stage. The neutral
    defaults (drive 0, no hysteresis/bias/roll-off) keep the stage a
    bit-exact no-op even when enabled, so the engine skips the processing
    pass entirely and leaves the signal untouched.
    """
    return TapeParams(
        drive_db=p.tape_drive_db,
        hysteresis=p.tape_hysteresis,
        bias=p.tape_bias,
        rolloff_amount=p.tape_rolloff_amount,
        hf_shelf_hz=p.tape_hf_shelf_hz,
    )


def _adaptive_comp_params_from_mastering(p: MasteringParameters) -> AdaptiveCompParams:
    """Map the MasteringParameters adaptive-compressor fields onto the DSP stage.

    The six ``adaptive_comp_*`` fields map 1:1 onto the program-dependent
    stage. The neutral default (ratio 1.0) keeps the stage a bit-exact no-op
    even when enabled, so the engine skips the processing pass entirely and
    leaves the fixed −16 dB compressor out of the chain.
    """
    return AdaptiveCompParams(
        threshold_offset_db=p.adaptive_comp_threshold_offset_db,
        ratio=p.adaptive_comp_ratio,
        attack_ms=p.adaptive_comp_attack_ms,
        release_ms=p.adaptive_comp_release_ms,
        makeup_db=p.adaptive_comp_makeup_db,
    )


def _delay_params_from_mastering(p: MasteringParameters) -> DelayParams:
    """Map the MasteringParameters delay fields onto the DSP stage config.

    The three ``delay_*`` fields map 1:1 onto the circular-buffer delay
    stage. The neutral default (``mix == 0.0``) keeps the stage a bit-exact
    no-op even when enabled, so the engine skips the processing pass
    entirely and leaves the signal untouched.
    """
    return DelayParams(
        time_ms=p.delay_time_ms,
        mix=p.delay_mix,
        feedback=p.delay_feedback,
    )


def _echo_params_from_mastering(p: MasteringParameters) -> EchoParams:
    """Map the MasteringParameters echo fields onto the DSP stage config.

    The three ``echo_*`` fields map 1:1 onto the cascading-repeats echo
    stage. The neutral default (``mix == 0.0``) keeps the stage a bit-exact
    no-op even when enabled, so the engine skips the processing pass
    entirely and leaves the signal untouched.
    """
    return EchoParams(
        time_ms=p.echo_time_ms,
        mix=p.echo_mix,
        feedback=p.echo_feedback,
    )


def _reverb_params_from_mastering(p: MasteringParameters) -> ReverbParams:
    """Map the MasteringParameters reverb fields onto the DSP stage config.

    The two ``reverb_*`` fields map 1:1 onto the Schroeder reverb stage
    (4 combs + 2 all-passes). The neutral default (``mix == 0.0``) keeps
    the stage a bit-exact no-op even when enabled, so the engine skips the
    processing pass entirely and leaves the signal untouched.
    """
    return ReverbParams(
        mix=p.reverb_mix,
        size=p.reverb_size,
    )


def _stereo_imaging_params_from_mastering(
    p: MasteringParameters,
) -> StereoImagingParams:
    """Map the MasteringParameters stereo-imaging fields onto the DSP stage.

    The four ``stereo_imaging_*`` fields map 1:1 onto the per-band stage.
    NEUTRAL (all widths 1.0, mono_below_hz 0.0) is a bit-exact no-op, so the
    engine's existing broadband width / mono-compat path stays untouched for
    existing masters; this stage only engages when explicitly enabled.
    """
    return StereoImagingParams(
        crossover_low_hz=150.0,
        crossover_high_hz=3000.0,
        low_width=p.stereo_imaging_low_width,
        mid_width=p.stereo_imaging_mid_width,
        high_width=p.stereo_imaging_high_width,
        mono_below_hz=p.stereo_imaging_mono_below_hz,
    )


def _deesser_params_from_mastering(p: MasteringParameters) -> DeesserParams:
    """Map the MasteringParameters de-esser fields onto the DSP stage config.

    The band edges use the module anchors (3-8 kHz); only the max reduction
    and the detector threshold are exposed. The neutral default (amount 0.0)
    keeps the stage a bit-exact no-op even when enabled, so the engine skips
    the processing pass entirely and leaves the signal untouched.
    """
    return DeesserParams(
        amount_db=p.deesser_amount_db,
        threshold_db=p.deesser_threshold_db,
    )


def _process_transparent(
    audio: np.ndarray,
    sr: int,
    params: MasteringParameters,
    output_path: Path,
    already_mastered: bool,
    report: Callable[[float], None],
    warnings: list[str],
    texture_recipe: dict[str, Any] | None = None,
    texture_adaptation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Transparent delivery mode — no tone shaping whatsoever.

    Compliance Phase 1 (BandLab/LANDR-like delivery). ONLY these stages
    run, and each ONLY when explicitly requested:

      * SRC to ``output_sr`` (never automatic);
      * loudness match + the streaming-safe limiter tail (codec-safe
        ceiling, soft-clip, true-peak limit) when ``target_lufs_db`` is
        set — explicitly or by a platform preset;
      * dither at 16-bit output only;
      * safety normalize ONLY when the loudness/limiter path ran.

    ``target_lufs`` is NEVER derived automatically here: a default request
    is a pure passthrough (samples untouched beyond the PCM quantization
    of the writer). Output always goes through the explicit-subtype PCM
    writer (default 24-bit).

    ``texture_recipe`` (P4, S5): when a recipe is present its declared
    ``loudness_delta_lu`` is removed from the loudness measurement exactly as
    in the main path — the PROGRAM, not the bed, lands on ``target_lufs_db``,
    so a textured transparent master is not quieter than a neutral one. The
    ``texture_adaptation`` report (profile/seed + the compensation actually
    applied) is attached to the returned dict ONLY when a recipe was read.
    """
    input_sr = sr
    resolved_sr = _resolve_output_sr(params.output_sr, input_sr)
    if resolved_sr != input_sr:
        audio = resample_audio(audio, input_sr, resolved_sr)
        sr = resolved_sr
        # Filter ringing can push a hair beyond [-1, 1] after SRC; trim
        # that tiny overshoot without otherwise touching the samples.
        audio = np.clip(audio, -1.0, 1.0)
    report(30)

    loudness_delta_lu = (
        texture_recipe["measured"]["loudness_delta_lu"]
        if texture_recipe is not None
        else 0.0
    )

    safe_ceiling: float | None = None
    user_ceiling: float | None = None
    codec_pre_matching = False
    did_loudness = False
    if params.target_lufs_db is not None:
        audio = target_lufs(
            audio, sr, params.target_lufs_db, loudness_delta_lu=loudness_delta_lu
        )
        report(55)

        crest_factor_db = calculate_crest_factor(audio)
        user_ceiling = _user_limiter_ceiling(
            params.limiter_ceiling_db, already_mastered
        )
        safe_ceiling = compute_codec_safe_ceiling(
            target_lufs=params.target_lufs_db,
            crest_factor_db=crest_factor_db,
            default_ceiling_db=user_ceiling,
        )
        clipper_threshold_db = safe_ceiling - CLIPPER_HEADROOM_DB
        audio = soft_clip(audio, sr, threshold_db=clipper_threshold_db)
        audio = final_limit(audio, sr, ceiling_db=safe_ceiling)
        codec_pre_matching = safe_ceiling < user_ceiling

        # Streaming-safe guard (only after loudness processing): never
        # deliver a sample above 0 dBFS.
        max_val = np.max(np.abs(audio))
        if max_val > 1.0:
            audio = audio / max_val * 0.99
        did_loudness = True
        report(75)

    if params.output_bit_depth == 16:
        audio = apply_dither_noise_shaping(
            audio, target_bit_depth=16, sample_rate=sr
        )

    report(85)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_output(audio, output_path, sr, params.output_bit_depth)
    # Free the Numpy/Soundfile buffers immediately after the WAV export so
    # the transient DSP arrays don't linger in RAM on small deployments.
    gc.collect()
    report(95)

    # Measure output metrics at the (possibly resampled) output rate.
    true_peak = true_peak_db(audio, sr)
    integrated_lufs = measure_lufs(audio, sr)
    crest = calculate_crest_factor(audio)
    lra = measure_lra(audio, sr)
    stereo_correlation = measure_stereo_correlation(audio)

    result: dict[str, Any] = {
        "output_path": str(output_path),
        "sample_rate": sr,
        "channels": audio.shape[0],
        "duration_seconds": audio.shape[1] / sr,
        "true_peak_db": round(true_peak, 2),
        "integrated_lufs": round(integrated_lufs, 2),
        "crest_factor_db": round(crest, 2),
        "limiter_ceiling_db": (
            round(safe_ceiling, 2) if safe_ceiling is not None else None
        ),
        "output_bit_depth": params.output_bit_depth,
        "codec_pre_matching": codec_pre_matching,
        "input_sr": input_sr,
        "output_sr": sr,
        "target_lufs": params.target_lufs_db if did_loudness else None,
        "warnings": warnings,
        "lra": round(lra, 2) if lra is not None else None,
        "stereo_correlation": (
            round(stereo_correlation, 3) if stereo_correlation is not None else None
        ),
    }
    # S3/S5: this path reports the recipe too, but ONLY when one was read, and
    # it records only the compensation actually applied (the loudness stage ran
    # whenever a target was set). No recipe ⇒ no key ⇒ exactly today's dict.
    if texture_adaptation is not None:
        if loudness_delta_lu != 0.0 and did_loudness:
            texture_adaptation["loudness_compensation_lu"] = loudness_delta_lu
        result["texture_adaptation"] = texture_adaptation
    return result


def process_audio(
    input_path: str | Path,
    output_path: str | Path,
    params: MasteringParameters,
    analysis_result: AnalysisResult | None = None,
    intensity_multiplier: float = 1.8,
    progress_cb: Callable[[float], None] | None = None,
    mix_metadata: dict | None = None,
) -> dict[str, Any]:
    """
    Module-based mastering pipeline.

    Processes audio using MasteringParameters fields instead of fixed presets.
    Each module (Clarity, Fire/Push, Tape/Saturation, Spatial/Cinematic)
    controls a specific aspect of the DSP chain via its sliders.

    The pipeline self-adjusts to input dynamics — compression threshold,
    LUFS target, and limiting adapt to the source material.
    """
    input_path = Path(input_path)
    output_path = Path(output_path)

    def report(pct: float) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(min(1.0, max(0.0, pct / 100.0)))
        except Exception:
            pass

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Read audio
    with AudioFile(str(input_path)) as f:
        audio = f.read(f.frames)
        sr = int(f.samplerate)
    input_sr = sr

    # ── Input QC (Compliance Phase 1) ─────────────────────────────────
    # Analyze the in-memory audio right after reading (both modes). The
    # strict_mode gate rejects clipped/hot sources BEFORE any DSP runs; the
    # warnings ride along in every result so the API can surface them in
    # the delivery report.
    warnings = _run_input_qc(audio, sr, params.strict_mode)

    # ── P4 texture recipe (S2): parse ONCE, here, at the top of the chain ──
    # The de-esser runs far above the existing mix_metadata adaptation block
    # (stage 7, near the spatial block), so the recipe is read here. The reader
    # is lenient by contract: an unknown schema or a malformed value discards
    # the recipe WHOLE and appends a named warning; the render is then exactly
    # the one it produces today. It never raises and never half-applies.
    texture_recipe, texture_warning = _read_texture_recipe(mix_metadata)
    if texture_warning is not None:
        warnings.append(texture_warning)

    # S7: the bed biases two analysis numbers (inflated spectral centroid,
    # deflated crest factor) and both gate consumers read them. Correct them
    # HERE, at the call sites, so analyzer.py / smart_gate.py keep their single
    # responsibility. With no recipe this is the very same object (neutral).
    effective_analysis = _texture_corrected_analysis(analysis_result, texture_recipe)

    # The report gains ``texture_adaptation`` only when a recipe is present;
    # each decision below fills its entry. Absent key ⇒ nothing to say.
    texture_adaptation: dict[str, Any] | None = None
    if texture_recipe is not None:
        texture_adaptation = {
            "profile": texture_recipe["profile"],
            "seed": texture_recipe["seed"],
        }

    # Reduce intensity for already-mastered audio (only kicks in at score ≥ 0.8)
    already_mastered = (
        effective_analysis.is_already_mastered if effective_analysis else False
    )
    am_factor = 0.8 if already_mastered else 1.0

    # ── Transparent delivery mode (Compliance Phase 1) ───────────────
    # Early dedicated branch BEFORE any DSP: no gain staging, no EQ, no
    # dynamics, no saturation, no automatic loudness. The master path
    # below is left untouched for existing clients.
    if params.processing_mode == "transparent":
        return _process_transparent(
            audio,
            sr,
            params,
            output_path,
            already_mastered,
            report,
            warnings,
            texture_recipe=texture_recipe,
            texture_adaptation=texture_adaptation,
        )

    # ── Sample-rate conversion ──────────────────────────────────────
    # In master mode the normal path (no fast-path) runs at the target
    # rate so ALL SR-dependent DSP operates on the output grid; metrics are
    # measured at the output rate too.
    resolved_sr = _resolve_output_sr(params.output_sr, input_sr)
    if resolved_sr != input_sr:
        audio = resample_audio(audio, input_sr, resolved_sr)
        sr = resolved_sr
    report(8)

    # ── Neutral fast-path ──────────────────────────────────────────────
    # Contract (AGENTS.md + approved PLAN): MasteringParameters() with all
    # DEFAULT values = bit-exact bypass — the master must be identical to the
    # original. When the params equal the pristine defaults we write the exact
    # samples read back out (same sample rate, same channel count) and measure
    # the output metrics on the untouched audio so the response keeps the same
    # shape. `model_dump()` compares every field, current and future.
    if params.model_dump() == MasteringParameters().model_dump():
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # Write the samples read back out losslessly as a 32-bit float WAV.
        # Pedalboard's AudioFile.write downconverts float audio to 16-bit PCM
        # (lossy), which would break bit-exactness; soundfile with FLOAT
        # subtype reproduces the exact float32 samples read, yielding a
        # byte-identical file for float-WAV inputs.
        sample_blocks = audio.T if audio.ndim > 1 else audio
        sf.write(str(output_path), sample_blocks, sr, subtype="FLOAT")

        report(100)
        # Best-effort immediate release of the read/roundtrip buffers; the
        # neutral fast-path would otherwise pin the full buffer set in RAM.
        gc.collect()

        true_peak = true_peak_db(audio, sr)
        integrated_lufs = measure_lufs(audio, sr)
        crest_factor_db = calculate_crest_factor(audio)
        user_ceiling = _user_limiter_ceiling(
            params.limiter_ceiling_db, already_mastered
        )
        safe_ceiling = compute_codec_safe_ceiling(
            target_lufs=params.target_lufs_db
            if params.target_lufs_db is not None
            else -14 + (1.0 - params.limiter_ceiling_db / -0.3) * 6,
            crest_factor_db=crest_factor_db,
            default_ceiling_db=user_ceiling,
        )
        lra = measure_lra(audio, sr)

        return {
            "output_path": str(output_path),
            "sample_rate": sr,
            "channels": audio.shape[0],
            "duration_seconds": audio.shape[1] / sr,
            "true_peak_db": round(true_peak, 2),
            "integrated_lufs": round(integrated_lufs, 2),
            "crest_factor_db": round(crest_factor_db, 2),
            "limiter_ceiling_db": round(safe_ceiling, 2),
            "output_bit_depth": params.output_bit_depth,
            "codec_pre_matching": safe_ceiling < user_ceiling,
            "input_sr": input_sr,
            "output_sr": sr,
            "target_lufs": params.target_lufs_db,
            "warnings": warnings,
            "lra": round(lra, 2) if lra is not None else None,
        }

    # 1. Gain staging — normalize to consistent headroom
    audio, _ = gain_stage(audio, target_peak_db=-6.0)
    report(5)

    # 1a. Smart gate — Advisory Mode ─────────────────────────────────────
    # Returns advisory intensity_scales (0.3–1.0) per module instead of
    # blocking modules. The engine scales corrective processing
    # proportionally while preserving character; the gate NEVER blocks a
    # module to 0.0 and never touches delivery-critical stages (HPF,
    # spatial, mono-compat, loudness, soft-clip, limiter, dither).
    smart_gate = decide_smart_gate(
        params,
        effective_analysis,
        effective_ceiling_db=_user_limiter_ceiling(
            params.limiter_ceiling_db, already_mastered
        ),
    )
    smart_gate_active = bool(smart_gate["applied"])
    intensity_scales = smart_gate["intensity_scales"]

    if (
        texture_adaptation is not None
        and effective_analysis is not analysis_result
        and texture_recipe is not None
    ):
        _measured = texture_recipe["measured"]
        texture_adaptation["gate_correction"] = {
            "crest_delta_db": _measured["crest_delta_db"],
            "centroid_delta_hz": _measured["centroid_delta_hz"],
        }

    def module_intensity(module: str, apply_am_factor: bool = True) -> float:
        """Effective strength for an advisory-scalable stage.

        Combines the base corrective intensity, the smart gate's advisory
        scale and the already-mastered factor. ``am_factor`` applies ONLY to
        EQ/saturation — never to the limiter or the soft-clipper, which stay
        delivery-critical.

        When the gate is INACTIVE the advisory reduction does not apply at
        all: the stage keeps its full strength (``am_factor`` only). Applying
        ``BASE_MODULE_INTENSITY`` unconditionally would quietly weaken every
        non-gated master, which is exactly the silent regression the neutral
        contract forbids.
        """
        am = am_factor if apply_am_factor else 1.0
        if not smart_gate_active:
            return am
        scale = intensity_scales.get(module, 1.0)
        # A module with scale at the engaged floor (0.7) has an actively
        # engaged signature � a deliberate creative choice, not corrective
        # processing. The advisory gate must not reduce its intensity.
        if scale == SIGNATURE_SCALE_FLOOR:
            return am
        return BASE_MODULE_INTENSITY * scale * am

    # 1b. Dynamic de-esser (Phase B — B2) — sibilance 3-8 kHz tamed BEFORE
    #     the tonal/dynamics chain. Ordering rationale: (1) the detector
    #     reads the UNCOMPRESSED transient, where sibilance is most visible;
    #     (2) the 8 kHz clarity shelf then brightens already-de-essed
    #     material instead of re-emphasizing the harshness (the stages do
    #     not fight each other); (3) the compressors never pump on sibilant
    #     drive. NEUTRAL (disabled, or enabled with amount 0.0) = bit-exact
    #     bypass; material below the detector threshold also passes through
    #     bit-exactly (deesser_gain stays at exactly 0 dB).
    deesser_params = _deesser_params_from_mastering(params)
    # S3: a report must name a decision that was actually taken. The de-esser
    # is only "skipped" when it would OTHERWISE have run — enabled AND an
    # engaged (non-neutral) amount. With it disabled or at amount 0.0 the
    # render is the baseline and no skip happened, so nothing is reported.
    deesser_would_run = (
        params.deesser_enabled and not deesser_params.is_neutral()
    )
    deesser_skip_reason: str | None = None
    if deesser_would_run and texture_recipe is not None:
        _bed = texture_recipe["bed"]
        if _bed["applied"] and _bed["transient"]:
            # S4.2: crackle ticks are program, and the spike gate cannot tell
            # them from sibilance — the de-esser would cut deliberate content.
            deesser_skip_reason = "crackle_bed"
        elif texture_recipe["measured"]["band_limited_vocal"]:
            # A telephone-band vocal has nothing inside 3-8 kHz to act on.
            deesser_skip_reason = "band_limited_vocal"
    if deesser_would_run and deesser_skip_reason is None:
        audio = deesser(audio, sr, deesser_params)
    if (
        texture_adaptation is not None
        and deesser_would_run
        and deesser_skip_reason is not None
    ):
        texture_adaptation["deesser"] = {
            "skipped": True,
            "reason": deesser_skip_reason,
        }

    # ── Build Pedalboard chain ──────────────────────────────────────
    board = Pedalboard()

    # 2. High-pass filter (corrective — fixed at 30 Hz)
    board.append(HighpassFilter(cutoff_frequency_hz=30))

    # 3. Match EQ — genre-aware spectral targeting via analysis result.
    #    The advisory scale reduces the analysis-derived corrective instead of
    #    blocking it (an already-deliverable source needs less correction,
    #    not none). Uses empty eq_bands since module params provide per-band
    #    control.
    eq_plugins = []
    match_eq_intensity = module_intensity("match_eq", apply_am_factor=True)
    hf_texture_offset_db = _recipe_hf_excess_db(texture_recipe)
    if match_eq_intensity > _ADVISORY_MIN_INTENSITY:
        eq_plugins = build_match_eq(
            audio, sr, [], effective_analysis,
            intensity_multiplier=intensity_multiplier * match_eq_intensity,
            hf_texture_offset_db=hf_texture_offset_db,
        )
        if texture_adaptation is not None and hf_texture_offset_db > 0.0:
            texture_adaptation["match_eq_hf"] = {
                "hf_offset_db": float(
                    min(MATCH_EQ_HF_OFFSET_LIMIT_DB, hf_texture_offset_db)
                ),
            }
    for p in eq_plugins:
        board.append(p)

    # 3b. Preset character EQ — the preset's declared tonal signature
    #     (params.eq_bands, e.g. fuego's 80 Hz low-shelf punch). NEVER
    #     gated: unlike the analysis-derived match EQ, these bands ARE the
    #     preset's identity — the user picked fuego/espacial for exactly
    #     this character, and the smart gate only skips corrective stages.
    #     The neutral default ([] = no plugins) is what keeps every
    #     existing master bit-exact. Gains are scaled by am_factor exactly
    #     like the 8 kHz clarity shelf, so already-mastered material gets
    #     the same proportional character, not the full preset boost.
    if params.eq_bands:
        for cp in build_character_eq(params.eq_bands, gain_scale=am_factor):
            board.append(cp)

    # 4. Module EQ: Claridad — Brilliance (8 kHz shelf)
    clarity_intensity = module_intensity("clarity_shelf", apply_am_factor=True)
    if (
        params.clarity_brightness_db != 0
        and clarity_intensity > _ADVISORY_MIN_INTENSITY
    ):
        clarity_requested_db = params.clarity_brightness_db * clarity_intensity
        clarity_applied_db = clarity_requested_db
        hf_excess_db = _recipe_hf_excess_db(texture_recipe)
        if clarity_requested_db > 0.0 and hf_excess_db > 0.0:
            # S4.3: the boost is static and amplifies the deliberate noise floor.
            # Withdraw it by the declared HF excess, FLOORED at 0.0 dB — the
            # shelf may stop lifting the top, it may never invert into a cut
            # (and a requested brightness CUT is a different decision, untouched).
            clarity_applied_db = max(0.0, clarity_requested_db - hf_excess_db)
        if clarity_applied_db != 0.0:
            board.append(PeakFilter(
                cutoff_frequency_hz=8000,
                gain_db=clarity_applied_db,
                q=0.6,
            ))
        if (
            texture_adaptation is not None
            and clarity_applied_db != clarity_requested_db
        ):
            texture_adaptation["clarity_gain_db"] = {
                "requested": clarity_requested_db,
                "applied": clarity_applied_db,
            }

    # 5. Module EQ: Cinta — Warmth (high roll-off or air boost at 10 kHz)
    warmth_intensity = module_intensity("warmth_tilt", apply_am_factor=True)
    if (
        params.saturation_warmth_db != 0
        and warmth_intensity > _ADVISORY_MIN_INTENSITY
    ):
        board.append(PeakFilter(
            cutoff_frequency_hz=10000,
            gain_db=params.saturation_warmth_db * warmth_intensity,
            q=0.5,
        ))

    # 6. Compression — fixed −16 dB stage (Fuego / Empuje) vs the adaptive
    #    program-dependent compressor (Sprint 8). adaptive_comp_enabled
    #    replaces the fixed pedalboard compressor with the real module
    #    (threshold tracks input RMS, crest-adaptive attack/release,
    #    sidechain + makeup). NEUTRAL (ratio 1.0) = bit-exact bypass; the
    #    fixed stage is skipped entirely in that case too. The smart gate
    #    may skip the fixed stage when the source is already deliverable
    #    (its job is corrective/normalizing, and the adaptive module — a
    #    signature — is NEVER gated).
    if params.adaptive_comp_enabled:
        adaptive_params = _adaptive_comp_params_from_mastering(params)
        adaptive_needs_board = True
        if adaptive_params.is_neutral():
            pass  # adaptive neutral — skip compression entirely
        # else: the module runs on `effected` AFTER the board() call below
        # (like the 7b multiband stage): it needs the post-EQ signal.
    else:
        # Fixed proportional compression — threshold from input RMS.
        # Module: Fuego / Empuje — compression ratio + transient boost.
        # The advisory scale reduces the squeeze proportionally; the
        # adaptive module above is a signature and is NEVER scaled.
        comp_intensity = module_intensity("compressor", apply_am_factor=True)
        if comp_intensity > _ADVISORY_MIN_INTENSITY:
            comp_threshold_db = -16 - (params.transient_boost_db * 1.5)
            comp_ratio = params.compression_ratio * comp_intensity
            comp_attack = max(3, 20 - params.transient_boost_db * 3)  # faster attack = more punch
            board.append(
                Compressor(
                    threshold_db=comp_threshold_db,
                    ratio=max(1.0, comp_ratio),
                    attack_ms=comp_attack,
                    release_ms=200,
                )
            )
        adaptive_needs_board = False

    # 7. Process through Pedalboard (EQ, compression)
    effected = board(audio, sr)
    report(18)

    # 7a. Adaptive compressor (Sprint 8) — program-dependent threshold
    #     T(t) = RMS(t) − offset, crest-adaptive attack/release, applied
    #     right after the (skipped) fixed stage. NEUTRAL (ratio 1.0) is a
    #     bit-exact bypass, so existing masters are untouched unless the
    #     parameter engages it.
    if adaptive_needs_board:
        effected = adaptive_compress(effected, sr, adaptive_params)

    # 7b. Multiband compressor (Sprint 4) — LR4 crossovers + per-band
    #     detector, right after the fixed compressor (it does NOT replace
    #     the fixed stage; Sprint 8's adaptive compressor does). NEUTRAL by
    #     default (ratio 1:1 = bit-exact bypass), so existing masters are
    #     untouched unless the parameter engages it.
    if params.multiband_enabled:
        multiband_params = _multiband_params_from_mastering(
            params, recipe=texture_recipe
        )
        _report_threshold_decision(
            texture_adaptation,
            "multiband_high",
            params.multiband_high_threshold_db,
            multiband_params.bands[2].threshold_db,
        )
        effected = multiband_compress(effected, sr, multiband_params)

    # 7c. Dynamic EQ (Sprint 5) — fixed bell/Q filters, gain depends on
    #     input energy. Cuts only, only when the problem exists. NEUTRAL by
    #     default (ratio 1:1 = bit-exact bypass).
    if params.dyn_eq_enabled:
        dyn_eq_params = _dyn_eq_params_from_mastering(params, recipe=texture_recipe)
        _report_threshold_decision(
            texture_adaptation,
            "dyn_eq_hf",
            params.dyn_eq_band3_threshold_db,
            dyn_eq_params.bands[2].threshold_db,
        )
        effected = dynamic_eq(effected, sr, dyn_eq_params)

    # 7d. Harmonic exciter (Sprint 6) — parallel harmonic generation per band
    #     (Ozone style: bass/tube/tape/air), restores air/body lost after the
    #     compression stages. NEUTRAL by default (amount 0.0 = bit-exact bypass).
    if params.exciter_enabled:
        exciter_params = _exciter_params_from_mastering(params)
        # S3/S4.4: the exciter is only "held neutral" when it would otherwise
        # have engaged — every amount at 0.0 is already its neutral path, so
        # reporting a held decision there would name one that was never taken.
        exciter_would_engage = any(
            b.amount != 0.0 for b in exciter_params.bands
        )
        if texture_recipe is not None and texture_recipe["bed"]["applied"]:
            # S4.4: exciter.py has no level gate (its only guard is _is_neutral),
            # so it would synthesize harmonics FROM the deliberate bed and
            # corrupt the texture it is meant to sit on top of. Hold it at 0
            # (the existing neutral path) and report it — but only when it would
            # otherwise have engaged.
            if texture_adaptation is not None and exciter_would_engage:
                texture_adaptation["exciter"] = {"held_neutral": True}
        else:
            pre_exciter = effected
            effected = excite(effected, sr, exciter_params)
            effected = _match_peak(pre_exciter, effected)

    report(30)

    report(30)

    def _adapt_spatial_for_mix_context(
        params: MasteringParameters,
        mix_meta: "MixMetadata",
    ) -> MasteringParameters:
        """Adjust mastering spatial parameters based on mix context.

        Prevents double-processing when the mix already applied spatial
        expansion, reverb, or side energy.
        """
        adapted = params.model_copy()

        # 1. Throttle legacy stereo_width (broadband M/S gain)
        if mix_meta.applied_spatial_width > 1.2:
            excess = mix_meta.applied_spatial_width - 1.2
            adapted.stereo_width = max(1.0, adapted.stereo_width - excess * 0.5)

        # 2. Throttle stereo_imaging (Sprint 9, per-band width)
        if mix_meta.applied_spatial_width > 1.15 and adapted.stereo_imaging_enabled:
            adapted.stereo_imaging_width_high = min(
                getattr(adapted, 'stereo_imaging_width_high', 1.3), 1.15
            )
            adapted.stereo_imaging_width_mid = min(
                getattr(adapted, 'stereo_imaging_width_mid', 1.1), 1.05
            )

        # 3. Side HPF more aggressive if side energy high
        if mix_meta.side_energy_ratio > 0.35:
            adapted.side_hpf_enabled = True
            adapted.side_hpf_hz = min(
                getattr(adapted, 'side_hpf_hz', 100.0), 150.0
            )

        # 4. Limiter ceiling conservative if little headroom
        if mix_meta.transient_headroom_db < 1.0:
            adapted.limiter_ceiling_db = min(adapted.limiter_ceiling_db, -1.5)

        return adapted

    # ── Mix→Master Adaptive Context ────────────────────────────────────
    # If mix_metadata is present (source="mix"), adapt spatial params to
    # avoid double-processing what the mix already did.
    if mix_metadata:
        from audiomind.models.mix_metadata import MixMetadata
        # S2: the recipe is data from another service, not configuration, so a
        # wrong-typed one must degrade to the ordinary render and never raise.
        # ``MixMetadata`` types ``texture_recipe`` as a dict since P4, so a
        # list/str/int payload would otherwise crash this pre-existing parse
        # site (ValidationError). Sanitize ONLY the field this feature added —
        # the other MixMetadata fields keep their pre-existing strictness — and
        # name the reason once (the lenient reader above already appended it),
        # so the render is exactly the no-recipe path.
        raw_recipe = mix_metadata.get("texture_recipe")
        if raw_recipe is not None and not isinstance(raw_recipe, dict):
            mix_metadata = {**mix_metadata, "texture_recipe": None}
            if TEXTURE_WARNING_MALFORMED not in warnings:
                warnings.append(TEXTURE_WARNING_MALFORMED)
        mix_meta = MixMetadata(**mix_metadata)
        params = _adapt_spatial_for_mix_context(params, mix_meta)

    # ── Spatial Processing: M/S with Reverb + Haas + Width ──────────
    from .spatial import (
        apply_frequency_dependent_width,
        apply_side_hpf,
        check_phase_correlation,
        mid_side_decode,
        mid_side_encode,
        safety_enforce_correlation,
    )

    if (params.clarity_wet > 0
            or (params.stereo_width != 1.0 and not params.stereo_imaging_enabled)
            or params.haas_delay_ms > 0
            or params.side_hpf_enabled):
        mid, side = mid_side_encode(effected)

        # 7a. Reverb on Side (Clarity module)
        if params.clarity_wet > 0:
            from pedalboard import Reverb

            # Wet level scales with clarity_wet (0.0 → 1.0)
            wet = min(0.15, params.clarity_wet * 0.15)
            board_rev = Pedalboard([
                Reverb(
                    room_size=0.3 + params.clarity_wet * 0.3,
                    damping=0.5,
                    wet_level=wet,
                    dry_level=1.0 - wet,
                    width=1.0,
                )
            ])
            side = board_rev(
                side.reshape(1, -1).astype(np.float32), sr
            ).flatten().astype(np.float64)

        # 7b. Haas delay on Side (Espacial / Cinemático module)
        if params.haas_delay_ms > 0:
            delay_samples = int(sr * params.haas_delay_ms / 1000)
            if delay_samples > 0 and delay_samples < len(side):
                delayed = np.zeros_like(side)
                delayed[delay_samples:] = side[:-delay_samples]
                mix = min(0.5, params.haas_delay_ms / 80.0)
                side = side * (1 - mix) + delayed * mix

        # 7b'. Side low-end clean (Phase B — B1): high-pass the SIDE below
        #      ~100 Hz (sub-bass room mud). Complementary to — never
        #      competing with — the <120 Hz mono collapse (stage 9): the
        #      HPF cleans the decorrelated sub-bass BEFORE the width stage
        #      can spread it, while the late collapse still forces the lows
        #      to mono center. Cutoff anchor: below mono-compat's 120 Hz,
        #      above the corrective 30 Hz master HPF (stage 2).
        if params.side_hpf_enabled:
            side = apply_side_hpf(side, sr, cutoff_hz=params.side_hpf_hz)

        # 7c. Stereo width (M/S gain) — legacy broadband width. Skipped when
        #     the per-band stereo imaging stage (Sprint 9) is enabled, which
        #     owns the width via constant-power per-band gains.
        if params.stereo_width != 1.0 and not params.stereo_imaging_enabled:
            width_factor = params.stereo_width
            mid = mid * (2.0 / (1.0 + width_factor))  # reduce mid as width increases
            side = side * width_factor

        effected = mid_side_decode(mid, side)

        # Phase correlation safety
        corr = check_phase_correlation(effected)
        if corr < 0:
            effected = safety_enforce_correlation(effected, sr)

    # ── Stereo Shuffler 3-Band (Mix→Master Handshake) ─────────────────
    # Mutually exclusive with legacy broadband width: when enabled, the
    # legacy broadband width stage is skipped. Runs BEFORE stereo imaging
    # (Sprint 9) so the per-band width can further refine if needed.
    if params.stereo_shuffler_enabled:
        from .spatial import apply_frequency_dependent_width
        effected = apply_frequency_dependent_width(
            effected, sr,
            width_low=params.stereo_shuffler_width_low,
            width_mid=params.stereo_shuffler_width_mid,
            width_high=params.stereo_shuffler_width_high,
            crossover_low=params.stereo_shuffler_crossover_low,
            crossover_high=params.stereo_shuffler_crossover_high,
        )

    # 7e. Per-band stereo imaging (Sprint 9) — LR4 3-band constant-power
    #     width + lows-mono + correlation safety. This is the correlation-safe
    #     replacement for the legacy broadband width cut (linear 2/(1+w),
    #     which risks a center hole). DISABLED by default (bit-exact bypass),
    #     so existing masters are untouched unless explicitly engaged. When
    #     engaged it runs AFTER the legacy spatial block (reverb/Haas) and
    #     BEFORE saturation, exactly like the broadband width it replaces.
    if params.stereo_imaging_enabled:
        stereo_params = _stereo_imaging_params_from_mastering(params)
        if not stereo_params.is_neutral():
            effected = apply_stereo_imaging(effected, sr, stereo_params)
        stereo_imaging_mono_applied = stereo_params.mono_below_hz > 0.0
    else:
        stereo_imaging_mono_applied = False

    # 7f. Time-based effects (Sprint 10) — delay, echo and reverb as opt-in
    #     insert stages between the dynamics/spatial chain and the final
    #     limiter (time effects belong BEFORE limiting so the wet tails are
    #     caught by the clipper/limiter, not after it). Each stage follows
    #     the same opt-in contract as the other modules: enabled=False — or
    #     enabled with mix 0.0 — is a bit-exact bypass, so existing masters
    #     are untouched unless a mix knob moves. They run AFTER the spatial
    #     stages and BEFORE the tape saturation, so the echoes feed the
    #     real-tape model — the classic "tape echo" insert order.
    if params.delay_enabled:
        delay_params = _delay_params_from_mastering(params)
        if not delay_params.is_neutral():
            effected = delay_pass(effected, sr, delay_params)
    if params.echo_enabled:
        echo_params = _echo_params_from_mastering(params)
        if not echo_params.is_neutral():
            effected = echo_pass(effected, sr, echo_params)
    if params.reverb_enabled:
        reverb_params = _reverb_params_from_mastering(params)
        if not reverb_params.is_neutral():
            effected = reverb_pass(effected, sr, reverb_params)

    report(45)

    # 8. Saturation (Cinta / Tape module) — boosted by intensity_multiplier
    #    with the advisory intensity scale. Sprint 7: when tape_enabled, the
    #    REAL tape model (hysteresis + level-dependent HF roll-off) replaces
    #    the legacy tanh shaper; the legacy path stays for tape_enabled=False
    #    so existing masters are unchanged. NEUTRAL (drive 0, no
    #    hysteresis/bias/roll-off) is a bit-exact bypass.
    sat_intensity = module_intensity("saturation", apply_am_factor=True)
    sat_drive = params.saturation_drive_db * intensity_multiplier * sat_intensity
    if params.tape_enabled:
        tape_params = _tape_params_from_mastering(params)
        if tape_params.is_neutral():
            pass  # real tape neutral — leave signal untouched
        else:
            pre_sat = effected
            effected = tape_saturate(effected, sr, tape_params)
            effected = _match_peak(pre_sat, effected)
    elif sat_drive > 0:
        pre_sat = effected
        effected = _apply_saturation(effected, sat_drive, "tape")
        effected = _match_peak(pre_sat, effected)

    report(55)

    # 9. Mono compatibility (force low frequencies to mono center).
    #     Skipped when the Sprint 9 per-band stage already collapsed the
    #     lows (its mono_below_hz > 0), because applying the legacy collapse
    #     on top of it is NOT idempotent — it re-filters and shifts the
    #     lows again. The Sprint 9 collapse is bit-identical to this one.
    if not stereo_imaging_mono_applied:
        effected = enforce_mono_compatibility(effected, sr, cutoff_hz=120)

    report(60)

    # 10. LUFS targeting — target moderate commercial loudness
    #     The limiter ceiling is the main loudness control via params
    if params.target_lufs_db is not None:
        target_lufs_val = params.target_lufs_db
    else:
        # Automatic loudness target. Clamped to the streaming-safe range:
        # never hotter than -12 LUFS (Spotify/YouTube/Tidal normalize at -14,
        # Apple at -16; louder masters are attenuated by the platforms while
        # carrying over-compression and distortion).
        target_lufs_val = -14 + (1.0 - params.limiter_ceiling_db / -0.3) * 6
        target_lufs_val = max(-14, min(-12, target_lufs_val))
    loudness_delta_lu = (
        texture_recipe["measured"]["loudness_delta_lu"]
        if texture_recipe is not None
        else 0.0
    )
    effected = target_lufs(
        effected, sr, target_lufs_val, loudness_delta_lu=loudness_delta_lu
    )
    if texture_adaptation is not None and loudness_delta_lu != 0.0:
        # S5: normalise the PROGRAM, not the noise. The consequence is stated,
        # not implied: the final integrated LUFS reads higher than the target by
        # exactly this delta, because the bed is legitimately program now.
        texture_adaptation["loudness_compensation_lu"] = loudness_delta_lu
    report(70)

    # ── Codec Pre-Matching ──────────────────────────────────────────
    # 11a. Measure crest factor for codec safety analysis
    crest_factor_db = calculate_crest_factor(effected)

    # 11b. Dynamically adjust ceiling based on loudness + crest factor
    #      Module: Fuego/Empuje — limiter_ceiling controls loudness ceiling
    lufs_target_actual = target_lufs_val
    user_ceiling = _user_limiter_ceiling(params.limiter_ceiling_db, already_mastered)
    safe_ceiling = compute_codec_safe_ceiling(
        target_lufs=lufs_target_actual,
        crest_factor_db=crest_factor_db,
        default_ceiling_db=user_ceiling,
    )

    # 11b'. Oversampled soft-clipper (Sprint 3) — trims transients BEFORE the
    #       true-peak limiter so the limiter sustains the body instead of
    #       catching every peak (KClip/Ozone "modern loudness"). The 16x
    #       erf knee keeps aliasing below -90 dBFS; the threshold sits a
    #       fixed margin below the ceiling, and material below it passes
    #       through bit-exactly (neutral default).
    clipper_threshold_db = safe_ceiling - CLIPPER_HEADROOM_DB
    effected = soft_clip(effected, sr, threshold_db=clipper_threshold_db)

    # 11c. Final True Peak limiting (catches overshoot from LUFS gain)
    #     Uses the codec-safe ceiling when appropriate
    effected = final_limit(effected, sr, ceiling_db=safe_ceiling)
    report(82)

    # 12. Safety: prevent any clipping
    max_val = np.max(np.abs(effected))
    if max_val > 1.0:
        effected = effected / max_val * 0.99

    # ── Dithering (high-quality export preparation) ─────────────────
    #     Applies TPDF dither with 2nd-order noise shaping to push
    #     quantization noise above 15 kHz.
    #     The output remains float [-1, 1]; actual bit reduction
    #     happens during WAV write or ffmpeg conversion.
    #     Dithering pre-distorts the float signal so the noise floor
    #     after quantization inherits the shaped spectrum.
    if params.output_bit_depth == 16:
        effected = apply_dither_noise_shaping(
            effected, target_bit_depth=16, sample_rate=sr
        )
    elif params.output_bit_depth <= 24:
        # 24-bit: apply TPDF dither only (no noise shaping needed,
        # as the noise floor is already at -144 dBFS)
        pass

    report(88)

    # 13. Dynamic range validation (Phase A — A3)
    #     Measured so the Layer 2 gate can judge the delivered master
    #     against the input dynamics (absolute floor + collapse ratio).
    input_dr_db = measure_dynamic_range(audio, sr)  # post-gain-staging input
    output_dr_db = measure_dynamic_range(effected, sr)
    dr_ratio = None
    if input_dr_db > 0:
        dr_ratio = output_dr_db / input_dr_db

    # Write output — explicit PCM subtype (honors output_bit_depth; the
    # pedalboard AudioFile writer silently downconverts to 16-bit PCM).
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_output(effected, output_path, sr, params.output_bit_depth)

    # Release the DSP buffers (input read, each stage's intermediate arrays,
    # the final output grid) immediately after the WAV export. On the 1GB
    # Railway node uncollected Numpy buffers across sequential presets can
    # push the container toward OOM; a single forced collection right after
    # the write reclaims the big transient arrays deterministically.
    gc.collect()
    report(95)

    # Measure output metrics
    true_peak = true_peak_db(effected, sr)
    integrated_lufs = measure_lufs(effected, sr)
    lra = measure_lra(effected, sr)
    stereo_correlation = measure_stereo_correlation(effected)

    result: dict[str, Any] = {
        "output_path": str(output_path),
        "sample_rate": sr,
        "channels": effected.shape[0],
        "duration_seconds": effected.shape[1] / sr,
        "true_peak_db": round(true_peak, 2),
        "integrated_lufs": round(integrated_lufs, 2),
        "crest_factor_db": round(crest_factor_db, 2),
        "limiter_ceiling_db": round(safe_ceiling, 2),
        "output_bit_depth": params.output_bit_depth,
        "codec_pre_matching": safe_ceiling < user_ceiling,
        "input_sr": input_sr,
        "output_sr": sr,
        "target_lufs": target_lufs_val,
        "warnings": warnings,
        "lra": round(lra, 2) if lra is not None else None,
        "stereo_correlation": (
            round(stereo_correlation, 3) if stereo_correlation is not None else None
        ),
        "dr_ratio": round(dr_ratio, 3) if dr_ratio is not None else None,
        "smart_gate": smart_gate if smart_gate_active else None,
    }
    # S3: the report gains ``texture_adaptation`` ONLY when a recipe was read.
    # No recipe ⇒ no key ⇒ every key of the returned dict is exactly today's.
    if texture_adaptation is not None:
        result["texture_adaptation"] = texture_adaptation
    return result
    

# ═══════════════════════════════════════════════════════════════
# FASE 1: compute_input_metrics — diagnóstico de entrada BS.1770
# ═══════════════════════════════════════════════════════════════

def compute_input_metrics(audio: np.ndarray, sr: int) -> dict:
    """Métricas absolutas de entrada antes de cualquier procesamiento DSP.

    Usa integrated_loudness (K-weighting BS.1770-4) para LUFS,
    true_peak_db para true-peak, y cálculos RMS/Crest/LRA propios.
    """
    # LUFS integrados (BS.1770-4 con K-weighting)
    lufs = integrated_loudness(audio, sr)

    # True peak (máximo absoluto en dBTP)
    true_peak = float(np.max(np.abs(audio)))
    true_peak_db = 20.0 * np.log10(true_peak) if true_peak > 0 else -120.0

    # RMS y Crest Factor
    rms = float(np.sqrt(np.mean(audio ** 2)))
    rms_db = 20.0 * np.log10(rms) if rms > 0 else -120.0
    crest_factor_db = true_peak_db - rms_db if rms > 0 else float("inf")

    # LRA simplificada: rango entre percentiles 10% y 90% de la magnitud
    magnitudes = np.abs(audio).flatten()
    sorted_mags = np.sort(magnitudes)
    floor_idx = max(1, int(0.10 * len(sorted_mags)))
    ceiling_idx = min(len(sorted_mags) - 1, int(0.90 * len(sorted_mags)))
    lra = float(sorted_mags[ceiling_idx] - sorted_mags[floor_idx]) if len(sorted_mags) > 1 else 0.0
    lra_db = 20.0 * np.log10(lra) if lra > 0 else 0.0

    # Muestras clipeadas (|s| >= 1.0)
    clipped_samples = int(np.sum(np.abs(audio) >= 1.0))

    return {
        "integrated_lufs": lufs,
        "true_peak_dbtp": true_peak_db,
        "rms_dbfs": rms_db,
        "crest_factor_db": crest_factor_db,
        "lra_lu": lra_db,
        "clipped_samples": clipped_samples,
    }


# ═══════════════════════════════════════════════════════════════
# FASE 2: categorize_audio — clasificación Rama A / Rama B
# ════════════════════════════════════════════════════════════════

# Umbrales de categorización (según la especificación)
_BRANCH_A_LUFS_THRESHOLD = -12.5  # Rama A si integrated_lufs > this
_BRANCH_A_PEAK_THRESHOLD = -0.1    # Rama A si true_peak > this (dBTP)
_BRANCH_B_LUFS_THRESHOLD = -13.5   # Rama B si integrated_lufs < this


def categorize_audio(integrated_lufs: float, true_peak_dbtp: float) -> str:
    """Clasifica el audio en Rama A u operativa Rama B.

    Rama A: audio "sobreprocesado/caliente" — requiere normalización transparente.
    Rama B: audio "dinámico/bajo nivel" — requiere densidad comercial y ganancia.
    """
    # Rama A: si supera el umbral de LUFS o true-peak
    if integrated_lufs > _BRANCH_A_LUFS_THRESHOLD or true_peak_dbtp > _BRANCH_A_PEAK_THRESHOLD:
        return "A"
    # Rama B: si está por debajo del umbral de LUFS más bajo
    if integrated_lufs < _BRANCH_B_LUFS_THRESHOLD:
        return "B"
    # Borde intermedio: default conservador a Rama B (no sobreprocesar)
    return "B"


# ════════════════════════════════════════════════════════════════
# FASE 3: validation_loop — bucle iterativo de autocorrección
# ════════════════════════════════════════════════════════════════

MAX_PASSES = 3
TARGET_TOLERANCE_LUFS = 0.3
CEILING_LIMIT_DBTP = -1.0


def validation_loop(audio_in: np.ndarray,
                    target_lufs: float,
                    target_dbtp: float,
                    params: MasteringParameters,
                    max_passes: int = MAX_PASSES) -> tuple:
    """Bucle iterativo de validación posterior al renderizado DSP.

    Hasta max_passes iteraciones ajustando trim y ceiling para converger
    a la diana LUFS y respetar el techo de true-peak.

    Retorna (audio_final, params_actualizados, pasadas_necesarias).
    """
    from audiomind.processing.engine import process_audio

    current_params = params
    for pass_idx in range(max_passes):
        # Renderizar cadena DSP con params actuales
        rendered_result = process_audio(
            input_path=None,  # working with in-memory audio
            output_path=None,
            params=current_params,
            analysis_result=None
        )

        # Medir métricas del renderizado
        measured_lufs = rendered_result.get("integrated_lufs", float("nan"))
        measured_peak = rendered_result.get("true_peak_db", float("nan"))

        # Verificar techo de true-peak
        if measured_peak > target_dbtp:
            # Reajustar trim hacia abajo proporcionalmente
            delta = measured_peak - target_dbtp
            current_params = _adjust_trim(current_params, -delta)
            current_params = _adjust_ceiling(current_params, -delta)
            continue

        # Verificar si LUFS objetivo alcanzado
        lufs_error = abs(measured_lufs - target_lufs)
        if lufs_error <= TARGET_TOLERANCE_LUFS:
            return rendered_result.get("output_path", None), current_params, pass_idx + 1

        # Ajuste proporcional: direction y magnitude del error
        if measured_lufs > target_lufs:
            # Estamos por encima del objetivo — recorte ligero
            current_params = _adjust_trim(current_params, -0.5)
        else:
            # Estamos por debajo del objetivo — ligera ganancia
            current_params = _adjust_trim(current_params, +0.5)

        # Clamping de trim a rangos físicos
        current_params = _clamp_trim(current_params)

    # Si agotamos passes, retornar último estado
    rendered_result = process_audio(
        input_path=None, output_path=None, params=current_params, analysis_result=None
    )
    return rendered_result.get("output_path", None), current_params, max_passes


def _adjust_trim(params: MasteringParameters, delta: float) -> MasteringParameters:
    """Ajusta el parámetro trim de los params por un delta (en LUFS)."""
    # MasteringParameters debe tener un field 'trim' — verificamos y ajustamos
    # Si no existe, creamos una copia con el ajuste aplicado
    new_params = params.model_copy()
    # Asumimos que params tiene un field trim (lo agregaremos en la Fase 4)
    if hasattr(new_params, 'trim'):
        new_params.trim = max(-20.0, min(20.0, (new_params.trim or 0) + delta))
    return new_params


def _adjust_ceiling(params: MasteringParameters, delta: float) -> MasteringParameters:
    """Ajusta el ceiling del limitador por un delta (en dBTP)."""
    new_params = params.model_copy()
    if hasattr(new_params, 'limiter_ceiling_db'):
        new_params.limiter_ceiling_db = max(-6.0, min(0.0, (new_params.limiter_ceiling_db or -1.0) + delta))
    return new_params


def _clamp_trim(params: MasteringParameters) -> MasteringParameters:
    """Clamps trim to physically meaningful range [-20, +20] LU."""
    new_params = params.model_copy()
    if hasattr(new_params, 'trim'):
        new_params.trim = max(-20.0, min(20.0, new_params.trim or 0))
    return new_params


def _apply_saturation(audio: np.ndarray, drive_db: float, sat_type: str) -> np.ndarray:
    """
    Apply subtle saturation (soft-clip or tape simulation).
    Drive is scaled to stay musical — never aggressive.
    """
    if drive_db <= 0:
        return audio

    # Scale drive to a musical range (0-1 internal)
    drive = min(drive_db / 10.0, 1.0)

    if sat_type == "tape":
        # Tape saturation: gentle soft-clipping with even harmonics
        k = drive * 5
        for ch in range(audio.shape[0]):
            x = audio[ch]
            audio[ch] = np.tanh(x * (1 + k)) / np.tanh(1 + k)
    else:
        # Soft-clip saturation
        k = drive * 8
        for ch in range(audio.shape[0]):
            x = audio[ch]
            audio[ch] = ((1 + k) * x) / (1 + k * np.abs(x))

    return audio