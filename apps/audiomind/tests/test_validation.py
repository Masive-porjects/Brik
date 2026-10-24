"""Unit tests for the Layer 2 post-master validation gate.

Covers the pure ``validate_master`` comparison logic: tolerances,
status/verdict shape, the low-confidence "universal" suggestion and
null-safety guarantees.
"""
import sys

sys.path.insert(0, "src")

from audiomind.models.audio import AnalysisResult, MasterResultMetrics
from audiomind.processing.presets import PRESET_CHAINS
from audiomind.processing.validation import (
    CREST_MINIMUM_DB,
    LUFS_TOLERANCE_DB,
    TRUE_PEAK_MARGIN_DB,
    validate_master,
)

# fuego: target_lufs=-12, limiter_ceiling_db=-1.0 (streaming-safe target)
PRESET = PRESET_CHAINS["fuego"]
_FUEGO_LUFS = PRESET["target_lufs"]
_FUEGO_CEILING = PRESET["limiter_ceiling_db"]


def _analysis(confidence: float = 0.9) -> AnalysisResult:
    return AnalysisResult(
        integrated_lufs=-18.0,
        true_peak_db=-6.0,
        dynamic_range_db=10.0,
        spectral_centroid=2000.0,
        tempo_bpm=100.0,
        duration_seconds=30.0,
        sample_rate=44100,
        channels=2,
        detected_genre="Trap",
        genre_confidence=confidence,
    )


def _master(lufs=None, peak=None, crest=None) -> MasterResultMetrics:
    return MasterResultMetrics(
        integrated_lufs=lufs,
        true_peak_db=peak,
        crest_factor_db=crest,
    )


class TestAllOk:
    def test_within_tolerances_is_ok(self):
        verdict = validate_master(
            _master(lufs=-12.2, peak=-1.4, crest=9.0), PRESET, _analysis()
        )
        assert verdict is not None
        assert verdict["status"] == "ok"
        assert verdict["issues"] == []
        assert verdict["retry_recommended"] is False
        assert verdict["suggested_preset_id"] is None

    def test_exact_tolerance_boundaries_are_ok(self):
        # Strictly-beyond comparisons: sitting exactly on a limit passes
        verdict = validate_master(
            _master(
                lufs=_FUEGO_LUFS - LUFS_TOLERANCE_DB,
                peak=_FUEGO_CEILING + TRUE_PEAK_MARGIN_DB,
                crest=CREST_MINIMUM_DB,
            ),
            PRESET,
            _analysis(),
        )
        assert verdict is not None
        assert verdict["status"] == "ok"


class TestLufsMiss:
    def test_below_target_reports_issue(self):
        verdict = validate_master(_master(lufs=-14.1, crest=9.0), PRESET, _analysis())
        assert verdict is not None
        assert verdict["status"] == "warning"
        issue = next(i for i in verdict["issues"] if i["metric"] == "lufs")
        assert issue["measured"] == -14.1
        assert f"{_FUEGO_LUFS}" in issue["expected"]
        assert "más bajo" in issue["message_es"]
        assert verdict["retry_recommended"] is True

    def test_above_target_reports_issue(self):
        verdict = validate_master(_master(lufs=-10.0, crest=9.0), PRESET, _analysis())
        issue = next(i for i in verdict["issues"] if i["metric"] == "lufs")
        assert "más alto" in issue["message_es"]


class TestCrestCollapse:
    def test_low_crest_flags_over_compression(self):
        verdict = validate_master(_master(lufs=-12.0, crest=4.2), PRESET, _analysis())
        issue = next(i for i in verdict["issues"] if i["metric"] == "crest")
        assert issue["measured"] == 4.2
        assert "≥ 6 dB" == issue["expected"]
        assert "sobre-comprimido" in issue["message_es"]
        assert verdict["status"] == "warning"

    def test_healthy_crest_has_no_crest_issue(self):
        verdict = validate_master(_master(lufs=-12.0, crest=12.0), PRESET, _analysis())
        assert verdict is not None
        assert all(i["metric"] != "crest" for i in verdict["issues"])


class TestTruePeakOverCeiling:
    def test_peak_above_ceiling_flags_issue(self):
        verdict = validate_master(
            _master(lufs=-12.0, peak=0.1), PRESET, _analysis()
        )
        issue = next(i for i in verdict["issues"] if i["metric"] == "true_peak")
        assert issue["measured"] == 0.1
        assert "techo" in issue["message_es"]

    def test_peak_at_ceiling_passes(self):
        verdict = validate_master(_master(lufs=-12.0, peak=-1.0), PRESET, _analysis())
        assert verdict is not None
        assert all(i["metric"] != "true_peak" for i in verdict["issues"])


class TestLowConfidenceSuggestion:
    def test_warning_with_low_confidence_suggests_universal(self):
        verdict = validate_master(
            _master(lufs=-14.0, crest=9.0), PRESET, _analysis(confidence=0.4)
        )
        assert verdict is not None
        assert verdict["suggested_preset_id"] == "universal"

    def test_warning_with_high_confidence_has_no_suggestion(self):
        verdict = validate_master(
            _master(lufs=-14.0, crest=9.0), PRESET, _analysis(confidence=0.85)
        )
        assert verdict is not None
        assert verdict["suggested_preset_id"] is None

    def test_ok_status_never_suggests_even_with_low_confidence(self):
        verdict = validate_master(
            _master(lufs=-12.0, crest=9.0), PRESET, _analysis(confidence=0.1)
        )
        assert verdict is not None
        assert verdict["status"] == "ok"
        assert verdict["suggested_preset_id"] is None


class TestNullSafety:
    def test_null_master_result_returns_none(self):
        assert validate_master(None, PRESET, _analysis()) is None

    def test_all_metrics_null_returns_none(self):
        # Failed best-effort measurement → nothing to judge, never a warning
        assert validate_master(_master(), PRESET, _analysis()) is None

    def test_partial_metrics_validate_only_present_ones(self):
        # Only crest measurable → only crest judged, no LUFS crash
        verdict = validate_master(_master(crest=3.0), PRESET, _analysis())
        assert verdict is not None
        assert [i["metric"] for i in verdict["issues"]] == ["crest"]

    def test_missing_analysis_does_not_crash(self):
        verdict = validate_master(_master(lufs=-14.0, crest=9.0), PRESET, None)
        assert verdict is not None
        assert verdict["status"] == "warning"
        assert verdict["suggested_preset_id"] == "universal"
