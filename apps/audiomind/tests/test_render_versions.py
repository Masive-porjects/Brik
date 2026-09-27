"""TDD tests for the Mix Engine versions renderer (Paso 07).

RED → GREEN → REFACTOR contract for ``render_version_buses``:

* the five versions share the SAME processed stems — only the vocals
  trim differs (pre-bus-compression sums are exact linear combinations);
* ``principal`` equals the plain 1:1 pad sum (trim 0.0 — the byte-exact
  identity the Paso 06 path relies on);
* ``instrumental``/``tv_mix`` silence the vocals (identical arrays) and
  keep every other stem untouched;
* ``vocal_up``/``vocal_down`` scale ONLY the vocals residual by
  ``10**(±0.75/20)``.
"""
import sys

sys.path.insert(0, "src")

import numpy as np
import pytest

from audiomind.processing.render_versions import (
    VERSION_DESCRIPTIONS,
    VERSION_TRIMS_DB,
    render_version_buses,
    version_trim_gain,
)
from audiomind.processing.splitter import STEM_NAMES

_SR = 44100

# (hz, seconds) — vocals longest, mirroring the test_mix_engine fixture.
_STEM_SPECS = {
    "drums": (120.0, 0.75),
    "bass": (90.0, 1.0),
    "other": (330.0, 1.0),
    "vocals": (440.0, 1.25),
}


def _build_stems() -> dict[str, np.ndarray]:
    """Deterministic stereo stems (L == R), one pure tone each."""
    stems: dict[str, np.ndarray] = {}
    for name, (hz, seconds) in _STEM_SPECS.items():
        t = np.linspace(0.0, seconds, int(_SR * seconds), endpoint=False)
        tone = (0.25 * np.sin(2.0 * np.pi * hz * t)).astype(np.float32)
        stems[name] = np.stack([tone, tone], axis=0)
    return stems


def _pad_sum(stems: dict[str, np.ndarray],
             names: list[str] | None = None) -> np.ndarray:
    """Reference 1:1 pad sum.

    Mirrors build_mix's own summing loop: the bus always spans the FULL
    duration (the longest stem — vocals), even when a subset of names is
    summed (versions keep the full timeline; missing stems are leading
    zeros only at the tail).
    """
    full_len = max(stem.shape[1] for stem in stems.values())
    names = STEM_NAMES if names is None else names
    bus = np.zeros((2, full_len), dtype=np.float32)
    for name in names:
        audio = stems[name]
        bus[:, : audio.shape[1]] += audio
    return bus


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x.astype(np.float64)))))


class TestVersionTrimsTable:
    def test_trim_values_match_plan(self):
        """Spec: principal 0, vocal ±0.75, instrumental/tv_mix silent."""
        assert VERSION_TRIMS_DB == {
            "principal": 0.0,
            "vocal_up": 0.75,
            "vocal_down": -0.75,
            "instrumental": None,
            "tv_mix": None,
        }

    def test_gain_identity_at_zero(self):
        assert version_trim_gain(0.0) == 1.0
        assert version_trim_gain(0.75) == pytest.approx(10 ** (0.75 / 20))
        assert version_trim_gain(-0.75) == pytest.approx(10 ** (-0.75 / 20))
        assert version_trim_gain(None) == 0.0

    def test_descriptions_present(self):
        assert set(VERSION_DESCRIPTIONS) == set(VERSION_TRIMS_DB)
        for description in VERSION_DESCRIPTIONS.values():
            assert description


class TestRenderVersionBuses:
    def test_returns_all_five_versions(self):
        buses = render_version_buses(_build_stems())
        assert set(buses) == set(VERSION_TRIMS_DB)

    def test_principal_equals_plain_sum(self):
        """Trim 0.0 → the exact Paso 06 pad sum (same loop, same bits)."""
        stems = _build_stems()
        buses = render_version_buses(stems)
        np.testing.assert_allclose(
            buses["principal"], _pad_sum(stems), rtol=1e-6, atol=0.0
        )

    def test_instrumental_equals_non_vocal_sum(self):
        stems = _build_stems()
        buses = render_version_buses(stems)
        expected = _pad_sum(stems, names=[n for n in STEM_NAMES if n != "vocals"])
        np.testing.assert_allclose(
            buses["instrumental"], expected, rtol=1e-6, atol=0.0
        )

    def test_tv_mix_identical_to_instrumental(self):
        """No-vocals renders share the exact same audio for this engine."""
        buses = render_version_buses(_build_stems())
        assert np.array_equal(buses["tv_mix"], buses["instrumental"])

    def test_all_versions_same_length(self):
        """Every version delivers the full bus duration (padded)."""
        buses = render_version_buses(_build_stems())
        lengths = {name: int(bus.shape[1]) for name, bus in buses.items()}
        assert len(set(lengths.values())) == 1

    def test_vocal_up_scales_only_vocals_residual(self):
        """up / principal residual ratio == 10**(+0.75/20)."""
        stems = _build_stems()
        buses = render_version_buses(stems)
        vocal = stems["vocals"]
        residual_p = buses["principal"] - buses["instrumental"]
        residual_up = buses["vocal_up"] - buses["instrumental"]
        expected_gain = 10 ** (0.75 / 20)
        assert _rms(residual_up) == pytest.approx(
            _rms(residual_p) * expected_gain, rel=1e-3
        )
        # And the difference is exactly the trimmed vocals region.
        vocal_len = vocal.shape[1]
        np.testing.assert_allclose(
            residual_up[:, :vocal_len] - residual_p[:, :vocal_len],
            vocal * (expected_gain - 1.0),
            rtol=1e-5,
            atol=1e-7,
        )

    def test_vocal_down_scales_only_vocals_residual(self):
        stems = _build_stems()
        buses = render_version_buses(stems)
        residual_p = buses["principal"] - buses["instrumental"]
        residual_down = buses["vocal_down"] - buses["instrumental"]
        expected_gain = 10 ** (-0.75 / 20)
        assert _rms(residual_down) == pytest.approx(
            _rms(residual_p) * expected_gain, rel=1e-3
        )

    def test_non_vocal_stems_untouched_across_versions(self):
        """Only the vocals residual changes between versions (exact math).

        ``principal - instrumental`` is the exact full-timeline vocals
        residual (instrumental = the no-vocals sum); each version must be
        exactly ``instrumental + gain * residual`` — same length, no other
        stem moved.
        """
        stems = _build_stems()
        buses = render_version_buses(stems)
        vocals_residual = buses["principal"] - buses["instrumental"]
        gains = {
            "principal": 1.0,
            "vocal_up": 10 ** (0.75 / 20),
            "vocal_down": 10 ** (-0.75 / 20),
            "instrumental": 0.0,
            "tv_mix": 0.0,
        }
        for name in VERSION_TRIMS_DB:
            expected = buses["instrumental"] + gains[name] * vocals_residual
            np.testing.assert_allclose(
                buses[name], expected, rtol=1e-6, atol=0.0
            )

    def test_silent_vocals_stem_no_crash(self):
        stems = _build_stems()
        stems["vocals"] = np.zeros_like(stems["vocals"])
        buses = render_version_buses(stems)
        for name in VERSION_TRIMS_DB:
            np.testing.assert_allclose(
                buses[name], buses["principal"], rtol=1e-6, atol=0.0
            )

    def test_missing_vocals_stem_fails_loudly(self):
        stems = _build_stems()
        del stems["vocals"]
        with pytest.raises(ValueError):
            render_version_buses(stems)