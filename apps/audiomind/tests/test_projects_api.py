"""Multi-tenant project document API: auth, CRUD, presigned upload, mix state.

The property under test is ownership. Every endpoint resolves the caller from
a Supabase token and only ever touches that user's rows. The suite therefore
drives the API through a FAKE Supabase client that both validates tokens
(``auth.get_user``) and stores rows, so "user B cannot read user A's project"
is exercised end to end rather than asserted against a stub that always agrees.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import audiomind.api.auth as auth_mod
import audiomind.api.projects as projects_mod
from audiomind.config import settings
from audiomind.main import app
from audiomind.services import storage as storage_mod

client = TestClient(app)


# ── Fake Supabase client ───────────────────────────────────────────────────


class _FakeAuth:
    """Token → user resolver mirroring ``client.auth.get_user(token)``."""

    def __init__(self, users: dict[str, str]) -> None:
        self._users = users

    def get_user(self, token: str) -> Any:
        user_id = self._users.get(token)
        if user_id is None:
            raise RuntimeError("invalid JWT")
        return SimpleNamespace(user=SimpleNamespace(id=user_id))


class _FakeTable:
    """The slice of the PostgREST fluent builder the router actually uses."""

    def __init__(self, store: _FakeClient, name: str) -> None:
        self._store = store
        self._name = name
        self._op: str | None = None
        self._payload: dict[str, Any] | None = None
        self._patch: dict[str, Any] | None = None
        self._filters: list[tuple[str, Any]] = []
        self._limit: int | None = None
        self._on_conflict: str | None = None

    # builder
    def insert(self, payload: dict[str, Any]) -> _FakeTable:
        self._op, self._payload = "insert", payload
        return self

    def select(self, _cols: str = "*") -> _FakeTable:
        self._op = "select"
        return self

    def update(self, patch: dict[str, Any]) -> _FakeTable:
        self._op, self._patch = "update", patch
        return self

    def upsert(
        self, payload: dict[str, Any], on_conflict: str | None = None
    ) -> _FakeTable:
        self._op, self._payload, self._on_conflict = "upsert", payload, on_conflict
        return self

    def eq(self, column: str, value: Any) -> _FakeTable:
        self._filters.append((column, value))
        return self

    def limit(self, count: int) -> _FakeTable:
        self._limit = count
        return self

    # execution
    def execute(self) -> SimpleNamespace:
        rows = self._store.tables[self._name]
        if self._op == "insert":
            row = dict(self._payload or {})
            row.setdefault("id", str(uuid.uuid4()))
            row.setdefault("created_at", "2026-10-08T00:00:00+00:00")
            row.setdefault("updated_at", row["created_at"])
            rows.append(row)
            return SimpleNamespace(data=[dict(row)])

        if self._op == "select":
            matched = self._match(rows)
            if self._limit is not None:
                matched = matched[: self._limit]
            return SimpleNamespace(data=[dict(r) for r in matched])

        if self._op == "update":
            matched = self._match(rows)
            for row in matched:
                row.update(self._patch or {})
            return SimpleNamespace(data=[dict(r) for r in matched])

        if self._op == "upsert":
            key = self._on_conflict
            payload = dict(self._payload or {})
            if key and payload.get(key) is not None:
                for row in rows:
                    if row.get(key) == payload[key]:
                        row.update(payload)
                        return SimpleNamespace(data=[dict(row)])
            payload.setdefault("id", str(uuid.uuid4()))
            rows.append(payload)
            return SimpleNamespace(data=[dict(payload)])

        return SimpleNamespace(data=[])

    def _match(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            row
            for row in rows
            if all(row.get(col) == val for col, val in self._filters)
        ]


class _FakeClient:
    """In-memory Supabase stand-in: token auth + three project tables."""

    def __init__(self, users: dict[str, str] | None = None) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "projects": [],
            "audio_assets": [],
            "project_states": [],
        }
        self.auth = _FakeAuth(users or {})

    def table(self, name: str) -> _FakeTable:
        return _FakeTable(self, name)


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    """Install a fake Supabase client with two known users.

    ``tok_a`` → user-a, ``tok_b`` → user-b. Both the auth dependency and the
    CRUD endpoints read the factory through the module, so this single patch
    drives the whole request path.
    """
    fake = _FakeClient({"tok_a": "user-a", "tok_b": "user-b"})
    monkeypatch.setattr(
        projects_mod.supabase_client, "get_supabase_client", lambda *_a, **_k: fake
    )
    monkeypatch.setattr(settings, "license_key", "")
    return fake


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Auth unit ──────────────────────────────────────────────────────────────


class TestUserContext:
    def test_missing_header_is_401(self) -> None:
        with pytest.raises(HTTPException) as exc:
            auth_mod.get_user_context(authorization=None)
        assert exc.value.status_code == 401

    def test_malformed_header_is_401(self) -> None:
        with pytest.raises(HTTPException) as exc:
            auth_mod.get_user_context(authorization="Token abc")
        assert exc.value.status_code == 401

    def test_sealed_client_falls_back_to_dev_identity(self) -> None:
        """No Supabase (dev/test) → the fixed dev id, never a 500."""
        ctx = auth_mod.get_user_context(authorization="Bearer whatever")
        assert ctx.user_id == auth_mod.DEV_USER_ID
        assert ctx.token is None

    def test_valid_token_resolves_the_supabase_user(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _FakeClient({"tok_a": "user-a"})
        monkeypatch.setattr(
            auth_mod.supabase_client, "get_supabase_client", lambda *_a, **_k: fake
        )
        ctx = auth_mod.get_user_context(authorization="Bearer tok_a")
        assert ctx.user_id == "user-a"
        assert ctx.token == "tok_a"

    def test_unresolvable_token_is_401(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _FakeClient({})  # no token maps to a user
        monkeypatch.setattr(
            auth_mod.supabase_client, "get_supabase_client", lambda *_a, **_k: fake
        )
        with pytest.raises(HTTPException) as exc:
            auth_mod.get_user_context(authorization="Bearer bogus")
        assert exc.value.status_code == 401


# ── Projects ───────────────────────────────────────────────────────────────


class TestProjects:
    def test_create_returns_201_and_owns_the_row(self, fake_db: _FakeClient) -> None:
        resp = client.post(
            "/api/projects",
            json={"name": "Mi tema", "bpm": 120},
            headers=_auth("tok_a"),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["name"] == "Mi tema"
        assert body["bpm"] == 120
        assert body["user_id"] == "user-a"
        # The stored row is owned by the token's user.
        assert fake_db.tables["projects"][0]["user_id"] == "user-a"

    def test_list_is_scoped_to_the_caller(self, fake_db: _FakeClient) -> None:
        client.post("/api/projects", json={"name": "A1"}, headers=_auth("tok_a"))
        client.post("/api/projects", json={"name": "B1"}, headers=_auth("tok_b"))

        a_list = client.get("/api/projects", headers=_auth("tok_a")).json()
        b_list = client.get("/api/projects", headers=_auth("tok_b")).json()
        assert [p["name"] for p in a_list] == ["A1"]
        assert [p["name"] for p in b_list] == ["B1"]

    def test_get_theirs_works_theirs_is_404(self, fake_db: _FakeClient) -> None:
        created = client.post(
            "/api/projects", json={"name": "Solo A"}, headers=_auth("tok_a")
        ).json()
        url = f"/api/projects/{created['id']}"

        theirs = client.get(url, headers=_auth("tok_a"))
        assert theirs.status_code == 200
        # User B must not even learn the project exists.
        assert client.get(url, headers=_auth("tok_b")).status_code == 404

    def test_missing_token_is_401(self, fake_db: _FakeClient) -> None:
        assert client.get("/api/projects").status_code == 401


# ── Presigned direct-to-R2 upload ──────────────────────────────────────────


class TestPresignAssets:
    @pytest.fixture(autouse=True)
    def _stub_presign(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            storage_mod,
            "presigned_put_url",
            lambda key, **kw: f"https://r2.example/{key}?sig=put",
        )

    def _project(self, token: str = "tok_a") -> str:
        return client.post(
            "/api/projects", json={"name": "P"}, headers=_auth(token)
        ).json()["id"]

    def test_presign_registers_asset_and_returns_a_put_url(
        self, fake_db: _FakeClient
    ) -> None:
        pid = self._project()
        resp = client.post(
            f"/api/projects/{pid}/assets/presign",
            json={
                "kind": "original",
                "original_filename": "toma.wav",
                "content_type": "audio/wav",
            },
            headers=_auth("tok_a"),
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["put_url"].startswith("https://r2.example/projects/")
        assert body["r2_key"].startswith(f"projects/{pid}/original/")
        assert body["r2_key"].endswith(".wav")
        # The row is already owned and parked in the store.
        stored = fake_db.tables["audio_assets"][0]
        assert stored["user_id"] == "user-a"
        assert stored["r2_key"] == body["r2_key"]

    def test_presign_on_a_foreign_project_is_404(self, fake_db: _FakeClient) -> None:
        pid = self._project("tok_a")
        resp = client.post(
            f"/api/projects/{pid}/assets/presign",
            json={"kind": "original", "content_type": "audio/wav"},
            headers=_auth("tok_b"),
        )
        assert resp.status_code == 404

    def test_stem_without_name_is_422(self, fake_db: _FakeClient) -> None:
        pid = self._project()
        resp = client.post(
            f"/api/projects/{pid}/assets/presign",
            json={"kind": "stem", "content_type": "audio/wav"},
            headers=_auth("tok_a"),
        )
        assert resp.status_code == 422

    def test_complete_records_introspection(self, fake_db: _FakeClient) -> None:
        pid = self._project()
        asset = client.post(
            f"/api/projects/{pid}/assets/presign",
            json={"kind": "original", "content_type": "audio/wav"},
            headers=_auth("tok_a"),
        ).json()

        resp = client.patch(
            f"/api/projects/{pid}/assets/{asset['asset_id']}",
            json={
                "duration_seconds": 12.5,
                "sample_rate": 44100,
                "channels": 2,
                "format": "wav",
                "size_bytes": 1024,
                "media_hash": "abc123",
            },
            headers=_auth("tok_a"),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["duration_seconds"] == 12.5
        assert body["media_hash"] == "abc123"

    def test_complete_on_foreign_asset_is_404(self, fake_db: _FakeClient) -> None:
        pid = self._project("tok_a")
        asset = client.post(
            f"/api/projects/{pid}/assets/presign",
            json={"kind": "original", "content_type": "audio/wav"},
            headers=_auth("tok_a"),
        ).json()
        resp = client.patch(
            f"/api/projects/{pid}/assets/{asset['asset_id']}",
            json={"duration_seconds": 1.0},
            headers=_auth("tok_b"),
        )
        assert resp.status_code == 404

    def test_list_assets_is_scoped(self, fake_db: _FakeClient) -> None:
        pid = self._project("tok_a")
        client.post(
            f"/api/projects/{pid}/assets/presign",
            json={"kind": "original", "content_type": "audio/wav"},
            headers=_auth("tok_a"),
        )
        mine = client.get(f"/api/projects/{pid}/assets", headers=_auth("tok_a"))
        theirs = client.get(f"/api/projects/{pid}/assets", headers=_auth("tok_b"))
        assert mine.status_code == 200 and len(mine.json()) == 1
        assert theirs.status_code == 404


# ── Mix state ──────────────────────────────────────────────────────────────


class TestMixState:
    def _project(self, token: str = "tok_a") -> str:
        return client.post(
            "/api/projects", json={"name": "P"}, headers=_auth(token)
        ).json()["id"]

    def test_uninitialised_state_is_empty(self, fake_db: _FakeClient) -> None:
        pid = self._project()
        resp = client.get(f"/api/projects/{pid}/state", headers=_auth("tok_a"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["state"] == {}
        assert body["undo_stack"] == []

    def test_upsert_then_read_round_trips(self, fake_db: _FakeClient) -> None:
        pid = self._project()
        state = {"faders": {"drums": -3.0, "vocals": 1.5}, "master": -1.0}
        up = client.patch(
            f"/api/projects/{pid}/state",
            json={"state": state, "undo_stack": [{"faders": {}}]},
            headers=_auth("tok_a"),
        )
        assert up.status_code == 200, up.text

        got = client.get(f"/api/projects/{pid}/state", headers=_auth("tok_a")).json()
        assert got["state"] == state
        assert len(got["undo_stack"]) == 1

    def test_upsert_replaces_not_appends(self, fake_db: _FakeClient) -> None:
        """project_id is the PK: a second autosave must not pile up a row."""
        pid = self._project()
        client.patch(
            f"/api/projects/{pid}/state",
            json={"state": {"master": -6.0}},
            headers=_auth("tok_a"),
        )
        client.patch(
            f"/api/projects/{pid}/state",
            json={"state": {"master": -2.0}},
            headers=_auth("tok_a"),
        )
        assert len(fake_db.tables["project_states"]) == 1
        got = client.get(f"/api/projects/{pid}/state", headers=_auth("tok_a")).json()
        assert got["state"]["master"] == -2.0

    def test_state_is_isolated_between_users(self, fake_db: _FakeClient) -> None:
        pid_a = self._project("tok_a")
        pid_b = self._project("tok_b")
        client.patch(
            f"/api/projects/{pid_a}/state",
            json={"state": {"master": -3.0}},
            headers=_auth("tok_a"),
        )
        # B sees their own empty state, never A's.
        got_b = client.get(
            f"/api/projects/{pid_b}/state", headers=_auth("tok_b")
        ).json()
        assert got_b["state"] == {}

    def test_foreign_state_upsert_is_404(self, fake_db: _FakeClient) -> None:
        pid = self._project("tok_a")
        resp = client.patch(
            f"/api/projects/{pid}/state",
            json={"state": {}},
            headers=_auth("tok_b"),
        )
        assert resp.status_code == 404


# ── Storage unit ───────────────────────────────────────────────────────────


class TestPresignedPutUrl:
    def test_put_url_is_signed_for_put_object(self, monkeypatch) -> None:
        calls: dict[str, Any] = {}

        def _fake_generate(operation: str, **params: Any) -> str:
            calls["operation"] = operation
            calls.update(params)
            return "https://r2.example/put-url"

        monkeypatch.setattr(
            storage_mod,
            "get_s3_client",
            lambda: SimpleNamespace(generate_presigned_url=_fake_generate),
        )
        monkeypatch.setattr(settings, "r2_bucket", "wave", raising=False)

        url = storage_mod.presigned_put_url(
            "projects/p1/original/a.wav", content_type="audio/wav", expires_in=60
        )
        assert url == "https://r2.example/put-url"
        assert calls["operation"] == "put_object"
        assert calls["Params"]["Key"] == "projects/p1/original/a.wav"
        assert calls["Params"]["ContentType"] == "audio/wav"
        assert calls["ExpiresIn"] == 60
