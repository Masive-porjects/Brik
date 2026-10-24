"""Objective tests for the 16x oversampled soft-clipper (Sprint 3 acceptance).

Covers: aliasing below -90 dBFS at 16x (20 kHz full-scale sine FFT), the
oversampling benefit over 4x, bit-stable null behavior below the threshold,
bounded crest reduction, API robustness, and engine integration (clipper
runs before the true-peak limiter).
"""
import sys

sys.path.insert(0, "src")

import numpy as np
import pytest
import soundfile as sf

from audiomind.models.audio import MasteringParameters
from audiomind.processing.clipper import OVERSAMPLE, soft_clip
from audiomind.processing.engine import CLIPPER_HEADROOM_DB, process_audio
from audiomind.processing.truepeak import calculate_crest_factor

SR = 44100


def _stereo(mono: np.ndarray) -> np.ndarray:
    return np.stack([mono, mono])


def _burst_program(amp: float, burst_s: float = 0.05, tail_s: float = 0.5):
    burst = np.sin(2.0 * np.pi * 1000.0 * np.arange(int(SR * burst_s)) / SR)
    tail = np.full(int(SR * tail_s), amp)
    return np.concatenate([burst, tail])


def _worst_inband_spur_db(y: np.ndarray, f0: float) -> float:
    """Worst non-fundamental in-band spectral spur (dBFS) on the steady state."""
    seg = y[int(0.2 * SR):int(0.8 * SR)]
    n = seg.shape[-1]
    w = np.hanning(n)
    mag = np.abs(np.fft.rfft(seg * w)) / (n / 2) * 2
    freq = np.fft.rfftfreq(n, 1.0 / SR)
    inband = freq < (SR / 2 - 1)
    fund = (freq >= f0 - 30) & (freq <= f0 + 30)
    spurs = inband & ~fund
    return float(20 * np.log10(np.max(mag[spurs]) + 1e-15))


def test_aliasing_below_minus_90_db_at_16x():
    n = int(1.0 * SR)
    t = np.arange(n) / SR
    x = np.sin(2.0 * np.pi * 20000.0 * t)  # full scale, engaged (thr 0.5)
    y = soft_clip(x, SR, threshold_db=-6.0)
    assert OVERSAMPLE == 16
    assert _worst_inband_spur_db(y, 20000.0) < -90.0


def test_oversampling_improves_alias_floor():
    n = int(1.0 * SR)
    t = np.arange(n) / SR
    x = np.sin(2.0 * np.pi * 20000.0 * t)
    floor_16x = _worst_inband_spur_db(soft_clip(x, SR, threshold_db=-6.0), 20000.0)
    floor_4x = _worst_inband_spur_db(
        soft_clip(x, SR, threshold_db=-6.0, oversample=4), 20000.0
    )
    # At 4x the H9 fold (-> 3.6 kHz) floors every shaper near -60 dBFS;
    # 16x (H35 fold) must be at least 20 dB cleaner.
    assert floor_16x < floor_4x - 20.0


def test_null_below_threshold_bit_stable():
    t = np.arange(int(SR * 0.5)) / SR
    mono = 0.25 * np.sin(2.0 * np.pi * 997.0 * t)  # -12 dBFS, far below knee
    x = _stereo(mono)
    out = soft_clip(x, SR, threshold_db=-1.0)
    assert np.array_equal(out, x)


def test_linear_zone_passes_through_below_knee():
    # Even when the signal has content above the knee, samples below it must
    # pass through exactly on the null path (whole-signal below knee).
    t = np.arange(int(SR * 0.4)) / SR
    mono = 0.05 * np.sin(2.0 * np.pi * 1500.0 * t)  # -26 dBFS << knee
    x = _stereo(mono)
    assert np.array_equal(soft_clip(x, SR, threshold_db=-6.0), x)


def test_engaged_clipping_reduces_peak():
    burst = _burst_program(1.0)
    x = _stereo(burst)
    out = soft_clip(x, SR, threshold_db=-1.0)
    assert float(np.max(np.abs(out))) < float(np.max(np.abs(x)))


def _percussive_program(amp: float = 1.0):
    """Quiet body + loud transient bursts: high crest factor material."""
    n = int(SR * 0.5)
    t = np.arange(n) / SR
    body = 0.15 * np.sin(2.0 * np.pi * 1000.0 * t)
    bursts = np.zeros(n)
    for k in range(5):
        i = int(SR * (0.05 + 0.1 * k))
        b = int(0.005 * SR)
        bursts[i : i + b] = amp * np.hanning(b)
    return body + bursts


def test_bounded_crest_reduction():
    mono = _percussive_program(1.0)
    x = _stereo(mono)
    out = soft_clip(x, SR, threshold_db=-1.0)

    crest_in = calculate_crest_factor(x)
    crest_out = calculate_crest_factor(out)

    assert crest_in > 10.0  # genuinely percussive
    assert crest_out <= crest_in  # clipper never increases crest
    assert crest_in - crest_out <= 6.0  # bounded reduction (acceptance: <= N dB)
    assert crest_in - crest_out > 0.0  # engaged on full-scale transients


def test_threshold_must_be_below_zero_dbfs():
    with pytest.raises(ValueError):
        soft_clip(np.zeros((2, SR)), SR, threshold_db=0.0)


def test_shape_and_dtype_preserved():
    x = np.random.default_rng(0).standard_normal((2, int(SR * 0.5))).astype(np.float32)
    x /= np.max(np.abs(x))
    out = soft_clip(x, SR, threshold_db=-1.0)
    assert out.shape == x.shape
    assert out.dtype == x.dtype
    assert np.all(np.isfinite(out))


def test_mono_and_empty_inputs():
    mono = np.zeros(int(SR * 0.2))
    assert soft_clip(mono, SR, threshold_db=-1.0).shape == mono.shape
    empty = np.zeros((2, 0))
    assert soft_clip(empty, SR, threshold_db=-1.0).shape == empty.shape


def test_engine_clipper_before_limiter(tmp_path):
    """Full pipeline: clipper runs before the limiter, so the delivered master
    stays under the ceiling and never gains crest (the clipper would violate
    the ceiling if it ran after the limiter)."""
    dur_s = 1.5
    n = int(SR * dur_s)
    t = np.arange(n) / SR
    rng = np.random.default_rng(0)

    kick = np.exp(-t * 6.0) * np.sin(2.0 * np.pi * 120.0 * t)
    env = np.zeros(n)
    for off in range(0, n, int(SR * 0.35)):
        b = int(min(SR * 0.02, n - off))
        env[off:off + b] = 1.0
    snare = rng.standard_normal(n) * env * 0.3
    mono = kick + snare
    mono = mono / np.max(np.abs(mono))  # full-scale hot program
    x = _stereo(mono)

    in_path = tmp_path / "in.wav"
    out_path = tmp_path / "out.wav"
    sf.write(str(in_path), x.T, SR, subtype="FLOAT")

    # Neutral = bypass contract: MasteringParameters() now returns the input
    # untouched (bit-exact), which would bypass the clipper/limiter. Use a
    # minimally non-default baseline (target_lufs_db=-14.0, matching the auto
    # default ceiling) to engage the processing chain so the clipper/limiter act.
    metrics = process_audio(
        in_path, out_path, MasteringParameters(target_lufs_db=-14.0)
    )
    out, sr_out = sf.read(str(out_path), always_2d=True)
    out = out.T  # (channels, samples)

    # Default ceiling -1.0 dBTP (not already-mastered, target -14 LUFS is
    # not codec-aggressive): the clipper + limiter must keep true peak below it.
    assert metrics["true_peak_db"] <= -0.85
    # Crest is reduced (transients shaved), never increased.
    crest_out = calculate_crest_factor(out)
    assert crest_out <= calculate_crest_factor(x) + 0.1
    # The clipper is wired with a real (below-ceiling) knee threshold.
    assert CLIPPER_HEADROOM_DB > 0.0
