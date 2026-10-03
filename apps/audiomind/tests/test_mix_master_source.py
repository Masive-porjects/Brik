"""Functional tests for the Mix → Master source routing (T2).

Feature ``odd/tasks/mix-master-flow.md``:

* ``SessionData.mix_status`` tracks the Mix Engine lifecycle
  (``none → processing → completed | failed``) so the client can gate the
  master step without inventing state, and ``POST /process`` accepts
  ``?source=original|mix`` to choose WHICH file the whole chain (existence
  check, analysis, DSP input) consumes;
* the default is smart: the mix only when it is ``completed`` and on disk;
* an explicit ``source=mix`` without a completed mix is a 400 naming the
  real state — never a silent fallback to the original;
* NEUTRAL = BYPASS is preserved: neutral parameters stay bit-exact against
  the SELECTED input.

The DSP is stubbed everywhere except the neutrality test: the contract under
test is WHICH file is routed, not the mastering chain. ``split_audio``
(Demucs) is monkeypatched like in ``test_mix_engine.py`` — the real model
download is heavy and non-deterministic.
"""
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, "src")

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import audiomind.api.mastering as mastering_mod
import audiomind.processing.mix_engine as mix_engine
from audiomind.api.upload import sessions
from audiomind.config import settings
from audiomind.main import app
from audiomind.models.audio import (
    AnalysisResult,
    PresetMasterEntry,
    ProcessingStatus,
    SessionData,
)
from audiomind.services import storage

client = TestClient(app)

_SR = 44100
# Per-stem fixtures for the mix: differing lengths force the pad path.
_STEM_SPECS = {
    "drums": (120.0, 0.75),
    "bass": (90.0, 1.0),
    "other": (330.0, 1.0),
    "vocals": (440.0, 1.25),
}


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch, tmp_path):
    sessions.clear()
    # Force development mode so require_license allows all requests
    monkeypatch.setattr(settings, "license_key", "")
    # Never let a test serve a real pre-built master from the shipped cache.
    monkeypatch.setattr(settings, "prebuilt_dir", tmp_path / "prebuilt")
    # These dirs are module-level settings read at CALL time, so patching them
    # here is what keeps re-hydration (``_hydrate_mix_from_r2``) and any other
    # write path inside tmp_path instead of the developer's real outputs/.
    # They must exist: production gets them from the app lifespan, and these
    # tests drive TestClient without one.
    monkeypatch.setattr(settings, "output_dir", tmp_path / "outputs")
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    for _dir in ("outputs", "uploads"):
        (tmp_path / _dir).mkdir(parents=True, exist_ok=True)
    # The session backend is redirected into ``tmp_path`` by the harness
    # fixture in conftest.py, so the endpoints' ``save_sessions`` calls cannot
    # write the developer's real uploads/sessions.json.
    yield
    sessions.clear()


def _write_tone(path: Path, hz: float, seconds: float, sr: int = _SR,
                subtype: str = "PCM_16") -> None:
    """Write a short mono sine tone (synthetic fixture, no DSP deps)."""
    t = np.linspace(0.0, seconds, int(sr * seconds), endpoint=False)
    sf.write(str(path), 0.25 * np.sin(2.0 * np.pi * hz * t), sr, subtype=subtype)


def _fake_split(input_path: str | Path, output_dir: str | Path | None = None,
                model: str = "htdemucs") -> dict:
    """Stand-in for Demucs: writes 4 distinct synthetic stems synchronously."""
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stems: dict[str, str] = {}
    for name, (hz, seconds) in _STEM_SPECS.items():
        stem_path = out / f"{name}.wav"
        _write_tone(stem_path, hz=hz, seconds=seconds)
        stems[name] = str(stem_path)
    return {
        "stems": stems,
        "sample_rate": _SR,
        "duration_seconds": 1.25,
        "stem_audio_dir": str(out),
    }


def _boom_split(*_a, **_k) -> dict:
    """Separator stand-in that always fails (induces the 500 path)."""
    raise RuntimeError("synthetic separator failure")


def _analysis(duration: float = 1.0) -> AnalysisResult:
    """Minimal valid AnalysisResult (never the real librosa analyzer)."""
    return AnalysisResult(
        integrated_lufs=-18.0,
        true_peak_db=-1.0,
        dynamic_range_db=8.0,
        spectral_centroid=2000.0,
        tempo_bpm=120.0,
        duration_seconds=duration,
        sample_rate=_SR,
        channels=2,
    )


# ── /mix state transitions (T2.2) ──────────────────────────────────────


def _register_session(tmp_path: Path, session_id: str | None = None) -> str:
    """Insert a session with a real original directly into the store.

    Bypasses ``/api/upload`` so no background analysis or pre-render fires;
    the endpoints only need ``original_path`` to exist.
    """
    sid = session_id or str(uuid.uuid4())
    original_path = tmp_path / f"{sid}_input.wav"
    _write_tone(original_path, hz=220.0, seconds=1.0)
    sessions[sid] = SessionData(
        session_id=sid,
        status=ProcessingStatus.UPLOADED,
        original_path=str(original_path),
        original_filename=original_path.name,
    )
    return sid


class TestMixStatusTransitions:
    """``mix_status`` is the backend-owned lifecycle of the mix."""

    def test_happy_path_ends_completed(self, tmp_path, monkeypatch):
        """``none`` → (processing) → ``completed``, exposed everywhere."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        assert sessions[session_id].mix_status == "none"

        resp = client.post(f"/api/session/{session_id}/mix")

        assert resp.status_code == 200, resp.text
        session = sessions[session_id]
        assert session.mix_status == "completed"
        assert session.mix_path, "the mix file pointer must be recorded"
        # Exposed in the POST /mix response payload (X-Mix-Result header)
        payload = json.loads(resp.headers["x-mix-result"])
        assert payload["mix_status"] == "completed"
        # …and by the session GET, and the mix GET header
        assert client.get(f"/api/session/{session_id}").json()["mix_status"] == (
            "completed"
        )
        audio = client.get(f"/api/session/{session_id}/audio/mix")
        assert audio.status_code == 200
        assert audio.headers["x-mix-status"] == "completed"

    def test_processing_is_published_before_the_pipeline_runs(
        self, tmp_path, monkeypatch
    ):
        """A client polling while the mix runs must read ``processing``.

        Observed from INSIDE the pipeline (the separator call happens while
        ``build_mix`` is still running), so there is no race: the state is
        published before the heavy work, not after it.
        """
        seen: list[str] = []
        session_id = _register_session(tmp_path)

        def _spy_split(input_path, output_dir=None, model="htdemucs") -> dict:
            seen.append(sessions[session_id].mix_status)
            return _fake_split(input_path, output_dir=output_dir, model=model)

        monkeypatch.setattr(mix_engine, "split_audio", _spy_split)

        assert client.post(f"/api/session/{session_id}/mix").status_code == 200
        assert seen == ["processing"], f"in-flight state was {seen}"

    def test_failure_marks_failed_and_keeps_previous_mix(
        self, tmp_path, monkeypatch
    ):
        """``none`` → (processing) → ``failed``; the 500 is unchanged."""
        session_id = _register_session(tmp_path)
        # A previous DELIVERED mix (this is what a re-mix failure must keep)
        delivered = tmp_path / f"{session_id}_mix.wav"
        _write_tone(delivered, hz=330.0, seconds=1.0)
        session = sessions[session_id]
        session.mix_path = str(delivered)
        session.mix_analysis = {"tempo_bpm": 120.0, "mix_status": "completed"}
        session.mix_status = "completed"

        monkeypatch.setattr(mix_engine, "split_audio", _boom_split)
        resp = client.post(f"/api/session/{session_id}/mix")

        assert resp.status_code == 500
        assert "Mix failed" in resp.json()["detail"]
        session = sessions[session_id]
        assert session.mix_status == "failed"
        # The last SUCCESSFUL mix survives verbatim (still on disk, still
        # served); the live state is the field, not the stored snapshot.
        assert session.mix_path == str(delivered)
        assert session.mix_analysis == {
            "tempo_bpm": 120.0,
            "mix_status": "completed",
        }
        audio = client.get(f"/api/session/{session_id}/audio/mix")
        assert audio.status_code == 200
        assert audio.headers["x-mix-status"] == "failed"

    def test_rejected_request_does_not_touch_the_state(self, tmp_path):
        """A guard rejection (no audio) is not a failed mix."""
        session_id = str(uuid.uuid4())
        sessions[session_id] = SessionData(session_id=session_id)

        resp = client.post(f"/api/session/{session_id}/mix")

        assert resp.status_code == 400
        assert sessions[session_id].mix_status == "none"

    def test_reset_clears_mix_status(self, tmp_path, monkeypatch):
        """``POST /reset`` reinitializes the mix state with the session."""
        monkeypatch.setattr(mix_engine, "split_audio", _fake_split)
        session_id = _register_session(tmp_path)
        assert client.post(f"/api/session/{session_id}/mix").status_code == 200

        resp = client.post(f"/api/session/{session_id}/reset")

        assert resp.status_code == 200
        assert resp.json()["mix_status"] == "none"


# ── /process source routing (T2.3) ─────────────────────────────────────


def _seed_mixed_session(tmp_path: Path, mix_status: str = "completed") -> tuple:
    """Session with a real original AND a real mix file, plus its state."""
    session_id = _register_session(tmp_path)
    session = sessions[session_id]
    mix_path = tmp_path / f"{session_id}_mix.wav"
    _write_tone(mix_path, hz=330.0, seconds=1.0)
    session.mix_path = str(mix_path)
    session.mix_analysis = {"tempo_bpm": 120.0, "mix_status": "completed"}
    session.mix_status = mix_status
    return session_id, str(session.original_path), str(mix_path)


def _spy_dsp(monkeypatch) -> dict:
    """Stub the engine and record which file every call consumed.

    ``analyze_audio`` is recorded too: the source decision must reach the
    analysis, not only the DSP input.
    """
    seen: dict[str, list[str]] = {"analyze": [], "process": []}

    def _fake_analyze(path, *_a, **_k):
        seen["analyze"].append(str(path))
        return _analysis()

    def _fake_process(input_path=None, output_path=None, params=None, **_k):
        seen["process"].append(str(input_path))
        out = Path(output_path)
        out.write_bytes(b"FAKE-DSP-RESULT")
        return {"output_path": str(out.resolve())}

    monkeypatch.setattr(mastering_mod, "analyze_audio", _fake_analyze)
    monkeypatch.setattr(mastering_mod, "process_audio", _fake_process)
    return seen


def _process(session_id: str, query: str = "") -> dict:
    resp = client.post(f"/api/session/{session_id}/process{query}", json={})
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestProcessSourceRouting:
    """``?source=`` picks the file the WHOLE chain consumes."""

    def test_source_mix_consumes_the_mix(self, tmp_path, monkeypatch):
        session_id, _original, mix_path = _seed_mixed_session(tmp_path)
        seen = _spy_dsp(monkeypatch)

        body = _process(session_id, "?source=mix")

        assert set(seen["process"]) == {mix_path}
        # The analysis is run on the MIX, and session.analysis (the analysis
        # of the UPLOADED original) is never overwritten with mix numbers.
        assert set(seen["analyze"]) == {mix_path}
        assert sessions[session_id].analysis is None
        # Response shape unchanged: mastered_path results from the mix run
        assert body["mastered_path"]
        assert Path(body["mastered_path"]).exists()
        assert body["status"] == "completed"
        assert body["mix_status"] == "completed"

    def test_source_original_still_consumes_the_original(
        self, tmp_path, monkeypatch
    ):
        session_id, original_path, _mix = _seed_mixed_session(tmp_path)
        seen = _spy_dsp(monkeypatch)

        _process(session_id, "?source=original")

        assert set(seen["process"]) == {original_path}
        assert set(seen["analyze"]) == {original_path}

    def test_default_uses_mix_when_completed(self, tmp_path, monkeypatch):
        """No ``source`` + completed mix → the mix (smart default)."""
        session_id, _original, mix_path = _seed_mixed_session(tmp_path)
        seen = _spy_dsp(monkeypatch)

        _process(session_id)

        assert set(seen["process"]) == {mix_path}

    def test_default_uses_original_without_mix(self, tmp_path, monkeypatch):
        """No ``source`` and no mix ever → the original, untouched."""
        session_id = _register_session(tmp_path)
        original_path = str(sessions[session_id].original_path)
        seen = _spy_dsp(monkeypatch)

        _process(session_id)

        assert set(seen["process"]) == {original_path}

    @pytest.mark.parametrize("mix_status", ["none", "processing", "failed"])
    def test_default_falls_back_to_original_for_unusable_mix(
        self, tmp_path, monkeypatch, mix_status
    ):
        """A mix file on disk is only masterable when it is ``completed``."""
        session_id, original_path, _mix = _seed_mixed_session(
            tmp_path, mix_status=mix_status
        )
        seen = _spy_dsp(monkeypatch)

        _process(session_id)

        assert set(seen["process"]) == {original_path}

    @pytest.mark.parametrize("mix_status", ["none", "processing", "failed"])
    def test_source_mix_without_completed_mix_is_400(
        self, tmp_path, monkeypatch, mix_status
    ):
        """Explicit mix request → actionable 400, NO silent fallback."""
        session_id, _original, _mix = _seed_mixed_session(
            tmp_path, mix_status=mix_status
        )
        seen = _spy_dsp(monkeypatch)

        resp = client.post(
            f"/api/session/{session_id}/process?source=mix", json={}
        )

        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "mix_status" in detail
        assert mix_status in detail
        # Nothing was processed: no fallback to the original, no DSP at all
        assert seen == {"analyze": [], "process": []}
        assert sessions[session_id].mastered_path is None

    def test_source_mix_with_missing_file_is_400(self, tmp_path, monkeypatch):
        """A completed mix whose WAV vanished is not masterable."""
        session_id, _original, mix_path = _seed_mixed_session(tmp_path)
        Path(mix_path).unlink()
        seen = _spy_dsp(monkeypatch)

        resp = client.post(
            f"/api/session/{session_id}/process?source=mix", json={}
        )

        assert resp.status_code == 400
        assert "missing" in resp.json()["detail"]
        assert seen == {"analyze": [], "process": []}

    def test_unknown_source_is_rejected(self, tmp_path):
        session_id, _original, _mix = _seed_mixed_session(tmp_path)

        resp = client.post(
            f"/api/session/{session_id}/process?source=stems", json={}
        )

        assert resp.status_code == 422

    # ── Redeploy survival: the mix only exists in R2 ──────────────────────
    #
    # Railway free tier has no persistent disk, so a redeploy leaves the
    # session pointing at a ``mix_path`` that no longer exists. Before the
    # R2 re-hydration the smart resolver read ONLY the local path, so it fell
    # back to "original" and quietly mastered the wrong audio. These tests pin
    # the recovered behavior.

    @staticmethod
    def _stub_r2(monkeypatch, *, present: bool = True) -> list:
        """Fake ``storage.download_to``; records the keys it was asked for."""
        fetched: list = []

        def _download(key: str, local_path: str) -> str:
            if not present:
                raise storage.StorageError(f"R2 download failed for {key!r}")
            fetched.append(key)
            Path(local_path).write_bytes(b"RIREMIX-WAV-BYTES")
            return local_path

        monkeypatch.setattr(mastering_mod.storage, "download_to", _download)
        return fetched

    def test_missing_local_mix_is_rehydrated_from_r2(self, tmp_path, monkeypatch):
        session_id, original_path, mix_path = _seed_mixed_session(tmp_path)
        r2_key = f"mixes/{session_id}/{session_id}_mix.wav"
        Path(mix_path).unlink()  # the redeploy
        sessions[session_id].mix_r2_key = r2_key
        fetched = self._stub_r2(monkeypatch)
        seen = _spy_dsp(monkeypatch)

        body = _process(session_id, "?source=mix")

        assert fetched == [r2_key], "the mix must be re-fetched from R2"
        # The DSP consumed the REHYDRATED file, never the original.
        rehydrated = str(
            (settings.output_dir / f"{session_id}_mix_from_r2.wav").resolve()
        )
        assert set(seen["process"]) == {rehydrated}
        assert set(seen["analyze"]) == {rehydrated}
        assert original_path not in seen["process"]
        assert body["status"] == "completed"

    def test_default_uses_mix_when_only_r2_has_it(self, tmp_path, monkeypatch):
        """The guardrail: with no local file but a durable R2 key, the SMART
        default must still be the MIX, not the original."""
        session_id, original_path, mix_path = _seed_mixed_session(tmp_path)
        Path(mix_path).unlink()
        sessions[session_id].mix_r2_key = f"mixes/{session_id}/mix.wav"
        self._stub_r2(monkeypatch)
        seen = _spy_dsp(monkeypatch)

        _process(session_id)

        assert seen["process"], "nothing was mastered at all"
        assert seen["process"] != [original_path], (
            "silently mastering the original instead of the mix is the "
            "wrong-output bug this fix exists to prevent"
        )

    def test_smart_default_falls_back_to_original_when_no_mix_exists(
        self, tmp_path, monkeypatch
    ):
        """No key, no local file: the mix is not deliverable at all, so the
        smart default is the original. R2 is never even contacted."""
        session_id, original_path, mix_path = _seed_mixed_session(tmp_path)
        Path(mix_path).unlink()  # no mix_r2_key either
        fetched = self._stub_r2(monkeypatch)
        seen = _spy_dsp(monkeypatch)

        _process(session_id)

        assert set(seen["process"]) == {original_path}
        assert fetched == [], "there is nothing to re-fetch"

    def test_unreachable_r2_refuses_instead_of_silently_mastering_the_original(
        self, tmp_path, monkeypatch
    ):
        """DELIBERATE 400, not a fallback.

        The session claims ``mix_status='completed'``, so the client asked for
        the MIX. If R2 then fails, mastering the ORIGINAL and returning
        ``status='completed'`` would hand the user a master of different audio
        with no error at all -- which is precisely the bug this whole fix
        exists to kill (redeploy -> silent wrong output). Refusing loudly with
        an actionable message keeps the "never silently substitute a different
        audio file" contract that the explicit ``?source=mix`` branch already
        enforces in ``test_source_mix_without_completed_mix_is_400``.

        The asymmetry is intentional: a SMART default falls back to the
        original only when the mix was never deliverable; once it has committed
        to a deliverable mix, an outage is a 400, not a wrong master.
        """
        session_id, _original, mix_path = _seed_mixed_session(tmp_path)
        Path(mix_path).unlink()
        sessions[session_id].mix_r2_key = f"mixes/{session_id}/missing.wav"
        self._stub_r2(monkeypatch, present=False)
        seen = _spy_dsp(monkeypatch)

        resp = client.post(f"/api/session/{session_id}/process", json={})

        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "not recoverable" in detail
        assert "R2 key present" in detail, "the message must name the culprit"
        assert "Re-run the mix" in detail, "the message must be actionable"
        # Crucially: NO DSP ran, so no wrong audio was produced.
        assert seen == {"analyze": [], "process": []}
        assert sessions[session_id].mastered_path is None

    def test_source_mix_stays_400_when_r2_cannot_hydrate(self, tmp_path, monkeypatch):
        """Explicit ``source=mix`` must NOT degrade to the original, even
        when R2 fails: the client asked for the mix."""
        session_id, _original, mix_path = _seed_mixed_session(tmp_path)
        Path(mix_path).unlink()
        sessions[session_id].mix_r2_key = f"mixes/{session_id}/missing.wav"
        self._stub_r2(monkeypatch, present=False)
        seen = _spy_dsp(monkeypatch)

        resp = client.post(
            f"/api/session/{session_id}/process?source=mix", json={}
        )

        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert "not recoverable" in detail
        assert "present" in detail, "the message must say an R2 key was tried"
        assert seen == {"analyze": [], "process": []}

    def test_rehydration_caches_the_pointer_on_the_session(self, tmp_path, monkeypatch):
        """Second master run is a local read: the recovered path is stored."""
        session_id, _original, mix_path = _seed_mixed_session(tmp_path)
        Path(mix_path).unlink()
        sessions[session_id].mix_r2_key = f"mixes/{session_id}/{session_id}_mix.wav"
        self._stub_r2(monkeypatch)
        _spy_dsp(monkeypatch)

        _process(session_id, "?source=mix")

        recovered = sessions[session_id].mix_path
        assert recovered.endswith("_mix_from_r2.wav")
        assert Path(recovered).exists()

    def test_an_empty_r2_object_is_refused(self, tmp_path, monkeypatch):
        """A zero-byte download would sail past the existence check and then
        fail deep inside the DSP chain with a codec error."""
        session_id, _original, mix_path = _seed_mixed_session(tmp_path)
        Path(mix_path).unlink()
        sessions[session_id].mix_r2_key = f"mixes/{session_id}/{session_id}_mix.wav"

        def _empty(key: str, local_path: str) -> str:
            Path(local_path).write_bytes(b"")
            return local_path

        monkeypatch.setattr(mastering_mod.storage, "download_to", _empty)
        seen = _spy_dsp(monkeypatch)

        resp = client.post(
            f"/api/session/{session_id}/process?source=mix", json={}
        )

        assert resp.status_code == 400
        assert seen == {"analyze": [], "process": []}

    def test_preset_path_routes_mix_and_skips_the_original_cache(
        self, tmp_path, monkeypatch
    ):
        """``?preset_id=`` must not serve an original-derived cached master
        for a mix request: the engine runs on the mix instead."""
        session_id, _original, mix_path = _seed_mixed_session(tmp_path)
        seen = _spy_dsp(monkeypatch)
        # A previous ORIGINAL master for the same preset (the cache the
        # source=original path would serve instantly).
        cached = tmp_path / f"{session_id}_universal_mastered.wav"
        cached.write_bytes(b"FAKE-CACHED-ORIGINAL-MASTER")
        sessions[session_id].preset_masters["universal"] = PresetMasterEntry(
            preset_id="universal",
            output_path=str(cached),
            status="completed",
            progress=1.0,
        )

        _process(session_id, "?preset_id=universal&source=mix")

        assert set(seen["process"]) == {mix_path}
        entry = sessions[session_id].preset_masters["universal"]
        assert entry.status == "completed"
        assert entry.output_path != str(cached), (
            "the cached original master must not be reused for a mix master"
        )

    def test_preset_path_serves_cache_for_original(self, tmp_path, monkeypatch):
        """Unchanged behavior: source=original still hits the preset cache."""
        session_id, _original, _mix = _seed_mixed_session(tmp_path)
        seen = _spy_dsp(monkeypatch)
        cached = tmp_path / f"{session_id}_universal_mastered.wav"
        cached.write_bytes(b"FAKE-CACHED-ORIGINAL-MASTER")
        sessions[session_id].preset_masters["universal"] = PresetMasterEntry(
            preset_id="universal",
            output_path=str(cached),
            status="completed",
            progress=1.0,
        )

        body = _process(session_id, "?preset_id=universal&source=original")

        assert body["mastered_path"] == str(cached)
        assert seen["process"] == []


class TestNeutralityIsPreserved:
    """NEUTRAL = BYPASS against the SELECTED input (real engine, no stubs)."""

    def test_neutral_source_original_is_bit_exact(self, tmp_path, monkeypatch):
        """Neutral params on source=original stay sample-identical."""
        session_id = _register_session(tmp_path)
        original = Path(sessions[session_id].original_path)
        # 32-bit float input: the neutral fast-path writes the same format,
        # so the roundtrip is lossless and the bypass is bit-exact.
        t = np.linspace(0.0, 0.5, int(_SR * 0.5), endpoint=False)
        left = 0.4 * np.sin(2 * np.pi * 440 * t)
        right = 0.4 * np.sin(2 * np.pi * 660 * t)
        sf.write(
            str(original), np.stack([left, right]).T, _SR, subtype="FLOAT"
        )
        # No analysis: the engine takes the same neutral fast-path as the
        # engine smoke test (analysis_result=None).
        monkeypatch.setattr(mastering_mod, "analyze_audio", lambda _p: None)

        body = _process(session_id, "?source=original")

        in_arr, in_sr = sf.read(str(original), always_2d=True)
        out_arr, out_sr = sf.read(body["mastered_path"], always_2d=True)
        assert in_sr == out_sr
        assert in_arr.shape == out_arr.shape
        np.testing.assert_array_equal(
            in_arr, out_arr, err_msg="neutral defaults must be bit-exact"
        )
