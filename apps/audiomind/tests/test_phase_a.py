"""Phase A — smart gating, stereo-correlation QC and dynamic-range QC tests.

Covers the Phase A scope:

  1. Smart gating (A1): loud/healthy/deliverable input → gate applied with
     ``gated_modules`` in the result; quiet raw input → gate not applied
     and the full chain runs; an engaged creative signature (e.g. clarity
     brightness moved) → conservative tier that never gates the signature.
  2. The bit-exact neutral contract still holds through the new path.
  3. Stereo-correlation QC (A2): decorrelated (inverted-channel) stereo →
     ``correlation`` issue; identical L/R → no issue.
  4. Dynamic-range QC (A3): over-compressed LRA → ``dr`` issue; healthy →
     none.
  5. Transparent passthrough is still sample-identical.

Conventions mirror the rest of the suite: ``sys.path.insert(0, "src")``,
synthetic numpy WAVs into ``tmp_path``, ``soundfile`` round-trips and
``engine.process_audio`` integration coverage.
"""
import sys

sys.path.insert(0, "src")

import numpy as np
import soundfile as sf

from audiomind.models.audio import (
    AnalysisResult,
    MasteringParameters,
    MasterResultMetrics,
)
from audiomind.processing.engine import process_audio
from audiomind.processing.presets import PRESET_CHAINS
from audiomind.processing.smart_gate import (
    ADVISORY_MODULES,
    CORRECTIVE_SCALE,
    SIGNATURE_SCALE_FLOOR,
)
from audiomind.processing.validation import (
    DR_COLLAPSE_RATIO,
    DR_MINIMUM_LU,
    STEREO_CORRELATION_MINIMUM,
    validate_master,
)

SR = 44100
#: Natural preset = quietest targets (LUFS -16), so the loud dense fixture
#: stays on the "warning" side of every threshold it needs to PASS.
_PRESET = PRESET_CHAINS["natural"]


def _write_wav(path, samples, sr=SR, subtype="FLOAT") -> None:
    x = np.asarray(samples)
    blocks = x.T if x.ndim == 2 else x
    sf.write(str(path), blocks, sr, subtype=subtype)


def _dense_program(seconds: float = 2.0, seed: int = 7) -> np.ndarray:
    """Loud, dense, healthy stereo program (the "already deliverable" case).

    Tuned so the input analysis passes ALL THREE smart-gate conditions:
    |LUFS − target| ≤ 1.5 dB (≈ -13.7 vs -14), crest ≥ 6 dB (≈ 8.9) and
    true peak ≤ ceiling + 0.1 dB (≈ -7 dBFS vs -0.9 ceiling bound).
    """
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.linspace(0.0, seconds, n, endpoint=False)
    env = (
        0.42
        + 0.08 * np.sin(2 * np.pi * 0.5 * t)
        + 0.05 * np.sin(2 * np.pi * 0.23 * t + 1.0)
    )
    sig = 0.38 * np.sin(2 * np.pi * 440 * t) * env
    det = 0.15 * np.sin(2 * np.pi * 441.5 * t) * env + 0.12 * np.sin(
        2 * np.pi * 660 * t
    ) * env
    noise = 0.015 * rng.standard_normal(n)
    left = sig + det + noise
    right = (
        0.38 * np.sin(2 * np.pi * 440 * t + 0.02) * env
        + 0.15 * np.sin(2 * np.pi * 438.5 * t) * env
        + 0.12 * np.sin(2 * np.pi * 660 * t + 0.05) * env
        + 0.015 * rng.standard_normal(n)
    )
    x = np.stack([left, right])
    x = x / np.max(np.abs(x)) * 10 ** (-7.0 / 20)  # peak ≈ -7 dBFS
    return x


def _dense_analysis(dynamic_range_db: float = 12.0) -> AnalysisResult:
    return AnalysisResult(
        integrated_lufs=-13.7,
        true_peak_db=-7.0,
        dynamic_range_db=dynamic_range_db,
        spectral_centroid=3000.0,
        tempo_bpm=120.0,
        duration_seconds=2.0,
        sample_rate=SR,
        channels=2,
        detected_genre="Electronic",
        genre_confidence=0.9,
        crest_factor_db=8.9,
        is_already_mastered=True,
        mastering_confidence=0.8,
    )


def _quiet_sine(seconds: float = 1.0) -> np.ndarray:
    t = np.linspace(0.0, seconds, int(SR * seconds), endpoint=False)
    low = 0.03 * np.sin(2 * np.pi * 220 * t)
    return np.stack([low, low])


def _quiet_analysis() -> AnalysisResult:
    """Raw low-level input analysis: misses every gate condition."""
    return AnalysisResult(
        integrated_lufs=-31.4,
        true_peak_db=-30.5,
        dynamic_range_db=14.0,
        spectral_centroid=220.0,
        tempo_bpm=120.0,
        duration_seconds=1.0,
        sample_rate=SR,
        channels=2,
        detected_genre="other",
        genre_confidence=0.0,
        crest_factor_db=3.0,
        is_already_mastered=False,
        mastering_confidence=0.1,
    )


# ── 1. Smart gating (A1) ───────────────────────────────────────────────


def test_smart_gate_applied_on_deliverable_input(tmp_path):
    """A loud/healthy/peak-deliverable source → advisory tier, scales set.

    Uses ``target_lufs_db=-14.0`` (the platform default) to take the FULL
    master chain — pristine defaults return early via the bit-exact
    fast-path, which is exactly what the neutral contract requires.
    """
    in_path = tmp_path / "in.wav"
    out_path = tmp_path / "out.wav"
    _write_wav(in_path, _dense_program())

    result = process_audio(
        in_path,
        out_path,
        MasteringParameters(target_lufs_db=-14.0),
        analysis_result=_dense_analysis(),
    )

    gate = result["smart_gate"]
    assert gate is not None
    assert gate["applied"] is True
    assert gate["tier"] == "advisory"
    # The advisory gate reports a scale for every advisory module, and never
    # scales a module to 0.0 — it reduces, it does not block.
    assert set(gate["intensity_scales"]) == set(ADVISORY_MODULES)
    assert all(v > 0.0 for v in gate["intensity_scales"].values())
    assert set(gate["gated_modules"]) == set(ADVISORY_MODULES)
    # Evidence mirrors the analysis and the layer-2 anchors.
    assert gate["evidence"]["lufs_within_tolerance"] is True
    assert gate["evidence"]["crest_healthy"] is True
    assert gate["evidence"]["peak_deliverable"] is True
    assert abs(gate["evidence"]["lufs_delta_db"] - 0.3) < 0.01
    assert "stereo_correlation" in result
    assert result["stereo_correlation"] is not None
    assert result["target_lufs"] == -14.0


def test_smart_gate_not_applied_on_quiet_raw_input(tmp_path):
    """A quiet raw source misses the LUFS tolerance → no gating, full chain."""
    in_path = tmp_path / "quiet.wav"
    out_path = tmp_path / "out.wav"
    _write_wav(in_path, _quiet_sine())

    result = process_audio(
        in_path,
        out_path,
        MasteringParameters(target_lufs_db=-14.0),
        analysis_result=_quiet_analysis(),
    )

    assert result.get("smart_gate") is None
    # The full chain still delivers a loud, healthy master.
    assert result["integrated_lufs"] > -20.0
    assert result["true_peak_db"] <= 0.0


def test_smart_gate_protects_engaged_signature(tmp_path):
    """Brightness moved (signature engaged) → the clarity shelf is protected.

    The advisory scale for an engaged signature never drops below
    ``SIGNATURE_SCALE_FLOOR``; the purely corrective match EQ still takes the
    full reduction to ``CORRECTIVE_SCALE``.
    """
    in_path = tmp_path / "in.wav"
    out_path = tmp_path / "out.wav"
    _write_wav(in_path, _dense_program())

    params = MasteringParameters(clarity_brightness_db=2.0, target_lufs_db=-14.0)
    result = process_audio(
        in_path, out_path, params, analysis_result=_dense_analysis()
    )

    gate = result["smart_gate"]
    assert gate is not None
    assert gate["applied"] is True
    assert gate["tier"] == "advisory"
    scales = gate["intensity_scales"]
    assert scales["clarity_shelf"] == SIGNATURE_SCALE_FLOOR
    assert scales["match_eq"] == CORRECTIVE_SCALE
    # Warming is a saturation signature, which the brightness move does not
    # engage — it keeps the corrective scale like the match EQ does.
    assert scales["warmth_tilt"] == CORRECTIVE_SCALE
    assert all(v > 0.0 for v in scales.values())


# ── 2. Bit-exact neutral contract ──────────────────────────────────────


def test_neutral_defaults_still_bit_exact_through_phase_a_path(tmp_path):
    """MasteringParameters() (master mode, full chain, gate evaluated) must
    remain a byte-identical bypass — the new gate never touches the
    pristine-default path."""
    in_path = tmp_path / "in.wav"
    out_path = tmp_path / "out.wav"
    _write_wav(in_path, _dense_program())

    result = process_audio(in_path, out_path, MasteringParameters())

    in_arr, in_sr = sf.read(str(in_path), always_2d=True)
    out_arr, out_sr = sf.read(str(out_path), always_2d=True)
    assert in_sr == out_sr
    assert in_arr.shape == out_arr.shape
    np.testing.assert_array_equal(in_arr, out_arr)
    # The response keeps its shape; the gate has nothing to gate without
    # an analysis result.
    assert result.get("smart_gate") is None


# ── 3. Stereo-correlation QC (A2) ──────────────────────────────────────


def test_decorrelated_stereo_flags_correlation_issue():
    """Inverted right channel → low correlation → warning-only issue."""
    master = MasterResultMetrics(
        integrated_lufs=-14.0,
        true_peak_db=-1.4,
        crest_factor_db=9.0,
        stereo_correlation=-0.85,
    )
    analysis = _dense_analysis()

    verdict = validate_master(master, _PRESET, analysis)

    assert verdict is not None
    assert verdict["status"] == "warning"
    issue = next(i for i in verdict["issues"] if i["metric"] == "correlation")
    assert issue["measured"] == -0.85
    assert str(STEREO_CORRELATION_MINIMUM) in issue["expected"]
    assert "fase" in issue["message_es"]


def test_identical_lr_has_no_correlation_issue():
    """Identical channels → correlation 1.0 → no issue."""
    master = MasterResultMetrics(
        integrated_lufs=-14.0,
        true_peak_db=-1.4,
        crest_factor_db=9.0,
        stereo_correlation=1.0,
    )

    verdict = validate_master(master, _PRESET, _dense_analysis())

    assert verdict is not None
    assert all(i["metric"] != "correlation" for i in verdict["issues"])


def test_engine_measures_stereo_correlation(tmp_path):
    """The engine emits the measured correlation on the final master."""
    in_path = tmp_path / "in.wav"
    out_path = tmp_path / "out.wav"
    _write_wav(in_path, _dense_program())

    result = process_audio(
        in_path,
        out_path,
        MasteringParameters(target_lufs_db=-14.0),
    )

    corr = result["stereo_correlation"]
    assert corr is not None
    assert -1.0 <= corr <= 1.0
    assert corr > STEREO_CORRELATION_MINIMUM  # dense fixture is mono-safe


# ── 4. Dynamic-range QC (A3) ───────────────────────────────────────────


def test_overcompressed_lra_flags_dr_issue():
    master = MasterResultMetrics(
        integrated_lufs=-14.0,
        true_peak_db=-1.4,
        crest_factor_db=3.0,
        lra=2.0,
    )

    verdict = validate_master(master, _PRESET, _dense_analysis(12.0))

    assert verdict is not None
    assert verdict["status"] == "warning"
    issue = next(i for i in verdict["issues"] if i["metric"] == "dr")
    assert issue["measured"] == 2.0
    assert f"{DR_MINIMUM_LU:g}" in issue["expected"]
    assert f"{DR_COLLAPSE_RATIO:g}" in issue["expected"]
    assert "colapsó" in issue["message_es"]


def test_healthy_lra_has_no_dr_issue():
    master = MasterResultMetrics(
        integrated_lufs=-14.0,
        true_peak_db=-1.4,
        crest_factor_db=9.0,
        lra=8.0,
    )

    verdict = validate_master(master, _PRESET, _dense_analysis(12.0))

    assert verdict is not None
    assert all(i["metric"] != "dr" for i in verdict["issues"])


def test_dr_check_skipped_without_input_reference():
    """No input dynamic range (analysis None or 0) → no DR judgement."""
    master = MasterResultMetrics(integrated_lufs=-14.0, lra=2.0)

    # LUFS is measurable, so the verdict exists — but with NO dr issue.
    verdict_no_analysis = validate_master(master, _PRESET, None)
    assert verdict_no_analysis is not None
    assert all(i["metric"] != "dr" for i in verdict_no_analysis["issues"])
    verdict_zero_dr = validate_master(master, _PRESET, _dense_analysis(0.0))
    assert verdict_zero_dr is not None
    assert all(i["metric"] != "dr" for i in verdict_zero_dr["issues"])


# ── 5. Transparent passthrough ─────────────────────────────────────────


def test_transparent_passthrough_is_identical_after_phase_a(tmp_path):
    """transparent + no target + same rate + 24-bit ≈ sample-identical
    (only the 24-bit PCM quantization of the writer may touch samples)."""
    in_path = tmp_path / "in.wav"
    out_path = tmp_path / "out.wav"
    _write_wav(in_path, _dense_program())

    result = process_audio(
        in_path,
        out_path,
        MasteringParameters(
            processing_mode="transparent",
            target_lufs_db=None,
            output_sr="same_as_input",
            output_bit_depth=24,
        ),
    )

    out, out_sr = sf.read(str(out_path), always_2d=True)
    expected = sf.read(str(in_path), always_2d=True)[0]
    assert out_sr == SR
    assert out.shape == expected.shape
    np.testing.assert_allclose(out, expected, atol=2e-7, rtol=0)
    assert result["warnings"] == []
    # The QC statistics ride along without touching the samples.
    assert "stereo_correlation" in result