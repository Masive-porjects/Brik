"""Session-wide test harness safety.

INVARIANTS: the test suite must never write to a real storage backend, must
never read or write the real ``sessions`` table, and must never construct a
real Supabase client.

All three exist because ``apps/audiomind/.env`` holds LIVE credentials.
Verified: before master R2 durability, a plain ``pytest tests/`` performed real
PUTs into the production bucket -- ``test_demo_mode.py::TestDemoDownload``
alone wrote 4 objects under ``masters/``. Supabase was already configured for
``tracks`` and ``masters``, so "credentials present" is TRUE in this checkout
and an unpinned consumer reached the real project over the network. The job
store was the concrete case: ``get_job_store()`` builds a real client and
PROBES the real ``dsp_jobs`` table, so once that probe passed, unit tests
wrote rows into production.

The stubs live here rather than in each test module because the failure mode is
silence -- a new test module that forgets its stub reintroduces the leak, and
40+ modules already did. Harness-level autouse fixtures make "no real backend"
a property of running the suite at all, not a per-file convention.

Individual tests that need upload/download behavior override these in their own
body via ``monkeypatch.setattr``; that runs after this fixture and wins.

Why the Supabase seal is at ``get_supabase_client``
---------------------------------------------------
It is the single chokepoint every consumer already goes through: the job store
(``job_store.get_job_store``), the session backend
(``services.session_backend``) and the master recorder in ``dsp_worker``. Sealing
one function covers all three, plus anything added later, instead of hunting
down each call site. ``create_client`` is sealed too, so a future code path
cannot bypass the factory and open a real connection.

``create_client`` raises rather than returning ``None``, because a caller that
ignores the result would then operate on ``None`` instead of failing. Returning
``None`` from the factory is the deliberate choice at the factory, not at the
constructor: it is the documented "Supabase is not configured" answer, which is
the situation these tests should be modelling.

Why the session pin is at module level, not in a fixture
---------------------------------------------------------
``api.upload`` evaluates ``load_sessions()`` at IMPORT time, which happens
during pytest collection -- before any fixture runs. A fixture-level pin would
therefore land too late: the selection (and a read of whatever store it picked)
would already have happened against the developer's real data. So the pin runs
in this module's body, and the fixture's job is only to redirect each test's
writes into its own ``tmp_path``.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from audiomind.services import storage
from audiomind.services.storage import StorageError

# ─────────────────────────────── import-time pin ───────────────────────────
# Runs before any test module is imported, therefore before `api.upload` builds
# its in-memory session dict and before any consumer can build a Supabase
# client. The temporary directory is only needed for that single import-time
# read; per-test writes are redirected by the fixture below.

_HARNESS_SESSIONS_DIR = Path(tempfile.mkdtemp(prefix="audiomind-test-sessions-"))


def _no_real_supabase_client(token: str | None = None) -> None:
    """Stand-in for ``get_supabase_client`` that never opens a connection.

    Returning ``None`` is the factory's own documented answer for "Supabase is
    not configured", so every caller's REAL handling of an unconfigured project
    runs: ``get_job_store`` falls back to its in-memory store, the session
    backend falls back to the file mirror, and ``dsp_worker`` skips the master
    record. Nothing reaches the network and no test depends on a live table.

    A test that needs Supabase semantics injects its own fake over this, which
    is what ``test_async_mix_jobs.py`` already does.
    """
    return None


def _sealed_create_client(*_args: Any, **_kwargs: Any) -> Any:
    """Refuse to construct a Supabase client from anywhere in the suite."""
    raise RuntimeError(
        "The test suite must not construct a real Supabase client. Inject a "
        "fake client, or patch get_supabase_client / create_client."
    )


try:
    from audiomind.config import settings
    from audiomind.services import session_backend as _session_backend
    from audiomind.services import supabase_client as _supabase_client

    settings.session_store_backend = "file"
    _session_backend.reset_session_backend()
    _session_backend._backend = _session_backend.FileSessionBackend(  # noqa: SLF001
        _HARNESS_SESSIONS_DIR / "sessions.json"
    )

    # Seal the Supabase chokepoint before anything can reach it. ``create_client``
    # is re-imported from the ``supabase`` package rather than exported by this
    # module, so mypy needs the ignore to seal a name it considers private.
    _supabase_client.get_supabase_client = _no_real_supabase_client
    _supabase_client.create_client = _sealed_create_client  # type: ignore[attr-defined]
    _supabase_client._default_client = None  # noqa: SLF001
except Exception as _exc:  # pragma: no cover - import safety net
    # A broken pin must be loud. Silently continuing would let the suite talk to
    # production, which is the exact failure this module exists to prevent.
    raise RuntimeError(
        "conftest could not hermetrize the storage backends; the test suite "
        "must not be allowed to reach R2 or Supabase."
    ) from _exc


@pytest.fixture(scope="session", autouse=True)
def _cleanup_harness_sessions_dir() -> Iterator[None]:
    """Remove the import-time scratch directory once the run finishes."""
    yield
    shutil.rmtree(_HARNESS_SESSIONS_DIR, ignore_errors=True)


# ─────────────────────────────── per-test stubs ────────────────────────────


@pytest.fixture(autouse=True)
def _never_talk_to_supabase(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep the Supabase seal in force for every single test.

    The module-level patch already covers collection-time imports; this
    re-applies it per test so the seal cannot drift, and so a test that patches
    the factory for itself gets it restored automatically afterwards instead of
    leaking that fake into the next test.
    """
    monkeypatch.setattr(
        _supabase_client, "get_supabase_client", _no_real_supabase_client
    )
    monkeypatch.setattr(_supabase_client, "create_client", _sealed_create_client)
    monkeypatch.setattr(_supabase_client, "_default_client", None)
    yield


@pytest.fixture(autouse=True)
def _never_touch_real_storage(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Make an unstubbed storage call degrade instead of hitting the network.

    ``storage.get_s3_client()`` raises ``StorageError`` when R2 is not fully
    configured, so reproducing that error here is enough: every storage helper
    propagates it, and the code that is *supposed* to degrade on an R2 outage
    (``_persist_master_to_r2``, ``_hydrate_mix_from_r2``) does so through its
    real ``except`` branch rather than a test-only one. A test that genuinely
    needs upload/download behavior overrides ``storage.upload_file`` /
    ``download_to`` in its own body, and that wins because it runs later.

    Deliberately NOT an ``AssertionError``: that would turn a forgotten stub
    into a hard failure in tests that are only incidentally exercising the R2
    path, and would mask whether the degradation logic itself is correct.
    """

    def _unconfigured() -> Any:
        raise StorageError(
            "Cloudflare R2 is not configured; the test suite must not reach "
            "the real bucket. Stub storage.upload_file / download_to / exists."
        )

    monkeypatch.setattr(storage, "get_s3_client", _unconfigured)
    yield


@pytest.fixture(autouse=True)
def _sessions_never_leave_tmp_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[None]:
    """Point the pinned session backend at this test's ``tmp_path``.

    Tests that assert on session persistence get a private file per test and do
    not have to know that a harness-level pin exists.
    """
    from audiomind.services import session_backend as session_backend_mod

    monkeypatch.setattr(
        session_backend_mod,
        "_backend",
        session_backend_mod.FileSessionBackend(tmp_path / "sessions.json"),
    )
    yield