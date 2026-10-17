"""Compile project: load document + state, produce MixPlan.

Pure function: no I/O, no writes. Reads project document and state,
produces a MixPlan for the DSP pipeline.

Spec §5 — The compiler is a pure function. load_inputs may have side effects
(reading from the database) but compile() itself is guaranteed pure.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError

from audiomind.models.audio import MasteringParameters
from audiomind.models.project_document import ProjectDocument
from audiomind.processing.character import is_known_profile


class StateProjection(BaseModel):
    """Lo mínimo que el compiler exige de project_states.state, con defaults
    neutrales. Cualquier campo ausente o fuera de rango cae al default."""

    faders: dict[str, float] = Field(
        default_factory=dict
    )  # {stem}_db -> dB. Ej: {"drums_db": -2.0, "bass_db": 1.5, ...}
    toggles: dict[str, bool] = Field(
        default_factory=lambda: {"dimension_enabled": True, "auto_balance": False}
    )


class MixPlan(BaseModel):
    """Plan de mezcla listo para ser inyectado en build_mix o en un job DSP."""

    # ── para build_mix (processing/mix_engine.py:490) ──
    stem_trims: dict[str, float] | None = None  # None si todo es 0.0 (neutral)
    dimension_enabled: bool = True  # -> dimension_profiles: None | {}
    auto_balance: bool = False
    character: str | None = None  # P5: known profile name, or None (neutral)

    # ── para MasterJobPayload (services/dsp_worker.py:68) ──
    preset_id: str | None = None  # Literal[8 presets]
    platform_target: str | None = None  # set de 7, top-level del payload
    format: str = "wav"  # default "wav"
    output_bit_depth: int = 24  # default 24
    master_name: str | None = None
    parameters: MasteringParameters | None = None  # overlay validado por Pydantic


class ProjectNotFoundError(Exception):
    """The project is not owned by the user (or does not exist)."""


def _rows(resp: Any) -> list[dict[str, Any]]:
    """Rows from a PostgREST response, tolerating empty/None payloads."""
    rows = getattr(resp, "data", None)
    if not rows:
        return []
    if isinstance(rows, dict):
        return [rows]
    return [row for row in rows if isinstance(row, dict)]


def load_inputs(
    project_id: str,
    user_id: str,
    client: Any = None,
) -> tuple[ProjectDocument | None, StateProjection]:
    """Load document + state for a project owned by the user.

    With no ``client`` (unit tests, importability) the neutral
    ``(None, StateProjection())`` is returned. With a client, ownership is a
    ``projects`` SELECT filtered by user: a miss raises
    :class:`ProjectNotFoundError`. A stored ``project_documents`` row must
    validate against schema V1 (a stored row that no longer validates is a
    server-side defect and raises ``ValueError``). The state row is projected
    onto :class:`StateProjection` taking ONLY the two boolean toggles --
    ``mute``/``solo`` are dicts and must never enter ``toggles``.
    """
    if client is None:
        return None, StateProjection()

    owned = (
        client.table("projects")
        .select("id,user_id")
        .eq("id", project_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not _rows(owned):
        raise ProjectNotFoundError(f"project {project_id} is not owned by {user_id}")

    doc: ProjectDocument | None = None
    doc_rows = _rows(
        client.table("project_documents")
        .select("document_json")
        .eq("project_id", project_id)
        .limit(1)
        .execute()
    )
    if doc_rows:
        try:
            doc = ProjectDocument.model_validate(doc_rows[0].get("document_json"))
        except ValidationError as exc:
            raise ValueError(f"stored project_document is invalid: {exc}") from exc

    state = StateProjection()
    state_rows = _rows(
        client.table("project_states")
        .select("state")
        .eq("project_id", project_id)
        .limit(1)
        .execute()
    )
    if state_rows:
        raw = state_rows[0].get("state") or {}
        faders = {
            k: float(v)
            for k, v in (raw.get("faders") or {}).items()
            if isinstance(v, (int, float))
        }
        toggles_raw = raw.get("toggles") or {}
        toggles = {
            "dimension_enabled": bool(toggles_raw.get("dimension_enabled", True)),
            "auto_balance": bool(toggles_raw.get("auto_balance", False)),
        }
        state = StateProjection(faders=faders, toggles=toggles)
    return doc, state


def compile(document: ProjectDocument | None, state: StateProjection) -> MixPlan:
    """PURO: compila (document, state) -> MixPlan.

    - state ausente/vacío -> defaults neutrales (0 dB, dimension on, balance off).
    - document ausente -> estructura derivada de audio_assets kind='stem'
      + master_intent en defaults.
    - stem_trims -> None si los 4 stems tienen fader 0.0 (neutral = bypass).
    - platform_target usa el set de 7 del payload (document master_intent),
      NOT el set de 5 de MasteringParameters.
    - parameters: si el documento tiene parameters, intentamos construir
      MasteringParameters(**parameters); si falla (clave desconocida o valor
      fuera de rango), devolvemos None y el llamado endpoint hará la
      validación completa al submit el job.
    """

    stem_names = ("drums", "bass", "other", "vocals")
    db_keys = (f"{n}_db" for n in stem_names)  # drums_db, bass_db, other_db, vocals_db

    # 1. stem_trims: check los 4 stems con su sufijo _db
    trim_dict: dict[str, float] = {}
    for db_key in db_keys:
        val = state.faders.get(db_key, 0.0)
        if isinstance(val, (int, float)) and val != 0.0:
            trim_dict[db_key] = float(val)
    stem_trims: dict[str, float] | None = trim_dict if trim_dict else None

    # 2. dimension_enabled y auto_balance de toggles
    dimension_enabled: bool = state.toggles.get("dimension_enabled", True)
    auto_balance: bool = state.toggles.get("auto_balance", False)

    # 2b. character (P5): publish the document's declared profile, but only if
    #     it actually names a profile this engine implements. The document field
    #     is a free-text descriptor (max 256 chars, sibling of genre), so an
    #     unknown value is a description, not an interrupted instruction, and
    #     leaves character=None (the neutral render).
    character: str | None = None
    if document is not None:
        mix_intent = getattr(document, "mix_intent", None)
        declared = (
            getattr(mix_intent, "character", None)
            if mix_intent is not None
            else None
        )
        if isinstance(declared, str) and is_known_profile(declared):
            character = declared

    # 3. preset_id, platform_target, format, output_bit_depth, master_name
    #    del master_intent del documento (si existe)
    preset_id: str | None = None
    platform_target: str | None = None
    fmt: str = "wav"
    output_bit_depth: int = 24
    master_name: str | None = None

    if document is not None:
        mi = document.master_intent
        preset_id = mi.preset_id
        platform_target = mi.platform_target
        fmt = mi.format
        output_bit_depth = mi.output_bit_depth
        master_name = mi.master_name

    # 4. parameters: overlay de MasteringParameters
    parameters: MasteringParameters | None = None
    if document is not None and document.master_intent.parameters is not None:
        try:
            parameters = MasteringParameters(
                **document.master_intent.parameters
            )
        except Exception:
            # unknown key or type error: devolver None y dejar validación
            # para el submit en tiempo de ejecución (WU5 endpoint)
            parameters = None

    return MixPlan(
        stem_trims=stem_trims,
        dimension_enabled=dimension_enabled,
        auto_balance=auto_balance,
        character=character,
        preset_id=preset_id,
        platform_target=platform_target,
        format=fmt,
        output_bit_depth=output_bit_depth,
        master_name=master_name,
        parameters=parameters,
    )