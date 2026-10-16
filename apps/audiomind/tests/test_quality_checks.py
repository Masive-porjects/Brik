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
  comes back with every check + summary + note);
* the style carve-out (``budget``) separates SAFETY checks (mono/phase/
  pan_stage — structurally unreachable) from tone/dynamics ones, which a
  declared style may widen by a bounded, reported tolerance. A budget is a
  bounded tolerance, never a blanket pass, and ``budget=None`` is strictly
  neutral.
"""
import json
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


def _sibilant_bus() -> np.ndarray:
    """White-noise body + a 5.5 kHz tone at 80 % amplitude.

    Measured: strict 4–7 kHz ratio ≈ −4.5 dB against the −6 dB flag — a REAL
    miss needing ≈ 1.5 dB of tolerance (so 1.0 dB is not enough and 2.5 dB
    is) — and crest ≈ 13.5 dB, inside the calibrated 6–18 dB window. That
    keeps ``sibilance_5k`` the ONLY flagged check, so the tone-family tests
    stay about the tone family and not about a second, accidental flag.
    """
    body = _white_noise() + _tone(5500.0, amp=0.25 * 0.8)
    return _stereo(body, body)


def _anti_phase_bus() -> np.ndarray:
    """R = −L: mono loss at the JSON-safe floor, correlation −1."""
    tone = _tone(440.0)
    return _stereo(tone, -tone)


def _clean_noise_bus() -> np.ndarray:
    """Identical-channel white noise: every check green on the strict path."""
    noise = _white_noise()
    return _stereo(noise, noise)


def _flat_bus_with_bed(level: float = 0.05) -> np.ndarray:
    """A pure tone plus a small mono white bed.

    Measured crest ≈ 4.5 dB (below the calibrated 6 dB floor) while the
    activity sub-check stays full — the texture-bed signature: the bed moves
    the crest factor without emptying the quiet parts.
    """
    body = _tone(440.0)
    bed = _white_noise(seed=1)
    return _stereo(body + level * bed, body + level * bed)


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


class TestQualityBudget:
    """The style carve-out: a declared, bounded, reported tolerance.

    Family contract: ``safety`` (mono/phase/pan_stage) is structurally
    unreachable through a budget; ``tone``/``dynamics`` may be widened by a
    declared ``relax_db`` capped at ``MAX_QC_RELAX_DB``. The point of the
    whole feature is that the general protection is NOT weakened — a budget
    buys a bounded tolerance, and the raw measurement always stays visible.
    """

    def test_budget_none_is_strictly_neutral(self):
        """No budget → byte-identical strict report, and NO new key anywhere.

        The pre-existing tests encode the strict thresholds and verdicts;
        this pins the extra promise the carve-out must keep: the neutral path
        grows no key of its own (``budget=None`` and the two-argument call
        return exactly the same report).
        """
        for bus in (_sibilant_bus(), _anti_phase_bus(), _clean_noise_bus()):
            strict = qc.run_qc_checks(bus, _SR)
            explicit_none = qc.run_qc_checks(bus, _SR, budget=None)

            assert strict == explicit_none
            assert "intentional_deviations" not in strict["summary"]
            # No relax annotation may leak into the neutral report.
            dumped = json.dumps(strict, sort_keys=True)
            assert "budget" not in dumped
            assert "relax" not in dumped

    def test_tone_budget_tolerates_declared_sibilance(self):
        """A declared budget covers the miss and reports it as intentional."""
        bus = _sibilant_bus()
        strict = qc.run_qc_checks(bus, _SR)
        assert strict["sibilance_5k"]["ok"] is False
        assert strict["summary"]["all_ok"] is False

        relaxed = qc.run_qc_checks(
            bus, _SR, budget={"sibilance_5k": {"relax_db": 2.5}}
        )
        assert relaxed["sibilance_5k"]["ok"] is True
        assert relaxed["summary"]["all_ok"] is True
        assert relaxed["summary"]["flagged"] == []
        assert relaxed["summary"]["intentional_deviations"] == ["sibilance_5k"]

        details = relaxed["sibilance_5k"]["details"]
        # The raw measurement is never hidden, and the standard flag is kept.
        assert details["band_ratio_db"] == (
            strict["sibilance_5k"]["details"]["band_ratio_db"]
        )
        assert details["flag_threshold_standard_db"] == qc.SIBILANCE_FLAG_DB
        assert details["flag_threshold_db"] == pytest.approx(
            qc.SIBILANCE_FLAG_DB + 2.5
        )
        assert details["budget_relax_db"] == 2.5
        assert details["budget_raw_ok"] is False

    def test_tone_budget_is_bounded_not_a_blanket_pass(self):
        """A tolerance smaller than the miss still flags — not immunity."""
        bus = _sibilant_bus()
        relaxed = qc.run_qc_checks(
            bus, _SR, budget={"sibilance_5k": {"relax_db": 1.0}}
        )
        assert relaxed["sibilance_5k"]["ok"] is False
        assert relaxed["summary"]["all_ok"] is False
        assert relaxed["summary"]["flagged"] == ["sibilance_5k"]
        assert relaxed["summary"]["intentional_deviations"] == []
        # The tolerance is declared and visible even when it does not cover.
        assert relaxed["sibilance_5k"]["details"]["budget_relax_db"] == 1.0

    def test_dynamics_budget_widens_the_crest_floor_only(self):
        """The texture-bed case: a bed moves the crest, the floor governs it."""
        bus = _flat_bus_with_bed()
        strict = qc.run_qc_checks(bus, _SR)
        strict_details = strict["low_level_listen"]["details"]
        assert strict["low_level_listen"]["ok"] is False
        assert strict_details["crest_ok"] is False
        assert strict_details["crest_ok_range_db"] == [qc.CREST_OK_MIN_DB, 18.0]
        # The bed FILLS the quiet parts, so the activity sub-check is already
        # ok: the tolerance is spent on the crest floor, not on the minimum.
        assert strict_details["low_level_activity_ok"] is True

        relaxed = qc.run_qc_checks(
            bus, _SR, budget={"low_level_listen": {"relax_db": 2.0}}
        )
        relaxed_details = relaxed["low_level_listen"]["details"]
        assert relaxed["low_level_listen"]["ok"] is True
        assert relaxed["summary"]["intentional_deviations"] == [
            "low_level_listen"
        ]
        assert relaxed_details["crest_ok_range_db"] == [
            qc.CREST_OK_MIN_DB - 2.0,
            18.0,
        ]
        assert relaxed_details["crest_floor_standard_db"] == qc.CREST_OK_MIN_DB
        # The raw crest is unchanged — only the window moved.
        assert relaxed_details["crest_db"] == strict_details["crest_db"]

    def test_safety_checks_are_unreachable_through_a_budget(self):
        """mono / phase / pan_stage raise: the deliverable is never relaxed."""
        for name in ("mono", "phase", "pan_stage"):
            with pytest.raises(ValueError, match="safety"):
                qc.run_qc_checks(
                    _clean_noise_bus(), _SR, budget={name: {"relax_db": 1.0}}
                )

    def test_phase_still_flags_with_a_budget_on_another_check(self):
        """A tone budget cannot rescue a mono/phase violation."""
        relaxed = qc.run_qc_checks(
            _anti_phase_bus(), _SR, budget={"sibilance_5k": {"relax_db": 2.5}}
        )
        assert relaxed["phase"]["ok"] is False
        assert relaxed["mono"]["ok"] is False
        assert relaxed["summary"]["all_ok"] is False
        assert relaxed["summary"]["intentional_deviations"] == []

    def test_budget_over_the_hard_cap_raises(self):
        """The exception is bounded by construction — never silently clamped."""
        bus = _clean_noise_bus()
        with pytest.raises(ValueError, match="MAX_QC_RELAX_DB"):
            qc.run_qc_checks(
                bus,
                _SR,
                budget={"sibilance_5k": {"relax_db": qc.MAX_QC_RELAX_DB + 0.1}},
            )

    @pytest.mark.parametrize(
        "budget",
        [
            pytest.param({"sibilance_5k": {"relax_db": -1.0}}, id="negative"),
            pytest.param(
                {"sibilance_5k": {"relax_db": float("nan")}}, id="nan"
            ),
            pytest.param({"not_a_check": {"relax_db": 1.0}}, id="unknown-check"),
            pytest.param(
                {"sibilance_5k": {"relax_db": 1.0, "extra": 1}}, id="extra-key"
            ),
            pytest.param({"sibilance_5k": 1.0}, id="entry-not-dict"),
            pytest.param(
                {"allowed_intentional": "texture_bed"}, id="provenance-not-list"
            ),
            pytest.param("nope", id="not-a-dict"),
        ],
    )
    def test_malformed_budget_raises(self, budget):
        with pytest.raises(ValueError):
            qc.run_qc_checks(_clean_noise_bus(), _SR, budget=budget)

    def test_texture_bed_mono_impact_is_documented_not_relaxed(self):
        """Why ``mono`` needs no budget: the bed's TOPOLOGY decides the loss.

        Measured on a correlated body with the bed at 30 % (an aggressive,
        deliberately unrealistic level): an identical-channels bed costs
        exactly 0 dB, an equal-power 30 %-spread bed is negligible, and even a
        fully decorrelated bed stays far clear of the −3 dB floor. A texture
        bed is therefore built mono-ish — a safety check is fixed by
        construction, never relaxed.
        """
        body = _tone(440.0)
        left = _white_noise(seed=1)
        right = _white_noise(seed=2)
        level = 0.30
        spread = 0.30
        spread_right = np.sqrt(1.0 - spread**2) * left + spread * right

        mono_bed = mono_compat_loss_db(
            _stereo(body + level * left, body + level * left)
        )
        spread_bed = mono_compat_loss_db(
            _stereo(body + level * left, body + level * spread_right)
        )
        wide_bed = mono_compat_loss_db(
            _stereo(body + level * left, body + level * right)
        )

        assert mono_bed == pytest.approx(0.0, abs=0.01)
        assert spread_bed > -0.25
        assert wide_bed > -1.0
        # The mechanism in order: the more decorrelated the bed, the more it
        # cancels in mono — and all three keep margin on the floor.
        assert mono_bed >= spread_bed >= wide_bed
        for loss_db in (mono_bed, spread_bed, wide_bed):
            assert loss_db >= MONO_COMPAT_MIN_DB

    def test_variant_is_valid_absorbs_the_budget_without_weakening(self):
        """The creative gate reads ``summary.all_ok`` — it needs no change.

        A budgeted deviation is absorbed (the QC layer already reports it as
        ok), while a safety violation still rejects, budget or not.
        """
        from audiomind.processing.creative import variant_is_valid

        pan_ok = {
            "mono_check": {"mono_compatible": True, "anti_phase_stems": []}
        }
        budget = {"sibilance_5k": {"relax_db": 2.5}}

        accepted = qc.run_qc_checks(_sibilant_bus(), _SR, budget=budget)
        assert variant_is_valid(pan_ok, accepted, manual=False) is True

        # The same budget does NOT rescue an anti-phase bus.
        rejected = qc.run_qc_checks(_anti_phase_bus(), _SR, budget=budget)
        assert variant_is_valid(pan_ok, rejected, manual=False) is False

        # And a failing positional check still rejects a fully green QC.
        pan_bad = {
            "mono_check": {"mono_compatible": False, "anti_phase_stems": []}
        }
        assert variant_is_valid(pan_bad, accepted, manual=False) is False