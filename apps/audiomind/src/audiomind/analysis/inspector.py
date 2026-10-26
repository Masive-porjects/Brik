"""Content-aware inspection: measurement only, zero DSP.

The Mix Engine and the Mastering chain both need to know what is *in* the
material before they decide what to do to it — is there a usable tempo, will
the voice survive a band-limited treatment, does the program leave room for a
textural bed. This module answers those three questions and nothing else. It
filters nothing, delays nothing and saturates nothing: every function here
decodes an input read-only and returns numbers.

IMPLEMENTED (P1-GREEN). All three measurements are live and driven by the
suite in ``tests/test_inspector.py``. They were built RED-first: the
calibrations below were fixed against the fixture corpus *before* the bodies
existed, so the tests decide the behaviour and the constants, never the other
way around. Tuning a threshold means editing the constant here, which is
exactly what each test asserts against.

CALIBRATIONS. The numeric thresholds are derived from measurements on the
fixture corpus (a synthetic click track, a pure tone, broadband noise, a
harmonic voice with a formant lift and breath air, a program with a real
silence gap) and each one sits with several dB or several tenths of margin
against the cases it must separate. They are not magic numbers: they are the
boundaries this pipeline is willing to act on, and they are expected to be
re-tuned after an A/B against real material. The separation each threshold
buys is recorded in the test suite.

Known measurement gotcha: ``librosa.pyin`` halves the reported pitch of a
pure tone (a 1 kHz sine measures as ~500 Hz), because a single partial offers
no octave evidence. The fundamental is therefore only trusted when enough
frames carry a detectable pitch; see ``VOICED_FRACTION_MIN``.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Final

import librosa
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

from audiomind.models.inspector import (
    AccentGrouping,
    InspectorProfile,
    LofiPermission,
    LofiRefusalReason,
    NegativeSpace,
    RhythmProfile,
    RhythmSource,
    Subdivision,
    VocalSource,
    VocalViability,
)

# ── Analysis configuration ──────────────────────────────────────────────

#: Rate every measurement runs at. Low enough to keep librosa cheap, high
#: enough to keep the 6-10 kHz air band below Nyquist.
INSPECTOR_SR: Final[int] = 22050

#: Frame hop for the onset/beat analysis. 256 frames at 22050 Hz is 11.6 ms,
#: which keeps a 120 BPM grid (500 ms = 43.0 hops) from quantising into a
#: wrong tempo the way a 512-sample hop does.
INSPECTOR_HOP_LENGTH: Final[int] = 256

#: Bound on how much audio the content measurements decode.
MAX_ANALYSIS_SECONDS: Final[float] = 120.0

#: Bound on how much audio the pitch tracker sees. ``pyin`` dominates the
#: cost of this module and its output is a median, so more audio stops
#: changing the answer long before it stops costing time.
MAX_F0_SECONDS: Final[float] = 30.0

# ── Band slicing for the voice measurements ─────────────────────────────

#: Order of the band-pass used to slice the spectrum. Steeper than the
#: QC layer's order 2 on purpose: those filters gate a warning, these
#: numbers feed a verdict, so filter leakage must not invent body content
#: in a signal that has none.
BAND_FILTER_ORDER: Final[int] = 4

#: Floor for every relative band level, so an empty band reads as a number
#: instead of ``-inf``.
BAND_FLOOR_DB: Final[float] = -60.0

#: Distance kept from Nyquist when clamping a band's top edge. A band whose
#: top edge lands on Nyquist has no representable filter at this rate, and a
#: clamped filter would report a number for a band that was never measured.
BAND_EDGE_MARGIN_HZ: Final[float] = 200.0

#: Canonical band order. Every ``band_energies_db`` mapping carries exactly
#: these keys, in this order, so consumers and reports need no lookup table.
VOCAL_BAND_ORDER: Final[tuple[str, ...]] = (
    "sub_100",
    "body_100_500",
    "low_mid_500_1k",
    "articulation_1k_4k",
    "presence_4k_6k",
    "air_6k_10k",
)

#: Band edges in Hz. The top band stops at 10 kHz to stay clear of the
#: 11.025 kHz Nyquist at ``INSPECTOR_SR``.
VOCAL_BANDS_HZ: Final[dict[str, tuple[float, float]]] = {
    "sub_100": (20.0, 100.0),
    "body_100_500": (100.0, 500.0),
    "low_mid_500_1k": (500.0, 1000.0),
    "articulation_1k_4k": (1000.0, 4000.0),
    "presence_4k_6k": (4000.0, 6000.0),
    "air_6k_10k": (6000.0, 10000.0),
}

#: The band a telephone treatment keeps, used as the denominator of the
#: articulation ratio.
VOICE_CORE_HZ: Final[tuple[float, float]] = (200.0, 8000.0)

# ── Rhythm calibration ─────────────────────────────────────────────────

#: Interval-dispersion ceiling. At or above this coefficient of variation
#: the beat grid is too irregular to trust, and tempo confidence reaches 0.
IBI_CV_UNUSABLE: Final[float] = 0.25

#: Beat counts below which the grid is treated as thin evidence. Confidence
#: ramps linearly from ``MIN_BEATS_FOR_TEMPO`` to ``FULL_CONFIDENCE_BEATS``
#: and is zero below the minimum.
MIN_BEATS_FOR_TEMPO: Final[int] = 4
FULL_CONFIDENCE_BEATS: Final[int] = 16

#: Contract ceiling on a reported tempo, mirroring ``RhythmProfile``. A grid
#: implying more than this is a tracker artefact, not a tempo, so the tempo
#: is dropped rather than clamped: a clamped BPM is a wrong BPM that still
#: looks usable to whatever locks to it.
TEMPO_MAX_BPM: Final[float] = 400.0

#: Window after each beat from which that beat's accent level is taken. Long
#: enough to catch a kick, short enough not to swallow the next beat.
ACCENT_WINDOW_S: Final[float] = 0.05

#: Minimum loudest-to-typical beat level ratio before accent grouping means
#: anything. A flat grid still autocorrelates a little through numerical
#: residue, and those spurious lags must not be read as a meter.
ACCENT_CONTRAST_MIN_DB: Final[float] = 3.0

#: Minimum autocorrelation behind a grouping verdict.
GROUPING_MIN_CONFIDENCE: Final[float] = 0.40

#: Lags searched for the accent period, in beats.
GROUPING_LAGS: Final[tuple[int, ...]] = (2, 3, 4)

#: Accent period -> musical meter. A measured two-beat accent cycle is read
#: as 4/4 because that is what a kick-snare backbeat produces; 2/4 is not
#: read out of a level pattern this coarse.
ACCENT_LAG_TO_GROUPING: Final[dict[int, AccentGrouping]] = {
    2: "4/4",
    3: "3/4",
    4: "4/4",
}

#: Note division locked to the grid. The dotted eighth is the meter-agnostic
#: default: it reads as a slapback in 4/4 and stays musical in 3/4.
SUBDIVISION_DEFAULT: Final[Subdivision] = "1/8d"

#: Reported when there is no grid to lock to.
SUBDIVISION_NONE: Final[Subdivision] = "none"

# ── Vocal viability calibration ────────────────────────────────────────

F0_FMIN_HZ: Final[float] = 65.0
F0_FMAX_HZ: Final[float] = 1000.0
F0_FRAME_LENGTH: Final[int] = 2048

#: Share of frames that must carry a pitch before the material is called a
#: voice at all. Unpitched material is refused as unvoiced rather than
#: judged on its spectrum: there is no voice to band-limit.
VOICED_FRACTION_MIN: Final[float] = 0.5

#: Below this fundamental a telephone high-pass eats the voice's own body.
LOW_FUNDAMENTAL_MIN_HZ: Final[float] = 110.0

#: A band at or below these relative levels counts as absent, which makes
#: the spectrum "not voice-like" and refuses the treatment outright.
BODY_PRESENT_MIN_DB: Final[float] = -25.0
AIR_PRESENT_MIN_DB: Final[float] = -35.0

#: Air share below which a telephone filter has nothing to trade away.
HF_RATIO_MIN: Final[float] = 0.03

#: Articulation share at or above which the treatment is a full green light,
#: and at or above which it is still usable with a narrower band.
ARTICULATION_FULL_MIN: Final[float] = 0.30
ARTICULATION_PARTIAL_MIN: Final[float] = 0.18

# ── Negative space calibration ─────────────────────────────────────────

#: Frames are counted as empty when they sit this far below the loudest
#: frame of the same program, which makes the ratio level-independent.
NEGATIVE_SPACE_GATE_DB: Final[float] = -40.0
NEGATIVE_SPACE_FRAME: Final[int] = 1024
NEGATIVE_SPACE_HOP: Final[int] = 512

#: Frame level below which a frame counts as carrying nothing at all. It only
#: exists so a digital-silence frame reads as a very low level instead of
#: ``-inf``, and it is far below any real audio.
NEGATIVE_SPACE_SILENCE_FLOOR: Final[float] = 1e-9

#: Empty share below which a textural bed would mask rather than add.
NEGATIVE_SPACE_MIN_RATIO: Final[float] = 0.15


def _probe_format(path: str | Path) -> tuple[int, float]:
    """Native sample rate and duration, read from the container header.

    Header-only on purpose: ``inspect_input`` needs the input's provenance
    before anything is decoded, and opening a 20-minute file just to ask how
    long it is would make every inspection pay for audio nobody measured.
    """
    info = sf.info(str(path))
    return int(info.samplerate), float(info.frames) / float(info.samplerate)


def _band_limits(band: tuple[float, float], sr: int) -> tuple[float, float] | None:
    """Clamped band edges, or ``None`` when the band cannot exist at this rate.

    A band whose top edge reaches Nyquist has no representable filter. Saying
    so lets the caller report an honest empty band instead of a number
    produced by a filter nobody asked for.
    """
    low, high = band
    high = min(high, (sr / 2.0) - BAND_EDGE_MARGIN_HZ)
    if low <= 0.0 or high <= low:
        return None
    return low, high


def _band_energy(y: np.ndarray, sr: int, band: tuple[float, float]) -> float:
    """Squared-sum energy inside ``band``, or 0.0 when the band cannot exist."""
    limits = _band_limits(band, sr)
    if limits is None:
        return 0.0
    sos = butter(
        BAND_FILTER_ORDER, [limits[0], limits[1]], btype="bandpass", fs=sr, output="sos"
    )
    filtered = sosfilt(sos, y, axis=-1).astype(np.float64)
    return float(np.sum(np.square(filtered)))


def _band_energy_db(y: np.ndarray, sr: int, band: tuple[float, float]) -> float:
    """Energy inside ``band`` relative to the full-band total, floored."""
    total = float(np.sum(np.square(y.astype(np.float64))))
    if total <= 0.0:
        return BAND_FLOOR_DB
    energy = _band_energy(y, sr, band)
    if energy <= 0.0:
        return BAND_FLOOR_DB
    return max(BAND_FLOOR_DB, min(0.0, 10.0 * float(np.log10(energy / total))))


def _load_mono(path: str | Path, sr: int | None) -> tuple[np.ndarray, int]:
    """Decode ``path`` to mono at the analysis rate, bounded in duration.

    Bounded on purpose: every measurement below describes the head of the
    program, at most ``MAX_ANALYSIS_SECONDS`` of it, which keeps a full
    inspection cheap enough to run before every render.
    """
    target = INSPECTOR_SR if sr is None else int(sr)
    y, sample_rate = librosa.load(
        str(path), sr=target, mono=True, duration=MAX_ANALYSIS_SECONDS
    )
    return np.asarray(y, dtype=np.float32), int(sample_rate)


def _beat_accents(
    percussive: np.ndarray, sr: int, beat_times: list[float]
) -> np.ndarray:
    """Level of each beat, from the percussive RMS just after it.

    Deliberately NOT the onset envelope: spectral flux is a difference
    function, so a beat window measured on it also catches the next beat's
    release. Measured on a click track, that fabricates a two-beat accent
    cycle out of a four-beat one.

    Only beats whose whole window lies inside ``percussive`` are reported. A
    window that leaves the signal measures the end of the file, not a quieter
    beat, and librosa 0.11's beat tracker returns a beat close enough to the
    end for that to happen (1.0 does not). Reporting 0.0 there put a phantom
    silence into the accent series and the autocorrelation read it as part of
    the pattern: a clean 4/4 grid scored 0.385 at lag 4 against a 0.40 gate,
    failing the grouping it should have found, only on the librosa that
    production installs.
    """
    window = max(1, int(ACCENT_WINDOW_S * sr))
    accents: list[float] = []
    for beat in beat_times:
        start = int(beat * sr)
        end = start + window
        if start < 0 or end > percussive.size:
            continue
        accents.append(float(np.sqrt(np.mean(np.square(percussive[start:end])))))
    return np.asarray(accents, dtype=np.float64)


def _accent_grouping(
    accents: np.ndarray,
) -> tuple[float, int | None, AccentGrouping, float]:
    """Accent contrast, and the grouping lag that contrast actually supports.

    Contrast is gated FIRST, and for a measured reason: a perfectly flat grid
    still autocorrelates through numerical residue (0.45 at lag 2 with about
    1 dB of beat-level variation), so a correlation-only gate reads a meter
    that is not in the audio.
    """
    peak = float(np.max(accents)) if accents.size else 0.0
    typical = float(np.median(accents)) if accents.size else 0.0
    contrast_db = 0.0
    if typical > 0.0:
        contrast_db = 20.0 * float(np.log10(peak / typical))
    contrast_db = min(60.0, max(0.0, contrast_db))
    if contrast_db < ACCENT_CONTRAST_MIN_DB:
        return contrast_db, None, "unknown", 0.0

    centered = accents - float(np.mean(accents))
    denominator = float(np.sum(np.square(centered)))
    if denominator <= 0.0:
        return contrast_db, None, "unknown", 0.0

    correlations = {
        lag: float(np.dot(centered[:-lag], centered[lag:]) / denominator)
        for lag in GROUPING_LAGS
        if centered.size > lag
    }
    if not correlations:
        return contrast_db, None, "unknown", 0.0

    best_lag = max(correlations, key=lambda lag: correlations[lag])
    best = min(1.0, max(0.0, correlations[best_lag]))
    if best < GROUPING_MIN_CONFIDENCE:
        return contrast_db, None, "unknown", 0.0
    return contrast_db, best_lag, ACCENT_LAG_TO_GROUPING[best_lag], best


def _track_fundamental(y: np.ndarray, sr: int) -> tuple[float | None, float]:
    """Median voiced fundamental, and the share of frames that carried one.

    The median is only reported once ``VOICED_FRACTION_MIN`` of the frames
    carry a pitch. Below that the material is not a voice, and whatever the
    tracker returned is it reaching for a periodicity that is not there.
    """
    chunk = y[: int(sr * MAX_F0_SECONDS)]
    if chunk.size < F0_FRAME_LENGTH:
        return None, 0.0
    with warnings.catch_warnings():
        # pyin casts its NaN pitch bins for every unvoiced frame, and NumPy
        # reports that cast as an invalid value. It IS the expected shape of
        # "no pitch here" on any material with silence in it, and voiced_fraction
        # below is what actually decides whether a pitch can be reported.
        warnings.simplefilter("ignore", RuntimeWarning)
        f0, _, _ = librosa.pyin(
            chunk,
            fmin=F0_FMIN_HZ,
            fmax=F0_FMAX_HZ,
            sr=sr,
            frame_length=F0_FRAME_LENGTH,
        )
    if f0 is None:
        return None, 0.0
    values = np.asarray(f0, dtype=np.float64)
    if values.size == 0:
        return None, 0.0
    voiced = ~np.isnan(values)
    voiced_fraction = float(np.mean(voiced))
    if not voiced.any() or voiced_fraction < VOICED_FRACTION_MIN:
        return None, voiced_fraction
    return float(np.median(values[voiced])), voiced_fraction


def measure_rhythm(
    beat_source: str | Path,
    *,
    sr: int | None = None,
    source: RhythmSource = "drums_stem",
) -> RhythmProfile:
    """Measure the tempo, beat grid and accent grouping of ``beat_source``.

    ``beat_source`` is normally the drum stem — a full mix hides the grid
    behind the arrangement, so callers should pass a stem whenever one
    exists and let ``source`` record that they did.

    Contract for the P1-GREEN body:

    * tempo from the MEDIAN beat interval, with ``trim=False`` so the grid is
      not silently shortened and the BPM is not biased by the frames the
      tracker would drop;
    * ``tempo_confidence`` from the interval coefficient of variation
      against ``IBI_CV_UNUSABLE``, ramped by beat count between
      ``MIN_BEATS_FOR_TEMPO`` and ``FULL_CONFIDENCE_BEATS``;
    * per-beat accent from the RMS of the percussive component in
      ``ACCENT_WINDOW_S`` after the beat — NOT from the onset envelope,
      whose flux values do not reproduce the accent pattern;
    * accent period from the autocorrelation of the mean-subtracted accent
      sequence at ``GROUPING_LAGS``, gated by ``ACCENT_CONTRAST_MIN_DB``;
    * ``subdivision_default`` is ``SUBDIVISION_DEFAULT`` when a grid exists,
      ``SUBDIVISION_NONE`` otherwise.

    Reads the source and writes nothing: the profile is the only output.
    """
    y, sample_rate = _load_mono(beat_source, sr)
    if y.size == 0:
        return RhythmProfile(source=source, subdivision_default=SUBDIVISION_NONE)

    percussive = librosa.effects.hpss(y)[1]
    onset_envelope = librosa.onset.onset_strength(
        y=percussive, sr=sample_rate, hop_length=INSPECTOR_HOP_LENGTH
    )
    _, detected = librosa.beat.beat_track(
        onset_envelope=onset_envelope,
        sr=sample_rate,
        hop_length=INSPECTOR_HOP_LENGTH,
        trim=False,
        units="time",
    )
    beat_times = [float(beat) for beat in np.asarray(detected, dtype=np.float64)]
    if len(beat_times) < 2:
        return RhythmProfile(
            source=source,
            beat_times=beat_times,
            subdivision_default=SUBDIVISION_NONE,
        )

    intervals = np.diff(np.asarray(beat_times, dtype=np.float64))
    mean_interval = float(np.mean(intervals))
    median_interval = float(np.median(intervals))
    tempo = 60.0 / median_interval if median_interval > 0.0 else None
    confidence = 0.0
    if tempo is None or not 0.0 < tempo <= TEMPO_MAX_BPM:
        tempo = None
    else:
        dispersion = (
            float(np.std(intervals)) / mean_interval if mean_interval > 0.0 else 1.0
        )
        ramp = (len(beat_times) - MIN_BEATS_FOR_TEMPO) / (
            FULL_CONFIDENCE_BEATS - MIN_BEATS_FOR_TEMPO
        )
        confidence = min(
            1.0,
            max(0.0, (1.0 - dispersion / IBI_CV_UNUSABLE) * min(1.0, max(0.0, ramp))),
        )

    contrast_db, accent_period, grouping, grouping_confidence = _accent_grouping(
        _beat_accents(percussive, sample_rate, beat_times)
    )

    return RhythmProfile(
        tempo_bpm=tempo,
        tempo_confidence=confidence,
        beat_times=beat_times,
        accent_period_beats=accent_period,
        accent_grouping=grouping,
        grouping_confidence=grouping_confidence,
        accent_contrast_db=contrast_db,
        subdivision_default=(
            SUBDIVISION_DEFAULT if tempo is not None else SUBDIVISION_NONE
        ),
        source=source,
    )


def measure_vocal_viability(
    vocals: str | Path,
    *,
    sr: int | None = None,
    source: VocalSource = "vocals_stem",
) -> VocalViability:
    """Measure whether the voice in ``vocals`` survives a band-limit.

    ``vocals`` is normally the vocals stem. A full mix is accepted but is
    weak evidence, and ``source`` records that so callers can weigh it.

    Contract for the P1-GREEN body:

    * ``band_energies_db`` for every key in ``VOCAL_BAND_ORDER``, relative to
      the full-band total, floored at ``BAND_FLOOR_DB``;
    * ``articulation_ratio`` = energy in 1-4 kHz over energy in
      ``VOICE_CORE_HZ``; ``hf_ratio`` = energy above 6 kHz over total;
    * ``median_f0_hz`` from ``librosa.pyin`` over at most ``MAX_F0_SECONDS``,
      and ``None`` unless ``voiced_fraction`` reaches ``VOICED_FRACTION_MIN``;
    * verdict, first match wins: not enough voiced frames -> ``refuse`` /
      ``unvoiced``; fundamental below ``LOW_FUNDAMENTAL_MIN_HZ`` ->
      ``refuse`` / ``low_fundamental``; body or air band absent ->
      ``refuse`` / ``narrowband``; ``hf_ratio`` below ``HF_RATIO_MIN`` ->
      ``refuse`` / ``insufficient_air``; ``articulation_ratio`` at or above
      ``ARTICULATION_FULL_MIN`` -> ``full``; at or above
      ``ARTICULATION_PARTIAL_MIN`` -> ``partial``; otherwise ``refuse`` /
      ``insufficient_articulation``.

    Reads the source and writes nothing: the profile is the only output.
    """
    y, sample_rate = _load_mono(vocals, sr)
    band_energies = {
        name: _band_energy_db(y, sample_rate, VOCAL_BANDS_HZ[name])
        for name in VOCAL_BAND_ORDER
    }
    if y.size == 0:
        return VocalViability(source=source, band_energies_db=band_energies)

    total_energy = float(np.sum(np.square(y.astype(np.float64))))
    core_energy = _band_energy(y, sample_rate, VOICE_CORE_HZ)
    articulation_energy = _band_energy(
        y, sample_rate, VOCAL_BANDS_HZ["articulation_1k_4k"]
    )
    air_energy = _band_energy(y, sample_rate, VOCAL_BANDS_HZ["air_6k_10k"])
    articulation_ratio = (
        min(1.0, articulation_energy / core_energy) if core_energy > 0.0 else 0.0
    )
    hf_ratio = min(1.0, air_energy / total_energy) if total_energy > 0.0 else 0.0

    median_f0, voiced_fraction = _track_fundamental(y, sample_rate)

    permission: LofiPermission
    reason: LofiRefusalReason
    if median_f0 is None:
        permission, reason = "refuse", "unvoiced"
    elif median_f0 < LOW_FUNDAMENTAL_MIN_HZ:
        permission, reason = "refuse", "low_fundamental"
    elif (
        band_energies["body_100_500"] <= BODY_PRESENT_MIN_DB
        or band_energies["air_6k_10k"] <= AIR_PRESENT_MIN_DB
    ):
        permission, reason = "refuse", "narrowband"
    elif hf_ratio < HF_RATIO_MIN:
        permission, reason = "refuse", "insufficient_air"
    elif articulation_ratio >= ARTICULATION_FULL_MIN:
        permission, reason = "full", "none"
    elif articulation_ratio >= ARTICULATION_PARTIAL_MIN:
        permission, reason = "partial", "none"
    else:
        permission, reason = "refuse", "insufficient_articulation"

    return VocalViability(
        source=source,
        band_energies_db=band_energies,
        articulation_ratio=articulation_ratio,
        hf_ratio=hf_ratio,
        median_f0_hz=median_f0,
        voiced_fraction=voiced_fraction,
        lofi_permission=permission,
        refusal_reason=reason,
    )


def measure_negative_space(
    mix: str | Path,
    *,
    sr: int | None = None,
) -> NegativeSpace:
    """Measure how much of ``mix`` is silence-like.

    Contract for the P1-GREEN body: frame RMS over a ``NEGATIVE_SPACE_FRAME``
    window and a ``NEGATIVE_SPACE_HOP`` hop, normalised to the loudest frame,
    counted against ``NEGATIVE_SPACE_GATE_DB``, and authorized when the
    resulting ratio reaches ``NEGATIVE_SPACE_MIN_RATIO``.

    Measured on the FULL MIX on purpose: the bed sits under the whole
    program, so the question is where the program is empty, not where one
    stem happens to be.

    Reads the source and writes nothing: the profile is the only output.
    """
    y, sample_rate = _load_mono(mix, sr)
    if y.size == 0:
        return NegativeSpace(gate_db=NEGATIVE_SPACE_GATE_DB)

    frame_rms = librosa.feature.rms(
        y=y, frame_length=NEGATIVE_SPACE_FRAME, hop_length=NEGATIVE_SPACE_HOP
    )[0]
    peak = float(np.max(frame_rms)) if frame_rms.size else 0.0
    if peak <= NEGATIVE_SPACE_SILENCE_FLOOR:
        ratio = 1.0
    else:
        levels = 20.0 * np.log10(
            np.maximum(frame_rms, NEGATIVE_SPACE_SILENCE_FLOOR) / peak
        )
        ratio = float(np.mean(levels < NEGATIVE_SPACE_GATE_DB))
    ratio = min(1.0, max(0.0, ratio))

    return NegativeSpace(
        negative_space_ratio=ratio,
        gate_db=NEGATIVE_SPACE_GATE_DB,
        bed_authorized=ratio >= NEGATIVE_SPACE_MIN_RATIO,
    )


def inspect_input(
    input_path: str | Path,
    *,
    stems: Mapping[str, str | Path] | None = None,
    sr: int | None = None,
) -> InspectorProfile:
    """Measure the uploaded material and whatever stems accompany it.

    Stem resolution is the load-bearing part: the rhythm measurement must
    come from the drum stem whenever one exists (a full mix hides the grid),
    and the vocal measurement from the vocals stem whenever one exists.
    Either falls back to ``input_path`` and the profile records which source
    it came from, so a later stage never has to guess how much to trust it.
    """
    source_rate, duration = _probe_format(input_path)
    supplied: Mapping[str, str | Path] = stems or {}
    drums = supplied.get("drums")
    vocals = supplied.get("vocals")

    rhythm = (
        measure_rhythm(drums, sr=sr, source="drums_stem")
        if drums is not None
        else measure_rhythm(input_path, sr=sr, source="input_mix")
    )
    viability = (
        measure_vocal_viability(vocals, sr=sr, source="vocals_stem")
        if vocals is not None
        else measure_vocal_viability(input_path, sr=sr, source="input_mix")
    )

    return InspectorProfile(
        input_sample_rate=source_rate,
        analysis_sample_rate=sr if sr is not None else INSPECTOR_SR,
        duration_seconds=duration,
        rhythm=rhythm,
        vocal_viability=viability,
        negative_space=measure_negative_space(input_path, sr=sr),
    )
