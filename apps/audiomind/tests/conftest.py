"""Session-wide test harness safety.

INVARIANT: the test suite must never write to a real storage backend.

Before master R2 durability, mastering only touched the local filesystem, so
test modules needed no storage stub and each one patched ``process_audio`` to
write into ``tmp_path``. Once every master also uploads to Cloudflare R2, that
stopped being true: ``apps/audiomind/.env`` holds live credentials, so a plain
``pytest tests/`` performed real PUTs into the production bucket. Verified:
``pytest tests/test_demo_mode.py::TestDemoDownload`` wrote 4 objects under
``masters/``.

The stubs live here rather than in each test module because the failure mode is
silence — a new test module that forgets its stub reintroduces the leak, and 40+
modules already did. A harness-level autouse fixture makes "no real R2" a
property of running the suite at all, not a per-file convention.

Individual tests that need upload/download behavior override these in their own
body via ``monkeypatch.setattr``; that runs after this fixture and wins.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from audiomind.services import storage
from audiomind.services.storage import StorageError


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
def _sessions_json_never_clobbered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[None]:
    """Redirect ``sessions.json`` away from the developer's real file.

    ``session_store.SESSION_FILE`` is resolved from ``settings.upload_dir`` AT
    IMPORT TIME, so patching ``upload_dir`` in a test is not enough: without
    this, any endpoint calling ``save_sessions()`` would overwrite the real
    ``uploads/sessions.json`` with a test's session dict. Tests that need to
    assert on persistence can re-patch it to their own ``tmp_path``.
    """
    import audiomind.session_store as session_store_mod

    monkeypatch.setattr(
        session_store_mod, "SESSION_FILE", tmp_path / "harness_sessions.json"
    )
    yield