"""Tests for the stateless DSP mastering worker and jobs API (Fase 6)."""

import uuid
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from audiomind.main import app
from audiomind.models.audio import MasteringParameters
from audiomind.services.dsp_worker import (
    MasterJobPayload,
    MasterJobResult,
    build_job_parameters,
    execute_master_job,
)


def _create_synthetic_wav_bytes(duration_sec: float = 0.5, sr: int = 44100) -> bytes:
    """Create in-memory bytes of a valid stereo WAV audio file."""
    import io

    rng = np.random.default_rng(42)
    samples = int(duration_sec * sr)
    # Stereo sinusoidal signal + gentle noise
    t = np.linspace(0, duration_sec, samples, endpoint=False)
    left = 0.2 * np.sin(2 * np.pi * 440 * t) + rng.normal(0, 0.02, samples)
    right = 0.2 * np.sin(2 * np.pi * 880 * t) + rng.normal(0, 0.02, samples)
    audio = np.stack([left, right], axis=1).astype(np.float32)

    bio = io.BytesIO()
    sf.write(bio, audio, sr, format="WAV", subtype="PCM_24")
    return bio.getvalue()


class TestBuildJobParameters:
    def test_preset_mapping(self):
        payload = MasterJobPayload(
            track_id=str(uuid.uuid4()),
            preset_id="fuego",
        )
        params = build_job_parameters(payload)
        assert params.compression_ratio == 4.0
        assert params.limiter_ceiling_db == -1.0
        assert params.output_bit_depth == 24

    def test_platform_target_override(self):
        payload = MasterJobPayload(
            track_id=str(uuid.uuid4()),
            preset_id="universal",
            platform_target="apple_music",
        )
        params = build_job_parameters(payload)
        assert params.target_lufs_db == -16.0
        assert params.limiter_ceiling_db == -1.0

    def test_user_parameter_overrides(self):
        payload = MasterJobPayload(
            track_id=str(uuid.uuid4()),
            preset_id="cinta",
            parameters=MasteringParameters(saturation_drive_db=5.5),
        )
        params = build_job_parameters(payload)
        assert params.saturation_drive_db == 5.5


class TestExecuteMasterJob:
    def test_missing_source_fails_gracefully(self):
        payload = MasterJobPayload(
            track_id=str(uuid.uuid4()),
            user_id=str(uuid.uuid4()),
        )
        result = execute_master_job(payload, client=None)
        assert result.success is False
        assert result.status == "error"
        assert "No input audio source" in (result.error or "")

    @patch("audiomind.services.dsp_worker.download_storage_file")
    @patch("audiomind.services.dsp_worker.upload_storage_file")
    @patch("audiomind.services.dsp_worker.create_or_update_master_record")
    @patch("audiomind.services.dsp_worker.update_track_status")
    @patch("audiomind.services.dsp_worker.log_track_event")
    def test_execute_master_job_success(
        self,
        mock_log,
        mock_track_status,
        mock_save_master,
        mock_upload,
        mock_download,
    ):
        wav_bytes = _create_synthetic_wav_bytes(0.3)
        mock_download.return_value = wav_bytes
        mock_upload.return_value = "audio-masters/test_user/test_track/master_123.wav"

        mock_client = MagicMock()
        mock_client.storage.from_().create_signed_url.return_value = {
            "signedURL": "https://signed.example.com/master.wav"
        }

        track_id = str(uuid.uuid4())
        user_id = str(uuid.uuid4())
        payload = MasterJobPayload(
            track_id=track_id,
            user_id=user_id,
            input_storage_path=f"{user_id}/{track_id}.wav",
            preset_id="natural",
            platform_target="spotify",
            format="wav",
        )

        result = execute_master_job(payload, client=mock_client)

        assert result.success is True
        assert result.status == "completed"
        assert result.track_id == track_id
        assert result.storage_path == (
            "audio-masters/test_user/test_track/master_123.wav"
        )

        assert result.metrics is not None
        assert result.metrics.integrated_lufs is not None
        assert result.metrics.true_peak_db is not None
        assert result.download_url == "https://signed.example.com/master.wav"

        mock_download.assert_called_once()
        mock_upload.assert_called_once()
        mock_save_master.assert_called_once()
        mock_track_status.assert_called_with(mock_client, track_id, "completed")
        mock_log.assert_called_once()


class TestJobsApiEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_jobs_health(self, client):
        resp = client.get("/api/jobs/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["subsystem"] == "dsp-worker"

    @patch("audiomind.api.jobs.execute_master_job")
    def test_submit_master_job_sync(self, mock_exec, client):
        track_id = str(uuid.uuid4())
        mock_exec.return_value = MasterJobResult(
            success=True,
            job_id="job_test123",
            track_id=track_id,
            master_id="master_abc",
            status="completed",
            storage_path="audio-masters/test.wav",
        )

        resp = client.post(
            "/api/jobs/master",
            json={
                "track_id": track_id,
                "input_audio_url": "https://example.com/audio.wav",
                "preset_id": "universal",
                "is_async": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["job_id"] == "job_test123"
        assert data["status"] == "completed"

    @patch("audiomind.api.jobs.run_async_master_job")
    def test_submit_master_job_async(self, mock_async_run, client):

        track_id = str(uuid.uuid4())
        resp = client.post(
            "/api/jobs/master",
            json={
                "track_id": track_id,
                "input_audio_url": "https://example.com/audio.wav",
                "preset_id": "fuego",
                "is_async": True,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        assert "job_id" in data
        assert data["track_id"] == track_id

    def test_get_master_job_not_found(self, client):
        resp = client.get("/api/jobs/master/job_nonexistent_999")
        assert resp.status_code == 404
