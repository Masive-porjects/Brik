from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from enum import Enum


class AudioFormat(str, Enum):
    WAV = "wav"
    MP3 = "mp3"


class ProcessingStatus(str, Enum):
    UPLOADED = "uploaded"
    ANALYZING = "analyzing"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"


# Lifecycle of the Mix Engine output of a session (``SessionData.mix_status``).
# The client must be able to tell "never mixed" from "mix running" from
# "mix delivered" from "mix failed" — the gate "if you chose to mix, deliver
# the mix first" (feature ``odd/tasks/mix-master-flow.md``) is only
# actionable when the backend owns this state. ``completed`` is the ONLY
# value that makes ``mix_path`` masterable.
MixStatus = Literal["none", "processing", "completed", "failed"]

# Which audio file a mastering run consumes: the uploaded original or the
# Mix Engine output. Resolved per request by ``/process`` (``source`` query
# param) — the smart default picks ``mix`` only when the mix is ``completed``
# and its file exists, otherwise ``original``.
MasterSource = Literal["original", "mix"]


class AnalysisResult(BaseModel):
    integrated_lufs: float
    true_peak_db: float
    dynamic_range_db: float
    spectral_centroid: float
    tempo_bpm: float
    duration_seconds: float
    sample_rate: int
    channels: int
    detected_genre: str = "other"
    genre_confidence: float = 0.0
    crest_factor_db: float = 0.0
    is_already_mastered: bool = False
    mastering_confidence: float = 0.0


class MasteringParameters(BaseModel):
    """Module-based mastering parameters — replaces fixed presets.

    Each group maps to a processing module in the DSP pipeline.
    Defaults represent a transparent/neutral master.
    """

    # ── Módulo Claridad — Reverb M/S + Brillo ────────────────────────
    clarity_wet: float = Field(
        0.15, ge=0, le=1.0,
        description="Reverb wet/dry mix for M/S spatial processing. 0 = dry, 1 = full reverb.",
    )
    clarity_brightness_db: float = Field(
        1.0, ge=-6, le=6,
        description="High-frequency boost/cut at 8 kHz. Positive = brighter air.",
    )

    # ── Preset character EQ (preset tonal signatures) ─────────────────
    # Declared in PRESET_CHAINS as the preset's audible identity: shelves
    # and peaks that render the character (bass punch, air, presence).
    # Empty list = no additional plugins (bit-exact bypass), so existing
    # masters are unchanged unless a preset explicitly ships bands.
    eq_bands: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Preset character EQ bands applied after match EQ: "
            "[{freq, max_gain_db, q, type: peak|low_shelf|high_shelf}]. "
            "Empty list = no additional plugins (bit-exact bypass)."
        ),
    )

    # ── Módulo Fuego / Empuje — Compresión + Límite + Transientes ────
    compression_ratio: float = Field(
        2.0, ge=1.0, le=10.0,
        description="Compression ratio. 1:1 = no compression, 10:1 = brickwall.",
    )
    limiter_ceiling_db: float = Field(
        -1.0, ge=-3.0, le=0.0,
        description="True-peak limiter ceiling in dBFS. -0.3 = loud, -3.0 = safe.",
    )
    transient_boost_db: float = Field(
        0.0, ge=0, le=6.0,
        description="Transient emphasis via wet compression mix. 0 = off, 6 = max punch.",
    )

    # ── Módulo Cinta / Saturación — THD + Calidez ────────────────────
    saturation_drive_db: float = Field(
        0.0, ge=0, le=10.0,
        description="Harmonic saturation drive (THD level). 0 = clean, 10 = heavy tape.",
    )
    saturation_warmth_db: float = Field(
        0.0, ge=-6.0, le=6.0,
        description="Warmth — gentle high-frequency roll-off (negative) or air boost (positive).",
    )

    # ── Módulo Espacial / Cinemático — Ancho estéreo + Haas ──────────
    stereo_width: float = Field(
        1.0, ge=0.5, le=2.0,
        description="Mid/Side stereo width multiplier. 1.0 = original, 2.0 = double width.",
    )
    haas_delay_ms: float = Field(
        0.0, ge=0, le=40.0,
        description="Haas (precedence) effect delay on Side signal in ms. 0 = off.",
    )

    # ── Stereo Imaging per-band (Sprint 9) ────────────────────────────
    # Replaces the broadband M/S width (linear mid cut, correlation-risky)
    # with an LR4 3-band constant-power width + lows-mono + correlation
    # safety. Disabled by default (all widths 1.0 = bit-exact bypass), so
    # existing masters are unchanged unless explicitly engaged.
    stereo_imaging_enabled: bool = Field(
        False,
        description="Enable the per-band stereo imaging stage. False = bit-exact bypass.",
    )
    stereo_imaging_low_width: float = Field(
        1.0, ge=0.0, le=2.0,
        description="Low-band (below crossover_low) stereo width multiplier.",
    )
    stereo_imaging_mid_width: float = Field(
        1.0, ge=0.0, le=2.0,
        description="Mid-band stereo width multiplier.",
    )
    stereo_imaging_high_width: float = Field(
        1.0, ge=0.0, le=2.0,
        description="High-band (above crossover_high) stereo width multiplier.",
    )
    stereo_imaging_mono_below_hz: float = Field(
        0.0, ge=0.0, le=400.0,
        description="Force low frequencies below this to mono center. 0 = off.",
    )

    # ── Side-channel HPF (Phase B — B1) — M/S low-end clean ────────────
    # Optional side high-pass below ~100 Hz: removes sub-bass room mud from
    # the DECORRELATED signal only (the mid/low-end weight stays). Disabled
    # by default (bit-exact bypass), so existing masters are unchanged; the
    # corner anchors between the corrective 30 Hz master HPF and the 120 Hz
    # mono-compat collapse.
    side_hpf_enabled: bool = Field(
        False,
        description=(
            "Enable the side-channel high-pass filter (sub-bass mud in the "
            "stereo decorrelation). False = bit-exact bypass."
        ),
    )
    side_hpf_hz: float = Field(
        100.0, ge=20.0, le=400.0,
        description=(
            "Side-channel high-pass corner in Hz. Sits below the 120 Hz "
            "mono-compat collapse and above the 30 Hz corrective master HPF."
        ),
    )

    output_bit_depth: int = Field(
        24, ge=16, le=32,
        description="Output bit depth. 16 applies noise-shaped dithering; 24+ is transparent.",
    )

    # ── Delivery / Compliance (Phase 1 — BandLab/LANDR-like delivery) ──
    # Backward-compatible defaults keep the engine's neutral fast-path
    # byte-identical: existing requests (no new fields) behave exactly as
    # today because every default matches the pristine model.
    processing_mode: Literal["master", "transparent"] = Field(
        "master",
        description=(
            "Processing mode. 'master' = the full adaptive chain (gain "
            "staging, HPF, match EQ, compression, saturation, automatic "
            "loudness). 'transparent' = delivery-only: optional SRC, "
            "optional explicit loudness + limiter, dither at 16-bit — no "
            "tone shaping and no automatic loudness target."
        ),
    )
    platform_target: Literal["spotify", "apple_music", "youtube", "tidal", "custom"] | None = Field(
        None,
        description=(
            "Delivery platform preset. Sets the loudness target and limiter "
            "ceiling: spotify -14 LUFS / -1.0 dBTP, apple_music -16 / -1.0, "
            "youtube -14 / -1.0 (YouTube also accepts -13 LUFS for louder "
            "masters — set target_lufs_db explicitly to use it), tidal "
            "-14 / -1.0. 'custom' keeps the sent values; None = no platform "
            "defaults applied."
        ),
    )
    output_sr: Literal["same_as_input", "44100", "48000", "96000", 44100, 48000, 96000] = Field(
        "same_as_input",
        description=(
            "Output sample rate. 'same_as_input' keeps the source rate; an "
            "explicit rate (int or str) resamples with libsoxr at VHQ "
            "quality. Accepted rates: 44100, 48000, 96000."
        ),
    )
    strict_mode: bool = Field(
        False,
        description=(
            "Reject the request (HTTP 422) when the input shows hard "
            "clipping or a true peak >= -0.3 dBTP, before any DSP runs."
        ),
    )

    # ── Loudness target (Sprint 1b) ────────────────────────────────────
    # When set, this overrides the engine's automatic loudness target
    # (which is derived from limiter_ceiling_db). None = keep the existing
    # automatic behavior so current masters are unchanged.
    target_lufs_db: float | None = Field(
        None, ge=-24.0, le=0.0,
        description="Explicit loudness target in LUFS (e.g. -14 Spotify, -16 Apple). "
        "None = derive automatically from limiter ceiling.",
    )

    # ── Multiband Compressor (Sprint 4) ────────────────────────────────
    # Disabled by default (ratio 1:1 stage = bit-exact bypass), so existing
    # masters are unchanged unless explicitly engaged.
    multiband_enabled: bool = Field(
        False,
        description="Enable the LR4 multiband compressor stage. False = bit-exact bypass.",
    )
    multiband_crossover_low_hz: float = Field(
        150.0, ge=40.0, le=1000.0,
        description="Low/mid Linkwitz-Riley crossover frequency in Hz.",
    )
    multiband_crossover_high_hz: float = Field(
        3000.0, ge=500.0, le=15000.0,
        description="Mid/high Linkwitz-Riley crossover frequency in Hz.",
    )
    multiband_low_threshold_db: float = Field(
        -20.0, ge=-60.0, le=0.0,
        description="Low-band compressor threshold in dBFS.",
    )
    multiband_mid_threshold_db: float = Field(
        -20.0, ge=-60.0, le=0.0,
        description="Mid-band compressor threshold in dBFS.",
    )
    multiband_high_threshold_db: float = Field(
        -20.0, ge=-60.0, le=0.0,
        description="High-band compressor threshold in dBFS.",
    )
    multiband_low_ratio: float = Field(
        1.0, ge=1.0, le=10.0,
        description="Low-band compression ratio. 1.0 = no compression (neutral).",
    )
    multiband_mid_ratio: float = Field(
        1.0, ge=1.0, le=10.0,
        description="Mid-band compression ratio. 1.0 = no compression (neutral).",
    )
    multiband_high_ratio: float = Field(
        1.0, ge=1.0, le=10.0,
        description="High-band compression ratio. 1.0 = no compression (neutral).",
    )

    # ── Dynamic EQ (Sprint 5) ───────────────────────────────────────────
    # Disabled by default (ratio 1:1 stage = bit-exact bypass). Three fixed
    # bell/Q bands — the roadmap's 400 Hz resonance case plus 2.5 kHz and
    # 8 kHz. Cuts only, and only above threshold, so the tone is never dulled
    # when the problem is absent.
    dyn_eq_enabled: bool = Field(
        False,
        description="Enable the dynamic EQ stage. False = bit-exact bypass.",
    )
    dyn_eq_band1_freq_hz: float = Field(
        400.0, ge=20, le=16000,
        description="Dynamic EQ band 1 center frequency (roadmap resonance case).",
    )
    dyn_eq_band1_q: float = Field(
        4.0, ge=0.5, le=20.0,
        description="Dynamic EQ band 1 bell width (Q).",
    )
    dyn_eq_band1_threshold_db: float = Field(
        -20.0, ge=-60, le=0,
        description="Dynamic EQ band 1 threshold in dBFS.",
    )
    dyn_eq_band1_ratio: float = Field(
        1.0, ge=1.0, le=10.0,
        description="Dynamic EQ band 1 ratio. 1.0 = no cut (neutral).",
    )
    dyn_eq_band2_freq_hz: float = Field(
        2500.0, ge=20, le=16000,
        description="Dynamic EQ band 2 center frequency in Hz.",
    )
    dyn_eq_band2_q: float = Field(
        4.0, ge=0.5, le=20.0,
        description="Dynamic EQ band 2 bell width (Q).",
    )
    dyn_eq_band2_threshold_db: float = Field(
        -20.0, ge=-60, le=0,
        description="Dynamic EQ band 2 threshold in dBFS.",
    )
    dyn_eq_band2_ratio: float = Field(
        1.0, ge=1.0, le=10.0,
        description="Dynamic EQ band 2 ratio. 1.0 = no cut (neutral).",
    )
    dyn_eq_band3_freq_hz: float = Field(
        8000.0, ge=20, le=16000,
        description="Dynamic EQ band 3 center frequency in Hz.",
    )
    dyn_eq_band3_q: float = Field(
        4.0, ge=0.5, le=20.0,
        description="Dynamic EQ band 3 bell width (Q).",
    )
    dyn_eq_band3_threshold_db: float = Field(
        -20.0, ge=-60, le=0,
        description="Dynamic EQ band 3 threshold in dBFS.",
    )
    dyn_eq_band3_ratio: float = Field(
        1.0, ge=1.0, le=10.0,
        description="Dynamic EQ band 3 ratio. 1.0 = no cut (neutral).",
    )

    # ── Harmonic Exciter (Sprint 6) ───────────────────────────────────────
    # Disabled by default (all amounts 0.0 = bit-exact bypass). Four
    # Ozone-style bands — bass (even), tube (even), tape (odd), air (odd) —
    # each with a dry/wet amount of its excited content, a drive for the
    # odd/tanh path, and a high-pass on the EXCITED content only so the bass
    # is not fattened. Restores harmonics lost after compression: even =
    # full-wave rectifier (warmth), odd = tanh soft-clip (presence), mix =
    # both.
    exciter_enabled: bool = Field(
        False,
        description="Enable the harmonic exciter stage. False = bit-exact bypass.",
    )
    exciter_band1_mode: str = Field(
        "even",
        description="Exciter band 1 (bass) harmonic curve: even, odd, or mix.",
    )
    exciter_band1_amount: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Exciter band 1 (bass) dry/wet mix of the excited content. 0.0 = neutral.",
    )
    exciter_band1_drive_db: float = Field(
        0.0, ge=0.0, le=24.0,
        description="Exciter band 1 (bass) drive in dB for the odd/tanh path.",
    )
    exciter_band1_low_cut_hz: float = Field(
        100.0, ge=20.0, le=20000.0,
        description="Exciter band 1 (bass) high-pass on the excited content in Hz.",
    )
    exciter_band2_mode: str = Field(
        "even",
        description="Exciter band 2 (tube) harmonic curve: even, odd, or mix.",
    )
    exciter_band2_amount: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Exciter band 2 (tube) dry/wet mix of the excited content. 0.0 = neutral.",
    )
    exciter_band2_drive_db: float = Field(
        0.0, ge=0.0, le=24.0,
        description="Exciter band 2 (tube) drive in dB for the odd/tanh path.",
    )
    exciter_band2_low_cut_hz: float = Field(
        200.0, ge=20.0, le=20000.0,
        description="Exciter band 2 (tube) high-pass on the excited content in Hz.",
    )
    exciter_band3_mode: str = Field(
        "odd",
        description="Exciter band 3 (tape) harmonic curve: even, odd, or mix.",
    )
    exciter_band3_amount: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Exciter band 3 (tape) dry/wet mix of the excited content. 0.0 = neutral.",
    )
    exciter_band3_drive_db: float = Field(
        0.0, ge=0.0, le=24.0,
        description="Exciter band 3 (tape) drive in dB for the odd/tanh path.",
    )
    exciter_band3_low_cut_hz: float = Field(
        200.0, ge=20.0, le=20000.0,
        description="Exciter band 3 (tape) high-pass on the excited content in Hz.",
    )
    exciter_band4_mode: str = Field(
        "odd",
        description="Exciter band 4 (air) harmonic curve: even, odd, or mix.",
    )
    exciter_band4_amount: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Exciter band 4 (air) dry/wet mix of the excited content. 0.0 = neutral.",
    )
    exciter_band4_drive_db: float = Field(
        0.0, ge=0.0, le=24.0,
        description="Exciter band 4 (air) drive in dB for the odd/tanh path.",
    )
    exciter_band4_low_cut_hz: float = Field(
        800.0, ge=20.0, le=20000.0,
        description="Exciter band 4 (air) high-pass on the excited content in Hz.",
    )

    # ── Tape Saturation (Sprint 7) ────────────────────────────────────────────
    # Disabled by default: the engine keeps the legacy tanh saturation path
    # (existing masters unchanged) unless tape_enabled engages the REAL tape
    # model. NEUTRAL defaults (drive 0, no hysteresis/bias/roll-off) = bit-exact
    # bypass even when enabled, so the model can be engaged without altering
    # the signal until the knobs move.
    tape_enabled: bool = Field(
        False,
        description="Enable the real tape saturation model. False = legacy tanh path.",
    )
    tape_drive_db: float = Field(
        0.0, ge=0.0, le=24.0,
        description="Tape drive in dB. 0 = neutral (bit-exact bypass).",
    )
    tape_hysteresis: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Magnetic memory strength (k, hysteresis recursion). 0 = neutral.",
    )
    tape_bias: float = Field(
        0.0, ge=0.0, le=0.2,
        description="Gentle asymmetry (DC offset) — mixes in even harmonics.",
    )
    tape_rolloff_amount: float = Field(
        0.0, ge=0.0, le=1.0,
        description="Level-dependent HF roll-off strength. 0 = neutral.",
    )
    tape_hf_shelf_hz: float = Field(
        8000.0, ge=1000.0, le=20000.0,
        description="HF roll-off corner above which high levels are attenuated.",
    )

    # ── Adaptive Compressor (Sprint 8) ────────────────────────────────────────
    # Disabled by default: the engine keeps the fixed −16 dB compressor stage
    # (existing masters unchanged) unless adaptive_comp_enabled engages the
    # program-dependent module. NEUTRAL defaults (ratio 1.0) = bit-exact
    # bypass even when enabled, so the model can be engaged without altering
    # the signal until the ratio moves.
    adaptive_comp_enabled: bool = Field(
        False,
        description="Enable the adaptive (program-dependent) compressor. "
        "False = fixed −16 dB stage.",
    )
    adaptive_comp_ratio: float = Field(
        1.0, ge=1.0, le=12.0,
        description="Compression ratio. 1.0 = neutral (bit-exact bypass).",
    )
    adaptive_comp_threshold_offset_db: float = Field(
        6.0, ge=0.0, le=16.0,
        description="Margin (dB) below the program RMS at which the "
        "adaptive threshold sits. Larger = gentler compression.",
    )
    adaptive_comp_attack_ms: float = Field(
        10.0, ge=1.0, le=50.0,
        description="Base attack time used at high program crest "
        "(percussion). Scaled down for lower crest.",
    )
    adaptive_comp_release_ms: float = Field(
        200.0, ge=50.0, le=800.0,
        description="Base release time used at low program crest (tails, "
        "pads). Scaled down for higher crest.",
    )
    adaptive_comp_makeup_db: float = Field(
        0.0, ge=0.0, le=12.0,
        description="Makeup gain applied after compression. 0 = none.",
    )

    # ── Time-Based Effects (Sprint 10) — Delay / Echo / Reverb ────────────────
    # Disabled by default (mix 0.0 = bit-exact bypass), so existing masters
    # are unchanged unless explicitly engaged. Each module follows the opt-in
    # contract: enabling the flag while the mix stays 0.0 is STILL a bit-exact
    # no-op (is_neutral → the pass is skipped), so the timing knobs
    # (time/feedback/size) never alter the signal until the mix moves.
    delay_enabled: bool = Field(
        False,
        description="Enable the delay stage. False = bit-exact bypass.",
    )
    delay_time_ms: float = Field(
        250.0, ge=20, le=2000,
        description="Delay time in ms. 0 = neutral",
    )
    delay_mix: float = Field(
        0.0, ge=0, le=1,
        description="Dry/wet mix of the delayed signal. 0.0 = no effect (neutral)",
    )
    delay_feedback: float = Field(
        0.0, ge=0, le=0.8,
        description=(
            "Feedback amount for repeated echoes. 0.0 = single repeat "
            "(neutral)"
        ),
    )

    echo_enabled: bool = Field(
        False,
        description="Enable the echo stage. False = bit-exact bypass.",
    )
    echo_time_ms: float = Field(
        400.0, ge=50, le=2000,
        description="Echo time in ms. 0 = neutral",
    )
    echo_mix: float = Field(
        0.0, ge=0, le=1,
        description="Dry/wet mix of the echo. 0.0 = no effect (neutral)",
    )
    echo_feedback: float = Field(
        0.0, ge=0, le=0.9,
        description="Echo feedback — cascading repeats. 0.0 = single repeat (neutral)",
    )

    reverb_enabled: bool = Field(
        False,
        description="Enable the reverb stage. False = bit-exact bypass.",
    )
    reverb_mix: float = Field(
        0.0, ge=0, le=1,
        description="Dry/wet mix of the reverb. 0.0 = no effect (neutral)",
    )
    reverb_size: float = Field(
        0.5, ge=0.1, le=1.0,
        description="Reverb room size / decay. 0.1 = small room, 1.0 = huge hall",
    )

    # ── Dynamic De-Esser (Phase B — B2) — sibilance 3-8 kHz ─────────────
    # Dynamic sibilance taming in the MASTER chain (the legacy static
    # de-esser lives only in the /vocal path). The 3-8 kHz band is
    # attenuated only while it is a dominant spectral region, with
    # attack/release smoothing. Disabled by default (bit-exact bypass);
    # enabling with amount 0.0 is STILL a bit-exact no-op, and material
    # below the detector threshold passes through bit-exactly too.
    deesser_enabled: bool = Field(
        False,
        description=(
            "Enable the dynamic de-esser for sibilance (3-8 kHz). "
            "False = bit-exact bypass."
        ),
    )
    deesser_amount_db: float = Field(
        0.0, ge=0.0, le=12.0,
        description=(
            "Maximum gain reduction in the sibilance band at full detector "
            "drive. 0 = neutral (bit-exact bypass even when enabled)."
        ),
    )
    deesser_threshold_db: float = Field(
        -4.0, ge=-12.0, le=0.0,
        description=(
            "Sibilance detector threshold in dB: the 3-8 kHz band must "
            "exceed this ratio over the broadband level before reduction "
            "starts. Matches the module anchor (audiomind.processing."
            "deesser.DEESSER_THRESHOLD_DB)."
        ),
    )

    # ── Stereo Shuffler 3-Band (Mix→Master Handshake) ───────────────────────────
    # Opt-in frequency-dependent width via LR4 crossover (phase-zero, float64).
    # Mutually exclusive with legacy broadband width and stereo_imaging: when
    # enabled, the legacy broadband width stage is skipped in the master chain.
    # Defaults are neutral (disabled + neutral widths) for backward compatibility.
    stereo_shuffler_enabled: bool = Field(
        default=False,
        description="Enable the 3-band Stereo Shuffler (LR4 phase-zero). False = legacy M/S width only."
    )
    stereo_shuffler_width_low: float = Field(
        default=0.0, ge=0.0, le=2.0,
        description="Width factor for LOW band (< crossover_low). 0.0 = mono strict."
    )
    stereo_shuffler_width_mid: float = Field(
        default=1.0, ge=0.0, le=2.0,
        description="Width factor for MID band (crossover_low – crossover_high). 1.0 = neutral."
    )
    stereo_shuffler_width_high: float = Field(
        default=1.3, ge=0.0, le=3.0,
        description="Width factor for HIGH band (> crossover_high). >1.0 = expanded air."
    )
    stereo_shuffler_crossover_low: float = Field(
        default=120.0, ge=20.0, le=500.0,
        description="Low/Mid crossover frequency in Hz (default 120 Hz)."
    )
    stereo_shuffler_crossover_high: float = Field(
        default=2500.0, ge=1000.0, le=8000.0,
        description="Mid/High crossover frequency in Hz (default 2500 Hz)."
    )

    @model_validator(mode="after")
    def _apply_platform_defaults(self) -> "MasteringParameters":
        """Apply platform delivery defaults for known targets.

        Only runs when ``platform_target`` is an explicit known platform;
        ``custom`` (and None) leave the sent values untouched so user
        settings always win. Backward compatible by construction: the
        pristine default model keeps ``platform_target=None``, so the
        engine's neutral fast-path equality check is unaffected and
        existing requests behave exactly as today.
        """
        if self.platform_target is None or self.platform_target == "custom":
            return self
        _platform_loudness: dict[str, tuple[float, float]] = {
            "spotify": (-14.0, -1.0),
            "apple_music": (-16.0, -1.0),
            "youtube": (-14.0, -1.0),
            "tidal": (-14.0, -1.0),
        }
        lufs_db, ceiling_db = _platform_loudness[self.platform_target]
        self.target_lufs_db = lufs_db
        self.limiter_ceiling_db = ceiling_db
        return self


class MasterResultMetrics(BaseModel):
    """Measured metrics of the final master output.

    All fields are nullable by design: the pre-built cache path can only
    measure best-effort, so old clients and cache hits never break.
    """

    integrated_lufs: float | None = None
    true_peak_db: float | None = None
    crest_factor_db: float | None = None
    limiter_ceiling_db: float | None = None
    duration_seconds: float | None = None
    sample_rate: int | None = None
    output_bit_depth: int | None = None
    stereo_correlation: float | None = None
    lra: float | None = None


class MasteringReport(BaseModel):
    """Delivery compliance report (Compliance Phase 1).

    Nullable fields by design: unmeasured values (pure passthrough renders
    without a loudness target, pre-built cache hits that never re-measure)
    stay None so the report never invents numbers.

    Fields:
        input_sr: Source sample rate of the uploaded file.
        output_sr: Delivered sample rate (after SRC, if any).
        output_bit_depth: Delivered PCM bit depth.
        lufs_i: Measured integrated loudness of the delivered file.
        true_peak_dbtp: Measured true peak of the delivered file.
        lra: Approximate Loudness Range (EBU 3342-style) in LU.
        crest_factor_db: Measured crest factor of the delivered file.
        target_lufs: The ACTUAL loudness target used (None = none applied).
        warnings: Input QC / delivery warnings, in Spanish (neutral Latin American).
    """

    input_sr: int | None = None
    output_sr: int | None = None
    output_bit_depth: int | None = None
    lufs_i: float | None = None
    true_peak_dbtp: float | None = None
    lra: float | None = None
    crest_factor_db: float | None = None
    stereo_correlation: float | None = None
    target_lufs: float | None = None
    warnings: list[str] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    """Single out-of-tolerance metric found by the Layer 2 gate."""

    metric: Literal["lufs", "crest", "true_peak"]
    measured: float
    expected: str
    message_es: str


class ReferenceRenderResult(BaseModel):
    """On-demand Crudo reference render (Layer 3 fair A/B).

    The neutral chain (natural preset character) rendered with the
    source preset's loudness targets, so the user judges character —
    not volume — when comparing against their master.
    """

    reference_path: str
    target_lufs: float
    source_preset_id: str


class ReferenceComparison(BaseModel):
    """External-reference comparison (Phase C, P1-1).

    Measurement-only metadata contrasting the mastered output against an
    uploaded external reference file. No DSP processing runs here: every
    value is a measurement of one of the two files or a
    ``reference − master`` delta, so the neutral contract (comparison
    never changes the master) holds by construction.

    Deltas are ``reference − master``: a positive ``band_deltas_db``
    entry means the reference has MORE energy in that band (a "too quiet
    here" hint for the master). All fields are nullable by design so a
    partial measurement never breaks the payload.

    ``status`` is ``"ready"`` after a successful full comparison, or one
    of ``"no_master"`` / ``"no_reference"`` / ``"error"`` for partial
    states (with ``message`` explaining why).
    """

    status: Literal["ready"] | str = "ready"
    message: str | None = None
    reference_filename: str | None = None
    target_bands_hz: list[int] | None = None
    master_band_levels_db: list[float] | None = None
    reference_band_levels_db: list[float] | None = None
    band_deltas_db: list[float] | None = None
    biggest_increase_band_hz: float | None = None
    biggest_decrease_band_hz: float | None = None
    master_lufs_db: float | None = None
    reference_lufs_db: float | None = None
    lufs_delta_db: float | None = None
    master_crest_db: float | None = None
    reference_crest_db: float | None = None
    crest_delta_db: float | None = None
    master_correlation: float | None = None
    reference_correlation: float | None = None
    master_lra_lu: float | None = None
    reference_lra_lu: float | None = None
    lra_delta_lu: float | None = None


class ReferenceUploadResult(BaseModel):
    """Result of uploading an external reference file for a session."""

    reference_path: str
    reference_filename: str


class ValidationReport(BaseModel):
    """Post-master validation verdict (Layer 2 gate).

    Nullable by design on the session: when there is no master_result
    (or no active preset to compare against), validation stays null.
    """

    status: Literal["ok", "warning"]
    issues: list[ValidationIssue] = Field(default_factory=list)
    retry_recommended: bool = False
    retry_applied: bool = False
    suggested_preset_id: str | None = None
    note: str | None = None


class PresetMasterEntry(BaseModel):
    """Per-preset mastered output record for a session.

    Additive to ``SessionData``: sessions persisted before this field
    existed load with an empty ``preset_masters`` dict (safe default), so
    old ``uploads/sessions.json`` data keeps its meaning. Created by the
    on-demand ``/process?preset_id=X`` path and by the pre-render cache
    hit path (so ``?preset_id=`` lookups work in every mode).

    ``status`` mirrors ``_prerender_cache`` semantics:
    ``pending | processing | completed | error``.
    """

    preset_id: str
    output_path: str | None = None
    # Durable R2 pointer for this preset's master. ``output_path`` is a LOCAL
    # path and Railway has no persistent disk, so a redeploy leaves it dangling;
    # this key is what re-hydrates the WAV from storage.
    r2_key: str | None = None
    master_result: MasterResultMetrics | None = None
    validation: ValidationReport | None = None
    status: str = "pending"
    progress: float = 0.0
    error: str | None = None
    created_at: float | None = None


class SessionData(BaseModel):
    session_id: str
    status: ProcessingStatus = ProcessingStatus.UPLOADED
    progress: float = 0.0
    original_path: str | None = None
    original_filename: str | None = None
    reference_path: str | None = None
    reference_filename: str | None = None
    reference_comparison: ReferenceComparison | None = None
    mastered_path: str | None = None
    # Durable R2 pointer for ``mastered_path``. Same story as
    # ``PresetMasterEntry.r2_key``: the local path is ephemeral on Railway, so
    # this key is the only thing that survives a redeploy. Independent of the
    # per-preset keys, because ``mastered_path`` is its own pointer.
    master_r2_key: str | None = None
    analysis: AnalysisResult | None = None
    parameters: MasteringParameters = MasteringParameters()
    master_result: MasterResultMetrics | None = None
    mastering_report: MasteringReport | None = None
    validation: ValidationReport | None = None
    error: str | None = None
    # Per-preset mastered outputs (client demo mode). ``mastered_path``
    # stays the legacy "last processed / currently selected" pointer and is
    # kept in sync on every successful preset process.
    preset_masters: dict[str, PresetMasterEntry] = Field(default_factory=dict)
    # Mix Engine (Paso 01): the mix is NOT the master — it lives on its own
    # pointer/analysis pair so the mastering pipeline is never affected.
    # ``mix_analysis`` mirrors the ``X-Mix-Result`` payload served by
    # POST /api/session/{id}/mix (per-stem analysis + full-mix tempo/genre).
    mix_path: str | None = None
    mix_analysis: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Mix Engine JSON analysis payload: per-stem analysis dict plus "
            "full-mix tempo_bpm / genre / genre_confidence."
        ),
    )
    # Lifecycle of the mix, kept OUT of ``mix_analysis`` on purpose: the
    # analysis dict is the snapshot of the LAST SUCCESSFUL mix, while this
    # field is the live state (``processing`` while the pipeline runs,
    # ``failed`` on error) and is what ``/process?source=mix`` reads before
    # consuming ``mix_path``. Defaults to ``none`` so sessions persisted
    # before the field existed keep loading unchanged.
    mix_status: MixStatus = "none"
    # Mix Engine metadata for adaptive mastering (Mix → Master handshake).
    # Populated by POST /mix via build_mix._compute_mix_metadata().
    mix_metadata: dict | None = Field(
        default=None,
        description="Metadatos de mezcla serializados (MixMetadata.model_dump()) para master adaptativo"
    )
    # Durable pointer to the delivered mix in Cloudflare R2. ``mix_path`` is a
    # LOCAL path and Railway has no persistent disk, so a redeploy leaves the
    # session pointing at a file that no longer exists. This key survives, and
    # the mastering resolver re-downloads the bytes from it when needed. It is
    # the async mix path (``POST /api/jobs/mix/{id}``) that sets it; sessions
    # persisted before it existed keep loading with ``None``.
    mix_r2_key: str | None = Field(
        default=None,
        description=(
            "Clave del WAV de mezcla en Cloudflare R2. Único puntero que "
            "sobrevive al redeploy cuando el archivo local se pierde."
        ),
    )


class BeatData(BaseModel):
    """Represents a generated beat / songstarter project.

    Stores full generation parameters and output paths for each stem
    plus the mixed WAV.
    """

    beat_id: str
    bpm: float
    scale: str
    root_note: str
    swing_amount: float = 0.3
    duration: float = 0.0
    output_path: str = ""
    stems: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Album / EP batch mastering (Phase D, P1-2) ───────────────────────────
# Relative LUFS/DR target negotiation across several sessions. Purely
# additive and backward-compatible by design: every request field defaults
# to the album defaults (None → -14.0 LUFS base, list → empty) and every
# result field is nullable so partial measurements never break the payload.
# The batch surface only COMPUTES ``target_lufs_db`` numbers and feeds them
# through the existing single-track pipeline — no new DSP, no audio
# mutation — preserving the neutral = bypass contract.


class AlbumNegotiateRequest(BaseModel):
    """Body for POST /api/album/negotiate (measurement-only)."""

    session_ids: list[str] = Field(default_factory=list)
    target_lufs_db: float | None = None  # album base; None -> -14.0


class AlbumProcessRequest(BaseModel):
    """Body for POST /api/album/process (master toward relative targets)."""

    session_ids: list[str] = Field(default_factory=list)
    target_lufs_db: float | None = None  # album base; None -> -14.0
    parameters: MasteringParameters = MasteringParameters()


class AlbumNegotiationTrack(BaseModel):
    """Per-track negotiation result (measurement-only, no DSP).

    Nullable by design: tracks whose file could not be loaded keep their
    metrics null and receive the album base unchanged, so the negotiation
    never fails the whole album for one bad track.
    """

    session_id: str
    original_filename: str | None = None
    input_lufs_db: float | None = None
    input_lra_lu: float | None = None
    negotiated_target_lufs_db: float | None = None
    offset_db: float | None = None


class AlbumNegotiationResult(BaseModel):
    """Result of POST /api/album/negotiate."""

    target_base_lufs_db: float
    lra_median_lu: float | None = None
    tracks: list[AlbumNegotiationTrack] = Field(default_factory=list)


class AlbumProcessTrack(BaseModel):
    """Per-track album mastering result.

    ``lufs_deviation_db`` is ``output_lufs_db − negotiated_target_lufs_db``
    (positive = louder than the negotiated target). ``within_tolerance`` is
    True when the deviation falls inside ±ALBUM_LUFS_TOLERANCE_DB (1.5 dB);
    a track that FAILED to process keeps all metrics null, carries the
    error in ``warnings`` (exception type + message, preserving
    IOError/InputQcError verbatim) and is marked ``within_tolerance=False``
    so consumers can filter failures — the album never aborts mid-way.
    """

    session_id: str
    original_filename: str | None = None
    negotiated_target_lufs_db: float | None = None
    output_lufs_db: float | None = None
    output_lra_lu: float | None = None
    output_crest_db: float | None = None
    output_true_peak_dbtp: float | None = None
    lufs_deviation_db: float | None = None  # output − target (+ = louder)
    within_tolerance: bool = True
    warnings: list[str] = Field(default_factory=list)


class AlbumProcessResult(BaseModel):
    """Result of POST /api/album/process."""

    target_base_lufs_db: float
    lra_median_lu: float | None = None
    tracks: list[AlbumProcessTrack] = Field(default_factory=list)
