"""Pydantic v2 models for the V1 project document.

Mirrors the JSON Schema in ``docs/reference/specs/project_document_v1_spec.md``
§3, which is the source of truth for the document shape. Two properties of that
schema are load-bearing and are reproduced here structurally rather than by
convention:

* ``structure.stems`` is an object with the four Demucs stems as REQUIRED
  keys — a payload with three, five or an extra ``snare`` key fails to
  validate at all.
* ``mix_intent.proposals`` entries are *pending intent*. They are never
  audible on their own: only the frontend store writes ``project_states``
  (ownership invariant I1), and a proposal becomes sound only after the user
  applies it there.

Everything in this module is English (docstrings, identifiers); user-facing HTTP
messages are Spanish and live in the API layer.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from audiomind.models.audio import MasteringParameters

#: The four Demucs stems, in the engine's order
#: (``processing/splitter.py``: ``STEM_NAMES``).
StemName = Literal["drums", "bass", "other", "vocals"]


class StemNode(BaseModel):
    """Identity and presentation of one stem (no audio, no gain)."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=64)
    order: int = Field(ge=0, le=3)
    group_id: str | None = None
    color_token: str | None = Field(default=None, max_length=64)
    hidden: bool = False


class StemBlock(BaseModel):
    """The four Demucs stems, keyed by name and all four REQUIRED.

    Making every stem a required key (with ``extra="forbid"``) is what makes
    "exactly the 4 Demucs stems, no more, no less" a STRUCTURAL constraint: a
    document with 3 stems, 5 stems, or a ``snare`` key does not validate at
    all. That is stronger than an array with min/max items, which cannot
    prevent duplicates or renamed keys, and it stops the document from
    promising stems the separation engine does not produce.
    """

    model_config = ConfigDict(extra="forbid")

    drums: StemNode
    bass: StemNode
    other: StemNode
    vocals: StemNode


class Group(BaseModel):
    """A UI grouping of stems (drag-and-drop folders in the Studio)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=64)
    order: int = Field(default=0, ge=0)
    color_token: str | None = Field(default=None, max_length=64)


class Structure(BaseModel):
    """Project structure: the 4 stems plus optional UI groups."""

    model_config = ConfigDict(extra="forbid")

    stems: StemBlock
    #: UI-only in V1: ``build_mix`` has no bus routing, so groups never reach
    #: the DSP. They exist so the Studio can lay out its own shelves.
    groups: list[Group] = Field(default_factory=list)


class Proposal(BaseModel):
    """A pending intent change proposed by the Intelligence.

    A proposal is NEVER audible by itself: it lives in the document, while the
    audible mix lives in ``project_states``, which only the frontend store
    writes (invariant I1). It becomes sound solely when the user applies its
    payload to ``project_states`` through the normal autosave path.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["fader", "toggle", "master"]
    payload: dict[str, Any]
    status: Literal["pending", "accepted", "rejected"]
    created_at: str
    rationale: str | None = Field(default=None, max_length=1024)
    decided_at: str | None = None

    @field_validator("id")
    @classmethod
    def _id_must_be_uuid(cls, value: str) -> str:
        """Reject any proposal id that is not a UUID."""
        try:
            uuid.UUID(value)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"proposal id must be a UUID, got {value!r}") from exc
        return value


class MixIntent(BaseModel):
    """The musical intent of the mix: style plus pending proposals."""

    model_config = ConfigDict(extra="forbid")

    genre: str | None = Field(default=None, max_length=64)
    character: str | None = Field(default=None, max_length=256)
    proposals: list[Proposal] = Field(default_factory=list)


class MasterIntent(BaseModel):
    """Delivery intent for the master job.

    The top-level fields mirror ``MasterJobPayload`` (``services/dsp_worker.py``)
    and NOT ``MasteringParameters`` (``models/audio.py``). In particular
    ``platform_target`` uses the 7-value payload set — spotify, apple_music,
    youtube, tidal, club, cd, custom — because the compiler projects it onto
    ``payload.platform_target``; ``MasteringParameters.platform_target`` only
    accepts 5 values (no ``club``/``cd``), so putting the 7-value set there
    would be rejected. The compiler therefore sets the payload field and never
    ``parameters.platform_target``.

    ``parameters`` is a PARTIAL overlay of ``MasteringParameters`` validated
    server-side as soon as the document is written (PUT), which surfaces a typo
    early; submit-time validation in the master job (WU5) remains the
    authoritative gate before any DSP runs.
    """

    model_config = ConfigDict(extra="forbid")

    preset_id: (
        Literal[
            "universal",
            "fuego",
            "claridad",
            "cinta",
            "natural",
            "espacial",
            "cinematico",
            "empuje",
        ]
        | None
    ) = None
    platform_target: (
        Literal[
            "spotify", "apple_music", "youtube", "tidal", "club", "cd", "custom"
        ]
        | None
    ) = None
    format: Literal["wav", "mp3"] = "wav"
    output_bit_depth: int = Field(default=24, ge=16, le=32)
    master_name: str | None = Field(default=None, max_length=128)
    parameters: dict[str, Any] | None = None

    @field_validator("parameters")
    @classmethod
    def _parameters_must_be_known_knobs(
        cls, value: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        """Reject unknown knobs, then let ``MasteringParameters`` judge values.

        ``MasteringParameters`` uses the default pydantic config, which
        SILENTLY IGNORES extra keyword arguments — so ``{"no_such_knob": 1}``
        would otherwise validate as an all-defaults instance and reach the
        compiler unnoticed. The explicit key check is therefore mandatory, not
        defensive. Only after it passes does the real model run, so bad types
        and out-of-range values raise from its own fields.
        """
        if value is None:
            return value
        known = MasteringParameters.model_fields
        for key in value:
            if key not in known:
                raise ValueError(
                    f"unknown mastering parameter {key!r}: not a "
                    "MasteringParameters field"
                )
        MasteringParameters(**value)
        return value


class ProjectDocument(BaseModel):
    """The stored V1 document: intention + structure of one project.

    Deliberately excludes timeline, automation and live faders — those belong
    to ``project_states`` (invariant I1). ``schema_version`` is pinned to 1;
    the server stamps ``updated_at`` (and this model's ``updated_by`` comes
    from the validated payload) on every write.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    structure: Structure
    mix_intent: MixIntent
    master_intent: MasterIntent
    updated_by: Literal["user", "intelligence", "system"] = "user"
    updated_at: str | None = None


def default_document() -> ProjectDocument:
    """Bootstrap document for a project with no stored row yet.

    Returned by ``GET`` as ``version: 0`` and NOT persisted: the row only comes
    into existence on the first ``PUT``. Display names follow the repo
    precedent of an English default (the ``'Untitled project'`` name in
    ``projects``) and the stem order mirrors ``STEM_NAMES`` in
    ``processing/splitter.py`` (drums, bass, other, vocals).
    """
    return ProjectDocument(
        schema_version=1,
        structure=Structure(
            stems=StemBlock(
                drums=StemNode(display_name="Drums", order=0),
                bass=StemNode(display_name="Bass", order=1),
                other=StemNode(display_name="Other", order=2),
                vocals=StemNode(display_name="Vocals", order=3),
            ),
        ),
        mix_intent=MixIntent(),
        master_intent=MasterIntent(),
        updated_by="user",
        updated_at=None,
    )
