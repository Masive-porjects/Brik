"""Objective tests for the 8x true-peak limiter (Sprint 2 acceptance).

Covers: oversampled ceiling enforcement, bit-stable null behavior below
the ceiling, explicit lookahead with length preservation, adaptive
(crest-driven) release, and the already-mastered ceiling bug fix in the
engine.
"""
import sys
sys.path.insert(0, "src")

import numpy as np

from audiomind.processing.engine import _user_limiter_ceiling
from audiomind.processing.truepeak import (
    LOOKAHEAD_MS,
    measure_true_peak,
    true_peak_limit,
)

SR = 44100
CEILING_DB = -1.0


def _stereo(mono: np.ndarray) -> np.ndarray:
    return np.stack([mono, mono])


def _burst_program(amp: float, burst_s: float = 0.05, tail_s: float = 0.5):
    burst = np.sin(2.0 * np.pi * 1000.0 * np.arange(int(SR * burst_s)) / SR)
    tail = np.full(int(SR * tail_s), amp)
    return np.concatenate([burst, tail])


def test_ceiling_enforced_on_oversampled_true_peak():
    burst = _burst_program(1.0)
    out = true_peak_limit(_stereo(burst), SR, ceiling_db=CEILING_DB)

    peak = measure_true_peak(out[:1], SR)
    assert peak <= CEILING_DB + 0.05


def test_impulse_true_peak_stays_below_ceiling():
    mono = np.zeros(int(SR * 0.2))
    mono[int(SR * 0.1)] = 1.0
    out = true_peak_limit(_stereo(mono), SR, ceiling_db=CEILING_DB)

    i0 = int(SR * 0.1)
    peak = measure_true_peak(out[:1, i0 - 500 : i0 + 500], SR)
    assert peak <= CEILING_DB + 0.05


def test_below_ceiling_null_path_is_bit_stable():
    t = np.arange(int(SR * 0.5)) / SR
    mono = 0.25 * np.sin(2.0 * np.pi * 997.0 * t)  # -12 dBFS, far below ceiling
    x = _stereo(mono)
    out = true_peak_limit(x, SR, ceiling_db=CEILING_DB)

    assert np.array_equal(out, x)
    assert np.max(np.abs(out - x)) < 1e-4


def test_lookahead_preserves_length_and_pre_empts_transient():
    n = int(SR * 0.3)
    mono = np.zeros(n)
    ramp_len = int(SR * 0.02)
    t0 = int(SR * 0.1)
    mono[t0 : t0 + ramp_len] = np.linspace(0.0, 1.0, ramp_len)
    out = true_peak_limit(_stereo(mono), SR, ceiling_db=CEILING_DB)

    assert out.shape == _stereo(mono).shape

    ceiling = 10.0 ** (CEILING_DB / 20.0)
    cross = int(np.where(mono >= ceiling)[0][0])
    atten = int(np.where(mono - out[0] > 0.01)[0][0])

    lead_s = (cross - atten) / SR
    assert lead_s >= 2e-3
    assert lead_s <= LOOKAHEAD_MS * 1.5e-3 + 5e-3


def test_adaptive_release_faster_for_percussive_material():
    def t_recover(amp: float) -> float:
        mono = _burst_program(amp)
        out = true_peak_limit(_stereo(mono), SR, ceiling_db=CEILING_DB)
        start = int(SR * (0.05 + 0.002))  # skip downsampling smear at the edge
        gain = out[0, start:] / amp
        idx = np.where(gain >= 0.99)[0]
        return idx[0] / SR if len(idx) else float("inf")

    t_percussive = t_recover(0.2)
    t_tail = t_recover(0.7)

    assert t_percussive < 40e-3
    assert t_tail > 50e-3
    assert t_percussive < t_tail


def test_engine_already_mastered_ceiling_is_lower():
    assert _user_limiter_ceiling(-1.0, True) < _user_limiter_ceiling(-1.0, False)
