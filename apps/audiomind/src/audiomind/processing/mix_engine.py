"""Mix Engine — per-stem routing (Paso 02: split → EQ mágico → bus).

Skeleton of the live Mix Engine: takes a session's audio, runs source
separation through ``split_audio`` (Demucs), routes every stem onto a
stereo mono-compatible bus, pads each stem to the longest one, writes the
result with ``write_output`` and produces per-stem analysis (LUFS /
dynamic range / spectral centroid) plus full-mix analysis (tempo / genre
/ confidence).

Since Paso 02 each stem follows the DAW chain (fader → pan → EQ →
compresor → sends, ``VIABILIDAD_MOTOR_DE_MEZCLA.md`` línea 214): Paso 02
added the EQ (``magic_frequencies.py``, Owsinski pág. 32 — cuts first →
boosts after), Paso 03 inserts the role PAN *before* the EQ plus the
positional validation (``panorama.py``): vocals/bass/drums → center,
other → inside the extremes, gross violations clamped-corrected with a
−3 dB pan law, mono check on the resulting bus. ``profiles={}`` restores
the Paso 01 NEUTRAL routing for EQ; ``pan_profiles={}`` keeps the exact
Paso 02 routing (no pan, no ``pan_report`` key). Paso 04 inserts the
TEMPO DIMENSION right after the EQ (``dimension.py``: tempo delay +
Schroeder reverb per stem with pre-delay and return EQ by layering;
``dimension_profiles={}`` restores the exact Paso 03 routing — no
dimension, no ``dimension_report`` key). PASO 05 inserted the
 COMPRESSOR between the EQ and the dimension/sends (``dynamics.py`` —
 book recipes per stem, drums by spectral segment through the existing
 ``LinkwitzRiley4``, breathing at tempo from the measured BPM) and
 compresses the STEREO BUS after the stem sum (Jerry Finn technique, 2–3
 dB total); ``compressor_profiles={}`` restores the exact Paso 04 routing
 — no compressor, no ``compressor_report`` key. PASO 06 (this step) adds
 the GENRE EMPHASIS — the "Interest" balance of the book (Ch8 pág. 58–60,
 the plan's honest mitigation of the last least-automatable element): the
 genre detected on the source maps into a vocal-forward/groove-forward
 weight pair (``emphasis.py``) that scales the per-stem dimension sends
 INSIDE the engine's standard ranges (reverb mix/size, delay mix) and the
 bus GR target inside the 2–3 dB recipe band; unknown genre or confidence
 below ``CONFIDENCE_THRESHOLD`` falls back to the NEUTRAL 0.5/0.5 weights
 — the exact Paso 05 routing — and ``emphasis_profiles={}`` restores that
 routing unconditionally (no ``emphasis_report`` key). Final per-stem
 chain: pan → EQ → compressor → dimension(sends) → bus; the bus
 compresses after the sum.

Neutrality contract (spec 08): in the backend a neutral parameter equals
bit-identical audio; the routing equivalent of that contract is 0 dB
gains with 1:1 summing. The recombined mix is NOT bit-exact to the
original because Demucs separation is lossy by nature — accepted and
documented (pitfall 7). The EQ passthrough itself (empty/zero bands) IS
bit-exact, the dimension stage is a same-object no-op when its
profiles/mix are neutral (or no valid tempo exists — Alex guard), and
the compressor stage is a same-object no-op for ``None``/empty/ratio-1:1
profiles (``apply_stem_compression`` enforces the same-object guarantee
because ``adaptive_comp`` returns a copy in ratio-1 mode — documented in
``dynamics.py``). The Paso 06 emphasis scaling is another neutral no-op:
at 0.5/0.5 weights the multipliers are exactly 1.0 (scaled profiles
carry the base values) and the bus falls back to the original
``apply_bus_compression`` path whenever the scaled GR target equals the
base one — identical value, identical behaviour.

PASO 07 adds the QC REPORT and the ALTERNATIVE VERSIONS. After the bus
compression and BEFORE the write, ``qc_report`` runs on the FINAL bus
(``quality_checks.run_qc_checks``: mono/fase reusing the panorama
internals, sibilance 4–7 kHz, muddy 200–300 Hz, honky 450–600 Hz and
the measurable "low-level listen" proxies — informational flags that
NEVER block the render; blocking is a human decision per the plan).
``with_versions=True`` (default) renders the five alternative WAVs
from the SAME processed stems (``render_versions.render_version_buses``
— vocals-only trims: principal 0 dB, vocal ±0.75 dB, instrumental /
tv_mix silence the vocals) with the same mix-bus compressor applied to
each bus (DAW-real: the 2-bus reacts to the fader move). The principal
path is byte-identical to Paso 06 — versions are separate files and
never perturb it.

PASO 08 adds the CREATIVE MODE (``creative.py`` — "exploración creativa
acotada"): ``creative_seed`` + ``creativity`` (0..1) + ``creative_variants``
draw N variants INSIDE the standard envelope (continuous space by user
requirement — never finite presets), each re-routed from the SAME
resampled stems (no re-split) with its own pan → EQ → compressor →
dimension chain, its own bus recipe and its own vocal trim, validated
against the positional/QC gate (rejection sampling, ``MAX_CREATIVE_ATTEMPTS``
per variant — the batch never blocks). ``creativity=0`` is the strict
standard: every variant reproduces the base routing (bit-identical
principal) and the principal render is byte-identical with or without
the creative block. Accepted variant files land at
``outputs/{session_id}_mix_creative_{i}.wav``. ``creative_manual=True``
marks the output ``non_standard`` instead of rejecting it ("no se
bloquea").
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from audiomind.config import settings
from audiomind.processing.adaptive_comp import AdaptiveCompressor
from audiomind.processing.creative import (
    apply_variant_to_profiles,
    run_creative_mode,
)
from audiomind.processing.dimension import (
    DIMENSION_PROFILES,
    apply_stem_dimension,
)
from audiomind.processing.dynamics import (
    BUS_COMPRESSOR_PROFILE,
    BUS_GR_MAX_DB,
    BUS_TECHNIQUE_NOTE,
    STEM_COMPRESSOR_PROFILES,
    _nominal_times,
    _params_from_profile,
    apply_bus_compression,
    apply_stem_compression,
)
from audiomind.processing.emphasis import (
    GENRE_EMPHASIS_PROFILES,
    resolve_emphasis,
    scale_bus_profile,
    scale_dimension_profile,
)
from audiomind.processing.io_write import write_output
from audiomind.processing.magic_frequencies import MAGIC_PROFILES, apply_stem_eq
from audiomind.processing.panorama import PAN_ROLE_PROFILES, validate_positions
from audiomind.processing.quality_checks import run_qc_checks
from audiomind.processing.render_versions import (
    VERSION_DESCRIPTIONS,
    VERSION_TRIMS_DB,
    render_version_buses,
)
from audiomind.processing.resample import resample_audio
from audiomind.processing.splitter import STEM_NAMES, split_audio
from audiomind.processing.stem_balance import compute_stem_balance
from audiomind.models.mix_metadata import MixMetadata
from audiomind.processing.spatial import mid_side_encode

#: Per-stem fields extracted from ``AnalysisResult`` (spec: LUFS/DR/centroid).
_STEM_ANALYSIS_FIELDS: tuple[str, ...] = (
    "integrated_lufs",
    "dynamic_range_db",
    "spectral_centroid",
    "sample_rate",
)


#: Layering rule reported by the dimension stage (book págs. 37–38).
_DIMENSION_LAYERING_NOTE = "longest reverb brightest, shortest darkest"


#: RMS threshold (dBFS) for a stem to count as PRESENT in the mix.
#:
#: Demucs always emits the 4 stems (drums/bass/other/vocals), but a song
#: without drums or bass (or an a cappella) leaves that stem at digital
#: silence or a tiny model residue. ``stem_presence`` reports which stems
#: are ACTUALLY audible so the UI can honestly name only the instruments
#: that are in the material. Justification:
#:   - digital silence measures ≈ −inf dBFS from the all-zero samples;
#:   - a missing stem's demucs residue sits well below −70 dBFS (model
#:     noise floor, far under any musical content);
#:   - a genuinely present stem almost never dips under ≈ −40 dBFS RMS
#:     (≈ 1 % amplitude) even in its quietest passage;
#:   - −50 dBFS (≈ 0.3 % amplitude) splits both populations with margin.
STEM_PRESENCE_RMS_DBFS_THRESHOLD = -50.0


def _stem_rms_db(audio: np.ndarray) -> float:
    """RMS level of a stem (any float layout) in dBFS.

    ``20*log10(sqrt(mean(x**2)))``; digital silence (or an empty array)
    returns exactly ``-inf`` so it never clears the presence threshold.
    Returns a native Python float — the value travels straight into a
    JSON payload later.
    """
    x = np.asarray(audio)
    if x.size == 0:
        return -np.inf
    mean_sq = float(np.mean(np.square(x.astype(np.float64))))
    if mean_sq == 0.0:
        return -np.inf
    return float(20.0 * np.log10(np.sqrt(mean_sq)))


def _measure_input_bpm(input_path: str | Path) -> float | None:
    """Tempo of the source via librosa (same measurement as the analyzer).

    Mirrors ``analysis/analyzer.py`` (``librosa.beat.beat_track`` on the
    mono load, with the scalar/array tolerance of librosa 1.x) so the
    dimension stage and the full-mix analysis agree on the tempo
    definition. Returns ``None`` when the file is missing/undecodable or
    the beat tracker reports no tempo (≤ 0) — the dimension stage then
    degrades to the neutral ``no_tempo`` report, never a crash (Alex
    guard: dimension only applies with a valid tempo). Lazy librosa
    import, same policy as the analyzer.
    """
    try:
        import librosa

        y, sr = librosa.load(str(input_path), sr=None, mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        tempo_flat = np.asarray(tempo).reshape(-1)
        tempo_val = float(tempo_flat[0]) if tempo_flat.size > 0 else 0.0
    except Exception:
        return None
    if not (np.isfinite(tempo_val) and tempo_val > 0.0):
        return None
    return float(tempo_val)


def _measure_input_genre(
    input_path: str | Path,
) -> tuple[str | None, float | None]:
    """Genre of the source audio (label + confidence) via the analyzer.

    The full-mix analysis at the end of ``build_mix`` runs on the
    REFINED mix — too late for the Paso 06 emphasis stage, which must
    know the material's direction BEFORE routing the stems. This hook
    measures the genre of the INPUT with the SAME detector the analyzer
    ships (``analyze_audio``; the ``_detect_genre`` rule set: pop, rock,
    electronic, hip_hop, reggaeton, jazz, classical, acoustic, metal,
    other — confidence 0.30–0.85). Returns ``(None, None)`` when the
    file is missing/undecodable — the emphasis stage then degrades to
    the NEUTRAL fallback, never a crash (Alex guard, same policy as
    ``_measure_input_bpm``). Lazy import, same policy as the analyzer.
    """
    try:
        from audiomind.analysis.analyzer import analyze_audio

        result = analyze_audio(str(input_path))
        return result.detected_genre, result.genre_confidence
    except Exception:
        return None, None


def _apply_scaled_bus_compression(
    bus: np.ndarray,
    sr: int,
    bpm: float | None,
    profile: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    """Jerry Finn mix-bus compressor pass with an explicit profile.

    Mirror of ``dynamics.apply_bus_compression`` (same silent/empty
    no-op guard, same ``AdaptiveCompressor`` pass, same report keys)
    that takes the profile as an argument instead of the module constant
    — the Paso 06 emphasis stage moves the GR target INSIDE the 2–3 dB
    recipe band (``scale_bus_profile``) without touching ``dynamics.py``
    (fixed Paso 05 API). Reuses the dynamics helpers verbatim; the extra
    ``bus_gr_target_db`` metadata key is ignored by ``_params_from_profile``
    (reads its known keys only).
    """
    x = np.asarray(bus)
    if x.size == 0 or not np.any(x):
        attack, release = _nominal_times(profile, bpm)
        return bus, {
            "gr_db": 0.0,
            "gr_ok": True,
            "technique": BUS_TECHNIQUE_NOTE,
            "ratio": float(profile.get("ratio", 1.0)),
            "attack_ms": attack,
            "release_ms": release,
        }

    params = _params_from_profile(profile, bpm)
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


def _apply_stem_trims(
    variant_processed: dict[str, np.ndarray],
    variant_bus_audio: list[np.ndarray],
    variant_trims: dict[str, float],
) -> None:
    """Stem balance faders (Mix Stem Balance, T2): every stem scales by
    10**(db/20) at the bus input, AFTER the stem chain — the creative-mode
    "mixer fader board". 0.0 dB trims are SKIPPED, so neutral stays
    bit-exact (spec 08); a trim of a stem absent from ``variant_processed``
    is a no-op. Mutates BOTH the processed dict and the bus audio list in
    sync (same objects) — the caller re-reads ``variant_processed``.
    """
    for stem in STEM_NAMES:
        gain_db = float(variant_trims.get(f"{stem}_db", 0.0))
        if gain_db == 0.0 or stem not in variant_processed:
            continue
        gain = 10.0 ** (gain_db / 20.0)
        variant_processed[stem] = variant_processed[stem] * gain
        variant_bus_audio[STEM_NAMES.index(stem)] = variant_processed[stem]


def _apply_bus_profile(
    bus: np.ndarray,
    sr: int,
    bpm: float | None,
    profile: dict[str, Any],
) -> tuple[np.ndarray, dict[str, Any]]:
    """Jerry Finn mix-bus pass honoring the (possibly scaled) profile.

    Single entry point used by BOTH the principal bus and every
    alternative-version bus so the 2-bus behaves identically everywhere:
    the base constant runs the ORIGINAL Paso 05 path (``apply_bus_compression``,
    byte-identical — the emphasis-neutral fallback) and a scaled profile
    runs the explicit-profile mirror. Principal byte-identity is
    preserved: the base path is unchanged.
    """
    if profile is BUS_COMPRESSOR_PROFILE:
        return apply_bus_compression(bus, sr, bpm)
    return _apply_scaled_bus_compression(bus, sr, bpm, profile)


#: Per-stem dimension entry for the no-tempo case (all neutral).
_DIMENSION_NO_TEMPO_ENTRY: dict[str, Any] = {
    "delay": {"subdivision": None, "ms": None},
    "reverb": {"size": None, "mix": None, "pre_delay_ms": None,
               "return_eq": "neutral"},
    "applied": False,
}


def _dimension_stem_entry(
    stem_report: dict[str, Any], profile: dict[str, Any],
) -> dict[str, Any]:
    """Normalize one ``apply_stem_dimension`` report into the
    ``dimension_report["stems"][stem]`` shape (delay/reverb values come
    from the report, the configured mix/subdivision from the profile)."""
    if stem_report.get("reason") == "no_tempo":
        return dict(_DIMENSION_NO_TEMPO_ENTRY)
    reverb_cfg = profile.get("reverb") or {}
    delay_cfg = profile.get("delay") or {}
    return {
        "delay": {
            "subdivision": delay_cfg.get("subdivision"),
            "ms": stem_report.get("delay_ms"),
        },
        "reverb": {
            "size": stem_report.get("reverb_size"),
            "mix": reverb_cfg.get("mix"),
            "pre_delay_ms": stem_report.get("pre_delay_ms"),
            "return_eq": reverb_cfg.get("return_eq", "neutral"),
        },
        "applied": stem_report.get("applied", False),
    }


def _read_stem_channels(stem_path: str | Path) -> tuple[np.ndarray, int]:
    """Read a stem WAV into channels-first float audio.

    ``sf.SoundFile.read(always_2d=True)`` returns ``(samples, channels)``;
    transpose to the ``(channels, samples)`` layout expected by
    ``measure_lufs`` and ``write_output`` (pitfall 1).
    """
    with sf.SoundFile(str(stem_path), "r") as f:
        sr = int(f.samplerate)
        frames = f.read(dtype="float32", always_2d=True)
    return frames.T, sr


def _common_sr(stem_srs: list[int]) -> int:
    """Pick the bus sample rate: most common stem rate, ties → highest.

    Demucs writes 44.1 kHz stems; when a stem diverges the whole bus is
    resampled to the common rate so every stem lands on one grid
    (pitfall 2).
    """
    if not stem_srs:
        return settings.sample_rate
    counts = Counter(stem_srs)
    return max(counts, key=lambda sr: (counts[sr], sr))


def _process_stem(
    name: str,
    audio: np.ndarray,
    target_sr: int,
    bpm: float | None,
    bands: list[dict[str, Any]],
    comp_profile: dict[str, Any] | None,
    dim_profile: dict[str, Any] | None,
) -> tuple[
    np.ndarray,
    list[dict[str, Any]] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    """One stem through the chain pan → EQ → compressor → dimension/sends.

    Shared by the PRINCIPAL routing and every CREATIVE variant (Paso 08):
    the same per-stem recipe run on already-panned audio — EQ bands first
    (bit-exact bypass for empty/zero lists), then the compressor recipe
    (neutral when ``None``), then the tempo dimension send (neutral when
    ``None``). Purely deterministic: identical inputs → identical output
    arrays, which is what the byte-identity contracts (versions, creative
    ``creativity=0``) rely on. The caller owns the per-stem report
    attribution (the principal also records which profiles were used).

    Returns:
        ``(shaped, eq_bands, comp_report, dim_report)`` — ``eq_bands`` is
        the applied band list (``None`` when no EQ ran), ``comp_report`` /
        ``dim_report`` the stage reports (``None`` when the stage was
        skipped for the stem).
    """
    shaped = audio
    eq_bands: list[dict[str, Any]] | None = None
    if bands:
        # All-zero gains bypass bit-exactly inside apply_stem_eq.
        shaped = apply_stem_eq(shaped, target_sr, bands)
        eq_bands = bands
    comp_report: dict[str, Any] | None = None
    if comp_profile is not None:
        shaped, comp_report = apply_stem_compression(
            shaped, target_sr, comp_profile, bpm
        )
    dim_report: dict[str, Any] | None = None
    if dim_profile is not None:
        shaped, dim_report = apply_stem_dimension(
            shaped, target_sr, bpm, dim_profile
        )
    return shaped, eq_bands, comp_report, dim_report


def _compute_mix_metadata(
    final_bus: np.ndarray,
    sr: int,
    analysis: dict,
    dimension_report: dict | None,
    emphasis_report: dict | None,
    stereo_width_param: float,
    stereo_imaging_enabled: bool,
    limiter_ceiling_db: float,
) -> MixMetadata:
    """Compute MixMetadata from the final mix bus and processing reports."""
    # 1. Side energy ratio (bus final)
    mid, side = mid_side_encode(final_bus)
    side_rms = float(np.sqrt(np.mean(side**2)))
    mid_rms = float(np.sqrt(np.mean(mid**2)))
    side_energy_ratio = side_rms / (mid_rms + 1e-10)

    # 2. Applied spatial width (heurística combinada)
    width = 1.0
    if dimension_report and dimension_report.get("status") == "active":
        # Promedio de reverb mix en stems vocales/other
        stems_reverb = dimension_report.get("stems", {})
        reverb_mixes = [
            s.get("reverb", {}).get("mix", 0) for s in stems_reverb.values()
            if s.get("reverb", {}).get("mix", 0) > 0
        ]
        avg_reverb_mix = np.mean(reverb_mixes) if reverb_mixes else 0.0
        width += 0.2 * avg_reverb_mix  # reverb en Side expande ancho percibido

    if emphasis_report and emphasis_report.get("status") == "active":
        dim_scaling = emphasis_report.get("scaling", {}).get("dimension", {})
        avg_dim_send = np.mean(list(dim_scaling.values())) if dim_scaling else 0.0
        width += 0.15 * avg_dim_send  # emphasis escala sends de dimensión

    if stereo_width_param != 1.0:
        width += abs(stereo_width_param - 1.0) * 0.5  # legacy width broadband

    if stereo_imaging_enabled:
        width += 0.2  # Sprint 9 añade ancho per-band

    applied_spatial_width = float(np.clip(width, 1.0, 2.5))

    # 3. Stem LUFS
    stem_lufs = {
        stem: float(analysis[stem]["integrated_lufs"])
        for stem in STEM_NAMES if stem in analysis
    }

    # 4. Transient headroom (True Peak - ceiling)
    from scipy.signal import find_peaks
    peak = float(np.max(np.abs(final_bus)))
    true_peak_db = 20.0 * float(np.log10(peak + 1e-10))
    transient_headroom_db = limiter_ceiling_db - true_peak_db

    return MixMetadata(
        applied_spatial_width=applied_spatial_width,
        side_energy_ratio=side_energy_ratio,
        stem_lufs=stem_lufs,
        transient_headroom_db=transient_headroom_db,
        mix_status="completed",
    )


def build_mix(
    session_id: str,
    input_path: str | Path,
    profiles: dict[str, list[dict[str, Any]]] | None = None,
    pan_profiles: dict[str, dict[str, Any]] | None = None,
    dimension_profiles: dict[str, dict[str, Any]] | None = None,
    compressor_profiles: dict[str, dict[str, Any]] | None = None,
    emphasis_profiles: dict[str, dict[str, Any]] | None = None,
    genre: str | None = None,
    genre_confidence: float | None = None,
    with_versions: bool = True,
    creative_seed: int | None = None,
    creativity: float = 0.0,
    creative_variants: int = 0,
    creative_manual: bool = False,
    auto_balance: bool = False,
    stem_trims: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Run the per-stem routing pipeline for a session.

    Args:
        session_id: Session UUID — owns the stems dir and the output file.
        input_path: Source audio to separate.
        profiles: Per-stem EQ band lists applied AFTER the pan, before
            the dimension/bus sum (Paso 02: magic frequencies, Owsinski
            pág. 32). ``None`` ⇒ ``MAGIC_PROFILES`` (default); pass
            ``{}`` or all-zero-gain bands to keep the Paso 01 NEUTRAL
            routing (bit-exact bypass per stem).
        pan_profiles: Per-stem role profiles for the positional validation
            (Paso 03: ``panorama.PAN_ROLE_PROFILES``). ``None`` ⇒ role pan
            ENABLED by default (Paso 03 behaviour). Pass ``{}`` to disable
            pan entirely — routing identical to Paso 02 (no pan applied,
            no ``pan_report`` key). A custom dict maps stem names to
            ``{"role": "center"|"wide", "target_max_abs_balance_db",
            "max_correction_db"}``.
        dimension_profiles: Per-stem tempo-dimension profiles (Paso 04:
            ``dimension.DIMENSION_PROFILES`` — tempo delay + reverb with
            pre-delay and return EQ). ``None`` ⇒ dimension ENABLED by
            default (Paso 04 behaviour); the BPM is measured ONCE from
            ``input_path`` via librosa (same measurement as the analyzer)
            and applied after the EQ, before the pad/sum. Pass ``{}`` to
            disable dimension — routing identical to Paso 03 (no
            ``dimension_report`` key). A custom dict maps stem names to
            ``{"reverb": {...}, "delay": {...}}``; unmapped stems pass
            through untouched and do not appear in the report. Without a
            valid tempo the stage degrades to the neutral ``no_tempo``
            report, never a crash (Alex guard).
        compressor_profiles: Per-stem compressor recipes (Paso 05:
            ``dynamics.STEM_COMPRESSOR_PROFILES`` — book recipes per
            role, drums by spectral segment, breathing at tempo). ``None``
            ⇒ compressors ENABLED by default (Paso 05 behaviour): the
            BPM measured once from ``input_path`` (same measurement as
            the dimension stage) feeds the beat-locked release, each stem
            is compressed AFTER the EQ and BEFORE the dimension/sends
            (final chain: pan → EQ → compressor → dimension/sends →
            bus), and the stereo bus compresses AFTER the stem sum with
            the Jerry Finn technique (``dynamics.apply_bus_compression``,
            2–3 dB total, ``gr_ok`` ≤ 3.1 dB). Pass ``{}`` to disable the
            compressors entirely — routing identical to Paso 04 (no
            ``compressor_report`` key). A custom dict maps stem names to
            recipe dicts; unmapped stems pass through untouched and do
            not appear in the report (panorama convention), while the bus
            stage stays active whenever the compressors are enabled.
        emphasis_profiles: Per-genre emphasis weights (Paso 06:
            ``emphasis.GENRE_EMPHASIS_PROFILES`` — the "Interest" balance
            of the book, Ch8 pág. 58–60: every analyzer genre maps to a
            vocal-forward/groove-forward pair, "Dance/Rap → énfasis en
            groove (kick/bajo); Country/Pop → énfasis en vocal"). ``None``
            ⇒ emphasis ENABLED by default (Paso 06 behaviour): the genre
            scales the per-stem dimension sends (reverb mix/size, delay
            mix — INSIDE the engine's standard ranges) and the bus GR
            target (inside the 2–3 dB recipe band). Pass ``{}`` to
            disable emphasis — routing identical to Paso 05 (no
            ``emphasis_report`` key). A custom dict maps genre labels to
            ``{"vocal_forward": float, "groove_forward": float}`` pairs
            in [0, 1] summing to 1.0.
        genre: Explicit genre label — overrides the source measurement.
            ``None`` ⇒ measured from ``input_path`` with the analyzer's
            own detector (``analyze_audio``, lazy import) when emphasis
            is enabled; a missing/undecodable input degrades to the
            NEUTRAL fallback, never a crash (Alex guard).
        genre_confidence: Confidence of the ``genre`` label (the
            analyzer's 0.30–0.85 scale). Below ``CONFIDENCE_THRESHOLD``
            (0.5, documented in ``emphasis.py``) the label is reported
            but NOT followed — neutral fallback. ``None`` means no
            confidence information: the label is trusted (the caller
            asserts it).
        with_versions: Render the five alternative WAVs (Paso 07:
            principal + vocal ±0.75 dB + instrumental + tv_mix) from the
            same processed stems. Default ``True`` — the plan's
            deliverable; the alternative files never perturb the
            principal render (byte-identical with or without).
        creative_seed: Base seed of the CREATIVE MODE (Paso 08,
            ``creative.py`` — "exploración creativa acotada"). With
            ``creative_variants > 0`` each variant draws from its own
            seed stream (``seed + index*1000 + attempt``); ``None``
            (default) together with variants disables the mode. A seed is
            REQUIRED for creative mode — it is what makes the A/B
            reproducible ("Semilla por variante", §4.2).
        creativity: Deviation slider in [0, 1]: 0 = strict standard (every
            variant reproduces the base routing, bit-identical principal),
            1 = wide exploration inside the standard envelope. Must be in
            [0, 1] (``ValueError`` otherwise).
        creative_variants: Number of N variants to render (default 0 =
            creative mode disabled — no ``creative_report`` key, exact
            previous routing). Must be ≥ 0.
        creative_manual: Producer's deliberate out-of-envelope choice
            (Paso 08): the variants render even when they violate a
            positional/QC check and are MARKED ``non_standard`` in the
            report — never blocked ("salida no-estándar se marca, no se
            bloquea").
        auto_balance: Opt-in stem auto-balance (T3, ``stem_balance`` —
            feature ``odd/tasks/mix-stem-balance.md``). Default ``False``:
            the exact previous routing (bit-identical neutral, no
            measurement, no mutation). When ``True`` the engine measures
            integrated LUFS on the PROCESSED stems, resolves the genre
            target from the SAME emphasis weights (explicit ``genre`` or
            measured from the input) and corrects ONLY the voice toward
            that target — bounded by the ±6 dB fader band of T1; a
            no-op/neutral outcome leaves the audio untouched. When on, the
            payload carries ``balance_report`` (T4): resolved genre +
            status, measured stem LUFS, groove/target levels, the computed
            ``d``, the final gains and the ``applied`` flag (honest about
            a neutral no-op); when off, the key is ABSENT (exact previous
            payload shape).
        stem_trims: MANUAL stem faders (T5, ``odd/tasks/mix-stem-balance.md``
            — the human decides): an optional dict of ``{stem}_db`` gains
            in the ±6 dB band (T1) applied to the bus input AFTER the whole
            chain (T2) and AFTER any auto-balance — the manual fader stays
            visible/relative to the engine's result (the auto-balance
            measured the stems WITHOUT the manual fader). ``None``
            (default) or all-zero dicts keep the exact previous routing
            (bit-identical neutral, spec 08) with no ``trim_report`` key;
            with at least one non-zero gain the payload carries
            ``trim_report`` = ``{"gains": {non-zero ``{stem}_db`` keys},
            "applied": true}``.

    Returns:
        ``{
            "mix_path": "<outputs/{session_id}_mix.wav>",
            "sample_rate": int,
            "duration_seconds": float,
            "analysis": {"drums": {...}, "bass": {...},
                         "other": {...}, "vocals": {...}},
            "stem_presence": {"drums": bool, "bass": bool,
                              "other": bool, "vocals": bool},
            "tempo_bpm": float,
            "genre": str,
            "genre_confidence": float,
            "eq_profiles_applied": {"drums": [...], "bass": [...],
                                    "other": [...], "vocals": [...]},
            "pan_report": {...},       # Paso 03, absent when pan_profiles={}
            "dimension_report": {...}  # Paso 04, absent when dimension disabled
            "compressor_report": {...} # Paso 05, absent when compressors disabled
            "emphasis_report": {...}   # Paso 06, absent when emphasis disabled
            "qc_report": {...},        # Paso 07, always present (informational)
            "versions": {...},         # Paso 07, absent when with_versions=False
            "balance_report": {...}    # T4, absent unless auto_balance=True
            "trim_report": {...}       # T5, absent unless a manual trim ≠ 0 is set
        }``
        where each per-stem analysis dict carries ``integrated_lufs``,
        ``dynamic_range_db``, ``spectral_centroid`` and ``sample_rate``,
        ``stem_presence`` reports the audible presence of each of the 4
        real ``STEM_NAMES`` stems — its RMS ≥
        ``STEM_PRESENCE_RMS_DBFS_THRESHOLD`` (−50 dBFS) measured on the
        resampled source stems (a missing instrument leaves a silent or
        residue-only stem → ``False``),
        ``eq_profiles_applied`` records the bands requested per stem
        (a stem with no profile / zero gains still appears only if a
        profile was passed for it; ``profiles={}`` ⇒ ``{}``),
        ``pan_report`` is the positional validation of
        ``panorama.validate_positions`` (roles / stems / mono_check /
        human_decision), ``dimension_report`` is
        ``{"bpm_used": float|None, "stems": {stem: {"delay":
        {"subdivision", "ms"}, "reverb": {"size", "mix", "pre_delay_ms",
        "return_eq"}, "applied"}}, "layering": {"note":
        "longest reverb brightest, shortest darkest"}, "status":
        "active"|"no_tempo"}`` and ``compressor_report`` is
        ``{"stems": {stem: {"gr_db": float, "ratio": float, "status":
        "applied"|"neutral"}}, "bus": {"gr_db": float, "gr_ok": bool,
        "technique": "jerry_finn_slow_attack_fast_release"}, "status":
        "active"}`` — a missing lambda-key ``compressor_profiles={}``
        keeps the exact Paso 04 result dict, and ``emphasis_report`` is
        ``{"genre": str, "genre_confidence": float|None,
        "vocal_forward": float, "groove_forward": float, "scaling":
        {"dimension": {stem: scaled send values}, "bus_gr_target_db":
        float (present only when the bus compressor is enabled)},
        "status": "active"|"neutral_fallback"}`` — the genre the
        emphasis followed, its confidence, the direction weights and the
        scaled values the stage applied (a ``neutral_fallback`` carries
        the exact Paso 05 base values). ``qc_report`` is
        ``quality_checks.run_qc_checks`` on the FINAL compressed bus:
        one checkpoint per check (mono / phase / sibilance_5k /
        muddy_250 / honky_500 / low_level_listen), each ``{"ok": bool,
        "details": {...}}`` plus an optional ``pan_stage`` context when
        the pan stage ran, a ``summary`` (``all_ok`` / ``flagged``) and
        the informational note — flags never block rendering. And
        ``versions`` is ``{name: {"path", "trim_db", "description"}}``
        for the five alternatives; ``principal`` points at the same
        ``mix_path`` the /mix endpoint serves, the alternative WAVs are
        ``outputs/{session_id}_mix_{name}.wav``. The creative report
        (Paso 08, present only with ``creative_variants > 0`` and a
        seed) is ``{"seed": int, "creativity": float, "manual": bool,
        "status": "active", "variants": [{"index", "seed", "status":
        "ok"|"rejected", "params", "qc_ok", "positional_ok",
        "non_standard", "path"}], "rejected_count": int, "note": str}``
        — accepted variant WAVs live at
        ``outputs/{session_id}_mix_creative_{i}.wav``; rejected entries
        carry no path and the batch never blocks.

    Raises:
        ValueError: When ``split_audio`` does not produce all 4 stems,
            ``creativity`` is outside [0, 1], ``creative_variants`` is
            negative, or variants are requested without a
            ``creative_seed``.
    """
    # Paso 08 contract validation — cheap, before any heavy work. The
    # slider lives in [0, 1] and creative mode REQUIRES a seed (the
    # per-variant streams are what make the A/B reproducible).
    if not (0.0 <= float(creativity) <= 1.0):
        raise ValueError(
            f"creativity must be in [0, 1] (slider), got {creativity!r}"
        )
    if creative_variants < 0:
        raise ValueError(
            f"creative_variants must be >= 0, got {creative_variants!r}"
        )
    if creative_variants > 0 and creative_seed is None:
        raise ValueError(
            "creative mode requires a seed (creative_seed) so every "
            "variant draws a reproducible stream"
        )

    stems_dir = settings.output_dir / session_id / "stems"
    split_result = split_audio(input_path, output_dir=stems_dir)
    stems = split_result["stems"]

    missing = [name for name in STEM_NAMES if name not in stems]
    if missing:
        raise ValueError(f"split_audio missing stems: {', '.join(missing)}")

    # Read + resample every stem to the common bus rate. Paso 03 measures
    # the M/S position on the RESAMPLED stem (before any correction) and
    # applies the role PAN (vocals/bass/drums → center, other → inside the
    # extremes) BEFORE the EQ — the DAW chain: fader → pan → EQ → compresor
    # → sends (VIABILIDAD línea 214).
    reads = [_read_stem_channels(stems[name]) for name in STEM_NAMES]
    target_sr = _common_sr([sr for _, sr in reads])
    profiles = MAGIC_PROFILES if profiles is None else profiles
    pan_profiles = PAN_ROLE_PROFILES if pan_profiles is None else pan_profiles
    dimension_profiles = (
        DIMENSION_PROFILES if dimension_profiles is None else dimension_profiles
    )
    compressor_profiles = (
        STEM_COMPRESSOR_PROFILES if compressor_profiles is None else compressor_profiles
    )
    emphasis_profiles = (
        GENRE_EMPHASIS_PROFILES if emphasis_profiles is None else emphasis_profiles
    )
    dimension_enabled = bool(dimension_profiles)
    compressor_enabled = bool(compressor_profiles)
    emphasis_enabled = bool(emphasis_profiles)

    # Paso 04 + Paso 05: measure the tempo ONCE from the INPUT (same
    # librosa measurement as the analyzer) — the dimension stage and the
    # compressor "breathing" (beat-locked release, book pág. 55) share the
    # same BPM. No valid tempo → neutral "no_tempo" dimension and static
    # compressor releases, never a crash (Alex guard).
    bpm_used: float | None = None
    if dimension_enabled or compressor_enabled:
        bpm_used = _measure_input_bpm(input_path)
        if bpm_used is not None:
            bpm_used = round(bpm_used, 1)

    # Paso 06: the genre the emphasis follows. An explicit ``genre``
    # parameter overrides the measurement; otherwise the genre is measured
    # from the INPUT with the analyzer's own detector (the final full-mix
    # analysis runs on the refined mix — too late for the routing). A
    # missing/undecodable input degrades to the NEUTRAL fallback, never a
    # crash (Alex guard, same policy as the BPM); unknown genre or
    # confidence below CONFIDENCE_THRESHOLD → the label is reported but
    # NOT followed (same neutral fallback).
    emphasis_resolved: dict[str, Any] | None = None
    emphasis_dim_scaling: dict[str, float] = {}
    scaled_bus_target: float | None = None
    # T3 — the auto-balance reuses the SAME measured/explicit genre as the
    # emphasis stage: one detection serves both when both are enabled.
    detected_genre = genre
    detected_confidence = genre_confidence
    if (emphasis_enabled or auto_balance) and detected_genre is None:
        detected_genre, detected_confidence = _measure_input_genre(input_path)
    if emphasis_enabled:
        emphasis_resolved = resolve_emphasis(
            detected_genre, detected_confidence, emphasis_profiles
        )

    resampled_stems: dict[str, np.ndarray] = {}
    for name, (audio, stem_sr) in zip(STEM_NAMES, reads, strict=True):
        resampled_stems[name] = resample_audio(audio, stem_sr, target_sr)

    # Paso 08: keep the RAW resampled stems for the creative variants —
    # every variant re-runs its OWN positional validation from the same
    # pre-pan material (no re-split): the alias survives because
    # validate_positions returns a NEW dict.
    raw_stems_for_creative = resampled_stems

    # v5 — instrumentos REALES: Demucs always emits the 4 stems, but what
    # is audible is the material's decision. Per-stem RMS (measured on the
    # resampled stems, BEFORE the pan — presence is a property of the
    # source, not of the routing) decides which stems the UI may truthfully
    # claim were in the mix. Additive key: existing payloads keep working.
    stem_presence: dict[str, bool] = {
        name: bool(
            _stem_rms_db(resampled_stems[name])
            >= STEM_PRESENCE_RMS_DBFS_THRESHOLD
        )
        for name in STEM_NAMES
    }

    pan_report: dict[str, Any] | None = None
    if pan_profiles:
        resampled_stems, pan_report = validate_positions(
            resampled_stems, pan_profiles
        )

    # Paso 06: the genre-scaled dimension profiles are computed ONCE per
    # stem (they are pure functions of the base profile + the weights)
    # and feed the PRINCIPAL routing below. Paso 08 creative variants
    # draw their own sends from the creative space (``creative.py``),
    # whose standards are the BASE profiles — under neutral emphasis
    # weights (0.5/0.5) the scaled values equal those base values.
    emphasis_weights: dict[str, float] | None = None
    effective_dimension_profiles: dict[str, dict[str, Any]] = {}
    if dimension_enabled:
        for name in STEM_NAMES:
            dim_profile = dimension_profiles.get(name)
            if dim_profile is None:
                continue
            if emphasis_resolved is not None:
                if emphasis_weights is None:
                    emphasis_weights = {
                        "vocal_forward": emphasis_resolved["vocal_forward"],
                        "groove_forward": emphasis_resolved["groove_forward"],
                    }
                # Paso 06: scale the dimension sends along the genre
                # direction (vocal_lead for the vocals role; the bed
                # mirrors it). Neutral weights → exact base values.
                dim_profile = scale_dimension_profile(
                    dim_profile, emphasis_weights, vocal_lead=(name == "vocals")
                )
                reverb_cfg = dim_profile.get("reverb") or {}
                delay_cfg = dim_profile.get("delay") or {}
                emphasis_dim_scaling[f"{name}_reverb_mix"] = round(
                    float(reverb_cfg.get("mix", 0.0)), 2
                )
                emphasis_dim_scaling[f"{name}_delay_mix"] = round(
                    float(delay_cfg.get("mix", 0.0)), 2
                )
                if name == "vocals":
                    emphasis_dim_scaling["vocals_reverb_size"] = round(
                        float(reverb_cfg.get("size", 0.5)), 2
                    )
            effective_dimension_profiles[name] = dim_profile

    # Apply the stem EQ profile AFTER the pan, then the COMPRESSOR (Paso
    # 05, BETWEEN the EQ and the sends: book recipes per stem, drums by
    # spectral segment), then the tempo dimension (Paso 04) — the DAW
    # chain: pan → EQ → compresor → sends. Every instrument lands on the
    # bus already shaped and controlled. The chain itself lives in
    # ``_process_stem`` so the principal path and the creative variants
    # (Paso 08) run the exact same recipe.
    bus_audio: list[np.ndarray] = []
    processed_stems: dict[str, np.ndarray] = {}
    eq_profiles_applied: dict[str, list[dict[str, Any]]] = {}
    dimension_stems_report: dict[str, Any] = {}
    compressor_stems_report: dict[str, Any] = {}
    for name in STEM_NAMES:
        comp_profile = (
            compressor_profiles.get(name) if compressor_enabled else None
        )
        dim_profile = (
            effective_dimension_profiles.get(name) if dimension_enabled else None
        )
        shaped, eq_bands, comp_report, stem_report = _process_stem(
            name,
            resampled_stems[name],
            target_sr,
            bpm_used,
            profiles.get(name, []),
            comp_profile,
            dim_profile,
        )
        if eq_bands is not None:
            eq_profiles_applied[name] = eq_bands
        if comp_report is not None:
            compressor_stems_report[name] = {
                "gr_db": comp_report["gr_db"],
                "ratio": comp_report["ratio"],
                "status": comp_report["status"],
            }
        # ``_process_stem`` returns a dimension report exactly when a
        # profile was passed — the joint guard narrows ``dim_profile``
        # for mypy (both are None-or-not together).
        if stem_report is not None and dim_profile is not None:
            dimension_stems_report[name] = _dimension_stem_entry(
                stem_report, dim_profile
            )
        bus_audio.append(shaped)
        processed_stems[name] = shaped

    # T3/T4 — auto-balance: measure the processed stems and correct ONLY the
    # voice toward the genre target (emphasis weights), bounded by the
    # ±6 dB fader band. OFF (default) = no measurement, no mutation: the
    # routing stays bit-identical to the manual-fader-only path. The gains
    # reuse the EXACT T2 application point (``_apply_stem_trims`` after
    # the chain, before the pad/sum) so neutral and manual behavior are
    # unchanged. A neutral/no-op outcome (``applied=False``) also leaves
    # the audio untouched. When ON, the measured ``compute_stem_balance``
    # envelope (stem LUFS, gains, target) plus the resolved genre is
    # exposed as ``balance_report`` in the payload (T4); when OFF the key
    # is absent (master-safe neutral payload shape).
    balance_report: dict[str, Any] | None = None
    if auto_balance:
        auto_balance_weights: dict[str, Any] = resolve_emphasis(
            detected_genre, detected_confidence
        )
        stem_balance_result = compute_stem_balance(
            processed_stems, target_sr, auto_balance_weights
        )
        if stem_balance_result["applied"]:
            _apply_stem_trims(
                processed_stems, bus_audio, stem_balance_result["gains"]
            )
        balance_report = {
            "genre": auto_balance_weights["genre"],
            "genre_confidence": auto_balance_weights["genre_confidence"],
            "status": auto_balance_weights["status"],
            "stem_lufs": stem_balance_result["stem_lufs"],
            "groove_level_lufs": stem_balance_result["groove_level_lufs"],
            "vocal_target_lufs": stem_balance_result["vocal_target_lufs"],
            "d": stem_balance_result["d"],
            "gains": stem_balance_result["gains"],
            "applied": stem_balance_result["applied"],
        }

    # T5 — MANUAL stem faders (the human decides): the user's trims land ON
    # TOP of the auto-balance result, AFTER it (the auto-balance measured
    # the stems WITHOUT any manual fader, so the manual trim is a relative
    # — always visible — adjustment). None or all-zero trims keep the exact
    # previous routing (bit-identical, spec 08) and ``trim_report`` stays
    # ABSENT (same payload shape); with at least one non-zero gain the
    # report carries ONLY the applied keys (``gains``) + ``applied``.
    trim_report: dict[str, Any] | None = None
    if stem_trims:
        manual_trims = {
            key: value for key, value in stem_trims.items() if value != 0.0
        }
        if manual_trims:
            _apply_stem_trims(processed_stems, bus_audio, manual_trims)
            trim_report = {"gains": manual_trims, "applied": True}

    dimension_report: dict[str, Any] | None = None
    if dimension_enabled:
        dimension_report = {
            "bpm_used": bpm_used,
            "stems": dimension_stems_report,
            "layering": {"note": _DIMENSION_LAYERING_NOTE},
            "status": "active" if bpm_used is not None else "no_tempo",
        }

    # Pad to the longest stem and sum onto the stereo mono-compatible bus.
    # Neutral 0 dB = 1:1 summing (no normalization); a hot sum just clips
    # at write time — accepted for the skeleton (no DSP yet).
    max_len = max(audio.shape[1] for audio in bus_audio)
    bus = np.zeros((2, max_len), dtype=np.float32)
    for audio in bus_audio:
        bus[:, : audio.shape[1]] += audio

    # Paso 05 + Paso 06: the mix bus compresses AFTER the stem sum (Jerry
    # Finn technique: 2–3 dB total, slow attack / fast release, breathing
    # at tempo — ``dynamics.apply_bus_compression``). Under emphasis, the
    # GR target moves INSIDE the recipe band (``scale_bus_profile``:
    # groove → a bit more glue, vocal → let the voice breathe); when the
    # scaled target equals the base one (neutral weights) the ORIGINAL
    # Paso 05 path runs, bit-identical.
    bus_stage: dict[str, Any] | None = None
    bus_profile: dict[str, Any] | None = None
    if compressor_enabled:
        bus_profile = BUS_COMPRESSOR_PROFILE
        if emphasis_resolved is not None:
            scaled_bus = scale_bus_profile(
                BUS_COMPRESSOR_PROFILE,
                {
                    "vocal_forward": emphasis_resolved["vocal_forward"],
                    "groove_forward": emphasis_resolved["groove_forward"],
                },
            )
            scaled_bus_target = float(scaled_bus["bus_gr_target_db"])
            if float(scaled_bus["threshold_offset_db"]) != float(
                BUS_COMPRESSOR_PROFILE["threshold_offset_db"]
            ):
                bus_profile = scaled_bus
        bus, bus_stage_report = _apply_bus_profile(
            bus, target_sr, bpm_used, bus_profile
        )
        bus_stage = {
            "gr_db": bus_stage_report["gr_db"],
            "gr_ok": bus_stage_report["gr_ok"],
            "technique": bus_stage_report["technique"],
        }

    # Paso 07: QC report on the FINAL compressed bus — informational
    # flags that never block the render (human decision per the plan).
    qc_report = run_qc_checks(bus, target_sr, pan_info=pan_report)

    mix_path = (settings.output_dir / f"{session_id}_mix.wav").resolve()
    write_output(bus, mix_path, target_sr, bit_depth=24)

    # Paso 07: alternative versions from the SAME processed stems (only
    # the vocals trim differs — ``render_versions``). The principal is
    # the file already written; the alternatives re-sum the stems and
    # run the SAME mix-bus compressor (the 2-bus reacts to the fader
    # move, DAW-real). Separate files — the principal render is
    # byte-identical with or without versions.
    version_outputs: dict[str, Any] | None = None
    if with_versions:
        version_buses = render_version_buses(processed_stems)
        version_outputs = {}
        for version_name, version_bus in version_buses.items():
            if version_name == "principal":
                version_outputs[version_name] = {
                    "path": str(mix_path),
                    "trim_db": 0.0,
                    "description": VERSION_DESCRIPTIONS["principal"],
                }
                continue
            if compressor_enabled and bus_profile is not None:
                version_bus, _ = _apply_bus_profile(
                    version_bus, target_sr, bpm_used, bus_profile
                )
            version_path = (
                settings.output_dir / f"{session_id}_mix_{version_name}.wav"
            ).resolve()
            write_output(version_bus, version_path, target_sr, bit_depth=24)
            version_outputs[version_name] = {
                "path": str(version_path),
                "trim_db": VERSION_TRIMS_DB[version_name],
                "description": VERSION_DESCRIPTIONS[version_name],
            }

    # Paso 08: CREATIVE MODE — "exploración creativa acotada"
    # (``creative.py``). Variants reroute the SAME raw resampled stems (no
    # re-split, no re-analysis): an RNG walk inside the standard envelope
    # (``creativity`` 0..1), each variant re-validates ITS OWN positional
    # gate from its pre-pan material and the Paso 07 QC gate from its own
    # bus, and the batch NEVER blocks the deliverable — a failing variant
    # is retried (``MAX_CREATIVE_ATTEMPTS``) and the last draw is reported
    # as ``status: "rejected"`` (no file) unless ``creative_manual`` marks
    # it ``non_standard``. Accepted files:
    # ``outputs/{session_id}_mix_creative_{i}.wav``. The PRINCIPAL path
    # above ran untouched: creative mode is a separate, later pass on the
    # raw stems — byte-identity preserved.
    creative_report: dict[str, Any] | None = None
    if creative_variants > 0 and creative_seed is not None:

        def _render_creative_variant(
            attempt_seed: int, variant: dict[str, float],
        ) -> dict[str, Any]:
            """Route one variant from the raw stems to a validated bus.

            Mirrors the principal chain (pan → EQ → compresor → sends →
            sum → 2-bus) with the variant's SIX routing roots; the stem
            trims land at the bus input (faders AFTER the stem chain,
            versions-style). Variant roots are deep copies of the shared
            constants — the principal constants are never touched.
            """
            (
                variant_eq_profiles,
                variant_pan_profiles,
                variant_dim_profiles,
                variant_comp_profiles,
                variant_bus_profile,
                variant_trims,
            ) = apply_variant_to_profiles(variant)

            variant_stems: dict[str, np.ndarray] = dict(raw_stems_for_creative)
            variant_pan_report: dict[str, Any] | None = None
            if variant_pan_profiles:
                variant_stems, variant_pan_report = validate_positions(
                    variant_stems, variant_pan_profiles
                )

            variant_bus_audio: list[np.ndarray] = []
            variant_processed: dict[str, np.ndarray] = {}
            for name in STEM_NAMES:
                comp_profile = (
                    variant_comp_profiles.get(name)
                    if compressor_enabled
                    else None
                )
                dim_profile = (
                    variant_dim_profiles.get(name)
                    if dimension_enabled
                    else None
                )
                shaped, _, _, _ = _process_stem(
                    name,
                    variant_stems[name],
                    target_sr,
                    bpm_used,
                    variant_eq_profiles.get(name, []),
                    comp_profile,
                    dim_profile,
                )
                variant_processed[name] = shaped
                variant_bus_audio.append(shaped)

            # Creative faders: the stem trims applied at the bus input,
            # AFTER the chain — same semantic as render_versions, but for
            # every stem (drums/bass/other/vocals, Mix Stem Balance T2).
            _apply_stem_trims(variant_processed, variant_bus_audio, variant_trims)

            max_len = max(audio.shape[1] for audio in variant_bus_audio)
            variant_bus = np.zeros((2, max_len), dtype=np.float32)
            for audio in variant_bus_audio:
                variant_bus[:, : audio.shape[1]] += audio

            if compressor_enabled:
                variant_bus, _ = _apply_bus_profile(
                    variant_bus, target_sr, bpm_used, variant_bus_profile
                )

            variant_qc = run_qc_checks(
                variant_bus, target_sr, pan_info=variant_pan_report
            )
            return {
                "validation": variant_pan_report or {},
                "qc": variant_qc,
                "bus": variant_bus,
            }

        def _save_creative_variant(
            index: int, attempt_seed: int, bus: np.ndarray,
        ) -> str:
            path = (
                settings.output_dir / f"{session_id}_mix_creative_{index}.wav"
            ).resolve()
            write_output(bus, path, target_sr, bit_depth=24)
            return str(path)

        creative_report = run_creative_mode(
            seed=creative_seed,
            creativity=creativity,
            variants_count=creative_variants,
            render=_render_creative_variant,
            save=_save_creative_variant,
            manual=creative_manual,
        )

    # Analysis is heavy (librosa) — lazy import, same policy as mastering.
    from audiomind.analysis.analyzer import analyze_audio

    analysis: dict[str, dict[str, Any]] = {}
    for name in STEM_NAMES:
        result = analyze_audio(stems[name])
        analysis[name] = {
            field: getattr(result, field) for field in _STEM_ANALYSIS_FIELDS
        }

    mix_result = analyze_audio(mix_path)
    build_result: dict[str, Any] = {
        "mix_path": str(mix_path),
        "sample_rate": target_sr,
        "duration_seconds": round(mix_result.duration_seconds, 2),
        "analysis": analysis,
        "stem_presence": stem_presence,
        "tempo_bpm": mix_result.tempo_bpm,
        "genre": mix_result.detected_genre,
        "genre_confidence": mix_result.genre_confidence,
        "eq_profiles_applied": eq_profiles_applied,
        "qc_report": qc_report,
    }
    if version_outputs is not None:
        build_result["versions"] = version_outputs
    if pan_report is not None:
        build_result["pan_report"] = pan_report
    if dimension_report is not None:
        build_result["dimension_report"] = dimension_report
    if compressor_enabled:
        build_result["compressor_report"] = {
            "stems": compressor_stems_report,
            "bus": bus_stage,
            "status": "active",
        }
    if emphasis_resolved is not None:
        scaling: dict[str, Any] = {}
        if dimension_enabled:
            scaling["dimension"] = emphasis_dim_scaling
        if compressor_enabled and scaled_bus_target is not None:
            scaling["bus_gr_target_db"] = scaled_bus_target
        build_result["emphasis_report"] = {
            "genre": emphasis_resolved["genre"],
            "genre_confidence": emphasis_resolved["genre_confidence"],
            "vocal_forward": emphasis_resolved["vocal_forward"],
            "groove_forward": emphasis_resolved["groove_forward"],
            "scaling": scaling,
            "status": emphasis_resolved["status"],
        }
    if creative_report is not None:
        build_result["creative_report"] = creative_report
    if balance_report is not None:
        build_result["balance_report"] = balance_report
    if trim_report is not None:
        build_result["trim_report"] = trim_report

    # Mix → Master handshake metadata (computed after all reports are built)
    build_result["mix_metadata"] = _compute_mix_metadata(
        final_bus=bus,
        sr=target_sr,
        analysis=analysis,
        dimension_report=dimension_report,
        emphasis_report=build_result.get("emphasis_report"),
        stereo_width_param=1.0,
        stereo_imaging_enabled=False,
        limiter_ceiling_db=-1.0,
    ).model_dump()
    
    return build_result
