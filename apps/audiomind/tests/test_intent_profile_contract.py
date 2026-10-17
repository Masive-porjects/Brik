"""Contract test: Python ``IntentProfile`` ↔ ``intent_profile.schema.json``.

The JSON Schema in ``packages/contracts`` is the source of truth shared by
the agent (Zod mirror in ``apps/agent``) and the Python mappers. Whatever
the agent emits must validate here, and nothing the schema rejects may
slip through — otherwise the AI → mix/master bridge drifts silently.
"""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from audiomind.models.intent_profile import INTENT_AXES, IntentProfile

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "packages"
    / "contracts"
    / "intent_profile.schema.json"
)


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def test_same_fields_as_schema(schema):
    assert set(IntentProfile.model_fields) == set(schema["properties"])


def test_axes_match_schema_numeric_properties(schema):
    numeric = {
        name for name, spec in schema["properties"].items() if spec["type"] == "number"
    }
    assert set(INTENT_AXES) == numeric


def test_defaults_match_schema(schema):
    neutral = IntentProfile()
    for name, spec in schema["properties"].items():
        assert getattr(neutral, name) == spec["default"], name


@pytest.mark.parametrize(
    "platform", ["spotify", "apple", "youtube", "club", "none"]
)
def test_every_schema_platform_is_accepted(schema, platform):
    assert platform in schema["properties"]["target_platform"]["enum"]
    assert IntentProfile(target_platform=platform).target_platform == platform


def test_unknown_platform_is_rejected():
    with pytest.raises(ValidationError):
        IntentProfile(target_platform="tidal")


def test_unknown_field_is_rejected(schema):
    assert schema["additionalProperties"] is False
    with pytest.raises(ValidationError):
        IntentProfile(loudnes=0.7)


def test_string_limits_match_schema(schema):
    for name in ("reference_genre", "notes"):
        limit = schema["properties"][name]["maxLength"]
        IntentProfile(**{name: "x" * limit})
        with pytest.raises(ValidationError):
            IntentProfile(**{name: "x" * (limit + 1)})


def test_agent_neutral_profile_validates():
    """The agent's NEUTRAL_PROFILE (apps/agent/src/intentProfile.ts) as JSON."""
    agent_neutral = {axis: 0.5 for axis in INTENT_AXES} | {
        "target_platform": "none",
        "reference_genre": "",
        "notes": "",
    }
    assert IntentProfile(**agent_neutral) == IntentProfile.neutral()
