"""TDD tests for role-based panorama + positional validation (Paso 03).

RED → GREEN → REFACTOR contract for the Mix Engine step 03:

* ``PAN_ROLE_PROFILES``: vocals / bass / drums → ``center`` (|balance_db|
  ≤ 3 dB), other (accompaniment) → ``wide`` (|balance_db| ≤ 12 dB — inside
  the extremes, never hard L/R). Drums is the full kit stem: CENTER
  balance role; the width comes from the percussion content.
* ``measure_stereo_position`` reports the M/S position of a ``(2, N)``
  float32 stem BEFORE any correction: ``balance_db = 10*log10(E_R/E_L)``
  (0 centered, + right), Pearson L↔R correlation (1 mono/identical, ~0
  wide, <0 anti-phase) and ``side_to_mid_db = 10*log10(E_side/E_mid)``
  with S=(L−R)/2, M=(L+R)/2. Mono stems ``(N,)`` or ``(1, N)`` are
  centered by definition (balance 0, correlation 1).
* ``pan_law_gains`` implements the constant −3 dB (equal-power) DAW law:
  ``θ = (pan+1)·π/4``, ``L = cos θ``, ``R = sin θ``; pan=0 → −3 dB on
  both channels, pan=±1 → one channel 0 dB, the other ≈0.
* ``apply_role_pan`` only ever applies 0 or 1 correction: gross
  violations are pulled toward the role target (center → 0 dB, wide →
  the 12 dB extreme, NOT the center) with a hard clamp of
  ``max_correction_db = 6 dB``. Stems inside the envelope pass through
  THE SAME array object (bit-exact neutrality). Anti-phase (correlation
  < CORRELATION_SAFETY_FLOOR = −0.1) is never corrected and lands on
  ``human_decision``; wide stems with correlation > 0.98 are flagged
  "sin ancho/pseudo-estéreo" (creating own stereo is a later step).
* ``validate_positions`` returns the corrected stems plus the structured
  ``pan_report`` (roles / stems / mono_check / human_decision) with JSON
  -safe floats — the payload rides ``X-Mix-Result`` via ``json.dumps``.
* ``build_mix`` inserts the pan BEFORE the EQ (DAW chain: fader → pan →
  EQ → compresor → sends); ``pan_profiles=None`` enables the role pan by
  default (Paso 03), ``pan_profiles={}`` keeps the exact Paso 02 routing
  (pan disabled, no ``pan_report`` key).

``split_audio`` is monkeypatched with the same synthetic stand-in as
Paso 01/02 (``tests.test_mix_engine._fake_split``) — its stems are MONO,
which exercises the mono-stem path of the positional validation.
"""
import json
import sys
import uuid

sys.path.insert(0, "src")

import numpy as np
import pytest

import audiomind.processing.mix_engine as mix_engine
from audiomind.processing.magic_frequencies import MAGIC_PROFILES
from audiomind.processing.mix_engine import build_mix
from audiomind.processing.panorama import (
    MONO_COMPAT_MIN_DB,
    PAN_ROLE_PROFILES,
    apply_role_pan,
    measure_stereo_position,
    mono_compat_loss_db,
    pan_law_gains,
    validate_positions,
)
from audiomind.processing.splitter import STEM_NAMES
from tests.test_mix_engine import _fake_split

_SR = 44100
_SECONDS = 0.125
#: Role profile handcrafted for the unit tests (mirrors PAN_ROLE_PROFILES).
_CENTER_PROFILE = {
    "role": "center",
    "target_max_abs_balance_db": 3.0,
    "max_correction_db": 6.0,
}
_WIDE_PROFILE = {
    "role": "wide",
    "target_max_abs_balance_db": 12.0,
    "max_correction_db": 6.0,
}


def _sine(freq: float, amp: float = 0.5) -> np.ndarray:
    """Short float32 sine tone (0.125 s @ 44.1 kHz — integral cycles)."""
    n = int(_SR * _SECONDS)
    t = np.linspace(0.0, _SECONDS, n, endpoint=False)
    return (amp * np.sin(2.0 * np.pi * freq * t)).astype(np.float32)


def _decorrelated_stereo(balance_db: float) -> np.ndarray:
    """Stereo pair with orthogonal channels (correlation ≈ 0) and
    ``E_R/E_L = 10**(balance_db/10)``.

    440 Hz vs 880 Hz are orthogonal over integral cycles, so the pair has
    real width (corr ≈ 0) instead of being a scaled copy (corr = 1) —
    realistic for the "wide" accompaniment role and immune to the
    pseudo-stereo flag.
    """
    ratio = 10.0 ** (balance_db / 20.0)
    return np.stack([_sine(440.0), ratio * _sine(880.0)]).astype(np.float32)


def _centered_stereo() -> np.ndarray:
    """L == R → perfect center: balance 0, correlation 1."""
    s = _sine(440.0)
    return np.stack([s, s]).astype(np.float32)


def _anti_phase_stereo() -> np.ndarray:
    """L == −R → balance 0, correlation −1 (kills the mono downmix)."""
    s = _sine(440.0)
    return np.stack([s, -s]).astype(np.float32)


class TestMeasureStereoPosition:
    """M/S measurement contract (spec §2)."""

    def test_centered_stereo_is_balance_zero_corr_one(self):
        """L == R → balance 0, correlation 1, side energy ~nothing."""
        measured = measure_stereo_position(_centered_stereo())
        assert measured["balance_db"] == pytest.approx(0.0, abs=1e-6)
        assert measured["correlation"] == pytest.approx(1.0, abs=1e-6)
        assert measured["side_to_mid_db"] <= -20.0, (
            "side energy must be very negative for L == R"
        )

    def test_right_heavy_plus_6db(self):
        """R = 2×L → E_R/E_L = 4 → balance ≈ +6.02 dB, corr 1."""
        left = _sine(440.0)
        audio = np.stack([left, 2.0 * left]).astype(np.float32)
        measured = measure_stereo_position(audio)
        assert measured["balance_db"] == pytest.approx(6.02, abs=0.01)
        assert measured["correlation"] == pytest.approx(1.0, abs=1e-6)

    def test_left_heavy_negative_balance(self):
        """L = 2×R → balance ≈ −6.02 dB (sign convention: + is right)."""
        right = _sine(440.0)
        audio = np.stack([2.0 * right, right]).astype(np.float32)
        assert measure_stereo_position(audio)["balance_db"] == pytest.approx(
            -6.02, abs=0.01
        )

    def test_mono_input_is_centered_no_crash(self):
        """Mono stems ``(N,)`` and ``(1, N)`` measure centered."""
        mono_1d = _sine(440.0)
        mono_2d = mono_1d.reshape(1, -1)
        for mono in (mono_1d, mono_2d):
            measured = measure_stereo_position(mono)
            assert measured["balance_db"] == 0.0
            assert measured["correlation"] == 1.0

    def test_rejects_non_stereo_shapes(self):
        """A 3-channel array is not stereo — loud failure, not silent math."""
        with pytest.raises(ValueError):
            measure_stereo_position(np.zeros((3, 64), dtype=np.float32))


class TestPanLaw:
    """Constant −3 dB (equal-power) pan law (spec §4)."""

    def test_center_is_minus_3db_both_channels(self):
        """pan=0 → both gains 0.7071 → −3.01 dB each (equal power)."""
        left, right = pan_law_gains(0.0)
        assert left == pytest.approx(np.sqrt(0.5), abs=1e-9)
        assert right == pytest.approx(np.sqrt(0.5), abs=1e-9)
        assert 20.0 * np.log10(left) == pytest.approx(-3.01, abs=0.01)

    def test_full_right(self):
        """pan=+1 → right 0 dB, left ≈ 0."""
        left, right = pan_law_gains(1.0)
        assert right == pytest.approx(1.0, abs=1e-9)
        assert left == pytest.approx(0.0, abs=1e-9)

    def test_full_left(self):
        """pan=−1 → left 0 dB, right ≈ 0 (mirror of +1)."""
        left, right = pan_law_gains(-1.0)
        assert left == pytest.approx(1.0, abs=1e-9)
        assert right == pytest.approx(0.0, abs=1e-9)

    def test_clamps_out_of_range(self):
        """pan outside [−1, 1] clamps to the extremes."""
        assert pan_law_gains(2.0) == pytest.approx(pan_law_gains(1.0))
        assert pan_law_gains(-3.0) == pytest.approx(pan_law_gains(-1.0))

    def test_constant_power_across_pan(self):
        """L² + R² = 1 for every pan (that is what "constant power" means)."""
        for pan in (-0.75, -0.3, 0.0, 0.35, 0.8):
            left, right = pan_law_gains(pan)
            assert left**2 + right**2 == pytest.approx(1.0, abs=1e-12)


class TestApplyRolePan:
    """0-or-1 correction with the 6 dB clamp (spec §4)."""

    def test_within_envelope_is_bit_exact_passthrough(self):
        """Centered vocals → the SAME array object back, no correction."""
        audio = _centered_stereo()
        out, entry = apply_role_pan(
            audio, _CENTER_PROFILE, measure_stereo_position(audio)
        )
        assert out is audio
        assert np.array_equal(out, audio)
        assert entry["status"] == "within_envelope"
        assert "correction" not in entry

    def test_center_violation_corrected(self):
        """Vocals at +8 dB → corrected: 5 dB reduction lands exactly on
        the 3 dB envelope edge, status "corrected"."""
        audio = _decorrelated_stereo(8.0)
        out, entry = apply_role_pan(
            audio, _CENTER_PROFILE, measure_stereo_position(audio)
        )
        assert entry["status"] == "corrected"
        assert entry["correction"]["applied_db"] == pytest.approx(5.0, abs=0.05)
        assert 0.0 < entry["correction"]["applied_db"] <= 6.0  # clamp
        assert -1.0 <= entry["correction"]["pan"] <= 1.0
        assert out is not audio, "a correction must produce a new array"
        residual = measure_stereo_position(out)["balance_db"]
        assert residual == pytest.approx(3.0, abs=0.1)
        # Theoretical residual is exactly 3.0; float32 energy math rounds to
        # ~3.000001 → allow a small epsilon around the envelope edge.
        assert abs(residual) <= 3.0 + 1e-3

    def test_wide_mild_violation_not_corrected(self):
        """Other at +8 dB is INSIDE the 12 dB extreme → untouched."""
        audio = _decorrelated_stereo(8.0)
        out, entry = apply_role_pan(
            audio, _WIDE_PROFILE, measure_stereo_position(audio)
        )
        assert out is audio
        assert np.array_equal(out, audio)
        assert entry["status"] == "within_envelope"
        assert "correction" not in entry

    def test_wide_gross_violation_clamped_to_human_review(self):
        """Other at +20 dB: 8 dB needed but the clamp only grants 6 → lands
        at ≈14 dB (NOT the 12 dB target) → "human_review" (per spec: allowed
        "corrected" o "human_review" según alcance — deterministic here)."""
        audio = _decorrelated_stereo(20.0)
        out, entry = apply_role_pan(
            audio, _WIDE_PROFILE, measure_stereo_position(audio)
        )
        assert entry["status"] == "human_review"
        assert entry["correction"]["applied_db"] == pytest.approx(6.0, abs=0.05)
        assert abs(measure_stereo_position(out)["balance_db"]) == pytest.approx(
            14.0, abs=0.3
        )
        assert any("clamp" in note for note in entry["notes"])

    def test_anti_phase_never_corrected(self):
        """L = −R (correlation −1) → reported, audio untouched."""
        audio = _anti_phase_stereo()
        out, entry = apply_role_pan(
            audio, _CENTER_PROFILE, measure_stereo_position(audio)
        )
        assert out is audio
        assert entry["status"] == "human_review"
        assert any("anti-phase" in note for note in entry["notes"])
        assert "correction" not in entry

    @pytest.mark.parametrize(
        "profile,balance_db",
        [(_CENTER_PROFILE, 30.0), (_WIDE_PROFILE, 30.0)],
    )
    def test_correction_never_exceeds_6_db(self, profile, balance_db):
        """The clamp is a hard limit: applied_db ≤ 6 even for +30 dB."""
        audio = _decorrelated_stereo(balance_db)
        out, entry = apply_role_pan(
            audio, profile, measure_stereo_position(audio)
        )
        assert 0.0 < entry["correction"]["applied_db"] <= 6.0
        reduced = abs(measure_stereo_position(out)["balance_db"])
        assert reduced < balance_db, "correction must reduce the imbalance"


class TestValidatePositions:
    """``pan_report`` structure + mono check (spec §5–6)."""

    def test_pan_role_profiles_roles(self):
        """voz/kick/bajo centro; acompañamiento dentro de extremos."""
        roles = {
            name: profile["role"]
            for name, profile in PAN_ROLE_PROFILES.items()
        }
        assert roles == {
            "drums": "center",
            "bass": "center",
            "other": "wide",
            "vocals": "center",
        }

    def test_roles_section_describes_envelope(self):
        """roles maps each stem to its envelope (spec §6 keys)."""
        _, report = validate_positions(
            {
                "vocals": _centered_stereo(),
                "other": _decorrelated_stereo(0.0),
            },
            PAN_ROLE_PROFILES,
        )
        assert report["roles"]["vocals"] == {
            "role": "center",
            "target_max_abs_balance_db": 3.0,
            "max_correction_db": 6.0,
        }
        assert report["roles"]["other"] == {
            "role": "wide",
            "target_max_abs_balance_db": 12.0,
            "max_correction_db": 6.0,
        }

    def test_wide_casi_mono_flagged_for_human(self):
        """Wide stem with correlation ~1 → "sin ancho/pseudo-estéreo" note.
        Not corrected in this step (own stereo creation is a later one)."""
        mono = _centered_stereo()  # corr = 1.0 > 0.98
        stems, report = validate_positions({"other": mono}, PAN_ROLE_PROFILES)
        assert stems["other"] is mono, "pseudo-stereo is never touched"
        assert report["stems"]["other"]["status"] == "human_review"
        assert any("sin ancho" in note for note in report["stems"]["other"]["notes"])
        assert report["human_decision"][0]["stem"] == "other"
        assert "sin ancho" in report["human_decision"][0]["reason"]

    def test_mono_check_centered_bus_compatible(self):
        """Bus sum with L == R → loss 0 dB, mono compatible."""
        _, report = validate_positions(
            {"vocals": _centered_stereo()}, PAN_ROLE_PROFILES
        )
        assert report["mono_check"]["bus_loss_db"] == pytest.approx(0.0, abs=1e-6)
        assert report["mono_check"]["mono_compatible"] is True
        assert report["mono_check"]["anti_phase_stems"] == []

    def test_mono_check_anti_phase_bus_incompatible(self):
        """An anti-phase stem collapses the mono bus → incompatible and
        listed in anti_phase_stems."""
        _, report = validate_positions(
            {"vocals": _anti_phase_stereo()}, PAN_ROLE_PROFILES
        )
        assert report["mono_check"]["bus_loss_db"] < MONO_COMPAT_MIN_DB
        assert report["mono_check"]["bus_loss_db"] == pytest.approx(-60.0, abs=0.5), (
            "JSON-safe floor instead of −∞"
        )
        assert report["mono_check"]["mono_compatible"] is False
        assert report["mono_check"]["anti_phase_stems"] == ["vocals"]
        assert any("anti-phase" in d["reason"] for d in report["human_decision"])

    def test_report_structure_and_json_safety(self):
        """Exact top-level/stem keys; all floats finite (X-Mix-Result header
        travels through json.dumps — Infinity would break the contract)."""
        stems = {
            "drums": _decorrelated_stereo(6.0),  # gross for center → corrected
            "bass": _centered_stereo(),  # within → passthrough
            "other": _decorrelated_stereo(10.0),  # within wide extreme
            "vocals": _anti_phase_stereo(),  # human review
        }
        _, report = validate_positions(stems, PAN_ROLE_PROFILES)
        assert set(report) == {"roles", "stems", "mono_check", "human_decision"}
        assert set(report["mono_check"]) == {
            "bus_loss_db",
            "mono_compatible",
            "anti_phase_stems",
        }
        assert set(report["stems"]["drums"]) == {
            "role", "position", "status", "correction", "notes",
        }
        assert report["stems"]["drums"]["status"] == "corrected"
        assert "correction" not in report["stems"]["bass"]
        assert report["stems"]["bass"]["status"] == "within_envelope"
        assert set(report["stems"]["vocals"]) == {
            "role", "position", "status", "notes",
        }
        assert report["stems"]["vocals"]["status"] == "human_review"
        payload = json.dumps(report)
        assert "Infinity" not in payload and "-Infinity" not in payload
        assert "NaN" not in payload


class TestMonoCompatLoss:
    """Direct contract of ``mono_compat_loss_db`` (spec §5)."""

    def test_centered_bus_zero_loss(self):
        """L == R → loss 0 dB."""
        left = _sine(440.0)
        bus = np.stack([left, left]).astype(np.float32)
        assert mono_compat_loss_db(bus) == pytest.approx(0.0, abs=1e-6)

    def test_anti_phase_bus_floor(self):
        """L = −R → total cancellation: JSON-safe floor (true value is −∞)."""
        left = _sine(440.0)
        bus = np.stack([left, -left]).astype(np.float32)
        assert mono_compat_loss_db(bus) == pytest.approx(-60.0, abs=0.5)
        assert mono_compat_loss_db(bus) < MONO_COMPAT_MIN_DB

    def test_right_heavy_bus_slight_loss(self):
        """R = 2×L → mid loses ≈ 0.46 dB — still mono compatible."""
        left = _sine(440.0)
        bus = np.stack([left, 2.0 * left]).astype(np.float32)
        assert mono_compat_loss_db(bus) == pytest.approx(-0.46, abs=0.05)
        assert mono_compat_loss_db(bus) >= MONO_COMPAT_MIN_DB


class TestMixEnginePanIntegration:
    """``build_mix`` integration (spec §: pan BEFORE EQ, contracts intact)."""

    def test_empty_pan_profiles_keeps_paso02_routing(self, tmp_path, monkeypatch):
        """``pan_profiles={}`` → no pan_report key, no pan applied; the
        EQ routing of Paso 02 stays untouched."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        result = build_mix(
            str(uuid.uuid4()), str(tmp_path / "input.wav"), pan_profiles={}
        )
        assert "pan_report" not in result
        assert result["eq_profiles_applied"] == MAGIC_PROFILES
        assert set(result["analysis"]) == set(STEM_NAMES)
        assert "tempo_bpm" in result and "genre" in result

    def test_default_pan_profiles_adds_pan_report(self, tmp_path, monkeypatch):
        """``pan_profiles=None`` → role pan enabled by default (Paso 03):
        pan_report present; mono fixture stems pass through the envelope
        except the wide mono "other" (pseudo-stereo → human_review)."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        result = build_mix(str(uuid.uuid4()), str(tmp_path / "input.wav"))
        assert "pan_report" in result
        report = result["pan_report"]
        assert set(report) == {"roles", "stems", "mono_check", "human_decision"}
        assert set(report["stems"]) == set(STEM_NAMES)
        for name in ("drums", "bass", "vocals"):
            assert report["stems"][name]["status"] == "within_envelope"
        assert report["stems"]["other"]["status"] == "human_review"
        assert any(
            "sin ancho" in decision["reason"]
            for decision in report["human_decision"]
        )
        assert report["mono_check"]["mono_compatible"] is True
        assert report["mono_check"]["anti_phase_stems"] == []
        # Paso 01/02 keys are untouched by the new key.
        assert result["eq_profiles_applied"] == MAGIC_PROFILES
        assert set(result["analysis"]) == set(STEM_NAMES)
        assert "tempo_bpm" in result and "genre" in result