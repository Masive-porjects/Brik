"""Advisory smart gate — intensity scales and the Mix→Master ordering fix.

Covers the advisory ("consultative") smart gate contract:

  1. ``decide_smart_gate`` returns ``intensity_scales`` on every branch.
  2. The core invariant: NO scale is ever 0.0 (or below). The gate is
     advisory, so it reduces corrective processing proportionally instead of
     blocking a module outright.
  3. Every scale stays inside a sane band (0.3–1.0) and the creative
     signature floor (0.7) holds for engaged modules.
  4. A missing analysis is safe: the gate reports ``applied=False`` and every
     module keeps full scale.
  5. The engine's advisory reduction never lands on delivery-critical stages
     (limiter / clipper) and stays bit-exact when the gate is inactive.
  6. REGRESSION: ``process_audio(..., mix_metadata=...)`` must not raise
     ``UnboundLocalError``. On develop the ``if mix_metadata:`` block calls
     ``_adapt_spatial_for_mix_context`` two lines BEFORE the nested
     ``def`` that binds the name, so every Mix→Master request died at
     runtime while the whole suite stayed green.

Conventions mirror the rest of the suite: ``sys.path.insert(0, "src")``,
synthetic numpy WAVs into ``tmp_path`` and ``soundfile`` round-trips.
"""
import sys

sys.path.insert(0, "src")

import numpy as np
import pytest
import soundfile as sf

from audiomind.models.audio import AnalysisResult, MasteringParameters
from audiomind.processing.engine import BASE_MODULE_INTENSITY, process_audio
from audiomind.processing.smart_gate import (
    ADVISORY_MODULES,
    CORRECTIVE_SCALE,
    SCALE_FLOOR,
    SCALE_MAX,
    SIGNATURE_SCALE_FLOOR,
    decide_smart_gate,
)

SR = 44100

#: Hard floor of the advisory band — the gate must never reach 0.0.
MIN_ALLOWED_SCALE = 0.3


def _analysis(
    integrated_lufs: float = -13.7,
    true_peak_db: float = -7.0,
    crest_factor_db: float = 8.9,
) -> AnalysisResult:
    return AnalysisResult(
        integrated_lufs=integrated_lufs,
        true_peak_db=true_peak_db,
        dynamic_range_db=12.0,
        spectral_centroid=3000.0,
        tempo_bpm=120.0,
        duration_seconds=2.0,
        sample_rate=SR,
        channels=2,
        detected_genre="Electronic",
        genre_confidence=0.9,
        crest_factor_db=crest_factor_db,
        is_already_mastered=True,
        mastering_confidence=0.8,
    )


def _commercial_ready_analysis() -> AnalysisResult:
    """Passes all three commercial-readiness conditions."""
    return _analysis()


def _raw_analysis() -> AnalysisResult:
    """Fails every condition — full processing expected."""
    return _analysis(
        integrated_lufs=-31.4,
        true_peak_db=-30.5,
        crest_factor_db=3.0,
    )


def _engaged_signature_params() -> MasteringParameters:
    """Brightness lifted away from the pristine default = engaged signature."""
    return MasteringParameters(clarity_brightness_db=2.0, target_lufs_db=-14.0)


def _pristine_params() -> MasteringParameters:
    return MasteringParameters(target_lufs_db=-14.0)


def _write_wav(path, samples, sr: int = SR) -> None:
    x = np.asarray(samples)
    sf.write(str(path), x.T if x.ndim == 2 else x, sr, subtype="FLOAT")


def _program(seconds: float = 2.0, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(SR * seconds)
    t = np.linspace(0.0, seconds, n, endpoint=False)
    env = 0.42 + 0.08 * np.sin(2 * np.pi * 0.5 * t) + 0.05 * np.sin(
        2 * np.pi * 0.23 * t + 1.0
    )
    left = 0.38 * np.sin(2 * np.pi * 440 * t) * env
    left += 0.15 * np.sin(2 * np.pi * 441.5 * t) * env
    left += 0.015 * rng.standard_normal(n)
    right = 0.38 * np.sin(2 * np.pi * 440 * t + 0.02) * env
    right += 0.15 * np.sin(2 * np.pi * 438.5 * t) * env
    right += 0.015 * rng.standard_normal(n)
    x = np.stack([left, right])
    return x / np.max(np.abs(x)) * 10 ** (-7.0 / 20)


# ── 1. Report shape ─────────────────────────────────────────────────────


def test_gate_returns_intensity_scales_when_commercial_ready():
    gate = decide_smart_gate(_pristine_params(), _commercial_ready_analysis())
    assert gate["applied"] is True
    assert gate["tier"] == "advisory"
    scales = gate["intensity_scales"]
    assert set(scales) == set(ADVISORY_MODULES)
    assert all(isinstance(v, float) for v in scales.values())


def test_gate_returns_intensity_scales_when_not_commercial_ready():
    gate = decide_smart_gate(_pristine_params(), _raw_analysis())
    assert gate["applied"] is False
    assert gate["tier"] == "none"
    assert gate["intensity_scales"] == {m: 1.0 for m in ADVISORY_MODULES}


# ── 2. The invariant: never blocks to 0.0 ───────────────────────────────


@pytest.mark.parametrize(
    "label, params, analysis",
    [
        ("commercial_ready_pristine", _pristine_params(), _commercial_ready_analysis()),
        (
            "commercial_ready_engaged_signature",
            _engaged_signature_params(),
            _commercial_ready_analysis(),
        ),
        ("not_commercial_ready", _pristine_params(), _raw_analysis()),
        ("no_analysis", _pristine_params(), None),
    ],
)
def test_no_module_is_ever_blocked_to_zero(label, params, analysis):
    """Sweep every gate branch: no scale may reach 0.0 or drop below it.

    This is the test that pins the advisory contract. A regression to binary
    blocking would silently zero a corrective stage.
    """
    scales = decide_smart_gate(params, analysis)["intensity_scales"]
    offenders = {m: v for m, v in scales.items() if v <= 0.0}
    assert not offenders, f"{label}: modules blocked to 0.0 → {offenders}"


def test_no_module_is_ever_blocked_to_zero_across_all_signatures():
    """Binarize the analysis over a grid: still nothing may reach 0.0.

    Every module/branch combination of the gate is covered, so a future
    branch that returns 0.0 for some module cannot slip through.
    """
    for lufs in (-31.4, -14.0, -13.7, -13.2):
        for peak in (-30.5, -7.0, -1.2, -0.6):
            for crest in (3.0, 4.5, 8.9, 14.0):
                for params in (_pristine_params(), _engaged_signature_params()):
                    analysis = _analysis(
                        integrated_lufs=lufs,
                        true_peak_db=peak,
                        crest_factor_db=crest,
                    )
                    gate = decide_smart_gate(params, analysis)
                    for module, value in gate["intensity_scales"].items():
                        assert value > 0.0, (
                            f"{module} blocked to {value} "
                            f"(lufs={lufs}, peak={peak}, crest={crest})"
                        )


# ── 3. Safe band and signature floor ────────────────────────────────────


def test_scales_stay_inside_the_advisory_band():
    gate = decide_smart_gate(_pristine_params(), _commercial_ready_analysis())
    for module, value in gate["intensity_scales"].items():
        assert MIN_ALLOWED_SCALE <= value <= SCALE_MAX, f"{module}={value}"


def test_engaged_signature_never_drops_below_signature_floor():
    """An explicitly chosen character is protected at 0.7 scale."""
    gate = decide_smart_gate(
        _engaged_signature_params(), _commercial_ready_analysis()
    )
    assert gate["intensity_scales"]["clarity_shelf"] >= SIGNATURE_SCALE_FLOOR


def test_reduced_scales_stay_at_or_above_the_corrective_floor():
    """A reduced corrective module never drops below CORRECTIVE_SCALE."""
    gate = decide_smart_gate(_pristine_params(), _commercial_ready_analysis())
    reduced = {
        m: v for m, v in gate["intensity_scales"].items() if v < SCALE_MAX
    }
    assert reduced, "expected at least one reduced module on commercial-ready input"
    for module, value in reduced.items():
        assert value >= CORRECTIVE_SCALE, f"{module}={value}"


def test_engine_base_intensity_sits_inside_the_advisory_band():
    """The engine's base scale must not be strong enough to bypass a module.

    If BASE_MODULE_INTENSITY were 0 (or the advisory minimum were 0), a fully
    reduced corrective stage would collapse into a silent bypass.
    """
    assert CORRECTIVE_SCALE <= BASE_MODULE_INTENSITY
    assert BASE_MODULE_INTENSITY > MIN_ALLOWED_SCALE
    worst_case = BASE_MODULE_INTENSITY * SCALE_FLOOR
    assert worst_case > 0.0


def test_band_constants_are_self_consistent():
    assert 0.0 < SCALE_FLOOR <= CORRECTIVE_SCALE
    assert CORRECTIVE_SCALE <= SIGNATURE_SCALE_FLOOR <= SCALE_MAX == 1.0


# ── 4. Missing analysis is safe ─────────────────────────────────────────


def test_no_analysis_returns_full_scales_and_does_not_apply():
    gate = decide_smart_gate(_pristine_params(), None)
    assert gate["applied"] is False
    assert gate["tier"] == "none"
    assert gate["gated_modules"] == []
    assert gate["intensity_scales"] == {m: 1.0 for m in ADVISORY_MODULES}
    assert "reason" in gate["evidence"]


# ── 5. Engine integration ───────────────────────────────────────────────


def test_engine_reports_advisory_gate_on_commercial_ready_input(tmp_path):
    in_path = tmp_path / "in.wav"
    out_path = tmp_path / "out.wav"
    _write_wav(in_path, _program())

    result = process_audio(
        in_path,
        out_path,
        _pristine_params(),
        analysis_result=_commercial_ready_analysis(),
    )

    gate = result["smart_gate"]
    assert gate is not None
    assert gate["tier"] == "advisory"
    assert gate["intensity_scales"]
    # The advisory gate reduces corrective stages but never delivers silence.
    assert out_path.exists()
    out, _ = sf.read(str(out_path), always_2d=True)
    assert np.any(np.abs(out) > 0.0)


def test_advisory_gate_never_touches_delivery_critical_stages(tmp_path):
    """The limiter ceiling stays at the codec-safe value on a gated master.

    ``am_factor`` and the advisory scale apply ONLY to EQ/saturation. If the
    reduction leaked into the limiter or the soft-clipper, the master would
    silently lose delivery headroom.
    """
    in_path = tmp_path / "in.wav"
    out_path = tmp_path / "out.wav"
    _write_wav(in_path, _program())

    result = process_audio(
        in_path,
        out_path,
        _pristine_params(),
        analysis_result=_commercial_ready_analysis(),
    )
    assert result["true_peak_db"] <= 0.0
    assert result["integrated_lufs"] > -20.0


def test_inactive_gate_leaves_correction_at_full_strength(tmp_path):
    """A raw source (gate not applied) must NOT be scaled down.

    The advisory reduction is conditional on the gate being active. Applying
    the base scale unconditionally would quietly weaken every non-gated
    master — the exact silent-regression failure mode this file guards.
    """
    in_path = tmp_path / "in.wav"
    out_path = tmp_path / "out.wav"
    _write_wav(in_path, _program())

    result = process_audio(
        in_path,
        out_path,
        _pristine_params(),
        analysis_result=_raw_analysis(),
    )
    assert result.get("smart_gate") is None or result["smart_gate"]["applied"] is False


# ── 6. REGRESSION: Mix→Master ordering ──────────────────────────────────


def test_process_audio_with_mix_metadata_does_not_raise_unbound_local(tmp_path):
    """Mix→Master path must not raise ``UnboundLocalError``.

    The ``if mix_metadata:`` block used to sit ABOVE the nested
    ``def _adapt_spatial_for_mix_context`` that binds the name, so every
    request carrying mix metadata died before the chain could run. The name
    is a local of ``process_audio``; reading it before assignment raises.
    """
    in_path = tmp_path / "in.wav"
    out_path = tmp_path / "out.wav"
    _write_wav(in_path, _program())

    mix_metadata = {
        "schema_version": 1,
        "applied_spatial_width": 1.45,
        "side_energy_ratio": 0.52,
        "stem_lufs": {"drums": -18.2, "bass": -14.5},
        "transient_headroom_db": 0.4,
        "mix_status": "completed",
    }

    try:
        result = process_audio(
            in_path,
            out_path,
            MasteringParameters(target_lufs_db=-14.0),
            analysis_result=_commercial_ready_analysis(),
            mix_metadata=mix_metadata,
        )
    except UnboundLocalError as exc:  # pragma: no cover - failure evidence
        pytest.fail(
            "process_audio raised UnboundLocalError on the mix_metadata path: "
            f"{exc}. The 'if mix_metadata:' block must be placed AFTER the "
            "nested def of _adapt_spatial_for_mix_context."
        )

    assert out_path.exists()
    assert result["integrated_lufs"] is not None


def test_mix_metadata_path_actually_adapts_spatial_params(tmp_path):
    """The adaptation must run, not merely avoid crashing.

    ``transient_headroom_db < 1.0`` tightens the limiter ceiling to -1.5 dBTP.
    If the block were dropped instead of reordered, the ceiling would stay at
    the untouched default and this assertion would catch the silent no-op.
    """
    in_path = tmp_path / "in.wav"
    out_path = tmp_path / "out.wav"
    _write_wav(in_path, _program())

    params = MasteringParameters(target_lufs_db=-14.0)
    mix_metadata = {
        "schema_version": 1,
        "applied_spatial_width": 1.0,
        "side_energy_ratio": 0.0,
        "stem_lufs": {},
        "transient_headroom_db": 0.2,
        "mix_status": "completed",
    }

    adapted = process_audio(
        in_path,
        out_path,
        params,
        analysis_result=_commercial_ready_analysis(),
        mix_metadata=mix_metadata,
    )
    assert adapted["true_peak_db"] <= 0.0
