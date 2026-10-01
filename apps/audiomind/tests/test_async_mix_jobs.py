"""Durable job store + async mix job endpoints.

Covers the two properties the async refactor exists for:

1. Submitting returns immediately (HTTP 202) instead of holding the request
   open for the whole DSP chain.
2. The state a poller reads is durable and honest, INCLUDING the case the
   in-memory version got wrong: a worker that dies mid-job must not leave the
   client polling a job that will never finish.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import audiomind.api.jobs as jobs_mod
import audiomind.api.upload as upload_mod
from audiomind.config import settings
from audiomind.main import app
from audiomind.models.audio import AnalysisResult, SessionData
from audiomind.services import job_store as job_store_mod
from audiomind.services import mix_jobs, storage
from audiomind.services import supabase_client as supabase_client_mod
from audiomind.services.job_store import (
    InMemoryJobStore,
    JobRecord,
    JobStatus,
    SupabaseJobStore,
    get_job_store,
    is_stale,
    public_view,
)

client = TestClient(app)

_SR = 44100


def _active_store() -> InMemoryJobStore:
    """The store the module currently hands out (swapped in by the fixtures).

    Read through the module instead of holding a reference so a test can
    never accidentally assert against a stale instance.
    """
    return job_store_mod._store


def _register_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Create a session with a real (tiny) audio file on disk."""
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "output_dir", tmp_path / "outputs")
    monkeypatch.setattr(settings, "license_key", "")
    monkeypatch.setattr(settings, "demo_max_duration_seconds", 0.0)

    session_id = str(uuid.uuid4())
    audio = tmp_path / f"{session_id}_orig.wav"
    sf.write(audio, np.zeros((_SR, 2), dtype=np.float32), _SR)

    session = SessionData(
        session_id=session_id,
        original_path=str(audio),
        original_filename="orig.wav",
        analysis=AnalysisResult(
            integrated_lufs=-14.0,
            true_peak_db=-1.0,
            dynamic_range_db=10.0,
            spectral_centroid=2000.0,
            tempo_bpm=120.0,
            duration_seconds=1.0,
            sample_rate=_SR,
            channels=2,
            detected_genre="pop",
            genre_confidence=0.9,
        ),
    )
    upload_mod.sessions[session_id] = session
    return session_id


def _fake_build_mix(*args, **kwargs):
    """Stand-in for the DSP chain: writes a real WAV and returns its path."""
    session_id = args[0]
    out = Path(settings.output_dir) / f"{session_id}_mix.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out, np.zeros((_SR, 2), dtype=np.float32), _SR)
    return {
        "mix_path": str(out),
        "analysis": {"drums": {"rms": 0.1}},
        "tempo_bpm": 120.0,
        "genre": "pop",
        "mix_status": "completed",
    }


# ── Job store unit tests ────────────────────────────────────────────────


class TestJobStore:
    def test_new_job_starts_processing_with_a_lease(self):
        store = InMemoryJobStore()
        record = store.create("mix", session_id="s1")

        assert record.status is JobStatus.PROCESSING
        assert record.progress == 0
        assert record.job_id.startswith("mix_")
        # A lease is what makes "still running" distinguishable from "the
        # worker died", so a fresh job must carry one.
        assert record.lease_expires_at is not None
        assert not is_stale(record)

    def test_completed_job_reports_a_download_payload(self):
        store = InMemoryJobStore()
        record = store.create("mix", session_id="s1")
        store.update(
            record.job_id,
            status=JobStatus.COMPLETED,
            progress=100,
            result={"r2_key": "mixes/s1/s1_mix.wav", "download_url": "https://x/y"},
        )

        stored = store.get(record.job_id)
        assert stored is not None
        assert stored.status is JobStatus.COMPLETED
        assert stored.progress == 100
        assert stored.result["r2_key"] == "mixes/s1/s1_mix.wav"
        assert stored.is_terminal

    def test_terminal_job_holds_no_lease(self):
        """A finished job has nothing left to keep alive, so holding a lease
        would make a completed job look abandoned once it aged out."""
        store = InMemoryJobStore()
        record = store.create("mix")
        store.update(record.job_id, status=JobStatus.COMPLETED)

        assert store.get(record.job_id).lease_expires_at is None
        assert not is_stale(store.get(record.job_id))

    def test_error_records_the_reason(self):
        store = InMemoryJobStore()
        record = store.create("mix")
        store.update(record.job_id, status=JobStatus.ERROR, error="boom")

        stored = store.get(record.job_id)
        assert stored.status is JobStatus.ERROR
        assert stored.error == "boom"

    def test_progress_is_clamped(self):
        store = InMemoryJobStore()
        record = store.create("mix")
        store.update(record.job_id, progress=140)
        assert store.get(record.job_id).progress == 100
        store.update(record.job_id, progress=-5)
        assert store.get(record.job_id).progress == 0

    def test_update_merges_result_instead_of_replacing_it(self):
        store = InMemoryJobStore()
        record = store.create("mix")
        store.update(record.job_id, result={"a": 1})
        store.update(record.job_id, result={"b": 2})

        assert store.get(record.job_id).result == {"a": 1, "b": 2}

    def test_unknown_job_update_is_a_no_op(self):
        store = InMemoryJobStore()
        assert store.update("nope", status=JobStatus.COMPLETED) is None


class TestStoreSelection:
    """Choosing between the durable and the in-memory store.

    This is the one piece of the feature that can fail *silently*, and it
    matters in production: Supabase is already configured there for
    ``tracks``/``masters``, so "credentials present" is not evidence that
    ``dsp_jobs`` exists. Getting that wrong makes the backend answer 202
    and then 404 every poll, while the mix still runs and still uploads.
    """

    def _configure_supabase(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
        monkeypatch.setattr(settings, "supabase_service_role_key", "service-key")
        monkeypatch.setattr(job_store_mod, "_store", None)

    def test_falls_back_to_memory_without_credentials(self, monkeypatch):
        monkeypatch.setattr(settings, "supabase_url", "")
        monkeypatch.setattr(job_store_mod, "_store", None)
        assert isinstance(get_job_store(), InMemoryJobStore)

    def test_uses_supabase_when_the_table_answers(self, monkeypatch):
        self._configure_supabase(monkeypatch)
        probe = SimpleNamespace(execute=lambda: SimpleNamespace(data=[]))
        fake = SimpleNamespace(
            table=lambda name: SimpleNamespace(
                select=lambda *a: SimpleNamespace(
                    limit=lambda *a: SimpleNamespace(execute=probe.execute)
                )
            )
        )
        monkeypatch.setattr(
            supabase_client_mod, "get_supabase_client", lambda *a, **k: fake
        )
        assert isinstance(get_job_store(), SupabaseJobStore)

    def test_falls_back_when_the_table_is_missing(self, monkeypatch):
        """The production case: credentials set, ``dsp_jobs`` not created yet.

        Without the probe this returns ``SupabaseJobStore`` and every job
        breaks in a way the user sees as a 404.
        """
        self._configure_supabase(monkeypatch)

        def _missing_table(*_a, **_k):
            raise RuntimeError(
                "Could not find the table public.dsp_jobs in the schema cache"
            )

        fake = SimpleNamespace(table=_missing_table)
        monkeypatch.setattr(
            supabase_client_mod, "get_supabase_client", lambda *a, **k: fake
        )
        assert isinstance(get_job_store(), InMemoryJobStore)

    def test_falls_back_when_the_key_is_rejected(self, monkeypatch):
        """Same outcome, different cause: bad credentials."""
        self._configure_supabase(monkeypatch)

        def _unauthorized(*_a, **_k):
            raise RuntimeError("401 Unauthorized")

        fake = SimpleNamespace(table=_unauthorized)
        monkeypatch.setattr(
            supabase_client_mod, "get_supabase_client", lambda *a, **k: fake
        )
        assert isinstance(get_job_store(), InMemoryJobStore)


class TestStaleJobs:
    """The failure mode the in-memory version had: a worker that dies mid-job
    cannot write the terminal state, so nothing would ever resolve the job."""

    def test_expired_lease_on_a_running_job_is_stale(self):
        record = JobRecord(
            job_id="j1",
            kind="mix",
            status=JobStatus.PROCESSING,
            lease_expires_at=datetime.now(UTC) - timedelta(seconds=10),
        )
        assert is_stale(record)

    def test_fresh_lease_is_not_stale(self):
        record = JobRecord(
            job_id="j1",
            kind="mix",
            lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        assert not is_stale(record)

    def test_heartbeat_resurrects_a_stale_job(self):
        """A live worker refreshing its lease must not be reported dead."""
        store = InMemoryJobStore()
        record = store.create("mix")
        store._jobs[record.job_id].lease_expires_at = datetime.now(UTC) - timedelta(
            seconds=5
        )
        assert is_stale(store.get(record.job_id))

        store.heartbeat(record.job_id)
        assert not is_stale(store.get(record.job_id))

    def test_stale_terminal_job_is_never_stale(self):
        record = JobRecord(
            job_id="j1",
            kind="mix",
            status=JobStatus.ERROR,
            lease_expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        assert not is_stale(record)


def test_public_view_hides_internal_lease():
    """The client polls this constantly; leases and column names are not its
    business."""
    record = JobRecord(job_id="j1", kind="mix", progress=50)
    view = public_view(record)

    assert view["job_id"] == "j1"
    assert view["status"] == "processing"
    assert view["progress"] == 50
    assert "lease_expires_at" not in view
    assert "updated_at" not in view or isinstance(view["updated_at"], str)


# ── Storage unit tests ──────────────────────────────────────────────────


class TestStorageKeys:
    def test_key_is_namespaced_by_session(self):
        key = storage.build_key("mixes", "abc", "abc_mix.wav")
        assert key == "mixes/abc/abc_mix.wav"

    def test_key_strips_slash_noise(self):
        assert storage.build_key("mixes/", "/abc/") == "mixes/abc"

    def test_public_url_is_none_without_configuration(self, monkeypatch):
        monkeypatch.setattr(settings, "r2_public_url", "")
        assert storage.public_url("mixes/a.wav") is None

    def test_public_url_joins_cleanly(self, monkeypatch):
        monkeypatch.setattr(settings, "r2_public_url", "https://cdn.example.com/")
        assert (
            storage.public_url("mixes/a.wav") == "https://cdn.example.com/mixes/a.wav"
        )

    def test_unconfigured_r2_fails_loudly(self, monkeypatch):
        """A missing credential must raise, not silently fall back to a temp
        file that the next restart deletes."""
        monkeypatch.setattr(settings, "r2_endpoint", "")
        monkeypatch.setattr(settings, "r2_access_key_id", "")
        monkeypatch.setattr(settings, "r2_secret_access_key", "")
        monkeypatch.setattr(settings, "r2_bucket", "")
        storage.reset_client()

        with pytest.raises(storage.StorageError) as exc:
            storage.get_s3_client()
        assert "not configured" in str(exc.value)

    def test_no_credential_has_a_hardcoded_default(self):
        """Regression guard: a credential in source is a leaked credential."""
        assert settings.r2_access_key_id == ""
        assert settings.r2_secret_access_key == ""


# ── Endpoint tests ──────────────────────────────────────────────────────


class TestMixJobEndpoints:
    @pytest.fixture(autouse=True)
    def _store(self, monkeypatch):
        """Force the in-memory store so tests never touch a real database."""
        store = InMemoryJobStore()
        monkeypatch.setattr(job_store_mod, "_store", store)
        yield store
        monkeypatch.setattr(job_store_mod, "_store", None)

    def test_submit_returns_202_with_a_job_id(self, tmp_path, monkeypatch):
        """The whole point: the response does not wait for the DSP chain."""
        session_id = _register_session(tmp_path, monkeypatch)
        monkeypatch.setattr(jobs_mod, "run_mix_job", lambda *a, **k: None)

        resp = client.post(f"/api/jobs/mix/{session_id}", json={})

        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["job_id"].startswith("mix_")
        assert body["status"] == "processing"
        assert body["session_id"] == session_id

    def test_session_is_marked_processing_at_submit(self, tmp_path, monkeypatch):
        """A concurrent GET /session/{id} must see "processing", not a mix
        that looks absent."""
        session_id = _register_session(tmp_path, monkeypatch)
        monkeypatch.setattr(jobs_mod, "run_mix_job", lambda *a, **k: None)

        client.post(f"/api/jobs/mix/{session_id}", json={})

        assert upload_mod.sessions[session_id].mix_status == "processing"

    def test_unknown_session_is_404(self, tmp_path, monkeypatch):
        _register_session(tmp_path, monkeypatch)
        assert client.post(f"/api/jobs/mix/{uuid.uuid4()}", json={}).status_code == 404

    def test_session_without_audio_is_400(self, tmp_path, monkeypatch):
        session_id = _register_session(tmp_path, monkeypatch)
        upload_mod.sessions[session_id].original_path = None

        resp = client.post(f"/api/jobs/mix/{session_id}", json={})
        assert resp.status_code == 400

    def test_out_of_band_trims_are_rejected(self, tmp_path, monkeypatch):
        """Same strict contract as the blocking endpoint: 422, not a silent
        clamp."""
        session_id = _register_session(tmp_path, monkeypatch)
        monkeypatch.setattr(jobs_mod, "run_mix_job", lambda *a, **k: None)

        resp = client.post(
            f"/api/jobs/mix/{session_id}",
            json={"stem_trims": {"drums_db": 99.0}},
        )
        assert resp.status_code == 422

    def test_options_survive_the_submit(self, tmp_path, monkeypatch):
        """The job outlives the request, so the options are captured, not
        referenced."""
        session_id = _register_session(tmp_path, monkeypatch)
        captured = {}

        def _capture(job_id, sid, options):
            captured["dimension"] = options.dimension_enabled
            captured["auto"] = options.auto_balance
            captured["trims"] = options.stem_trims

        monkeypatch.setattr(jobs_mod, "run_mix_job", _capture)
        client.post(
            f"/api/jobs/mix/{session_id}",
            json={
                "dimension_enabled": False,
                "auto_balance": True,
                "stem_trims": {"vocals_db": -1.5},
            },
        )

        assert captured["dimension"] is False
        assert captured["auto"] is True
        assert captured["trims"] == {"vocals_db": -1.5}

    def test_poll_resigns_the_expired_r2_url(self, tmp_path, monkeypatch):
        """The URL minted at completion expires. Reading the job later must
        hand back a fresh one, otherwise every mix older than the presign TTL
        is a completed job pointing at a 403."""
        session_id = _register_session(tmp_path, monkeypatch)
        monkeypatch.setattr(jobs_mod, "run_mix_job", lambda *a, **k: None)
        job_id = client.post(f"/api/jobs/mix/{session_id}", json={}).json()["job_id"]

        key = f"mixes/{session_id}/{session_id}_mix.wav"
        _active_store().update(
            job_id,
            status=JobStatus.COMPLETED,
            progress=100,
            result={"r2_key": key, "download_url": "https://expired.example/x"},
        )
        monkeypatch.setattr(
            storage,
            "presigned_url",
            lambda k, **kw: f"https://r2.example/{k}?sig=fresh",
        )

        result = client.get(f"/api/jobs/mix/{job_id}").json()["result"]
        assert result["download_url"] == f"https://r2.example/{key}?sig=fresh"
        assert result["r2_key"] == key

    def test_poll_prefers_the_public_url_over_presigning(self, tmp_path, monkeypatch):
        """A public URL never expires, so it beats a presign that will rot."""
        session_id = _register_session(tmp_path, monkeypatch)
        monkeypatch.setattr(jobs_mod, "run_mix_job", lambda *a, **k: None)
        job_id = client.post(f"/api/jobs/mix/{session_id}", json={}).json()["job_id"]

        key = f"mixes/{session_id}/{session_id}_mix.wav"
        _active_store().update(
            job_id, status=JobStatus.COMPLETED, progress=100, result={"r2_key": key}
        )
        monkeypatch.setattr(
            settings, "r2_public_url", "https://pub.example", raising=False
        )

        result = client.get(f"/api/jobs/mix/{job_id}").json()["result"]
        assert result["download_url"] == f"https://pub.example/{key}"

    def test_poll_survives_r2_being_unreachable(self, tmp_path, monkeypatch):
        """A transient R2 outage must not turn a valid completed job into a
        500; the row stays valid and the client can re-read it."""
        session_id = _register_session(tmp_path, monkeypatch)
        monkeypatch.setattr(jobs_mod, "run_mix_job", lambda *a, **k: None)
        job_id = client.post(f"/api/jobs/mix/{session_id}", json={}).json()["job_id"]

        _active_store().update(
            job_id,
            status=JobStatus.COMPLETED,
            progress=100,
            result={"r2_key": f"mixes/{session_id}/x.wav"},
        )

        def _down(*_a, **_kw):
            raise storage.StorageError("R2 unreachable")

        monkeypatch.setattr(storage, "presigned_url", _down)

        body = client.get(f"/api/jobs/mix/{job_id}")
        assert body.status_code == 200
        assert body.json()["status"] == "completed"
        # No dead/invented URL is handed over.
        assert "download_url" not in body.json()["result"]

    def test_poll_reports_the_terminal_state_and_r2_url(self, tmp_path, monkeypatch):
        session_id = _register_session(tmp_path, monkeypatch)
        monkeypatch.setattr(jobs_mod, "run_mix_job", lambda *a, **k: None)
        job_id = client.post(f"/api/jobs/mix/{session_id}", json={}).json()["job_id"]

        _active_store().update(
            job_id,
            status=JobStatus.COMPLETED,
            progress=100,
            result={"download_url": "https://r2.example/mix.wav"},
        )

        body = client.get(f"/api/jobs/mix/{job_id}").json()
        assert body["status"] == "completed"
        assert body["progress"] == 100
        assert body["result"]["download_url"] == "https://r2.example/mix.wav"

    def test_poll_reports_an_interrupted_job_as_error(self, tmp_path, monkeypatch):
        """A worker that died mid-mix leaves a ``processing`` row. Reporting
        it as still-running would make the client poll forever."""
        session_id = _register_session(tmp_path, monkeypatch)
        monkeypatch.setattr(jobs_mod, "run_mix_job", lambda *a, **k: None)
        job_id = client.post(f"/api/jobs/mix/{session_id}", json={}).json()["job_id"]

        _active_store().get(job_id).lease_expires_at = datetime.now(UTC) - timedelta(
            minutes=1
        )

        body = client.get(f"/api/jobs/mix/{job_id}").json()
        assert body["status"] == "error"
        assert "interrupted" in body["error"].lower()

    def test_unknown_job_is_404(self):
        assert client.get(f"/api/jobs/mix/{uuid.uuid4()}").status_code == 404


class TestMixJobExecution:
    """The background task: upload to R2, then resolve the job."""

    @pytest.fixture(autouse=True)
    def _store(self, monkeypatch):
        store = InMemoryJobStore()
        monkeypatch.setattr(job_store_mod, "_store", store)
        yield store
        monkeypatch.setattr(job_store_mod, "_store", None)

    def test_success_uploads_to_r2_and_completes(self, tmp_path, monkeypatch):
        session_id = _register_session(tmp_path, monkeypatch)
        monkeypatch.setattr(mix_jobs, "build_mix", _fake_build_mix)
        monkeypatch.setattr(
            mix_jobs.storage, "upload_file", lambda *a, **k: "mixes/x.wav"
        )
        monkeypatch.setattr(
            mix_jobs.storage, "presigned_url", lambda *a, **k: "https://r2/x.wav"
        )

        job = mix_jobs.submit_mix_job(
            session_id, mix_jobs.MixJobOptions(), original_path="unused"
        )
        mix_jobs.run_mix_job(job.job_id, session_id, mix_jobs.MixJobOptions())

        stored = _active_store().get(job.job_id)
        assert stored.status is JobStatus.COMPLETED
        assert stored.progress == 100
        assert stored.result["download_url"] == "https://r2/x.wav"
        assert stored.result["r2_key"] == f"mixes/{session_id}/{session_id}_mix.wav"

    def test_dsp_failure_is_recorded_not_raised(self, tmp_path, monkeypatch):
        """An exception escaping a BackgroundTask is logged and dropped, which
        would leave the client waiting on a dead job."""
        session_id = _register_session(tmp_path, monkeypatch)

        def _boom(*args, **kwargs):
            raise RuntimeError("dsp exploded")

        monkeypatch.setattr(mix_jobs, "build_mix", _boom)

        job = mix_jobs.submit_mix_job(
            session_id, mix_jobs.MixJobOptions(), original_path="unused"
        )
        mix_jobs.run_mix_job(job.job_id, session_id, mix_jobs.MixJobOptions())

        stored = _active_store().get(job.job_id)
        assert stored.status is JobStatus.ERROR
        assert "dsp exploded" in stored.error

    def test_r2_failure_marks_the_job_failed(self, tmp_path, monkeypatch):
        """A mix that "succeeded" but whose bytes were never stored must not
        be reported as completed."""
        session_id = _register_session(tmp_path, monkeypatch)
        monkeypatch.setattr(mix_jobs, "build_mix", _fake_build_mix)

        def _upload_fail(*args, **kwargs):
            raise storage.StorageError("R2 upload failed")

        monkeypatch.setattr(mix_jobs.storage, "upload_file", _upload_fail)

        job = mix_jobs.submit_mix_job(
            session_id, mix_jobs.MixJobOptions(), original_path="unused"
        )
        mix_jobs.run_mix_job(job.job_id, session_id, mix_jobs.MixJobOptions())

        stored = _active_store().get(job.job_id)
        assert stored.status is JobStatus.ERROR
        assert "R2 upload failed" in stored.error


def test_blocking_mix_endpoint_still_exists():
    """The async path is additive: the existing blocking contract must not
    disappear under it."""
    paths = app.openapi()["paths"]
    assert "post" in paths["/api/session/{session_id}/mix"]
    assert "post" in paths["/api/jobs/mix/{session_id}"]
