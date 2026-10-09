"""Unit tests for the compile_project module (WU5).

Coverage:
- compile() with document absent, state absent -> neutral defaults
- compile() with document present, state absent -> defaults from document
- compile() stem_trims: all zeros -> None (bypass); non-zero -> dict with {stem}_db keys
- compile() dimension_enabled/auto_balance from toggles
- load_inputs() returns (None, StateProjection()) when project not found
"""

from __future__ import annotations

from typing import Optional

import pytest

from audiomind.models.audio import MasteringParameters
from audiomind.models.project_document import (
    ProjectDocument,
    default_document,
    MixIntent,
    MasterIntent,
    Structure,
    StemBlock,
    StemNode,
    Group,
)


# ─── Mock ProjectDocument ──────────────────────────────────────────────
class _MockProjectDocument:
    """Minimal mock for compile() tests when no real DB is available."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        # Ensure master_intent is always set for compile() tests
        if not hasattr(self, "master_intent") or self.master_intent is None:
            from audiomind.services.compile_project import MasterIntent  # type: ignore
            self.master_intent = MasterIntent(
                preset_id="universal",
                platform_target="spotify",
                format="wav",
                output_bit_depth=24,
                master_name=None,
                parameters=None,
            )


# ─── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def mock_doc():
    """A mock ProjectDocument with some data."""
    doc = _MockProjectDocument()
    return doc


@pytest.fixture
def mock_state():
    """A mock StateProjection with some custom values."""
    from audiomind.services.compile_project import StateProjection
    return StateProjection(
        faders={"drums_db": -2.0},
        toggles={"dimension_enabled": False, "auto_balance": True},
    )


# ─── Compiler tests ────────────────────────────────────────────────────

def test_compile_no_doc_no_state():
    """compile(None, StateProjection()) -> neutral defaults."""
    from audiomind.services.compile_project import compile, StateProjection
    plan = compile(None, StateProjection())
    assert plan.stem_trims is None
    assert plan.dimension_enabled is True
    assert plan.auto_balance is False
    assert plan.preset_id is None
    assert plan.platform_target is None
    assert plan.format == "wav"
    assert plan.output_bit_depth == 24
    assert plan.master_name is None
    assert plan.parameters is None


def test_compile_no_doc_no_state_no_overrides():
    """compile(None, StateProjection()) with no document: all neutral."""
    from audiomind.services.compile_project import compile, StateProjection
    plan = compile(None, StateProjection())
    assert plan.stem_trims is None
    assert plan.dimension_enabled is True  # default
    assert plan.auto_balance is False  # default


def test_compile_all_zero_faders():
    """compile() with all faders 0.0 -> stem_trims = None (bypass)."""
    from audiomind.services.compile_project import compile, StateProjection
    state = StateProjection(faders={"drums_db": 0.0, "bass_db": 0.0, "other_db": 0.0, "vocals_db": 0.0})
    plan = compile(None, state)
    assert plan.stem_trims is None


def test_compile_some_nonzero_faders():
    """compile() with some non-zero faders -> stem_trims dict con claves {stem}_db."""
    from audiomind.services.compile_project import compile, StateProjection
    state = StateProjection(faders={"drums_db": 1.5, "bass_db": 0.0, "other_db": -0.5, "vocals_db": 0.0})
    plan = compile(None, state)
    assert plan.stem_trims == {"drums_db": 1.5, "other_db": -0.5}


def test_compile_load_inputs_missing_project():
    """load_inputs returns (None, StateProjection()) when project not found."""
    from audiomind.services.compile_project import load_inputs
    doc, state = load_inputs("nonexistent_project", "user123")
    assert doc is None
    assert state.faders == {}
    assert state.toggles == {"dimension_enabled": True, "auto_balance": False}


# ─── Integration-ish test ──────────────────────────────────────────────

def test_compile_full_pipeline():
    """End-to-end: compile with doc and state produces consistent MixPlan."""
    from audiomind.services.compile_project import compile, StateProjection, MixPlan

    doc = _MockProjectDocument()
    state = StateProjection(
        faders={"drums_db": -2.0},
        toggles={"dimension_enabled": False, "auto_balance": True},
    )
    plan = compile(doc, state)
    assert isinstance(plan, MixPlan)
    assert plan.stem_trims == {"drums_db": -2.0}
    assert plan.dimension_enabled is False
    assert plan.auto_balance is True
    assert plan.preset_id == "universal"
    assert plan.platform_target == "spotify"
    assert plan.format == "wav"
    assert plan.output_bit_depth == 24