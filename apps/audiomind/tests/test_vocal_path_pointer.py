"""T8 — the vocal chain writes its OWN pointer, never the master pointer.

``POST /session/{id}/vocal`` used to assign its output to
``session.mastered_path``, so a session that only ran the vocal chain looked
like it had a master: ``/audio/mastered``, ``/raw-mastered`` and
``/download/{format}`` all serve ``mastered_path``, so the client could
download a processed VOICE believing it was a master. Same contract the mix
follows (``mix_path`` + ``mix_status``, T2): the vocal gets its own optional
pointer, exposed by ``GET /session/{id}`` and cleared by ``POST /reset``.

The chain is stubbed in most tests — the contract under test is WHICH field
the output lands in, not the DSP — plus one real-chain test proving the
recorded pointer is the file the engine actually wrote.
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "src")

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import audiomind.processing.vocal as vocal_engine
from audiomind.api.upload import sessions
from audiomind.config import settings
from audiomind.main import app
from audiomind.models.audio import ProcessingStatus, SessionData

client = TestClient(app)

_SR = 44100
_PARAMS = {
    "deesser_amount": 0.3,
    "pitch_shift_semitones": 0.0,
    "cohesion_amount": 0.4,
}
# Bytes written by the stubbed chain — distinguishable from any real WAV.
_FAKE_VOCAL = b"FAKE-VOCAL-CHAIN-OUTPUT"


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch, tmp_path):
    sessions.clear()
    # Force development mode so require_license allows all requests
    monkeypatch.setattr(settings, "license_key", "")
    # Keep every rendered vocal out of the repo's real outputs/ directory.
    monkeypatch.setattr(settings, "output_dir", tmp_path / "outputs")
    yield
    sessions.clear()


def _write_tone(path: Path, hz: float, seconds: float = 1.0) -> None:
    """Write a short mono sine tone (synthetic fixture, no DSP deps)."""
    t = np.linspace(0.0, seconds, int(_SR * seconds), endpoint=False)
    sf.write(str(path), 0.25 * np.sin(2.0 * np.pi * hz * t), _SR, subtype="PCM_16")


def _register_session(tmp_path: Path, session_id: str | None = None) -> str:
    """Insert a session with a real original directly into the store.

    Bypasses ``/api/upload`` so no background analysis or pre-render fires;
    the endpoint only needs ``original_path`` to exist.
    """
    sid = session_id or str(uuid.uuid4())
    original = tmp_path / f"{sid}_input.wav"
    _write_tone(original, hz=220.0)
    sessions[sid] = SessionData(
        session_id=sid,
        status=ProcessingStatus.UPLOADED,
        original_path=str(original),
        original_filename=original.name,
    )
    return sid


def _stub_chain(monkeypatch) -> list[str]:
    """Stand-in for the engine: writes the requested file, records its input.

    ``vocal.py`` imports ``process_vocal`` inside the request handler, so
    patching the module attribute is enough to intercept the call.
    """
    seen: list[str] = []

    def _fake_process_vocal(input_path, output_path, params, progress_cb=None):
        seen.append(str(input_path))
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_FAKE_VOCAL)
        if progress_cb is not None:
            progress_cb(1.0)
        return {"output_path": str(out.resolve()), "gain_reduction_db": -1.5}

    monkeypatch.setattr(vocal_engine, "process_vocal", _fake_process_vocal)
    return seen


def _boom_chain(monkeypatch) -> None:
    """Chain stand-in that always fails (induces the 500 path)."""

    def _fake(*_a, **_k):
        raise RuntimeError("synthetic vocal chain failure")

    monkeypatch.setattr(vocal_engine, "process_vocal", _fake)


def _vocal(session_id: str) -> dict:
    resp = client.post(f"/api/session/{session_id}/vocal", json=_PARAMS)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _convention_path(session_id: str) -> Path:
    return settings.output_dir / f"{session_id}_vocal.wav"


# ── The pointer contract (T8.1) ─────────────────────────────────────────


class TestVocalPointerIsNotTheMaster:
    """The processed vocal must never be served as "the master"."""

    def test_output_lands_on_vocal_path_only(self, tmp_path, monkeypatch):
        """A vocal-only session has ``vocal_path``, and NO master pointer."""
        seen = _stub_chain(monkeypatch)
        session_id = _register_session(tmp_path)
        assert sessions[session_id].vocal_path is None

        body = _vocal(session_id)

        session = sessions[session_id]
        assert session.vocal_path == str(_convention_path(session_id).resolve())
        assert Path(session.vocal_path).exists()
        # The bug: this used to be the field the vocal chain wrote.
        assert session.mastered_path is None
        # Response shape unchanged for the frontend /voz player.
        assert body["output_path"] == session.vocal_path
        assert body["status"] == "completed"
        assert body["gain_reduction_db"] == -1.5
        assert session.status == ProcessingStatus.COMPLETED
        # …and the chain still consumed the session original.
        assert seen == [session.original_path]

    def test_existing_master_survives_the_vocal_run(
        self, tmp_path, monkeypatch
    ):
        """A real master stays the master after the vocal chain runs."""
        _stub_chain(monkeypatch)
        session_id = _register_session(tmp_path)
        mastered = tmp_path / f"{session_id}_mastered.wav"
        _write_tone(mastered, hz=110.0)
        master_bytes = mastered.read_bytes()
        sessions[session_id].mastered_path = str(mastered)

        _vocal(session_id)

        session = sessions[session_id]
        assert session.mastered_path == str(mastered)
        assert session.vocal_path != session.mastered_path
        # Every master-serving surface still serves the MASTER, not the vocal.
        for url in (
            f"/api/session/{session_id}/audio/mastered",
            f"/api/session/{session_id}/download/wav",
        ):
            resp = client.get(url)
            assert resp.status_code == 200, url
            assert resp.content == master_bytes, url
        raw = client.get(f"/api/session/{session_id}/raw-mastered")
        assert raw.status_code == 200
        assert raw.json()["sampleRate"] == _SR
        # The vocal itself is still downloadable from its own URL.
        assert (
            client.get(f"/api/session/{session_id}/vocal/audio").content
            == _FAKE_VOCAL
        )

    def test_failed_vocal_keeps_the_master_intact(
        self, tmp_path, monkeypatch
    ):
        """A 500 records no pointer at all and never touches the master."""
        _boom_chain(monkeypatch)
        session_id = _register_session(tmp_path)
        mastered = tmp_path / f"{session_id}_mastered.wav"
        _write_tone(mastered, hz=110.0)
        sessions[session_id].mastered_path = str(mastered)

        resp = client.post(f"/api/session/{session_id}/vocal", json=_PARAMS)

        assert resp.status_code == 500
        session = sessions[session_id]
        assert session.mastered_path == str(mastered)
        assert session.vocal_path is None
        assert session.status == ProcessingStatus.ERROR


# ── GET /session exposure + reset (T8.2) ───────────────────────────────


class TestSessionExposure:
    def test_get_session_exposes_vocal_path(self, tmp_path, monkeypatch):
        """First-level field, present before and after the run."""
        _stub_chain(monkeypatch)
        session_id = _register_session(tmp_path)

        before = client.get(f"/api/session/{session_id}").json()
        assert before["vocal_path"] is None
        # T2's contract is untouched by the new field.
        assert before["mix_status"] == "none"
        assert before["mix_path"] is None

        _vocal(session_id)

        after = client.get(f"/api/session/{session_id}").json()
        assert after["vocal_path"] == str(
            _convention_path(session_id).resolve()
        )
        assert after["mastered_path"] is None
        assert after["mix_status"] == "none"

    def test_reset_clears_vocal_path(self, tmp_path, monkeypatch):
        """A reset drops the derived pointer; the WAV stays on disk."""
        _stub_chain(monkeypatch)
        session_id = _register_session(tmp_path)
        _vocal(session_id)
        rendered = Path(sessions[session_id].vocal_path)
        assert rendered.exists()

        resp = client.post(f"/api/session/{session_id}/reset")

        assert resp.status_code == 200
        assert resp.json()["vocal_path"] is None
        assert sessions[session_id].vocal_path is None
        # Untracked on disk, exactly like the rendered masters.
        assert rendered.exists()
        # The pointer is gone, so the session GET no longer advertises it…
        assert client.get(f"/api/session/{session_id}").json()["vocal_path"] is None
        # …but a session persisted before the field existed still serves.
        assert client.get(f"/api/session/{session_id}/vocal/audio").status_code == 200


# ── The serving endpoint must resolve the SAME file (frontend /voz) ────


class TestVocalAudioEndpoint:
    def test_serves_the_recorded_pointer(self, tmp_path, monkeypatch):
        _stub_chain(monkeypatch)
        session_id = _register_session(tmp_path)
        _vocal(session_id)

        resp = client.get(f"/api/session/{session_id}/vocal/audio")

        assert resp.status_code == 200
        assert resp.content == _FAKE_VOCAL
        assert resp.headers["content-type"].startswith("audio/wav")

    def test_pointer_and_convention_are_the_same_file(
        self, tmp_path, monkeypatch
    ):
        """The pointer must resolve to the file the URL always served."""
        _stub_chain(monkeypatch)
        session_id = _register_session(tmp_path)
        _vocal(session_id)

        assert Path(sessions[session_id].vocal_path) == (
            _convention_path(session_id).resolve()
        )

    def test_404_without_a_rendered_vocal(self, tmp_path, monkeypatch):
        _stub_chain(monkeypatch)
        session_id = _register_session(tmp_path)

        resp = client.get(f"/api/session/{session_id}/vocal/audio")

        assert resp.status_code == 404
        assert "vocal" in resp.json()["detail"].lower()

    def test_404_unknown_session(self):
        resp = client.get("/api/session/no-such-id/vocal/audio")
        assert resp.status_code == 404

    def test_vocal_without_audio_is_400(self, tmp_path, monkeypatch):
        """A session with no uploadable file never reaches the chain."""
        seen = _stub_chain(monkeypatch)
        session_id = str(uuid.uuid4())
        sessions[session_id] = SessionData(session_id=session_id)

        resp = client.post(f"/api/session/{session_id}/vocal", json=_PARAMS)

        assert resp.status_code == 400
        assert seen == []
        assert sessions[session_id].vocal_path is None


# ── Real chain: the pointer is the file the engine actually wrote ──────


def test_real_chain_records_the_file_it_wrote(tmp_path):
    """No stubs — pedalboard writes the WAV and the pointer must match it."""
    session_id = _register_session(tmp_path)

    body = _vocal(session_id)

    session = sessions[session_id]
    assert session.vocal_path == body["output_path"]
    assert Path(session.vocal_path).exists()
    # A real, readable WAV written by the chain (one second of audio).
    info = sf.info(session.vocal_path)
    assert info.samplerate == _SR
    assert info.frames == _SR
    # Still not a master.
    assert session.mastered_path is None
    assert (
        client.get(f"/api/session/{session_id}/audio/mastered").status_code
        == 404
    )
    assert client.get(f"/api/session/{session_id}/vocal/audio").content == (
        Path(session.vocal_path).read_bytes()
    )
