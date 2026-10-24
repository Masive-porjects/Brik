"""Objective tests for the dynamic EQ (Sprint 5 acceptance).

Covers: bit-exact neutral bypass, the exact roadmap gain formula
``G = min(0, −(E − T)·(1 − 1/R))``, cuts-only behavior, reduction only when
the problem exists (injected 400 Hz resonance), frequency selectivity, joint
stereo detection, API robustness (mono/empty/dtype/finite), and parameter
validation. Imports only numpy/scipy plus the pure-DSP modules — never the
pedalboard-backed engine — so these tests run on any machine.
"""
import sys

sys.path.insert(0, "src")

import numpy as np
import pytest
from scipy.signal import sosfilt

from audiomind.processing.dyn_eq import (
    DynamicEQ,
    DynEqBandParams,
    DynEqParams,
    dyn_eq_gain,
    dynamic_eq,
)

SR = 44100


def _stereo(mono: np.ndarray) -> np.ndarray:
    return np.stack([mono, mono])


def _tone(freq: float, amp: float, dur_s: float = 1.5) -> np.ndarray:
    t = np.arange(int(SR * dur_s)) / SR
    return amp * np.sin(2.0 * np.pi * freq * t)


def _engaged_band(
    freq_hz: float = 400.0, ratio: float = 4.0, threshold_db: float = -20.0,
) -> DynEqParams:
    """One engaged band; the other two stay ratio 1:1 (transparent)."""
    neutral = (DynEqBandParams(freq_hz=2500.0, q=4.0),
               DynEqBandParams(freq_hz=8000.0, q=4.0))
    return DynEqParams(
        bands=(
            DynEqBandParams(
                freq_hz=freq_hz, q=4.0,
                threshold_db=threshold_db, ratio=ratio,
            ),
            *neutral,
        )
    )


# ── Neutral bypass ───────────────────────────────────────────────────


def test_neutral_default_is_bit_exact_bypass():
    rng = np.random.default_rng(0)
    x = (rng.standard_normal((2, int(SR * 0.5))) * 0.3).astype(np.float32)
    assert np.array_equal(dynamic_eq(x, SR), x)
    assert np.array_equal(DynamicEQ(SR).process(x), x)
    assert np.array_equal(DynamicEQ(SR, DynEqParams()).process(x), x)


# ── Gain computer (exact roadmap formula) ────────────────────────────


def test_gain_computer_exact_roadmap_formula():
    e = np.array([-60.0, -40.0, -20.0, -10.0, 0.0, 5.0, 10.0])
    for thr, ratio in ((-20.0, 4.0), (-10.0, 2.0), (-30.0, 10.0)):
        g = dyn_eq_gain(e, thr, ratio)
        expected = np.minimum(0.0, -(e - thr) * (1.0 - 1.0 / ratio))
        assert np.allclose(g, expected, atol=1e-12)
    # ratio 1:1 → transparent everywhere
    assert np.array_equal(dyn_eq_gain(e, -20.0, 1.0), np.zeros_like(e))


def test_gains_are_cuts_only_never_positive():
    e = np.linspace(-60.0, 0.0, 2001)
    for ratio in (2.0, 4.0, 10.0):
        assert np.all(dyn_eq_gain(e, -20.0, ratio) <= 1e-12)
    # strictly below threshold is exactly transparent (G == 0)
    below = e[e < -20.0]
    assert np.all(dyn_eq_gain(below, -20.0, 4.0) == 0.0)


# ── Reduction only when the problem exists ───────────────────────────


def test_reduction_only_when_the_problem_exists():
    n = int(SR * 2.0)
    t = np.arange(n) / SR
    clean = 0.4 * np.sin(2.0 * np.pi * 1000.0 * t) + 0.15 * np.sin(
        2.0 * np.pi * 8000.0 * t
    )
    mono = clean.copy()
    mono[n // 2:] += 0.5 * np.sin(2.0 * np.pi * 400.0 * t[n // 2:])
    x = _stereo(mono)

    eq = DynamicEQ(SR, _engaged_band(freq_hz=400.0, ratio=4.0))
    out, diag = eq.process_with_diagnostics(x)
    assert diag["gr_mean_db"][0] < -3.0  # the 400 Hz band engaged overall
    assert np.all(diag["gain_db"][0] <= 1e-12)  # cuts only, never boosts

    def band_rms(a: np.ndarray, start: int, stop: int) -> float:
        band = sosfilt(eq._sos[0], a.mean(axis=0))
        return float(np.sqrt(np.mean(band[start:stop] ** 2)))

    first_in = band_rms(x, 0, n // 2)
    first_out = band_rms(out, 0, n // 2)
    assert abs(20.0 * np.log10(first_out / first_in)) < 0.1  # clean half ~bit-exact
    second_in = band_rms(x, n // 2, n)
    second_out = band_rms(out, n // 2, n)
    reduction = 20.0 * np.log10(second_in / second_out)
    assert reduction > 3.0  # resonance present → real cut


# ── Frequency selectivity ────────────────────────────────────────────


def test_frequency_selectivity_400hz_band_spares_8khz():
    tone_400 = _tone(400.0, 0.5)
    tone_8k = _tone(8000.0, 0.5)
    eq = DynamicEQ(SR, _engaged_band(freq_hz=400.0, ratio=4.0))

    def reduction_db(mono: np.ndarray) -> float:
        start = int(SR * 0.2)  # skip the filter/envelope transient
        band_in = sosfilt(eq._sos[0], mono)
        out = eq.process(_stereo(mono))
        band_out = sosfilt(eq._sos[0], out.mean(axis=0))
        r_in = float(np.sqrt(np.mean(band_in[start:] ** 2)))
        r_out = float(np.sqrt(np.mean(band_out[start:] ** 2)))
        return 20.0 * np.log10(r_in / r_out)

    red_400 = reduction_db(tone_400)
    red_8k = reduction_db(tone_8k)
    assert red_400 > 3.0
    assert red_8k < 1.0
    assert red_8k < red_400 - 3.0


# ── Stereo joint detection ───────────────────────────────────────────


def test_stereo_joint_detection_preserves_image_and_shares_gain():
    mono = _tone(400.0, 0.5)
    eq = DynamicEQ(SR, _engaged_band(freq_hz=400.0, ratio=4.0))
    out = eq.process(_stereo(mono))
    assert np.array_equal(out[0], out[1])  # identical channels stay identical

    # A loud tone in ONE channel engages the joint (L+R)/2 detector and the
    # cut applies to BOTH channels: the quiet 400 Hz in the right channel
    # (alone below threshold) is reduced too.
    left = _tone(400.0, 0.5)
    right = _tone(400.0, 0.02)
    x = np.stack([left, right])
    out, diag = eq.process_with_diagnostics(x)
    assert diag["gr_mean_db"][0] < -3.0

    start = int(SR * 0.2)
    band_in = sosfilt(eq._sos[0], x[1])[start:]
    band_out = sosfilt(eq._sos[0], out[1])[start:]
    reduction_right = 20.0 * np.log10(
        np.sqrt(np.mean(band_in**2)) / np.sqrt(np.mean(band_out**2))
    )
    assert reduction_right > 3.0  # joint cut applied to the quiet channel


# ── API robustness ───────────────────────────────────────────────────


def test_mono_and_empty_inputs():
    mono = _tone(400.0, 0.5, dur_s=0.5)
    eq = DynamicEQ(SR, _engaged_band(freq_hz=400.0, ratio=4.0))
    assert eq.process(mono).shape == mono.shape
    empty = np.zeros((2, 0))
    assert eq.process(empty).shape == empty.shape
    assert dynamic_eq(empty, SR).shape == empty.shape


def test_shape_and_dtype_preserved():
    x = np.random.default_rng(0).standard_normal(
        (2, int(SR * 0.5))
    ).astype(np.float32)
    x /= np.max(np.abs(x))
    out = DynamicEQ(SR, _engaged_band(freq_hz=400.0, ratio=4.0)).process(x)
    assert out.shape == x.shape
    assert out.dtype == x.dtype
    assert np.all(np.isfinite(out))


# ── Parameter validation ─────────────────────────────────────────────


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        DynamicEQ(SR, DynEqParams(bands=(DynEqBandParams(400.0, 4.0, ratio=0.5),)))
    with pytest.raises(ValueError):
        DynamicEQ(SR, DynEqParams(bands=(DynEqBandParams(-1.0, 4.0),)))
    with pytest.raises(ValueError):
        DynamicEQ(SR, DynEqParams(bands=(DynEqBandParams(SR / 2.0, 4.0),)))
    with pytest.raises(ValueError):
        DynamicEQ(SR, DynEqParams(bands=(DynEqBandParams(400.0, 0.0),)))
