"""Tests for demo-mode session TTL pruning."""
import sys

sys.path.insert(0, "src")

import pytest

from audiomind.api.upload import sessions
from audiomind.config import settings
from audiomind.models.audio import ProcessingStatus, SessionData
from audiomind.services import demo_guard


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch):
    sessions.clear()
    demo_guard.clear_activity()
    monkeypatch.setattr(settings, "license_key", "")
    yield
    sessions.clear()
    demo_guard.clear_activity()


# ── TTL disabled ─────────────────────────────────────────────────────


class TestDemoTTLDisabled:
    def test_no_prune_when_disabled(self, monkeypatch):
        """session_ttl_minutes=0 -> prune returns [], nothing removed."""
        monkeypatch.setattr(settings, "session_ttl_minutes", 0)
        sessions["sid"] = SessionData(
            session_id="sid",
            status=ProcessingStatus.UPLOADED,
        )
        demo_guard.touch("sid", now=1000)
        pruned = demo_guard.prune_expired_sessions(now=999999)
        assert pruned == []
        assert "sid" in sessions


# ── TTL enabled ──────────────────────────────────────────────────────


class TestDemoTTLEnabled:
    def test_prunes_old_keeps_fresh(self, monkeypatch):
        """Old session pruned, fresh session kept."""
        monkeypatch.setattr(settings, "session_ttl_minutes", 60)

        sessions["old-sid"] = SessionData(
            session_id="old-sid",
            status=ProcessingStatus.UPLOADED,
        )
        sessions["fresh-sid"] = SessionData(
            session_id="fresh-sid",
            status=ProcessingStatus.UPLOADED,
        )
        demo_guard.touch("old-sid", now=1000)
        demo_guard.touch("fresh-sid", now=100000)

        # cutoff = 100000 - 3600 = 96400
        # old-sid: 1000 <= 96400 -> pruned
        # fresh-sid: 100000 > 96400 -> kept
        pruned = demo_guard.prune_expired_sessions(now=100000)
        assert "old-sid" in pruned
        assert "fresh-sid" not in pruned
        assert "old-sid" not in sessions
        assert "fresh-sid" in sessions


# ── Processing session skipped ───────────────────────────────────────


class TestDemoTTLProcessingSkipped:
    def test_processing_session_not_pruned(self, monkeypatch):
        """Processing sessions are never pruned even if old."""
        monkeypatch.setattr(settings, "session_ttl_minutes", 60)
        sessions["proc-sid"] = SessionData(
            session_id="proc-sid",
            status=ProcessingStatus.PROCESSING,
        )
        demo_guard.touch("proc-sid", now=1000)

        pruned = demo_guard.prune_expired_sessions(now=100000)
        assert "proc-sid" not in pruned
        assert "proc-sid" in sessions


# ── Missing files tolerated ──────────────────────────────────────────


class TestDemoTTLMissingFiles:
    def test_missing_files_tolerated(self, monkeypatch):
        """Pruning a session with non-existent files does not raise."""
        monkeypatch.setattr(settings, "session_ttl_minutes", 60)
        sessions["missing-sid"] = SessionData(
            session_id="missing-sid",
            status=ProcessingStatus.UPLOADED,
            original_path="/nonexistent/path/to/audio.wav",
        )
        demo_guard.touch("missing-sid", now=1000)

        pruned = demo_guard.prune_expired_sessions(now=100000)
        assert "missing-sid" in pruned
        assert "missing-sid" not in sessions
