"""Tests for the character stage (P3) — see ``odd/tasks/character-integration.md``.

Every threshold here traces to a measurement recorded in that document, taken with the
probes before the module existed. Two of them exist because a draft of the design got
the physics wrong:

* the wow/flutter compensation does NOT make the residual lag zero — it removes the
  static head spacing and leaves the LFO, because the LFO is the effect. The suite
  asserts the *difference*, which is the thing that has to be exact;
* the naked bed's crest factor is 29.81 dB against a QC ceiling of 18 dB, which is why
  the bed is a bus stage and not a stem stage.
"""

from __future__ import annotations

import numpy as np
import pytest

from audiomind.processing import character as ch
from audiomind.processing.modulation import (
    WowFlutterParams,
    fractional_delay,
    wow_flutter_delays,
)
from audiomind.processing.quality_checks import (
    CREST_OK_MIN_DB,
    MAX_QC_RELAX_DB,
    validate_budget,
)

SR = 44100
SEED = 20261016
WOW_DEPTH_MS = 1.5


def _rms(audio: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(np.asarray(audio, dtype=np.float64)))))


def _lag_samples(a: np.ndarray, b: np.ndarray, max_lag: int) -> int:
    """Lag of the cross-correlation peak of ``b`` relative to ``a``, in samples."""
    x = np.asarray(a, dtype=np.float64).ravel()
    y = np.asarray(b, dtype=np.float64).ravel()
    x = x - x.mean()
    y = y - y.mean()
    lags = np.arange(-max_lag, max_lag + 1)
    scores = []
    for lag in lags:
        if lag >= 0:
            left, right = x[: x.size - lag], y[lag:]
        else:
            left, right = x[-lag:], y[: y.size + lag]
        scores.append(float(np.dot(left, right)))
    return int(lags[int(np.argmax(scores))])


def _hf_band_db(audio: np.ndarray) -> float:
    from scipy.signal import butter, sosfilt

    sos = butter(2, list(ch.HF_BAND_HZ), btype="bandpass", fs=SR, output="sos")
    filtered = sosfilt(sos, np.asarray(audio, dtype=np.float64), axis=-1)
    return float(10.0 * np.log10(np.sum(np.square(filtered)) + 1e-300))


def _lfo_samples(n_padded: int, base: int, depth_ms: float) -> np.ndarray:
    """The LFO trajectory alone, in samples, with the static part subtracted.

    Rebuilt from the module's own public trajectory function so the test states the
    contract (delay = base + LFO) instead of restating the implementation.
    """
    params = WowFlutterParams(depth_ms=depth_ms, base_delay_ms=base * 1000.0 / SR)
    return wow_flutter_delays(n_padded, SR, params)[base:] - base


def _burst(n: int) -> np.ndarray:
    """A short broadband burst inside silence — something with an unambiguous onset."""
    rng = np.random.default_rng(SEED)
    burst = np.zeros((2, n), dtype=np.float64)
    noise = rng.standard_normal(n // 4) * 0.4
    start = n // 4
    burst[0, start : start + noise.size] = noise
    burst[1, start : start + noise.size] = noise * 0.7
    return burst


class TestHeadSpacing:
    def test_is_a_whole_number_of_samples(self) -> None:
        assert ch.head_spacing_samples(WOW_DEPTH_MS, SR) == 67

    def test_never_collapses_to_zero(self) -> None:
        assert ch.head_spacing_samples(0.0, SR) >= 1

    def test_scales_with_the_sample_rate(self) -> None:
        assert ch.head_spacing_samples(WOW_DEPTH_MS, 48000) == 72

    @pytest.mark.parametrize("depth_ms", [0.5, 1.0, 1.5, 2.0])
    @pytest.mark.parametrize("sr", [44100, 48000, 96000])
    def test_always_covers_the_depth_so_no_tap_goes_negative(
        self, depth_ms: float, sr: int
    ) -> None:
        base = ch.head_spacing_samples(depth_ms, sr)
        assert base * 1000.0 / sr >= depth_ms


class TestWowFlutterAlignment:
    """Requirement 2: the static head spacing is removed, sample-exactly."""

    def test_removes_the_static_spacing_and_keeps_the_lfo(self) -> None:
        n = SR
        ramp = np.arange(n, dtype=np.float64) / SR
        out, base = ch.wow_flutter_aligned(ramp, SR, depth_ms=WOW_DEPTH_MS)
        lfo = _lfo_samples(n + base, base, WOW_DEPTH_MS)
        tap = np.arange(n) - lfo
        # Away from the buffer edges the tap is an interior sample read, and a cubic
        # interpolator reproduces a linear function exactly — so this is an identity
        # about the delay trajectory, not an approximation of it.
        interior = (tap >= 2.0) & (tap <= n - 3.0)
        expected = ramp - lfo / SR
        np.testing.assert_allclose(out[interior], expected[interior], atol=1e-9)
        assert np.sum(interior) > 0.99 * n

    def test_the_edge_bleed_is_bounded_by_the_depth(self) -> None:
        n = SR
        ramp = np.arange(n, dtype=np.float64) / SR
        out, base = ch.wow_flutter_aligned(ramp, SR, depth_ms=WOW_DEPTH_MS)
        lfo = _lfo_samples(n + base, base, WOW_DEPTH_MS)
        tap = np.arange(n) - lfo
        boundary = ~((tap >= 2.0) & (tap <= n - 3.0))
        # Only the samples whose tap reaches past the material are affected at all...
        assert int(np.sum(boundary)) <= int(np.ceil(WOW_DEPTH_MS * SR / 1000.0)) + 5
        # ...and there the interpolator blends toward the zero pad instead of reading
        # whatever happened to be in memory.
        assert np.all(np.isfinite(out))
        beyond = (tap <= -3.0) | (tap >= n + 3.0)
        assert np.sum(beyond) > 0
        assert np.all(out[beyond] == 0.0)

    def test_the_head_loses_only_what_the_lfo_asks_for(self) -> None:
        n = SR
        out, base = ch.wow_flutter_aligned(np.ones(n), SR, depth_ms=WOW_DEPTH_MS)
        lfo = _lfo_samples(n + base, base, WOW_DEPTH_MS)
        tap = np.arange(n) - lfo
        interior = (tap >= 2.0) & (tap <= n - 3.0)
        # A constant is reproduced exactly wherever the tap stays inside the material.
        np.testing.assert_allclose(out[interior], 1.0, atol=1e-12)
        lost = int(np.sum(~interior))
        assert lost <= int(np.ceil(WOW_DEPTH_MS * SR / 1000.0)) + 5

    def test_the_static_offset_removed_is_exactly_the_head_spacing(self) -> None:
        n = 2 * SR
        burst = _burst(n)
        base = ch.head_spacing_samples(WOW_DEPTH_MS, SR)
        raw = fractional_delay(
            burst,
            np.full(n, float(base)) + _lfo_samples(n, 0, WOW_DEPTH_MS)[:n],
        )
        aligned, base_used = ch.wow_flutter_aligned(burst, SR, depth_ms=WOW_DEPTH_MS)
        assert base_used == base
        lag_raw = _lag_samples(burst[0], raw[0], 400)
        lag_aligned = _lag_samples(burst[0], aligned[0], 200)
        # Measured 133 and 66: the whole of the static spacing, and nothing more.
        assert abs((lag_raw - lag_aligned) - base) <= 1

    def test_keeps_the_input_length_and_dtype(self) -> None:
        burst = _burst(4096).astype(np.float32)
        out, _ = ch.wow_flutter_aligned(burst, SR, depth_ms=WOW_DEPTH_MS)
        assert out.shape == burst.shape
        assert out.dtype == burst.dtype

    def test_does_not_mutate_its_input(self) -> None:
        burst = _burst(4096)
        before = burst.copy()
        ch.wow_flutter_aligned(burst, SR, depth_ms=WOW_DEPTH_MS)
        np.testing.assert_array_equal(burst, before)


class TestSlapback:
    """The slapback locks to the grid and takes the direct-index path."""

    def test_locks_to_the_beat(self) -> None:
        # (60 / 120) s per beat, a 16th of it, at 44.1 kHz.
        assert ch.slapback_delay_samples(120.0, SR) == 5512

    def test_tracks_the_tempo(self) -> None:
        assert ch.slapback_delay_samples(140.0, SR) < ch.slapback_delay_samples(
            90.0, SR
        )

    @pytest.mark.parametrize("bpm", [None, 0.0, -120.0, float("nan"), float("inf")])
    def test_refuses_a_tempo_it_cannot_use(self, bpm: float | None) -> None:
        assert ch.slapback_delay_samples(bpm, SR) is None

    def test_is_a_bit_exact_shift_and_sum(self) -> None:
        n = 16384
        rng = np.random.default_rng(SEED)
        audio = (rng.standard_normal(n) * 0.25).astype(np.float32)
        out, report = ch.apply_slapback(audio, SR, bpm=120.0)
        delay = int(report["delay_samples"])
        assert delay == 5512
        shifted = np.zeros_like(audio)
        shifted[delay:] = audio[: n - delay]
        expected = audio + shifted * np.float32(ch.SLAPBACK_WET_GAIN)
        # Exact equality is the point: a whole-sample tap never runs the interpolator.
        np.testing.assert_array_equal(out, expected)

    def test_without_a_tempo_it_is_a_reported_no_op(self) -> None:
        rng = np.random.default_rng(SEED)
        audio = rng.standard_normal(2048)
        before = audio.copy()
        out, report = ch.apply_slapback(audio, SR, bpm=None)
        assert report["status"] == "no_tempo"
        assert "delay_samples" not in report
        np.testing.assert_array_equal(out, before)

    def test_the_whole_vocal_stage_reports_a_missing_tempo(self) -> None:
        rng = np.random.default_rng(SEED)
        audio = rng.standard_normal(2048).astype(np.float32)
        out, report = ch.apply_stem_character("vocals", audio, SR, bpm=None)
        stages = {entry["stage"]: entry for entry in report["stages_report"]}
        assert stages["slapback"]["status"] == "no_tempo"
        np.testing.assert_array_equal(out, audio)


class TestChorusCompensation:
    """Requirement 3: the comb loss is measured and paid back."""

    def _signal(self) -> np.ndarray:
        rng = np.random.default_rng(SEED)
        mono = rng.standard_normal(SR) * 0.2
        return np.stack([mono, mono * 0.8])

    def test_the_profile_loss_reproduces_the_p2_disclosure(self) -> None:
        _, report = ch.apply_chorus(self._signal(), SR)
        assert -3.6 < report["comb_loss_db"] < -2.6  # measured -3.095 at mix 0.4
        assert report["mix"] == ch.CHORUS_MIX

    def test_the_make_up_restores_unity_rms(self) -> None:
        signal = self._signal()
        out, report = ch.apply_chorus(signal, SR)
        assert report["gain_compensation_db"] > 0.0
        assert abs(20.0 * np.log10(_rms(out) / _rms(signal))) < 0.01

    def test_the_make_up_is_bounded_and_the_bound_is_reported(self) -> None:
        signal = self._signal()
        out, report = ch.apply_chorus(signal, SR, mix=0.5, max_makeup_db=1.0)
        assert report["comb_loss_db"] < -3.0  # measured -3.440 at mix 0.5
        assert report["gain_compensation_db"] == 1.0
        assert report["gain_compensation_clamped"] is True
        assert _rms(out) < _rms(signal)  # capped, so not fully restored
        assert report["gain_compensation_db"] < -report["comb_loss_db"]

    def test_the_unclamped_case_says_it_was_not_clamped(self) -> None:
        _, report = ch.apply_chorus(self._signal(), SR, mix=0.3)
        assert report["gain_compensation_clamped"] is False


class TestParallelSaturation:
    def _signal(self) -> np.ndarray:
        t = np.arange(SR) / SR
        mono = 0.3 * np.sin(2 * np.pi * 90.0 * t)
        return np.stack([mono, mono * 0.9]).astype(np.float32)

    def test_blends_harmonics_on_top_of_the_dry_bass(self) -> None:
        signal = self._signal()
        out, report = ch.apply_saturation(signal, SR)
        assert report["status"] == "active"
        assert out.shape == signal.shape
        assert not np.array_equal(out, signal)

    def test_matches_the_harmonic_path_level_before_blending(self) -> None:
        # The level match exists so the blend is tonal and not a fader move: with it,
        # blending 35% in must not move the RMS by anything like 35%.
        signal = self._signal()
        out, _ = ch.apply_saturation(signal, SR)
        assert abs(20.0 * np.log10(_rms(out) / _rms(signal))) < 1.0

    def test_a_zero_blend_is_neutral(self) -> None:
        signal = self._signal()
        out, report = ch.apply_saturation(signal, SR, mix=0.0)
        assert report["status"] == "neutral"
        np.testing.assert_array_equal(out, signal)

    def test_does_not_mutate_its_input(self) -> None:
        signal = self._signal()
        before = signal.copy()
        ch.apply_saturation(signal, SR)
        np.testing.assert_array_equal(signal, before)


class TestHighFrequencyDroop:
    """Requirement 4: measured, bounded, and paid back only when it is real."""

    @pytest.mark.parametrize(
        ("droop_db", "expected"),
        [
            (0.0, 0.0),
            (0.4, 0.0),
            (-0.164, 0.0),  # the measured pure-wow/flutter residual
            (-0.5, 0.0),  # exactly at the threshold: not yet a loss worth filtering
            (-0.51, 0.51),
            (-2.0, 2.0),
            (-3.0, 3.0),
            (-9.0, 3.0),  # capped
            (float("nan"), 0.0),
        ],
    )
    def test_the_make_up_decision(self, droop_db: float, expected: float) -> None:
        assert ch.droop_makeup_db(droop_db) == expected

    def test_the_shelf_leaves_the_low_band_alone(self) -> None:
        t = np.arange(SR) / SR
        low = np.sin(2 * np.pi * 100.0 * t)
        out = ch.hf_shelf(low, SR, 3.0)
        assert abs(20.0 * np.log10(_rms(out) / _rms(low))) < 0.05

    def test_the_shelf_lifts_the_high_band(self) -> None:
        rng = np.random.default_rng(SEED)
        noise = rng.standard_normal(SR) * 0.2
        out = ch.hf_shelf(noise, SR, 3.0)
        lift = _hf_band_db(out) - _hf_band_db(noise)
        assert 1.5 < lift < 3.4

    def test_the_configured_chain_reports_a_droop_it_does_not_need_to_pay(self) -> None:
        rng = np.random.default_rng(SEED)
        mono = rng.standard_normal(SR) * 0.2
        signal = np.stack([mono, mono * 0.8])
        _, report = ch.apply_stem_character("other", signal, SR, bpm=120.0)
        # The interpolating stages' share of the chain, after the comb make-up.
        assert report["hf_makeup_db"] >= 0.0
        assert report["hf_makeup_db"] <= ch.HF_DROOP_MAX_COMP_DB
        assert report["hf_shelf_hz"] == ch.HF_SHELF_HZ
        if report["hf_droop_db"] >= -ch.HF_DROOP_MIN_DB:
            assert report["hf_makeup_db"] == 0.0

    def test_a_pure_shift_is_never_asked_to_pay_a_droop(self) -> None:
        rng = np.random.default_rng(SEED)
        audio = (rng.standard_normal(SR) * 0.2).astype(np.float32)
        _, report = ch.apply_stem_character("vocals", audio, SR, bpm=120.0)
        assert report["hf_droop_db"] == 0.0
        assert report["hf_makeup_db"] == 0.0


class TestBed:
    """The bed is the only stochastic stage, and it is gated by a measurement."""

    def _bus(self) -> np.ndarray:
        n = SR
        rng = np.random.default_rng(SEED)
        mono = rng.standard_normal(n) * 0.2
        return np.stack([mono, mono * 0.9]).astype(np.float32)

    def test_unauthorized_is_skipped_and_explains_itself(self) -> None:
        bus = self._bus()
        out, report = ch.apply_bed(bus, SR, seed=SEED, authorized=False)
        assert report["status"] == "skipped"
        assert report["reason"] == "no_negative_space"
        assert "bed_authorized" in report["note"]
        np.testing.assert_array_equal(out, bus)
        assert out is not bus

    def test_authorized_adds_a_bed_under_the_program(self) -> None:
        bus = self._bus()
        out, report = ch.apply_bed(bus, SR, seed=SEED, authorized=True)
        assert report["status"] == "active"
        assert out.shape == bus.shape
        added = out.astype(np.float64) - bus.astype(np.float64)
        # Measured: hiss at -48 dBFS plus crackle at -54 dBFS sum to about -47.0 dBFS.
        assert abs(20.0 * np.log10(_rms(added)) - (-47.0)) < 0.5

    def test_the_bed_stays_near_mono_so_it_cannot_break_the_phase_gate(self) -> None:
        _, report = ch.apply_bed(self._bus(), SR, seed=SEED, authorized=True)
        assert report["spread"] <= 0.3
        n = SR
        bed = ch.stereo_bed(
            ch.pink_hiss(n, SR, seed=SEED, level_dbfs=ch.BED_HISS_LEVEL_DBFS),
            spread=ch.BED_SPREAD,
            seed=SEED,
        )
        correlation = float(np.corrcoef(bed[0], bed[1])[0, 1])
        assert correlation > 0.9  # analytic 0.9231 at spread 0.2

    def test_is_deterministic_for_a_seed(self) -> None:
        bus = self._bus()
        first, _ = ch.apply_bed(bus, SR, seed=SEED, authorized=True)
        second, _ = ch.apply_bed(bus, SR, seed=SEED, authorized=True)
        np.testing.assert_array_equal(first, second)

    def test_an_empty_bus_is_skipped(self) -> None:
        out, report = ch.apply_bed(
            np.zeros((2, 0), dtype=np.float32), SR, seed=SEED, authorized=True
        )
        assert report["reason"] == "empty_bus"
        assert out.shape == (2, 0)


class TestBudget:
    """Requirement 5a: the declared budget is in contract and does real work."""

    def test_a_comfortable_bus_declares_only_the_tone_tolerance(self) -> None:
        budget = ch.character_budget(bus_crest_db=12.0)
        assert "low_level_listen" not in budget
        assert budget["sibilance_5k"] == {"relax_db": ch.TONE_RELAX_DB}

    def test_a_crest_below_the_floor_earns_exactly_the_relax_it_needs(self) -> None:
        budget = ch.character_budget(bus_crest_db=CREST_OK_MIN_DB - 2.0)
        assert budget["low_level_listen"] == {"relax_db": 2.0}

    def test_an_extreme_crest_is_capped_rather_than_declared(self) -> None:
        budget = ch.character_budget(bus_crest_db=0.0)
        assert budget["low_level_listen"] == {"relax_db": MAX_QC_RELAX_DB}
        assert ch.crest_relax_needed_db(0.0) > MAX_QC_RELAX_DB

    @pytest.mark.parametrize("bus_crest_db", [0.0, 2.0, 5.9, 6.0, 12.0, 30.0])
    def test_every_declared_budget_is_in_contract(self, bus_crest_db: float) -> None:
        validate_budget(ch.character_budget(bus_crest_db=bus_crest_db))

    def test_the_provenance_names_the_stages(self) -> None:
        budget = ch.character_budget(bus_crest_db=12.0)
        assert budget["allowed_intentional"] == list(ch.BUDGET_PROVENANCE)

    def test_crest_measurement_matches_the_qc_definition(self) -> None:
        t = np.arange(SR) / SR
        sine = np.sin(2 * np.pi * 100.0 * t)
        assert abs(ch.crest_db(sine) - 3.01) < 0.05
        assert ch.crest_db(np.zeros(1024)) == 0.0
        assert ch.crest_db(np.zeros((2, 0))) == 0.0


class TestComposition:
    def _stem(self, n: int = SR) -> np.ndarray:
        rng = np.random.default_rng(SEED)
        mono = rng.standard_normal(n) * 0.2
        return np.stack([mono, mono * 0.8])

    def test_the_untreated_stem_comes_back_as_a_copy(self) -> None:
        stem = self._stem()
        out, report = ch.apply_stem_character("drums", stem, SR, bpm=120.0)
        assert report["status"] == "untreated"
        assert report["stages"] == []
        np.testing.assert_array_equal(out, stem)
        assert out is not stem

    @pytest.mark.parametrize(
        ("stem", "expected"),
        [
            ("vocals", ["slapback"]),
            ("other", ["wow_flutter", "chorus"]),
            ("bass", ["saturation"]),
            ("drums", []),
        ],
    )
    def test_the_report_names_every_stage_it_ran(
        self, stem: str, expected: list[str]
    ) -> None:
        _, report = ch.apply_stem_character(stem, self._stem(), SR, bpm=120.0)
        assert report["stages"] == expected

    @pytest.mark.parametrize("stem", ["vocals", "other", "bass", "drums"])
    def test_no_stage_mutates_its_input(self, stem: str) -> None:
        source = self._stem()
        before = source.copy()
        ch.apply_stem_character(stem, source, SR, bpm=120.0)
        np.testing.assert_array_equal(source, before)

    def test_the_output_keeps_the_input_length_and_dtype(self) -> None:
        source = self._stem().astype(np.float32)
        out, _ = ch.apply_stem_character("other", source, SR, bpm=120.0)
        assert out.shape == source.shape
        assert out.dtype == source.dtype

    def test_the_compensation_is_reported_per_stem(self) -> None:
        _, report = ch.apply_stem_character("other", self._stem(), SR, bpm=120.0)
        assert report["latency_compensated_samples"] == ch.head_spacing_samples(
            ch.WOW_FLUTTER_DEPTH_MS, SR
        )

    def test_the_profile_is_the_only_known_one(self) -> None:
        assert ch.is_known_profile("commercial_alt_pop")
        assert not ch.is_known_profile("trap")
        assert not ch.is_known_profile(None)
