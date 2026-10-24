"""Integration tests for SongStarter API (Module D, Phase 5).

Tests the full REST API: generate, save, list, load, audio serve, delete.
"""
import sys

sys.path.insert(0, "src")

import pytest
from fastapi.testclient import TestClient

from audiomind.main import app

client = TestClient(app)


class TestSongStarterAPI:
    """Integration tests for SongStarter endpoints."""

    @pytest.fixture(autouse=True)
    def setup_session(self):
        """Create a fresh test session before each test."""
        resp = client.post("/api/session/new", json={"name": "test_songstarter"})
        assert resp.status_code == 200, f"Session creation failed: {resp.text}"
        self.session_id = resp.json()["session_id"]
        yield

    # ── 5.4 Integration: Generate beat → 200 ──────────────────────────────

    def test_generate_beat_returns_200_with_beat_data(self):
        """POST /api/session/{id}/beat/generate devuelve BeatData."""
        resp = client.post(
            f"/api/session/{self.session_id}/beat/generate",
            json={
                "bpm": 120,
                "scale": "major",
                "root_note": "C",
                "swing_amount": 0.3,
            },
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert "beat_id" in data, "Falta beat_id"
        assert data["bpm"] == 120
        assert data["scale"] == "major"
        assert data["root_note"] == "C"
        assert "stems" in data
        assert "output_path" in data

    # ── 5.5 Integration: CRUD cycle ──────────────────────────────────────

    def test_beat_crud_cycle(self):
        """Save → List → Load → Delete."""
        # Generate
        gen = client.post(
            f"/api/session/{self.session_id}/beat/generate",
            json={"bpm": 120, "scale": "major", "root_note": "C"},
        )
        assert gen.status_code == 200, f"Generate failed: {gen.text}"
        beat_id = gen.json()["beat_id"]

        # Save
        save = client.post("/api/beat/save", json={
            "session_id": self.session_id,
            "beat_id": beat_id,
            "name": "test-beat",
        })
        assert save.status_code == 200, f"Save failed: {save.text}"

        # List
        lst = client.get("/api/beats")
        assert lst.status_code == 200
        saved = [b for b in lst.json() if b["id"] == beat_id]
        assert len(saved) >= 1, f"Beat {beat_id} no encontrado en lista"

        # Load
        load = client.get(f"/api/beat/{beat_id}")
        assert load.status_code == 200
        assert load.json()["bpm"] == 120

        # Delete
        delete = client.delete(f"/api/beat/{beat_id}")
        assert delete.status_code == 200

        # Verify deleted (404)
        load_again = client.get(f"/api/beat/{beat_id}")
        assert load_again.status_code == 404

    # ── 5.6 Integration: GET audio returns WAV ───────────────────────────

    def test_get_beat_audio_returns_wav(self):
        """GET /api/session/{id}/beat/{beat_id}/audio → 200 + audio/wav."""
        gen = client.post(
            f"/api/session/{self.session_id}/beat/generate",
            json={"bpm": 120, "scale": "major", "root_note": "C"},
        )
        assert gen.status_code == 200, f"Generate failed: {gen.text}"
        beat_id = gen.json()["beat_id"]

        # Get audio
        resp = client.get(
            f"/api/session/{self.session_id}/beat/{beat_id}/audio"
        )
        assert resp.status_code == 200, (
            f"Audio failed: {resp.status_code}"
        )
        assert resp.headers["content-type"] == "audio/wav", (
            f"Expected audio/wav, got {resp.headers.get('content-type')}"
        )
        assert len(resp.content) > 1000, (
            f"Audio too small: {len(resp.content)} bytes"
        )
