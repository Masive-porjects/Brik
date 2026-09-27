"""TDD tests for the stem balance auto-gain module (Mix Stem Balance, T3).

RED → GREEN → REFACTOR contract for ``stem_balance.compute_stem_balance``:

* measures integrated LUFS per stem (reuses ``measure_lufs``, the same
  meter the engine analysis uses),
* derives the vocal target from the genre emphasis geometry
  (``d = vocal_forward − groove_forward``: positive = voice forward,
  negative = groove forward, 0 = balanced) mapped to the SAME ±6 dB
  fader band the creative trims use (T1),
* computes ONE correction on the voice relative to the groove level
  (mean of drums/bass), clamped at ±6 dB — the only relationship the
  emphasis defines (vocal v. groove). Drums/bass/other gains stay 0.0:
  fixing the voice is the reported symptom, the manual faders (T1) stay
  on top for the rest,
* never mutates audio: pure calculation, ``mix_engine`` decides whether
  to apply (toggle, default OFF), so OFF stays bit-exact.
"""
import sys

sys.path.insert(0, "src")

import numpy as np
import pytest

from audiomind.processing.loudness import measure_lufs

_SR = 44100


def _tone(hz: float, seconds: float = 1.0, gain: float = 0.25) -> np.ndarray:
    t = np.linspace(0.0, seconds, int(_SR * seconds), endpoint=False)
    mono = gain * np.sin(2.0 * np.pi * hz * t)
    return np.stack([mono, mono]).astype(np.float32)


def _session_stems(
    vocals_gain: float = 0.05, drums_gain: float = 0.4,
) -> dict[str, np.ndarray]:
    """Synthetic stems with a controllable vocal v. groove imbalance."""
    return {
        "drums": _tone(120.0, gain=drums_gain),
        "bass": _tone(90.0, gain=drums_gain * 0.8),
        "other": _tone(330.0, gain=0.2),
        "vocals": _tone(440.0, gain=vocals_gain),
    }


def _session_stems_balanced(vocal_gap_db: float = 4.0) -> dict[str, np.ndarray]:
    """Realistic fixture: the voice sits EXACTLY ``vocal_gap_db`` below the
    groove level (mean of drums/bass), close to the producer session's
    reported ~7 dB — K-weighting makes raw amplitudes misleading, so the
    gap is normalized by measured LUFS (deterministic)."""
    stems = _session_stems()
    lufs = {name: measure_lufs(audio, _SR) for name, audio in stems.items()}
    groove = float(np.mean([lufs["drums"], lufs["bass"]]))
    target = groove - vocal_gap_db
    current = lufs["vocals"]
    stems["vocals"] = stems["vocals"] * (10.0 ** ((target - current) / 20.0))
    return stems


class TestMeasureStemLufs:
    def test_returns_finite_lufs_per_stem(self):
        from audiomind.processing.stem_balance import measure_stem_lufs

        stems = _session_stems()
        lufs = measure_stem_lufs(stems, _SR)
        assert set(lufs) == {"drums", "bass", "other", "vocals"}
        for value in lufs.values():
            assert np.isfinite(value)
            assert value > -70.0

    def test_louder_stem_measures_higher(self):
        from audiomind.processing.stem_balance import measure_stem_lufs

        stems = _session_stems(vocals_gain=0.05, drums_gain=0.4)
        lufs = measure_stem_lufs(stems, _SR)
        assert lufs["drums"] > lufs["vocals"]


class TestComputeStemBalance:
    def test_voice_forward_target_raises_voice(self):
        """pop (vocal 0.7/groove 0.3): the voice is pulled UP toward the
        groove level +d*6 dB."""
        from audiomind.processing.stem_balance import compute_stem_balance

        stems = _session_stems(vocals_gain=0.05, drums_gain=0.4)
        result = compute_stem_balance(
            stems, _SR, {"vocal_forward": 0.7, "groove_forward": 0.3}
        )
        assert result["gains"]["vocals_db"] > 0.0
        assert result["gains"]["drums_db"] == 0.0
        assert result["gains"]["bass_db"] == 0.0
        assert result["gains"]["other_db"] == 0.0

    def test_groove_forward_target_lowers_raise(self):
        """hip_hop (0.3/0.7): target is BELOW the groove, so a mild
        imbalance needs a smaller (or negative) vocal gain than pop."""
        from audiomind.processing.stem_balance import compute_stem_balance

        stems = _session_stems_balanced(vocal_gap_db=4.0)
        pop = compute_stem_balance(
            stems, _SR, {"vocal_forward": 0.7, "groove_forward": 0.3}
        )
        hip_hop = compute_stem_balance(
            stems, _SR, {"vocal_forward": 0.3, "groove_forward": 0.7}
        )
        # pop: target at groove+2.4 (gap 4 → corr +6.4 → clamp 6.0)
        # hip_hop: target at groove−2.4 (gap 4 → corr +1.6)
        assert pop["gains"]["vocals_db"] == pytest.approx(6.0, abs=0.01)
        assert hip_hop["gains"]["vocals_db"] == pytest.approx(1.6, abs=0.2)
        assert hip_hop["gains"]["vocals_db"] < pop["gains"]["vocals_db"]

    def test_balanced_weights_target_groove_level(self):
        """neutral 0.5/0.5: the voice is corrected exactly onto the
        groove level (d=0 → offset 0 dB)."""
        from audiomind.processing.stem_balance import compute_stem_balance

        stems = _session_stems_balanced(vocal_gap_db=4.0)
        result = compute_stem_balance(
            stems, _SR, {"vocal_forward": 0.5, "groove_forward": 0.5}
        )
        # gap 4 → correction ≈ +4.0 (inside the band, no clamp).
        assert result["gains"]["vocals_db"] == pytest.approx(4.0, abs=0.2)
        assert 0.0 <= result["gains"]["vocals_db"] <= 6.0

    def test_gain_clamped_at_6_db(self):
        """A gigantic imbalance never exceeds the ±6 dB fader band."""
        from audiomind.processing.stem_balance import compute_stem_balance

        stems = _session_stems_balanced(vocal_gap_db=30.0)
        result = compute_stem_balance(
            stems, _SR, {"vocal_forward": 0.7, "groove_forward": 0.3}
        )
        assert abs(result["gains"]["vocals_db"]) <= 6.0
        assert result["gains"]["vocals_db"] == 6.0

    def test_report_geometry_is_truthful(self):
        """The report exposes what was measured and what was targeted."""
        from audiomind.processing.stem_balance import compute_stem_balance

        stems = _session_stems_balanced(vocal_gap_db=4.0)
        result = compute_stem_balance(
            stems, _SR, {"vocal_forward": 0.7, "groove_forward": 0.3}
        )
        assert "stem_lufs" in result and "vocals" in result["stem_lufs"]
        assert "groove_level_lufs" in result
        assert "vocal_target_lufs" in result
        assert "d" in result
        assert result["d"] == pytest.approx(0.4)
        # target = groove + d*6 ; gain = clamp(target − voice)
        assert result["vocal_target_lufs"] == pytest.approx(
            result["groove_level_lufs"] + 0.4 * 6.0, abs=0.01
        )

    def test_apply_gains_closes_the_gap(self):
        """Round-trip integrity: applying the computed gains with the T2
        fader helper re-measures the voice ON the groove target."""
        import audiomind.processing.mix_engine as mix_engine
        from audiomind.processing.stem_balance import compute_stem_balance

        stems = _session_stems_balanced(vocal_gap_db=4.0)
        result = compute_stem_balance(
            stems, _SR, {"vocal_forward": 0.5, "groove_forward": 0.5}
        )
        processed = {name: arr.copy() for name, arr in stems.items()}
        bus_audio = [processed[name] for name in mix_engine.STEM_NAMES]
        mix_engine._apply_stem_trims(
            processed, bus_audio, result["gains"]
        )
        after = measure_lufs(processed["vocals"], _SR)
        assert abs(after - result["vocal_target_lufs"]) < 0.6