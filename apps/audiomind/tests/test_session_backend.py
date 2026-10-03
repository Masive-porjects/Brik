"""Durable session backend, and the guards that keep it from eating sessions.

The regression this pins: sessions lived in ``uploads/sessions.json`` on
Railway's ephemeral disk, so a redeploy lost every session even though the
audio was already durable in R2.

What is asserted here, in order of how much damage it prevents:

  1. "empty" and "unreadable" are DIFFERENT answers. ``save_sessions`` deletes
     the ids missing from its in-memory dict, so a backend that reports a
     network timeout as an empty store would make the next save delete EVERY
     session row. ``test_incomplete_load_defers_pruning`` is that catastrophe.
  2. A failed write is retried instead of being written off as done.
  3. Round-trip fidelity through ``model_dump(mode="json")``, including the
     nested models and enums that the ``jsonb`` payload must not flatten.
  4. Selection: ``auto`` falls back to the file mirror, and an invalid setting
     fails loudly rather than silently degrading.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

from audiomind.config import settings
from audiomind.models.audio import ProcessingStatus, SessionData
from audiomind.services import session_backend as sb
from audiomind.services.session_backend import (
    FileSessionBackend,
    SupabaseSessionBackend,
    get_session_backend,
    reset_session_backend,
)

# ─────────────────────────────── fakes ─────────────────────────────────────

#: Distinguishes "the caller set this to None" from "the caller set nothing".
#: Both mean different things here: ``None`` is the backend's way of saying
#: "I could not read", and it must be expressible.
_UNSET = object()


class RecordingBackend:
    """In-memory stand-in that records calls and can fail on demand."""

    def __init__(self, rows: dict[str, SessionData] | None = None) -> None:
        self.rows: dict[str, SessionData] = dict(rows or {})
        self.load_result: Any = _UNSET
        self.upserts: list[dict[str, Any]] = []
        self.deletes: list[list[str]] = []
        self.fail_upsert = False
        self.fail_delete = False

    def load_all(self) -> dict[str, SessionData] | None:
        if self.load_result is not _UNSET:
            return cast("dict[str, SessionData] | None", self.load_result)
        return dict(self.rows)

    def upsert_many(self, rows: dict[str, dict[str, Any]]) -> bool:
        self.upserts.append(dict(rows))
        if self.fail_upsert:
            return False
        for sid, data in rows.items():
            self.rows[sid] = SessionData.model_validate(data)
        return True

    def delete_many(self, session_ids: Any) -> bool:
        ids = list(session_ids)
        self.deletes.append(ids)
        if self.fail_delete:
            return False
        for sid in ids:
            self.rows.pop(sid, None)
        return True


class _Result:
    def __init__(self, data: Any) -> None:
        self.data = data


class _Query:
    def __init__(self, client: FakeSupabase, table: str) -> None:
        self._client = client
        self._table = table

    def select(self, *args: Any, **kwargs: Any) -> _Query:
        self._client.select_calls.append((self._table, args, kwargs))
        return self

    def limit(self, _n: int) -> _Query:
        return self

    def upsert(self, payload: list[dict[str, Any]]) -> _Query:
        self._client.upserts.append((self._table, payload))
        return self

    def delete(self) -> _Query:
        self._client.deletes.append(self._table)
        return self

    def in_(self, column: str, values: list[str]) -> _Query:
        self._client.in_calls.append((column, list(values)))
        return self

    def execute(self) -> _Result:
        self._client.executes += 1
        if self._client.raise_on_execute:
            raise RuntimeError("postgrest exploded")
        return _Result(self._client.data)


class FakeSupabase:
    def __init__(self, data: Any = _UNSET) -> None:
        self.data: Any = [] if data is _UNSET else data
        self.upserts: list[tuple[str, list[dict[str, Any]]]] = []
        self.deletes: list[str] = []
        self.in_calls: list[tuple[str, list[str]]] = []
        self.select_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.executes = 0
        self.raise_on_execute = False
        self.tables: list[str] = []

    def table(self, name: str) -> _Query:
        self.tables.append(name)
        return _Query(self, name)


def make_session(**kwargs: Any) -> SessionData:
    return SessionData(session_id=kwargs.pop("session_id", "s1"), **kwargs)


# ────────────────────── file backend ───────────────────────────────────────


class TestFileSessionBackend:
    def test_missing_file_is_empty_not_unknown(self, tmp_path: Path) -> None:
        backend = FileSessionBackend(tmp_path / "sessions.json")
        assert backend.load_all() == {}

    def test_round_trip_preserves_nested_models_and_enums(
        self, tmp_path: Path
    ) -> None:
        backend = FileSessionBackend(tmp_path / "sessions.json")
        session = make_session(
            status=ProcessingStatus.COMPLETED,
            progress=0.75,
            master_r2_key="masters/s1.wav",
            mix_r2_key="masters/s1-mix.wav",
            preset_masters={
                "warm": {"preset_id": "warm", "r2_key": "masters/s1-warm.wav"}
            },
        )

        assert backend.upsert_many({"s1": session.model_dump(mode="json")}) is True

        loaded = backend.load_all()
        assert loaded is not None
        assert loaded["s1"] == session
        assert loaded["s1"].status is ProcessingStatus.COMPLETED

    def test_upsert_merges_instead_of_replacing(self, tmp_path: Path) -> None:
        backend = FileSessionBackend(tmp_path / "sessions.json")
        backend.upsert_many({"a": make_session().model_dump(mode="json")})
        backend.upsert_many({"b": make_session().model_dump(mode="json")})

        loaded = backend.load_all()
        assert loaded is not None
        assert set(loaded) == {"a", "b"}

    def test_corrupt_file_reports_unknown(self, tmp_path: Path) -> None:
        path = tmp_path / "sessions.json"
        path.write_text("{not json", encoding="utf-8")

        assert FileSessionBackend(path).load_all() is None

    def test_corrupt_file_is_not_overwritten_by_an_upsert(
        self, tmp_path: Path
    ) -> None:
        """A half-readable file must not be replaced by a partial view."""
        path = tmp_path / "sessions.json"
        path.write_text("{not json", encoding="utf-8")
        backend = FileSessionBackend(path)

        assert (
            backend.upsert_many({"a": make_session().model_dump(mode="json")})
            is False
        )
        assert path.read_text(encoding="utf-8") == "{not json"

    def test_write_is_atomic_leaving_no_tmp_file(self, tmp_path: Path) -> None:
        backend = FileSessionBackend(tmp_path / "sessions.json")
        backend.upsert_many({"a": make_session().model_dump(mode="json")})

        assert not (tmp_path / "sessions.json.tmp").exists()
        assert json.loads((tmp_path / "sessions.json").read_text("utf-8"))

    def test_delete_removes_only_the_named_ids(self, tmp_path: Path) -> None:
        backend = FileSessionBackend(tmp_path / "sessions.json")
        backend.upsert_many(
            {
                "a": make_session().model_dump(mode="json"),
                "b": make_session().model_dump(mode="json"),
            }
        )

        assert backend.delete_many(["a"]) is True

        loaded = backend.load_all()
        assert loaded is not None
        assert set(loaded) == {"b"}

    def test_empty_calls_are_successful_no_ops(self, tmp_path: Path) -> None:
        backend = FileSessionBackend(tmp_path / "sessions.json")
        assert backend.upsert_many({}) is True
        assert backend.delete_many([]) is True


# ────────────────────── supabase backend ───────────────────────────────────


class TestSupabaseSessionBackend:
    def test_probe_accepts_a_queryable_table(self) -> None:
        SupabaseSessionBackend.probe(FakeSupabase(data=[{"session_id": "a"}]))

    def test_probe_rejects_a_table_that_returns_nothing(self) -> None:
        """The missing-migration case: PostgREST answers, but with no data."""
        with pytest.raises(RuntimeError):
            SupabaseSessionBackend.probe(FakeSupabase(data=None))

    def test_probe_rejects_a_failing_project(self) -> None:
        client = FakeSupabase()
        client.raise_on_execute = True
        with pytest.raises(RuntimeError):
            SupabaseSessionBackend.probe(client)

    def test_load_parses_rows(self) -> None:
        payload = make_session(status=ProcessingStatus.PROCESSING).model_dump(
            mode="json"
        )
        client = FakeSupabase(data=[{"session_id": "s1", "payload": payload}])

        loaded = SupabaseSessionBackend(client).load_all()

        assert loaded is not None
        assert loaded["s1"].status is ProcessingStatus.PROCESSING

    def test_load_returns_unknown_on_error(self) -> None:
        client = FakeSupabase()
        client.raise_on_execute = True

        assert SupabaseSessionBackend(client).load_all() is None

    def test_load_returns_unknown_when_no_data_comes_back(self) -> None:
        assert SupabaseSessionBackend(FakeSupabase(data=None)).load_all() is None

    def test_one_bad_row_does_not_hide_the_others(self) -> None:
        """A mass "data loss" report must not come from a single bad row."""
        good = make_session().model_dump(mode="json")
        client = FakeSupabase(
            data=[
                {"session_id": "ok", "payload": good},
                {"session_id": "broken", "payload": {"progress": "not-a-number"}},
            ]
        )

        loaded = SupabaseSessionBackend(client).load_all()

        assert loaded is not None
        assert set(loaded) == {"ok"}

    def test_load_skips_structurally_wrong_rows(self) -> None:
        client = FakeSupabase(
            data=[
                {"session_id": 42, "payload": {}},
                {"session_id": "no-payload"},
                {"payload": {}},
                "not-a-dict",
            ]
        )

        assert SupabaseSessionBackend(client).load_all() == {}

    def test_upsert_sends_session_id_status_and_the_whole_payload(self) -> None:
        client = FakeSupabase()
        payload = make_session(status=ProcessingStatus.COMPLETED).model_dump(
            mode="json"
        )

        assert SupabaseSessionBackend(client).upsert_many({"s1": payload}) is True

        table, rows = client.upserts[0]
        assert table == "sessions"
        assert rows[0]["session_id"] == "s1"
        assert rows[0]["status"] == "completed"
        assert rows[0]["payload"] == payload
        assert rows[0]["updated_at"]

    def test_upsert_reports_failure_without_raising(self) -> None:
        client = FakeSupabase()
        client.raise_on_execute = True

        assert (
            SupabaseSessionBackend(client).upsert_many(
                {"s1": make_session().model_dump(mode="json")}
            )
            is False
        )

    def test_delete_scopes_by_session_id(self) -> None:
        client = FakeSupabase()

        assert SupabaseSessionBackend(client).delete_many(["a", "b"]) is True

        assert client.deletes == ["sessions"]
        assert client.in_calls == [("session_id", ["a", "b"])]

    def test_delete_reports_failure_without_raising(self) -> None:
        client = FakeSupabase()
        client.raise_on_execute = True

        assert SupabaseSessionBackend(client).delete_many(["a"]) is False


# ────────────────────────────── selection ──────────────────────────────────


class TestBackendSelection:
    @pytest.fixture(autouse=True)
    def _clean(self) -> None:
        reset_session_backend()

    def teardown_method(self) -> None:
        reset_session_backend()

    def test_file_choice_never_touches_supabase(self) -> None:
        settings.session_store_backend = "file"

        backend = get_session_backend()

        assert isinstance(backend, FileSessionBackend)

    def test_invalid_setting_fails_loudly(self) -> None:
        """Silently degrading on a typo would hide the misconfiguration."""
        settings.session_store_backend = "sqlite"

        with pytest.raises(ValueError):
            get_session_backend()

    def test_forced_supabase_without_credentials_raises(self) -> None:
        settings.session_store_backend = "supabase"
        original_url = settings.supabase_url
        settings.supabase_url = ""
        try:
            with pytest.raises(RuntimeError):
                get_session_backend()
        finally:
            settings.supabase_url = original_url

    def test_auto_falls_back_to_the_file_mirror_without_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings.session_store_backend = "auto"
        monkeypatch.setattr(settings, "supabase_url", "")

        assert isinstance(get_session_backend(), FileSessionBackend)

    def test_auto_falls_back_when_the_table_does_not_exist(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Credentials are already live in production, so 'configured' proves
        nothing about the table. An unapplied migration must degrade to the
        file mirror instead of picking a backend that fails every write."""
        from audiomind.services import supabase_client

        settings.session_store_backend = "auto"
        monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
        monkeypatch.setattr(settings, "supabase_service_role_key", "service-role")
        # Patched at the SOURCE module: ``get_session_backend`` imports the
        # helper inside the function body, so patching this module's attribute
        # would do nothing and the test would probe the real project over the
        # network -- the exact leak the harness exists to prevent.
        monkeypatch.setattr(
            supabase_client, "get_supabase_client", lambda: FakeSupabase(data=None)
        )

        assert isinstance(get_session_backend(), FileSessionBackend)

    def test_auto_selects_supabase_when_the_table_is_queryable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from audiomind.services import supabase_client

        settings.session_store_backend = "auto"
        monkeypatch.setattr(settings, "supabase_url", "https://example.supabase.co")
        monkeypatch.setattr(settings, "supabase_service_role_key", "service-role")
        monkeypatch.setattr(
            supabase_client,
            "get_supabase_client",
            lambda: FakeSupabase(data=[{"session_id": "a"}]),
        )

        backend = get_session_backend()

        assert isinstance(backend, SupabaseSessionBackend)
        assert FakeSupabase is not None

    def test_the_backend_is_cached(self) -> None:
        settings.session_store_backend = "file"
        assert get_session_backend() is get_session_backend()


# ───────────────────────── harness self-guard ──────────────────────────────


def test_the_suite_can_never_reach_the_real_sessions_table() -> None:
    """Guards the conftest pin itself.

    The failure mode this exists to catch: someone deletes the import-time pin
    in conftest.py, the real ``.env`` credentials make ``auto`` select
    Supabase, and every subsequent test writes and prunes rows in the
    PRODUCTION sessions table without a single failure. Asserting the active
    backend turns that silence into a red test.
    """
    assert isinstance(get_session_backend(), FileSessionBackend)


def test_the_suite_can_never_build_a_real_supabase_client() -> None:
    """Guards the Supabase seal in conftest.

    The job store reached production this way: ``get_job_store`` builds a real
    client and probes the real ``dsp_jobs`` table, and once that probe passed,
    unit tests wrote rows into production. ``create_client`` is sealed too, so
    this asserts the factory seam rather than one caller's behaviour.
    """
    from audiomind.services import supabase_client

    assert supabase_client.get_supabase_client() is None
    with pytest.raises(RuntimeError):
        supabase_client.create_client(  # type: ignore[attr-defined]
            "https://example.supabase.co", "key"
        )


# ─────────────────────── session_store integration ─────────────────────────


class TestSessionStoreReconciliation:
    @pytest.fixture
    def backend(self) -> RecordingBackend:
        return RecordingBackend()

    @pytest.fixture
    def store(
        self, backend: RecordingBackend, monkeypatch: pytest.MonkeyPatch
    ) -> Any:
        """Install a recording backend and clear the reconciliation state."""
        from audiomind import session_store

        monkeypatch.setattr(sb, "_backend", backend)
        monkeypatch.setattr(session_store, "_last_digests", {})
        monkeypatch.setattr(session_store, "_load_complete", False)
        return session_store

    def test_only_changed_sessions_are_written(
        self, store: Any, backend: RecordingBackend
    ) -> None:
        """The point of the digests: a whole-store save must not rewrite every
        row just because one session changed."""
        store.save_sessions(
            {
                "a": make_session(),
                "b": make_session(session_id="b"),
            }
        )
        assert set(backend.upserts[0]) == {"a", "b"}

        backend.upserts.clear()
        sessions = {"a": make_session(), "b": make_session(session_id="b")}
        sessions["b"] = SessionData(session_id="b", progress=0.5)
        store.save_sessions(sessions)

        assert set(backend.upserts[0]) == {"b"}

    def test_an_unchanged_store_writes_nothing(
        self, store: Any, backend: RecordingBackend
    ) -> None:
        backend.rows = {"a": make_session()}
        store.load_sessions()
        backend.upserts.clear()

        store.save_sessions({"a": make_session()})

        assert backend.upserts == []

    def test_key_order_alone_is_not_a_change(self, store: Any) -> None:
        session = make_session()
        dumped = session.model_dump(mode="json")
        reordered = {k: dumped[k] for k in reversed(list(dumped))}
        assert store._digest(reordered) == store._digest(dumped)

    def test_incomplete_load_defers_pruning(
        self, store: Any, backend: RecordingBackend
    ) -> None:
        """THE CATASTROPHE TEST.

        A backend that cannot be read returns None, so the in-memory view may
        be missing sessions that are still stored. Deleting on that evidence
        would drop every session row in the table -- and the delete itself
        would succeed, so no exception and no recovery path.
        """
        backend.rows = {"a": make_session(), "b": make_session(session_id="b")}
        store.load_sessions()  # a healthy start: {a, b} are known to exist

        backend.load_result = None  # the store goes dark
        store.load_sessions()  # ... and a reload fails
        store.save_sessions({"a": make_session()})  # "b" pruned by the janitor

        assert backend.deletes == []
        assert "b" in backend.rows

    def test_a_failed_load_is_reported_and_not_treated_as_empty(
        self, store: Any, backend: RecordingBackend
    ) -> None:
        backend.load_result = None

        assert store.load_sessions() == {}
        assert store._load_complete is False

    def test_a_successful_load_prunes_dropped_sessions(
        self, store: Any, backend: RecordingBackend
    ) -> None:
        backend.rows = {
            "a": make_session(),
            "b": make_session(session_id="b"),
        }
        store.load_sessions()

        store.save_sessions({"a": make_session()})

        assert backend.deletes == [["b"]]
        assert "b" not in backend.rows

    def test_a_failed_upsert_is_retried_on_the_next_save(
        self, store: Any, backend: RecordingBackend
    ) -> None:
        """A write that fails must not be recorded as done: there is no
        periodic reconciler to catch up later."""
        backend.fail_upsert = True
        store.save_sessions({"a": make_session()})

        backend.fail_upsert = False
        backend.upserts.clear()
        store.save_sessions({"a": make_session()})

        assert set(backend.upserts[0]) == {"a"}

    def test_a_failed_delete_is_retried_on_the_next_save(
        self, store: Any, backend: RecordingBackend
    ) -> None:
        backend.rows = {
            "a": make_session(),
            "b": make_session(session_id="b"),
        }
        store.load_sessions()
        backend.fail_delete = True

        store.save_sessions({"a": make_session()})
        assert backend.rows["b"] is not None

        backend.fail_delete = False
        backend.deletes.clear()
        store.save_sessions({"a": make_session()})

        assert backend.deletes == [["b"]]
        assert "b" not in backend.rows

    def test_a_deferred_delete_is_not_forgotten(
        self, store: Any, backend: RecordingBackend
    ) -> None:
        """Deferring must mean 'retry', not 'drop the evidence'."""
        backend.rows = {"a": make_session(), "b": make_session(session_id="b")}
        store.load_sessions()  # a healthy start: {a, b} are known to exist

        backend.load_result = None  # the store goes dark, and a reload fails
        store.load_sessions()
        store.save_sessions({"a": make_session()})  # "b" pruned by the janitor
        assert backend.deletes == []

        # The store recovers and a load completes, so the view is authoritative
        # again. The deferred removal must now actually happen.
        backend.load_result = _UNSET
        store.load_sessions()
        store.save_sessions({"a": make_session()})

        assert backend.deletes == [["b"]]
        assert "b" not in backend.rows

    def test_load_seeds_the_digests(
        self, store: Any, backend: RecordingBackend
    ) -> None:
        backend.rows = {"a": make_session()}

        loaded = store.load_sessions()

        assert set(loaded) == {"a"}
        assert store._last_digests == {
            "a": store._digest(loaded["a"].model_dump(mode="json"))
        }
        assert store._load_complete is True