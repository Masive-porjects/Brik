"""Mastering API endpoints."""
from pathlib import Path
import asyncio
import logging
import shutil
import time
import uuid
import urllib.parse
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Any
import numpy as np
import soundfile as sf

from audiomind.config import settings
from audiomind.models.audio import (
    AnalysisResult,
    MasteringParameters,
    MasteringReport,
    MasterResultMetrics,
    MasterSource,
    PresetMasterEntry,
    ProcessingStatus,
    ReferenceComparison,
    ReferenceRenderResult,
    ReferenceUploadResult,
    SessionData,
    ValidationReport,
)
from audiomind.services import demo_guard, storage
from audiomind.session_store import save_sessions
from audiomind.api.upload import sessions
# Heavy DSP modules (librosa/pedalboard) are imported lazily inside the
# functions that use them so FastAPI startup stays light and fast on
# low-memory deployments (Railway 1GB) — see OOM/timeout mitigation.
from audiomind.processing.presets import PRESET_CHAINS
from audiomind.processing.validation import validate_master
from audiomind.api.license import require_license

# Lazy module-level names for the heavy DSP entry points.
#
# ``process_audio`` and ``analyze_audio`` ARE real module attributes,
# bound to thin wrappers that import the actual implementation on FIRST
# CALL. This keeps the historic namespace contract — call sites and tests
# reference ``mastering_mod.process_audio`` / ``analyze_audio``, and
# monkeypatched names at either level take effect:
#   * patching ``mastering_mod.process_audio`` replaces the wrapper itself,
#   * patching ``audiomind.analysis.analyzer.analyze_audio`` (the source
#     module) is seen by the stateless wrapper, which late-binds on every
#     call (importlib on an already-loaded module is a dict lookup).
# Importing this module still never pulls in librosa/pedalboard/engine —
# only an actual DSP call does (preserves the lazy-load OOM mitigation).
def _lazy_dsp_call(module_name: str, attr: str) -> Callable[..., Any]:
    """Return a wrapper that late-imports ``module_name.attr`` per call."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        import importlib

        impl = getattr(importlib.import_module(module_name), attr)
        return impl(*args, **kwargs)

    return wrapper


process_audio: Callable[..., dict[str, Any]] = _lazy_dsp_call(
    "audiomind.processing.engine", "process_audio"
)
analyze_audio: Callable[..., AnalysisResult | None] = _lazy_dsp_call(
    "audiomind.analysis.analyzer", "analyze_audio"
)
compare_tracks: Callable[..., ReferenceComparison] = _lazy_dsp_call(
    "audiomind.analysis.reference_compare", "compare_tracks"
)

router = APIRouter()

logger = logging.getLogger(__name__)

# Thread pool for CPU-bound DSP — keeps the FastAPI event loop free
# so progress polling and other requests remain responsive during processing.
_dsp_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dsp")

# Separate executor for pre-rendering all presets in parallel after upload.
# Uses 8 workers (one per preset) so all presets process concurrently.
# 1 worker: DSP jobs are heavy (librosa + pedalboard + 8x/16x oversampling)
# and Railway demos run on 1GB RAM — parallel presets risk OOM.
_prerender_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="prerender")

# Engine's default proportional-processing intensity (see
# ``process_audio`` signature). The Layer 2 auto-retry scales it down once.
_BASE_INTENSITY_MULTIPLIER = 1.8

# ── Pre-render cache: stores results for all presets ────────────────
# Structure: {session_id: {preset_id: {"output_path", "master_result",
# "validation", "status", "progress", "error"}}}
# Status per preset: "pending" | "processing" | "completed" | "error"
_prerender_cache: dict[str, dict[str, dict[str, Any]]] = {}


def _build_preset_params(preset_id: str) -> MasteringParameters:
    """Build MasteringParameters from a PRESET_CHAINS entry for pre-rendering.

    Uses the preset's loudness/ceiling targets and character defaults.
    Custom user slider overrides are NOT applied — pre-render uses the
    canonical preset values so the result is always "factory default".
    """
    entry = PRESET_CHAINS[preset_id]
    comp = entry.get("compressor", {})
    return MasteringParameters(
        clarity_wet=0.15 if entry.get("eq_character") == "brillante" else 0.1,
        clarity_brightness_db=1.0 if entry.get("eq_character") == "brillante" else 0.5,
        compression_ratio=comp.get("ratio", 2.0),
        limiter_ceiling_db=entry.get("limiter_ceiling_db", -1.0),
        transient_boost_db=1.0 if entry.get("eq_character") == "punch" else 0.5,
        saturation_drive_db=entry.get("saturation", {}).get("drive_max", 0) if entry.get("saturation") else 0.0,
        saturation_warmth_db=1.0 if entry.get("saturation") else 0.0,
        # Declared stereo_width wins (espacial ships 1.4); the legacy
        # fallback (1.2 for spatial presets, 1.0 otherwise) keeps claridad
        # unchanged and gives cinematico (no spatial flag) width 1.0.
        stereo_width=entry.get("stereo_width", 1.2 if entry.get("spatial") else 1.0),
        haas_delay_ms=5.0 if entry.get("spatial") else 0.0,
        eq_bands=entry.get("eq_bands", []),
        output_bit_depth=24,
        target_lufs_db=entry.get("target_lufs"),
    )


def _prerender_single_preset(
    session_id: str,
    preset_id: str,
    input_path: str,
    analysis: AnalysisResult | None,
) -> None:
    """Process a single preset and store the result in _prerender_cache.

    Runs inside _prerender_executor — one thread per preset.
    """
    cache = _prerender_cache.get(session_id, {})
    entry = cache.get(preset_id, {})
    entry["status"] = "processing"
    entry["progress"] = 0.0

    try:
        params = _build_preset_params(preset_id)
        output_path = (
            settings.output_dir / f"{session_id}_{preset_id}_mastered.wav"
        ).resolve()

        def update_progress(pct: float) -> None:
            entry["progress"] = max(0.0, min(1.0, pct))

        result = process_audio(
            input_path=input_path,
            output_path=output_path,
            params=params,
            analysis_result=analysis,
            intensity_multiplier=_BASE_INTENSITY_MULTIPLIER,
            progress_cb=update_progress,
        )

        entry["output_path"] = str(output_path)
        entry["master_result"] = _master_result_from_engine(result)
        entry["progress"] = 1.0

        # Best-effort validation
        preset_entry = PRESET_CHAINS.get(preset_id)
        if preset_entry is not None:
            try:
                verdict = validate_master(
                    entry["master_result"], preset_entry, analysis
                )
                if verdict is not None:
                    entry["validation"] = ValidationReport(**verdict)
            except Exception:
                pass

        entry["status"] = "completed"
    except Exception as e:
        entry["status"] = "error"
        entry["error"] = str(e)
        entry["progress"] = 0.0


def _prerender_all_presets(
    session_id: str,
    input_path: str,
    analysis: AnalysisResult | None,
) -> None:
    """Launch pre-rendering of all presets in parallel (background task).

    Called after upload/analysis completes. Each preset runs in its own
    thread via _prerender_executor. Results are stored in _prerender_cache.
    """
    _prerender_cache[session_id] = {}
    for preset_id in PRESET_CHAINS:
        _prerender_cache[session_id][preset_id] = {
            "status": "pending",
            "progress": 0.0,
            "output_path": None,
            "master_result": None,
            "validation": None,
            "error": None,
        }
        _prerender_executor.submit(
            _prerender_single_preset,
            session_id,
            preset_id,
            input_path,
            analysis,
        )
_RETRY_INTENSITY_SCALE = 0.8


class StatelessMasterRequest(BaseModel):
    """Body for the stateless mastering endpoint (no session)."""

    audio_url: str
    settings: MasteringParameters


class MasterInput(NamedTuple):
    """The single audio file one ``/process`` run must consume.

    ``source`` is the resolved decision (``original`` | ``mix``) and
    ``input_path`` the file it points at. Every step of the run — the
    existence check, ``analyze_audio`` and the engine's ``input_path`` —
    reads this, so the delivered master always comes from the SELECTED
    input (feature ``odd/tasks/mix-master-flow.md``).

    ``mix_metadata`` carries the Mix→Master handshake metadata when
    ``source == "mix"``, enabling adaptive mastering based on the
    actual mix state (spatial width, side energy, stem LUFS, headroom).
    """

    source: MasterSource
    input_path: str
    mix_metadata: dict | None = None


def _mix_is_deliverable(session: SessionData) -> bool:
    """Whether a ``completed`` mix still has bytes we can master.

    Local file first (fast path, no network), otherwise the durable R2 key.

    Checking only ``mix_path`` used to be the whole test, and that is exactly
    why a redeployed container silently mastered the ORIGINAL instead of the
    delivered mix: the mix was fine and sitting in R2, the local copy was gone,
    and the user got a master of the wrong audio with no error at all.
    """
    if session.mix_path and Path(session.mix_path).exists():
        return True
    return bool(session.mix_r2_key)


async def _hydrate_mix_from_r2(session: SessionData) -> str | None:
    """Re-download the delivered mix from R2 when the local file is gone.

    Returns the local path of the rehydrated WAV, or ``None`` when the bytes
    cannot be recovered (no key recorded, object absent, R2 unreachable, or no
    credentials). Callers read ``None`` as "this mix is not deliverable" and
    keep the honest error -- never a silent fall back to the original.

    The download runs on a worker thread: it is network I/O, and blocking the
    event loop on it is the exact failure this whole async-job design exists
    to avoid. Deliberately NOT ``_dsp_executor``: a download must not occupy a
    slot reserved for CPU-bound DSP on a single-worker container.
    """
    key = session.mix_r2_key
    if not key:
        return None

    target = (settings.output_dir / f"{session.session_id}_mix_from_r2.wav").resolve()
    try:
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(storage.download_to, key, str(target))
    except (storage.StorageError, OSError) as exc:
        logger.warning(
            "Could not rehydrate the mix for session %s from R2 key %s: %s",
            session.session_id,
            key,
            exc,
        )
        return None

    # An empty or truncated download would sail through exists() and then fail
    # deep inside the DSP chain with a confusing codec error. Refuse it here.
    try:
        size = target.stat().st_size
    except OSError as exc:  # pragma: no cover - stat on a just-written file
        logger.warning(
            "Rehydrated mix for %s is unreadable: %s", session.session_id, exc
        )
        return None
    if size <= 0:
        logger.warning(
            "R2 returned an empty mix for session %s (key %s)", session.session_id, key
        )
        return None

    # Cache the recovered pointer so the next master run is a plain local read
    # and the session is self-healing across further requests.
    session.mix_path = str(target)
    save_sessions(sessions)
    logger.info(
        "Rehydrated mix for session %s from R2 key %s (%d bytes)",
        session.session_id,
        key,
        size,
    )
    return str(target)


async def _persist_master_to_r2(
    session: SessionData,
    path: str | Path | None,
    *,
    preset_id: str | None = None,
) -> str | None:
    """Upload a mastered WAV to R2 and record the durable key on the session.

    Returns the key on success and ``None`` on ANY failure. It never raises:
    the master already exists on the local disk, and R2 is only the insurance
    that survives a Railway redeploy. Turning an R2 outage into a failed
    mastering request would be a regression (the user already has the file),
    and silently swallowing it is the documented policy of the mix twin
    ``_record_mix_on_session``.

    Which pointers get stamped:

    * ``preset_id`` given → that entry's ``r2_key``, so a later
      ``?preset_id=`` lookup can re-hydrate.
    * always → ``session.master_r2_key``, because ``mastered_path`` is a
      SEPARATE pointer that must stay independently durable.

    When both point at the very file uploaded here (the preset on-demand
    path), this is ONE PUT and both keys point at it — two R2 writes for one
    object would be waste. ``output_path``/``mastered_path`` are never set
    here: the call sites own their naming.

    The PUT runs on a worker thread. Sites 2/3/5 are async and a blocking
    upload would stall the single event-loop worker of the container.
    """
    if not path:
        return None
    source = Path(path)
    if not source.exists():
        logger.warning(
            "Skipping the R2 upload of the master for session %s: %s is gone",
            session.session_id,
            source,
        )
        return None

    key = (
        storage.build_key(
            "masters", session.session_id, f"{preset_id}_mastered.wav"
        )
        if preset_id
        else storage.build_key(
            "masters", session.session_id, f"{session.session_id}_mastered.wav"
        )
    )
    try:
        await asyncio.to_thread(
            storage.upload_file, str(source), key, content_type="audio/wav"
        )
    except Exception as exc:
        # Local pointers keep their values: the master is deliverable on THIS
        # container, and a redeploy may then lose it (an honest 404 later).
        logger.warning(
            "Master %s for session %s was not persisted to R2 key %s: %s",
            source.name,
            session.session_id,
            key,
            exc,
        )
        return None

    if preset_id:
        # Only stamp an entry that already exists: inventing a pending one
        # would advertise a master the client never received.
        entry = session.preset_masters.get(preset_id)
        if entry is not None:
            entry.r2_key = key
    session.master_r2_key = key
    save_sessions(sessions)
    logger.info("Master for session %s persisted to R2 key %s", session.session_id, key)
    return key


def _master_hydration_target(session: SessionData, preset_id: str | None) -> Path:
    """Deterministic local filename for a re-hydrated master (D4).

    Derived from the session id and the preset, never from the dead path
    string, so it matches the production naming
    (``{sid}_{preset_id}_mastered.wav`` / ``{sid}_mastered.wav``) instead of
    trying to revive a filename that may contain characters no session id has.
    """
    if preset_id:
        name = f"{session.session_id}_{preset_id}_mastered_from_r2.wav"
    else:
        name = f"{session.session_id}_mastered_from_r2.wav"
    return (settings.output_dir / name).resolve()


async def _resolve_master_file(
    session: SessionData,
    preset_id: str | None,
    *,
    missing_detail: str,
    missing_status: int = 404,
) -> Path:
    """Return a local, readable path for the requested master.

    Every endpoint that serves a master routes through here, so the
    re-hydration logic exists once. Precedence is exactly what the endpoints
    implemented on their own: with a ``preset_id`` only that entry counts
    (an unknown preset never falls back to ``mastered_path``); without one,
    the legacy ``mastered_path`` pointer.

    A master whose local file vanished on a redeploy is re-downloaded from the
    durable R2 key (the master-side twin of ``_hydrate_mix_from_r2``), then
    the recovered pointer is cached on the session so the next request is a
    plain local read.

    ``missing_detail``/``missing_status`` keep each caller's existing answer
    for "this master never existed" (the wording and the status the endpoint
    already used). An EXISTING master that cannot be re-hydrated is a
    different failure — the resource is gone, the request is fine — so it is
    always a 404 naming the key and the real reason.
    """
    entry = session.preset_masters.get(preset_id) if preset_id else None
    if preset_id:
        pointer = entry.output_path if entry is not None else None
        key = entry.r2_key if entry is not None else None
        label = f"preset '{preset_id}'"
    else:
        pointer = session.mastered_path
        key = session.master_r2_key
        label = "master"

    if pointer and Path(pointer).exists():
        return Path(pointer)

    if not key:
        raise HTTPException(status_code=missing_status, detail=missing_detail)

    target = _master_hydration_target(session, preset_id)
    try:
        settings.output_dir.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(storage.download_to, key, str(target))
        size = target.stat().st_size
    except (storage.StorageError, OSError) as exc:
        logger.warning(
            "Could not rehydrate the %s of session %s from R2 key %s: %s",
            label,
            session.session_id,
            key,
            exc,
        )
        raise HTTPException(
            status_code=404,
            detail=(
                f"The {label} of session {session.session_id} is not recoverable: "
                f"its local file is missing and the R2 key {key!r} could not be "
                f"downloaded ({exc}). Re-run POST /session/{{id}}/process."
            ),
        ) from exc

    # An empty object would sail past the existence check and then fail deep
    # inside the codec, so it is treated as unrecoverable, never served.
    if size <= 0:
        logger.warning(
            "R2 returned an empty master for session %s (key %s)",
            session.session_id,
            key,
        )
        target.unlink(missing_ok=True)
        raise HTTPException(
            status_code=404,
            detail=(
                f"The {label} of session {session.session_id} is not recoverable: "
                f"its local file is missing and the R2 key {key!r} holds an empty "
                "object. Re-run POST /session/{id}/process."
            ),
        )

    # Cache the recovered pointer so the next request is a plain local read.
    if entry is not None:
        entry.output_path = str(target)
    # ``mastered_path`` is repaired too when the key just fetched is its OWN
    # durable pointer (the preset paths stamp both from one upload), so a
    # preset lookup also un-breaks the legacy pointer. Never otherwise: a
    # different key means different bytes.
    if not preset_id or key == session.master_r2_key:
        session.mastered_path = str(target)
    save_sessions(sessions)
    logger.info(
        "Rehydrated the %s of session %s from R2 key %s (%d bytes)",
        label,
        session.session_id,
        key,
        size,
    )
    return target


async def _resolve_master_input(
    session: SessionData, source: MasterSource | None
) -> MasterInput:
    """Resolve which file ``/process`` must master for this session.

    ``source=None`` (the default) is the SMART resolution: the mix wins
    only when it is genuinely deliverable -- ``mix_status == "completed"``
    AND its bytes are reachable (local file, or the durable R2 key that
    ``_hydrate_mix_from_r2`` can re-fetch). Otherwise the uploaded original.
    Any client that does not know about mixes (older builds) therefore keeps
    the historic behavior.

    An explicit ``source="mix"`` on a session that never completed a mix
    is a REQUEST error (400) with the real state in the message, not a
    silent fallback to the original: asking for the mix and getting the
    original back would be a lie.

    ``async`` because recovering a mix that only exists in R2 is a network
    round trip. Refusing instead would make every delivered mix unmasterable
    after a redeploy, which is precisely the deployment we run on.
    """
    if source is None:
        resolved: MasterSource = "original"
        if session.mix_status == "completed" and _mix_is_deliverable(session):
            resolved = "mix"
    else:
        resolved = source
        if resolved == "mix" and session.mix_status != "completed":
            raise HTTPException(
                status_code=400,
                detail=(
                    f"source='mix' requires a completed mix, but mix_status="
                    f"'{session.mix_status}'. Run POST /session/{{id}}/mix "
                    "first and wait for mix_status='completed'."
                ),
            )

    if resolved == "mix":
        local: str | None = (
            session.mix_path
            if session.mix_path and Path(session.mix_path).exists()
            else None
        )
        if local is None:
            # A ``completed`` mix whose local copy vanished (redeploy, cleaned
            # volume) is still recoverable from R2.
            local = await _hydrate_mix_from_r2(session)
        if local is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "source='mix' but the mix is not recoverable "
                    f"(mix_status='{session.mix_status}', local file missing, "
                    f"R2 key {'present' if session.mix_r2_key else 'absent'}). "
                    "Re-run the mix."
                ),
            )
        return MasterInput(
            source="mix",
            input_path=local,
            mix_metadata=session.mix_metadata,
        )

    return MasterInput(source="original", input_path=str(session.original_path or ""))


def _master_result_from_engine(result: dict[str, Any]) -> MasterResultMetrics:
    """Map the engine result dict onto the response model.

    Uses ``.get()`` so partial/stubbed engine results never raise —
    missing keys simply stay null.
    """
    return MasterResultMetrics(
        integrated_lufs=result.get("integrated_lufs"),
        true_peak_db=result.get("true_peak_db"),
        crest_factor_db=result.get("crest_factor_db"),
        limiter_ceiling_db=result.get("limiter_ceiling_db"),
        duration_seconds=result.get("duration_seconds"),
        sample_rate=result.get("sample_rate"),
        output_bit_depth=result.get("output_bit_depth"),
        stereo_correlation=result.get("stereo_correlation"),
        lra=result.get("lra"),
    )


def _mastering_report_from_engine(result: dict[str, Any]) -> MasteringReport:
    """Build the delivery compliance report from an engine result dict.

    Same ``.get()`` discipline as ``_master_result_from_engine``: stubbed
    or partial engine results yield an all-null report, never a raise.
    """
    return MasteringReport(
        input_sr=result.get("input_sr"),
        output_sr=result.get("output_sr"),
        output_bit_depth=result.get("output_bit_depth"),
        lufs_i=result.get("integrated_lufs"),
        true_peak_dbtp=result.get("true_peak_db"),
        lra=result.get("lra"),
        crest_factor_db=result.get("crest_factor_db"),
        stereo_correlation=result.get("stereo_correlation"),
        target_lufs=result.get("target_lufs"),
        warnings=result.get("warnings", []),
    )


def _measure_master_file(path: Path) -> MasterResultMetrics:
    """Best-effort measured metrics for a cached/pre-built master.

    Reuses the project's existing BS.1770 LUFS meter plus the same
    sample-peak/crest math as ``analyze_audio`` — no new DSP work.
    Any failure (corrupt file, decode error) returns an all-null model;
    measurements must never break a cache-hit response.
    """
    try:
        from audiomind.processing.loudness import measure_lufs
        from audiomind.processing.spatial import measure_stereo_correlation

        audio, sr = sf.read(str(path), dtype="float32", always_2d=True)
        mono = audio.mean(axis=1)
        lufs = measure_lufs(audio.T, sr)
        peak = float(np.max(np.abs(mono)))
        true_peak_db = 20 * np.log10(max(peak, 1e-10))
        rms = float(np.sqrt(np.mean(mono**2)))
        crest = 20 * np.log10(peak / rms) if rms > 0 else 0.0
        corr = (
            measure_stereo_correlation(audio.T)
            if audio.shape[1] == 2
            else None
        )
        return MasterResultMetrics(
            integrated_lufs=round(float(lufs), 1),
            true_peak_db=round(true_peak_db, 1),
            crest_factor_db=round(crest, 1),
            stereo_correlation=round(corr, 3) if corr is not None else None,
        )
    except Exception:
        return MasterResultMetrics()


def _resolve_preset_entry(preset_id: str | None) -> dict[str, Any] | None:
    """Active preset chain entry, or None when there is no preset target."""
    if preset_id and preset_id in PRESET_CHAINS:
        return PRESET_CHAINS[preset_id]
    return None


def _reference_output_path(session_id: str, preset_id: str) -> Path:
    """Session-scoped reference file, built like the mastered output path."""
    return (settings.output_dir / f"{session_id}_reference_{preset_id}.wav").resolve()


def _build_reference_params(preset_entry: dict[str, Any]) -> MasteringParameters:
    """Neutral-chain parameters for the Crudo reference render.

    Character comes from ``PRESET_CHAINS["natural"]`` — no EQ bands,
    gentle 1.1:1 compression, no saturation, no spatial processing.
    Loudness (``target_lufs_db`` + ``limiter_ceiling_db``) is overridden
    with the active preset's values so the reference lands at the same
    perceived loudness as the master: the ear judges character, not volume.
    """
    natural = PRESET_CHAINS["natural"]
    return MasteringParameters(
        clarity_wet=0.0,
        clarity_brightness_db=0.0,
        compression_ratio=natural["compressor"]["ratio"],
        limiter_ceiling_db=preset_entry.get("limiter_ceiling_db", -1.0),
        transient_boost_db=0.0,
        saturation_drive_db=0.0,
        saturation_warmth_db=0.0,
        stereo_width=1.0,
        haas_delay_ms=0.0,
        output_bit_depth=24,
        target_lufs_db=preset_entry.get("target_lufs"),
    )


def _lufs_distance(lufs: float | None, target: float) -> float:
    """Absolute distance to the LUFS target; unmeasurable never wins."""
    if lufs is None:
        return float("inf")
    return abs(lufs - target)


def _retry_once_on_lufs_miss(
    result: dict[str, Any],
    session: SessionData,
    params: MasteringParameters,
    output_path: Path,
    preset_entry: dict[str, Any],
    progress_cb: Callable[[float], None],
    master_input: MasterInput,
    analysis: AnalysisResult | None,
) -> tuple[dict[str, Any], bool]:
    """Single bounded auto-retry at reduced engine intensity.

    Trigger: a LUFS-miss issue on the first attempt. The retry writes to
    a sibling temp file (attempt 1 stays restorable) and the attempt
    closest to the preset LUFS target wins. Hard cap: ONE retry.
    Returns ``(final_result, retried)``.

    The retry re-reads the SAME selected input (and the same analysis) as
    the first attempt, so a mix master never falls back to the original.
    """
    target_lufs = preset_entry.get("target_lufs")
    if target_lufs is None:
        return result, False

    first_verdict = validate_master(
        _master_result_from_engine(result), preset_entry, analysis
    )
    if not any(
        issue["metric"] == "lufs" for issue in (first_verdict or {}).get("issues", [])
    ):
        return result, False

    first_miss = _lufs_distance(result.get("integrated_lufs"), target_lufs)
    retry_output = output_path.with_name(f"{output_path.stem}_retry.wav")
    try:
        retry_result = process_audio(
            input_path=master_input.input_path,
            output_path=retry_output,
            params=params,
            analysis_result=analysis,
            intensity_multiplier=_BASE_INTENSITY_MULTIPLIER * _RETRY_INTENSITY_SCALE,
            progress_cb=progress_cb,
        )
    except Exception:
        # Retry failed — keep attempt 1; the one-retry cap is consumed.
        retry_output.unlink(missing_ok=True)
        return result, False

    retry_path = Path(retry_result.get("output_path", str(retry_output)))
    if _lufs_distance(retry_result.get("integrated_lufs"), target_lufs) < first_miss:
        # Retry wins → adopt it as the session master
        retry_path.replace(output_path)
        return {**retry_result, "output_path": str(output_path)}, True

    retry_path.unlink(missing_ok=True)
    return result, False


async def _process_preset_on_demand(
    session: SessionData,
    session_id: str,
    params: MasteringParameters,
    preset_id: str,
    master_input: MasterInput,
    analysis: AnalysisResult | None,
) -> SessionData:
    """Run (or join) the single-flighted heavy DSP job for one preset.

    Single-flight contract for ``POST /session/{id}/process?preset_id=X``:

    * CASE 1 — nothing recorded yet: create the flight Future, submit the
      job to the gated pool, await it.
    * CASE 2 — preset already completed with an existing file: return the
      session state for that preset. NO DSP. Only valid for the ORIGINAL
      source: that cache holds masters of the uploaded track, so a mix
      master always runs the engine (see ``master_input``).
    * CASE 3 — flight in progress for (session, preset): await the SAME
      Future; never a second heavy pipeline.
    * CASE 4 — flight in progress for a DIFFERENT preset: the new job
      queues on the global DSP gate and runs after the first finishes
      (``max_concurrent_dsp=1`` serializes). The HTTP call may wait —
      that is documented demo behavior, never a 500.

    Errors keep the legacy mapping: ``InputQcError`` → 422 (the session
    keeps its current state); anything else → 500 with the session marked
    ERROR.
    """
    # CASE 2 — already-mastered preset with a file on disk: serve it.
    entry = session.preset_masters.get(preset_id)
    if (
        master_input.source == "original"
        and entry is not None
        and entry.status == "completed"
        and entry.output_path
        and Path(entry.output_path).exists()
    ):
        session.mastered_path = entry.output_path
        session.master_result = entry.master_result
        session.validation = entry.validation
        session.status = ProcessingStatus.COMPLETED
        session.progress = 1.0
        session.error = None
        return session

    output_path = (
        settings.output_dir / f"{session_id}_{preset_id}_mastered.wav"
    ).resolve()

    def _job() -> None:
        with demo_guard.gate():
            _run_preset_job(
                session=session,
                session_id=session_id,
                params=params,
                preset_id=preset_id,
                output_path=output_path,
                master_input=master_input,
                analysis=analysis,
            )

    # CASE 1 / CASE 3 — create or join the shared flight future.
    future = demo_guard.get_or_create_flight(session_id, preset_id, _job)
    try:
        await asyncio.wrap_future(future)
    except Exception as e:
        from audiomind.processing.engine import InputQcError

        if isinstance(e, InputQcError):
            # Request rejection, not a processing failure: the session
            # keeps its current state (mirrors the legacy path).
            raise HTTPException(status_code=422, detail=str(e)) from e
        session.status = ProcessingStatus.ERROR
        session.error = f"Processing failed: {str(e)}"
        raise HTTPException(status_code=500, detail=session.error) from e

    # The job ran in a worker thread, so the durable R2 pointer is written
    # here, from async context. The preset entry and ``mastered_path`` share
    # one file here, so this single call stamps BOTH keys from ONE upload.
    if session.preset_masters.get(preset_id) is not None:
        entry_path = session.preset_masters[preset_id].output_path
        if entry_path and session.mastered_path == entry_path:
            await _persist_master_to_r2(session, entry_path, preset_id=preset_id)
    return session


def _run_preset_job(
    session: SessionData,
    session_id: str,
    params: MasteringParameters,
    preset_id: str,
    output_path: Path,
    master_input: MasterInput,
    analysis: AnalysisResult | None,
) -> None:
    """Heavy DSP + bookkeeping for one preset (runs in a gated pool thread).

    Analysis is produced here when the upload-time background analysis is
    missing (the engine tolerates ``analysis_result=None`` with safe
    defaults, mirroring the legacy /process path). ``master_input`` decides
    WHICH file is read and analyzed, so the preset master is always a
    master of the selected source.
    """
    # Meter: this is the ONLY place the heavy pipeline runs, so the count
    # is the authoritative "DSP executions" evidence for demo validation.
    demo_guard.record_dsp_execution()
    if analysis is None and session.status != ProcessingStatus.ANALYZING:
        try:
            analysis = analyze_audio(master_input.input_path)
            if analysis is not None:
                # ``session.analysis`` describes the UPLOADED original and is
                # read by compare-reference / validation / metrics: a mix
                # master never overwrites it.
                if master_input.source == "original":
                    session.analysis = analysis
        except Exception:
            pass  # analysis is optional; the engine handles None safely

    entry = session.preset_masters.setdefault(
        preset_id, PresetMasterEntry(preset_id=preset_id)
    )
    entry.status = "processing"
    entry.progress = 0.0
    entry.error = None
    session.status = ProcessingStatus.PROCESSING
    session.progress = 0.0

    def update_progress(pct: float) -> None:
        session.progress = max(0.0, min(1.0, pct))
        entry.progress = max(0.0, min(1.0, pct))

    try:
        result = process_audio(
            input_path=master_input.input_path,
            output_path=output_path,
            params=params,
            analysis_result=analysis,
            progress_cb=update_progress,
            mix_metadata=master_input.mix_metadata,
        )

        # ── Layer 2 gate: validate against the preset, with at most ONE
        # auto-retry at reduced intensity on LUFS misses (legacy semantics).
        preset_entry = PRESET_CHAINS[preset_id]
        retried = False
        try:
            result, retried = _retry_once_on_lufs_miss(
                result=result,
                session=session,
                params=params,
                output_path=output_path,
                preset_entry=preset_entry,
                progress_cb=update_progress,
                master_input=master_input,
                analysis=analysis,
            )
        except Exception:
            retried = False

        master_result = _master_result_from_engine(result)
        validation: ValidationReport | None = None
        try:
            verdict = validate_master(
                master_result, preset_entry, analysis
            )
            if verdict is not None:
                if retried:
                    verdict["retry_applied"] = True
                    verdict["note"] = (
                        "Reintento automático con menor intensidad; "
                        "se conservó el intento más cercano al objetivo."
                    )
                validation = ValidationReport(**verdict)
        except Exception:
            validation = None

        entry.output_path = str(output_path)
        entry.master_result = master_result
        entry.validation = validation
        entry.status = "completed"
        entry.progress = 1.0
        entry.created_at = time.time()

        # Legacy pointers stay in sync so existing consumers keep working:
        # mastered_path is the "last processed / currently selected
        # available master" pointer.
        session.mastered_path = str(output_path)
        session.master_result = master_result
        session.validation = validation
        session.mastering_report = _mastering_report_from_engine(result)
        session.parameters = params
        session.status = ProcessingStatus.COMPLETED
        session.progress = 1.0
        session.error = None
    except Exception as e:
        # The async wrapper maps InputQcError → 422 keeping the session
        # state untouched (REQUEST rejection); other failures are marked
        # on both the per-preset entry and the session (→ 500).
        from audiomind.processing.engine import InputQcError

        if not isinstance(e, InputQcError):
            entry.status = "error"
            entry.error = str(e)
            entry.progress = 0.0
            session.status = ProcessingStatus.ERROR
            session.error = f"Processing failed: {str(e)}"
        raise

    demo_guard.touch(session_id)
    save_sessions(sessions)


@router.post("/session/{session_id}/process")
async def process_session(
    session_id: str,
    params: MasteringParameters,
    preset_id: str | None = Query(default=None, description="Preset ID for pre-built lookup"),
    source: MasterSource | None = Query(
        default=None,
        description=(
            "Which audio file to master: 'original' (uploaded track) or "
            "'mix' (Mix Engine output). Omitted = smart: 'mix' when the mix "
            "is completed and on disk, else 'original'."
        ),
    ),
    _: object = Depends(require_license),
) -> SessionData:
    """Process a session with the given mastering parameters.

    If ``preset_id`` is provided and a pre-built master exists for the
    uploaded track + preset, the cached WAV is served directly — no DSP
    pipeline runs. This makes the demo feel instant (~1–2s instead of
    ~44s for a 3-min track).

    ``source`` selects the file the whole chain consumes (existence check,
    analysis and DSP input), so the Mix → Master flow can master the
    delivered mix instead of always the upload:

    * omitted → smart default: the mix only when it is ``completed`` and
      its file exists, otherwise the original (unchanged for clients that
      never mix);
    * ``source=mix`` without a completed mix → 400 naming the real state
      (never a silent fallback to the original);
    * ``source=original`` → the historic behavior, bit-for-bit.

    The pre-built / pre-render caches hold masters of the UPLOADED track,
    so they are shortcuts for the original source only; a mix master
    always runs the engine. Response shape is unchanged.
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Which file this run consumes (raises 400 on source=mix without a
    # recoverable mix) — resolved before ANY read so the existence check,
    # the analysis and the engine all agree.
    master_input = await _resolve_master_input(session, source)

    if not master_input.input_path or not Path(master_input.input_path).exists():
        raise HTTPException(
            status_code=400, detail="No audio file found for this session"
        )

    # Demo duration guard (defensive, API layer only — DSP untouched):
    # the upload endpoint rejects overlength files first; this catches
    # sessions restored from disk, analyzed later, or created outside
    # /api/upload. Applies to preset AND no-preset paths alike.
    if demo_guard.duration_over_limit(
        session.analysis.duration_seconds if session.analysis else None
    ):
        raise HTTPException(
            status_code=422,
            detail=demo_guard.demo_duration_message(
                settings.demo_max_duration_seconds
            ),
        )

    # Analysis of the SELECTED input. ``session.analysis`` always describes
    # the UPLOADED original (compare-reference, validation and metrics read
    # it), so a mix run analyzes the mix into a LOCAL and leaves the session
    # field untouched. The original flow below is unchanged: it only fills
    # ``session.analysis`` when it is missing.
    selected_analysis: AnalysisResult | None = session.analysis
    if master_input.source == "mix":
        try:
            selected_analysis = await asyncio.get_running_loop().run_in_executor(
                _dsp_executor, analyze_audio, master_input.input_path
            )
        except Exception as e:
            session.status = ProcessingStatus.ERROR
            session.error = f"Analysis failed: {str(e)}"
            raise HTTPException(status_code=500, detail=session.error) from e

    output_path = settings.output_dir / f"{session_id}_mastered.wav"
    output_path = output_path.resolve()

    # ── Pre-built lookup: serve cached master instantly ────── */
    # Both cache shortcuts below are ORIGINAL-only: the pre-built WAV and
    # the pre-rendered presets are masters of the UPLOADED track, so
    # serving them for source=mix would return a master of the wrong file.
    original_source = master_input.source == "original"
    if preset_id and original_source:
        # Key by the ORIGINAL filename (e.g. "mi_tema_fuego.wav"), since the
        # stored file is renamed to the session id. Falls back to the stored
        # path stem for sessions created before original_filename existed
        # (``master_input.input_path`` IS the original path in this branch).
        original_stem = (
            Path(session.original_filename).stem
            if session.original_filename
            else Path(master_input.input_path).stem
        )
        prebuilt_file = settings.prebuilt_dir / f"{original_stem}_{preset_id}.wav"
        # A mastered WAV is always > 1 KiB; smaller files are broken stubs
        # and must never be served as a master.
        if prebuilt_file.exists() and prebuilt_file.stat().st_size > 1024:
            # Copy pre-built master into session output dir
            shutil.copy2(prebuilt_file, output_path)
            session.mastered_path = str(output_path)
            session.parameters = params
            session.status = ProcessingStatus.COMPLETED
            session.progress = 1.0
            session.error = None
            # Best-effort measurements on the cached file (nulls on failure)
            session.master_result = _measure_master_file(output_path)
            # Layer 2 verdict — cache hits are never reprocessed, so a
            # warning here only informs (retry_recommended, no auto-retry).
            preset_entry = _resolve_preset_entry(preset_id)
            if preset_entry is not None:
                try:
                    verdict = validate_master(
                        session.master_result, preset_entry, session.analysis
                    )
                    if verdict is not None:
                        session.validation = ValidationReport(**verdict)
                except Exception:
                    session.validation = None  # never break a cache hit
            # Record the per-preset result so ?preset_id= lookups and the
            # per-preset download/audio endpoints work for this session.
            session.preset_masters[preset_id] = PresetMasterEntry(
                preset_id=preset_id,
                output_path=str(output_path),
                master_result=session.master_result,
                validation=session.validation,
                status="completed",
                progress=1.0,
                created_at=time.time(),
            )
            save_sessions(sessions)
            # The entry and ``mastered_path`` are the SAME file (the copy
            # above), so one upload stamps both durable keys.
            await _persist_master_to_r2(session, output_path, preset_id=preset_id)
            return session

    # ── Pre-render cache: serve dynamically pre-rendered master ── */
    if preset_id and original_source and session_id in _prerender_cache:
        entry = _prerender_cache[session_id].get(preset_id)
        if (
            entry
            and entry["status"] == "completed"
            and entry.get("output_path")
        ):
            cached_path = Path(entry["output_path"])
            # A mastered WAV is always > 1 KiB; smaller files are broken
            # stubs and must never be served as a master.
            if cached_path.exists() and cached_path.stat().st_size > 1024:
                shutil.copy2(cached_path, output_path)
                session.mastered_path = str(output_path)
                session.parameters = params
                session.status = ProcessingStatus.COMPLETED
                session.progress = 1.0
                session.error = None
                session.master_result = entry.get("master_result")
                session.validation = entry.get("validation")
                # Record the per-preset result pointing at the PRERENDER
                # output file so ?preset_id= lookups work later; the legacy
                # copy-to-{session_id}_mastered.wav + mastered_path behavior
                # above is unchanged.
                session.preset_masters[preset_id] = PresetMasterEntry(
                    preset_id=preset_id,
                    output_path=entry.get("output_path"),
                    master_result=entry.get("master_result"),
                    validation=entry.get("validation"),
                    status="completed",
                    progress=1.0,
                    created_at=time.time(),
                )
                save_sessions(sessions)
                # Durability is recorded for the SESSION copy (the prerender
                # artifact itself is shared by every session of that upload),
                # and the entry is pointed at that same key so a later
                # ?preset_id= lookup re-hydrates identical bytes.
                await _persist_master_to_r2(session, output_path, preset_id=preset_id)
                return session

    # ── Preset-aware on-demand processing (client demo mode) ──
    # Single-flight per (session, preset): concurrent /process calls for the
    # same preset share ONE heavy DSP job (never two engines writing the
    # same output file); calls for different presets queue on the global
    # DSP gate. HTTP calls may wait — that is documented demo behavior.
    if preset_id and preset_id in PRESET_CHAINS:
        return await _process_preset_on_demand(
            session=session,
            session_id=session_id,
            params=params,
            preset_id=preset_id,
            master_input=master_input,
            analysis=selected_analysis,
        )

    # Use background analysis if already done; skip re-analysis entirely
    # when it's still running (status == ANALYZING) to avoid double work.
    # The engine handles analysis_result=None gracefully with safe defaults.
    # Only the ORIGINAL source reaches here for analysis: a mix run already
    # analyzed the mix above (into ``selected_analysis``).
    if (
        master_input.source == "original"
        and not session.analysis
        and session.status != ProcessingStatus.ANALYZING
    ):
        session.status = ProcessingStatus.ANALYZING
        try:
            session.analysis = await asyncio.get_running_loop().run_in_executor(
                _dsp_executor, analyze_audio, master_input.input_path
            )
            selected_analysis = session.analysis
        except Exception as e:
            session.status = ProcessingStatus.ERROR
            session.error = f"Analysis failed: {str(e)}"
            raise HTTPException(status_code=500, detail=session.error)

    # Process
    session.status = ProcessingStatus.PROCESSING
    session.progress = 0.0

    def update_progress(pct: float) -> None:
        session.progress = max(0.0, min(1.0, pct))

    def _run_processing() -> None:
        """CPU-bound work executed in a thread so the event loop stays free."""
        with demo_guard.gate():
            result = process_audio(
                input_path=master_input.input_path,
                output_path=output_path,
                params=params,
                analysis_result=selected_analysis,
                progress_cb=update_progress,
            )
            session.mastered_path = result["output_path"]

            # ── Layer 2 gate: validate against the active preset, with at
            # most ONE auto-retry at reduced intensity on LUFS misses. All
            # best-effort: any failure here keeps validation null and never
            # breaks the response.
            preset_entry = _resolve_preset_entry(preset_id)
            if preset_entry is not None:
                retried = False
                try:
                    result, retried = _retry_once_on_lufs_miss(
                        result=result,
                        session=session,
                        params=params,
                        output_path=output_path,
                        preset_entry=preset_entry,
                        progress_cb=update_progress,
                        master_input=master_input,
                        analysis=selected_analysis,
                    )
                except Exception:
                    retried = False
                try:
                    session.master_result = _master_result_from_engine(result)
                    verdict = validate_master(
                        session.master_result, preset_entry, selected_analysis
                    )
                    if verdict is not None:
                        if retried:
                            verdict["retry_applied"] = True
                            verdict["note"] = (
                                "Reintento automático con menor intensidad; "
                                "se conservó el intento más cercano al objetivo."
                            )
                        session.validation = ValidationReport(**verdict)
                except Exception:
                    session.validation = None
            else:
                session.master_result = _master_result_from_engine(result)

            # Delivery compliance report (Compliance Phase 1) — same engine
            # result mapped onto the report model.
            session.mastering_report = _mastering_report_from_engine(result)

            session.parameters = params
            session.status = ProcessingStatus.COMPLETED
            session.progress = 1.0

    try:
        await asyncio.get_running_loop().run_in_executor(
            demo_guard.DSP_THREAD_POOL, _run_processing
        )
    except Exception as e:
        from audiomind.processing.engine import InputQcError

        if isinstance(e, InputQcError):
            # Strict-mode input QC rejection — a REQUEST rejection, not a
            # processing failure: the session keeps its current state and
            # the client gets a 422 with the strict-mode reason. The
            # generic 500 below stays for real DSP failures.
            raise HTTPException(status_code=422, detail=str(e)) from e
        session.status = ProcessingStatus.ERROR
        session.error = f"Processing failed: {str(e)}"
        raise HTTPException(status_code=500, detail=session.error)

    demo_guard.touch(session_id)
    save_sessions(sessions)
    # ``_run_processing`` is a worker thread, so the R2 pointer is written from
    # async context here. Upload failure never fails the request: the local
    # master is already written and deliverable on this container.
    await _persist_master_to_r2(session, session.mastered_path)
    return session


# ── Pre-render endpoints ────────────────────────────────────────────


@router.post("/session/{session_id}/prerender")
async def trigger_prerender(session_id: str, _: object = Depends(require_license)) -> dict[str, Any]:
    """Trigger background pre-rendering of all presets for this session.

    Launches 8 parallel DSP jobs (one per preset). Each preset's result
    is stored in _prerender_cache and can be served instantly when the
    user selects that preset via GET /prerender/{preset_id}.
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.original_path or not Path(session.original_path).exists():
        raise HTTPException(
            status_code=400, detail="No audio file found for this session"
        )

    # If already pre-rendered, return current status
    if session_id in _prerender_cache:
        completed = sum(
            1 for v in _prerender_cache[session_id].values()
            if v["status"] == "completed"
        )
        return {
            "session_id": session_id,
            "status": "in_progress" if completed < len(PRESET_CHAINS) else "completed",
            "completed": completed,
            "total": len(PRESET_CHAINS),
        }

    # Reuse existing analysis; compute only when missing
    if not session.analysis and session.status != ProcessingStatus.ANALYZING:
        try:
            session.analysis = await asyncio.get_running_loop().run_in_executor(
                _dsp_executor, analyze_audio, session.original_path
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

    # Launch pre-render in background (non-blocking)
    _prerender_all_presets(
        session_id=session_id,
        input_path=session.original_path,
        analysis=session.analysis,
    )
    save_sessions(sessions)

    return {
        "session_id": session_id,
        "status": "in_progress",
        "completed": 0,
        "total": len(PRESET_CHAINS),
    }


@router.get("/session/{session_id}/prerender/status")
async def prerender_status(session_id: str) -> dict[str, Any]:
    """Check which presets have been pre-rendered for this session.

    Returns a dict mapping preset_id -> {status, progress, ...}.
    """
    cache = _prerender_cache.get(session_id)
    if not cache:
        return {"session_id": session_id, "presets": {}, "status": "not_started"}

    presets = {}
    completed = 0
    errors = 0
    for preset_id, info in cache.items():
        presets[preset_id] = {
            "status": info["status"],
            "progress": info.get("progress", 0.0),
        }
        if info["status"] == "completed":
            completed += 1
        elif info["status"] == "error":
            errors += 1

    total = len(PRESET_CHAINS)
    overall = "completed" if completed == total else "in_progress"

    return {
        "session_id": session_id,
        "status": overall,
        "completed": completed,
        "errors": errors,
        "total": total,
        "presets": presets,
    }


@router.get("/session/{session_id}/prerender/{preset_id}")
async def get_prerendered(session_id: str, preset_id: str) -> FileResponse:
    """Serve a pre-rendered master for instant playback.

    If the preset is cached, returns the mastered file immediately.
    Falls back to processing on demand if not cached.
    """
    cache = _prerender_cache.get(session_id, {})
    entry = cache.get(preset_id)

    if entry and entry["status"] == "completed" and entry.get("output_path"):
        path = Path(entry["output_path"])
        if path.exists() and path.stat().st_size > 0:
            # Also update the session so the rest of the app sees it
            session = sessions.get(session_id)
            if session:
                session.mastered_path = str(path)
                session.master_result = entry.get("master_result")
                session.validation = entry.get("validation")
                # Keep the durable pointer in step with the pointer this
                # endpoint just published.
                await _persist_master_to_r2(session, path)
            return FileResponse(str(path), media_type="audio/wav", filename=path.name)

    raise HTTPException(
        status_code=404,
        detail=f"Preset '{preset_id}' not ready yet. Check GET /prerender/status.",
    )


@router.post(
    "/session/{session_id}/reference/{preset_id}",
    response_model=ReferenceRenderResult,
)
async def render_reference(
    session_id: str,
    preset_id: str,
    _: object = Depends(require_license),
) -> ReferenceRenderResult:
    """Render the neutral Crudo reference for a fair loudness-matched A/B.

    Uses the "natural" chain character (no EQ bands, 1.1:1 compression,
    no saturation) but overrides ``target_lufs`` and ``limiter_ceiling_db``
    with the chosen preset's values, so the reference sits at the same
    perceived loudness as the master. Cached per session+preset: once
    ``{session_id}_reference_{preset_id}.wav`` exists it is returned
    immediately without re-rendering.
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if preset_id not in PRESET_CHAINS:
        raise HTTPException(status_code=400, detail=f"Unknown preset '{preset_id}'")

    if not session.original_path or not Path(session.original_path).exists():
        raise HTTPException(
            status_code=400, detail="No audio file found for this session"
        )

    preset_entry = PRESET_CHAINS[preset_id]
    output_path = _reference_output_path(session_id, preset_id)

    # ── Per session+preset cache hit: serve without re-rendering ──
    if output_path.exists() and output_path.stat().st_size > 0:
        return ReferenceRenderResult(
            reference_path=str(output_path),
            target_lufs=float(preset_entry["target_lufs"]),
            source_preset_id=preset_id,
        )

    # Reuse existing analysis; compute it only when missing and not
    # already running in the background — same policy as process_session.
    if not session.analysis and session.status != ProcessingStatus.ANALYZING:
        try:
            session.analysis = await asyncio.get_running_loop().run_in_executor(
                _dsp_executor, analyze_audio, session.original_path
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

    def _run_reference() -> None:
        """CPU-bound work executed in a thread so the event loop stays free."""
        process_audio(
            input_path=session.original_path,
            output_path=output_path,
            params=_build_reference_params(preset_entry),
            analysis_result=session.analysis,
        )

    try:
        await asyncio.get_running_loop().run_in_executor(_dsp_executor, _run_reference)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reference render failed: {str(e)}")

    return ReferenceRenderResult(
        reference_path=str(output_path),
        target_lufs=float(preset_entry["target_lufs"]),
        source_preset_id=preset_id,
    )


@router.post("/session/{session_id}/reset")
async def reset_session_master(session_id: str) -> SessionData:
    """Revert the mastered state, leaving only the uploaded original.

    Clears every master pointer and per-preset output and returns the
    session to the pre-master state (``uploaded``). The rendered WAV files
    stay on disk, untracked by the session — a later preset selection
    re-masters normally. The durable Cloudflare R2 pointers are cleared too
    (``master_r2_key`` and every per-preset key), so a discarded master can
    never be re-hydrated from storage; the objects themselves are left alone
    (there is no lifecycle for them, same as the mixes). The uploaded
    original and its analysis are untouched.

    ``mix_status`` is cleared with the rest of the session state (``none``):
    the mix is not a master pointer, but a reset means "start over from my
    upload", so the client stops advertising a delivered mix and the
    default ``/process`` source goes back to the original. The already
    written ``mix_path`` / ``mix_analysis`` survive (the WAV stays
    downloadable from its stable URL); running the mix again re-marks the
    session as ``completed``.
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.mastered_path = None
    # The durable R2 pointer goes with the local one: a reset means the user
    # discarded the master, so nothing must be able to re-hydrate it. The
    # per-preset keys are dropped by ``preset_masters = {}`` below.
    session.master_r2_key = None
    session.master_result = None
    session.mastering_report = None
    session.validation = None
    session.reference_path = None
    session.reference_filename = None
    session.reference_comparison = None
    session.preset_masters = {}
    session.mix_status = "none"
    session.status = ProcessingStatus.UPLOADED
    session.progress = 0.0
    session.error = None
    save_sessions(sessions)
    return session


@router.get("/session/{session_id}/audio/reference/{preset_id}")
async def get_reference_audio(session_id: str, preset_id: str) -> FileResponse:
    """Serve the rendered Crudo reference WAV for playback."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if preset_id not in PRESET_CHAINS:
        raise HTTPException(status_code=400, detail=f"Unknown preset '{preset_id}'")

    path = _reference_output_path(session_id, preset_id)
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Reference not rendered yet. POST /session/{id}/reference/{preset} first.",
        )

    return FileResponse(str(path), media_type="audio/wav", filename=path.name)


# ── External reference (Phase C, P1-1) ─────────────────────────────────
# Distinct surface from the Crudo ``/reference/{preset_id}`` re-render:
# the user uploads a REAL mastered reference file and the comparison is
# pure measurement (spectral diff + loudness/brightness profile). No DSP
# runs — the neutral contract is preserved by construction. Routes live
# on the ``reference-file`` prefix so they never collide with the Crudo
# ``/reference/{preset_id}`` paths; the playback route below MUST stay
# registered before ``/audio/{audio_type}`` (literal beats parameter).


def _validate_reference_upload(filename: str, content: bytes) -> str:
    """Validate an external reference upload (suffix + size).

    Same rules as ``upload.upload_audio`` so the two upload surfaces
    behave identically; kept here because the endpoint lives in the
    mastering router and upload.py exposes no reusable validator.
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in (".wav", ".mp3"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{suffix}'. Only WAV and MP3 are supported.",
        )
    size_mb = len(content) / (1024 * 1024)
    if size_mb > settings.max_file_size_mb:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large ({size_mb:.1f}MB). Maximum is "
                f"{settings.max_file_size_mb}MB."
            ),
        )
    return suffix


@router.post(
    "/session/{session_id}/reference-file",
    response_model=ReferenceUploadResult,
)
async def upload_reference_file(
    session_id: str,
    file: UploadFile = File(...),
    _: object = Depends(require_license),
) -> ReferenceUploadResult:
    """Upload an external mastered reference file for this session.

    REPLACE semantics: a second upload overwrites the previous reference
    and drops the stale comparison. The file lands in the upload dir as
    ``{session_id}_reference{suffix}`` and the session gains
    ``reference_path``/``reference_filename`` (the original uploaded
    name, mirroring ``original_filename``).
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    filename = file.filename
    if not filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    content = await file.read()
    suffix = _validate_reference_upload(filename, content)

    reference_path = (
        settings.upload_dir / f"{session_id}_reference{suffix}"
    ).resolve()
    reference_path.write_bytes(content)

    # Replace semantics: drop the stale comparison and remove the previous
    # reference file when the suffix changed (e.g. .wav -> .mp3).
    previous = session.reference_path
    if previous and Path(previous).resolve() != reference_path:
        Path(previous).unlink(missing_ok=True)
    session.reference_path = str(reference_path)
    session.reference_filename = filename
    session.reference_comparison = None
    save_sessions(sessions)

    return ReferenceUploadResult(
        reference_path=str(reference_path),
        reference_filename=filename,
    )


@router.post(
    "/session/{session_id}/compare-reference",
    response_model=ReferenceComparison,
)
async def compare_reference(session_id: str, _: object = Depends(require_license)) -> ReferenceComparison:
    """Compare the mastered output against the uploaded external reference.

    Pure measurement (spectral diff + loudness/brightness profile); no
    DSP runs. Cached per session like the Crudo reference render: once
    ``reference_comparison`` exists it is returned without re-measuring
    (re-uploading the reference clears the cache). Files that fail to
    decode surface as ``status="error"`` in the payload rather than a
    hard failure.
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.reference_path or not Path(session.reference_path).exists():
        raise HTTPException(
            status_code=400,
            detail=(
                "No reference file uploaded for this session. "
                "POST /session/{id}/reference-file first."
            ),
        )
    # Re-hydrates the master from R2 when a redeploy took the local file, so
    # the comparison view keeps working instead of asking for a re-master.
    master_file = await _resolve_master_file(
        session,
        None,
        missing_detail=(
            "No mastered audio available. POST /session/{id}/process first."
        ),
        # Historic status for "this session was never mastered": an actionable
        # request-state problem, not a missing resource.
        missing_status=400,
    )

    if session.reference_comparison is not None:
        return session.reference_comparison

    try:
        comparison = await asyncio.get_running_loop().run_in_executor(
            _dsp_executor, compare_tracks, str(master_file), session.reference_path
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Reference comparison failed: {str(e)}"
        ) from e

    # The stored path is session-scoped; the payload carries the ORIGINAL
    # uploaded filename, mirroring ``original_filename``.
    comparison.reference_filename = session.reference_filename
    session.reference_comparison = comparison
    save_sessions(sessions)
    return comparison


@router.get("/session/{session_id}/audio/reference-file")
async def get_reference_file_audio(session_id: str) -> FileResponse:
    """Serve the uploaded external reference file for playback."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.reference_path or not Path(session.reference_path).exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "No reference file uploaded for this session. "
                "POST /session/{id}/reference-file first."
            ),
        )

    path = Path(session.reference_path).resolve()
    media_type = "audio/mpeg" if path.suffix.lower() == ".mp3" else "audio/wav"
    return FileResponse(
        str(path),
        media_type=media_type,
        filename=session.reference_filename or path.name,
    )


@router.get("/session/{session_id}/audio/{audio_type}")
async def get_audio(
    session_id: str,
    audio_type: str,
    preset_id: str | None = Query(default=None),
) -> FileResponse:
    """Serve audio file for playback.

    ``audio_type == "mastered"`` accepts an optional ``?preset_id=X`` to
    serve that preset's mastered file instead of the legacy
    ``mastered_path`` pointer; unknown presets / missing files → 404.
    A master whose local file was lost with the container is re-hydrated
    from its durable R2 pointer first, so playback survives a redeploy.
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if audio_type == "original":
        path = session.original_path
        if not path or not Path(path).exists():
            raise HTTPException(status_code=404, detail="Audio file not found")
    elif audio_type == "mastered":
        path = str(
            await _resolve_master_file(
                session, preset_id, missing_detail="Audio file not found"
            )
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="audio_type must be 'original' or 'mastered'",
        )

    return FileResponse(
        str(Path(path).resolve()),
        media_type="audio/wav",
        filename=f"{session_id}_{audio_type}.wav",
    )


@router.get("/session/{session_id}/raw")
async def get_raw_audio(session_id: str) -> dict[str, Any]:
    """Return raw PCM audio data as JSON for Web Audio API.

    Returns:
    - samples: flat array of Float32 samples (interleaved L/R for stereo)
    - sampleRate: audio sample rate
    - channels: number of channels
    - duration: duration in seconds
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.original_path or not Path(session.original_path).exists():
        raise HTTPException(status_code=404, detail="Audio file not found")

    audio, sr = sf.read(session.original_path, dtype="float32")

    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)

    channels = audio.shape[1]
    duration = audio.shape[0] / sr

    return {
        "samples": audio.flatten().tolist(),
        "sampleRate": sr,
        "channels": channels,
        "duration": duration,
    }


@router.get("/session/{session_id}/raw-mastered")
async def get_raw_mastered_audio(
    session_id: str,
    preset_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Return raw PCM audio data of the mastered version.

    ``?preset_id=X`` serves that preset's mastered file (404 when unknown
    or missing); the no-param legacy behavior reads ``mastered_path``. A
    master lost with the container is re-hydrated from R2 first, so the
    waveform comparison keeps working after a redeploy.
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    path = await _resolve_master_file(
        session, preset_id, missing_detail="No mastered audio available"
    )

    audio, sr = sf.read(path, dtype="float32")

    if audio.ndim == 1:
        audio = np.stack([audio, audio], axis=1)

    channels = audio.shape[1]
    duration = audio.shape[0] / sr

    return {
        "samples": audio.flatten().tolist(),
        "sampleRate": sr,
        "channels": channels,
        "duration": duration,
    }


@router.get("/session/{session_id}/download/{format}")
async def download_audio(
    session_id: str,
    format: str,
    preset_id: str | None = Query(default=None),
    _: object = Depends(require_license),
) -> FileResponse:
    """Download mastered audio in specified format.

    ``?preset_id=X`` downloads THAT preset's mastered file (same
    precedence as ``/audio/mastered``); no param keeps the legacy
    ``mastered_path`` behavior. MP3 conversion keeps using ffmpeg. A master
    lost with the container is re-hydrated from R2 first, so a master the
    user already paid for stays downloadable after a redeploy.
    """
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    source = str(
        await _resolve_master_file(
            session,
            preset_id,
            missing_detail="No mastered audio available. Process first.",
        )
    )

    if format not in ("wav", "mp3"):
        raise HTTPException(status_code=400, detail="Format must be 'wav' or 'mp3'")

    # Name the download after the original upload: "beatRap.wav" → "BeatRapMasterizado.wav"
    if session.original_filename:
        stem = Path(session.original_filename).stem
        display_name = f"{stem[:1].upper()}{stem[1:]}Masterizado"
    else:
        display_name = "WaveAIFinal"

    if format == "mp3":
        import subprocess
        import shutil

        mp3_path = Path(source).with_suffix(".mp3")
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            # Try common Windows install path
            for candidate in [
                r"C:\ffmpeg\bin\ffmpeg.exe",
                r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
            ]:
                if Path(candidate).exists():
                    ffmpeg = candidate
                    break
        if not ffmpeg:
            raise HTTPException(status_code=500, detail="ffmpeg not found. Install ffmpeg for MP3 support.")
        
        result = subprocess.run(
            [ffmpeg, "-i", source, "-codec:a", "libmp3lame", "-b:a", "320k", "-y", str(mp3_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"MP3 conversion failed: {result.stderr[-200:]}")
        
        return FileResponse(
            str(mp3_path),
            media_type="audio/mpeg",
            filename=f"{display_name}.mp3",
        )

    return FileResponse(
        source,
        media_type="audio/wav",
        filename=f"{display_name}.wav",
    )


@router.get("/session/{session_id}")
async def get_session(session_id: str) -> SessionData:
    """Get session status and data (for polling progress)."""
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/session/new", response_model=SessionData)
async def create_session() -> SessionData:
    """Create a new empty session (without uploading audio yet).

    Useful for pre-initializing a session before upload, or for
    programmatic session creation.
    """
    import uuid
    session_id = str(uuid.uuid4())
    session = SessionData(session_id=session_id)
    sessions[session_id] = session
    return session


@router.post("/master")
async def master_stateless(
    req: StatelessMasterRequest,
    _: object = Depends(require_license),
) -> dict[str, Any]:
    """Stateless one-shot mastering from a signed audio URL.

    Downloads ``audio_url`` (no session, no upload), analyzes it and runs
    the DSP pipeline with the given settings in one synchronous-per-
    request flow. Returns the mastered output path and the measured
    metrics of the final master.

    This endpoint is deliberately parallel to the session-based flow: it
    shares the same engine, analysis and metrics mapping but keeps zero
    in-memory state on the server.
    """
    # Guard the URL scheme before touching the network.
    parsed = urllib.parse.urlparse(req.audio_url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(
            status_code=400, detail="audio_url must be an http(s) URL"
        )

    # Download to a fresh upload-dir file. The suffix follows the URL when
    # recognizable (same pair as /api/upload); otherwise assume WAV.
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in (".wav", ".mp3"):
        suffix = ".wav"
    input_path = (
        settings.upload_dir / f"stateless_{uuid.uuid4().hex}{suffix}"
    ).resolve()
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    try:
        with urllib.request.urlopen(req.audio_url, timeout=60) as resp, open(
            input_path, "wb"
        ) as out:
            total = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    input_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"Audio too large (>{settings.max_file_size_mb}MB)",
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        input_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400, detail=f"Failed to download audio_url: {e}"
        )

    output_path = (
        settings.output_dir / f"stateless_{uuid.uuid4().hex}_mastered.wav"
    ).resolve()

    def _run_pipeline() -> dict[str, Any]:
        """Analyze + process on the DSP executor; the event loop stays free."""
        with demo_guard.gate():
            analysis = analyze_audio(input_path)
            if demo_guard.duration_over_limit(
                getattr(analysis, "duration_seconds", None)
            ):
                # Demo duration limit — analyzed BEFORE any DSP runs.
                raise demo_guard.DemoDurationError(
                    demo_guard.demo_duration_message(
                        settings.demo_max_duration_seconds
                    )
                )
            return process_audio(
                input_path=input_path,
                output_path=output_path,
                params=req.settings,
                analysis_result=analysis,
            )

    try:
        result = await asyncio.get_running_loop().run_in_executor(
            demo_guard.DSP_THREAD_POOL, _run_pipeline
        )
    except demo_guard.DemoDurationError as e:
        input_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=str(e)) from e
    except Exception as e:
        input_path.unlink(missing_ok=True)
        from audiomind.processing.engine import InputQcError

        if isinstance(e, InputQcError):
            # Strict-mode input QC rejection: 422 (request rejection), not
            # the generic processing-failure 500 below.
            raise HTTPException(status_code=422, detail=str(e)) from e
        raise HTTPException(status_code=500, detail=f"Mastering failed: {e}")

    return {
        "audio": result.get("output_path", str(output_path)),
        "metrics": _master_result_from_engine(result),
        "mastering_report": _mastering_report_from_engine(result),
    }
