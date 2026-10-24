"""Tests for ``POST /session/{id}/reset`` — reverts the mastered state.

The reset endpoint clears every master pointer and per-preset output so the
player falls back to original-only, while keeping the uploaded original (and
its analysis) intact. Rendered WAV files stay on disk, untracked.
"""
import sys

sys.path.insert(0, "src")
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from audiomind.api.upload import sessions
from audiomind.config import settings
from audiomind.main import app
from audiomind.models.audio import (
    MasterResultMetrics,
    PresetMasterEntry,
    ProcessingStatus,
    ValidationReport,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch, tmp_path):
    sessions.clear()
    # Force development mode so require_license allows all requests
    monkeypatch.setattr(settings, "license_key", "")
    yield
    sessions.clear()


def _seed_mastered_session(tmp_path) -> tuple[str, Path]:
    """Create a session shaped like a completed, per-preset mastered one."""
    resp = client.post("/api/session/new", json={"name": "resetme"})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]
    session = sessions[session_id]

    original = tmp_path / f"{session_id}_orig.wav"
    original.write_bytes(b"RIFFtiny-fake")  # endpoint never reads the audio
    mastered = tmp_path / f"{session_id}_mastered.wav"
    mastered.write_bytes(b"RIFFtiny-fake")

    session.original_path = str(original.resolve())
    session.original_filename = "cliente.wav"
    session.status = ProcessingStatus.COMPLETED
    session.progress = 1.0
    session.mastered_path = str(mastered.resolve())
    session.master_result = MasterResultMetrics(
        integrated_lufs=-14.2, true_peak_db=-1.05
    )
    session.validation = ValidationReport(status="ok")
    session.preset_masters["universal"] = PresetMasterEntry(
        preset_id="universal",
        output_path=str(mastered.resolve()),
        status="completed",
        progress=1.0,
    )
    return session_id, mastered


class TestResetSession:
    def test_reset_clears_master_and_keeps_original(self, tmp_path):
        session_id, mastered = _seed_mastered_session(tmp_path)

        resp = client.post(f"/api/session/{session_id}/reset")
        assert resp.status_code == 200
        body = resp.json()

        # Mastered state is gone…
        assert body["mastered_path"] is None
        assert body["preset_masters"] == {}
        assert body["master_result"] is None
        assert body["validation"] is None
        assert body["status"] == "uploaded"
        assert body["progress"] == 0.0
        # …but the uploaded original (and its analysis bucket) is untouched
        assert body["original_path"] == str(
            (tmp_path / f"{session_id}_orig.wav").resolve()
        )
        assert body["original_filename"] == "cliente.wav"
        # Rendered files stay on disk, untracked
        assert mastered.exists()

    def test_reset_accepts_already_reset_session(self, tmp_path):
        session_id, _ = _seed_mastered_session(tmp_path)
        first = client.post(f"/api/session/{session_id}/reset")
        second = client.post(f"/api/session/{session_id}/reset")
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["preset_masters"] == {}

    def test_reset_unknown_session_404(self):
        resp = client.post("/api/session/no-such-id/reset")
        assert resp.status_code == 404