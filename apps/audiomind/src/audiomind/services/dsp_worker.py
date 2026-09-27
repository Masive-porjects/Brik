"""DSP worker service for decoupled, stateless AudioMind mastering jobs.

Orchestrates downloading audio from Supabase Storage or signed URLs,
running the 13-stage DSP chain (or transparent delivery), validating output
metrics, uploading mastered assets back to Supabase Storage ('audio-masters'),
and persisting audit & version metadata in PostgreSQL ('public.masters').
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field
from supabase import Client

from audiomind.config import settings
from audiomind.models.audio import (
    MasteringParameters,
    MasteringReport,
    MasterResultMetrics,
    ValidationReport,
)
from audiomind.processing.engine import process_audio
from audiomind.processing.presets import PRESET_CHAINS
from audiomind.processing.validation import validate_master
from audiomind.services import demo_guard
from audiomind.services.supabase_client import (
    create_or_update_master_record,
    download_storage_file,
    get_supabase_client,
    log_track_event,
    update_track_status,
    upload_storage_file,
)

logger = logging.getLogger(__name__)

# Streaming platform delivery targets (LUFS, True Peak ceiling in dBTP)
PLATFORM_DELIVERY_TARGETS: dict[str, dict[str, float]] = {
    "spotify": {"target_lufs": -14.0, "limiter_ceiling_db": -1.0},
    "apple_music": {"target_lufs": -16.0, "limiter_ceiling_db": -1.0},
    "youtube": {"target_lufs": -14.0, "limiter_ceiling_db": -1.0},
    "tidal": {"target_lufs": -14.0, "limiter_ceiling_db": -1.0},
    "club": {"target_lufs": -9.0, "limiter_ceiling_db": -0.3},
    "cd": {"target_lufs": -11.0, "limiter_ceiling_db": -0.3},
}


class MasterJobPayload(BaseModel):
    """Payload for submitting a mastering worker job."""

    track_id: str = Field(..., description="UUID of the track in public.tracks")
    user_id: str | None = Field(
        None, description="UUID of the owner in auth.users / public.profiles"
    )
    version_id: str | None = Field(
        None, description="Optional master UUID (defaults to generating a fresh one)"
    )
    input_audio_url: str | None = Field(
        None, description="Signed or public HTTP(S) URL for the raw input audio"
    )
    input_storage_path: str | None = Field(
        None,
        description="Storage path in audio-originals bucket (e.g. userId/trackId.wav)",
    )
    preset_id: str | None = Field(
        None,
        description=(
            "Preset ID (universal, fuego, claridad, cinta, "
            "natural, espacial, cinematico, empuje)"
        ),
    )

    parameters: MasteringParameters | None = Field(
        None, description="Explicit MasteringParameters overrides"
    )
    platform_target: (
        Literal["spotify", "apple_music", "youtube", "tidal", "club", "cd", "custom"]
        | None
    ) = Field(None, description="Streaming target compliance profile")
    format: Literal["wav", "mp3"] = Field(
        "wav", description="Delivery container format"
    )
    output_bit_depth: int = Field(
        24,
        ge=16,
        le=32,
        description="Target bit depth for WAV (24 standard, 16 dithered)",
    )
    master_name: str | None = Field(
        None, description="Human-readable name for the consolidated master"
    )
    is_async: bool = Field(
        False, description="Whether to enqueue the job for asynchronous execution"
    )


class MasterJobResult(BaseModel):
    """Execution result for a master job."""

    success: bool
    job_id: str
    track_id: str
    master_id: str
    status: str
    storage_path: str | None = None
    download_url: str | None = None
    file_size_bytes: int = 0
    format: str = "wav"
    metrics: MasterResultMetrics | None = None
    validation: ValidationReport | None = None
    report: MasteringReport | None = None
    error: str | None = None


# In-memory tracking for async background jobs
_active_jobs: dict[str, dict[str, Any]] = {}


def get_job_status(job_id: str) -> dict[str, Any] | None:
    """Retrieve the current state of an asynchronous job."""
    return _active_jobs.get(job_id)


def build_job_parameters(payload: MasterJobPayload) -> MasteringParameters:
    """Construct the final MasteringParameters, combining preset and overrides."""
    # 1. Start from preset or default
    if payload.preset_id and payload.preset_id in PRESET_CHAINS:
        entry = PRESET_CHAINS[payload.preset_id]
        comp = entry.get("compressor", {})
        params = MasteringParameters(
            clarity_wet=0.15 if entry.get("eq_character") == "brillante" else 0.1,
            clarity_brightness_db=1.0
            if entry.get("eq_character") == "brillante"
            else 0.5,
            compression_ratio=comp.get("ratio", 2.0),
            limiter_ceiling_db=entry.get("limiter_ceiling_db", -1.0),
            transient_boost_db=1.0 if entry.get("eq_character") == "punch" else 0.5,
            saturation_drive_db=entry.get("saturation", {}).get("drive_max", 0.0)
            if entry.get("saturation")
            else 0.0,
            saturation_warmth_db=1.0 if entry.get("saturation") else 0.0,
            stereo_width=entry.get(
                "stereo_width", 1.2 if entry.get("spatial") else 1.0
            ),
            haas_delay_ms=5.0 if entry.get("spatial") else 0.0,
            eq_bands=entry.get("eq_bands", []),
            output_bit_depth=payload.output_bit_depth,
            target_lufs_db=entry.get("target_lufs"),
        )
    else:
        params = payload.parameters or MasteringParameters(
            output_bit_depth=payload.output_bit_depth
        )

    # 2. Apply platform targets if specified
    if payload.platform_target and payload.platform_target in PLATFORM_DELIVERY_TARGETS:
        targets = PLATFORM_DELIVERY_TARGETS[payload.platform_target]
        params.target_lufs_db = targets["target_lufs"]
        params.limiter_ceiling_db = targets["limiter_ceiling_db"]

    # 3. Merge explicit parameter overrides if preset was used
    if payload.preset_id and payload.parameters:
        user_dump = payload.parameters.model_dump(exclude_unset=True)
        current_dump = params.model_dump()
        current_dump.update(user_dump)
        params = MasteringParameters(**current_dump)

    params.output_bit_depth = payload.output_bit_depth
    return params


def _convert_wav_to_mp3(wav_path: Path, mp3_path: Path) -> Path:
    """Convert a WAV master to MP3 320kbps via ffmpeg with fallbacks."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        for candidate in [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        ]:
            if Path(candidate).exists():
                ffmpeg = candidate
                break

    if not ffmpeg:
        raise RuntimeError("ffmpeg not found on server for MP3 encoding.")

    cmd = [
        ffmpeg,
        "-i",
        str(wav_path),
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "320k",
        "-y",
        str(mp3_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    if res.returncode != 0:
        raise RuntimeError(f"MP3 encoding failed: {res.stderr[-250:]}")
    return mp3_path


def execute_master_job(
    payload: MasterJobPayload,
    client: Client | None = None,
    job_id: str | None = None,
) -> MasterJobResult:
    """Execute the full end-to-end stateless mastering pipeline.

    1. Resolves input audio from storage path or HTTP URL.
    2. Runs the 13-stage AudioMind DSP engine.
    3. Converts to requested output format (WAV/MP3).
    4. Uploads master to Supabase Storage ('audio-masters').
    5. Saves row in PostgreSQL ('public.masters') & updates 'public.tracks'.
    6. Returns structured MasterJobResult.
    """
    effective_job_id = job_id or f"job_{uuid.uuid4().hex[:12]}"
    master_id = payload.version_id or str(uuid.uuid4())
    sb_client = client or get_supabase_client()

    logger.info(
        "Starting master job %s for track %s (format=%s, preset=%s)",
        effective_job_id,
        payload.track_id,
        payload.format,
        payload.preset_id,
    )

    # 1. Determine input source
    source = payload.input_audio_url or payload.input_storage_path
    if not source:
        # Check if we can find the track's storage path in DB
        if sb_client:
            try:
                res = (
                    sb_client.table("tracks")
                    .select("storage_path, user_id, title")
                    .eq("id", payload.track_id)
                    .maybe_single()
                    .execute()
                )
                track_row = res.data if res and isinstance(res.data, dict) else None
                if track_row:
                    source_val = track_row.get("storage_path")
                    source = str(source_val) if source_val else None
                    if not payload.user_id and track_row.get("user_id"):
                        payload.user_id = str(track_row["user_id"])
                    if not payload.master_name:
                        track_title = str(track_row.get("title") or "Track")
                        payload.master_name = f"{track_title} - Master"

            except Exception as e:
                logger.warning(
                    "Could not query track %s from DB: %s", payload.track_id, e
                )

    if not source:
        err = f"No input audio source provided or found for track {payload.track_id}"
        return MasterJobResult(
            success=False,
            job_id=effective_job_id,
            track_id=payload.track_id,
            master_id=master_id,
            status="error",
            error=err,
        )

    # Prepare temporary working files
    with tempfile.TemporaryDirectory(prefix="audiomind_job_") as temp_dir:
        temp_dir_path = Path(temp_dir)
        temp_input = temp_dir_path / f"input_{payload.track_id}.wav"
        temp_output_wav = temp_dir_path / f"master_{master_id}.wav"
        temp_final = temp_output_wav

        try:
            # 2. Download audio
            audio_bytes = download_storage_file(
                source=source,
                bucket=settings.supabase_originals_bucket,
                client=sb_client,
            )
            temp_input.write_bytes(audio_bytes)

            # 3. Build DSP parameters
            params = build_job_parameters(payload)

            # 4. Run DSP engine through concurrency gate
            with demo_guard.gate():
                engine_result = process_audio(
                    input_path=temp_input,
                    output_path=temp_output_wav,
                    params=params,
                )

            # 5. Extract metrics and reports
            metrics = MasterResultMetrics(
                integrated_lufs=engine_result.get("integrated_lufs"),
                true_peak_db=engine_result.get("true_peak_db"),
                crest_factor_db=engine_result.get("crest_factor_db"),
                limiter_ceiling_db=engine_result.get("limiter_ceiling_db"),
                duration_seconds=engine_result.get("duration_seconds"),
                sample_rate=engine_result.get("sample_rate"),
                output_bit_depth=engine_result.get("output_bit_depth"),
                stereo_correlation=engine_result.get("stereo_correlation"),
                lra=engine_result.get("lra"),
            )

            report = MasteringReport(
                input_sr=engine_result.get("input_sr"),
                output_sr=engine_result.get("output_sr"),
                output_bit_depth=engine_result.get("output_bit_depth"),
                lufs_i=engine_result.get("integrated_lufs"),
                true_peak_dbtp=engine_result.get("true_peak_db"),
                lra=engine_result.get("lra"),
                crest_factor_db=engine_result.get("crest_factor_db"),
                stereo_correlation=engine_result.get("stereo_correlation"),
                target_lufs=engine_result.get("target_lufs"),
                warnings=engine_result.get("warnings", []),
            )

            # Validation
            validation = None
            preset_entry = (
                PRESET_CHAINS.get(payload.preset_id) if payload.preset_id else None
            )
            if preset_entry:
                try:
                    v_dict = validate_master(metrics, preset_entry, None)
                    if v_dict:
                        validation = ValidationReport(**v_dict)
                except Exception as e:
                    logger.debug("Validation check skipped or failed: %s", e)

            # 6. Format conversion if MP3
            if payload.format == "mp3":
                temp_mp3 = temp_dir_path / f"master_{master_id}.mp3"
                temp_final = _convert_wav_to_mp3(temp_output_wav, temp_mp3)

            master_bytes = temp_final.read_bytes()
            file_size_bytes = len(master_bytes)

            # 7. Upload to Supabase Storage if client available
            destination_storage_path = None
            signed_download_url = None
            content_type = "audio/mpeg" if payload.format == "mp3" else "audio/wav"

            if sb_client and payload.user_id:
                dest_rel_path = (
                    f"{payload.user_id}/{payload.track_id}/"
                    f"master_{master_id}.{payload.format}"
                )
                try:
                    destination_storage_path = upload_storage_file(
                        file_bytes=master_bytes,
                        destination_path=dest_rel_path,
                        bucket=settings.supabase_masters_bucket,
                        content_type=content_type,
                        client=sb_client,
                    )
                    # Try to generate signed URL
                    try:
                        signed_res = sb_client.storage.from_(
                            settings.supabase_masters_bucket
                        ).create_signed_url(destination_storage_path, 3600)
                        if isinstance(signed_res, dict) and "signedURL" in signed_res:
                            signed_download_url = signed_res["signedURL"]
                        elif hasattr(signed_res, "signed_url"):
                            signed_download_url = signed_res.signed_url
                    except Exception:
                        pass
                except Exception as upload_err:
                    logger.warning(
                        "Could not upload master to Supabase Storage: %s", upload_err
                    )

            # 8. Record in Supabase Database
            if sb_client and payload.user_id:
                master_record = {
                    "id": master_id,
                    "track_id": payload.track_id,
                    "user_id": payload.user_id,
                    "name": payload.master_name
                    or f"Master {payload.preset_id or 'Custom'}",
                    "storage_path": destination_storage_path
                    or f"local:{master_id}.{payload.format}",
                    "format": payload.format,
                    "file_size_bytes": file_size_bytes,
                    "integrated_lufs": metrics.integrated_lufs,
                    "true_peak_db": metrics.true_peak_db,
                    "parameters_applied": params.model_dump(),
                    "preset_name": payload.preset_id,
                    "status": "completed",
                }
                try:
                    create_or_update_master_record(sb_client, master_record)
                    update_track_status(sb_client, payload.track_id, "completed")
                    log_track_event(
                        sb_client,
                        user_id=payload.user_id,
                        track_id=payload.track_id,
                        event_type="master_job_completed",
                        details={
                            "master_id": master_id,
                            "job_id": effective_job_id,
                            "preset": payload.preset_id,
                            "format": payload.format,
                            "lufs": metrics.integrated_lufs,
                        },
                    )
                except Exception as db_err:
                    logger.warning("Could not persist master record to DB: %s", db_err)

            result_obj = MasterJobResult(
                success=True,
                job_id=effective_job_id,
                track_id=payload.track_id,
                master_id=master_id,
                status="completed",
                storage_path=destination_storage_path,
                download_url=signed_download_url,
                file_size_bytes=file_size_bytes,
                format=payload.format,
                metrics=metrics,
                validation=validation,
                report=report,
            )
            return result_obj

        except Exception as e:
            logger.error(
                "Mastering worker job %s failed: %s", effective_job_id, e, exc_info=True
            )
            if sb_client and payload.track_id:
                update_track_status(sb_client, payload.track_id, "error")

            return MasterJobResult(
                success=False,
                job_id=effective_job_id,
                track_id=payload.track_id,
                master_id=master_id,
                status="error",
                error=str(e),
            )


def run_async_master_job(
    payload: MasterJobPayload,
    job_id: str,
) -> None:
    """Entry point for executing a background job."""
    _active_jobs[job_id] = {
        "job_id": job_id,
        "track_id": payload.track_id,
        "status": "processing",
        "started_at": datetime.now(UTC).isoformat(),
        "result": None,
        "error": None,
    }
    try:
        result = execute_master_job(payload, job_id=job_id)
        _active_jobs[job_id]["status"] = result.status
        _active_jobs[job_id]["result"] = result.model_dump()
        _active_jobs[job_id]["completed_at"] = datetime.now(UTC).isoformat()
        if not result.success:
            _active_jobs[job_id]["error"] = result.error
    except Exception as e:
        _active_jobs[job_id]["status"] = "error"
        _active_jobs[job_id]["error"] = str(e)
        _active_jobs[job_id]["completed_at"] = datetime.now(UTC).isoformat()
