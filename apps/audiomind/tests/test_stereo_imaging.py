"""Tests for the per-band stereo imaging stage (Sprint 9).

These tests import ONLY numpy/scipy and ``audiomind.processing.stereo_imaging``
(plus the shared multiband crossover) — NEVER ``engine``/``pedalboard`` — so
they run on machines where Smart App Control blocks the pedalboard binary.

Acceptance mapping (roadmap): correlation >0.9 below, controlled width above;
mono downmix null test; constant-power widening preserves perceived energy.
"""

import numpy as np
import pytest
from scipy.signal import butter, sosfilt

from audiomind.processing.multiband import LinkwitzRiley4
from audiomind.processing.stereo_imaging import (
    StereoImaging,
    StereoImagingParams,
    apply_stereo_imaging,
)

SR = 44100


def _sine(freq: float = 440.0, dur_s: float = 1.0, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(SR * dur_s)) / SR
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def _stereo(left: np.ndarray, right: np.ndarray | None = None) -> np.ndarray:
    right = left if right is None else right
    return np.stack([left, right]).astype(np.float64)


def _rng(seed: int = 42) -> np.random.Generator:
    return np.random.default_rng(seed)


def _corr(audio: np.ndarray) -> float:
    left, right = audio[0], audio[1]
    return float(
        np.dot(left, right)
        / (np.linalg.norm(left) * np.linalg.norm(right) + 1e-10)
    )


def _band_rms(stereo: np.ndarray, sr: int, low: float, high: float) -> np.ndarray:
    """RMS of the mid/high/low band energy for each channel."""
    x = stereo
    # Band-pass per channel using the LR4 band bank edges.
    bands = LinkwitzRiley4(sr, 150.0, 3000.0).split(x)
    return np.array([np.sqrt(np.mean(b**2)) for b in bands])


class TestNullTest:
    def test_neutral_defaults_are_bit_exact(self):
        x = _stereo(_sine(220.0), _sine(220.0, amp=0.3))
        y = apply_stereo_imaging(x, SR)
        assert np.array_equal(x, y)

    def test_neutral_random_signal_bit_exact(self):
        rng = _rng()
        x = rng.standard_normal((2, SR // 4)).astype(np.float64) * 0.3
        y = apply_stereo_imaging(x, SR)
        assert np.array_equal(x, y)

    def test_neutral_bypass_when_all_widths_one_and_mono_off(self):
        x = _stereo(_sine(100.0), _sine(100.0, amp=0.9))
        p = StereoImagingParams(
            crossover_low_hz=150.0,
            crossover_high_hz=3000.0,
            low_width=1.0,
            mid_width=1.0,
            high_width=1.0,
            mono_below_hz=0.0,
        )
        y = StereoImaging(SR, p).process(x)
        assert np.array_equal(x, y)

    def test_neutral_diagnostics(self):
        x = _stereo(_sine())
        _, diag = StereoImaging(SR).process_with_diagnostics(x)
        assert diag["neutral"] is True
        assert diag["correlation_in"] == pytest.approx(1.0, abs=1e-6)
        assert diag["correlation_out"] == pytest.approx(1.0, abs=1e-6)


class TestConstantPowerWidth:
    def test_width_one_band_is_identity(self):
        # w=1.0 must be EXACT: sqrt(2/2)=1, sqrt(2/2)=1.
        mid_gain, side_gain = _constant_power_gains_import()
        assert mid_gain == 1.0
        assert side_gain == 1.0

    def test_widening_increases_side_energy_in_band(self):
        # Stereo signal with correlated mid + decorrelated side: widening the
        # low band must raise low-band side energy relative to mid.
        rng = _rng(1)
        t = np.arange(SR // 2) / SR
        mid = 0.4 * np.sin(2 * np.pi * 80.0 * t)
        side = 0.2 * rng.standard_normal(len(t))
        left = (mid + side) / np.sqrt(2.0)
        right = (mid - side) / np.sqrt(2.0)
        x = np.stack([left, right])

        p = StereoImagingParams(low_width=1.6, mid_width=1.0, high_width=1.0)
        y = StereoImaging(SR, p).process(x)

        # Measure low-band side RMS in input vs output.
        def low_side_rms(a: np.ndarray) -> float:
            bands = LinkwitzRiley4(SR, 150.0, 3000.0).split(a)
            l_b, r_b = bands[0][0], bands[0][1]
            s = (l_b - r_b) / np.sqrt(2.0)
            return float(np.sqrt(np.mean(s**2)))

        # Width 1.6 → side gain sqrt(2*1.6/2.6)=1.109; LR4 ripple ~0.3%.
        assert low_side_rms(y) > low_side_rms(x) * 1.05

    def test_narrowing_decreases_side_energy_in_band(self):
        rng = _rng(2)
        t = np.arange(SR // 2) / SR
        mid = 0.4 * np.sin(2 * np.pi * 80.0 * t)
        side = 0.2 * rng.standard_normal(len(t))
        left = (mid + side) / np.sqrt(2.0)
        right = (mid - side) / np.sqrt(2.0)
        x = np.stack([left, right])

        p = StereoImagingParams(low_width=0.5, mid_width=1.0, high_width=1.0)
        y = StereoImaging(SR, p).process(x)

        def low_side_rms(a: np.ndarray) -> float:
            bands = LinkwitzRiley4(SR, 150.0, 3000.0).split(a)
            s = (bands[0][0] - bands[0][1]) / np.sqrt(2.0)
            return float(np.sqrt(np.mean(s**2)))

        # Width 0.5 → side gain sqrt(2*0.5/1.5)=0.816; LR4 ripple ~0.3%.
        assert low_side_rms(y) < low_side_rms(x) * 0.85

    def test_widening_preserves_mid_energy_no_center_hole(self):
        # Constant-power property: with equal mid/side power the TOTAL
        # M/S power is preserved when widening. For a pure-mid signal the
        # mid is reduced by sqrt(2/(1+w)) — gentler than the legacy
        # 2/(1+w) linear cut, which is the "no center hole" claim.
        #
        # NOTE: widening a decorrelated signal (equal mid/side power) lowers
        # the output correlation; the correlation safety must NOT trigger
        # here, otherwise it would absorb the widened side and break the
        # energy measurement. w=1.2 keeps corr_out = (0.909-1.091)/2 =
        # -0.0909 just above the -0.1 safety floor, so the raw
        # constant-power gains are measurable end to end.
        t = np.arange(SR // 2) / SR
        mid = 0.4 * np.sin(2 * np.pi * 1000.0 * t)  # well inside the mid band
        side = 0.4 * np.sin(2 * np.pi * 1000.0 * t + 1.3)  # equal-power side
        left = (mid + side) / np.sqrt(2.0)
        right = (mid - side) / np.sqrt(2.0)
        x = np.stack([left, right])

        p = StereoImagingParams(mid_width=1.2, low_width=1.0, high_width=1.0)
        y = StereoImaging(SR, p).process(x)

        def ms_power(a: np.ndarray) -> float:
            m = (a[0] + a[1]) / np.sqrt(2.0)
            s = (a[0] - a[1]) / np.sqrt(2.0)
            return float(np.sqrt(np.mean(m**2) + np.mean(s**2)))

        # Total M/S power preserved (constant-power), not collapsed.
        assert ms_power(y) == pytest.approx(ms_power(x), rel=0.05)

        # The mid is cut by sqrt(2/(1+w)) = sqrt(2/2.2) ≈ 0.953, NOT by the
        # legacy linear 2/(1+w) ≈ 0.909 — that difference is the
        # "no center hole" improvement.
        mid_out = np.sqrt(np.mean(((y[0] + y[1]) / np.sqrt(2.0)) ** 2))
        mid_in = np.sqrt(np.mean(((x[0] + x[1]) / np.sqrt(2.0)) ** 2))
        assert mid_out / mid_in == pytest.approx(np.sqrt(2.0 / 2.2), rel=0.05)

    def test_pure_mid_widening_uses_sqrt_not_linear_cut(self):
        # A pure-mid signal has no side to widen: the mid must be cut by
        # sqrt(2/(1+w)) (0.845 at w=1.8), NOT by the legacy linear
        # 2/(1+w) (0.714). This is the "no center hole" improvement.
        t = np.arange(SR // 2) / SR
        left = 0.5 * np.sin(2 * np.pi * 200.0 * t)
        right = left.copy()
        x = np.stack([left, right])

        p = StereoImagingParams(mid_width=1.8, low_width=1.8, high_width=1.8)
        y = StereoImaging(SR, p).process(x)

        mid_in = np.sqrt(np.mean(((x[0] + x[1]) / np.sqrt(2.0)) ** 2))
        mid_out = np.sqrt(np.mean(((y[0] + y[1]) / np.sqrt(2.0)) ** 2))
        factor = mid_out / mid_in
        assert factor == pytest.approx(np.sqrt(2.0 / 2.8), rel=0.05)
        assert factor > (2.0 / 2.8)  # gentler than the legacy cut

    def test_width_zero_collapses_band_to_mono(self):
        t = np.arange(SR // 2) / SR
        left = 0.4 * np.sin(2 * np.pi * 80.0 * t)
        right = 0.1 * np.sin(2 * np.pi * 80.0 * t)
        x = np.stack([left, right])

        p = StereoImagingParams(low_width=0.0, mid_width=1.0, high_width=1.0)
        y = StereoImaging(SR, p).process(x)

        def low_side_rms(a: np.ndarray) -> float:
            bands = LinkwitzRiley4(SR, 150.0, 3000.0).split(a)
            s = (bands[0][0] - bands[0][1]) / np.sqrt(2.0)
            return float(np.sqrt(np.mean(s**2)))

        # Width 0 removes ALL side energy from the low band; only LR4 ripple
        # (~0.3%) remains, so the drop must be at least 90%.
        assert low_side_rms(y) < low_side_rms(x) * 0.1


class TestMonoLows:
    def test_mono_below_collapses_lows_in_mono_downmix(self):
        # Mono downmix null test: forcing lows to mono must NOT change the
        # mono downmix at all (mono_low + stereo_highs reconstruction is
        # exactly the input downmix). This is the phase-cancellation safety.
        rng = _rng(3)
        t = np.arange(SR // 2) / SR
        low = 0.5 * np.sin(2 * np.pi * 60.0 * t)
        left = low + 0.2 * rng.standard_normal(len(t))
        right = low + 0.2 * rng.standard_normal(len(t))
        x = np.stack([left, right])

        p = StereoImagingParams(mono_below_hz=120.0)
        y = StereoImaging(SR, p).process(x)

        mono_in = (x[0] + x[1]) / 2.0
        mono_out = (y[0] + y[1]) / 2.0
        assert np.allclose(mono_out, mono_in, atol=1e-12)  # null: bit-identical downmix

    def test_mono_below_improves_low_band_correlation(self):
        # Forcing lows to mono must push the sub-cutoff region toward mono:
        # its correlation must be HIGHER than the input's (or stay above 0.9
        # when the input is already healthy). NOTE: with the legacy-compatible
        # reconstruction the low region does NOT become L == R — the 4th-order
        # transition band retains side content — so the assertion is about
        # correlation improvement, not an impossible equality.
        rng = _rng(3)
        t = np.arange(SR // 2) / SR
        low_mid = 0.5 * np.sin(2 * np.pi * 60.0 * t)      # correlated low
        anti = 0.4 * np.sin(2 * np.pi * 40.0 * t)          # anti-phase below cutoff
        left = low_mid + anti + 0.2 * rng.standard_normal(len(t))
        right = low_mid - anti + 0.2 * rng.standard_normal(len(t))
        x = np.stack([left, right])

        p = StereoImagingParams(mono_below_hz=120.0)
        y = StereoImaging(SR, p).process(x)

        sos = butter(4, 120.0 / (SR / 2.0), btype="low", output="sos")

        def low_corr(a: np.ndarray) -> float:
            left = sosfilt(sos, a[0])
            right = sosfilt(sos, a[1])
            return float(
                np.dot(left, right)
                / (np.linalg.norm(left) * np.linalg.norm(right) + 1e-10)
            )

        # The input low region is weakly correlated; mono collapse improves it.
        assert low_corr(y) > low_corr(x)

    def test_mono_zero_keeps_low_width(self):
        rng = _rng(4)
        t = np.arange(SR // 2) / SR
        mid = 0.4 * np.sin(2 * np.pi * 60.0 * t)
        side = 0.15 * rng.standard_normal(len(t))
        left = (mid + side) / np.sqrt(2.0)
        right = (mid - side) / np.sqrt(2.0)
        x = np.stack([left, right])

        p = StereoImagingParams(mono_below_hz=0.0, low_width=1.4)
        y = StereoImaging(SR, p).process(x)

        bands = LinkwitzRiley4(SR, 150.0, 3000.0).split(y)
        l_b, r_b = bands[0][0], bands[0][1]
        # Side must remain: L != R in the low band.
        assert np.sqrt(np.mean((l_b - r_b) ** 2)) > 1e-3

    def test_mid_band_keeps_stereo_when_only_lows_mono(self):
        rng = _rng(5)
        t = np.arange(SR // 2) / SR
        low_mid = 0.4 * np.sin(2 * np.pi * 60.0 * t)
        high_mid = 0.4 * np.sin(2 * np.pi * 1000.0 * t)
        left = low_mid + high_mid + 0.1 * rng.standard_normal(len(t))
        right = low_mid - high_mid + 0.1 * rng.standard_normal(len(t))
        x = np.stack([left, right])

        p = StereoImagingParams(mono_below_hz=120.0)
        y = StereoImaging(SR, p).process(x)

        bands = LinkwitzRiley4(SR, 150.0, 3000.0).split(y)
        l_m, r_m = bands[1][0], bands[1][1]
        # The mid band keeps its anti-phase content (right is -high_mid).
        assert np.sqrt(np.mean((l_m - r_m) ** 2)) > 1e-2


class TestCorrelationSafety:
    def test_safety_restores_negative_correlation(self):
        # Anti-phase low band: L = +sine, R = -sine → corr < -0.1.
        # The params must be NON-neutral (a width != 1.0) so the processing
        # path actually runs: with all-neutral defaults the module is a
        # bit-exact bypass and the safety never executes.
        t = np.arange(SR // 4) / SR
        left = 0.5 * np.sin(2 * np.pi * 100.0 * t)
        right = -0.5 * np.sin(2 * np.pi * 100.0 * t)
        x = np.stack([left, right])
        assert _corr(x) < -0.1

        p = StereoImagingParams(mono_below_hz=0.0, low_width=1.1)
        y = StereoImaging(SR, p).process(x)

        assert _corr(y) >= -0.1
        # Not degraded to full mono unless needed: side energy mostly kept.
        assert np.sqrt(np.mean((y[0] - y[1]) ** 2)) > 1e-3

    def test_safety_does_not_touch_healthy_signal(self):
        x = _stereo(_sine())
        p = StereoImagingParams(mono_below_hz=0.0, low_width=1.5)
        y = StereoImaging(SR, p).process(x)
        # Correlated input stays above the floor.
        assert _corr(y) > -0.1


def _three_tone_x() -> np.ndarray:
    """Stereo signal with energy in ALL three LR4 bands.

    Low (80 Hz) is correlated, mid (500 Hz) correlated, high (8 kHz) is
    anti-phase. Every band carries real energy so a per-band width change is
    measurable and cross-band leakage is dominated by LR4 ripple, not an
    empty-band measurement artifact.
    """
    t = np.arange(SR // 2) / SR
    low = 0.5 * np.sin(2 * np.pi * 80.0 * t)
    mid = 0.4 * np.sin(2 * np.pi * 500.0 * t)
    high = 0.3 * np.sin(2 * np.pi * 8000.0 * t)
    return np.stack([low + mid + high, low + mid - high])


def _band_energy_pct(
    x: np.ndarray, y: np.ndarray, band_index: int
) -> float:
    """Relative energy change of one LR4 band between x and y, in percent.

    Uses energy per band rather than a sample-domain difference: the causal
    LR4 recombine is an all-pass, so ``bands_out[i] - bands_in[i]`` picks up
    the filter's group delay as a phantom "change" even when the band was
    untouched. Band energy is invariant to that phase.
    """
    bands_in = LinkwitzRiley4(SR, 150.0, 3000.0).split(x)
    bands_out = LinkwitzRiley4(SR, 150.0, 3000.0).split(y)
    e_in = float(np.sqrt(np.mean(bands_in[band_index] ** 2)))
    e_out = float(np.sqrt(np.mean(bands_out[band_index] ** 2)))
    if e_in < 1e-9:
        return float("inf")
    return abs(e_out - e_in) / e_in * 100.0


class TestBandsIndependent:
    def test_low_width_affects_low_only(self):
        x = _three_tone_x()
        p = StereoImagingParams(low_width=1.8, mid_width=1.0, high_width=1.0)
        y = StereoImaging(SR, p).process(x)

        change_low = _band_energy_pct(x, y, 0)
        change_mid = _band_energy_pct(x, y, 1)
        change_high = _band_energy_pct(x, y, 2)

        # The low band changes substantially; the untouched bands only drift
        # by LR4 ripple/transition (~1.5% worst case), at least 5x smaller.
        assert change_low > 5.0
        assert change_high < change_low * 0.2
        assert change_mid < change_low * 0.2

    def test_mid_width_affects_mid_only(self):
        x = _three_tone_x()
        p = StereoImagingParams(low_width=1.0, mid_width=1.8, high_width=1.0)
        y = StereoImaging(SR, p).process(x)

        change_low = _band_energy_pct(x, y, 0)
        change_mid = _band_energy_pct(x, y, 1)
        change_high = _band_energy_pct(x, y, 2)

        assert change_mid > 5.0
        assert change_high < change_mid * 0.2
        assert change_low < change_mid * 0.2

    def test_high_width_affects_high_only(self):
        x = _three_tone_x()
        p = StereoImagingParams(low_width=1.0, mid_width=1.0, high_width=1.8)
        y = StereoImaging(SR, p).process(x)

        change_low = _band_energy_pct(x, y, 0)
        change_mid = _band_energy_pct(x, y, 1)
        change_high = _band_energy_pct(x, y, 2)

        # High band changes substantially; low/mid untouched drift only by
        # ripple/transition (~0.4% and 1.5%), at least 5x smaller.
        assert change_high > 5.0
        assert change_low < change_high * 0.2
        assert change_mid < change_high * 0.2


class TestIO:
    def test_shape_and_dtype_preserved(self):
        x = _stereo(_sine()).astype(np.float64)
        p = StereoImagingParams(low_width=1.4)
        y = apply_stereo_imaging(x, SR, p)
        assert y.shape == x.shape
        assert y.dtype == np.float64

    def test_mono_input_returned_unchanged(self):
        x = _sine()
        p = StereoImagingParams(low_width=1.8, mono_below_hz=120.0)
        y = apply_stereo_imaging(x, SR, p)
        assert np.array_equal(x, y)

    def test_deterministic(self):
        rng = _rng(7)
        x = rng.standard_normal((2, SR // 4)).astype(np.float64) * 0.3
        p = StereoImagingParams(low_width=1.5, high_width=0.6, mono_below_hz=100.0)
        y1 = StereoImaging(SR, p).process(x)
        y2 = StereoImaging(SR, p).process(x)
        assert np.array_equal(y1, y2)

    def test_finite_output(self):
        rng = _rng(8)
        x = rng.standard_normal((2, SR // 4)).astype(np.float64) * 0.3
        p = StereoImagingParams(low_width=1.8, mid_width=0.5, high_width=1.3,
                                mono_below_hz=120.0)
        y = StereoImaging(SR, p).process(x)
        assert np.all(np.isfinite(y))

    def test_diagnostics_engaged(self):
        x = _stereo(_sine())
        p = StereoImagingParams(low_width=1.4)
        _, diag = StereoImaging(SR, p).process_with_diagnostics(x)
        assert diag["neutral"] is False
        assert diag["band_widths_used"] == [1.4, 1.0, 1.0]
        assert np.isfinite(diag["correlation_in"])
        assert np.isfinite(diag["correlation_out"])


class TestValidation:
    def test_bad_crossover_order_raises(self):
        with pytest.raises(ValueError):
            StereoImaging(SR, StereoImagingParams(crossover_low_hz=3000.0,
                                                  crossover_high_hz=150.0))

    def test_width_out_of_range_raises(self):
        with pytest.raises(ValueError):
            StereoImaging(SR, StereoImagingParams(low_width=2.5))
        with pytest.raises(ValueError):
            StereoImaging(SR, StereoImagingParams(high_width=-1.0))

    def test_mono_below_too_high_raises(self):
        with pytest.raises(ValueError):
            StereoImaging(SR, StereoImagingParams(mono_below_hz=SR / 2))

    def test_wrong_ndim_raises(self):
        with pytest.raises(ValueError):
            StereoImaging(SR, StereoImagingParams(low_width=1.4)).process(
                np.zeros((3, 100))
            )


def _constant_power_gains_import():
    """Re-derive the constant-power gains exactly as the module computes them."""
    from audiomind.processing.stereo_imaging import _constant_power_gains

    return _constant_power_gains(1.0)
