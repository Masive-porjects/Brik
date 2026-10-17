"""P2 suite for the native texture generators.

See ``odd/tasks/texture-modulation-dsp.md`` (specs S1-S5) for every threshold and the
measurement it came from.

Written RED-first, before ``audiomind.processing.texture`` existed, so RED here is a
collection error rather than an assertion failure. That is weaker than phase 1's
staged-bodies RED, and it is compensated the same way phase 1 compensated: every
expected number below was measured on an INDEPENDENT implementation before the module
was written (probes 1-3), so the assertions describe measured behaviour rather than the
module's current output.

Measured before implementation:
  pink slope, 8 seeds          mean -2.978 dB/oct, max |dev| 0.053 from -3.0103
  pink level                   -48.000000 dBFS for a -48 target
  crackle Poisson, 200 seeds   mean 119.11 vs 120 expected, std 11.36 vs 10.95
  crackle one realization      98.01 % of samples exactly zero, crest 34.63 dB
  stereo spread                side/mid exactly 0.1000 and 0.3000; correlation
                               0.9802 and 0.8349; (L+R)/2 bitwise == mid
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy.signal import welch

from audiomind.processing.texture import (
    CRACKLE_LEVEL_DBFS,
    HISS_LEVEL_DBFS,
    MAX_STEREO_SPREAD,
    PINK_SLOPE_DB_PER_OCTAVE,
    SLOPE_TOLERANCE_DB_PER_OCTAVE,
    crackle,
    pink_hiss,
    stereo_bed,
)

SR = 22050
SLOPE_F_LO_HZ = 125.0
SLOPE_F_HI_HZ = 4000.0
SEED = 20261016


def _octave_levels(x: np.ndarray, sr: int, f_lo: float, f_hi: float):
    """Octave-band power levels via Welch, for the pink-noise slope fit.

    The fit band starts well above ``HISS_LOW_CUT_HZ`` so the high-pass that
    protects headroom cannot bend the slope it is measured against.
    """
    freqs, psd = welch(x, fs=sr, nperseg=8192)
    centers: list[float] = []
    levels: list[float] = []
    low = f_lo
    while low * 2.0 <= f_hi:
        high = low * 2.0
        mask = (freqs >= low) & (freqs < high)
        if mask.any():
            centers.append(float(np.sqrt(low * high)))
            levels.append(10.0 * np.log10(float(np.mean(psd[mask])) + 1e-30))
        low = high
    return np.asarray(centers), np.asarray(levels)


def _spectral_slope(centers: np.ndarray, levels: np.ndarray) -> float:
    """Least-squares dB-per-octave slope of the octave-band levels."""
    log_f = np.log2(centers)
    design = np.vstack([log_f, np.ones_like(log_f)]).T
    slope, _ = np.linalg.lstsq(design, levels, rcond=None)[0]
    return float(slope)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))))


def _burst_count(bed: np.ndarray) -> int:
    """Number of crackle events, counted as nonzero runs.

    The bed is sparse enough (98 % exact zeros) that bursts almost never touch,
    so a run count recovers the Poisson event count from the audio alone.
    """
    nonzero = bed != 0.0
    starts = nonzero & np.concatenate([[True], ~nonzero[:-1]])
    return int(np.count_nonzero(starts))


class TestPinkHiss:
    """S1 and S5: slope, level, determinism, no DC."""

    def test_slope_is_minus_three_db_per_octave(self):
        hiss = pink_hiss(SR * 8, SR, seed=SEED)
        centers, levels = _octave_levels(hiss, SR, SLOPE_F_LO_HZ, SLOPE_F_HI_HZ)
        slope = _spectral_slope(centers, levels)
        assert np.isfinite(slope)
        assert abs(slope - PINK_SLOPE_DB_PER_OCTAVE) <= SLOPE_TOLERANCE_DB_PER_OCTAVE

    def test_slope_holds_across_seeds(self):
        """One lucky draw is not a spectrum: four independent seeds must agree."""
        for offset in range(4):
            hiss = pink_hiss(SR * 8, SR, seed=SEED + offset)
            centers, levels = _octave_levels(hiss, SR, SLOPE_F_LO_HZ, SLOPE_F_HI_HZ)
            slope = _spectral_slope(centers, levels)
            assert (
                abs(slope - PINK_SLOPE_DB_PER_OCTAVE) <= SLOPE_TOLERANCE_DB_PER_OCTAVE
            ), f"seed {SEED + offset} gave {slope:.3f} dB/oct"

    def test_slope_is_steeper_than_white_noise(self):
        """A guard against a shaping bug that flattens towards white.

        White noise measures ~0 dB/oct, so a genuine 1/sqrt(f) shaping and a
        broken flat shaping cannot both satisfy this.
        """
        hiss = pink_hiss(SR * 8, SR, seed=SEED)
        centers, levels = _octave_levels(hiss, SR, SLOPE_F_LO_HZ, SLOPE_F_HI_HZ)
        assert _spectral_slope(centers, levels) < -2.0

    def test_rms_matches_the_requested_level(self):
        for level in (HISS_LEVEL_DBFS, -60.0):
            hiss = pink_hiss(SR * 4, SR, seed=SEED, level_dbfs=level)
            assert _rms(hiss) == pytest.approx(10.0 ** (level / 20.0), rel=1e-12)

    def test_has_no_dc_offset(self):
        hiss = pink_hiss(SR * 4, SR, seed=SEED)
        dc_db = 20.0 * np.log10(abs(float(np.mean(hiss))) / _rms(hiss) + 1e-30)
        assert dc_db < -60.0

    def test_is_deterministic_and_seed_dependent(self):
        first = pink_hiss(SR * 2, SR, seed=SEED)
        again = pink_hiss(SR * 2, SR, seed=SEED)
        other = pink_hiss(SR * 2, SR, seed=SEED + 1)
        assert np.array_equal(first, again)
        assert not np.array_equal(first, other)

    def test_returns_the_declared_dtype_and_shape(self):
        hiss = pink_hiss(4096, SR, seed=SEED)
        assert hiss.shape == (4096,)
        assert hiss.dtype == np.float64

    def test_zero_length_is_allowed(self):
        assert pink_hiss(0, SR, seed=SEED).shape == (0,)


class TestCrackle:
    """S2 and S5: Poisson arrivals, sparsity, the rate-0 contract, determinism."""

    def test_events_follow_a_poisson_process(self):
        """Both moments of a Poisson count, not just the mean.

        A uniform scatter with the right mean would pass a mean-only assertion
        and fail this one, because its variance would be ~0 instead of rate*T.
        """
        rate, seconds, trials = 12.0, 10.0, 100
        expected = rate * seconds
        sigma = float(np.sqrt(expected))
        counts = np.array(
            [
                _burst_count(crackle(int(SR * seconds), SR, seed=seed, rate_per_s=rate))
                for seed in range(trials)
            ],
            dtype=np.float64,
        )
        assert abs(float(np.mean(counts)) - expected) <= 0.10 * expected
        assert abs(float(np.std(counts)) - sigma) <= 0.30 * sigma

    def test_is_sparse(self):
        bed = crackle(SR * 10, SR, seed=SEED, rate_per_s=12.0)
        assert float(np.mean(bed == 0.0)) >= 0.90

    def test_stays_well_below_full_scale(self):
        bed = crackle(SR * 10, SR, seed=SEED, rate_per_s=12.0)
        assert float(np.max(np.abs(bed))) < 0.9

    def test_rate_zero_is_exactly_silent(self):
        bed = crackle(4096, SR, seed=SEED, rate_per_s=0.0)
        assert bed.shape == (4096,)
        assert bool(np.all(bed == 0.0))

    def test_negative_rate_is_rejected(self):
        with pytest.raises(ValueError, match="rate_per_s"):
            crackle(4096, SR, seed=SEED, rate_per_s=-1.0)

    def test_rms_matches_the_requested_level(self):
        bed = crackle(SR * 10, SR, seed=SEED, rate_per_s=12.0)
        assert _rms(bed) == pytest.approx(
            10.0 ** (CRACKLE_LEVEL_DBFS / 20.0), rel=1e-12
        )

    def test_is_deterministic_and_seed_dependent(self):
        first = crackle(SR * 4, SR, seed=SEED, rate_per_s=12.0)
        again = crackle(SR * 4, SR, seed=SEED, rate_per_s=12.0)
        other = crackle(SR * 4, SR, seed=SEED + 1, rate_per_s=12.0)
        assert np.array_equal(first, again)
        assert not np.array_equal(first, other)


class TestStereoBed:
    """S3: the spread ratio, the phase guarantee, and the ceiling."""

    @pytest.mark.parametrize("spread", [0.1, 0.3])
    def test_side_to_mid_ratio_is_exactly_the_spread(self, spread):
        mono = pink_hiss(SR * 4, SR, seed=SEED)
        bed = stereo_bed(mono, spread=spread, seed=SEED)
        mid = 0.5 * (bed[0] + bed[1])
        side = 0.5 * (bed[0] - bed[1])
        assert bed.shape == (2, mono.shape[-1])
        assert _rms(side) / _rms(mid) == pytest.approx(spread, abs=1e-9)

    @pytest.mark.parametrize("spread", [0.1, 0.3])
    def test_correlation_matches_the_analytic_spread(self, spread):
        """A second, independent check on the same construction.

        M/S with side/mid ratio s has correlation (1 - s^2)/(1 + s^2), measured
        at 0.9802 for 0.1 and 0.8349 for 0.3. A construction that scattered the
        channels independently would land near 0 here.
        """
        mono = pink_hiss(SR * 4, SR, seed=SEED)
        bed = stereo_bed(mono, spread=spread, seed=SEED)
        expected = (1.0 - spread**2) / (1.0 + spread**2)
        assert float(np.corrcoef(bed[0], bed[1])[0, 1]) == pytest.approx(
            expected, abs=1e-3
        )

    def test_side_is_independent_of_the_bed(self):
        """The width must not be a filtered copy of the material it widens.

        The natural call passes one seed for the whole bed. Drawing the side from
        that same stream measured ``|corr(mono, side)|`` 0.7373 and pulled the L/R
        correlation to 0.9908 where the construction promises 0.9802, so the side
        comes from a derived stream instead.
        """
        mono = pink_hiss(SR * 4, SR, seed=SEED)
        bed = stereo_bed(mono, spread=0.3, seed=SEED)
        side = 0.5 * (bed[0] - bed[1])
        assert abs(float(np.corrcoef(mono, side)[0, 1])) < 0.05

    def test_mono_fold_down_is_lossless(self):
        """The phase guarantee that the whole ceiling exists for."""
        mono = pink_hiss(SR * 4, SR, seed=SEED)
        bed = stereo_bed(mono, spread=MAX_STEREO_SPREAD, seed=SEED)
        folded = 0.5 * (bed[0] + bed[1])
        assert np.allclose(folded, mono, rtol=0.0, atol=1e-12)
        assert 20.0 * np.log10(_rms(folded) / _rms(mono)) == pytest.approx(
            0.0, abs=1e-6
        )

    def test_zero_spread_is_bit_identical_channels(self):
        mono = pink_hiss(SR * 2, SR, seed=SEED)
        bed = stereo_bed(mono, spread=0.0, seed=SEED)
        assert np.array_equal(bed[0], bed[1])
        assert np.array_equal(bed[0], mono)

    def test_rejects_spread_above_the_ceiling(self):
        mono = pink_hiss(1024, SR, seed=SEED)
        with pytest.raises(ValueError, match="spread"):
            stereo_bed(mono, spread=MAX_STEREO_SPREAD + 1e-6, seed=SEED)

    def test_rejects_negative_spread(self):
        mono = pink_hiss(1024, SR, seed=SEED)
        with pytest.raises(ValueError, match="spread"):
            stereo_bed(mono, spread=-0.01, seed=SEED)

    def test_rejects_a_non_1d_bed(self):
        """A 2-D input would otherwise be flattened into a 3-D stack."""
        with pytest.raises(ValueError, match="1-D"):
            stereo_bed(np.zeros((2, 16)), spread=0.1, seed=SEED)

    def test_is_deterministic_and_seed_dependent(self):
        mono = pink_hiss(SR * 2, SR, seed=SEED)
        first = stereo_bed(mono, spread=0.2, seed=SEED)
        again = stereo_bed(mono, spread=0.2, seed=SEED)
        other = stereo_bed(mono, spread=0.2, seed=SEED + 1)
        assert np.array_equal(first, again)
        assert not np.array_equal(first, other)
