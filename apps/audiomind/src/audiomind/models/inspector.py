"""Content-aware inspection contract — what the analysis stage MEASURED.

This is the measurement half of the content-aware pipeline. A profile here
describes what ``audiomind.analysis.inspector`` observed in the uploaded
material; it never says what should be done about it. Downstream stages (Mix
Engine, Mastering) read these numbers instead of decoding the audio again.

The one property every field shares: it is derived from a read-only decode.
The inspector filters nothing, delays nothing and saturates nothing — it
measures. Any profile produced here is safe to compute on the same file the
master will later be rendered from.

Contract source of truth for the values: ``audiomind.analysis.inspector``
holds the calibration constants the verdicts below are derived from.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: Beat-accent period read off the autocorrelation, expressed in beats.
AccentGrouping = Literal["4/4", "3/4", "unknown"]

#: Tempo-locked note division a creative stage should default to. ``"none"``
#: means no usable tempo was found, so nothing may be locked to the grid.
Subdivision = Literal["1/4", "1/8", "1/8d", "1/8t", "1/16", "none"]

#: Which audio the rhythm measurement was taken from.
RhythmSource = Literal["drums_stem", "input_mix", "none"]

#: Which audio the vocal measurement was taken from.
VocalSource = Literal["vocals_stem", "input_mix"]

#: Whether a telephone-style band-limit may be applied to this material.
#: ``full`` = safe, ``partial`` = usable but keep the band narrow and the wet
#: level low, ``refuse`` = do not band-limit this material at all.
LofiPermission = Literal["full", "partial", "refuse"]

#: Why permission was refused. ``"none"`` when it was granted. Kept separate
#: from the verdict so a caller can tell "no voice here" (nothing to treat)
#: from "the voice would not survive it" (a real constraint).
LofiRefusalReason = Literal[
    "none",
    "unvoiced",
    "low_fundamental",
    "narrowband",
    "insufficient_air",
    "insufficient_articulation",
]


class RhythmProfile(BaseModel):
    """Tempo and beat-grid measurement for one rhythm source.

    Measured from the drum stem whenever the caller supplied one (a full mix
    hides the grid behind the arrangement), and from the mix otherwise. The
    ``source`` field records which, so ``input_mix`` profiles can be treated
    as the weaker evidence they are.
    """

    model_config = ConfigDict(extra="forbid")

    tempo_bpm: float | None = Field(
        None,
        ge=0.0,
        le=400.0,
        description="Tempo from the median beat interval. None when no beat "
        "grid was found at all. Reported even when it is unreliable — "
        "tempo_confidence is what decides whether to use it.",
    )
    tempo_confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="How far to trust tempo_bpm, from interval dispersion "
        "weighted by how many beats were observed. 0.0 = do not lock anything "
        "to this grid.",
    )
    beat_times: list[float] = Field(
        default_factory=list,
        description="Beat positions in seconds, ascending.",
    )
    accent_period_beats: int | None = Field(
        None,
        ge=2,
        le=16,
        description="Strongest accent autocorrelation lag, in beats. None when "
        "the beat levels carry no usable contrast, which makes any grouping "
        "verdict meaningless.",
    )
    accent_grouping: AccentGrouping = Field(
        "unknown",
        description="Musical reading of accent_period_beats. A measured "
        "two-beat accent cycle is read as 4/4, which is the common case in "
        "this repertoire; a three-beat cycle is read as 3/4.",
    )
    grouping_confidence: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Autocorrelation strength behind accent_grouping.",
    )
    accent_contrast_db: float = Field(
        0.0,
        ge=0.0,
        le=60.0,
        description="Loudest-to-typical beat level ratio. Near 0 dB means a "
        "flat grid with no accent pattern worth grouping.",
    )
    subdivision_default: Subdivision = Field(
        "none",
        description="Note division a creative stage should lock to. "
        "Meter-agnostic by design: the default works in both 4/4 and 3/4.",
    )
    source: RhythmSource = Field(
        "none",
        description="Which audio produced this profile.",
    )


class VocalViability(BaseModel):
    """Whether the voice in this material survives a band-limited treatment.

    The telephone effect trades the voice's extremes for intelligibility: it
    removes everything below ~300 Hz and above ~3.4 kHz. That is safe when
    the voice has body and air to spare, and destructive when it does not.
    The verdict answers that question; the measurements that produced it are
    kept alongside so a caller can re-decide under a different threshold.
    """

    model_config = ConfigDict(extra="forbid")

    source: VocalSource = Field(
        "input_mix",
        description="Which audio produced this profile. A mix measurement is "
        "weaker evidence than a vocals stem and should be read as such.",
    )
    band_energies_db: dict[str, float] = Field(
        default_factory=dict,
        description="Per-band energy relative to the full-band total, in dB. "
        "Keys follow audiomind.analysis.inspector.VOCAL_BAND_ORDER.",
    )
    articulation_ratio: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Energy in 1-4 kHz over energy in 200 Hz - 8 kHz: the "
        "share of the voice a telephone band-pass keeps.",
    )
    hf_ratio: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Share of total energy above 6 kHz: the air a telephone "
        "filter removes. Near zero means the treatment has nothing to trade.",
    )
    median_f0_hz: float | None = Field(
        None,
        ge=0.0,
        description="Median voiced fundamental. None when too few frames "
        "carried a detectable pitch to call the material a voice.",
    )
    voiced_fraction: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Share of analysed frames carrying a detectable "
        "fundamental. This is the gate behind median_f0_hz.",
    )
    lofi_permission: LofiPermission = Field(
        "refuse",
        description="Whether a telephone-style band-limit is safe here. "
        "Refusing by default is deliberate: the conservative answer keeps a "
        "creative stage from mangling material it cannot help.",
    )
    refusal_reason: LofiRefusalReason = Field(
        "unvoiced",
        description="Why permission was refused. 'none' when granted.",
    )


class NegativeSpace(BaseModel):
    """Where the program leaves room for a textural bed.

    A bed only earns its place if the program is quiet somewhere; otherwise
    it masks instead of adding. The ratio is measured against the loudest
    frame of the same program, so it is level-independent.
    """

    model_config = ConfigDict(extra="forbid")

    negative_space_ratio: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of frames sitting at or below gate_db relative "
        "to the loudest frame.",
    )
    gate_db: float = Field(
        -40.0,
        le=0.0,
        description="The relative gate the ratio was counted against, "
        "recorded so the ratio stays interpretable. Set by the inspector to "
        "audiomind.analysis.inspector.NEGATIVE_SPACE_GATE_DB.",
    )
    bed_authorized: bool = Field(
        False,
        description="True when negative_space_ratio reaches the inspector's "
        "minimum. False means no bed should be laid under this program.",
    )


class InspectorProfile(BaseModel):
    """Everything the content-aware pipeline knows before it changes a sample.

    Assembled by ``audiomind.analysis.inspector.inspect_input`` and intended
    to travel into the mix -> master handshake alongside ``MixMetadata``.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(
        1,
        ge=1,
        description="Schema version, for future migrations.",
    )
    input_sample_rate: int = Field(
        ge=1,
        description="Native sample rate of the decoded input.",
    )
    analysis_sample_rate: int = Field(
        ge=1,
        description="Sample rate every measurement below was taken at, so "
        "beat_times and frame counts stay interpretable.",
    )
    duration_seconds: float = Field(
        ge=0.0,
        description="Duration of the analysed input.",
    )
    rhythm: RhythmProfile = Field(
        description="Tempo and beat grid.",
    )
    vocal_viability: VocalViability = Field(
        description="Whether the voice survives a band-limited treatment.",
    )
    negative_space: NegativeSpace = Field(
        description="Whether the program leaves room for a textural bed.",
    )
