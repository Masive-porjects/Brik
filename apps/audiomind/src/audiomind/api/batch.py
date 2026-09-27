"""Album/EP batch mastering endpoints (Phase D, P1-2).

Two additive routes under the ``/api`` prefix:

- ``POST /api/album/negotiate`` — measurement-only (no DSP): loads each
  session's original file, measures its EBU 3342-style LRA and negotiates
  one relative ``target_lufs_db`` per track against the album base.
- ``POST /api/album/process`` — masters each session IN ORDER toward its
  negotiated target by overriding ONLY ``MasteringParameters.target_lufs_db``
  on the existing single-track pipeline (``process_audio``). The DSP chain,
  engine, presets and neutral contract are untouched: this endpoint is
  purely additive — it computes numbers and feeds them through the exact
  path ``POST /api/session/{id}/process`` already uses, then replaces the
  session state exactly like that endpoint does.

Failure semantics (documented contract):
- Guards fail fast (empty ``session_ids`` → 400, unknown session → 404,
  missing original file → 400) — structural problems, not per-track ones.
- Per-track measurement/processing failures NEVER abort the album: the
  affected track is marked (null metrics + error in ``warnings``,
  ``within_tolerance=False``) and the remaining tracks are processed. The
  original exception type is preserved in the warning (``IOError``,
  ``InputQcError``, …) so callers can react without losing the reason.
- All statements in English; report-facing warning strings follow the
  existing Spanish (neutral Latin American) convention of the engine/mastering
  surfaces.

Lightweight imports only: heavy DSP (librosa, the loudness meter, the
engine) is late-bound through lazy wrappers exactly like ``mastering.py``,
so FastAPI startup stays light (OOM mitigation).
"""
from __future__ import annotations

import asyncio
import statistics
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from audiomind.api.license import require_license
from audiomind.api.mastering import (
    _dsp_executor,
    _master_result_from_engine,
    _mastering_report_from_engine,
)
from audiomind.api.upload import sessions
from audiomind.config import settings
from audiomind.models.audio import (
    AlbumNegotiateRequest,
    AlbumNegotiationResult,
    AlbumNegotiationTrack,
    AlbumProcessRequest,
    AlbumProcessResult,
    AlbumProcessTrack,
    MasteringParameters,
    ProcessingStatus,
    SessionData,
)
from audiomind.processing.album import (
    ALBUM_LUFS_TOLERANCE_DB,
    DEFAULT_ALBUM_TARGET_LUFS_DB,
    negotiate_targets,
)
from audiomind.session_store import save_sessions


# Lazy module-level names for the heavy DSP entry points — same pattern as
# ``mastering.py``: the wrapper imports the real implementation on first
# call, and monkeypatching this module's attribute replaces the wrapper
# itself (the technique the route tests rely on).
def _lazy_dsp_call(module_name: str, attr: str) -> Callable[..., Any]:
    """Return a wrapper that late-imports ``module_name.attr`` per call."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        import importlib

        impl = getattr(importlib.import_module(module_name), attr)
        return impl(*args, **kwargs)

    return wrapper


# The aliases carry the REAL signatures of the targets (engine.process_audio
# returns ``dict[str, Any]``; loudness.measure_lra returns ``float``) so the
# wrappers stay honest for callers while still importing lazily.
process_audio: Callable[..., dict[str, Any]] = _lazy_dsp_call(
    "audiomind.processing.engine", "process_audio"
)
_load_audio = _lazy_dsp_call("librosa", "load")
measure_lra: Callable[..., float] = _lazy_dsp_call(
    "audiomind.processing.loudness", "measure_lra"
)

router = APIRouter()


def _resolve_sessions(session_ids: list[str]) -> list[tuple[str, SessionData]]:
    """Guard: resolve session ids in album order; fail fast on structure.

    400 for an empty list, 404 for an unknown session (naming it), 400 for
    a session whose original file is missing on disk (naming it). Only
    STRUCTURAL problems fail here — per-track measurement/processing
    failures are handled by the endpoints, never here.
    """
    if not session_ids:
        raise HTTPException(
            status_code=400,
            detail=(
                "session_ids must contain at least one session. Upload "
                "tracks first (POST /api/upload) and send their ids in "
                "album order."
            ),
        )
    resolved: list[tuple[str, SessionData]] = []
    for sid in session_ids:
        session = sessions.get(sid)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{sid}' not found.",
            )
        if not session.original_path or not Path(session.original_path).exists():
            raise HTTPException(
                status_code=400,
                detail=f"Session '{sid}' has no audio file on disk.",
            )
        resolved.append((sid, session))
    return resolved


def _measure_input_lra(session: SessionData) -> float | None:
    """Load the original file and measure its EBU 3342-style LRA.

    Runs on the DSP executor (librosa load + the loudness meter are the
    heavy parts). Raises on undecodable files — callers catch per-track.
    """
    audio, sr = _load_audio(session.original_path, sr=None, mono=False)
    return measure_lra(audio, sr)


async def _measure_and_negotiate(
    session_ids: list[str], base_lufs_db: float | None
) -> tuple[
    list[tuple[str, SessionData]],
    list[float | None],
    list[float | None],
    float,
    float | None,
]:
    """Shared measurement + negotiation pass for both album endpoints.

    Returns ``(resolved, lras, targets, base, median)``. Per-track load
    failures contribute None to ``lras`` (never aborting the album); the
    negotiation then gives those tracks the album base unchanged.
    """
    resolved = _resolve_sessions(session_ids)
    lras: list[float | None] = []
    for _sid, session in resolved:
        try:
            lra = await asyncio.get_running_loop().run_in_executor(
                _dsp_executor, _measure_input_lra, session
            )
            lras.append(lra)
        except Exception:
            # Undecodable/corrupt file: keep the album alive, treat the
            # track as measurement-less (None LRA → base target).
            lras.append(None)
    base = (
        base_lufs_db
        if base_lufs_db is not None
        else DEFAULT_ALBUM_TARGET_LUFS_DB
    )
    targets = negotiate_targets(lras, base_lufs_db)
    valid_lras = [lra for lra in lras if lra is not None]
    median = statistics.median(valid_lras) if valid_lras else None
    return resolved, lras, targets, base, median


@router.post("/album/negotiate", response_model=AlbumNegotiationResult)
async def negotiate_album_targets(
    req: AlbumNegotiateRequest,
    _: object = Depends(require_license),  # noqa: B008 — repo-wide FastAPI convention
) -> AlbumNegotiationResult:
    """Measure per-track loudness/LRA and negotiate relative album targets.

    Measurement-only: no DSP, no audio mutation, so the neutral contract
    is preserved by construction. A track whose file fails to load keeps
    its input metrics null and receives the album base unchanged — the
    negotiation never fails the whole album for one bad track.
    """
    resolved, lras, targets, base, median = await _measure_and_negotiate(
        req.session_ids, req.target_lufs_db
    )

    tracks: list[AlbumNegotiationTrack] = []
    for (sid, session), lra, target in zip(resolved, lras, targets, strict=True):
        analysis_lufs = (
            session.analysis.integrated_lufs if session.analysis is not None else None
        )
        tracks.append(
            AlbumNegotiationTrack(
                session_id=sid,
                original_filename=session.original_filename,
                input_lufs_db=(
                    round(analysis_lufs, 1)
                    if analysis_lufs is not None
                    else None
                ),
                input_lra_lu=round(lra, 2) if lra is not None else None,
                negotiated_target_lufs_db=target,
                offset_db=(
                    round(target - base, 1) if target is not None else None
                ),
            )
        )

    return AlbumNegotiationResult(
        target_base_lufs_db=base,
        lra_median_lu=round(median, 2) if median is not None else None,
        tracks=tracks,
    )


def _run_track_processing(
    session: SessionData, params: MasteringParameters, output_path: Path
) -> dict[str, Any]:
    """Run the existing single-track engine on the DSP executor.

    Only ``target_lufs_db`` is overridden per track — the rest of the
    request parameters pass through unchanged, so the neutral contract and
    the DSP chain behave exactly as in ``POST /api/session/{id}/process``.
    """
    return process_audio(
        input_path=session.original_path,
        output_path=output_path,
        params=params,
        analysis_result=session.analysis,
    )


@router.post("/album/process", response_model=AlbumProcessResult)
async def process_album(
    req: AlbumProcessRequest,
    _: object = Depends(require_license),  # noqa: B008 — repo-wide FastAPI convention
) -> AlbumProcessResult:
    """Master a batch of sessions toward negotiated relative targets.

    Runs the EXISTING single-track pipeline once per session, IN ORDER,
    with ``target_lufs_db`` set to the negotiated value. Each successful
    track REPLACES its session state the same way the single-track process
    endpoint does (``mastered_path``, ``parameters``, ``master_result``,
    ``mastering_report``, ``status=completed``) and the album is persisted
    once after ALL tracks.

    Per-track process failures (IOError, InputQcError, engine errors) are
    captured in the report — the track is marked with null metrics, the
    error in ``warnings`` and ``within_tolerance=False`` — and the album
    continues with the remaining tracks.
    """
    resolved, lras, targets, base, median = await _measure_and_negotiate(
        req.session_ids, req.target_lufs_db
    )

    tracks: list[AlbumProcessTrack] = []
    for (sid, session), _lra, target in zip(
        resolved, lras, targets, strict=True
    ):
        params = req.parameters.model_copy(update={"target_lufs_db": target})
        output_path = (
            settings.output_dir / f"{sid}_album_mastered.wav"
        ).resolve()
        try:
            result = await asyncio.get_running_loop().run_in_executor(
                _dsp_executor, _run_track_processing, session, params, output_path
            )
        except Exception as e:
            # Preserve the failure (type + message, e.g. IOError,
            # InputQcError) and keep mastering the rest of the album.
            tracks.append(
                AlbumProcessTrack(
                    session_id=sid,
                    original_filename=session.original_filename,
                    negotiated_target_lufs_db=target,
                    within_tolerance=False,
                    warnings=[f"{type(e).__name__}: {e}"],
                )
            )
            continue

        # Replace semantics — mirrors POST /api/session/{id}/process.
        session.mastered_path = result.get("output_path") or str(output_path)
        session.parameters = params
        session.master_result = _master_result_from_engine(result)
        session.mastering_report = _mastering_report_from_engine(result)
        session.status = ProcessingStatus.COMPLETED
        session.progress = 1.0
        session.error = None

        output_lufs = result.get("integrated_lufs")
        deviation = (
            round(float(output_lufs) - target, 1)
            if output_lufs is not None and target is not None
            else None
        )
        warnings: list[str] = []
        within = True
        if deviation is not None and abs(deviation) > ALBUM_LUFS_TOLERANCE_DB:
            within = False
            direction = "más alto" if deviation > 0 else "más bajo"
            warnings.append(
                f"El master quedó {abs(deviation):.1f} LUFS {direction} "
                f"que el objetivo del álbum ({target:g} LUFS)"
            )
        # Carry the engine's own delivery warnings (Spanish, neutral Latin American).
        warnings.extend(result.get("warnings", []) or [])

        tracks.append(
            AlbumProcessTrack(
                session_id=sid,
                original_filename=session.original_filename,
                negotiated_target_lufs_db=target,
                output_lufs_db=output_lufs,
                output_lra_lu=result.get("lra"),
                output_crest_db=result.get("crest_factor_db"),
                output_true_peak_dbtp=result.get("true_peak_db"),
                lufs_deviation_db=deviation,
                within_tolerance=within,
                warnings=warnings,
            )
        )

    # Single persistence point after ALL tracks (one disk write per album).
    save_sessions(sessions)

    return AlbumProcessResult(
        target_base_lufs_db=base,
        lra_median_lu=round(median, 2) if median is not None else None,
        tracks=tracks,
    )