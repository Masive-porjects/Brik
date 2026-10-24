"""Unit tests for the compile_project module (WU5).

Coverage:
- compile() with document absent, state absent -> neutral defaults
- compile() with document present, state absent -> defaults from document
- compile() stem_trims: all zeros -> None (bypass); non-zero -> dict with {stem}_db keys
- compile() dimension_enabled/auto_balance from toggles
- load_inputs() returns (None, StateProjection()) when project not found
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from audiomind.models.project_document import (
    MasterIntent,
    default_document,
)


# ─── Mock ProjectDocument ──────────────────────────────────────────────
class _MockProjectDocument:
    """Minimal mock for compile() tests when no real DB is available."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        # Ensure master_intent is always set for compile() tests
        if not hasattr(self, "master_intent") or self.master_intent is None:
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
    from audiomind.services.compile_project import StateProjection, compile
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
    assert plan.character is None


def test_compile_carries_a_known_character():
    from audiomind.models.project_document import MixIntent, default_document
    from audiomind.services.compile_project import StateProjection, compile

    doc = default_document()
    doc.mix_intent = MixIntent(character="commercial_alt_pop")
    plan = compile(doc, StateProjection())
    assert plan.character == "commercial_alt_pop"


def test_compile_drops_an_unknown_character():
    from audiomind.models.project_document import MixIntent, default_document
    from audiomind.services.compile_project import StateProjection, compile

    doc = default_document()
    doc.mix_intent = MixIntent(character="warm analog")
    plan = compile(doc, StateProjection())
    assert plan.character is None


def test_compile_defaults_to_no_character_without_a_document():
    from audiomind.services.compile_project import StateProjection, compile

    plan = compile(None, StateProjection())
    assert plan.character is None


def test_compile_no_doc_no_state_no_overrides():
    """compile(None, StateProjection()) with no document: all neutral."""
    from audiomind.services.compile_project import StateProjection, compile
    plan = compile(None, StateProjection())
    assert plan.stem_trims is None
    assert plan.dimension_enabled is True  # default
    assert plan.auto_balance is False  # default


def test_compile_all_zero_faders():
    """compile() with all faders 0.0 -> stem_trims = None (bypass)."""
    from audiomind.services.compile_project import StateProjection, compile
    state = StateProjection(faders={"drums_db": 0.0, "bass_db": 0.0, "other_db": 0.0, "vocals_db": 0.0})
    plan = compile(None, state)
    assert plan.stem_trims is None


def test_compile_some_nonzero_faders():
    """compile() with some non-zero faders -> stem_trims dict con claves {stem}_db."""
    from audiomind.services.compile_project import StateProjection, compile
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


# ─── load_inputs with a real (fake) client ───────────────────────────────


class _FakeTable:
    """Chainable PostgREST-shaped fake: select/eq/limit/execute."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self._filters: list[tuple[str, Any]] = []
        self._limit: int | None = None

    def select(self, _cols: str = "*") -> _FakeTable:
        return self

    def eq(self, column: str, value: Any) -> _FakeTable:
        self._filters.append((column, value))
        return self

    def limit(self, count: int) -> _FakeTable:
        self._limit = count
        return self

    def execute(self) -> SimpleNamespace:
        matched = [
            r for r in self._rows
            if all(r.get(c) == v for c, v in self._filters)
        ]
        if self._limit is not None:
            matched = matched[: self._limit]
        return SimpleNamespace(data=[dict(r) for r in matched])


class _FakeClient:
    """Supabase-shaped fake: ``table(name)`` backed by dicts of rows."""

    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self._tables = tables

    def table(self, name: str) -> _FakeTable:
        return _FakeTable(self._tables.get(name, []))


def _doc_row() -> dict[str, Any]:
    return {
        "project_id": "p1",
        "user_id": "user123",
        "document_json": default_document().model_dump(mode="json"),
    }


def test_load_inputs_ownership_miss_raises():
    """load_inputs raises ProjectNotFoundError when the project is not owned."""
    from audiomind.services.compile_project import (
        ProjectNotFoundError,
        load_inputs,
    )

    db = _FakeClient({"projects": []})
    with pytest.raises(ProjectNotFoundError):
        load_inputs("p1", "user123", client=db)


def test_load_inputs_parses_document_and_state():
    """load_inputs returns the stored document and the projected live state."""
    from audiomind.services.compile_project import load_inputs

    db = _FakeClient(
        {
            "projects": [{"id": "p1", "user_id": "user123"}],
            "project_documents": [_doc_row()],
            "project_states": [
                {
                    "project_id": "p1",
                    "state": {
                        "faders": {
                            "drums_db": -2.0,
                            "vocals_db": 1.5,
                            "bad_db": "loud",  # non-numeric: dropped
                        },
                        "toggles": {
                            "dimension_enabled": False,
                            "auto_balance": True,
                            "mute": {"drums": True},
                            "solo": {"vocals": True},
                        },
                    },
                }
            ],
        }
    )
    doc, state = load_inputs("p1", "user123", client=db)
    assert doc is not None
    assert doc.schema_version == 1
    # Only the two boolean toggles survive; mute/solo (dicts) are excluded.
    assert state.faders == {"drums_db": -2.0, "vocals_db": 1.5}
    assert state.toggles == {"dimension_enabled": False, "auto_balance": True}


def test_load_inputs_bad_stored_document_raises_value_error():
    """A document row that no longer validates is a server-side defect."""
    from audiomind.services.compile_project import load_inputs

    db = _FakeClient(
        {
            "projects": [{"id": "p1", "user_id": "user123"}],
            "project_documents": [
            {"project_id": "p1", "user_id": "user123",
             "document_json": {"schema_version": 99}}
        ],
        }
    )
    with pytest.raises(ValueError, match="stored project_document is invalid"):
        load_inputs("p1", "user123", client=db)


# ─── Integration-ish test ──────────────────────────────────────────────

def test_compile_full_pipeline():
    """End-to-end: compile with doc and state produces consistent MixPlan."""
    from audiomind.services.compile_project import MixPlan, StateProjection, compile

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