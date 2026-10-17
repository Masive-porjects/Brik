"""P2 suite for the fractional delay line and its LFO effects.

See ``odd/tasks/texture-modulation-dsp.md`` (specs S6-S12) for every threshold and the
measurement it came from.

Written RED-first, before ``audiomind.processing.modulation`` existed, so RED here is a
collection error rather than an assertion failure. Compensated the same way phase 1
compensated: every expected number was measured on an independent implementation before
the module was written (probes 2-4).

Measured before implementation:
  zero / integer delays        bitwise exact; delay > length -> all zeros
  1 kHz, 3.3 samples           linear -0.0757 dB, cubic -0.0024 dB, phase err 0.0222 deg
  8 kHz, 0.3 samples           linear -5.134 dB, cubic -2.549 dB (documented droop)
  pitch deviation, depth 1 ms  std matches the analytic f*sigma(d') within 0.2 %
  flutter share                trajectory deviation ratio 0.3000 / 0.5000 exactly
  base == depth                minimum delay +0.007 samples
  base < depth                 minimum delay -22.03 samples -> must raise
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import hilbert

from audiomind.processing.modulation import (
    MAX_BASE_DELAY_MS,
    MAX_DEPTH_MS,
    WOW_HZ,
    Chorus,
    ChorusParams,
    WowFlutter,
    WowFlutterParams,
    chorus_is_neutral,
    chorus_pass,
    fractional_delay,
    wow_flutter_delays,
    wow_flutter_is_neutral,
    wow_flutter_pass,
)

SR = 22050
CARRIER_HZ = 200.0
PROBE_F0_HZ = 1000.0
PROBE_DELAY = 3.3
SEED = 20261016


def _tone(freq_hz: float, n_samples: int, sr: int = SR) -> np.ndarray:
    t = np.arange(n_samples, dtype=np.float64) / sr
    return np.sin(2.0 * np.pi * freq_hz * t)


def _instantaneous_frequency(y: np.ndarray, sr: int = SR) -> np.ndarray:
    """Instantaneous frequency via the analytic signal, in Hz per sample."""
    phase = np.unwrap(np.angle(hilbert(y)))
    return np.diff(phase) * sr / (2.0 * np.pi)


def _dominant_lfo_hz(inst_freq: np.ndarray, sr: int = SR) -> float:
    centered = inst_freq - float(np.mean(inst_freq))
    spectrum = np.abs(np.fft.rfft(centered))
    freqs = np.fft.rfftfreq(centered.size, d=1.0 / sr)
    band = (freqs >= 0.05) & (freqs <= 20.0)
    return float(freqs[band][int(np.argmax(spectrum[band]))])


class TestFractionalDelay:
    """S6 and S7: exactness, shape, and the interpolator contrast."""

    def test_zero_delay_is_bit_identical(self):
        rng = np.random.default_rng(SEED)
        signal = rng.standard_normal(4096)
        out = fractional_delay(signal, np.zeros(4096))
        assert np.array_equal(out, signal)

    def test_integer_delay_is_exact_indexing(self):
        rng = np.random.default_rng(SEED)
        signal = rng.standard_normal(4096)
        out = fractional_delay(signal, np.full(4096, 5.0))
        assert np.array_equal(out[5:], signal[:-5])
        assert bool(np.all(out[:5] == 0.0))

    def test_delay_longer_than_the_buffer_reads_as_silence(self):
        signal = np.ones(1024)
        out = fractional_delay(signal, np.full(1024, 4096.0))
        assert bool(np.all(out == 0.0))

    def test_preserves_shape_for_mono_and_stereo(self):
        delays = np.full(64, 1.5)
        assert fractional_delay(np.zeros(64), delays).shape == (64,)
        assert fractional_delay(np.zeros((2, 64)), delays).shape == (2, 64)

    def test_channels_do_not_bleed(self):
        rng = np.random.default_rng(SEED)
        left = rng.standard_normal(2048)
        stereo = np.stack([left, left * 2.0], axis=0)
        out = fractional_delay(stereo, np.full(2048, 3.7))
        assert np.allclose(out[1], 2.0 * out[0], rtol=0.0, atol=1e-12)

    def test_preserves_the_input_dtype(self):
        signal = np.zeros(64, dtype=np.float32)
        signal[:] = np.linspace(-0.5, 0.5, 64)
        out = fractional_delay(signal, np.full(64, 1.5))
        assert out.dtype == np.float32

    def test_rejects_negative_delays(self):
        with pytest.raises(ValueError, match="delay"):
            fractional_delay(np.zeros(16), np.full(16, -1.0))

    def test_rejects_a_delay_length_mismatch(self):
        with pytest.raises(ValueError, match="length"):
            fractional_delay(np.zeros(16), np.full(8, 1.0))

    def test_phase_matches_the_analytic_delay(self):
        n = SR * 2
        sine = _tone(PROBE_F0_HZ, n)
        core = slice(2000, -2000)
        resolution = n - 4000
        bin_index = int(round(PROBE_F0_HZ * resolution / SR))
        reference = np.angle(np.fft.rfft(sine[core]))[bin_index]
        expected = -2.0 * np.pi * PROBE_F0_HZ * PROBE_DELAY / SR

        for cubic in (False, True):
            out = fractional_delay(sine, np.full(n, PROBE_DELAY), cubic=cubic)
            measured = np.angle(np.fft.rfft(out[core]))[bin_index]
            error = np.angle(np.exp(1j * (measured - reference - expected)))
            assert abs(float(np.degrees(error))) < 0.1

    def test_cubic_is_far_more_accurate_than_linear(self):
        """The assertion that would pass for the wrong interpolator is the
        point: linear must lose audibly more than cubic at 1 kHz."""
        n = SR * 2
        sine = _tone(PROBE_F0_HZ, n)
        core = slice(2000, -2000)
        resolution = n - 4000
        bin_index = int(round(PROBE_F0_HZ * resolution / SR))
        reference = float(np.abs(np.fft.rfft(sine[core]))[bin_index])

        loss_db: dict[bool, float] = {}
        for cubic in (False, True):
            out = fractional_delay(sine, np.full(n, PROBE_DELAY), cubic=cubic)
            magnitude = float(np.abs(np.fft.rfft(out[core]))[bin_index])
            loss_db[cubic] = 20.0 * np.log10(magnitude / reference)

        assert loss_db[True] > -0.01
        assert loss_db[False] < -0.05


class TestWowFlutter:
    """S8 to S11: the bypass invariant, pitch modulation, and the tap bound."""

    def test_neutral_predicate_defaults_to_bypass(self):
        assert WowFlutterParams().is_neutral()
        assert wow_flutter_is_neutral(WowFlutterParams())
        assert WowFlutterParams().depth_ms == 0.0

    def test_neutral_at_zero_depth_regardless_of_base_delay(self):
        """A zero-depth delay is still a delay, so the base must not leak.

        If the neutral path honoured ``base_delay_ms`` the stage would shift the
        stem against its neighbours while claiming to be off.
        """
        params = WowFlutterParams(depth_ms=0.0, base_delay_ms=2.0)
        assert params.is_neutral()
        assert wow_flutter_is_neutral(params)
        signal = np.linspace(-0.5, 0.5, 4096)
        out = wow_flutter_pass(signal, SR, params)
        assert np.array_equal(out, signal)

    def test_neutral_returns_a_copy_not_the_input(self):
        signal = np.linspace(-0.5, 0.5, 1024)
        out = wow_flutter_pass(signal, SR, WowFlutterParams())
        assert np.array_equal(out, signal)
        assert out is not signal
        assert out.dtype == signal.dtype

    def test_engaged_at_zero_depth_is_not_neutral(self):
        params = WowFlutterParams(depth_ms=1.0, base_delay_ms=2.0)
        assert not params.is_neutral()
        assert not wow_flutter_is_neutral(params)

    def test_engaged_changes_the_signal(self):
        n = SR * 4
        tone = _tone(CARRIER_HZ, n)
        out = wow_flutter_pass(tone, SR, WowFlutterParams(depth_ms=1.0))
        assert not np.array_equal(out, tone)

    def test_modulates_pitch_by_the_analytic_amount(self):
        """The physical law, not a copy of the trajectory formula.

        A time-varying delay d(n) puts the output's instantaneous frequency at
        f*(1 - d'(n)), so its spread is f*sigma(d'). Both the trajectory and the
        measurement are independent here: the trajectory comes from the module's
        public accessor, the spread comes from the rendered audio.
        """
        n = SR * 20
        params = WowFlutterParams(depth_ms=1.0, base_delay_ms=2.0)
        out = wow_flutter_pass(_tone(CARRIER_HZ, n), SR, params)

        measured = _instantaneous_frequency(out)[3000:-3000]
        delays = wow_flutter_delays(n, SR, params)
        expected = CARRIER_HZ * float(np.std(np.gradient(delays)))

        assert expected > 0.5
        assert float(np.std(measured)) == pytest.approx(expected, rel=0.05)

    def test_modulation_runs_at_the_wow_rate(self):
        n = SR * 20
        params = WowFlutterParams(depth_ms=1.0, base_delay_ms=2.0)
        out = wow_flutter_pass(_tone(CARRIER_HZ, n), SR, params)
        measured = _instantaneous_frequency(out)[3000:-3000]
        assert _dominant_lfo_hz(measured) == pytest.approx(WOW_HZ, abs=0.1)

    def test_pitch_deviation_scales_with_depth(self):
        n = SR * 20
        tone = _tone(CARRIER_HZ, n)
        spreads: list[float] = []
        for depth_ms in (1.0, 2.0):
            params = WowFlutterParams(depth_ms=depth_ms, base_delay_ms=2.0)
            out = wow_flutter_pass(tone, SR, params)
            measured = _instantaneous_frequency(out)[3000:-3000]
            delays = wow_flutter_delays(n, SR, params)
            expected = CARRIER_HZ * float(np.std(np.gradient(delays)))
            assert float(np.std(measured)) == pytest.approx(expected, rel=0.05)
            spreads.append(float(np.std(measured)))
        assert spreads[1] == pytest.approx(2.0 * spreads[0], rel=0.05)

    @pytest.mark.parametrize("share", [0.0, 0.3, 0.5])
    def test_flutter_share_is_a_share_of_pitch_deviation(self, share):
        """Pitch deviation is depth x rate, so a raw depth share would invert
        the intent: at 7.5 Hz against 0.8 Hz, a 0.3 depth share measures a
        deviation ratio of 2.8, not 0.3. This pins the pitch-space reading."""
        n = SR * 40
        params = WowFlutterParams(depth_ms=1.0, base_delay_ms=2.0, flutter_share=share)
        delays = wow_flutter_delays(n, SR, params)
        spectrum = np.abs(np.fft.rfft(delays - float(np.mean(delays))))

        def deviation_at(freq_hz: float) -> float:
            index = int(round(freq_hz * n / SR))
            return float(spectrum[index]) * freq_hz

        wow_deviation = deviation_at(params.wow_hz)
        flutter_deviation = deviation_at(params.flutter_hz)
        assert wow_deviation > 0.0
        if share == 0.0:
            assert flutter_deviation == pytest.approx(0.0, abs=1e-6)
        else:
            ratio = flutter_deviation / wow_deviation
            assert ratio == pytest.approx(share, rel=0.01)

    def test_delay_never_runs_before_the_buffer(self):
        """base == depth is the tightest legal configuration (measured +0.007
        samples), and it must still be accepted rather than rejected."""
        n = SR * 40
        params = WowFlutterParams(depth_ms=MAX_DEPTH_MS, base_delay_ms=MAX_DEPTH_MS)
        delays = wow_flutter_delays(n, SR, params)
        assert float(np.min(delays)) >= 0.0
        base_samples = params.base_delay_ms * SR / 1000.0
        cap_samples = params.depth_ms * SR / 1000.0
        assert float(np.max(np.abs(delays - base_samples))) <= cap_samples

    def test_rejects_a_base_delay_below_the_depth(self):
        """Measured -22.03 samples of tap if this is allowed through."""
        with pytest.raises(ValueError, match="base_delay_ms"):
            WowFlutter(SR, WowFlutterParams(depth_ms=2.0, base_delay_ms=1.0))

    def test_rejects_depth_above_the_ceiling(self):
        limit = MAX_DEPTH_MS + 0.5
        with pytest.raises(ValueError, match="depth_ms"):
            WowFlutter(SR, WowFlutterParams(depth_ms=limit, base_delay_ms=limit))

    def test_rejects_a_base_delay_above_the_ceiling(self):
        """Neutral or not, an unbounded delay line is a resource risk."""
        with pytest.raises(ValueError, match="base_delay_ms"):
            WowFlutter(
                SR,
                WowFlutterParams(depth_ms=0.0, base_delay_ms=MAX_BASE_DELAY_MS + 1.0),
            )

    def test_rejects_non_positive_lfo_rates(self):
        """``wow_flutter_delays`` divides by ``flutter_hz``; zero must raise,
        not divide."""
        with pytest.raises(ValueError, match="flutter_hz"):
            WowFlutter(
                SR, WowFlutterParams(depth_ms=1.0, base_delay_ms=2.0, flutter_hz=0.0)
            )
        with pytest.raises(ValueError, match="wow_hz"):
            WowFlutter(
                SR, WowFlutterParams(depth_ms=1.0, base_delay_ms=2.0, wow_hz=0.0)
            )


class TestChorus:
    """S8 and S12: the bypass invariant and the engaged shape."""

    def test_depth_zero_is_bit_identical_even_with_mix(self):
        """A static delay summed with dry is a comb filter, not a chorus."""
        n = SR * 4
        rng = np.random.default_rng(SEED)
        signal = rng.standard_normal(n) * 0.1
        params = ChorusParams(depth_ms=0.0, mix=0.5)
        assert params.is_neutral()
        assert np.array_equal(chorus_pass(signal, SR, params), signal)

    def test_mix_zero_is_bit_identical_even_with_depth(self):
        n = SR * 4
        rng = np.random.default_rng(SEED)
        signal = rng.standard_normal(n) * 0.1
        params = ChorusParams(depth_ms=3.0, mix=0.0)
        assert params.is_neutral()
        assert chorus_is_neutral(params)
        assert np.array_equal(chorus_pass(signal, SR, params), signal)

    def test_engaged_differs_and_stays_bounded(self):
        n = SR * 4
        rng = np.random.default_rng(SEED)
        signal = rng.standard_normal(n) * 0.1
        params = ChorusParams(depth_ms=3.0, mix=0.5)
        assert not chorus_is_neutral(params)
        out = chorus_pass(signal, SR, params)
        assert not np.array_equal(out, signal)
        assert float(np.max(np.abs(out))) <= 1.0

    def test_rejects_mix_out_of_range(self):
        with pytest.raises(ValueError, match="mix"):
            Chorus(SR, ChorusParams(depth_ms=3.0, mix=1.5))

    def test_rejects_a_base_delay_below_the_depth(self):
        with pytest.raises(ValueError, match="base_delay_ms"):
            Chorus(SR, ChorusParams(depth_ms=20.0, base_delay_ms=15.0))

    def test_preserves_the_input_dtype_when_engaged(self):
        signal = np.linspace(-0.5, 0.5, 4096).astype(np.float32)
        params = WowFlutterParams(depth_ms=1.0, base_delay_ms=2.0)
        assert wow_flutter_pass(signal, SR, params).dtype == np.float32
        assert chorus_pass(signal, SR, ChorusParams(depth_ms=3.0, mix=0.5)).dtype == (
            np.float32
        )
