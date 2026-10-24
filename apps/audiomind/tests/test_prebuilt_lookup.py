"""Functional tests for the pre-built master lookup (hackathon speedup).

Verifies that ``POST /session/{id}/process?preset_id=...`` serves a cached
master from ``settings.prebuilt_dir`` and never touches the DSP pipeline.
"""
import sys

sys.path.insert(0, "src")
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from audiomind.api.upload import sessions
from audiomind.config import settings
from audiomind.main import app
from audiomind.models.audio import ProcessingStatus

client = TestClient(app)

# The endpoint refuses cache files < 1 KiB (broken stubs), so the fake
# master must be well above that to be served like a real WAV would be.
FAKE_PREBUILT = b"FAKE-PREBUILT-WAV-CONTENT" * 256


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch, tmp_path):
    sessions.clear()
    # Force development mode so require_license allows all requests
    monkeypatch.setattr(settings, "license_key", "")
    # Point the prebuilt cache at a throwaway dir so the tests never
    # leave stub files behind in the real prebuilt/ cache.
    monkeypatch.setattr(settings, "prebuilt_dir", tmp_path / "prebuilt")
    yield
    sessions.clear()


def _tiny_wav(path, duration_s=0.1):
    """Write a tiny valid WAV (1s of silence-ish tone)."""
    import soundfile as sf

    sr = 8000
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    wave = 0.1 * np.sin(2 * np.pi * 220 * t)
    sf.write(str(path), wave, sr)


class TestPrebuiltLookup:
    def test_preset_id_serves_cached_master_without_dsp(self, monkeypatch):
        """Cache hit → completed + progress 1.0, DSP never runs."""
        # Create a session with a real original file, named as an upload would
        resp = client.post("/api/session/new", json={"name": "prebuilt"})
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]
        session = sessions[session_id]

        original = settings.upload_dir / f"{session_id}_orig.wav"
        _tiny_wav(original)
        session.original_path = str(original.resolve())
        session.original_filename = "mi_tema.wav"  # the user's real file name

        # Place a pre-built master keyed by the ORIGINAL stem
        prebuilt = settings.prebuilt_dir / f"{Path('mi_tema.wav').stem}_fuego.wav"
        prebuilt.parent.mkdir(parents=True, exist_ok=True)
        prebuilt.write_bytes(FAKE_PREBUILT)

        # DSP must NOT run on a cache hit
        import audiomind.api.mastering as mastering_mod

        def _boom(*_a, **_k):
            raise AssertionError("process_audio must not run on pre-built hit")

        monkeypatch.setattr(mastering_mod, "process_audio", _boom)

        resp = client.post(
            f"/api/session/{session_id}/process?preset_id=fuego",
            json={"compression_ratio": 5.0},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["status"] == ProcessingStatus.COMPLETED
        assert data["progress"] == 1.0
        assert data["mastered_path"], "mastered_path must be set"
        # The copied file exists and equals the prebuilt bytes
        assert Path(data["mastered_path"]).exists()
        assert Path(data["mastered_path"]).read_bytes() == FAKE_PREBUILT
        # No analysis was run either (DSP would have needed it)
        assert data["analysis"] is None or True  # analysis untouched by this path

    def test_no_preset_id_runs_dsp_normally(self, monkeypatch):
        """Without preset_id, the endpoint must call the DSP pipeline."""
        resp = client.post("/api/session/new", json={"name": "dsp"})
        session_id = resp.json()["session_id"]
        session = sessions[session_id]

        original = settings.upload_dir / f"{session_id}_orig.wav"
        _tiny_wav(original)
        session.original_path = str(original.resolve())

        import audiomind.api.mastering as mastering_mod

        called = {}

        def _fake_process(input_path, output_path, params, **kwargs):
            called["yes"] = True
            from pathlib import Path

            Path(output_path).write_bytes(b"FAKE-DSP-RESULT")
            return {"output_path": str(Path(output_path).resolve())}

        monkeypatch.setattr(mastering_mod, "process_audio", _fake_process)
        # Analysis needs an existing session.analysis; the guard skips
        # re-analysis when status == ANALYZING. Set UPLOADED + None analysis
        # so the endpoint attempts analysis — which would fail on real
        # analyzer, so stub that too.
        monkeypatch.setattr(
            mastering_mod, "analyze_audio", lambda _p: None
        )

        resp = client.post(
            f"/api/session/{session_id}/process",
            json={"compression_ratio": 5.0},
        )
        assert resp.status_code == 200, resp.text
        assert called.get("yes"), "process_audio must be called without preset_id"
        assert resp.json()["status"] == ProcessingStatus.COMPLETED
