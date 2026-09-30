"""Tests for the intent → Mix Engine knobs mapper.

The core contract: a fully neutral intent (all axes at exactly 0.5) maps
onto the ``MixRequest`` defaults — every fader is exactly 0 dB, so
``stem_trims=None`` and the payload keeps the previous routing (no
``trim_report`` key). That neutrality is a claim about the fader
contribution only, not about bit-identical audio: ``dimension_enabled``
stays ``True``, so the engine's default dimension stage still runs.
Every emitted fader stays inside the ±6 dB band ``POST /mix`` validates,
and the mapped settings are always a valid ``MixRequest`` body.
"""
import pytest

from audiomind.api.mix import MixRequest
from audiomind.models.intent_profile import INTENT_AXES, IntentProfile
from audiomind.processing.mix_mapper import MixSettings, map_intent_to_mix
from audiomind.processing.stem_balance import TRIM_STEM_RANGE

_MASTERING_ONLY_AXES = (
    "warmth", "clarity", "brightness", "width", "vintage", "loudness"
)


class TestNeutrality:
    def test_neutral_maps_to_default_settings(self):
        assert map_intent_to_mix(IntentProfile.neutral()) == MixSettings()

    def test_neutral_has_no_stem_trims(self):
        """None, not a dict of zeros: no trim_report, exact previous payload."""
        assert map_intent_to_mix(IntentProfile.neutral()).stem_trims is None

    def test_settings_defaults_mirror_mix_request_defaults(self):
        """MixSettings() must be the same body as an empty POST /mix."""
        assert MixSettings().model_dump() == MixRequest().model_dump()

    @pytest.mark.parametrize("axis", _MASTERING_ONLY_AXES)
    @pytest.mark.parametrize("value", [0.0, 1.0])
    def test_mastering_axes_leave_the_mix_untouched(self, axis, value):
        mapped = map_intent_to_mix(IntentProfile(**{axis: value}))
        assert mapped == MixSettings()


class TestFaders:
    @pytest.mark.parametrize(
        ("axis", "key"),
        [
            ("punch", "drums_db"),
            ("bass_weight", "bass_db"),
        ],
    )
    def test_axis_extremes_hit_the_anchors(self, axis, key):
        assert map_intent_to_mix(IntentProfile(**{axis: 1.0})).stem_trims == {key: 3.0}
        assert map_intent_to_mix(IntentProfile(**{axis: 0.0})).stem_trims == {key: -3.0}

    @pytest.mark.parametrize(
        ("axis", "key"),
        [
            ("punch", "drums_db"),
            ("bass_weight", "bass_db"),
        ],
    )
    def test_fader_is_monotonic(self, axis, key):
        values = [i / 20 for i in range(21)]
        gains = [
            (map_intent_to_mix(IntentProfile(**{axis: v})).stem_trims or {}).get(
                key, 0.0
            )
            for v in values
        ]
        assert gains == sorted(gains)

    def test_only_active_faders_are_emitted(self):
        trims = map_intent_to_mix(IntentProfile(punch=0.75)).stem_trims
        assert trims == {"drums_db": 1.5}

    def test_no_vocal_fader_is_ever_emitted(self):
        """The vocal axis went away with the Vocal Chain: the voice stays put."""
        for value in (0.0, 0.25, 0.5, 0.75, 1.0):
            trims = map_intent_to_mix(
                IntentProfile(punch=value, bass_weight=value)
            ).stem_trims
            assert "vocals_db" not in (trims or {})

    def test_combined_intent_moves_each_stem(self):
        trims = map_intent_to_mix(IntentProfile(punch=0.8, bass_weight=0.2)).stem_trims
        assert trims is not None
        assert "vocals_db" not in trims
        assert trims["drums_db"] > 0.0
        assert trims["bass_db"] < 0.0
        assert "other_db" not in trims

    @pytest.mark.parametrize("value", [i / 10 for i in range(11)])
    def test_every_axis_value_is_a_valid_mix_request(self, value):
        """Whatever the intent, POST /mix accepts the body (±6 dB, known keys)."""
        intent = IntentProfile(**{axis: value for axis in INTENT_AXES})
        settings = map_intent_to_mix(intent)
        request = MixRequest(**settings.model_dump())
        for db in (request.stem_trims or {}).values():
            assert TRIM_STEM_RANGE[0] <= db <= TRIM_STEM_RANGE[1]


class TestUntouchedKnobs:
    def test_auto_balance_and_dimension_stay_at_defaults(self):
        mapped = map_intent_to_mix(IntentProfile(punch=1.0, bass_weight=1.0))
        assert mapped.auto_balance is False
        assert mapped.dimension_enabled is True
