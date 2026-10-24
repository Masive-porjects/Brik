"""Tests for the Layer 3 Crudo reference render (fair A/B comparison).

Verifies ``POST /session/{id}/reference/{preset_id}``: the neutral-chain
parameters with preset-overridden loudness targets, per session+preset
caching, and the 404/400 guards. DSP is stubbed — route-level tests only.
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

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch):
    sessions.clear()
    # Force development mode so require_license allows all requests
    monkeypatch.setattr(settings, "license_key", "")
    yield
    sessions.clear()


def _tiny_wav(path, duration_s=0.1):
    """Write a tiny valid WAV."""
    import soundfile as sf

    sr = 8000
    t = np.linspace(0, duration_s, int(sr * duration_s), endpoint=False)
    wave = 0.1 * np.sin(2 * np.pi * 220 * t)
    sf.write(str(path), wave, sr)


def _make_session(name="ref"):
    resp = client.post("/api/session/new", json={"name": name})
    assert resp.status_code == 200
    session_id = resp.json()["session_id"]
    session = sessions[session_id]
    original = settings.upload_dir / f"{session_id}_orig.wav"
    _tiny_wav(original)
    session.original_path = str(original.resolve())
    return session_id


def _stub_process(monkeypatch, captured=None):
    """Stub the DSP pipeline; optionally capture the call kwargs."""
    import audiomind.api.mastering as mastering_mod

    calls = {"n": 0}

    def _fake_process(input_path, output_path, params, **kwargs):
        calls["n"] += 1
        if captured is not None:
            captured["params"] = params
            captured["analysis"] = kwargs.get("analysis_result")
        Path(output_path).write_bytes(b"FAKE-REFERENCE-WAV")
        return {"output_path": str(Path(output_path).resolve())}

    monkeypatch.setattr(mastering_mod, "process_audio", _fake_process)
    # Analysis would run on first render (no analysis on a fresh session);
    # stub it like test_prebuilt_lookup does.
    monkeypatch.setattr(mastering_mod, "analyze_audio", lambda _p: None)
    return calls


class TestReferenceRender:
    def test_unknown_session_returns_404(self):
        resp = client.post("/api/session/does-not-exist/reference/fuego")
        assert resp.status_code == 404

    def test_unknown_preset_returns_400(self):
        session_id = _make_session()
        resp = client.post(f"/api/session/{session_id}/reference/not-a-preset")
        assert resp.status_code == 400

    def test_renders_neutral_chain_with_preset_targets(self, monkeypatch):
        """Natural character + the SOURCE preset's loudness overrides."""
        session_id = _make_session()
        captured = {}
        _stub_process(monkeypatch, captured)

        resp = client.post(f"/api/session/{session_id}/reference/fuego")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["source_preset_id"] == "fuego"
        assert data["target_lufs"] == -12  # fuego's target, not natural's -14
        assert Path(data["reference_path"]).exists()
        assert Path(data["reference_path"]).read_bytes() == b"FAKE-REFERENCE-WAV"

        params = captured["params"]
        # Neutral chain character — PRESET_CHAINS["natural"]
        assert params.compression_ratio == pytest.approx(1.1)
        assert params.clarity_brightness_db == 0
        assert params.saturation_drive_db == 0
        assert params.saturation_warmth_db == 0
        assert params.clarity_wet == 0
        assert params.transient_boost_db == 0
        assert params.stereo_width == pytest.approx(1.0)
        assert params.haas_delay_ms == 0
        # Loudness overridden with the source preset's targets
        assert params.target_lufs_db == pytest.approx(-12)
        assert params.limiter_ceiling_db == pytest.approx(-1.0)

    def test_cache_hit_skips_rerender(self, monkeypatch):
        session_id = _make_session()
        calls = _stub_process(monkeypatch)

        first = client.post(f"/api/session/{session_id}/reference/natural")
        assert first.status_code == 200, first.text
        second = client.post(f"/api/session/{session_id}/reference/natural")
        assert second.status_code == 200, second.text
        assert calls["n"] == 1, "cache hit must not re-render"

        # Same response shape on the cache hit
        assert second.json()["source_preset_id"] == "natural"
        assert second.json()["target_lufs"] == -14

    def test_reference_audio_404_before_render(self):
        """The playback endpoint must not serve anything pre-render."""
        session_id = _make_session()
        resp = client.get(f"/api/session/{session_id}/audio/reference/fuego")
        assert resp.status_code == 404
