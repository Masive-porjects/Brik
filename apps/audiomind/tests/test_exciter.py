"""Objective tests for the harmonic exciter (Sprint 6 acceptance).

Covers: bit-exact neutral bypass, the even-harmonic math (full-wave
rectifier → only even harmonics, H2 ≈ 0.42 of the fundamental), the odd
tanh path, the mix path, the high-pass on the EXCITED content (bass is not
fattened), linear amount scaling, neutral-band-within-engaged-stage
behavior, stereo channel consistency, API robustness (mono/empty/dtype/
finite), diagnostics, and parameter validation. Imports only numpy/scipy
plus the pure-DSP exciter module — never the pedalboard-backed engine — so
these tests run on any machine.
"""
import sys

sys.path.insert(0, "src")

import numpy as np
import pytest

from audiomind.processing.exciter import (
    Exciter,
    ExciterBandParams,
    ExciterParams,
    excite,
)

SR = 44100
#: Analysis window (samples): 0.5 s → 2 Hz bin spacing, so 440 Hz (bin 220),
#: its harmonics and the 60 Hz / 1 kHz test tones land EXACTLY on rfft bins
#: (integer number of cycles → no spectral leakage).
WINDOW = SR // 2
#: Analysis window start: skips the HPF/rectifier startup transients.
ANALYZE_START = int(SR * 0.25)


def _tone(freq: float, amp: float, dur_s: float = 1.0) -> np.ndarray:
    n = int(SR * dur_s)
    t = np.arange(n) / SR
    return amp * np.sin(2.0 * np.pi * freq * t)


def _spectrum(mono: np.ndarray) -> np.ndarray:
    """Magnitude spectrum of the bin-aligned window (A·N/2 at harmonic bins)."""
    return np.abs(np.fft.rfft(mono[ANALYZE_START:ANALYZE_START + WINDOW]))


def _bin_amp(spectrum: np.ndarray, freq: float) -> float:
    k = int(round(freq * WINDOW / SR))
    return float(spectrum[k])


def _engaged_band(
    mode: str = "even", amount: float = 1.0, low_cut_hz: float = 20.0, **kw,
) -> ExciterParams:
    """A single engaged band; defaults chosen for clean spectral analysis."""
    return ExciterParams(
        bands=(ExciterBandParams(
            mode=mode, amount=amount, low_cut_hz=low_cut_hz, **kw
        ),)
    )


# ── Neutral bypass ───────────────────────────────────────────────────


def test_neutral_default_is_bit_exact_bypass():
    rng = np.random.default_rng(0)
    x = (rng.standard_normal((2, int(SR * 0.5))) * 0.3).astype(np.float32)
    assert np.array_equal(excite(x, SR), x)
    assert np.array_equal(Exciter(SR).process(x), x)
    assert np.array_equal(Exciter(SR, ExciterParams()).process(x), x)


# ── Even harmonics (full-wave rectifier math) ────────────────────────


def test_even_harmonic_math_rectifier_produces_only_even():
    params = _engaged_band(mode="even", amount=1.0)
    out = Exciter(SR, params).process(_tone(440.0, 0.5))
    spec = _spectrum(out)

    fund = _bin_amp(spec, 440.0)
    h2 = _bin_amp(spec, 880.0)
    h4 = _bin_amp(spec, 1760.0)
    h3 = _bin_amp(spec, 1320.0)

    assert fund > 0.0
    # |sin(ωt)| → H2 = 4/(3π) ≈ 0.42 of the fundamental (roadmap acceptance).
    assert 0.35 < h2 / fund < 0.50
    # H4 = 4/(15π) ≈ 0.085 of the fundamental — clearly present.
    assert h4 / fund > 0.04
    # The rectifier produces ONLY even harmonics: H3 is numerically absent.
    assert h3 / fund < 1e-3


# ── Odd path (tanh with drive) ───────────────────────────────────────


def test_odd_path_produces_odd_harmonics_only():
    params = _engaged_band(mode="odd", amount=1.0, drive_db=18.0)
    out = Exciter(SR, params).process(_tone(440.0, 0.5))
    spec = _spectrum(out)

    fund = _bin_amp(spec, 440.0)
    h3 = _bin_amp(spec, 1320.0)
    h2 = _bin_amp(spec, 880.0)

    assert fund > 0.0
    assert h3 / fund > 0.1   # 3rd harmonic clearly present (drive saturates)
    assert h2 / fund < 1e-3  # tanh is odd → no even harmonics
    assert h2 < h3           # no even dominance on the odd path


# ── Mix path (even + odd blend) ──────────────────────────────────────


def test_mix_mode_produces_both_even_and_odd_harmonics():
    params = _engaged_band(mode="mix", amount=1.0, drive_db=18.0,
                           harmonic_blend=0.5)
    out = Exciter(SR, params).process(_tone(440.0, 0.5))
    spec = _spectrum(out)

    fund = _bin_amp(spec, 440.0)
    h2 = _bin_amp(spec, 880.0)
    h3 = _bin_amp(spec, 1320.0)

    assert fund > 0.0
    assert h2 / fund > 0.03  # even family present
    assert h3 / fund > 0.1   # odd family present


# ── HPF on the EXCITED content (bass not fattened) ───────────────────


def test_hpf_on_excited_content_spares_the_bass():
    low = _tone(60.0, 0.5)
    high = _tone(1000.0, 0.5)

    def added_rms(mono: np.ndarray, amount: float) -> float:
        out = Exciter(SR, _engaged_band(mode="even", amount=amount,
                                        low_cut_hz=800.0)).process(mono)
        return float(np.sqrt(np.mean((out - mono) ** 2)))

    low_in = float(np.sqrt(np.mean(low**2)))
    high_in = float(np.sqrt(np.mean(high**2)))
    low_add = added_rms(low, 1.0)
    high_add = added_rms(high, 1.0)

    # 60 Hz is NOT fattened: the excited content (120/240/… Hz) sits below
    # the 800 Hz high-pass, so the added energy is a tiny fraction of input.
    assert low_add / low_in < 0.03
    # 1 kHz IS boosted: its even harmonics (2 kHz, 4 kHz, …) pass the
    # high-pass and add real energy.
    assert high_add / high_in > 0.2
    assert high_add > 10.0 * low_add

    # Fundamental-level check at the 60 Hz bin: amount 1 vs amount 0.
    spec0 = _spectrum(Exciter(
        SR, _engaged_band(mode="even", amount=0.0, low_cut_hz=800.0)
    ).process(low))
    spec1 = _spectrum(Exciter(
        SR, _engaged_band(mode="even", amount=1.0, low_cut_hz=800.0)
    ).process(low))
    db = 20.0 * np.log10(_bin_amp(spec1, 60.0) / _bin_amp(spec0, 60.0))
    assert abs(db) < 0.3


# ── Amount scaling (linear in the mix) ───────────────────────────────


def test_amount_scaling_is_linear_in_the_mix():
    x = _tone(440.0, 0.5)

    def excited_for(amount: float) -> np.ndarray:
        return Exciter(SR, _engaged_band(mode="even", amount=amount)).process(x) - x

    d_full = excited_for(1.0)
    d_half = excited_for(0.5)
    assert np.allclose(d_half, 0.5 * d_full, rtol=1e-9, atol=1e-12)


# ── Neutral band inside an engaged stage ─────────────────────────────


def test_zero_amount_band_contributes_nothing():
    with_neutral = ExciterParams(
        bands=(
            ExciterBandParams(mode="even", amount=0.5, low_cut_hz=20.0),
            ExciterBandParams(mode="odd", amount=0.0, drive_db=18.0,
                              low_cut_hz=800.0),
        )
    )
    only_engaged = ExciterParams(
        bands=(ExciterBandParams(mode="even", amount=0.5, low_cut_hz=20.0),)
    )
    x = _tone(440.0, 0.5)
    out_a = Exciter(SR, with_neutral).process(x)
    out_b = Exciter(SR, only_engaged).process(x)
    assert np.array_equal(out_a, out_b)


# ── Stereo ───────────────────────────────────────────────────────────


def test_stereo_identical_channels_stay_identical():
    params = _engaged_band(mode="even", amount=0.5)
    mono = _tone(440.0, 0.5)
    x = np.stack([mono, mono])
    out = Exciter(SR, params).process(x)
    assert out.shape == x.shape
    assert np.array_equal(out[0], out[1])


# ── Diagnostics ──────────────────────────────────────────────────────


def test_diagnostics_report_per_band_content():
    params = _engaged_band(mode="even", amount=0.5)
    out, diag = Exciter(SR, params).process_with_diagnostics(_tone(440.0, 0.5))
    assert out.ndim == 1
    assert len(diag["excited_rms"]) == 1
    assert len(diag["thd"]) == 1
    assert diag["band_mode"] == ["even"]
    assert diag["amount"] == [0.5]
    assert diag["excited_rms"][0] > 0.0
    assert 0.0 < diag["thd"][0] < 1.0


# ── API robustness ───────────────────────────────────────────────────


def test_mono_and_empty_inputs():
    exc = Exciter(SR, _engaged_band(mode="even", amount=0.5))
    mono = _tone(440.0, 0.5, dur_s=0.3)
    assert exc.process(mono).shape == mono.shape
    empty = np.zeros((2, 0))
    assert exc.process(empty).shape == empty.shape
    assert excite(empty, SR).shape == empty.shape
    assert excite(np.zeros(0), SR).shape == (0,)


def test_shape_and_dtype_preserved():
    x = np.random.default_rng(0).standard_normal(
        (2, int(SR * 0.5))
    ).astype(np.float32)
    x /= np.max(np.abs(x))
    out = Exciter(
        SR, _engaged_band(mode="mix", amount=0.5, drive_db=12.0, low_cut_hz=200.0)
    ).process(x)
    assert out.shape == x.shape
    assert out.dtype == x.dtype
    assert np.all(np.isfinite(out))


# ── Parameter validation ─────────────────────────────────────────────


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        Exciter(SR, ExciterParams(bands=(ExciterBandParams(mode="square"),)))
    with pytest.raises(ValueError):
        Exciter(SR, ExciterParams(bands=(ExciterBandParams(amount=-0.1),)))
    with pytest.raises(ValueError):
        Exciter(SR, ExciterParams(bands=(ExciterBandParams(amount=1.5),)))
    with pytest.raises(ValueError):
        Exciter(SR, ExciterParams(bands=(ExciterBandParams(drive_db=-1.0),)))
    with pytest.raises(ValueError):
        Exciter(SR, ExciterParams(bands=(ExciterBandParams(drive_db=30.0),)))
    with pytest.raises(ValueError):
        Exciter(SR, ExciterParams(bands=(ExciterBandParams(low_cut_hz=0.0),)))
    with pytest.raises(ValueError):
        Exciter(SR, ExciterParams(bands=(ExciterBandParams(low_cut_hz=SR / 2.0),)))
    with pytest.raises(ValueError):
        Exciter(SR, ExciterParams(
            bands=(ExciterBandParams(mode="mix", harmonic_blend=1.5),)
        ))
