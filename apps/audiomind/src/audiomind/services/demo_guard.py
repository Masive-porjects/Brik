"""Demo-mode runtime guards: single-flight DSP, global gate, session TTL.

Owns the module-level structures that enforce the client-demo constraints
without touching any DSP code:

* ``get_or_create_flight`` — one in-flight ``concurrent.futures.Future``
  per ``(session_id, preset_id)`` key, so concurrent
  ``/process?preset_id=X`` calls share the SAME heavy DSP job
  (single-flight: never two engines writing the same output file).
* ``gate`` + ``DSP_THREAD_POOL`` — a global semaphore and a thread pool
  sized by ``settings.max_concurrent_dsp`` (default 2 = the historic
  ``_dsp_executor`` width; the demo sets 1 so heavy DSP serializes on the
  1GB Railway box).
* ``touch`` / ``prune_expired_sessions`` — per-session activity timestamps
  and a tolerant TTL janitor (enabled only when
  ``session_ttl_minutes > 0``).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any

from audiomind.config import settings

_lock = threading.Lock()
_flights: dict[tuple[str, str], Future[None]] = {}

# Heavy-DSP execution counter: incremented ONLY where the real pipeline
# runs (mastering._run_preset_job). Cache hits, pre-built copies, and
# pre-render-cache copies never call it, so it is the authoritative
# "DSP executions" meter for demo validation over the real HTTP path.
_dsp_executions: int = 0

_gate = threading.BoundedSemaphore(max(1, settings.max_concurrent_dsp))

# Dedicated pool for heavy DSP invocations (process_audio) that must be
# concurrency-limited. Analysis/reference/album work keeps the historic
# ``_dsp_executor`` in mastering.py.
DSP_THREAD_POOL = ThreadPoolExecutor(
    max_workers=max(1, settings.max_concurrent_dsp),
    thread_name_prefix="dsp-gated",
)

_activity: dict[str, float] = {}


class DemoDurationError(Exception):
    """Raised when a demo-mode duration limit is exceeded (→ HTTP 422)."""


# ── Single-flight map ─────────────────────────────────────────────────


def get_or_create_flight(
    session_id: str, preset_id: str, job_fn: Callable[[], None]
) -> Future[None]:
    """Return the in-flight Future for (session, preset), creating it once.

    The map is read AND written under ``_lock``, so concurrent ``/process``
    calls racing for the same key share one Future and one DSP job. The key
    is removed in the Future's done callback.

    ``job_fn`` is submitted to ``DSP_THREAD_POOL`` only when no Future
    exists yet.
    """
    with _lock:
        existing = _flights.get((session_id, preset_id))
        if existing is not None:
            return existing
        future = DSP_THREAD_POOL.submit(job_fn)
        _flights[(session_id, preset_id)] = future
    future.add_done_callback(lambda _f: _pop_flight(session_id, preset_id))
    return future


def _pop_flight(session_id: str, preset_id: str) -> None:
    """Remove a finished flight key (called from the Future callback)."""
    with _lock:
        _flights.pop((session_id, preset_id), None)


def clear_flights() -> None:
    """Forget all in-flight keys (tests). Never cancels running jobs."""
    with _lock:
        _flights.clear()


# ── Global DSP gate ────────────────────────────────────────────────────


def gate() -> threading.BoundedSemaphore:
    """The global DSP concurrency gate — use ``with demo_guard.gate():``."""
    return _gate


def reset_gate() -> None:
    """Rebuild gate + pool from the CURRENT settings value.

    Production reads the env at startup; tests that monkeypatch
    ``settings.max_concurrent_dsp`` after import call this to make the
    gate (and pool width) match.
    """
    global _gate, DSP_THREAD_POOL
    workers = max(1, settings.max_concurrent_dsp)
    _gate = threading.BoundedSemaphore(workers)
    DSP_THREAD_POOL = ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="dsp-gated"
    )


# ── DSP execution meter (demo validation) ─────────────────────────────


def record_dsp_execution() -> None:
    """Count one real heavy-DSP pipeline run (called by the job itself)."""
    global _dsp_executions
    with _lock:
        _dsp_executions += 1


def dsp_execution_count() -> int:
    """Current total of DSP pipelines executed since process start."""
    return _dsp_executions


def reset_dsp_count() -> None:
    """Forget the counter (tests / benchmark reset)."""
    global _dsp_executions
    with _lock:
        _dsp_executions = 0


# ── Demo duration probe / message ─────────────────────────────────────


def probe_duration(path: str | Path) -> float | None:
    """Header-only duration probe; None on any failure.

    WAV uses ``soundfile.info`` (header-only, fast); MP3 uses
    ``librosa.get_duration`` (audioread). A failed probe never rejects —
    the defensive ``/process`` and ``/master`` checks catch it later.
    """
    try:
        audio_path = Path(path)
        if audio_path.suffix.lower() == ".wav":
            import soundfile as sf

            return float(sf.info(str(audio_path)).duration)
        import librosa

        return float(librosa.get_duration(path=str(audio_path)))
    except Exception:
        return None


def demo_duration_message(limit_seconds: float) -> str:
    """Friendly 422 detail for demo duration rejection (es-AR microcopy).

    The numeric part is formatted as an integer when whole (60.0 → "60"),
    otherwise as-is (60.5 → "60.5").
    """
    if float(limit_seconds).is_integer():
        value = str(int(limit_seconds))
    else:
        value = str(limit_seconds)
    return f"Demo: carga hasta {value} segundos de audio."


def duration_over_limit(duration: float | None) -> bool:
    """True when a measured duration exceeds the configured demo limit."""
    limit = settings.demo_max_duration_seconds
    return limit > 0.0 and duration is not None and duration > limit


# ── Session activity / TTL pruning ────────────────────────────────────


def touch(session_id: str, now: float | None = None) -> None:
    """Record session activity so TTL pruning never deletes live work."""
    if settings.session_ttl_minutes <= 0:
        return
    _activity[session_id] = time.time() if now is None else now


def clear_activity() -> None:
    """Forget all activity timestamps (tests / manual reset)."""
    _activity.clear()


def prune_expired_sessions(now: float | None = None) -> list[str]:
    """Remove demo sessions idle longer than ``session_ttl_minutes``.

    Disabled by default (0 = never prune). Tolerant by design: missing
    files, partial sessions, lost caches and restart-emptied activity are
    all skipped; sessions that are analyzing/processing (or have a preset
    currently processing) are NEVER deleted. Only the session's own files
    under ``uploads/`` and ``outputs/`` are removed.

    Returns the list of pruned session ids.
    """
    ttl_minutes = settings.session_ttl_minutes
    if ttl_minutes <= 0:
        return []
    from audiomind.api.mastering import _prerender_cache
    from audiomind.api.upload import sessions
    from audiomind.models.audio import ProcessingStatus
    from audiomind.session_store import save_sessions

    cutoff = (time.time() if now is None else now) - ttl_minutes * 60.0
    pruned: list[str] = []
    for session_id, last_activity in list(_activity.items()):
        if last_activity > cutoff:
            continue
        session = sessions.get(session_id)
        if session is None:
            continue
        if session.status in (
            ProcessingStatus.ANALYZING,
            ProcessingStatus.PROCESSING,
        ):
            continue  # never delete active work
        if any(
            entry.status == "processing" for entry in session.preset_masters.values()
        ):
            continue
        _remove_session_files(session_id, _prerender_cache)
        sessions.pop(session_id, None)
        _activity.pop(session_id, None)
        pruned.append(session_id)
    if pruned:
        save_sessions(sessions)  # best-effort internally
    return pruned


def _remove_session_files(
    session_id: str, prerender_cache: dict[str, dict[str, dict[str, Any]]]
) -> None:
    """Delete every file owned by the session (upload + output + cache)."""
    for pattern, directory in (
        (f"{session_id}*", settings.upload_dir),
        (f"{session_id}*.wav", settings.output_dir),
    ):
        for path in directory.glob(pattern):
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass  # tolerate transient locks / already-missing files
    try:
        prerender_cache.pop(session_id, None)
    except Exception:
        pass
