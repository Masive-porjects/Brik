"""Tests for the deterministic, producer-facing narrative.

The narrative is the text the producer reads after the audio comes back. Two
properties are the whole point, and both are pinned here:

* it comes from recorded evidence (``tool_log`` plus measured state), never
  from a template and never from the model -- the model already writes the
  diagnosis, and a second, unmeasured explanation would let the text contradict
  the audio the user is hearing;
* it is structured (a stable ``code`` plus numbers), so the studio renders it
  in the user's language and the backend never holds a translation table.
"""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from audiomind.models.audio import AnalysisResult
from audiomind.processing import agentic_loop as al
from audiomind.services.narrative import NarrativeItem, build_narrative


def _state(**kwargs: Any) -> al.AgentState:
    return al.AgentState(session_id="probe", input_path=Path("x.wav"), **kwargs)


def _analysis(**overrides: Any) -> AnalysisResult:
    fields: dict[str, Any] = {
        "integrated_lufs": -18.0,
        "true_peak_db": -1.0,
        "dynamic_range_db": 17.0,
        "spectral_centroid": 3000.0,
        "tempo_bpm": 120.0,
        "duration_seconds": 180.0,
        "sample_rate": 44100,
        "channels": 2,
        "crest_factor_db": 20.0,
    }
    fields.update(overrides)
    return AnalysisResult(**fields)


def _ok(tool: str, payload: dict[str, Any] | None = None) -> al.ToolResult:
    return al.ToolResult(ok=True, tool=tool, detail="", payload=payload or {})


def _fail(tool: str) -> al.ToolResult:
    return al.ToolResult.fail(tool, "explotó")


def _codes(items: list[NarrativeItem]) -> list[str]:
    return [item.code for item in items]


def _master_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": "mix",
        "attempt": 1,
        "integrated_lufs": -14.04,
        "true_peak_db": -1.0,
        "crest_factor_db": 9.0,
        "crest_delta_db": -3.0,
        "crest_warning": False,
        "reverted": False,
    }
    payload.update(overrides)
    return payload


class TestEvidenceOnly:
    def test_a_run_that_did_nothing_narrates_nothing(self):
        assert build_narrative(_state()) == []

    def test_the_numbers_are_rounded_for_display(self):
        state = _state(analysis=_analysis(integrated_lufs=-17.951, crest_factor_db=19.87))

        (item,) = build_narrative(state)

        assert item.code == "analyzed_original"
        assert item.params == {"lufs": -18.0, "crest": 19.9}

    def test_an_unmeasured_number_is_null_and_never_zero(self):
        """``None`` is not 0: printing 0.0 would invent a measurement."""
        state = _state()
        state.tool_log.append(
            _ok("send_to_master", _master_payload(true_peak_db=None))
        )

        (item,) = build_narrative(state)

        assert item.params["peak"] is None


class TestTheRoute:
    def test_the_short_route_is_stated_first(self):
        state = _state(
            decision=al.DecisionRecord(requested="auto", applied="master_only")
        )

        assert _codes(build_narrative(state)) == ["route_master_only"]

    def test_the_long_route_adds_no_item(self):
        """The steps already tell the story; a redundant header would be noise."""
        state = _state(
            decision=al.DecisionRecord(requested="auto", applied="mix_then_master")
        )

        assert build_narrative(state) == []


class TestTheMix:
    def test_separation_reports_the_real_stem_count(self):
        state = _state()
        state.stems = {name: f"{name}.wav" for name in ("vocals", "drums", "bass", "other")}
        state.tool_log.append(_ok("trigger_stem_separation"))

        (item,) = build_narrative(state)

        assert item.code == "separated"
        assert item.severity == "success"
        assert item.params == {"stems": 4}

    def test_a_render_and_a_clean_qc_are_two_distinct_events(self):
        state = _state(iteration=2)
        state.tool_log.append(_ok("render_mix", {"iteration": 2}))
        state.tool_log.append(
            _ok("analyze_mix_bus", {"iteration": 2, "qc_report": {"summary": {"flagged": []}}})
        )

        items = build_narrative(state)

        assert _codes(items) == ["mix_rendered", "mix_clean"]
        assert items[1].severity == "success"
        assert items[1].params == {"iteration": 2, "flags": 0}

    def test_a_flagged_qc_says_how_many_things_it_found(self):
        state = _state(iteration=1)
        state.tool_log.append(_ok("render_mix", {"iteration": 1}))
        state.tool_log.append(
            _ok(
                "analyze_mix_bus",
                {
                    "iteration": 1,
                    "qc_report": {"summary": {"flagged": ["muddy_250", "honky_500"]}},
                },
            )
        )

        items = build_narrative(state)

        assert items[1].code == "mix_flagged"
        assert items[1].severity == "warning"
        assert items[1].params["flags"] == 2

    def test_every_qc_reading_is_told_in_order(self):
        """Two readings are the real story: it was flagged, then it converged."""
        state = _state(iteration=2)
        state.tool_log.append(
            _ok("analyze_mix_bus", {"iteration": 1, "qc_report": {"summary": {"flagged": ["muddy_250"]}}})
        )
        state.tool_log.append(
            _ok("analyze_mix_bus", {"iteration": 2, "qc_report": {"summary": {"flagged": []}}})
        )

        assert _codes(build_narrative(state)) == ["mix_flagged", "mix_clean"]

    def test_the_knowledge_lookup_reports_its_fragment_count(self):
        state = _state()
        state.tool_log.append(_ok("search_knowledge", {"chunks": [{}, {}, {}]}))

        (item,) = build_narrative(state)

        assert item.code == "knowledge_consulted"
        assert item.params == {"fragments": 3}

    def test_reads_and_staged_knobs_do_not_narrate(self):
        """They touched nothing in the audio: an item would be a false claim."""
        state = _state()
        state.tool_log.extend(
            [
                _ok("analyze_original_audio"),
                _ok("adjust_stem_parameters"),
                _ok("analyze_master_output"),
            ]
        )

        assert build_narrative(state) == []


class TestTheMaster:
    def test_a_master_from_the_mix_names_its_source(self):
        state = _state()
        state.tool_log.append(_ok("send_to_master", _master_payload()))

        (item,) = build_narrative(state)

        assert item.code == "master_from_mix"
        assert item.severity == "success"
        assert item.params == {"attempt": 1, "lufs": -14.0, "peak": -1.0, "crest": 9.0}

    def test_a_master_from_the_original_is_a_different_sentence(self):
        state = _state()
        state.tool_log.append(_ok("send_to_master", _master_payload(source="original")))

        assert _codes(build_narrative(state)) == ["master_from_original"]

    def test_a_correction_is_its_own_event(self):
        state = _state()
        state.tool_log.append(_ok("send_to_master", _master_payload()))
        state.tool_log.append(
            _ok("send_to_master", _master_payload(attempt=2, integrated_lufs=-12.0))
        )

        items = build_narrative(state)

        assert _codes(items) == ["master_from_mix", "master_corrected"]
        assert items[1].params["attempt"] == 2
        assert items[1].params["lufs"] == -12.0

    def test_a_reverted_correction_is_not_reported_as_a_correction(self):
        """The pointer never moved: the user does not get that file."""
        state = _state()
        state.tool_log.append(_ok("send_to_master", _master_payload()))
        state.tool_log.append(
            _ok(
                "send_to_master",
                _master_payload(
                    attempt=2,
                    reverted=True,
                    crest_delta_db=-8.0,
                    crest_warning=True,
                ),
            )
        )

        items = build_narrative(state)

        assert _codes(items) == ["master_from_mix", "master_correction_reverted"]
        assert items[1].severity == "warning"
        assert items[1].params == {"attempt": 2, "crest_drop": 8.0}

    def test_a_squashed_first_master_is_kept_but_flagged(self):
        state = _state()
        state.tool_log.append(
            _ok(
                "send_to_master",
                _master_payload(crest_delta_db=-6.0, crest_warning=True),
            )
        )

        items = build_narrative(state)

        assert _codes(items) == ["master_from_mix", "master_dynamic_warning"]
        assert items[1].params == {"crest_drop": 6.0}

    def test_a_healthy_master_carries_no_warning(self):
        state = _state()
        state.tool_log.append(_ok("send_to_master", _master_payload()))

        assert _codes(build_narrative(state)) == ["master_from_mix"]


class TestFailures:
    def test_a_failed_step_is_named(self):
        state = _state()
        state.tool_log.append(_fail("render_mix"))

        (item,) = build_narrative(state)

        assert item.code == "step_failed"
        assert item.severity == "error"
        assert item.params == {"tool": "render_mix"}

    def test_a_failed_step_does_not_hide_the_steps_that_worked(self):
        state = _state()
        state.stems = {"vocals": "v.wav", "drums": "d.wav", "bass": "b.wav", "other": "o.wav"}
        state.tool_log.append(_ok("trigger_stem_separation"))
        state.tool_log.append(_fail("render_mix"))

        assert _codes(build_narrative(state)) == ["separated", "step_failed"]


class TestPayloadContract:
    def test_the_items_are_json_safe(self):
        state = _state()
        state.tool_log.append(_ok("send_to_master", _master_payload()))

        dumped = [item.model_dump(mode="json") for item in build_narrative(state)]

        assert dumped == [
            {
                "code": "master_from_mix",
                "severity": "success",
                "params": {"attempt": 1, "lufs": -14.0, "peak": -1.0, "crest": 9.0},
            }
        ]

    def test_the_item_rejects_unknown_fields(self):
        with pytest.raises(ValidationError):
            NarrativeItem(code="x", text="una frase suelta")
