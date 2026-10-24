"""Tests for the adaptive (program-dependent) compressor (Sprint 8).

These tests import ONLY numpy/scipy and ``audiomind.processing.adaptive_comp``
(plus the shared multiband helpers) — NEVER ``engine``/``pedalboard`` — so they
run on machines where Smart App Control blocks the pedalboard binary.

Acceptance mapping (roadmap): threshold tracks input RMS; GR matches program
crest; null test in bypass; sidechain drives the detector for the first time.
"""

import numpy as np
import pytest

from audiomind.processing.adaptive_comp import (
    AdaptiveCompParams,
    AdaptiveCompressor,
    adaptive_compress,
)

SR = 44100


def _sine(freq: float = 440.0, dur_s: float = 1.0, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(SR * dur_s)) / SR
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def _stereo(x: np.ndarray) -> np.ndarray:
    return np.stack([x, x])


def _rms_db(x: np.ndarray) -> float:
    return float(20.0 * np.log10(np.sqrt(np.mean(x.astype(np.float64) ** 2)) + 1e-12))


class TestNullTest:
    def test_neutral_default_is_bit_exact(self):
        x = _sine()
        y = adaptive_compress(x, SR)
        assert np.array_equal(x, y)

    def test_neutral_stereo_is_bit_exact(self):
        x = _stereo(_sine())
        y = adaptive_compress(x, SR)
        assert np.array_equal(x, y)

    def test_neutral_with_knobs_ratio_one_is_bit_exact(self):
        # Ratio 1.0 is the neutral switch: even with aggressive timing
        # knobs the stage must remain a bit-exact no-op.
        x = _stereo(_sine())
        p = AdaptiveCompParams(
            ratio=1.0,
            threshold_offset_db=12.0,
            attack_ms=1.0,
            release_ms=50.0,
            makeup_db=6.0,
        )
        y = AdaptiveCompressor(SR, p).process(x)
        assert np.array_equal(x, y)


class TestThresholdTracksRMS:
    def test_threshold_follows_program_loudness(self):
        # Two segments with different RMS: the threshold must be lower
        # (more negative) in the quiet segment and higher in the loud one —
        # it tracks the input dynamics instead of staying fixed.
        t = np.arange(SR) / SR
        quiet = 0.05 * np.sin(2.0 * np.pi * 220.0 * t)
        loud = 0.5 * np.sin(2.0 * np.pi * 220.0 * t)
        x = np.concatenate([quiet, loud]).astype(np.float32)

        p = AdaptiveCompParams(ratio=3.0, threshold_offset_db=6.0)
        _, diag = AdaptiveCompressor(SR, p).process_with_diagnostics(x)

        half = x.shape[0] // 2
        th_quiet = np.mean(diag["threshold_db"][:half])
        th_loud = np.mean(diag["threshold_db"][half:])
        assert th_loud > th_quiet, (
            f"threshold should track RMS (loud {th_loud:.1f} > quiet "
            f"{th_quiet:.1f})"
        )

    def test_threshold_is_clamped_to_valid_range(self):
        # Offset outside the clamp must land inside [min, max] (roadmap
        # [−30, −4]): a very quiet passage cannot push the threshold below
        # the floor, a loud one cannot push it above the ceiling.
        t = np.arange(SR) / SR
        x = (0.001 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)
        p = AdaptiveCompParams(ratio=4.0, threshold_offset_db=6.0)
        _, diag = AdaptiveCompressor(SR, p).process_with_diagnostics(x)
        assert float(np.min(diag["threshold_db"])) >= p.threshold_min_db
        assert float(np.max(diag["threshold_db"])) <= p.threshold_max_db


class TestGainReductionMatchesCrest:
    @staticmethod
    def _time_to_gr(x: np.ndarray, params: AdaptiveCompParams) -> float:
        _, diag = AdaptiveCompressor(SR, params).process_with_diagnostics(x)
        gr = diag["gr_db"]
        idx = np.where(gr <= -3.0)[0]
        if idx.size == 0:
            return float("inf")
        return idx[0] / SR

    def test_high_crest_attacks_faster_than_low_crest(self):
        # Percussion-like (high crest) must reach −3 dB GR sooner than a
        # pad-like tone (low crest), because the crest-adaptive timing uses
        # a shorter attack for transients.
        t = np.arange(SR) / SR
        # High crest: short loud burst with gaps (sparse percussive hits).
        burst = np.zeros(SR)
        for start in (0, 4410, 8820):
            seg = burst[start : start + 882]
            seg[:] = 0.9 * np.sin(2.0 * np.pi * 1000.0 * np.arange(seg.size) / SR)
        # Low crest: sustained sine at a comparable RMS.
        pad = (0.5 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)
        burst = burst.astype(np.float32)

        p = AdaptiveCompParams(
            ratio=4.0, threshold_offset_db=6.0, attack_ms=5.0, release_ms=100.0,
        )
        t_high = self._time_to_gr(burst, p)
        t_low = self._time_to_gr(pad, p)
        assert t_high < t_low, (
            f"high-crest should reach GR sooner (high {t_high:.3f}s < "
            f"low {t_low:.3f}s)"
        )

    def test_engaged_compression_reduces_peak_to_rms_spread(self):
        # Roadmap acceptance: "GR matches program crest". A repeated
        # high-crest percussion pattern: AFTER the compressor has attacked
        # (past the very first transient, which a lookahead-free ballistics
        # cannot catch), the later hits must come out with REDUCED peaks
        # relative to the input — the transients are being controlled.
        n = int(0.5 * SR)
        _t = np.arange(n) / SR
        hits = np.zeros(n)
        for start in range(0, n, 8820):
            m = min(882, n - start)
            hits[start : start + m] = 0.9 * np.sin(2.0 * np.pi * 1000.0 * np.arange(m) / SR)
        hits = hits.astype(np.float32)

        p = AdaptiveCompParams(ratio=4.0, threshold_offset_db=6.0, attack_ms=3.0)
        y = adaptive_compress(hits, SR, p)

        # Measure over the SECOND hit onward (compressor already hot): the
        # output peaks must be smaller than the input peaks there.
        lo, hi = int(0.2 * SR), int(0.5 * SR)
        in_peak = float(np.max(np.abs(hits[lo:hi])))
        out_peak = float(np.max(np.abs(y[lo:hi])))
        assert out_peak < in_peak, (
            f"post-attack peaks should be reduced (in {in_peak:.3f} > "
            f"out {out_peak:.3f})"
        )

    def test_gr_matches_program_crest(self):
        # Roadmap acceptance: "GR matches program crest". Two programs at a
        # comparable level — a HIGH-crest percussion pattern and a LOW-crest
        # sustained tone. Gain reduction measured over the ACTIVE regions
        # must be stronger (more negative) for the high-crest program.
        t = np.arange(int(0.5 * SR)) / SR
        # High crest: repeated short hits with gaps (sparse, peaky).
        hits = np.zeros(int(0.5 * SR))
        for start in range(0, hits.size, 8820):
            n = min(882, hits.size - start)
            hits[start : start + n] = 0.9 * np.sin(2.0 * np.pi * 1000.0 * np.arange(n) / SR)
        hits = hits.astype(np.float32)
        # Low crest: sustained tone at a similar RMS.
        pad = (0.5 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)

        p = AdaptiveCompParams(ratio=4.0, threshold_offset_db=6.0, attack_ms=3.0)
        _, d_hits = AdaptiveCompressor(SR, p).process_with_diagnostics(hits)
        _, d_pad = AdaptiveCompressor(SR, p).process_with_diagnostics(pad)

        # Mean GR only where the program is actually active (|x| > noise floor).
        def active_mean_gr(x, gr):
            mask = np.abs(x) > 1e-4
            return float(np.mean(gr[mask]))

        gr_hits = active_mean_gr(hits, d_hits["gr_db"])
        gr_pad = active_mean_gr(pad, d_pad["gr_db"])
        assert gr_hits < gr_pad, (
            f"high-crest program should get MORE gain reduction "
            f"(hits {gr_hits:.2f} dB < pad {gr_pad:.2f} dB)"
        )


class TestProgramDependentVsFixed:
    def test_quiet_section_compresses_less_than_loud_section(self):
        # With a FIXED threshold a quiet section would be over-compressed.
        # The program-dependent threshold tracks RMS, so the gain reduction
        # in the quiet section must be smaller (less negative) than in the
        # loud one.
        t = np.arange(SR) / SR
        quiet = 0.05 * np.sin(2.0 * np.pi * 220.0 * t)
        loud = 0.5 * np.sin(2.0 * np.pi * 220.0 * t)
        x = np.concatenate([quiet, loud]).astype(np.float32)

        p = AdaptiveCompParams(ratio=4.0, threshold_offset_db=6.0)
        _, diag = AdaptiveCompressor(SR, p).process_with_diagnostics(x)

        half = x.shape[0] // 2
        gr_quiet = np.mean(diag["gr_db"][:half])
        gr_loud = np.mean(diag["gr_db"][half:])
        assert gr_quiet > gr_loud, (
            f"quiet section should be compressed less "
            f"(quiet {gr_quiet:.1f} dB > loud {gr_loud:.1f} dB)"
        )


class TestSidechain:
    def test_external_sidechain_drives_the_detector(self):
        # A steady program tone with an external drum-like sidechain: gain
        # reduction must occur AT the sidechain peaks and decay to ~0 once
        # the sidechain goes silent, even though the program never changes
        # level.
        t = np.arange(SR) / SR
        program = (0.3 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32)

        # Single sidechain hit in the first 10 ms, silence afterwards.
        side = np.zeros(SR)
        side[:441] = 0.9 * np.sin(2.0 * np.pi * 1000.0 * np.arange(441) / SR)
        side = side.astype(np.float32)

        p = AdaptiveCompParams(ratio=5.0, threshold_offset_db=4.0, attack_ms=3.0)
        y, diag = AdaptiveCompressor(SR, p).process_with_diagnostics(
            program, sidechain=side
        )
        gr = diag["gr_db"]

        # GR during the hit window (attack peak + settle tail), measured well
        # after the attack has ramped in.
        during = np.mean(gr[int(0.02 * SR):int(0.06 * SR)])
        # GR long after the sidechain went silent (release fully recovered).
        late = np.mean(gr[int(0.8 * SR):])
        assert during < late, (
            f"sidechain hit should cause GR, silence should recover "
            f"(during {during:.1f} dB < late {late:.1f} dB)"
        )
        # And the program itself did get compressed at the hit.
        assert not np.array_equal(program, y)


class TestMakeup:
    def test_makeup_raises_output_level(self):
        x = _sine(amp=0.5)
        no_makeup = AdaptiveCompParams(ratio=4.0, threshold_offset_db=6.0, makeup_db=0.0)
        with_makeup = AdaptiveCompParams(
            ratio=4.0, threshold_offset_db=6.0, makeup_db=6.0,
        )
        y0 = adaptive_compress(x, SR, no_makeup)
        y1 = adaptive_compress(x, SR, with_makeup)
        # +6 dB makeup ≈ +6 dB RMS (within release-settling tolerance).
        delta = _rms_db(y1) - _rms_db(y0)
        assert 5.0 < delta < 7.0, f"makeup should add ~6 dB RMS, got {delta:.2f}"

    def test_makeup_never_breaks_null_test(self):
        x = _sine()
        p = AdaptiveCompParams(ratio=1.0, makeup_db=6.0)
        y = adaptive_compress(x, SR, p)
        assert np.array_equal(x, y)


class TestStereoAndRobustness:
    def test_identical_channels_stay_identical(self):
        x = _stereo(_sine(amp=0.4))
        p = AdaptiveCompParams(ratio=4.0, threshold_offset_db=6.0)
        y = AdaptiveCompressor(SR, p).process(x)
        assert np.array_equal(y[0], y[1])

    def test_mono_shape_preserved(self):
        x = _sine()
        p = AdaptiveCompParams(ratio=4.0, threshold_offset_db=6.0)
        y = AdaptiveCompressor(SR, p).process(x)
        assert y.shape == x.shape
        assert y.dtype == x.dtype

    def test_stereo_shape_and_dtype_preserved(self):
        x = _stereo(_sine(amp=0.4))
        p = AdaptiveCompParams(ratio=4.0, threshold_offset_db=6.0)
        y = AdaptiveCompressor(SR, p).process(x)
        assert y.shape == x.shape
        assert y.dtype == x.dtype

    def test_empty_input(self):
        x = np.zeros((2, 0), dtype=np.float32)
        p = AdaptiveCompParams(ratio=4.0)
        y = AdaptiveCompressor(SR, p).process(x)
        assert y.shape == x.shape

    def test_outputs_are_finite(self):
        x = _stereo(_sine(amp=0.5))
        p = AdaptiveCompParams(ratio=4.0, threshold_offset_db=6.0)
        y = AdaptiveCompressor(SR, p).process(x)
        assert np.all(np.isfinite(y))

    def test_deterministic(self):
        x = _stereo(_sine(amp=0.5))
        p = AdaptiveCompParams(ratio=4.0, threshold_offset_db=6.0)
        y1 = AdaptiveCompressor(SR, p).process(x)
        y2 = AdaptiveCompressor(SR, p).process(x)
        assert np.array_equal(y1, y2)


class TestValidation:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"ratio": 0.5},
            {"attack_ms": 0.0},
            {"release_ms": -1.0},
            {"crest_window_ms": 0.0},
            {"threshold_offset_db": 0.0},
            {"threshold_offset_db": -3.0},
            {"threshold_min_db": 0.0, "threshold_max_db": -10.0},
            {"makeup_db": -1.0},
        ],
    )
    def test_invalid_params_raise(self, kwargs):
        with pytest.raises(ValueError):
            AdaptiveCompressor(SR, AdaptiveCompParams(**kwargs))


class TestDiagnostics:
    def test_diagnostics_are_present_and_finite(self):
        x = _sine(amp=0.5)
        p = AdaptiveCompParams(ratio=4.0, threshold_offset_db=6.0)
        _, diag = AdaptiveCompressor(SR, p).process_with_diagnostics(x)
        for key in ("gr_db", "threshold_db", "crest_db", "attack_ms", "release_ms"):
            assert key in diag
            assert np.all(np.isfinite(diag[key]))
        assert np.isfinite(diag["mean_gr_db"])
        assert np.isfinite(diag["mean_threshold_db"])
        assert diag["mean_crest_db"] > 0.0
