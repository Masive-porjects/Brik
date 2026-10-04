"""Mastering job state backed by the shared JobStore.

The regression that motivated this file: job state used to live in a module
dict (``dsp_worker._active_jobs``) that died with the process. After a
redeploy, ``GET /api/jobs/master/{id}`` returned 404 for a job the client
had legitimately submitted, and the poller hung forever.

These tests pin the three properties that fix it:
  1. the submitted job is readable BEFORE the worker starts (no 404 window),
  2. the response shape is still the one the Studio client consumes,
  3. a worker that dies leaves a detectable orphan, not a silent "processing".
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from audiomind.main import app
from audiomind.services import dsp_worker
from audiomind.services import job_store as job_store_mod
from audiomind.services.job_store import JobStatus
from audiomind.services.mix_jobs import _heartbeat_loop
from audiomind.services.dsp_worker import get_job_status, run_async_master_job


@pytest.fixture
def store():
    """A real in-memory store, installed as the process-wide one."""
    active = job_store_mod.InMemoryJobStore()
    previous = job_store_mod.get_job_store()
    job_store_mod.set_job_store(active)
    try:
        yield active
    finally:
        job_store_mod.set_job_store(previous)


@pytest.fixture
def client() -> Any:
    return TestClient(app)


@pytest.fixture
def queued() -> Any:
    """Neutralise the background worker so only registration is under test.

    ``TestClient`` runs ``BackgroundTasks`` synchronously, so without this the
    real worker executes inside the submit call and turns every observation
    into a pipeline failure. Here we are testing that the record exists
    BEFORE the worker touches it.
    """
    with patch("audiomind.api.jobs.run_async_master_job") as stub:
        yield stub


def _submit(client: TestClient, *, is_async: bool = True) -> dict[str, Any]:
    resp = client.post(
        "/api/jobs/master",
        json={
            "track_id": str(uuid.uuid4()),
            "input_audio_url": "https://example.com/audio.wav",
            "preset_id": "universal",
            "is_async": is_async,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestSubmitRegistersBeforeQueueing:
    """The poller must never 404 a job the server already accepted."""

    def test_job_is_readable_immediately_after_submit(
        self, client: TestClient, store: Any, queued: Any
    ) -> None:
        body = _submit(client)
        assert body["status"] == "processing"

        # No worker has run: the record still exists, which is the whole point.
        status = client.get(f"/api/jobs/master/{body['job_id']}")
        assert status.status_code == 200, status.text
        assert status.json()["status"] == "processing"
        assert status.json()["track_id"] == body["track_id"]

    def test_registered_job_is_actually_in_the_store(
        self, client: TestClient, store: Any, queued: Any
    ) -> None:
        body = _submit(client)
        record = store.get(body["job_id"])
        assert record is not None, "submit must write to the job store"
        assert record.kind == "master"
        assert record.meta["track_id"] == body["track_id"]
        assert record.status is JobStatus.PROCESSING

    def test_no_module_level_dict_remains(self) -> None:
        """The process-owned dict is the bug; it must not come back."""
        from audiomind.services import dsp_worker

        assert not hasattr(dsp_worker, "_active_jobs")


class TestResponseShapeIsPreserved:
    """The client contract is fixed: ``AsyncJobStatus`` in client.ts."""

    def test_legacy_fields_are_present_while_processing(
        self, client: TestClient, store: Any, queued: Any
    ) -> None:
        body = _submit(client)
        data = client.get(f"/api/jobs/master/{body['job_id']}").json()
        assert set(data) == {
            "job_id",
            "track_id",
            "status",
            "started_at",
            "completed_at",
            "result",
            "error",
        }
        assert data["completed_at"] is None
        assert data["result"] is None
        assert data["error"] is None
        assert data["started_at"]

    def test_unknown_job_is_still_404(self, client: TestClient, store: Any) -> None:
        assert client.get("/api/jobs/master/nope_123").status_code == 404

    def test_reading_a_job_does_not_mutate_it(
        self, client: TestClient, store: Any, queued: Any
    ) -> None:
        """A reader must not overwrite a lease a live worker is refreshing."""
        body = _submit(client)
        first = store.get(body["job_id"])
        assert first is not None
        client.get(f"/api/jobs/master/{body['job_id']}")
        again = store.get(body["job_id"])
        assert again is not None
        assert again.status is JobStatus.PROCESSING
        assert again.lease_expires_at == first.lease_expires_at


class TestOrphanDetection:
    """A dead worker must not be indistinguishable from a slow one."""

    def test_expired_lease_reports_error_not_processing(
        self, store: Any
    ) -> None:
        record = store.create("master", meta={"track_id": "t1"})
        # Simulate a worker that died: the lease ran out.
        record.lease_expires_at = record.updated_at - timedelta(seconds=60)

        status = get_job_status(record.job_id)
        assert status is not None
        assert status["status"] == "error"
        assert "interrupted" in (status["error"] or "").lower()
        assert status["completed_at"]

    def test_live_lease_still_reports_processing(self, store: Any) -> None:
        record = store.create("master", meta={"track_id": "t1"})
        status = get_job_status(record.job_id)
        assert status is not None
        assert status["status"] == "processing"
        assert status["error"] is None

    def test_heartbeat_loop_refreshes_then_stops(
        self, store: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The heartbeat must extend the lease and exit when told to stop."""
        import threading

        # The production lease is 900s, so the first beat lands 300s in. The
        # loop reads the interval from settings, so shrinking the lease shrinks
        # the wait without weakening the assertion.
        monkeypatch.setattr(
            dsp_worker.settings, "job_lease_seconds", 15, raising=False
        )
        assert max(5, dsp_worker.settings.job_lease_seconds // 3) == 5

        record = store.create("master", meta={"track_id": "t1"})
        expired = record.updated_at - timedelta(seconds=60)
        record.lease_expires_at = expired

        stop = threading.Event()
        thread = threading.Thread(
            target=_heartbeat_loop, args=(store, record.job_id, stop), daemon=True
        )
        thread.start()
        deadline = time.monotonic() + 20
        refreshed = False
        while time.monotonic() < deadline:
            current = store.get(record.job_id)
            assert current is not None
            if current.lease_expires_at > expired:
                refreshed = True
                break
            time.sleep(0.2)
        stop.set()
        thread.join(timeout=5)

        assert refreshed, "lease was never refreshed"
        assert not thread.is_alive(), "heartbeat ignored the stop event"


class TestRunnerRecordsTerminalState:
    """The worker must leave a durable verdict, success or failure."""

    def _payload(self) -> Any:
        from audiomind.services.dsp_worker import MasterJobPayload

        return MasterJobPayload(
            track_id=str(uuid.uuid4()),
            input_audio_url="https://example.com/audio.wav",
            preset_id="universal",
        )

    def test_success_is_recorded_with_progress_100(self, store: Any) -> None:
        from audiomind.services.dsp_worker import MasterJobResult

        job_id = store.create("master", meta={"track_id": "t1"}).job_id
        result = MasterJobResult(
            success=True,
            job_id=job_id,
            track_id="t1",
            master_id="master_abc",
            status="completed",
            storage_path="audio-masters/t1.wav",
        )
        with patch(
            "audiomind.services.dsp_worker.execute_master_job", return_value=result
        ):
            run_async_master_job(self._payload(), job_id)

        status = get_job_status(job_id)
        assert status is not None
        assert status["status"] == "completed"
        assert status["result"]["master_id"] == "master_abc"
        assert status["error"] is None

    def test_pipeline_failure_is_recorded_as_error(self, store: Any) -> None:
        from audiomind.services.dsp_worker import MasterJobResult

        job_id = store.create("master", meta={"track_id": "t1"}).job_id
        result = MasterJobResult(
            success=False,
            job_id=job_id,
            track_id="t1",
            master_id="master_abc",
            status="error",
            error="no input audio",
        )
        with patch(
            "audiomind.services.dsp_worker.execute_master_job", return_value=result
        ):
            run_async_master_job(self._payload(), job_id)

        status = get_job_status(job_id)
        assert status is not None
        assert status["status"] == "error"
        assert status["error"] == "no input audio"

    def test_unexpected_exception_does_not_escape(self, store: Any) -> None:
        """A raising task would leave the client polling a dead job."""
        job_id = store.create("master", meta={"track_id": "t1"}).job_id
        with patch(
            "audiomind.services.dsp_worker.execute_master_job",
            side_effect=RuntimeError("boom"),
        ):
            run_async_master_job(self._payload(), job_id)

        status = get_job_status(job_id)
        assert status is not None
        assert status["status"] == "error"
        assert "boom" in (status["error"] or "")

    def test_missing_record_is_created_instead_of_crashing(
        self, store: Any
    ) -> None:
        """Direct callers (tests, scripts) may pass a job_id never created."""
        from audiomind.services.dsp_worker import MasterJobResult

        orphan_id = "master_never_registered"
        result = MasterJobResult(
            success=True,
            job_id=orphan_id,
            track_id="t1",
            master_id="master_abc",
            status="completed",
        )
        with patch(
            "audiomind.services.dsp_worker.execute_master_job", return_value=result
        ):
            run_async_master_job(self._payload(), orphan_id)

        assert store.get(orphan_id) is not None
