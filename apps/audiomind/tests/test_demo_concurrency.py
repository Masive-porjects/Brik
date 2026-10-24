"""Tests for demo-mode concurrency: single-flight dedup and global serialization."""
import sys

sys.path.insert(0, "src")

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from audiomind.api.upload import sessions
from audiomind.config import settings
from audiomind.main import app
from audiomind.services import demo_guard

client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    sessions.clear()
    demo_guard.clear_flights()
    demo_guard.clear_activity()
    monkeypatch.setattr(settings, "license_key", "")
    monkeypatch.setattr(settings, "max_concurrent_dsp", 1)
    demo_guard.reset_gate()
    yield
    demo_guard.clear_flights()
    demo_guard.clear_activity()
    sessions.clear()


# ── Helpers ──────────────────────────────────────────────────────────


def _tiny_wav(path, sr=8000, duration=0.5):
    """Write a tiny valid WAV."""
    t = np.linspace(0, duration, int(sr * duration), endpoint=False)
    wave = 0.1 * np.sin(2 * np.pi * 220 * t)
    sf.write(str(path), wave, sr)


def _make_session(name="concurrency"):
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
    """Stub process_audio: writes fake output, optionally counts calls."""
    lock = Lock()

    def _fake(input_path, output_path, params, **kwargs):
        if call_counter is not None:
            with lock:
                call_counter["n"] += 1
        Path(output_path).write_bytes(b"FAKE")
        return {
            "output_path": str(Path(output_path).resolve()),
            # -13 LUFS is within ±1.5 tolerance of every preset target.
            "integrated_lufs": -13.0,
            "true_peak_db": -1.0,
            "crest_factor_db": 10.0,
        }

    return _fake


# ── Single-flight ────────────────────────────────────────────────────


class TestDemoSingleFlight:
    def test_single_flight_same_preset(self, monkeypatch):
        """N=5 concurrent /process for same preset -> exactly 1 DSP call."""
        import audiomind.api.mastering as mastering_mod

        active = {"count": 0, "max": 0}
        calls = {"n": 0}
        lock = Lock()

        def _slow(input_path, output_path, params, **kwargs):
            with lock:
                calls["n"] += 1
                active["count"] += 1
                active["max"] = max(active["max"], active["count"])
            time.sleep(0.3)
            with lock:
                active["count"] -= 1
            Path(output_path).write_bytes(b"FAKE")
            return {
                "output_path": str(Path(output_path).resolve()),
                # -13 LUFS within ±1.5 of all preset targets
                "integrated_lufs": -13.0,
                "true_peak_db": -1.0,
                "crest_factor_db": 10.0,
            }

        monkeypatch.setattr(mastering_mod, "process_audio", _slow)
        monkeypatch.setattr(mastering_mod, "analyze_audio", lambda _p: None)

        sid = _make_session()

        def do_process():
            resp = client.post(
                f"/api/session/{sid}/process?preset_id=fuego", json={}
            )
            return resp.status_code

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(do_process) for _ in range(5)]
            results = [f.result() for f in futures]

        assert all(r == 200 for r in results), f"Some requests failed: {results}"
        assert calls["n"] == 1, f"Single-flight violated: {calls['n']} calls"
        assert active["max"] == 1


# ── Global serialization ─────────────────────────────────────────────


class TestDemoGlobalSerialization:
    def test_serialization_different_presets(self, monkeypatch):
        """2 DIFFERENT presets, max_concurrent_dsp=1 -> serialized execution."""
        import audiomind.api.mastering as mastering_mod

        active = {"count": 0, "max": 0}
        calls = {"n": 0}
        lock = Lock()

        def _slow(input_path, output_path, params, **kwargs):
            with lock:
                calls["n"] += 1
                active["count"] += 1
                active["max"] = max(active["max"], active["count"])
            time.sleep(0.3)
            with lock:
                active["count"] -= 1
            Path(output_path).write_bytes(b"FAKE")
            return {
                "output_path": str(Path(output_path).resolve()),
                # -13 LUFS within ±1.5 of all preset targets
                "integrated_lufs": -13.0,
                "true_peak_db": -1.0,
                "crest_factor_db": 10.0,
            }

        monkeypatch.setattr(mastering_mod, "process_audio", _slow)
        monkeypatch.setattr(mastering_mod, "analyze_audio", lambda _p: None)

        sid = _make_session()

        def do_process(preset_id):
            resp = client.post(
                f"/api/session/{sid}/process?preset_id={preset_id}", json={}
            )
            return resp.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(do_process, "fuego")
            f2 = pool.submit(do_process, "cinta")
            r1, r2 = f1.result(), f2.result()

        assert r1 == 200 and r2 == 200
        assert calls["n"] == 2, f"Expected 2 DSP calls, got {calls['n']}"
        assert active["max"] == 1, (
            f"Max active was {active['max']}, expected 1 (serialized)"
        )


# ── No 500s ──────────────────────────────────────────────────────────


class TestDemoNoErrors:
    def test_no_500s_concurrent(self, monkeypatch):
        """Concurrent requests for different presets produce no 500 errors."""
        import audiomind.api.mastering as mastering_mod

        monkeypatch.setattr(mastering_mod, "process_audio", _make_process_stub())
        monkeypatch.setattr(mastering_mod, "analyze_audio", lambda _p: None)

        sid = _make_session()

        def do_process(preset_id):
            resp = client.post(
                f"/api/session/{sid}/process?preset_id={preset_id}", json={}
            )
            return resp.status_code

        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [
                pool.submit(do_process, pid)
                for pid in ["fuego", "cinta", "claridad"]
            ]
            results = [f.result() for f in futures]

        assert all(r == 200 for r in results), f"Some requests got 500: {results}"
