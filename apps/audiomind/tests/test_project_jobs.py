"""Project-native mix and mastering jobs (WU5 closure): submit, worker, poll.

The suite drives ``submit_project_mix_job`` / ``run_project_mix_job`` and the
mastering twins directly for the DSP + store mechanics, and the HTTP endpoints
for the ownership and status contracts, with the real ``InMemoryJobStore`` in
play — the same seam the separation suite uses.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import audiomind.api.projects as projects_mod
import audiomind.services.project_jobs as jobs_mod
import audiomind.services.supabase_client as supabase_mod
from audiomind.config import settings
from audiomind.main import app
from audiomind.models.audio import MasteringParameters
from audiomind.services import storage as storage_mod
from audiomind.services.compile_project import MixPlan, StateProjection, compile
from audiomind.services.job_store import InMemoryJobStore, JobStatus, set_job_store

client = TestClient(app)

#: Bytes the fake R2 download produces.
_DOWNLOAD_BYTES = b"RIFF....WAVE-original-audio-payload"


# ── Minimal fake Supabase (projects + audio_assets + documents/states) ──────


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
            "project_documents": [],
            "project_states": [],
        }
        self.auth = _FakeAuth({"tok_a": "user-a", "tok_b": "user-b"})

    def table(self, name: str) -> _FakeTable:
        return _FakeTable(self, name)


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
def dsp_mix(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the R2 transfers and the mix engine for mix worker tests."""
    calls: dict[str, Any] = {"uploads": [], "mix_kwargs": []}

    def _download(key: str, local_path: str) -> str:
        Path(local_path).write_bytes(_DOWNLOAD_BYTES)
        return local_path

    def _upload(local_path: str, key: str, content_type: str = "audio/wav") -> str:
        calls["uploads"].append(key)
        return key

    def _engine(session_id: str, input_path: str, **kw: Any) -> dict[str, Any]:
        calls["mix_kwargs"].append(kw)
        out = Path(input_path).parent / "mixed.wav"
        out.write_bytes(b"RIFF....mix")
        return {"mix_path": str(out), "sample_rate": 44100, "duration_seconds": 3.5}

    monkeypatch.setattr(storage_mod, "download_to", _download)
    monkeypatch.setattr(storage_mod, "upload_file", _upload)
    monkeypatch.setattr(
        storage_mod, "presigned_url", lambda key, **kw: f"https://r2.example/{key}"
    )
    monkeypatch.setattr(jobs_mod, "build_mix", _engine)
    return calls


@pytest.fixture
def dsp_master(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the R2 transfers and the mastering chain for master worker tests."""
    calls: dict[str, Any] = {"uploads": [], "params": None}

    def _download(key: str, local_path: str) -> str:
        Path(local_path).write_bytes(_DOWNLOAD_BYTES)
        return local_path

    def _upload(local_path: str, key: str, content_type: str = "audio/wav") -> str:
        calls["uploads"].append(key)
        return key

    def _engine(
        input_path: str | Path, output_path: str | Path, params: MasteringParameters, **_kw: Any
    ) -> dict[str, Any]:
        calls["params"] = params
        Path(output_path).write_bytes(b"RIFF....master")
        return {"sample_rate": 44100, "duration_seconds": 3.5}

    monkeypatch.setattr(storage_mod, "download_to", _download)
    monkeypatch.setattr(storage_mod, "upload_file", _upload)
    monkeypatch.setattr(
        storage_mod, "presigned_url", lambda key, **kw: f"https://r2.example/{key}"
    )
    monkeypatch.setattr(jobs_mod, "process_audio", _engine)
    return calls


def _seed(
    fake: _FakeClient,
    *,
    user_id: str = "user-a",
    project_id: str | None = None,
    kind: str = "original",
    asset_id: str | None = None,
    created_at: str = "2026-10-08T00:00:00+00:00",
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
            "created_at": created_at,
        }
    )
    return pid, aid


def _auth(token: str = "tok_a") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Submit: source resolution and plan pinning ──────────────────────────────


class TestSubmit:
    def test_mix_submit_pins_the_requested_asset(
        self, store: InMemoryJobStore, fake_db: _FakeClient
    ) -> None:
        pid, aid = _seed(fake_db)
        plan = compile(None, StateProjection())
        record = jobs_mod.submit_project_mix_job(pid, "user-a", aid, fake_db, plan)
        assert record.kind == "mix"
        assert record.meta["asset_id"] == aid
        assert record.meta["r2_key"] == f"projects/{pid}/original/{aid}.wav"
        assert record.meta["plan"]["dimension_enabled"] is True

    def test_mix_submit_without_asset_id_picks_newest_original(
        self, store: InMemoryJobStore, fake_db: _FakeClient
    ) -> None:
        _, older = _seed(fake_db, created_at="2026-10-08T00:00:00+00:00")
        pid, newer = _seed(fake_db, created_at="2026-10-09T00:00:00+00:00")
        assert newer != older
        plan = compile(None, StateProjection())
        record = jobs_mod.submit_project_mix_job(pid, "user-a", None, fake_db, plan)
        assert record.meta["asset_id"] == newer

    def test_master_submit_pins_asset_and_plan(
        self, store: InMemoryJobStore, fake_db: _FakeClient
    ) -> None:
        pid, aid = _seed(fake_db)
        plan = MixPlan(
            preset_id="universal",
            platform_target="club",
            output_bit_depth=24,
            parameters=MasteringParameters(target_lufs_db=-16.0),
        )
        record = jobs_mod.submit_project_master_job(pid, "user-a", aid, fake_db, plan)
        assert record.kind == "master"
        assert record.meta["asset_id"] == aid
        assert record.meta["plan"]["preset_id"] == "universal"
        assert record.meta["plan"]["platform_target"] == "club"
        # Only the fields the document actually set survive the JSON round trip.
        assert record.meta["plan"]["parameters"] == {"target_lufs_db": -16.0}

    def test_non_original_asset_is_rejected(
        self, store: InMemoryJobStore, fake_db: _FakeClient
    ) -> None:
        pid, aid = _seed(fake_db, kind="stem")
        plan = compile(None, StateProjection())
        with pytest.raises(ValueError):
            jobs_mod.submit_project_mix_job(pid, "user-a", aid, fake_db, plan)

    def test_missing_original_raises_value_error(
        self, store: InMemoryJobStore, fake_db: _FakeClient
    ) -> None:
        pid, _ = _seed(fake_db)
        fake_db.tables["audio_assets"].clear()
        plan = compile(None, StateProjection())
        with pytest.raises(ValueError):
            jobs_mod.submit_project_mix_job(pid, "user-a", None, fake_db, plan)


# ── Mix worker mechanics ────────────────────────────────────────────────────


class TestMixWorker:
    def test_mix_completes_and_registers_the_master(
        self, store: InMemoryJobStore, fake_db: _FakeClient, dsp_mix: dict[str, Any]
    ) -> None:
        pid, aid = _seed(fake_db)
        plan = compile(None, StateProjection())
        record = jobs_mod.submit_project_mix_job(pid, "user-a", aid, fake_db, plan)
        jobs_mod.run_project_mix_job(record.job_id)

        done = store.get(record.job_id)
        assert done.status == JobStatus.COMPLETED
        assert done.result["asset_id"]
        assert done.result["r2_key"] == f"projects/{pid}/masters/{record.job_id}.wav"
        assert dsp_mix["uploads"] == [done.result["r2_key"]]
        masters = [a for a in fake_db.tables["audio_assets"] if a["kind"] == "master"]
        assert len(masters) == 1
        assert masters[0]["r2_key"] == done.result["r2_key"]
        assert masters[0]["user_id"] == "user-a"
        assert masters[0]["sample_rate"] == 44100
        # No extra originals or stems were created.
        assert len(fake_db.tables["audio_assets"]) == 2

    def test_mix_honors_disabled_dimensions_and_trims(
        self, store: InMemoryJobStore, fake_db: _FakeClient, dsp_mix: dict[str, Any]
    ) -> None:
        pid, aid = _seed(fake_db)
        plan = MixPlan(
            dimension_enabled=False,
            auto_balance=True,
            stem_trims={"drums_db": -1.0},
        )
        record = jobs_mod.submit_project_mix_job(pid, "user-a", aid, fake_db, plan)
        jobs_mod.run_project_mix_job(record.job_id)

        assert store.get(record.job_id).status == JobStatus.COMPLETED
        kwargs = dsp_mix["mix_kwargs"][0]
        assert kwargs["dimension_profiles"] == {}  # neutral bypass, not None
        assert kwargs["auto_balance"] is True
        assert kwargs["stem_trims"] == {"drums_db": -1.0}

    def test_mix_forwards_character_to_build_mix(
        self, store: InMemoryJobStore, fake_db: _FakeClient, dsp_mix: dict[str, Any]
    ) -> None:
        pid, aid = _seed(fake_db)
        plan = MixPlan(character="commercial_alt_pop")
        record = jobs_mod.submit_project_mix_job(pid, "user-a", aid, fake_db, plan)
        jobs_mod.run_project_mix_job(record.job_id)

        assert store.get(record.job_id).status == JobStatus.COMPLETED
        kwargs = dsp_mix["mix_kwargs"][0]
        assert kwargs.get("character") == "commercial_alt_pop"

    def test_mix_forwards_no_character_by_default(
        self, store: InMemoryJobStore, fake_db: _FakeClient, dsp_mix: dict[str, Any]
    ) -> None:
        pid, aid = _seed(fake_db)
        plan = compile(None, StateProjection())
        record = jobs_mod.submit_project_mix_job(pid, "user-a", aid, fake_db, plan)
        jobs_mod.run_project_mix_job(record.job_id)

        assert store.get(record.job_id).status == JobStatus.COMPLETED
        kwargs = dsp_mix["mix_kwargs"][0]
        assert kwargs.get("character") is None

    def test_mix_failure_marks_the_job_error(
        self,
        store: InMemoryJobStore,
        fake_db: _FakeClient,
        dsp_mix: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pid, aid = _seed(fake_db)
        plan = compile(None, StateProjection())
        record = jobs_mod.submit_project_mix_job(pid, "user-a", aid, fake_db, plan)

        def _boom(*_a: Any, **_k: Any) -> dict[str, Any]:
            raise RuntimeError("Mix engine exploded")

        monkeypatch.setattr(jobs_mod, "build_mix", _boom)
        jobs_mod.run_project_mix_job(record.job_id)

        done = store.get(record.job_id)
        assert done.status == JobStatus.ERROR
        assert "Mix engine exploded" in (done.error or "")


# ── Master worker mechanics ─────────────────────────────────────────────────


class TestMasterWorker:
    def test_master_applies_preset_platform_overlay_and_bit_depth(
        self,
        store: InMemoryJobStore,
        fake_db: _FakeClient,
        dsp_master: dict[str, Any],
    ) -> None:
        pid, aid = _seed(fake_db)
        plan = MixPlan(
            preset_id="universal",
            platform_target="club",
            output_bit_depth=24,
            parameters=MasteringParameters(target_lufs_db=-16.0),
        )
        record = jobs_mod.submit_project_master_job(pid, "user-a", aid, fake_db, plan)
        jobs_mod.run_project_master_job(record.job_id)

        done = store.get(record.job_id)
        assert done.status == JobStatus.COMPLETED
        assert done.result["r2_key"] == f"projects/{pid}/masters/{record.job_id}.wav"
        params = dsp_master["params"]
        assert params is not None
        # Explicit overlay wins over the club platform target...
        assert params.target_lufs_db == -16.0
        # ...while the platform ceiling survives (club: -0.3 dBTP)...
        assert params.limiter_ceiling_db == -0.3
        # ...and the top-level bit depth is applied last.
        assert params.output_bit_depth == 24
        masters = [a for a in fake_db.tables["audio_assets"] if a["kind"] == "master"]
        assert len(masters) == 1
        assert masters[0]["format"] == "wav"

    def test_master_neutral_plan_uses_defaults(
        self,
        store: InMemoryJobStore,
        fake_db: _FakeClient,
        dsp_master: dict[str, Any],
    ) -> None:
        pid, aid = _seed(fake_db)
        plan = compile(None, StateProjection())  # no preset, no intent
        record = jobs_mod.submit_project_master_job(pid, "user-a", aid, fake_db, plan)
        jobs_mod.run_project_master_job(record.job_id)

        assert store.get(record.job_id).status == JobStatus.COMPLETED
        params = dsp_master["params"]
        assert params is not None
        # Spot-check the neutral mastering defaults: transparent base, no
        # explicit loudness target (the engine derives it from the ceiling).
        assert params.target_lufs_db is None
        assert params.limiter_ceiling_db == -1.0
        assert params.output_bit_depth == 24

    def test_master_failure_marks_the_job_error(
        self,
        store: InMemoryJobStore,
        fake_db: _FakeClient,
        dsp_master: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pid, aid = _seed(fake_db)
        plan = compile(None, StateProjection())
        record = jobs_mod.submit_project_master_job(pid, "user-a", aid, fake_db, plan)

        def _boom(*_a: Any, **_k: Any) -> dict[str, Any]:
            raise RuntimeError("Mastering chain exploded")

        monkeypatch.setattr(jobs_mod, "process_audio", _boom)
        jobs_mod.run_project_master_job(record.job_id)

        done = store.get(record.job_id)
        assert done.status == JobStatus.ERROR
        assert "Mastering chain exploded" in (done.error or "")


# ── HTTP endpoints ──────────────────────────────────────────────────────────


class TestProjectJobEndpoints:
    def test_mix_404_when_project_not_owned(
        self, store: InMemoryJobStore, fake_db: _FakeClient
    ) -> None:
        pid, _ = _seed(fake_db, user_id="user-a")
        resp = client.post(
            f"/api/projects/{pid}/jobs/mix", json={}, headers=_auth("tok_b")
        )
        assert resp.status_code == 404

    def test_mix_202_with_a_real_job_id(
        self,
        store: InMemoryJobStore,
        fake_db: _FakeClient,
        dsp_mix: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pid, aid = _seed(fake_db)
        # TestClient runs BackgroundTasks synchronously; make them no-ops so
        # this test only covers the submit contract.
        monkeypatch.setattr(projects_mod, "run_project_mix_job", lambda *_a, **_k: None)
        resp = client.post(
            f"/api/projects/{pid}/jobs/mix",
            json={"asset_id": aid},
            headers=_auth(),
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["project_id"] == pid
        assert body["asset_id"] == aid
        assert body["status"] == "processing"
        assert body["poll_url"] == f"/api/jobs/mix/{body['job_id']}"
        # The job is really registered and answerable by the shared poll.
        record = store.get(body["job_id"])
        assert record is not None and record.kind == "mix"

    def test_master_202_with_a_real_job_id(
        self,
        store: InMemoryJobStore,
        fake_db: _FakeClient,
        dsp_master: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        pid, aid = _seed(fake_db)
        monkeypatch.setattr(
            projects_mod, "run_project_master_job", lambda *_a, **_k: None
        )
        resp = client.post(
            f"/api/projects/{pid}/jobs/master",
            json={"asset_id": aid},
            headers=_auth(),
        )
        assert resp.status_code == 202, resp.text
        body = resp.json()
        assert body["asset_id"] == aid
        assert body["poll_url"] == f"/api/jobs/master/{body['job_id']}"
        record = store.get(body["job_id"])
        assert record is not None and record.kind == "master"

    def test_master_422_when_there_is_no_original(
        self, store: InMemoryJobStore, fake_db: _FakeClient
    ) -> None:
        pid, _ = _seed(fake_db)
        fake_db.tables["audio_assets"].clear()
        resp = client.post(
            f"/api/projects/{pid}/jobs/master", json={}, headers=_auth()
        )
        assert resp.status_code == 422, resp.text

    def test_missing_token_is_401(
        self, store: InMemoryJobStore, fake_db: _FakeClient
    ) -> None:
        resp = client.post(f"/api/projects/{uuid.uuid4()}/jobs/mix", json={})
        assert resp.status_code == 401


# ── Shared poll endpoints (reused, not duplicated) ──────────────────────────


class TestProjectPoll:
    def test_mix_poll_returns_completed(
        self, store: InMemoryJobStore, fake_db: _FakeClient, dsp_mix: dict[str, Any]
    ) -> None:
        pid, aid = _seed(fake_db)
        plan = compile(None, StateProjection())
        record = jobs_mod.submit_project_mix_job(pid, "user-a", aid, fake_db, plan)
        jobs_mod.run_project_mix_job(record.job_id)

        resp = client.get(f"/api/jobs/mix/{record.job_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["result"]["asset_id"]
        assert body["result"]["download_url"].startswith("https://r2.example/")

    def test_master_poll_returns_completed(
        self,
        store: InMemoryJobStore,
        fake_db: _FakeClient,
        dsp_master: dict[str, Any],
    ) -> None:
        pid, aid = _seed(fake_db)
        plan = compile(None, StateProjection())
        record = jobs_mod.submit_project_master_job(pid, "user-a", aid, fake_db, plan)
        jobs_mod.run_project_master_job(record.job_id)

        resp = client.get(f"/api/jobs/master/{record.job_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        # The master poll reuses the existing worker status contract: the
        # stable R2 key is exposed, no fresh presigned URL is minted here.
        assert body["result"]["r2_key"] == f"projects/{pid}/masters/{record.job_id}.wav"
        assert "download_url" not in body["result"]