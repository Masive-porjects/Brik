"""Invariants over the session endpoints registered on the real FastAPI app.

``POST /api/session/new`` and ``GET /api/session/{session_id}`` were defined in
both ``api/upload.py`` and ``api/mastering.py``. Starlette matches routes in
registration order, so only the first one ever served traffic, while the
duplicate made FastAPI emit a ``Duplicate Operation ID`` warning every time the
OpenAPI schema was built.

The warning is the canonical, public signal for this defect: it is emitted by
``fastapi.openapi.utils.get_openapi_path`` once per registered handler that
reuses an operation ID, so it catches a duplicate no matter which router it is
added to. FastAPI 0.143 keeps included routers as lazy ``_IncludedRouter``
objects inside ``app.routes``, so walking the route table is not viable through
public API, and the generated schema deduplicates the path entry before the
duplicate becomes visible.
"""

import sys

sys.path.insert(0, "src")

import warnings

import pytest
from fastapi.testclient import TestClient

from audiomind.api.upload import sessions
from audiomind.config import settings
from audiomind.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch):
    sessions.clear()
    # Development mode so require_license allows every request.
    monkeypatch.setattr(settings, "license_key", "")
    yield
    sessions.clear()


def test_openapi_has_no_duplicate_operation_id_warning() -> None:
    app.openapi_schema = None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app.openapi()
    duplicates = [str(w.message) for w in caught if "Duplicate Operation ID" in str(w.message)]
    assert duplicates == []


def test_session_roundtrip_contract_is_unchanged() -> None:
    created = client.post("/api/session/new", json={"name": "routes"})
    assert created.status_code == 200
    session_id = created.json()["session_id"]
    # The serving handler persists the session in the shared store.
    assert session_id in sessions

    fetched = client.get(f"/api/session/{session_id}")
    assert fetched.status_code == 200
    assert fetched.json()["session_id"] == session_id

    missing = client.get("/api/session/does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Session not found"
