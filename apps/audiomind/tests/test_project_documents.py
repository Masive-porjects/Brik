"""CRUD for the V1 project document: bootstrap, OCC, schema, ownership.

Two contracts are under test:

1. **The document schema** (``docs/reference/specs/project_document_v1_spec.md``
   §3): exactly the 4 Demucs stems, declared fields only, and a
   ``master_intent`` that mirrors the 7-value ``MasterJobPayload`` set.
   Rejections are asserted by status code and by the offending ``loc`` — never
   by pydantic's English message text, which is an implementation detail.
2. **Optimistic concurrency + ownership**: one row per project, ``version``
   bumped by the server, a stale ``expected_version`` losing with 409, and
   user B answered 404 for user A's project.

The suite drives the API through a FAKE Supabase client (token auth + rows) so
both properties are exercised end to end. ``project_states`` is deliberately
NOT one of the fake's tables: invariant I1 says the frontend store is that
table's single writer, so any backend attempt to touch it would raise a
``KeyError`` here instead of passing silently.

The SQL migration is not exercised — no Postgres in the suite; its correctness
is reviewed against the WU1 template instead.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import audiomind.api.projects as projects_mod
from audiomind.config import settings
from audiomind.main import app
from audiomind.models.project_document import default_document

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

    def delete(self) -> _FakeTable:
        self._op = "delete"
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

        if self._op == "delete":
            matched = self._match(rows)
            for row in matched:
                rows.remove(row)
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
    """In-memory Supabase stand-in: token auth + the two document tables."""

    def __init__(self, users: dict[str, str] | None = None) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "projects": [],
            "project_documents": [],
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


def _project(token: str = "tok_a") -> str:
    """Create a project owned by ``token``'s user and return its id."""
    resp = client.post("/api/projects", json={"name": "P"}, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


def _doc(**overrides: Any) -> dict[str, Any]:
    """The bootstrap document as a plain dict, with top-level overrides.

    Built fresh on every call so a test may mutate the result freely. Nested
    structures (stems, proposals) are passed in explicitly by the caller.
    """
    document = default_document().model_dump()
    document.update(overrides)
    return document


def _stems() -> dict[str, Any]:
    """The bootstrap stems dict, mutable and private to the caller."""
    return default_document().model_dump()["structure"]["stems"]


def _put(
    project_id: str,
    document: dict[str, Any],
    expected_version: int = 0,
    token: str = "tok_a",
) -> Any:
    """PUT a document with an explicit ``expected_version``."""
    return client.put(
        f"/api/projects/{project_id}/document",
        json={"document": document, "expected_version": expected_version},
        headers=_auth(token),
    )


def _loc(resp: Any) -> list[Any]:
    """First error's ``loc`` from a 422 body — never its English message."""
    return list(resp.json()["detail"][0]["loc"])


# ── Bootstrap (no row yet) ─────────────────────────────────────────────────


class TestDocumentBootstrap:
    def test_get_without_a_row_bootstraps_version_zero(
        self, fake_db: _FakeClient
    ) -> None:
        pid = _project()
        resp = client.get(f"/api/projects/{pid}/document", headers=_auth("tok_a"))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["project_id"] == pid
        assert body["version"] == 0
        assert body["updated_at"] is None

        document = body["document"]
        assert document["schema_version"] == 1
        assert document["updated_by"] == "user"
        stems = document["structure"]["stems"]
        assert set(stems) == {"drums", "bass", "other", "vocals"}
        orders = {name: node["order"] for name, node in stems.items()}
        assert orders == {"drums": 0, "bass": 1, "other": 2, "vocals": 3}
        # The bootstrap is an answer, not a write.
        assert fake_db.tables["project_documents"] == []


# ── Write + round trip ─────────────────────────────────────────────────────


class TestDocumentWrite:
    def test_put_creates_version_one_and_owns_the_row(
        self, fake_db: _FakeClient
    ) -> None:
        pid = _project()
        resp = _put(pid, _doc())
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["version"] == 1
        # Server-stamped, never the client's value.
        assert body["document"]["updated_at"] is not None

        rows = fake_db.tables["project_documents"]
        assert len(rows) == 1
        assert rows[0]["user_id"] == "user-a"
        assert rows[0]["project_id"] == pid
        assert rows[0]["version"] == 1
        assert rows[0]["document_json"]["schema_version"] == 1

    def test_get_after_put_round_trips_the_stored_document(
        self, fake_db: _FakeClient
    ) -> None:
        pid = _project()
        stems = _stems()
        stems["vocals"]["display_name"] = "Lead Vox"
        created = _put(pid, _doc(structure={"stems": stems}))
        assert created.status_code == 200, created.text

        got = client.get(
            f"/api/projects/{pid}/document", headers=_auth("tok_a")
        ).json()
        assert got["version"] == 1
        got_stems = got["document"]["structure"]["stems"]
        assert got_stems["vocals"]["display_name"] == "Lead Vox"
        assert {n: s["order"] for n, s in got_stems.items()} == {
            "drums": 0,
            "bass": 1,
            "other": 2,
            "vocals": 3,
        }


# ── Optimistic concurrency ─────────────────────────────────────────────────


class TestOptimisticConcurrency:
    def test_nonzero_expected_version_on_a_fresh_project_is_409(
        self, fake_db: _FakeClient
    ) -> None:
        pid = _project()
        resp = _put(pid, _doc(), expected_version=5)
        assert resp.status_code == 409
        assert fake_db.tables["project_documents"] == []

    def test_reusing_zero_after_v1_exists_is_409(
        self, fake_db: _FakeClient
    ) -> None:
        pid = _project()
        assert _put(pid, _doc()).status_code == 200

        resp = _put(pid, _doc(), expected_version=0)
        assert resp.status_code == 409
        # The conflict did not clobber the stored document.
        rows = fake_db.tables["project_documents"]
        assert len(rows) == 1
        assert rows[0]["version"] == 1

    def test_matching_expected_version_bumps_to_two(
        self, fake_db: _FakeClient
    ) -> None:
        pid = _project()
        assert _put(pid, _doc(), expected_version=0).status_code == 200
        resp = _put(pid, _doc(), expected_version=1)
        assert resp.status_code == 200, resp.text
        assert resp.json()["version"] == 2
        assert fake_db.tables["project_documents"][0]["version"] == 2


# ── Schema rejections ──────────────────────────────────────────────────────


class TestSchemaRejections:
    def test_three_of_four_stems_is_422(self, fake_db: _FakeClient) -> None:
        pid = _project()
        stems = _stems()
        del stems["vocals"]
        resp = _put(pid, _doc(structure={"stems": stems}))
        assert resp.status_code == 422
        assert "stems" in _loc(resp)
        assert fake_db.tables["project_documents"] == []

    def test_extra_stem_key_is_422(self, fake_db: _FakeClient) -> None:
        pid = _project()
        stems = _stems()
        stems["snare"] = dict(stems["drums"])
        resp = _put(pid, _doc(structure={"stems": stems}))
        assert resp.status_code == 422
        assert "stems" in _loc(resp)

    def test_unknown_top_level_key_is_422(self, fake_db: _FakeClient) -> None:
        pid = _project()
        document = _doc()
        document["faders"] = {"vocals_db": 2.0}
        resp = _put(pid, document)
        assert resp.status_code == 422
        assert "document" in _loc(resp)

    def test_invalid_preset_id_is_422(self, fake_db: _FakeClient) -> None:
        pid = _project()
        resp = _put(pid, _doc(master_intent={"preset_id": "hyperdrive"}))
        assert resp.status_code == 422
        assert "preset_id" in _loc(resp)

    def test_output_bit_depth_out_of_range_is_422(self, fake_db: _FakeClient) -> None:
        pid = _project()
        resp = _put(pid, _doc(master_intent={"output_bit_depth": 8}))
        assert resp.status_code == 422
        assert "output_bit_depth" in _loc(resp)

    def test_missing_schema_version_is_422(self, fake_db: _FakeClient) -> None:
        pid = _project()
        document = _doc()
        del document["schema_version"]
        resp = _put(pid, document)
        assert resp.status_code == 422
        assert "schema_version" in _loc(resp)

    def test_schema_version_two_is_422(self, fake_db: _FakeClient) -> None:
        pid = _project()
        resp = _put(pid, _doc(schema_version=2))
        assert resp.status_code == 422
        assert "schema_version" in _loc(resp)


# ── master_intent projection (7-value payload set + parameter overlay) ─────


class TestMasterIntent:
    def test_platform_target_club_is_accepted_and_deezer_is_not(
        self, fake_db: _FakeClient
    ) -> None:
        pid = _project()
        ok = _put(pid, _doc(master_intent={"platform_target": "club"}))
        assert ok.status_code == 200, ok.text
        assert ok.json()["document"]["master_intent"]["platform_target"] == "club"

        bad = _put(pid, _doc(master_intent={"platform_target": "deezer"}))
        assert bad.status_code == 422
        assert "platform_target" in _loc(bad)

    def test_parameter_overlay_validates_known_knobs_and_ranges(
        self, fake_db: _FakeClient
    ) -> None:
        pid = _project()
        good = _put(
            pid, _doc(master_intent={"parameters": {"limiter_ceiling_db": -1.5}})
        )
        assert good.status_code == 200, good.text

        unknown = _put(
            pid, _doc(master_intent={"parameters": {"no_such_knob": 1}})
        )
        assert unknown.status_code == 422
        assert "parameters" in _loc(unknown)

        out_of_range = _put(
            pid, _doc(master_intent={"parameters": {"limiter_ceiling_db": -99}})
        )
        assert out_of_range.status_code == 422
        assert "parameters" in _loc(out_of_range)


# ── Proposals (intent only, never live state) ──────────────────────────────


class TestProposals:
    def test_pending_fader_proposal_stores_and_reads_back(
        self, fake_db: _FakeClient
    ) -> None:
        pid = _project()
        proposal = {
            "id": str(uuid.uuid4()),
            "kind": "fader",
            "payload": {"vocals_db": 2.0},
            "status": "pending",
            "created_at": "2026-10-08T12:00:00+00:00",
            "rationale": "The vocal sits under the band.",
        }
        resp = _put(pid, _doc(mix_intent={"proposals": [proposal]}))
        assert resp.status_code == 200, resp.text

        got = client.get(
            f"/api/projects/{pid}/document", headers=_auth("tok_a")
        ).json()
        stored = got["document"]["mix_intent"]["proposals"][0]
        assert stored["id"] == proposal["id"]
        assert stored["kind"] == "fader"
        assert stored["status"] == "pending"
        assert stored["payload"] == {"vocals_db": 2.0}
        assert stored["rationale"] == "The vocal sits under the band."
        # ``project_states`` is not even a table of this fake, so reaching it
        # would have raised: the proposal stayed intent (invariant I1).

    def test_proposal_id_that_is_not_a_uuid_is_422(
        self, fake_db: _FakeClient
    ) -> None:
        pid = _project()
        proposal = {
            "id": "not-a-uuid",
            "kind": "fader",
            "payload": {"vocals_db": 2.0},
            "status": "pending",
            "created_at": "2026-10-08T12:00:00+00:00",
        }
        resp = _put(pid, _doc(mix_intent={"proposals": [proposal]}))
        assert resp.status_code == 422
        assert "proposals" in _loc(resp)
        assert fake_db.tables["project_documents"] == []


# ── Ownership + auth ───────────────────────────────────────────────────────


class TestOwnership:
    def test_foreign_project_is_404_for_get_and_put(
        self, fake_db: _FakeClient
    ) -> None:
        pid = _project("tok_a")

        got = client.get(f"/api/projects/{pid}/document", headers=_auth("tok_b"))
        assert got.status_code == 404

        put = _put(pid, _doc(), expected_version=0, token="tok_b")
        assert put.status_code == 404
        # User B did not write a shadow row for user A's project.
        assert fake_db.tables["project_documents"] == []

    def test_missing_authorization_header_is_401(self, fake_db: _FakeClient) -> None:
        pid = _project()
        assert client.get(f"/api/projects/{pid}/document").status_code == 401
        assert (
            client.put(
                f"/api/projects/{pid}/document",
                json={"document": _doc(), "expected_version": 0},
            ).status_code
            == 401
        )
        assert (
            client.delete(f"/api/projects/{pid}/document").status_code == 401
        )


# ── Delete (reset to bootstrap) ────────────────────────────────────────────


class TestDocumentDelete:
    def test_delete_resets_to_bootstrap_then_404s(self, fake_db: _FakeClient) -> None:
        pid = _project()
        assert _put(pid, _doc()).status_code == 200
        assert len(fake_db.tables["project_documents"]) == 1

        resp = client.delete(f"/api/projects/{pid}/document", headers=_auth("tok_a"))
        assert resp.status_code == 204
        assert fake_db.tables["project_documents"] == []

        got = client.get(
            f"/api/projects/{pid}/document", headers=_auth("tok_a")
        ).json()
        assert got["version"] == 0
        assert got["document"]["schema_version"] == 1

        again = client.delete(f"/api/projects/{pid}/document", headers=_auth("tok_a"))
        assert again.status_code == 404

    def test_delete_without_a_row_is_404(self, fake_db: _FakeClient) -> None:
        pid = _project()
        resp = client.delete(f"/api/projects/{pid}/document", headers=_auth("tok_a"))
        assert resp.status_code == 404
