"""Tests for Mix→Master Handshake & Stereo Shuffler integration."""

import pytest
import numpy as np
from pydantic import ValidationError
from pathlib import Path

# ─── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def sample_wav_path(tmp_path):
    """Path to a sample WAV file for testing."""
    import soundfile as sf
    path = tmp_path / "test.wav"
    t = np.linspace(0.0, 1.0, 44100, endpoint=False)
    sf.write(str(path), 0.25 * np.sin(2.0 * np.pi * 220.0 * t), 44100)
    return path


# ─── Tests ──────────────────────────────────────────────────────────────


class TestMixMetadataContract:
    """Tests for MixMetadata Pydantic contract."""

    def test_serialization_roundtrip(self):
        """MixMetadata serializes and deserializes correctly."""
        from audiomind.models.mix_metadata import MixMetadata
        
        meta = MixMetadata(
            applied_spatial_width=1.35,
            side_energy_ratio=0.38,
            stem_lufs={"drums": -18.2, "bass": -14.5, "other": -20.1, "vocals": -16.8},
            transient_headroom_db=0.8,
            mix_status="completed",
        )
        json_str = meta.model_dump_json()
        parsed = MixMetadata.model_validate_json(json_str)
        assert parsed.applied_spatial_width == 1.35
        assert parsed.side_energy_ratio == 0.38
        assert parsed.stem_lufs["bass"] == -14.5

    @pytest.mark.parametrize("field,value,should_fail", [
        ("applied_spatial_width", 5.0, True),
        ("applied_spatial_width", 0.3, True),
        ("side_energy_ratio", 1.5, True),
        ("side_energy_ratio", -0.1, True),
        ("transient_headroom_db", -15.0, True),
        ("transient_headroom_db", 25.0, True),
    ])
    def test_validation_ranges(self, field, value, should_fail):
        """MixMetadata validates field ranges correctly."""
        from audiomind.models.mix_metadata import MixMetadata
        
        kwargs = {
            "applied_spatial_width": 1.0,
            "side_energy_ratio": 0.1,
            "stem_lufs": {},
            "transient_headroom_db": 3.0,
            "mix_status": "completed",
        }
        kwargs[field] = value
        if should_fail:
            with pytest.raises(ValidationError):
                MixMetadata(**kwargs)
        else:
            MixMetadata(**kwargs)  # no raise


class TestBuildMixIncludesMetadata:
    """Tests for build_mix returning MixMetadata."""

    def test_build_mix_returns_mix_metadata(self, tmp_path):
        """build_mix returns mix_metadata with realistic ranges."""
        from audiomind.processing.mix_engine import build_mix
        import soundfile as sf
        
        wav_path = tmp_path / "test.wav"
        t = np.linspace(0.0, 1.0, 44100, endpoint=False)
        sf.write(str(tmp_path / "test.wav"), 0.25 * np.sin(2.0 * np.pi * 220.0 * np.linspace(0.0, 1.0, 44100, endpoint=False)), 44100)
        
        result = build_mix(session_id="test_meta", input_path=tmp_path / "test.wav")
        meta = result["mix_metadata"]
        
        # Verify all required fields exist
        assert "applied_spatial_width" in meta
        assert "side_energy_ratio" in meta
        assert "stem_lufs" in meta
        assert "transient_headroom_db" in meta
        assert "mix_status" in meta
        
        # Verify realistic ranges
        assert 1.0 <= meta["applied_spatial_width"] <= 2.5
        assert 0.0 <= meta["side_energy_ratio"] <= 1.0
        assert all(k in meta["stem_lufs"] for k in ["drums", "bass", "other", "vocals"])
        assert isinstance(meta["transient_headroom_db"], (int, float))
        assert meta["mix_status"] in ["none", "processing", "completed", "failed"]