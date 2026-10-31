"""Deterministic, producer-facing narrative of one agent run.

The loop records what it DID in ``AgentState.tool_log`` and what it MEASURED in
``analysis`` / ``render`` / ``master_payload``. This module turns that evidence
into an ordered list of things a person can read: "separé el audio en 4 stems",
"el control de calidad dio la mezcla por limpia", "el máster quedó en −14 LUFS".

Two decisions worth stating, because both are load-bearing.

**Structured items, not sentences.** Every item is a stable ``code`` plus the
numbers it needs. The studio renders them through ``useTranslation()``, so the
same run reads in Spanish or English without the backend holding a second
translation table next to ``es.json``/``en.json`` -- which ``AGENTS.md`` forbids.

**Deterministic, not the model.** The model already writes the diagnosis. If it
also wrote the explanation of the numbers, the text could contradict the audio
the user is hearing, and the producer would stop trusting both. Every item here
is backed by a recorded tool result or a measured field; nothing is inferred
from a value being populated.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from audiomind.processing.agentic_loop import AgentState, ToolResult

#: How many decimals a measurement travels with. One is what the studio shows,
#: and rounding here keeps the payload stable across float noise.
_DIGITS = 1


class NarrativeItem(BaseModel):
    """One thing that happened, ready to be rendered in any language."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(
        ...,
        description="Stable key the studio maps to a sentence (es.json/en.json).",
    )
    severity: Literal["info", "success", "warning", "error"] = "info"
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Numbers the sentence interpolates. Never prose.",
    )


def _num(value: Any) -> float | None:
    """A measurement rounded for display, or ``None`` when it was never taken.

    ``None`` is not zero: the studio must be able to say "sin medir" instead of
    printing a number the engine never produced.
    """
    return None if value is None else round(float(value), _DIGITS)


def _flagged(result: ToolResult) -> list[str]:
    """What the QC flagged in that result's render. Empty = clean."""
    report = result.payload.get("qc_report") or {}
    return list((report.get("summary") or {}).get("flagged") or [])


def _master_items(result: ToolResult) -> list[NarrativeItem]:
    """The master story: what the attempt measured and whether it survived.

    A reverted correction is NOT a correction: the pointer never moved and the
    previous master is still the delivered one. Reporting it as a successful
    correction would describe an audio file the user does not get.
    """
    payload = result.payload
    attempt = int(payload.get("attempt") or 1)
    crest_delta = payload.get("crest_delta_db")
    crest_drop = None if crest_delta is None else abs(float(crest_delta))

    if payload.get("reverted"):
        return [
            NarrativeItem(
                code="master_correction_reverted",
                severity="warning",
                params={"attempt": attempt, "crest_drop": _num(crest_drop)},
            )
        ]

    if attempt > 1:
        code = "master_corrected"
    elif payload.get("source") == "mix":
        code = "master_from_mix"
    else:
        code = "master_from_original"

    items = [
        NarrativeItem(
            code=code,
            severity="success",
            params={
                "attempt": attempt,
                "lufs": _num(payload.get("integrated_lufs")),
                "peak": _num(payload.get("true_peak_db")),
                "crest": _num(payload.get("crest_factor_db")),
            },
        )
    ]
    if payload.get("crest_warning"):
        items.append(
            NarrativeItem(
                code="master_dynamic_warning",
                severity="warning",
                params={"crest_drop": _num(crest_drop)},
            )
        )
    return items


def build_narrative(state: AgentState) -> list[NarrativeItem]:
    """The run, step by step, in the order it really happened.

    Reads only ``tool_log`` and measured state. The order is the execution
    order, not a template: a run that never separated has no separation item.

    Three tools deliberately produce no item, because they are reads or
    intermediate knobs, not things that happened to the audio:
    ``analyze_original_audio`` (the ``analyzed_original`` item already carries
    its numbers), ``analyze_master_output`` (it reads a master that has its own
    item) and ``adjust_stem_parameters`` (it only stages the next render).
    """
    items: list[NarrativeItem] = []

    if state.decision.applied == "master_only":
        items.append(NarrativeItem(code="route_master_only"))

    analysis = state.analysis
    if analysis is not None:
        items.append(
            NarrativeItem(
                code="analyzed_original",
                params={
                    "lufs": _num(analysis.integrated_lufs),
                    "crest": _num(analysis.crest_factor_db),
                },
            )
        )

    for result in state.tool_log:
        if not result.ok:
            items.append(
                NarrativeItem(
                    code="step_failed",
                    severity="error",
                    params={"tool": result.tool},
                )
            )
            continue

        if result.tool == "trigger_stem_separation":
            items.append(
                NarrativeItem(
                    code="separated",
                    severity="success",
                    params={"stems": len(state.stems)},
                )
            )
        elif result.tool == "render_mix":
            items.append(
                NarrativeItem(
                    code="mix_rendered",
                    severity="success",
                    params={
                        "iteration": result.payload.get("iteration")
                        or state.iteration
                    },
                )
            )
        elif result.tool == "analyze_mix_bus":
            flagged = _flagged(result)
            items.append(
                NarrativeItem(
                    code="mix_flagged" if flagged else "mix_clean",
                    severity="warning" if flagged else "success",
                    params={
                        "iteration": result.payload.get("iteration")
                        or state.iteration,
                        "flags": len(flagged),
                    },
                )
            )
        elif result.tool == "search_knowledge":
            items.append(
                NarrativeItem(
                    code="knowledge_consulted",
                    params={"fragments": len(result.payload.get("chunks") or [])},
                )
            )
        elif result.tool == "send_to_master":
            items.extend(_master_items(result))

    return items
