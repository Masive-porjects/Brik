"""TDD tests for the Mix Engine QC report (Paso 07 — quality_checks).

RED → GREEN → REFACTOR contract for ``run_qc_checks``:

* mono/fase reuses the panorama internals (``mono_compat_loss_db`` /
  ``measure_stereo_position``) — no duplicated measurement logic;
* the spectral checks (sibilance 4–7 kHz, muddy 200–300 Hz, honky
  450–600 Hz) flag synthetic signals with excess energy in their band
  and stay quiet on clean signals;
* the "escucha a nivel bajo" (low-level listen) check is implemented as
  the measurable proxies (crest factor + gate activity at −40 dBFS) with
  the derivation documented — a perceptual listen stays human;
* flags are informational: no check raises or blocks (the dict always
  comes back with every check + summary + note).
"""
import sys

sys.path.insert(0, "src")

import numpy as np
import pytest

from audiomind.processing import quality_checks as qc
from audiomind.processing.panorama import (
    MONO_COMPAT_MIN_DB,
    measure_stereo_position,
    mono_compat_loss_db,
)
from audiomind.processing.stereo_imaging import CORRELATION_SAFETY_FLOOR

_SR = 44100

_QC_KEYS = {
    "mono",
    "phase",
    "sibilance_5k",
    "muddy_250",
    "honky_500",
    "low_level_listen",
    "summary",
    "note",
}


def _tone(hz: float, seconds: float = 1.0, amp: float = 0.25,
          sr: int = _SR) -> np.ndarray:
    """A mono float32 sine tone (synthetic fixture, no DSP deps)."""
    t = np.linspace(0.0, seconds, int(sr * seconds), endpoint=False)
    return (amp * np.sin(2.0 * np.pi * hz * t)).astype(np.float32)


def _stereo(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Stack two mono channels into (2, N) float32."""
    return np.stack([left, right], axis=0)


def _white_noise(seconds: float = 1.0, seed: int = 0) -> np.ndarray:
    """Deterministic white noise (flat spectrum — the clean control)."""
    rng = np.random.default_rng(seed)
    n = int(_SR * seconds)
    return (rng.standard_normal(n) * 0.25).astype(np.float32)


class TestMonoPhase:
    """Mono-compat and phase checks reuse the panorama measurement."""

    def test_mono_identical_channels_ok(self):
        """L == R → 0 dB mono loss, mono ok, phase ok (correlation 1)."""
        tone = _tone(440.0)
        bus = _stereo(tone, tone)
        report = qc.run_qc_checks(bus, _SR)
        assert report["mono"]["ok"] is True
        # Same function validate_positions reports with.
        assert report["mono"]["details"]["bus_loss_db"] == pytest.approx(
            mono_compat_loss_db(bus), abs=0.01
        )
        assert report["mono"]["details"]["threshold_db"] == MONO_COMPAT_MIN_DB
        assert report["phase"]["ok"] is True
        assert report["phase"]["details"]["correlation"] == pytest.approx(
            measure_stereo_position(bus)["correlation"], abs=1e-4
        )

    def test_anti_phase_flags_mono_and_phase(self):
        """R = −L → −∞ mono loss (JSON-safe floor) and correlation −1."""
        tone = _tone(440.0)
        bus = _stereo(tone, -tone)
        report = qc.run_qc_checks(bus, _SR)
        assert report["mono"]["ok"] is False
        assert report["mono"]["details"]["bus_loss_db"] <= MONO_COMPAT_MIN_DB
        assert report["phase"]["ok"] is False
        assert report["phase"]["details"]["correlation"] < CORRELATION_SAFETY_FLOOR

    def test_normal_stereo_no_crash(self):
        """A common slightly-decorrelated stereo bus passes both checks."""
        tone = _tone(440.0)
        noise = _white_noise() * 0.05
        bus = _stereo(tone, tone * 0.8 + noise)
        report = qc.run_qc_checks(bus, _SR)
        assert report["mono"]["ok"] is True
        assert report["phase"]["ok"] is True

    def test_mono_input_accepted(self):
        """A mono (N,) bus is trivially compatible (0 dB loss, corr 1)."""
        report = qc.run_qc_checks(_tone(440.0), _SR)
        assert report["mono"]["ok"] is True
        assert report["phase"]["ok"] is True


class TestSpectralChecks:
    """Sibilance / muddy / honky flags on synthetic band excess."""

    def test_sibilance_excess_5k_flags(self):
        """A strong 5.5 kHz tone (equal to the 440 body) flags 4–7 kHz."""
        bus = _stereo(_tone(440.0) + _tone(5500.0),
                      _tone(440.0) + _tone(5500.0))
        report = qc.run_qc_checks(bus, _SR)
        assert report["sibilance_5k"]["ok"] is False
        assert report["sibilance_5k"]["details"]["band_hz"] == [4000.0, 7000.0]

    def test_sibilance_clean_tone_not_flag(self):
        """A 440 tone only → the 4–7 kHz band is silent."""
        bus = _stereo(_tone(440.0), _tone(440.0))
        report = qc.run_qc_checks(bus, _SR)
        assert report["sibilance_5k"]["ok"] is True

    def test_sibilance_white_noise_not_flag(self):
        """Flat noise keeps the 4–7 kHz share below the calibrated flag."""
        bus = _stereo(_white_noise(), _white_noise())
        report = qc.run_qc_checks(bus, _SR)
        assert report["sibilance_5k"]["ok"] is True

    def test_muddy_excess_250_flags(self):
        """A strong 250 Hz tone (equal to the 440 body) flags 200–300 Hz."""
        bus = _stereo(_tone(250.0) + _tone(440.0),
                      _tone(250.0) + _tone(440.0))
        report = qc.run_qc_checks(bus, _SR)
        assert report["muddy_250"]["ok"] is False

    def test_muddy_clean_not_flag(self):
        bus = _stereo(_tone(440.0), _tone(440.0))
        report = qc.run_qc_checks(bus, _SR)
        assert report["muddy_250"]["ok"] is True

    def test_honky_excess_500_flags(self):
        """A strong 520 Hz tone (equal to the 440 body) flags 450–600 Hz."""
        bus = _stereo(_tone(520.0) + _tone(440.0),
                      _tone(520.0) + _tone(440.0))
        report = qc.run_qc_checks(bus, _SR)
        assert report["honky_500"]["ok"] is False

    def test_honky_clean_not_flag(self):
        """A 330 Hz tone (outside 450–600 with real filter margin) is clean."""
        bus = _stereo(_tone(330.0), _tone(330.0))
        report = qc.run_qc_checks(bus, _SR)
        assert report["honky_500"]["ok"] is True


class TestLowLevelListen:
    """The measurable proxies of the plan's "escucha a nivel bajo"."""

    def test_steady_sine_flags_over_smooth_crest(self):
        """A pure sine has crest ≈ 3 dB — below the calibrated 6 dB floor."""
        bus = _stereo(_tone(440.0), _tone(440.0))
        report = qc.run_qc_checks(bus, _SR)
        assert report["low_level_listen"]["ok"] is False
        assert report["low_level_listen"]["details"]["crest_ok"] is False

    def test_sparse_impulses_flag_low_activity(self):
        """Short bursts over silence vanish at a −40 dBFS low listen."""
        t = np.zeros(int(_SR * 1.25), dtype=np.float32)
        burst = _tone(440.0, seconds=0.02, amp=0.5)
        for start in range(0, len(t) - len(burst), int(0.25 * _SR)):
            t[start:start + len(burst)] = burst
        bus = _stereo(t, t)
        report = qc.run_qc_checks(bus, _SR)
        assert report["low_level_listen"]["ok"] is False
        details = report["low_level_listen"]["details"]
        assert details["low_level_activity_ratio"] < 0.5
        assert details["low_level_activity_ok"] is False

    def test_white_noise_low_level_ok(self):
        """Noise crest sits inside [6, 18] dB and activity is ~full."""
        bus = _stereo(_white_noise(), _white_noise())
        report = qc.run_qc_checks(bus, _SR)
        assert report["low_level_listen"]["ok"] is True

    def test_low_level_details_documented(self):
        """The measurable-proxy derivation is explicit in the report."""
        bus = _stereo(_tone(440.0), _tone(440.0))
        details = qc.run_qc_checks(bus, _SR)["low_level_listen"]["details"]
        assert "crest_db" in details
        assert "gate_db" in details
        assert details["gate_db"] == -40.0
        assert "note" in details and details["note"]


class TestReportShape:
    """run_qc_checks always returns the full informational report."""

    def test_report_shape_full_keys(self):
        noise = _white_noise()
        bus = _stereo(noise, noise)
        report = qc.run_qc_checks(bus, _SR)
        assert set(report) == _QC_KEYS
        assert report["note"]
        assert report["summary"]["flagged"] == []
        assert report["summary"]["all_ok"] is True

    def test_summary_lists_flagged_checks(self):
        bus = _stereo(_tone(440.0) + _tone(5500.0),
                      _tone(440.0) + _tone(5500.0))
        report = qc.run_qc_checks(bus, _SR)
        assert report["summary"]["all_ok"] is False
        assert "sibilance_5k" in report["summary"]["flagged"]

    def test_silent_bus_no_crash(self):
        """A silent bus → vacuous ok flags, never a crash or NaN."""
        bus = np.zeros((2, _SR), dtype=np.float32)
        report = qc.run_qc_checks(bus, _SR)
        assert set(report) == _QC_KEYS
        assert report["mono"]["ok"] is True
        assert report["phase"]["ok"] is True
        assert report["low_level_listen"]["ok"] is True

    def test_pan_info_context_included(self):
        """The pan stage's mono_check rides along when given."""
        pan_info = {
            "mono_check": {
                "bus_loss_db": -0.5,
                "mono_compatible": True,
                "anti_phase_stems": [],
            }
        }
        bus = _stereo(_tone(440.0), _tone(440.0))
        report = qc.run_qc_checks(bus, _SR, pan_info=pan_info)
        assert report["pan_stage"]["ok"] is True
        assert report["pan_stage"]["details"]["mono_check"] == pan_info[
            "mono_check"
        ]

    def test_reuses_pan_mono_loss_function(self):
        """The mono check must call the SAME helper validate_positions uses."""
        tone = _tone(440.0)
        bus = _stereo(tone, tone * 0.5)
        expected = mono_compat_loss_db(bus)
        report = qc.run_qc_checks(bus, _SR)
        assert report["mono"]["details"]["bus_loss_db"] == pytest.approx(
            round(expected, 2), abs=1e-6
        )