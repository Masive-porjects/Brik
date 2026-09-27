"""Tests for demo-mode client behavior: on_demand upload, preset processing,
cache hit, multi-preset, download, normal mode prerender, duration limit, MP3."""
import sys
sys.path.insert(0, "src")

import shutil
import subprocess
import time
from pathlib import Path
from threading import Lock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from audiomind.main import app
from audiomind.config import settings
from audiomind.api.upload import sessions
from audiomind.api.mastering import _prerender_cache
from audiomind.services import demo_guard
from audiomind.models.audio import AnalysisResult, ProcessingStatus
import soundfile as sf

client = TestClient(app)

PRESET_IDS = [
    "universal", "fuego", "claridad", "cinta",
    "natural", "espacial", "cinematico", "empuje",
]

_DUMMY_ANALYSIS = AnalysisResult(
    integrated_lufs=-18.0,
    true_peak_db=-6.0,
    dynamic_range_db=10.0,
    spectral_centroid=2000.0,
    tempo_bpm=100.0,
    duration_seconds=30.0,
    sample_rate=44100,
    channels=2,
    detected_genre="Trap",
    genre_confidence=0.9,
)


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch):
    sessions.clear()
    _prerender_cache.clear()
    demo_guard.clear_flights()
    demo_guard.clear_activity()
    monkeypatch.setattr(settings, "license_key", "")
    yield
    sessions.clear()
    _prerender_cache.clear()
    demo_guard.clear_flights()
    demo_guard.clear_activity()


# ── Helpers ──────────────────────────────────────────────────────────


def _tiny_wav(path, sr=8000, duration=0.5):
    """Write a tiny valid WAV."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    wave = 0.1 * np.sin(2 * np.pi * 220 * t)
    sf.write(str(path), wave, sr)


def _make_session(name="demo"):
    """Create a session via /api/session/new with a fake original file."""
    resp = client.post("/api/session/new", json={"name": name})
    assert resp.status_code == 200
    sid = resp.json()["session_id"]
    session = sessions[sid]
    original = settings.upload_dir / f"{sid}_orig.wav"
    _tiny_wav(original)
    session.original_path = str(original.resolve())
    return sid


def _make_process_stub(call_counter=None):
    """Stub process_audio: writes unique fake output, optionally counts calls."""
    lock = Lock()

    def _fake(input_path, output_path, params, **kwargs):
        if call_counter is not None:
            with lock:
                call_counter["n"] += 1
        content = f"FAKE-MASTERED-{Path(output_path).stem}".encode()
        Path(output_path).write_bytes(content)
        return {
            "output_path": str(Path(output_path).resolve()),
            # -13 LUFS is within ±1.5 tolerance of every preset target
            # (-14, -13, -12) so _retry_once_on_lufs_miss never fires.
            "integrated_lufs": -13.0,
            "true_peak_db": -1.0,
            "crest_factor_db": 10.0,
            "duration_seconds": 30.0,
            "sample_rate": 44100,
            "output_bit_depth": 24,
            "stereo_correlation": 0.9,
            "lra": 8.0,
        }

    return _fake


# ── Upload in on_demand mode ─────────────────────────────────────────


class TestDemoOnDemandUpload:
    def test_upload_no_dsp(self, monkeypatch, tmp_path):
        """Upload in on_demand mode triggers 0 process_audio calls."""
        monkeypatch.setattr(settings, "prerender_mode", "on_demand")
        import audiomind.api.mastering as mastering_mod

        calls = {"n": 0}
        monkeypatch.setattr(mastering_mod, "process_audio", _make_process_stub(calls))

        wav_path = tmp_path / "test.wav"
        t = np.linspace(0, 1, 8000, endpoint=False)
        sf.write(
            str(wav_path),
            (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32),
            8000,
        )

        with open(wav_path, "rb") as f:
            resp = client.post(
                "/api/upload", files={"file": ("test.wav", f, "audio/wav")}
            )
        assert resp.status_code == 200

        # In on_demand mode no process_audio fires during upload
        assert calls["n"] == 0, f"process_audio called {calls['n']}x in on_demand mode"


# ── Preset processing ───────────────────────────────────────────────


class TestDemoPresets:
    @pytest.mark.parametrize("preset_id", PRESET_IDS)
    def test_all_presets(self, preset_id, monkeypatch):
        """Each of the 8 preset IDs works via /process?preset_id=X."""
        import audiomind.api.mastering as mastering_mod

        calls = {"n": 0}
        monkeypatch.setattr(mastering_mod, "process_audio", _make_process_stub(calls))
        monkeypatch.setattr(mastering_mod, "analyze_audio", lambda _p: _DUMMY_ANALYSIS)

        sid = _make_session()
        resp = client.post(
            f"/api/session/{sid}/process?preset_id={preset_id}",
            json={},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == ProcessingStatus.COMPLETED

        session = sessions[sid]
        assert preset_id in session.preset_masters
        assert session.preset_masters[preset_id].status == "completed"
        assert calls["n"] == 1


# ── Cache hit ────────────────────────────────────────────────────────


class TestDemoCacheHit:
    def test_second_process_skips_dsp(self, monkeypatch):
        """Second /process for same preset -> still 1 process_audio call."""
        import audiomind.api.mastering as mastering_mod

        calls = {"n": 0}
        monkeypatch.setattr(mastering_mod, "process_audio", _make_process_stub(calls))
        monkeypatch.setattr(mastering_mod, "analyze_audio", lambda _p: _DUMMY_ANALYSIS)

        sid = _make_session()
        resp1 = client.post(f"/api/session/{sid}/process?preset_id=fuego", json={})
        assert resp1.status_code == 200
        assert calls["n"] == 1

        resp2 = client.post(f"/api/session/{sid}/process?preset_id=fuego", json={})
        assert resp2.status_code == 200
        assert calls["n"] == 1, "Cache hit must not re-run DSP"


# ── Multi-preset ─────────────────────────────────────────────────────


class TestDemoMultiPreset:
    def test_three_presets_create_files(self, monkeypatch):
        """Process 3 presets -> 3 output files + 3 entries in preset_masters."""
        import audiomind.api.mastering as mastering_mod

        monkeypatch.setattr(mastering_mod, "process_audio", _make_process_stub())
        monkeypatch.setattr(mastering_mod, "analyze_audio", lambda _p: _DUMMY_ANALYSIS)

        sid = _make_session()
        for pid in ["universal", "fuego", "cinta"]:
            resp = client.post(f"/api/session/{sid}/process?preset_id={pid}", json={})
            assert resp.status_code == 200, resp.text

        session = sessions[sid]
        for pid in ["universal", "fuego", "cinta"]:
            expected = settings.output_dir / f"{sid}_{pid}_mastered.wav"
            assert expected.exists(), f"Output file missing for {pid}"
            assert pid in session.preset_masters
            assert session.preset_masters[pid].status == "completed"


# ── Download serves correct preset ───────────────────────────────────


class TestDemoDownload:
    def test_download_matches_processed_preset(self, monkeypatch):
        """GET /download/wav?preset_id=fuego serves fuego's file, not cinta's."""
        import audiomind.api.mastering as mastering_mod

        monkeypatch.setattr(mastering_mod, "process_audio", _make_process_stub())
        monkeypatch.setattr(mastering_mod, "analyze_audio", lambda _p: _DUMMY_ANALYSIS)

        sid = _make_session()
        client.post(f"/api/session/{sid}/process?preset_id=fuego", json={})
        client.post(f"/api/session/{sid}/process?preset_id=cinta", json={})

        fuego_path = settings.output_dir / f"{sid}_fuego_mastered.wav"
        cinta_path = settings.output_dir / f"{sid}_cinta_mastered.wav"
        assert fuego_path.exists()
        assert cinta_path.exists()
        assert fuego_path.read_bytes() != cinta_path.read_bytes()

        resp = client.get(f"/api/session/{sid}/download/wav?preset_id=fuego")
        assert resp.status_code == 200
        assert resp.content == fuego_path.read_bytes()

    def test_download_filename_uses_original_title(self, monkeypatch):
        """Content-Disposition names the master after the original upload:
        'beatRap.wav' → 'BeatRapMasterizado.wav' (first letter capitalized)."""
        import audiomind.api.mastering as mastering_mod

        monkeypatch.setattr(mastering_mod, "process_audio", _make_process_stub())
        monkeypatch.setattr(mastering_mod, "analyze_audio", lambda _p: _DUMMY_ANALYSIS)

        sid = _make_session()
        sessions[sid].original_filename = "beatRap.wav"
        client.post(f"/api/session/{sid}/process?preset_id=universal", json={})

        resp = client.get(f"/api/session/{sid}/download/wav?preset_id=universal")
        assert resp.status_code == 200
        assert resp.headers["content-disposition"] == (
            'attachment; filename="BeatRapMasterizado.wav"'
        )

        resp_mp3 = client.get(f"/api/session/{sid}/download/mp3?preset_id=universal")
        if resp_mp3.status_code == 200:
            # MP3 conversion needs ffmpeg on PATH — environmental; name logic
            # is the same, so assert the header only when conversion ran.
            assert resp_mp3.headers["content-disposition"] == (
                'attachment; filename="BeatRapMasterizado.mp3"'
            )

    def test_download_filename_falls_back_without_original(self, monkeypatch):
        """Sessions without an original filename keep the legacy name."""
        import audiomind.api.mastering as mastering_mod

        monkeypatch.setattr(mastering_mod, "process_audio", _make_process_stub())
        monkeypatch.setattr(mastering_mod, "analyze_audio", lambda _p: _DUMMY_ANALYSIS)

        sid = _make_session()
        client.post(f"/api/session/{sid}/process?preset_id=fuego", json={})

        resp = client.get(f"/api/session/{sid}/download/wav?preset_id=fuego")
        assert resp.status_code == 200
        assert resp.headers["content-disposition"] == (
            'attachment; filename="WaveAIFinal.wav"'
        )


# ── Normal mode prerender ────────────────────────────────────────────


class TestDemoNormalMode:
    def test_prerender_all_presets(self, monkeypatch, tmp_path):
        """prerender_mode=all -> upload triggers 8-entry prerender cache."""
        import audiomind.api.mastering as mastering_mod

        monkeypatch.setattr(mastering_mod, "process_audio", _make_process_stub())
        try:
            import audiomind.analysis.analyzer as analyzer_mod

            monkeypatch.setattr(
                analyzer_mod, "analyze_audio", lambda _p: _DUMMY_ANALYSIS
            )
        except ImportError:
            pytest.skip("Cannot import audiomind.analysis.analyzer")

        wav_path = tmp_path / "test.wav"
        t = np.linspace(0, 1, 8000, endpoint=False)
        sf.write(
            str(wav_path),
            (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32),
            8000,
        )

        with open(wav_path, "rb") as f:
            resp = client.post(
                "/api/upload", files={"file": ("test.wav", f, "audio/wav")}
            )
        assert resp.status_code == 200
        sid = resp.json()["session_id"]

        # Wait for background analysis + prerender to complete
        for _ in range(200):
            cache = _prerender_cache.get(sid)
            if cache and len(cache) == 8:
                completed = sum(1 for v in cache.values() if v["status"] == "completed")
                if completed == 8:
                    break
            time.sleep(0.05)
        else:
            pytest.fail("Prerender did not complete within timeout")

        assert len(_prerender_cache[sid]) == 8


# ── Duration limit ───────────────────────────────────────────────────


class TestDemoDurationLimit:
    def test_rejects_long_audio(self, monkeypatch, tmp_path):
        """61s WAV -> 422 with demo duration message."""
        monkeypatch.setattr(settings, "demo_max_duration_seconds", 60.0)
        long_wav = tmp_path / "long.wav"
        samples = np.zeros((44100 * 61, 2), dtype=np.float32)
        sf.write(str(long_wav), samples, 44100)

        with open(long_wav, "rb") as f:
            resp = client.post(
                "/api/upload", files={"file": ("long.wav", f, "audio/wav")}
            )
        assert resp.status_code == 422
        assert "Demo: carga hasta 60 segundos de audio." in resp.json()["detail"]

    def test_accepts_short_audio(self, monkeypatch, tmp_path):
        """30s WAV -> 200."""
        monkeypatch.setattr(settings, "demo_max_duration_seconds", 60.0)
        short_wav = tmp_path / "short.wav"
        samples = np.zeros((44100 * 30, 2), dtype=np.float32)
        sf.write(str(short_wav), samples, 44100)

        with open(short_wav, "rb") as f:
            resp = client.post(
                "/api/upload", files={"file": ("short.wav", f, "audio/wav")}
            )
        assert resp.status_code == 200

    def test_mp3_accepted(self, tmp_path):
        """MP3 upload accepted when ffmpeg available."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            pytest.skip("ffmpeg not available")

        mp3_path = tmp_path / "tiny.mp3"
        result = subprocess.run(
            [
                ffmpeg,
                "-f", "lavfi",
                "-i", "sine=frequency=440:duration=1",
                "-codec:a", "libmp3lame",
                "-b:a", "128k",
                "-y", str(mp3_path),
            ],
            capture_output=True,
            timeout=10,
        )
        assert result.returncode == 0, f"ffmpeg failed: {result.stderr.decode()}"

        with open(mp3_path, "rb") as f:
            resp = client.post(
                "/api/upload", files={"file": ("tiny.mp3", f, "audio/mpeg")}
            )
        assert resp.status_code == 200
