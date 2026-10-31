"""HTTP+model contract for ``GET /api/session/{id}/metrics`` (Fase A).

Why this module exists
----------------------
The adaptive agent contract needs a stable, real-measurement JSON. These
tests pin the four behaviors of the phase:

1. The route is registered under ``/api`` (openapi publishes it).
2. A analyzed session answers 200 with every promised block, 8 aligned
   bands, and the loudness standard exposed verbatim (BS.1770-4 honesty
   marker) - never fabricated numbers: what the session's analysis holds is
   what the endpoint echoes.
3. Unknown session / missing original file answer the sibling 404 vocabulary.
4. Legacy ``AnalysisResult`` payloads (pre-fase rows) still validate.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import audiomind.api.upload as upload_api
from audiomind.main import app
from audiomind.models.audio import AnalysisResult, SessionData

client = TestClient(app)

METRICS_PATH = "/api/session/metrics-session/metrics"

#: The analyzer's eight measurement bands (analysis/analyzer.py TARGET_BANDS_HZ).
EXPECTED_BANDS = [60, 150, 400, 1000, 2500, 6000, 10000, 15000]


def _write_wav(tmp_path) -> str:
    """A 2 s stereo 44.1 kHz sine: enough for the inspector to decode."""
    sr = 44100
    duration = 2.0
    t = np.linspace(0.0, duration, int(sr * duration), endpoint=False)
    left = 0.2 * np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
    audio = np.stack([left, left], axis=1)
    path = tmp_path / "metrics-fixture.wav"
    sf.write(path, audio, sr, subtype="FLOAT")
    return str(path)


def _analysis(energies: list[float] | None = None) -> AnalysisResult:
    return AnalysisResult(
        integrated_lufs=-18.4,
        true_peak_db=-3.1,
        dynamic_range_db=12.5,
        spectral_centroid=2450.7,
        tempo_bpm=120.0,
        duration_seconds=2.0,
        sample_rate=44100,
        channels=2,
        detected_genre="pop",
        genre_confidence=0.55,
        crest_factor_db=14.2,
        is_already_mastered=False,
        mastering_confidence=0.2,
        bands_hz=EXPECTED_BANDS,
        band_energies_db=energies or [round(-10.0 - i, 2) for i in range(8)],
    )


@pytest.fixture()
def session_with_analysis(tmp_path) -> str:
    """Persist one session the way mastering endpoints read it: through the
    in-memory ``api/upload.sessions`` dict (mastering reads that exact
    object, unlike the agent endpoints which reload from the store)."""
    upload_api.sessions["metrics-session"] = SessionData(
        session_id="metrics-session",
        original_path=_write_wav(tmp_path),
        analysis=_analysis(),
    )
    return "metrics-session"


def test_the_metrics_route_is_published_under_the_api_prefix() -> None:
    assert METRICS_PATH.replace("{id}", "x") in app.openapi()["paths"].keys() or any(
        p.startswith("/api/session/") and p.endswith("/metrics")
        for p in app.openapi()["paths"]
    )


def test_metrics_answers_every_promised_block_with_aligned_bands(
    session_with_analysis: str,
) -> None:
    response = client.get(METRICS_PATH)

    assert response.status_code == 200
    body = response.json()

    loudness = body["loudness"]
    assert loudness["integrated_lufs"] == -18.4
    assert loudness["standard"] == "ITU-R BS.1770-4"

    spectral = body["spectral"]
    assert spectral["bands_hz"] == EXPECTED_BANDS
    assert len(spectral["energies_db"]) == len(EXPECTED_BANDS)
    assert spectral["centroid_hz"] == 2450.7

    assert body["genre"]["detected"] == "pop"
    assert body["tempo"]["bpm"] == 120.0
    assert body["state"]["is_already_mastered"] is False
    assert body["duration_seconds"] == 2.0
    assert body["sample_rate"] == 44100
    assert body["channels"] == 2

    # The inspector runs read-only against the fixture; its rhythm block must
    # exist even when it holds no usable tempo (synthetic sine).
    profile = body["profile"]
    assert profile is not None
    assert "rhythm" in profile
    assert "duration_seconds" in profile


def test_metrics_degrades_honestly_when_the_file_is_missing(
    session_with_analysis: str,
) -> None:
    """A floor reading must answer the sibling 404, not a fabricated block."""
    upload_api.sessions["metrics-session"].original_path = "does/not/exist.wav"

    response = client.get(METRICS_PATH)
    assert response.status_code == 404
    assert response.json()["detail"] == "Audio file not found"


def test_metrics_answers_the_sibling_404_for_unknown_sessions() -> None:
    response = client.get("/api/session/no-existe/metrics")
    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


def test_legacy_analysis_results_still_validate() -> None:
    """Phase-A rows must survive: pre-contract payloads keep loading."""
    legacy: dict[str, Any] = _analysis().model_dump()
    legacy.pop("bands_hz", None)
    legacy.pop("band_energies_db", None)
    legacy.pop("loudness_standard", None)

    restored = AnalysisResult.model_validate(legacy)
    assert restored.bands_hz == []
    assert restored.band_energies_db == []
    assert restored.loudness_standard == "ITU-R BS.1770-4"


def test_analyze_audio_fills_the_aligned_band_energies(tmp_path) -> None:
    """S2: one computation, aligned to TARGET_BANDS_HZ, filled at analyze time."""
    from audiomind.analysis.analyzer import analyze_audio

    wav = _write_wav(tmp_path)
    result = analyze_audio(wav)

    assert result.bands_hz == EXPECTED_BANDS
    assert len(result.band_energies_db) == len(EXPECTED_BANDS)
    # A pure 440 Hz sine leaves out-of-band energies at the float floor, so
    # the contract only requires non-positive, finite measurements.
    assert all(np.isfinite(e) and e <= 0.0 for e in result.band_energies_db)
