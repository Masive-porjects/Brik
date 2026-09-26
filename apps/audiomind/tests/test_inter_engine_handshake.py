"""Tests for Mix→Master Handshake & Stereo Shuffler integration."""

import pytest
import numpy as np
from pydantic import ValidationError

# Fixtures will be imported from conftest or defined here
# For now, we'll define minimal fixtures inline


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