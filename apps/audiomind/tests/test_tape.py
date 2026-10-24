"""Objective tests for the real tape saturation model (Sprint 7 acceptance).

Covers: bit-exact neutral bypass, BOTH even and odd harmonics (bias
asymmetry + tanh), hysteresis memory (output differs, bounded, finite),
level-dependent HF roll-off (high drive attenuates highs progressively
while the lows are not attenuated more), drive→THD monotonicity, neutral
auxiliary parameters inside an engaged stage, stereo channel consistency,
API robustness (mono/empty/dtype/finite), diagnostics, determinism, and
parameter validation. Imports only numpy/scipy plus the pure-DSP tape and
multiband modules — never the pedalboard-backed engine — so these tests run
on any machine.
"""
import sys

sys.path.insert(0, "src")

import numpy as np
import pytest

from audiomind.processing.tape import (
    TapeParams,
    TapeSaturation,
    tape_is_neutral,
    tape_saturate,
)

SR = 44100
#: Analysis window (samples): 0.5 s → 2 Hz bin spacing, so 200 Hz (bin 100),
#: 440 Hz (bin 220), 10 kHz (bin 5000) and all their harmonics land EXACTLY
#: on rfft bins (integer number of cycles → no spectral leakage).
WINDOW = SR // 2
#: Analysis window start: skips the shaper/envelope startup transients.
ANALYZE_START = int(SR * 0.25)


def _tone(freq: float, amp: float, dur_s: float = 1.0) -> np.ndarray:
    n = int(SR * dur_s)
    t = np.arange(n) / SR
    return amp * np.sin(2.0 * np.pi * freq * t)


def _two_tone(
    f1: float = 200.0, f2: float = 10000.0, amp: float = 0.4,
) -> np.ndarray:
    return _tone(f1, amp) + _tone(f2, amp)


def _spectrum(mono: np.ndarray) -> np.ndarray:
    """Magnitude spectrum of the bin-aligned window (A·N/2 at harmonic bins)."""
    return np.abs(np.fft.rfft(mono[ANALYZE_START:ANALYZE_START + WINDOW]))


def _bin_amp(spectrum: np.ndarray, freq: float) -> float:
    k = int(round(freq * WINDOW / SR))
    return float(spectrum[k])


def _engaged(
    drive_db: float = 9.0, hysteresis: float = 0.3, bias: float = 0.05,
    rolloff_amount: float = 0.0, hf_shelf_hz: float = 8000.0,
) -> TapeParams:
    """A non-neutral tape configuration with the given settings."""
    return TapeParams(
        drive_db=drive_db,
        hysteresis=hysteresis,
        bias=bias,
        rolloff_amount=rolloff_amount,
        hf_shelf_hz=hf_shelf_hz,
    )


# ── Neutral bypass ───────────────────────────────────────────────────


def test_neutral_default_is_bit_exact_bypass():
    rng = np.random.default_rng(0)
    x = (rng.standard_normal((2, int(SR * 0.5))) * 0.3).astype(np.float32)
    assert tape_is_neutral(TapeParams())
    assert TapeParams().is_neutral()
    assert np.array_equal(tape_saturate(x, SR), x)
    assert np.array_equal(TapeSaturation(SR).process(x), x)
    assert np.array_equal(TapeSaturation(SR, TapeParams()).process(x), x)


# ── Even AND odd harmonics (Sprint 7 acceptance) ─────────────────────


def test_engaged_produces_both_even_and_odd_harmonics():
    # bias (asymmetry) → even, tanh shaper → odd. roll-off off so the
    # harmonic bins are not attenuated by the HF shelf.
    params = _engaged(drive_db=9.0, hysteresis=0.3, bias=0.1)
    out = TapeSaturation(SR, params).process(_tone(440.0, 0.5))
    spec = _spectrum(out)

    fund = _bin_amp(spec, 440.0)
    h2 = _bin_amp(spec, 880.0)
    h3 = _bin_amp(spec, 1320.0)

    assert fund > 0.0
    # Both families present above −60 dB relative to the fundamental
    # (roadmap acceptance: even AND odd harmonics from one engaged stage).
    assert 20.0 * np.log10(h2 / fund) > -60.0
    assert 20.0 * np.log10(h3 / fund) > -60.0
    assert h2 > 0.0 and h3 > 0.0


# ── Hysteresis memory ────────────────────────────────────────────────


def test_hysteresis_memory_changes_output_and_bounds():
    x = _tone(440.0, 0.5)
    no_mem = TapeSaturation(
        SR, _engaged(hysteresis=0.0)
    ).process(x)
    with_mem = TapeSaturation(
        SR, _engaged(hysteresis=0.4)
    ).process(x)

    # The recursive term is not a no-op: same drive/bias, different memory.
    assert not np.array_equal(no_mem, with_mem)
    # The shaper is bounded (tanh clips the feedback): |y| stays ≤ ~1.
    assert np.max(np.abs(with_mem)) <= 1.0
    assert np.all(np.isfinite(with_mem))


# ── Level-dependent HF roll-off (Sprint 7 acceptance) ────────────────


def test_level_dependent_hf_rolloff_progressive():
    x = _two_tone(200.0, 10000.0, amp=0.4)
    s_in = _spectrum(x)
    in_200 = _bin_amp(s_in, 200.0)
    in_10k = _bin_amp(s_in, 10000.0)

    def atten_db(drive_db: float) -> tuple[float, float]:
        out = TapeSaturation(
            SR, _engaged(drive_db=drive_db, rolloff_amount=0.6)
        ).process(x)
        s = _spectrum(out)
        return (
            20.0 * np.log10(_bin_amp(s, 200.0) / in_200),
            20.0 * np.log10(_bin_amp(s, 10000.0) / in_10k),
        )

    a200_low, a10k_low = atten_db(6.0)
    a200_high, a10k_high = atten_db(18.0)

    # High drive attenuates the 10 kHz component clearly MORE than low drive
    # (progressive roll-off), while the 200 Hz component is NOT attenuated
    # more (the shaper boosts its fundamental toward 4/π, it never rolls off).
    assert a10k_high < a10k_low - 2.0
    assert a200_high > a200_low - 1.0

    # "Progressive": HF attenuation is monotonic across increasing drives
    # (each higher drive attenuates the 10 kHz component more than the last).
    drives = (6.0, 9.0, 12.0, 18.0)
    a10k = [atten_db(d)[1] for d in drives]
    assert all(b < a - 0.25 for a, b in zip(a10k, a10k[1:], strict=False))


# ── Drive scaling (THD rises monotonically) ──────────────────────────


def test_thd_rises_monotonically_with_drive():
    x = _tone(440.0, 0.5)

    def thd(drive_db: float) -> float:
        out = TapeSaturation(
            SR, _engaged(drive_db=drive_db)
        ).process(x)
        s = _spectrum(out)
        fund = _bin_amp(s, 440.0)
        harmonics = sum(
            _bin_amp(s, 440.0 * (h + 1)) ** 2 for h in range(1, 20)
        )
        return float(np.sqrt(harmonics) / fund)

    values = [thd(d) for d in (0.0, 3.0, 6.0, 9.0, 12.0, 18.0)]
    assert all(a < b for a, b in zip(values, values[1:], strict=False))


# ── Neutral auxiliary params inside an engaged stage ─────────────────


def test_neutral_auxiliary_params_inside_engaged_stage():
    # drive > 0 with hysteresis/bias/rolloff at their zero defaults is a
    # PURE drive stage: the zero auxiliary parameters contribute nothing, so
    # it is bit-identical to a stage built with drive only.
    x = _tone(440.0, 0.5)
    drive_only = TapeSaturation(SR, TapeParams(drive_db=9.0)).process(x)
    aux_neutral = TapeSaturation(
        SR, TapeParams(
            drive_db=9.0, hysteresis=0.0, bias=0.0, rolloff_amount=0.0,
        )
    ).process(x)
    assert np.array_equal(drive_only, aux_neutral)


# ── Stereo ───────────────────────────────────────────────────────────


def test_stereo_identical_channels_stay_identical():
    params = _engaged(hysteresis=0.4, rolloff_amount=0.5)
    mono = _two_tone(amp=0.4)
    x = np.stack([mono, mono])
    out = TapeSaturation(SR, params).process(x)
    assert out.shape == x.shape
    assert np.array_equal(out[0], out[1])


# ── Diagnostics ──────────────────────────────────────────────────────


def test_diagnostics_report_stage_metrics():
    out, diag = TapeSaturation(
        SR, _engaged(drive_db=18.0, rolloff_amount=0.6)
    ).process_with_diagnostics(_two_tone(amp=0.4))
    assert out.ndim == 1
    assert diag["mean_blend"] > 0.0
    assert diag["hf_rolloff_db"] < 0.0
    assert diag["peak_reduction_db"] < 6.0
    assert diag["asymmetry"] >= 0.0


# ── API robustness ───────────────────────────────────────────────────


def test_mono_and_empty_inputs():
    tape = TapeSaturation(SR, _engaged(hysteresis=0.3))
    mono = _tone(440.0, 0.5, dur_s=0.3)
    assert tape.process(mono).shape == mono.shape
    empty = np.zeros((2, 0))
    assert tape.process(empty).shape == empty.shape
    assert tape_saturate(empty, SR).shape == empty.shape
    assert tape_saturate(np.zeros(0), SR).shape == (0,)


def test_shape_and_dtype_preserved():
    x = np.random.default_rng(0).standard_normal(
        (2, int(SR * 0.5))
    ).astype(np.float32)
    x /= np.max(np.abs(x))
    out = TapeSaturation(
        SR, _engaged(drive_db=12.0, rolloff_amount=0.5)
    ).process(x)
    assert out.shape == x.shape
    assert out.dtype == x.dtype
    assert np.all(np.isfinite(out))


# ── Parameter validation ─────────────────────────────────────────────


def test_invalid_params_raise():
    with pytest.raises(ValueError):
        TapeSaturation(SR, TapeParams(drive_db=-1.0))
    with pytest.raises(ValueError):
        TapeSaturation(SR, TapeParams(drive_db=25.0))
    with pytest.raises(ValueError):
        TapeSaturation(SR, TapeParams(drive_db=float("nan")))
    with pytest.raises(ValueError):
        TapeSaturation(SR, TapeParams(drive_db=float("inf")))
    with pytest.raises(ValueError):
        TapeSaturation(SR, TapeParams(hysteresis=-0.1))
    with pytest.raises(ValueError):
        TapeSaturation(SR, TapeParams(hysteresis=1.5))
    with pytest.raises(ValueError):
        TapeSaturation(SR, TapeParams(bias=-0.1))
    with pytest.raises(ValueError):
        TapeSaturation(SR, TapeParams(bias=0.5))
    with pytest.raises(ValueError):
        TapeSaturation(SR, TapeParams(rolloff_amount=-0.1))
    with pytest.raises(ValueError):
        TapeSaturation(SR, TapeParams(rolloff_amount=1.5))
    with pytest.raises(ValueError):
        TapeSaturation(SR, TapeParams(hf_shelf_hz=0.0))
    with pytest.raises(ValueError):
        TapeSaturation(SR, TapeParams(hf_shelf_hz=SR / 2.0))
    with pytest.raises(ValueError):
        TapeSaturation(SR, TapeParams(hf_shelf_hz=-100.0))


# ── Determinism ──────────────────────────────────────────────────────


def test_deterministic_across_runs():
    params = _engaged(drive_db=12.0, rolloff_amount=0.5)
    x = _two_tone(amp=0.4)
    out_a = TapeSaturation(SR, params).process(x)
    out_b = TapeSaturation(SR, params).process(x)
    assert np.array_equal(out_a, out_b)
