"""Objective tests for the LR4 multiband compressor (Sprint 4 acceptance).

Covers: LR4 crossover flat-sum within ±0.05 dB (frequency response null),
per-band gain-reduction isolation, bit-exact bypass in the neutral
configuration, the envelope detector time constants, the soft-knee gain
computer, automatic makeup compensation, stereo image preservation, engine
integration (neutral flag toggle bit-exact; engaged stage changes output),
and the Sprint 4 A/B (per-band GR, makeup, output LUFS/true peak off vs on).
"""
import sys

sys.path.insert(0, "src")

import numpy as np
import pytest
import soundfile as sf
from scipy.signal import sosfreqz

from audiomind.models.audio import MasteringParameters
from audiomind.processing.engine import process_audio
from audiomind.processing.multiband import (
    BandParams,
    LinkwitzRiley4,
    MultibandCompressor,
    MultibandParams,
    detect_envelope,
    gain_computer,
    multiband_compress,
)
from audiomind.processing.truepeak import measure_lufs, measure_true_peak

SR = 44100
F1, F2 = 150.0, 3000.0


def _stereo(mono: np.ndarray) -> np.ndarray:
    return np.stack([mono, mono])


def _engaged_params(index: int, ratio: float = 4.0) -> MultibandParams:
    """Compress only one band (index 0/1/2); the other two stay ratio 1:1."""
    bands = [BandParams(), BandParams(), BandParams()]
    bands[index] = BandParams(
        threshold_db=-20.0, ratio=ratio, knee_db=3.0, attack_ms=1.0, release_ms=50.0
    )
    return MultibandParams(bands=tuple(bands), auto_makeup=False)


def _tone(freq: float, amp: float, dur_s: float = 1.5) -> np.ndarray:
    t = np.arange(int(SR * dur_s)) / SR
    return amp * np.sin(2.0 * np.pi * freq * t)


def _audible_band(f, mag_db):
    mask = (f >= 20.0) & (f <= 18000.0)
    return f[mask], mag_db[mask]


# ── LR4 crossovers ───────────────────────────────────────────────────


def test_lr4_three_band_sum_flat_within_050_db():
    xo = LinkwitzRiley4(SR, F1, F2)
    w, h = sosfreqz(xo.band_sos[0], worN=65536)
    _, h_mid = sosfreqz(xo.band_sos[1], worN=65536)
    _, h_high = sosfreqz(xo.band_sos[2], worN=65536)
    f, mag_db = _audible_band(
        w * SR / (2.0 * np.pi), 20.0 * np.log10(np.abs(h + h_mid + h_high) + 1e-30)
    )
    assert mag_db.max() - mag_db.min() <= 0.05
    assert abs(mag_db.mean()) <= 0.05


def test_lr4_two_way_sum_flat_at_each_edge():
    for fc in (F1, F2):
        xo = LinkwitzRiley4(SR, F1, F2)
        lp = xo._lr4(fc / (SR / 2.0), "low")
        hp = xo._lr4(fc / (SR / 2.0), "high")
        w, h_lp = sosfreqz(lp, worN=65536)
        _, h_hp = sosfreqz(hp, worN=65536)
        f, mag_db = _audible_band(
            w * SR / (2.0 * np.pi),
            20.0 * np.log10(np.abs(h_lp + h_hp) + 1e-30),
        )
        assert mag_db.max() - mag_db.min() <= 0.05
        assert abs(mag_db.mean()) <= 0.05


def test_lr4_time_domain_sum_preserves_power():
    rng = np.random.default_rng(0)
    x = rng.standard_normal((2, int(SR * 2.0))) * 0.3
    bands = LinkwitzRiley4(SR, F1, F2).split(x)
    summed = np.sum(bands, axis=0)
    ratio_db = 20.0 * np.log10(
        np.sqrt(np.mean(summed**2)) / np.sqrt(np.mean(x**2)) + 1e-30
    )
    assert abs(ratio_db) <= 0.05


def test_invalid_crossovers_raise():
    with pytest.raises(ValueError):
        LinkwitzRiley4(SR, F2, F1)  # low >= high
    with pytest.raises(ValueError):
        LinkwitzRiley4(SR, F1, SR)  # high >= nyquist


# ── Envelope detector ────────────────────────────────────────────────


def test_envelope_attack_and_release_time_constants():
    attack_ms, release_ms = 10.0, 200.0
    n = int(SR * 2.0)
    step = np.zeros(n)
    step[int(SR * 0.5):] = 1.0
    env = detect_envelope(step, SR, attack_ms, release_ms)

    idx = int(SR * 0.5)
    final = float(env[-1])
    target = 0.6321 * final
    rise = int(np.where(env[idx:] >= target)[0][0]) / SR
    assert 0.7 * attack_ms * 1e-3 <= rise <= 1.3 * attack_ms * 1e-3

    step = np.ones(n)
    step[int(SR * 1.5):] = 0.0
    env = detect_envelope(step, SR, attack_ms, release_ms)
    idx = int(SR * 1.5)
    base = float(env[idx])
    target = base * np.exp(-1.0)
    fall = int(np.where(env[idx:] <= target)[0][0]) / SR
    assert 0.7 * release_ms * 1e-3 <= fall <= 1.3 * release_ms * 1e-3


def test_envelope_tracks_constant_level():
    x = np.full(int(SR * 0.5), 0.5)
    env = detect_envelope(x, SR, attack_ms=5.0, release_ms=5.0)
    assert abs(float(env[-1]) - 0.5) < 1e-3


# ── Gain computer ────────────────────────────────────────────────────


def test_gain_computer_soft_knee_curve():
    thr, ratio, knee = -20.0, 4.0, 6.0
    levels = np.linspace(-60.0, 0.0, 2001)
    g = gain_computer(levels, thr, ratio, knee)
    gr = g - levels

    below = levels < thr - knee / 2.0
    hard = levels > thr + knee / 2.0
    assert np.all(gr[below] == 0.0)
    expected = thr + (levels[hard] - thr) / ratio
    assert np.allclose(g[hard], expected, atol=1e-12)
    # monotone non-decreasing output, no expansion anywhere
    assert np.all(np.diff(g) >= -1e-9)
    assert np.all(gr <= 1e-12)


def test_gain_computer_hard_knee():
    thr, ratio = -20.0, 4.0
    x = np.array([-40.0, -22.0, -20.0, -10.0, 0.0])
    g = gain_computer(x, thr, ratio, knee_db=0.0)
    above = x > thr
    assert np.allclose(g[above], thr + (x[above] - thr) / ratio, atol=1e-12)
    assert np.all(g[~above] == x[~above])


def test_gain_computer_ratio_one_is_exact_identity():
    x = np.array([-60.0, -30.0, -20.0, -6.0, -1.0])
    assert np.array_equal(gain_computer(x, -20.0, 1.0, 6.0), x)


# ── Neutral bypass ───────────────────────────────────────────────────


def test_neutral_ratio_is_bit_exact_bypass():
    rng = np.random.default_rng(0)
    x = (rng.standard_normal((2, int(SR * 0.5))) * 0.3).astype(np.float32)
    assert np.array_equal(multiband_compress(x, SR), x)
    assert np.array_equal(MultibandCompressor(SR, MultibandParams()).process(x), x)


# ── Per-band gain-reduction isolation ────────────────────────────────


def test_per_band_gain_reduction_isolated():
    for freq, index in ((60.0, 0), (1000.0, 1), (8000.0, 2)):
        x = _stereo(_tone(freq, 0.5))
        _, diag = MultibandCompressor(SR, _engaged_params(index)).process_with_diagnostics(x)
        for i, gr in enumerate(diag["gr_mean_db"]):
            if i == index:
                assert gr < -6.0, f"{freq} Hz must trigger band {i} (GR {gr:.2f} dB)"
            else:
                assert abs(gr) < 0.5, (
                    f"{freq} Hz leaked {gr:.2f} dB of GR into band {i}"
                )


# ── Makeup ───────────────────────────────────────────────────────────


def test_auto_makeup_compensates_mean_gain_reduction():
    x = _stereo(_tone(60.0, 0.5))
    params = MultibandParams(
        bands=(
            BandParams(threshold_db=-20.0, ratio=4.0, knee_db=3.0,
                       attack_ms=1.0, release_ms=50.0),
            BandParams(),
            BandParams(),
        ),
        auto_makeup=True,
    )
    _, diag = MultibandCompressor(SR, params).process_with_diagnostics(x)
    assert diag["gr_mean_db"][0] < -6.0
    assert diag["makeup_db"][0] > 0.0
    # Exact rule: makeup_db == -mean(GR_db)
    assert abs(diag["makeup_db"][0] + diag["gr_mean_db"][0]) < 1e-9
    assert abs(diag["gr_mean_db"][1]) < 0.5
    assert diag["makeup_db"][1] == 0.0


# ── Stereo ───────────────────────────────────────────────────────────


def test_stereo_joint_detection_preserves_image():
    mono = _tone(1000.0, 0.5)
    x = _stereo(mono)
    comp = MultibandCompressor(SR, _engaged_params(1))
    out = comp.process(x)
    assert np.array_equal(out[0], out[1])  # identical channels stay identical

    # content in a single channel still engages the joint (L+R)/2 detector
    x_left = np.stack([mono, np.zeros_like(mono)])
    _, diag = comp.process_with_diagnostics(x_left)
    assert diag["gr_mean_db"][1] < -3.0


def test_stereo_correlation_not_collapsed():
    rng = np.random.default_rng(0)
    n = int(SR * 1.0)
    left = 0.3 * rng.standard_normal(n)
    right = 0.25 * rng.standard_normal(n)
    x = np.stack([left, right])
    out = MultibandCompressor(SR, _engaged_params(1)).process(x)
    corr_in = np.corrcoef(left, right)[0, 1]
    corr_out = np.corrcoef(out[0], out[1])[0, 1]
    assert corr_out >= corr_in - 0.02


# ── Engine integration ───────────────────────────────────────────────


def _program(dur_s: float = 1.0):
    n = int(SR * dur_s)
    t = np.arange(n) / SR
    rng = np.random.default_rng(1)
    mono = (
        0.3 * np.sin(2.0 * np.pi * 120.0 * t)
        + 0.2 * np.sin(2.0 * np.pi * 1000.0 * t)
        + 0.15 * np.sin(2.0 * np.pi * 8000.0 * t)
        + 0.05 * rng.standard_normal(n)
    )
    return _stereo(mono / np.max(np.abs(mono)))


def test_engine_neutral_flag_toggle_is_bit_exact(tmp_path):
    x = _program()
    in_path = tmp_path / "in.wav"
    out_off = tmp_path / "out_off.wav"
    out_on = tmp_path / "out_on.wav"
    sf.write(str(in_path), x.T, SR, subtype="FLOAT")

    # Neutral = bypass contract: MasteringParameters() is a bit-exact bypass, so
    # the global fast-path makes a full-default run return the input untouched
    # while the multiband-flag run processes the whole chain. To validate that
    # toggling ONLY the neutral multiband flag is bit-exact, both runs share a
    # minimally non-default baseline that engages the same processing chain, and
    # the "on" side adds only the flag with all-neutral (ratio 1.0) module params.
    base = MasteringParameters(target_lufs_db=-14.0)
    process_audio(in_path, out_off, base)
    process_audio(in_path, out_on, base.model_copy(update={"multiband_enabled": True}))

    a, _ = sf.read(str(out_off), always_2d=True)
    b, _ = sf.read(str(out_on), always_2d=True)
    assert a.shape == b.shape
    assert np.array_equal(a, b)


def test_engine_multiband_engaged_changes_output(tmp_path):
    x = _program()
    in_path = tmp_path / "in.wav"
    out_off = tmp_path / "out_off.wav"
    out_on = tmp_path / "out_on.wav"
    sf.write(str(in_path), x.T, SR, subtype="FLOAT")

    # Neutral = bypass contract: MasteringParameters() would bypass the whole
    # chain. Use a shared minimally non-default baseline so both runs process
    # the same chain; they differ ONLY by the aggressive multiband stage.
    base = MasteringParameters(target_lufs_db=-14.0)
    off = base
    on = base.model_copy(
        update={
            "multiband_enabled": True,
            "multiband_low_ratio": 3.0,
            "multiband_mid_ratio": 2.0,
            "multiband_high_ratio": 2.5,
            "multiband_low_threshold_db": -20.0,
            "multiband_mid_threshold_db": -20.0,
            "multiband_high_threshold_db": -20.0,
        }
    )
    m_off = process_audio(in_path, out_off, off)
    m_on = process_audio(in_path, out_on, on)

    a, _ = sf.read(str(out_off), always_2d=True)
    b, _ = sf.read(str(out_on), always_2d=True)
    assert not np.array_equal(a, b)  # engaged stage actually does something
    assert np.isfinite(m_on["integrated_lufs"])
    assert np.isfinite(m_on["true_peak_db"])
    # Both runs target the same loudness (-14 LUFS) and differ only in the
    # multiband stage, whose auto-makeup preserves loudness, so the master
    # LUFS must stay within ±3 dB between off/on.
    assert abs(m_on["integrated_lufs"] - m_off["integrated_lufs"]) < 3.0


# ── A/B vs previous sprint ───────────────────────────────────────────


def test_ab_multiband_on_vs_off_metrics():
    """A/B on a synthetic 3-band program: report per-band GR, makeup gain,
    and output LUFS / true peak with the multiband off vs on."""
    n = int(SR * 2.0)
    t = np.arange(n) / SR
    bass = 0.8 * np.sin(2.0 * np.pi * 60.0 * t)
    mid = 0.6 * np.sin(2.0 * np.pi * 1000.0 * t)
    hi = 0.5 * np.sin(2.0 * np.pi * 8000.0 * t)
    prog = (bass + mid + hi) / np.max(np.abs(bass + mid + hi)) * 0.9
    x = _stereo(prog)

    params = MultibandParams(
        bands=(
            BandParams(threshold_db=-20.0, ratio=3.0, knee_db=6.0),
            BandParams(threshold_db=-20.0, ratio=2.5, knee_db=6.0),
            BandParams(threshold_db=-20.0, ratio=2.0, knee_db=6.0),
        ),
        auto_makeup=True,
    )
    off = x
    on, diag = MultibandCompressor(SR, params).process_with_diagnostics(x)

    lufs_off = measure_lufs(off, SR)
    lufs_on = measure_lufs(on, SR)
    tp_off = measure_true_peak(off, SR)
    tp_on = measure_true_peak(on, SR)

    print("A/B multiband on vs off (3-band program)")
    for name, gr, mu in zip(
        ("low", "mid", "high"), diag["gr_mean_db"], diag["makeup_db"], strict=False
    ):
        print(f"  {name:>4}: GR mean {gr:7.2f} dB   makeup {mu:7.2f} dB")
    print(f"  LUFS: off {lufs_off:7.2f}  on {lufs_on:7.2f}  (delta {lufs_on - lufs_off:+.2f})")
    print(f"  true peak: off {tp_off:7.2f}  on {tp_on:7.2f}  (delta {tp_on - tp_off:+.2f})")

    # all three bands engage
    assert all(gr < -1.5 for gr in diag["gr_mean_db"])
    # makeup compensates the reduction, never amplifies it away
    assert all(mu > 0.0 for mu in diag["makeup_db"])
    # loudness returns near the input level thanks to makeup
    assert abs(lufs_on - lufs_off) < 1.5
    # any true-peak overshoot is bounded by the makeup budget (the engine's
    # downstream LUFS/limiter stages enforce the actual ceiling)
    assert tp_on - tp_off < max(diag["makeup_db"]) + 0.5


# ── API robustness ───────────────────────────────────────────────────


def test_mono_and_empty_inputs():
    mono = np.zeros(int(SR * 0.2))
    assert multiband_compress(mono, SR).shape == mono.shape
    empty = np.zeros((2, 0))
    assert multiband_compress(empty, SR).shape == empty.shape
    out = MultibandCompressor(SR, _engaged_params(0)).process(mono)
    assert out.shape == mono.shape


def test_shape_and_dtype_preserved():
    x = np.random.default_rng(0).standard_normal((2, int(SR * 0.5))).astype(np.float32)
    x /= np.max(np.abs(x))
    out = MultibandCompressor(SR, _engaged_params(0)).process(x)
    assert out.shape == x.shape
    assert out.dtype == x.dtype
    assert np.all(np.isfinite(out))
