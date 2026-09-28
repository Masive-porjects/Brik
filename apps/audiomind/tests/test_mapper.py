"""Tests for the intent → mastering parameters mapper.

The core contract: a fully neutral intent (all 9 axes at exactly 0.5)
maps BIT-EXACTLY onto ``MasteringParameters()`` — the transparent master.
Every curve in the mapper is anchored at 0.5 on the parameter's EXACT
default, and out-of-range intent values are rejected, never clamped.
"""
import pytest
from pydantic import ValidationError

from audiomind.models.audio import MasteringParameters
from audiomind.models.intent_profile import INTENT_AXES, IntentProfile
from audiomind.processing.mapper import map_intent_to_mastering


def _assert_exact_defaults(mapped: MasteringParameters) -> None:
    """Assert every parameter equals the default bit-exactly."""
    defaults = MasteringParameters()
    for field_name in MasteringParameters.model_fields:
        actual, expected = getattr(mapped, field_name), getattr(defaults, field_name)
        assert actual == expected, (
            f"Field '{field_name}' drifted from its default at neutral: "
            f"{actual!r} != {expected!r}"
        )


class TestNeutrality:
    def test_neutral_factory_puts_every_axis_at_half(self):
        neutral = IntentProfile.neutral()
        for axis in INTENT_AXES:
            assert getattr(neutral, axis) == 0.5
        assert neutral.target_platform == "none"

    def test_neutral_maps_to_exact_defaults(self):
        """The hard rule: neutral intent → bit-exact MasteringParameters()."""
        mapped = map_intent_to_mastering(IntentProfile.neutral())
        _assert_exact_defaults(mapped)

    def test_neutral_preserves_nonzero_tricky_defaults(self):
        """A naive '0 = neutral' mapper would break these exact defaults."""
        mapped = map_intent_to_mastering(IntentProfile.neutral())
        assert mapped.clarity_wet == 0.15
        assert mapped.clarity_brightness_db == 1.0
        assert mapped.limiter_ceiling_db == -1.0
        assert mapped.target_lufs_db is None


class TestDistinctIntents:
    def test_warm_aggressive_modern_produce_distinct_parameters(self):
        """Three intents that sound different → different parameter sets."""
        warm = IntentProfile(warmth=0.9, vintage=0.6)
        aggressive = IntentProfile(punch=0.9, loudness=0.9)
        modern = IntentProfile(clarity=0.8, width=0.8, brightness=0.8)

        neutral = map_intent_to_mastering(IntentProfile.neutral())
        p_warm = map_intent_to_mastering(warm)
        p_aggressive = map_intent_to_mastering(aggressive)
        p_modern = map_intent_to_mastering(modern)

        # Each differs from neutral…
        assert p_warm != neutral
        assert p_aggressive != neutral
        assert p_modern != neutral
        # …and from each other.
        assert p_warm != p_aggressive
        assert p_warm != p_modern
        assert p_aggressive != p_modern

    def test_warm_intent_shape(self):
        mapped = map_intent_to_mastering(IntentProfile(warmth=0.9, vintage=0.6))
        assert mapped.saturation_warmth_db > 0.0
        assert mapped.tape_enabled is True
        assert mapped.tape_drive_db > 0.0
        assert mapped.tape_hysteresis > 0.0  # vintage engaged too

    def test_aggressive_intent_shape(self):
        mapped = map_intent_to_mastering(IntentProfile(punch=0.9, loudness=0.9))
        assert mapped.transient_boost_db > 0.0
        assert mapped.adaptive_comp_ratio > 1.0
        assert mapped.target_lufs_db is not None
        assert mapped.target_lufs_db < -9.0 or mapped.target_lufs_db == -9.0
        assert mapped.limiter_ceiling_db < -0.3

    def test_modern_intent_shape(self):
        mapped = map_intent_to_mastering(
            IntentProfile(clarity=0.8, width=0.8, brightness=0.8)
        )
        assert mapped.clarity_wet > 0.15
        assert mapped.stereo_width > 1.0
        assert mapped.clarity_brightness_db > 1.0
        assert mapped.exciter_enabled is True
        assert mapped.exciter_band4_amount > 0.0


class TestCombinationRules:
    def test_vintage_warmth_scales_tape_drive(self):
        """Both axes engage the tape — the warmth drive must back off."""
        warm_only = map_intent_to_mastering(IntentProfile(warmth=1.0, vintage=0.5))
        warm_vintage = map_intent_to_mastering(IntentProfile(warmth=1.0, vintage=1.0))
        assert warm_only.tape_drive_db == 2.0
        assert warm_vintage.tape_drive_db < warm_only.tape_drive_db
        assert warm_vintage.tape_drive_db > 0.0

    def test_dyn_eq_shared_by_clarity_and_vocal_focus(self):
        clarity_only = map_intent_to_mastering(IntentProfile(clarity=0.8))
        vocal_only = map_intent_to_mastering(IntentProfile(vocal_focus=0.8))
        assert clarity_only.dyn_eq_enabled is True
        assert vocal_only.dyn_eq_enabled is True
        assert vocal_only.dyn_eq_band2_ratio > 1.0


class TestValidation:
    def test_out_of_range_axis_rejected_above(self):
        with pytest.raises(ValidationError):
            IntentProfile(warmth=1.2)

    def test_out_of_range_axis_rejected_below(self):
        with pytest.raises(ValidationError):
            IntentProfile(warmth=-0.1)

    def test_boundary_values_are_accepted(self):
        IntentProfile(warmth=0.0)
        IntentProfile(warmth=1.0)

    def test_mapped_values_stay_inside_field_constraints(self):
        """Full-scale intent must never exceed the Field(ge/le) bounds."""
        extreme = map_intent_to_mastering(
            IntentProfile(
                warmth=1.0, punch=1.0, clarity=1.0, brightness=1.0,
                width=1.0, bass_weight=1.0, vocal_focus=1.0,
                vintage=1.0, loudness=1.0,
            )
        )
        from annotated_types import Ge, Le

        for name, field in MasteringParameters.model_fields.items():
            value = getattr(extreme, name)
            for constraint in field.metadata:
                if isinstance(constraint, Ge) and value < constraint.ge:
                    pytest.fail(f"{name}={value!r} below minimum {constraint.ge}")
                if isinstance(constraint, Le) and value > constraint.le:
                    pytest.fail(f"{name}={value!r} above maximum {constraint.le}")