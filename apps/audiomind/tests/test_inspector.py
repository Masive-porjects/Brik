"""P1 suite for the content-aware inspector.

Written RED-first. It was authored against ``audiomind.analysis.inspector``
while its three measurement bodies were still staged placeholders, and every
test failed on a POSITIVE assertion about a value that had not been measured
yet — never on an import error, an attribute error or a missing key. That is
what made the RED step worth anything: the failures proved the suite exercised
real behaviour rather than the absence of a module.

Its expectations come from an independent computation, not from running the
implementation and copying the answer: every number below was measured during
recon on the same fixtures, read back from PCM_16 WAV, before the bodies
existed. Where a threshold decides an outcome the assertion is written against
the module's named calibration constant, so tuning a threshold means editing
the constant and never the test.

Fixture corpus, and the property each one exists to carry (all of them
measured during recon, not assumed):

* ``click_4_4`` — 120 BPM click track, loud beat every 4 beats. Measures
  120.19 BPM with 16 beats, accent autocorrelation 0.73 at lag 4.
* ``click_waltz`` — same track with the loud beat every 3 beats: 0.81 at lag 3.
* ``click_flat`` — every click at the same level: accent contrast 1.26 dB,
  below the 3.0 dB gate, so no grouping may be claimed.
* ``tone_1k`` — 1 kHz sine. Energy sits in the articulation band and the
  body band reads -30.1 dB (leakage only), so the spectrum is not a voice.
* ``voice_150`` / ``voice_90`` — harmonic stack with a 1-4 kHz formant lift
  and 6-10 kHz breath air, at a mid fundamental and at a fundamental a
  telephone high-pass would eat.
* ``noise_flat`` — unpitched broadband noise: 29% voiced frames, 0.36 air
  share.
* ``gap_2s`` — 1 s of program then 2 s of digital silence: negative-space
  ratio 0.654.
* ``sparse_gap`` — 10 s of program with a 0.8 s hole: ratio ~0.079, which
  must stay BELOW the threshold, pinning the boundary from underneath.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import butter, sosfilt

from audiomind.analysis import inspector
from audiomind.analysis.inspector import (
    ACCENT_CONTRAST_MIN_DB,
    ARTICULATION_FULL_MIN,
    BAND_FLOOR_DB,
    BODY_PRESENT_MIN_DB,
    GROUPING_MIN_CONFIDENCE,
    HF_RATIO_MIN,
    INSPECTOR_SR,
    LOW_FUNDAMENTAL_MIN_HZ,
    NEGATIVE_SPACE_MIN_RATIO,
    VOICED_FRACTION_MIN,
)

# NumPy reports "invalid value encountered in cast" from inside numba's ufunc
# dispatch while librosa's JIT kernels warm up on material that is mostly
# silence. It is upstream, it is not deterministic across runs (it surfaces in
# some processes and not others, and cannot be reproduced by calling hpss,
# onset_strength, beat_track or pyin directly under an error filter), and it
# changes none of the measurements. Filtered here rather than in the suite
# config so the blast radius stays inside this module.
pytestmark = pytest.mark.filterwarnings(
    "ignore:invalid value encountered in cast:RuntimeWarning"
)

# ── Fixture builders ───────────────────────────────────────────────────


def _click_track(
    *,
    bpm: float = 120.0,
    seconds: float = 8.0,
    accent_period: int = 4,
    sr: int = INSPECTOR_SR,
) -> np.ndarray:
    """A click track whose loud beat repeats every ``accent_period`` beats.

    The click lasts 80 ms with a flat top because of the flat-grid test, not
    because of the meter itself: a 5 ms click is only measured through the
    smear left by HPSS, and on librosa 0.11 that residue reached 2.08 dB of
    false accent contrast on a grid with none (the refusal gate is 3.0 dB, so
    the invariant had about 1 dB of headroom). The flat burst measures 0.04 dB
    on the same grid. Both widths read the 4/4 cycle once ``_beat_accents``
    stops inventing a zero for the beat past the end of the signal.
    """
    y = np.zeros(int(sr * seconds), dtype=np.float32)
    step = 60.0 / bpm
    rng = np.random.default_rng(7)
    click = rng.standard_normal(int(0.080 * sr)).astype(np.float32)
    ramp = max(1, int(0.002 * sr))
    click[:ramp] *= np.linspace(0.0, 1.0, ramp).astype(np.float32)
    click[-ramp:] *= np.linspace(1.0, 0.0, ramp).astype(np.float32)
    for index in range(int(seconds / step)):
        start = int(round(index * step * sr))
        segment = click * (1.0 if index % accent_period == 0 else 0.30)
        y[start : start + len(segment)] += segment[: max(0, len(y) - start)]
    return y


def _voice_like(
    *,
    f0: float = 150.0,
    seconds: float = 3.0,
    sr: int = INSPECTOR_SR,
    seed: int = 3,
) -> np.ndarray:
    """A harmonic stack with a 1-4 kHz formant lift and breath air.

    The formant is what makes this voice-like rather than merely tonal: a
    plain 1/k harmonic stack is far too dark, and would (correctly) be
    refused for having no articulation to spare.
    """
    rng = np.random.default_rng(seed)
    n = int(sr * seconds)
    t = np.linspace(0.0, seconds, n, endpoint=False)
    y = np.zeros(n)
    k = 1
    while f0 * k < 9000.0:
        freq = f0 * k
        formant = np.exp(-((freq - 2200.0) ** 2) / (2.0 * 1200.0**2))
        y += (1.0 / k) * (0.20 + 2.5 * formant) * np.sin(2.0 * np.pi * freq * t)
        k += 1
    y *= 0.30
    y += 0.03 * rng.standard_normal(n)
    hiss = sosfilt(
        butter(2, [6000.0, 10000.0], btype="bandpass", fs=sr, output="sos"),
        rng.standard_normal(n),
    )
    y += 0.10 * hiss
    return (y / np.max(np.abs(y)) * 0.6).astype(np.float32)


def _write(tmp_path: Path, name: str, y: np.ndarray, sr: int = INSPECTOR_SR) -> Path:
    path = tmp_path / f"{name}.wav"
    sf.write(str(path), y, sr, subtype="PCM_16")
    return path


def _noise(seconds: float, *, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (0.5 * rng.standard_normal(int(INSPECTOR_SR * seconds))).astype(np.float32)


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def click_4_4(tmp_path: Path) -> Path:
    return _write(tmp_path, "click_4_4", _click_track(accent_period=4))


@pytest.fixture
def click_waltz(tmp_path: Path) -> Path:
    return _write(tmp_path, "click_waltz", _click_track(accent_period=3))


@pytest.fixture
def click_flat(tmp_path: Path) -> Path:
    return _write(tmp_path, "click_flat", _click_track(accent_period=1))


@pytest.fixture
def tone_1k(tmp_path: Path) -> Path:
    t = np.linspace(0.0, 2.0, int(INSPECTOR_SR * 2.0), endpoint=False)
    y = (0.5 * np.sin(2.0 * np.pi * 1000.0 * t)).astype(np.float32)
    return _write(tmp_path, "tone_1k", y)


@pytest.fixture
def voice_150(tmp_path: Path) -> Path:
    return _write(tmp_path, "voice_150", _voice_like(f0=150.0))


@pytest.fixture
def voice_90(tmp_path: Path) -> Path:
    return _write(tmp_path, "voice_90", _voice_like(f0=90.0))


@pytest.fixture
def noise_flat(tmp_path: Path) -> Path:
    return _write(tmp_path, "noise_flat", _noise(3.0, seed=12))


@pytest.fixture
def gap_2s(tmp_path: Path) -> Path:
    silence = np.zeros(int(INSPECTOR_SR * 2.0), dtype=np.float32)
    return _write(tmp_path, "gap_2s", np.concatenate([_noise(1.0, seed=11), silence]))


@pytest.fixture
def sparse_gap(tmp_path: Path) -> Path:
    program = _noise(5.0, seed=13)
    silence = np.zeros(int(INSPECTOR_SR * 0.8), dtype=np.float32)
    return _write(tmp_path, "sparse_gap", np.concatenate([program, silence, program]))


# ── Rhythm ─────────────────────────────────────────────────────────────


def test_rhythm_tracks_a_known_click_grid(click_4_4: Path) -> None:
    profile = inspector.measure_rhythm(click_4_4)

    assert profile.source == "drums_stem"
    assert profile.tempo_bpm == pytest.approx(120.0, abs=1.5)
    assert profile.tempo_confidence > 0.5
    assert len(profile.beat_times) >= 12
    assert profile.beat_times == sorted(profile.beat_times)
    assert profile.subdivision_default == inspector.SUBDIVISION_DEFAULT


def test_rhythm_grouping_reads_a_four_beat_accent_cycle(click_4_4: Path) -> None:
    profile = inspector.measure_rhythm(click_4_4)

    assert profile.accent_period_beats == 4
    assert profile.accent_grouping == "4/4"
    assert profile.grouping_confidence >= GROUPING_MIN_CONFIDENCE
    assert profile.accent_contrast_db > ACCENT_CONTRAST_MIN_DB


def test_rhythm_grouping_reads_a_three_beat_accent_cycle(click_waltz: Path) -> None:
    profile = inspector.measure_rhythm(click_waltz)

    assert profile.accent_period_beats == 3
    assert profile.accent_grouping == "3/4"


def test_rhythm_refuses_to_group_a_flat_grid(click_flat: Path) -> None:
    profile = inspector.measure_rhythm(click_flat)

    assert len(profile.beat_times) >= 12, "the grid itself must still be found"
    assert profile.accent_contrast_db < ACCENT_CONTRAST_MIN_DB
    assert profile.accent_period_beats is None
    assert profile.accent_grouping == "unknown"


def test_a_beat_whose_window_leaves_the_signal_is_not_measured_as_a_level() -> None:
    """A trailing beat must not become a phantom accent.

    librosa 0.11's ``beat_track`` can return a beat close enough to the end of
    the signal that its ``ACCENT_WINDOW_S`` measurement window leaves it
    (librosa 1.0 does not, which is why this reached production and CI -- both
    on Python 3.11 -- while a 3.12 checkout stayed green). Recording 0.0 for
    that beat conflates "not measured" with "silent", and the phantom silence
    then fights the real period inside the autocorrelation: a clean 4/4 grid
    scored 0.385 at lag 4 against a 0.40 gate only because of it.
    """
    sr = INSPECTOR_SR
    percussive = np.full(sr, 0.5, dtype=np.float32)

    accents = inspector._beat_accents(percussive, sr, [0.10, 0.50, 0.98])

    assert len(accents) == 2, "a window that leaves the signal measures nothing"
    assert np.allclose(accents, 0.5, atol=1e-4)


def test_rhythm_reports_a_thin_grid_on_unpitched_material(noise_flat: Path) -> None:
    profile = inspector.measure_rhythm(noise_flat)

    assert len(profile.beat_times) > 0
    assert profile.tempo_confidence < 0.5
    assert profile.accent_grouping == "unknown"


# ── Vocal viability ────────────────────────────────────────────────────


def test_vocal_viability_grants_full_on_a_voice_with_body_and_air(
    voice_150: Path,
) -> None:
    profile = inspector.measure_vocal_viability(voice_150)

    assert profile.source == "vocals_stem"
    assert profile.median_f0_hz == pytest.approx(150.0, abs=20.0)
    assert profile.voiced_fraction >= VOICED_FRACTION_MIN
    assert profile.articulation_ratio >= ARTICULATION_FULL_MIN
    assert profile.hf_ratio >= HF_RATIO_MIN
    assert profile.lofi_permission == "full"
    assert profile.refusal_reason == "none"


def test_vocal_viability_refuses_a_pure_tone_as_narrowband(tone_1k: Path) -> None:
    profile = inspector.measure_vocal_viability(tone_1k)

    assert profile.voiced_fraction >= VOICED_FRACTION_MIN
    assert profile.band_energies_db["articulation_1k_4k"] > -10.0
    assert profile.band_energies_db["body_100_500"] <= BODY_PRESENT_MIN_DB
    assert profile.band_energies_db["air_6k_10k"] <= BAND_FLOOR_DB + 1.0
    assert profile.hf_ratio < HF_RATIO_MIN
    assert profile.lofi_permission == "refuse"
    assert profile.refusal_reason == "narrowband"


def test_vocal_viability_refuses_a_fundamental_the_band_limit_would_eat(
    voice_90: Path,
) -> None:
    profile = inspector.measure_vocal_viability(voice_90)

    assert profile.median_f0_hz is not None
    assert profile.median_f0_hz < LOW_FUNDAMENTAL_MIN_HZ
    assert profile.lofi_permission == "refuse"
    assert profile.refusal_reason == "low_fundamental"


def test_vocal_viability_refuses_unpitched_material_as_unvoiced(
    noise_flat: Path,
) -> None:
    profile = inspector.measure_vocal_viability(noise_flat)

    assert profile.voiced_fraction < VOICED_FRACTION_MIN
    assert profile.median_f0_hz is None
    assert profile.hf_ratio > 0.2
    assert profile.lofi_permission == "refuse"
    assert profile.refusal_reason == "unvoiced"


def test_band_energies_cover_every_canonical_band(voice_150: Path) -> None:
    profile = inspector.measure_vocal_viability(voice_150)

    assert tuple(profile.band_energies_db) == inspector.VOCAL_BAND_ORDER
    assert profile.band_energies_db["body_100_500"] > BODY_PRESENT_MIN_DB
    assert profile.band_energies_db["air_6k_10k"] > inspector.AIR_PRESENT_MIN_DB


# ── Negative space ─────────────────────────────────────────────────────


def test_negative_space_authorizes_a_bed_when_the_program_has_a_gap(
    gap_2s: Path,
) -> None:
    profile = inspector.measure_negative_space(gap_2s)

    assert profile.negative_space_ratio > 0.5
    assert profile.negative_space_ratio >= NEGATIVE_SPACE_MIN_RATIO
    assert profile.gate_db == inspector.NEGATIVE_SPACE_GATE_DB
    assert profile.bed_authorized is True


def test_negative_space_denies_a_bed_when_the_gap_is_below_threshold(
    sparse_gap: Path,
) -> None:
    profile = inspector.measure_negative_space(sparse_gap)

    assert profile.negative_space_ratio > 0.02, "there is a real hole in there"
    assert profile.negative_space_ratio < NEGATIVE_SPACE_MIN_RATIO
    assert profile.bed_authorized is False


# ── inspect_input ──────────────────────────────────────────────────────


def test_inspect_input_measures_rhythm_from_the_drums_stem(click_4_4: Path) -> None:
    profile = inspector.inspect_input(click_4_4, stems={"drums": click_4_4})

    assert profile.rhythm.source == "drums_stem"
    assert profile.rhythm.tempo_bpm == pytest.approx(120.0, abs=1.5)
    assert profile.input_sample_rate == INSPECTOR_SR
    assert profile.analysis_sample_rate == INSPECTOR_SR
    assert profile.duration_seconds == pytest.approx(8.0, abs=0.05)


def test_inspect_input_falls_back_to_the_mix_without_stems(click_4_4: Path) -> None:
    profile = inspector.inspect_input(click_4_4)

    assert profile.rhythm.source == "input_mix"
    assert profile.vocal_viability.source == "input_mix"
    assert profile.rhythm.tempo_bpm == pytest.approx(120.0, abs=1.5)


def test_inspect_input_measures_viability_from_the_vocals_stem(
    click_4_4: Path, voice_150: Path
) -> None:
    profile = inspector.inspect_input(
        click_4_4, stems={"drums": click_4_4, "vocals": voice_150}
    )

    assert profile.vocal_viability.source == "vocals_stem"
    assert profile.vocal_viability.median_f0_hz == pytest.approx(150.0, abs=20.0)
    assert profile.vocal_viability.lofi_permission == "full"
