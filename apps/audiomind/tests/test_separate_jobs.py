"""Async, idempotent stem separation: submit, worker, and poll.

The property under test is idempotency. Separating the same audio twice must
run Demucs once: a finished separation for this user + project + media_hash is
reused, not re-run. The suite drives ``submit_separate_job`` / ``run_separate_job``
directly for the DSP + store mechanics and the HTTP endpoints for the
ownership and status contracts, with the real ``InMemoryJobStore`` in play so
the idempotency probe is exercised against the same code production uses.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import audiomind.services.separate_jobs as separate_mod
import audiomind.services.supabase_client as supabase_mod
from audiomind.config import settings
from audiomind.main import app
from audiomind.services import storage as storage_mod
from audiomind.services.job_store import InMemoryJobStore, JobStatus, set_job_store

client = TestClient(app)

#: Bytes the fake R2 download produces; the worker hashes exactly these.
_DOWNLOAD_BYTES = b"RIFF....WAVE-original-audio-payload"
#: The SHA-256 the worker will compute for ``_DOWNLOAD_BYTES``.
_DOWNLOAD_HASH = hashlib.sha256(_DOWNLOAD_BYTES).hexdigest()

_STEMS = ("drums", "bass", "other", "vocals")


# ── Minimal fake Supabase (projects + audio_assets only) ───────────────────


class _FakeTable:
    def __init__(self, store: _FakeClient, name: str) -> None:
        self._store = store
        self._name = name
        self._op: str | None = None
        self._payload: dict[str, Any] | None = None
        self._patch: dict[str, Any] | None = None
        self._filters: list[tuple[str, Any]] = []
        self._limit: int | None = None

    def select(self, _cols: str = "*") -> _FakeTable:
        self._op = "select"
        return self

    def insert(self, payload: dict[str, Any]) -> _FakeTable:
        self._op, self._payload = "insert", payload
        return self

    def update(self, patch: dict[str, Any]) -> _FakeTable:
        self._op, self._patch = "update", patch
        return self

    def eq(self, column: str, value: Any) -> _FakeTable:
        self._filters.append((column, value))
        return self

    def limit(self, count: int) -> _FakeTable:
        self._limit = count
        return self

    def execute(self) -> SimpleNamespace:
        rows = self._store.tables[self._name]
        if self._op == "insert":
            row = dict(self._payload or {})
            row.setdefault("id", str(uuid.uuid4()))
            rows.append(row)
            return SimpleNamespace(data=[dict(row)])
        matched = [
            r for r in rows if all(r.get(c) == v for c, v in self._filters)
        ]
        if self._op == "update":
            for row in matched:
                row.update(self._patch or {})
        if self._limit is not None:
            matched = matched[: self._limit]
        return SimpleNamespace(data=[dict(r) for r in matched])


class _FakeAuth:
    """Token → user resolver mirroring ``client.auth.get_user(token)``."""

    def __init__(self, users: dict[str, str]) -> None:
        self._users = users

    def get_user(self, token: str) -> Any:
        user_id = self._users.get(token)
        if user_id is None:
            raise RuntimeError("invalid JWT")
        return SimpleNamespace(user=SimpleNamespace(id=user_id))


class _FakeClient:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "projects": [],
            "audio_assets": [],
        }
        self.auth = _FakeAuth({"tok_a": "user-a", "tok_b": "user-b"})

    def table(self, name: str) -> _FakeTable:
        return _FakeTable(self, name)


class _BackgroundTasks:
    """Stand-in that captures enqueued work instead of running it."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, tuple[Any, ...]]] = []

    def add_task(self, fn: Any, *args: Any) -> None:
        self.calls.append((fn, args))


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def store() -> InMemoryJobStore:
    """A fresh in-memory job store, isolated from other tests."""
    fresh = InMemoryJobStore()
    set_job_store(fresh)
    yield fresh
    set_job_store(None)


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    fake = _FakeClient()
    monkeypatch.setattr(
        supabase_mod, "get_supabase_client", lambda *_a, **_k: fake
    )
    monkeypatch.setattr(settings, "license_key", "")
    return fake


@pytest.fixture
def dsp(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the R2 transfers and Demucs; record what ran."""
    calls: dict[str, Any] = {"uploads": [], "splits": 0}

    def _download(key: str, local_path: str) -> str:
        Path(local_path).write_bytes(_DOWNLOAD_BYTES)
        return local_path

    def _upload(local_path: str, key: str, content_type: str = "audio/wav") -> str:
        calls["uploads"].append(key)
        return key

    def _split(input_path: str, output_dir: str, model: str = "htdemucs") -> dict:
        calls["splits"] += 1
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        stems: dict[str, str] = {}
        for name in _STEMS:
            p = out / f"{name}.wav"
            p.write_bytes(b"stem:" + name.encode())
            stems[name] = str(p)
        return {
            "stems": stems,
            "sample_rate": 44100,
            "duration_seconds": 9.5,
            "stem_audio_dir": str(out),
        }

    monkeypatch.setattr(storage_mod, "download_to", _download)
    monkeypatch.setattr(storage_mod, "upload_file", _upload)
    monkeypatch.setattr(storage_mod, "presigned_url", lambda key, **kw: f"https://r2.example/{key}")
    monkeypatch.setattr(separate_mod, "split_audio", _split)
    return calls


def _seed(
    fake: _FakeClient,
    *,
    user_id: str = "user-a",
    project_id: str | None = None,
    media_hash: str | None = None,
    kind: str = "original",
    asset_id: str | None = None,
) -> tuple[str, str]:
    """Insert a project + an asset row directly and return their ids."""
    pid = project_id or str(uuid.uuid4())
    if not any(p["id"] == pid for p in fake.tables["projects"]):
        fake.tables["projects"].append({"id": pid, "user_id": user_id, "name": "P"})
    aid = asset_id or str(uuid.uuid4())
    fake.tables["audio_assets"].append(
        {
            "id": aid,
            "project_id": pid,
            "user_id": user_id,
            "kind": kind,
            "r2_key": f"projects/{pid}/{kind}/{aid}.wav",
            "media_hash": media_hash,
        }
    )
    return pid, aid


# ── Submit idempotency ─────────────────────────────────────────────────────


class TestSubmitIdempotency:
    def test_first_submit_queues_a_job(
        self, store: InMemoryJobStore, fake_db: _FakeClient
    ) -> None:
        pid, aid = _seed(fake_db, media_hash=_DOWNLOAD_HASH)
        tasks = _BackgroundTasks()
        outcome = separate_mod.submit_separate_job(
            user_id="user-a",
            project_id=pid,
            asset_id=aid,
            media_hash=_DOWNLOAD_HASH,
            background_tasks=tasks,
        )
        assert outcome.reused is False
        assert outcome.status == "processing"
        assert len(tasks.calls) == 1  # the worker was enqueued
        record = store.get(outcome.job_id)
        assert record is not None and record.kind == "separate"
        assert record.meta["media_hash"] == _DOWNLOAD_HASH

    def test_completed_separation_is_reused_not_requeued(
        self, store: InMemoryJobStore, fake_db: _FakeClient, dsp: dict[str, Any]
    ) -> None:
        pid, aid = _seed(fake_db, media_hash=_DOWNLOAD_HASH)

        first = separate_mod.submit_separate_job(
            user_id="user-a", project_id=pid, asset_id=aid,
            media_hash=_DOWNLOAD_HASH, background_tasks=_BackgroundTasks(),
        )
        separate_mod.run_separate_job(first.job_id)  # actually separates
        assert dsp["splits"] == 1
        assert store.get(first.job_id).status == JobStatus.COMPLETED

        # Same bytes again: reuse, no new job, no second Demucs run.
        second = separate_mod.submit_separate_job(
            user_id="user-a", project_id=pid, asset_id=aid,
            media_hash=_DOWNLOAD_HASH, background_tasks=_BackgroundTasks(),
        )
        assert second.reused is True
        assert second.status == "completed"
        assert second.job_id == first.job_id
        assert len(second.result["stems"]) == 4
        assert dsp["splits"] == 1  # still one Demucs run

    def test_reuse_is_scoped_to_one_project(
        self, store: InMemoryJobStore, fake_db: _FakeClient, dsp: dict[str, Any]
    ) -> None:
        """The same bytes in a DIFFERENT project must separate again."""
        pid_a, aid_a = _seed(fake_db, media_hash=_DOWNLOAD_HASH)
        first = separate_mod.submit_separate_job(
            user_id="user-a", project_id=pid_a, asset_id=aid_a,
            media_hash=_DOWNLOAD_HASH, background_tasks=_BackgroundTasks(),
        )
        separate_mod.run_separate_job(first.job_id)

        pid_b, aid_b = _seed(fake_db, media_hash=_DOWNLOAD_HASH)
        second = separate_mod.submit_separate_job(
            user_id="user-a", project_id=pid_b, asset_id=aid_b,
            media_hash=_DOWNLOAD_HASH, background_tasks=_BackgroundTasks(),
        )
        assert second.reused is False
        assert second.job_id != first.job_id
        separate_mod.run_separate_job(second.job_id)  # a real second run
        assert dsp["splits"] == 2  # a second Demucs run happened

    def test_reuse_is_scoped_to_one_user(
        self, store: InMemoryJobStore, fake_db: _FakeClient, dsp: dict[str, Any]
    ) -> None:
        """A different user with the same bytes must separate again."""
        pid, aid = _seed(fake_db, user_id="user-a", media_hash=_DOWNLOAD_HASH)
        first = separate_mod.submit_separate_job(
            user_id="user-a", project_id=pid, asset_id=aid,
            media_hash=_DOWNLOAD_HASH, background_tasks=_BackgroundTasks(),
        )
        separate_mod.run_separate_job(first.job_id)

        # Same project id but a different owner (defence-in-depth path).
        other = separate_mod.submit_separate_job(
            user_id="user-b", project_id=pid, asset_id=aid,
            media_hash=_DOWNLOAD_HASH, background_tasks=_BackgroundTasks(),
        )
        assert other.reused is False
        separate_mod.run_separate_job(other.job_id)  # a real second run
        assert dsp["splits"] == 2


# ── Worker mechanics ───────────────────────────────────────────────────────


class TestWorker:
    def test_separates_registers_four_stems_and_completes(
        self, store: InMemoryJobStore, fake_db: _FakeClient, dsp: dict[str, Any]
    ) -> None:
        pid, aid = _seed(fake_db, media_hash=_DOWNLOAD_HASH)
        outcome = separate_mod.submit_separate_job(
            user_id="user-a", project_id=pid, asset_id=aid,
            media_hash=_DOWNLOAD_HASH, background_tasks=_BackgroundTasks(),
        )
        separate_mod.run_separate_job(outcome.job_id)

        record = store.get(outcome.job_id)
        assert record.status == JobStatus.COMPLETED
        result = record.result
        assert result["media_hash"] == _DOWNLOAD_HASH
        assert result["original_asset_id"] == aid
        assert len(result["stems"]) == 4
        assert {s["stem_name"] for s in result["stems"]} == set(_STEMS)
        # Every stem went to R2 under this project.
        assert all(k.startswith(f"projects/{pid}/stems/") for k in dsp["uploads"])
        # Every stem is registered as a project asset with the source hash.
        stem_rows = [a for a in fake_db.tables["audio_assets"] if a["kind"] == "stem"]
        assert len(stem_rows) == 4
        assert all(r["media_hash"] == _DOWNLOAD_HASH for r in stem_rows)

    def test_worker_backfills_unknown_media_hash(
        self, store: InMemoryJobStore, fake_db: _FakeClient, dsp: dict[str, Any]
    ) -> None:
        """When the browser did not report a hash, the worker computes it."""
        pid, aid = _seed(fake_db, media_hash=None)  # no hash yet
        outcome = separate_mod.submit_separate_job(
            user_id="user-a", project_id=pid, asset_id=aid,
            media_hash=None, background_tasks=_BackgroundTasks(),
        )
        separate_mod.run_separate_job(outcome.job_id)

        # Computed hash is recorded on the job AND backfilled onto the asset.
        record = store.get(outcome.job_id)
        assert record.meta["media_hash"] == _DOWNLOAD_HASH
        assert record.result["media_hash"] == _DOWNLOAD_HASH
        original = next(
            a for a in fake_db.tables["audio_assets"] if a["id"] == aid
        )
        assert original["media_hash"] == _DOWNLOAD_HASH

        # Now the NEXT submit can probe without re-downloading: it reuses.
        again = separate_mod.submit_separate_job(
            user_id="user-a", project_id=pid, asset_id=aid,
            media_hash=original["media_hash"], background_tasks=_BackgroundTasks(),
        )
        assert again.reused is True
        assert dsp["splits"] == 1

    def test_worker_failure_marks_the_job_error(
        self, store: InMemoryJobStore, fake_db: _FakeClient,
        dsp: dict[str, Any], monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pid, aid = _seed(fake_db, media_hash=_DOWNLOAD_HASH)
        outcome = separate_mod.submit_separate_job(
            user_id="user-a", project_id=pid, asset_id=aid,
            media_hash=_DOWNLOAD_HASH, background_tasks=_BackgroundTasks(),
        )

        def _boom(*_a: Any, **_k: Any) -> dict:
            raise RuntimeError("Demucs exploded")

        monkeypatch.setattr(separate_mod, "split_audio", _boom)
        separate_mod.run_separate_job(outcome.job_id)

        record = store.get(outcome.job_id)
        assert record.status == JobStatus.ERROR
        assert "Demucs exploded" in (record.error or "")


# ── HTTP endpoints ─────────────────────────────────────────────────────────


def _auth(token: str = "tok_a") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestSeparateEndpoint:
    def test_submit_returns_202_with_a_job_id(
        self, store: InMemoryJobStore, fake_db: _FakeClient, dsp: dict[str, Any]
    ) -> None:
        pid, aid = _seed(fake_db, media_hash=_DOWNLOAD_HASH)
        resp = client.post(
            f"/api/projects/{pid}/separate",
            json={"asset_id": aid},
            headers=_auth(),
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["status"] == "processing"
        assert body["reused"] is False
        assert body["job_id"]

    def test_non_original_asset_is_422(
        self, store: InMemoryJobStore, fake_db: _FakeClient
    ) -> None:
        pid, aid = _seed(fake_db, kind="stem")
        resp = client.post(
            f"/api/projects/{pid}/separate",
            json={"asset_id": aid},
            headers=_auth(),
        )
        assert resp.status_code == 422

    def test_foreign_asset_is_404(
        self, store: InMemoryJobStore, fake_db: _FakeClient
    ) -> None:
        pid, aid = _seed(fake_db, user_id="user-a", media_hash=_DOWNLOAD_HASH)
        # Token resolves to user-a; a bogus token maps to no user → 401, so use
        # a project owned by user-a but ask as a mismatched asset id instead.
        resp = client.post(
            f"/api/projects/{pid}/separate",
            json={"asset_id": str(uuid.uuid4())},  # not in this project
            headers=_auth(),
        )
        assert resp.status_code == 404

    def test_missing_token_is_401(
        self, store: InMemoryJobStore, fake_db: _FakeClient
    ) -> None:
        resp = client.post(f"/api/projects/{uuid.uuid4()}/separate", json={})
        assert resp.status_code == 401


class TestSeparatePoll:
    def test_completed_job_returns_stems_with_fresh_urls(
        self, store: InMemoryJobStore, fake_db: _FakeClient, dsp: dict[str, Any]
    ) -> None:
        pid, aid = _seed(fake_db, media_hash=_DOWNLOAD_HASH)
        outcome = separate_mod.submit_separate_job(
            user_id="user-a", project_id=pid, asset_id=aid,
            media_hash=_DOWNLOAD_HASH, background_tasks=_BackgroundTasks(),
        )
        separate_mod.run_separate_job(outcome.job_id)

        resp = client.get(f"/api/jobs/separate/{outcome.job_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        for stem in body["result"]["stems"]:
            assert stem["download_url"].startswith("https://r2.example/")

    def test_unknown_job_is_404(self, store: InMemoryJobStore) -> None:
        assert client.get(f"/api/jobs/separate/{uuid.uuid4()}").status_code == 404

    def test_processing_job_has_no_urls(
        self, store: InMemoryJobStore, fake_db: _FakeClient
    ) -> None:
        pid, aid = _seed(fake_db, media_hash=_DOWNLOAD_HASH)
        outcome = separate_mod.submit_separate_job(
            user_id="user-a", project_id=pid, asset_id=aid,
            media_hash=_DOWNLOAD_HASH, background_tasks=_BackgroundTasks(),
        )
        resp = client.get(f"/api/jobs/separate/{outcome.job_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "processing"
