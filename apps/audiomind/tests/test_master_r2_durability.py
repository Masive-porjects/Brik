"""Master durability across a Railway redeploy (feature ``#30``).

Railway free tier has NO persistent disk: ``outputs/`` is wiped on every
redeploy, and every master pointer (``session.mastered_path`` and
``session.preset_masters[pid].output_path``) is a local path. Before this
feature the four master-serving endpoints 404'd after a redeploy and the user
could not download a master they had already paid for. These tests pin the
master-side twin of the mix durability pattern (``mix_r2_key`` +
``_hydrate_mix_from_r2``): a durable R2 key on every pointer that gets set,
and re-hydration before any endpoint gives up.

Isolation rules that MUST be respected here (a previous session got them
wrong and wrote into the developer's real repo):

* the session backend is pinned into ``tmp_path`` by the harness fixture in
  ``conftest.py``, so the endpoints' ``save_sessions`` calls cannot overwrite
  the developer's real ``uploads/sessions.json``;
* ``output_dir``/``upload_dir`` must exist: production gets them from the app
  lifespan, and ``TestClient`` without ``with`` never runs it;
* R2 is stubbed over the real ``storage`` module, so no test can reach the
  network or use the credentials sitting in the local ``.env``.
"""
import sys
import uuid
from io import BytesIO
from pathlib import Path

sys.path.insert(0, "src")

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import audiomind.api.mastering as mastering_mod
from audiomind.api.upload import sessions
from audiomind.config import settings
from audiomind.main import app
from audiomind.models.audio import (
    AnalysisResult,
    PresetMasterEntry,
    ReferenceComparison,
    SessionData,
)
from audiomind.services import storage

client = TestClient(app)

_SR = 44100
# A real preset id (used by test_demo_mode.py too), so the on-demand path runs
# instead of the no-preset branch.
_PRESET = "fuego"


def _wav_bytes(seconds: float = 0.25, hz: float = 440.0) -> bytes:
    """A decodable mono WAV — ``/raw-mastered`` needs real PCM, not a stub."""
    t = np.linspace(0.0, seconds, int(_SR * seconds), endpoint=False)
    buf = BytesIO()
    sf.write(
        buf, 0.3 * np.sin(2.0 * np.pi * hz * t), _SR, subtype="PCM_16", format="WAV"
    )
    return buf.getvalue()


# ── Isolation ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch, tmp_path):
    sessions.clear()
    mastering_mod._prerender_cache.clear()
    # Force development mode so require_license allows all requests.
    monkeypatch.setattr(settings, "license_key", "")
    # Never let a test serve a real pre-built master from the shipped cache.
    monkeypatch.setattr(settings, "prebuilt_dir", tmp_path / "prebuilt")
    # Call-time settings: keeps re-hydration and every write inside tmp_path.
    # They must exist (no app lifespan without ``with TestClient(app)``).
    monkeypatch.setattr(settings, "output_dir", tmp_path / "outputs")
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    for _dir in ("outputs", "uploads"):
        (tmp_path / _dir).mkdir(parents=True, exist_ok=True)
    yield
    sessions.clear()
    mastering_mod._prerender_cache.clear()


class _FakeR2:
    """In-memory R2 wired over the real ``storage`` module.

    Autouse for the whole file, so no test can reach the network or the real
    credentials. Tests flip ``fail_upload``/``fail_download``/``empty_download``
    to drive the failure paths, and read ``uploads``/``downloads`` to assert
    how many PUTs a single mastered file costs.
    """

    def __init__(self) -> None:
        self.payload = _wav_bytes()
        self.uploads: list[tuple[str, str]] = []
        self.downloads: list[tuple[str, str]] = []
        self.fail_upload = False
        self.fail_download = False
        self.empty_download = False

    def upload_file(self, local_path, key, content_type="audio/wav") -> str:
        if self.fail_upload:
            raise storage.StorageError(f"R2 upload failed for {key!r}: stubbed outage")
        self.uploads.append((str(local_path), key))
        return key

    def download_to(self, key: str, local_path: str) -> str:
        if self.fail_download:
            raise storage.StorageError(
                f"R2 download failed for {key!r}: stubbed outage"
            )
        self.downloads.append((key, local_path))
        Path(local_path).write_bytes(b"" if self.empty_download else self.payload)
        return local_path

    @property
    def uploaded_keys(self) -> list[str]:
        return [key for _local, key in self.uploads]


@pytest.fixture(autouse=True)
def _r2(monkeypatch) -> _FakeR2:
    fake = _FakeR2()
    monkeypatch.setattr(storage, "upload_file", fake.upload_file)
    monkeypatch.setattr(storage, "download_to", fake.download_to)
    return fake


def _analysis(duration: float = 0.25) -> AnalysisResult:
    """Minimal valid AnalysisResult (never the real librosa analyzer)."""
    return AnalysisResult(
        integrated_lufs=-18.0,
        true_peak_db=-1.0,
        dynamic_range_db=8.0,
        spectral_centroid=2000.0,
        tempo_bpm=120.0,
        duration_seconds=duration,
        sample_rate=_SR,
        channels=1,
    )


def _stub_dsp(monkeypatch) -> None:
    """Stub the engine: write bytes to ``output_path`` and report it back.

    Same shape as ``_spy_dsp`` in ``test_mix_master_source.py`` — the contract
    under test is WHICH file is uploaded/recovered, not the mastering chain.
    """

    def _fake_process(input_path=None, output_path=None, params=None, **_k):
        out = Path(output_path)
        out.write_bytes(b"FAKE-DSP-RESULT")
        return {"output_path": str(out.resolve())}

    monkeypatch.setattr(mastering_mod, "analyze_audio", lambda *_a, **_k: _analysis())
    monkeypatch.setattr(mastering_mod, "process_audio", _fake_process)


def _register_session(tmp_path: Path, session_id: str | None = None) -> str:
    """Insert a session with a real original directly into the store.

    Bypasses ``/api/upload`` so no background analysis or pre-render fires.
    """
    sid = session_id or str(uuid.uuid4())
    original = tmp_path / f"{sid}_input.wav"
    original.write_bytes(_wav_bytes())
    sessions[sid] = SessionData(
        session_id=sid,
        original_path=str(original.resolve()),
        original_filename="mi_tema.wav",
    )
    return sid


def _redeploy_preset(sid: str, preset_id: str = _PRESET) -> str:
    """Simulate the redeploy: a preset master that only exists in R2.

    The local file is NEVER created (that is the whole point), and the entry
    keeps its dead path plus the durable key.
    """
    dead = settings.output_dir / f"{sid}_{preset_id}_mastered.wav"
    key = f"masters/{sid}/{preset_id}_mastered.wav"
    sessions[sid].preset_masters[preset_id] = PresetMasterEntry(
        preset_id=preset_id,
        output_path=str(dead),
        status="completed",
        progress=1.0,
        r2_key=key,
    )
    return key


def _redeploy_legacy(sid: str) -> str:
    """Simulate the redeploy for the legacy ``mastered_path`` pointer."""
    dead = settings.output_dir / f"{sid}_mastered.wav"
    key = f"masters/{sid}/{sid}_mastered.wav"
    session = sessions[sid]
    session.mastered_path = str(dead)
    session.master_r2_key = key
    return key


def _hydration_target(sid: str, preset_id: str | None = None) -> Path:
    """The deterministic re-hydration filename (D4)."""
    name = (
        f"{sid}_{preset_id}_mastered_from_r2.wav"
        if preset_id
        else f"{sid}_mastered_from_r2.wav"
    )
    return (settings.output_dir / name).resolve()


# ── Consumers: a master that only lives in R2 is still served ───────────


class TestRehydrationOnRead:
    def test_preset_master_is_rehydrated_by_the_audio_endpoint(self, tmp_path, _r2):
        """GET /audio/mastered?preset_id=X serves the recovered WAV."""
        sid = _register_session(tmp_path)
        key = _redeploy_preset(sid)

        resp = client.get(f"/api/session/{sid}/audio/mastered?preset_id={_PRESET}")

        assert resp.status_code == 200, resp.text
        assert resp.content == _r2.payload
        assert _r2.downloads == [(key, str(_hydration_target(sid, _PRESET)))]
        # Self-healing: the recovered pointer is cached on the entry, so the
        # next request is a plain local read.
        entry = sessions[sid].preset_masters[_PRESET]
        assert entry.output_path == str(_hydration_target(sid, _PRESET))
        assert Path(entry.output_path).exists()

    def test_download_wav_rehydrates_the_legacy_pointer(self, tmp_path, _r2):
        sid = _register_session(tmp_path)
        key = _redeploy_legacy(sid)

        resp = client.get(f"/api/session/{sid}/download/wav")

        assert resp.status_code == 200, resp.text
        assert resp.content == _r2.payload
        assert _r2.downloads == [(key, str(_hydration_target(sid)))]
        assert sessions[sid].mastered_path == str(_hydration_target(sid))

    def test_raw_mastered_reads_the_recovered_file(self, tmp_path, _r2):
        """The waveform-comparison view survives the redeploy too."""
        sid = _register_session(tmp_path)
        _redeploy_legacy(sid)
        expected_samples, expected_sr = sf.read(BytesIO(_r2.payload), dtype="float32")

        resp = client.get(f"/api/session/{sid}/raw-mastered")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["sampleRate"] == expected_sr
        # Stereo-ised by the endpoint: mono input is duplicated on both sides.
        assert len(body["samples"]) == expected_samples.size * 2
        np.testing.assert_allclose(
            np.asarray(body["samples"][::2], dtype=np.float32), expected_samples
        )

    def test_unknown_preset_never_falls_back_to_the_legacy_pointer(
        self, tmp_path, _r2
    ):
        """Precedence is unchanged: a missing preset is a 404, not the master."""
        sid = _register_session(tmp_path)
        _redeploy_legacy(sid)

        resp = client.get(f"/api/session/{sid}/audio/mastered?preset_id=bruma")

        assert resp.status_code == 404
        assert _r2.downloads == [], "nothing may be re-fetched for an unknown preset"

    def test_reference_comparison_measures_the_recovered_master(
        self, tmp_path, _r2, monkeypatch
    ):
        """The comparison endpoint reads the same durable pointer."""
        sid = _register_session(tmp_path)
        session = sessions[sid]
        reference = settings.upload_dir / f"{sid}_reference.wav"
        reference.write_bytes(_wav_bytes())
        session.reference_path = str(reference.resolve())
        session.reference_filename = "referencia.wav"
        _redeploy_legacy(sid)

        captured: dict[str, str] = {}

        def _fake_compare(master_path, reference_path):
            captured["master_path"] = str(master_path)
            return ReferenceComparison(status="ready")

        monkeypatch.setattr(mastering_mod, "compare_tracks", _fake_compare)

        resp = client.post(f"/api/session/{sid}/compare-reference")

        assert resp.status_code == 200, resp.text
        assert captured["master_path"] == str(_hydration_target(sid))

    def test_local_file_is_served_without_contacting_r2(self, tmp_path, _r2):
        """The fast path: a master on disk never costs a network round trip."""
        sid = _register_session(tmp_path)
        _redeploy_legacy(sid)
        # The pointed-at file is back (e.g. a warm container): plain local read.
        Path(sessions[sid].mastered_path).write_bytes(_r2.payload)

        resp = client.get(f"/api/session/{sid}/download/wav")

        assert resp.status_code == 200, resp.text
        assert _r2.downloads == []


class TestUnrecoverableMasters:
    def test_failed_download_is_404_naming_the_key(self, tmp_path, _r2):
        """A R2 outage must never be answered with a wrong or empty file."""
        sid = _register_session(tmp_path)
        key = _redeploy_preset(sid)
        _r2.fail_download = True

        resp = client.get(f"/api/session/{sid}/audio/mastered?preset_id={_PRESET}")

        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert "not recoverable" in detail
        assert key in detail, "the message must name the key that was tried"
        assert "stubbed outage" in detail, "the message must carry the reason"
        # NO wrong file served: JSON error, and the dead pointer untouched.
        assert resp.headers["content-type"].startswith("application/json")
        assert sessions[sid].preset_masters[_PRESET].r2_key == key
        assert not _hydration_target(sid, _PRESET).exists()

    def test_a_zero_byte_object_is_refused(self, tmp_path, _r2):
        """An empty WAV would sail past exists() and fail inside the codec."""
        sid = _register_session(tmp_path)
        _redeploy_legacy(sid)
        _r2.empty_download = True

        resp = client.get(f"/api/session/{sid}/download/wav")

        assert resp.status_code == 404
        assert "empty" in resp.json()["detail"]
        assert not _hydration_target(sid).exists()

    def test_missing_file_and_missing_key_keep_the_existing_404(self, tmp_path, _r2):
        """Never-mastered sessions keep each endpoint's historic wording."""
        sid = _register_session(tmp_path)
        sessions[sid].mastered_path = str(settings.output_dir / f"{sid}_mastered.wav")

        audio = client.get(f"/api/session/{sid}/audio/mastered")
        download = client.get(f"/api/session/{sid}/download/wav")
        raw = client.get(f"/api/session/{sid}/raw-mastered")

        assert (audio.status_code, audio.json()["detail"]) == (
            404,
            "Audio file not found",
        )
        assert (download.status_code, download.json()["detail"]) == (
            404,
            "No mastered audio available. Process first.",
        )
        assert (raw.status_code, raw.json()["detail"]) == (
            404,
            "No mastered audio available",
        )
        assert _r2.downloads == [], "with no key there is nothing to re-fetch"


# ── Producers: every pointer that gets set gets a durable key ──────────


class TestKeysAreRecorded:
    def test_preset_master_stamps_both_pointers_from_one_upload(
        self, tmp_path, _r2, monkeypatch
    ):
        """D3: the entry and ``mastered_path`` are ONE file → ONE PUT."""
        _stub_dsp(monkeypatch)
        sid = _register_session(tmp_path)

        resp = client.post(f"/api/session/{sid}/process?preset_id={_PRESET}", json={})

        assert resp.status_code == 200, resp.text
        entry = sessions[sid].preset_masters[_PRESET]
        assert entry.output_path == sessions[sid].mastered_path, (
            "the preset path shares one file between both pointers"
        )
        key = f"masters/{sid}/{_PRESET}_mastered.wav"
        assert entry.r2_key == key
        assert sessions[sid].master_r2_key == key
        # Exactly one PUT for that one object.
        assert _r2.uploads == [(entry.output_path, key)]

    def test_plain_process_stamps_the_legacy_pointer(self, tmp_path, _r2, monkeypatch):
        _stub_dsp(monkeypatch)
        sid = _register_session(tmp_path)

        resp = client.post(f"/api/session/{sid}/process", json={})

        assert resp.status_code == 200, resp.text
        key = f"masters/{sid}/{sid}_mastered.wav"
        assert _r2.uploads == [(sessions[sid].mastered_path, key)]
        assert sessions[sid].master_r2_key == key

    def test_prerender_serve_stamps_the_legacy_pointer(self, tmp_path, _r2):
        """The pre-render playback route publishes a master pointer too."""
        sid = _register_session(tmp_path)
        prerendered = settings.output_dir / f"prerender_{sid}_{_PRESET}.wav"
        prerendered.write_bytes(_wav_bytes())
        mastering_mod._prerender_cache[sid] = {
            _PRESET: {"status": "completed", "output_path": str(prerendered)}
        }

        resp = client.get(f"/api/session/{sid}/prerender/{_PRESET}")

        assert resp.status_code == 200, resp.text
        key = f"masters/{sid}/{sid}_mastered.wav"
        assert _r2.uploads == [(str(prerendered), key)]
        assert sessions[sid].master_r2_key == key

    def test_album_process_stamps_the_legacy_pointer(self, tmp_path, _r2, monkeypatch):
        """The album path is the sixth producer (batch.py)."""
        import audiomind.api.batch as batch_mod

        sid = _register_session(tmp_path)
        monkeypatch.setattr(batch_mod, "_measure_input_lra", lambda _s: 6.0)

        def _fake_process(input_path=None, output_path=None, params=None, **_k):
            out = Path(output_path)
            out.write_bytes(b"FAKE-ALBUM-MASTER")
            return {
                "output_path": str(out.resolve()),
                "integrated_lufs": -14.0,
                "lra": 6.0,
            }

        monkeypatch.setattr(batch_mod, "process_audio", _fake_process)

        resp = client.post("/api/album/process", json={"session_ids": [sid]})

        assert resp.status_code == 200, resp.text
        key = f"masters/{sid}/{sid}_mastered.wav"
        assert _r2.uploads == [(sessions[sid].mastered_path, key)]
        assert sessions[sid].master_r2_key == key


class TestUploadFailureIsNotFatal:
    def test_process_still_succeeds_and_the_local_master_still_serves(
        self, tmp_path, _r2, monkeypatch
    ):
        """D2: R2 is insurance, never a reason to fail a delivered master."""
        _stub_dsp(monkeypatch)
        _r2.fail_upload = True
        sid = _register_session(tmp_path)

        resp = client.post(f"/api/session/{sid}/process", json={})

        assert resp.status_code == 200, resp.text
        local = sessions[sid].mastered_path
        assert local and Path(local).exists()
        assert sessions[sid].master_r2_key is None, "no key may be invented"
        # The user still gets their master on this container.
        download = client.get(f"/api/session/{sid}/download/wav")
        assert download.status_code == 200, download.text
        assert download.content == Path(local).read_bytes()


class TestResetClearsDurability:
    def test_reset_nulls_the_legacy_key_and_drops_the_preset_ones(
        self, tmp_path, _r2
    ):
        sid = _register_session(tmp_path)
        _redeploy_legacy(sid)
        _redeploy_preset(sid)

        resp = client.post(f"/api/session/{sid}/reset")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["master_r2_key"] is None
        assert body["preset_masters"] == {}
        assert body["mastered_path"] is None
