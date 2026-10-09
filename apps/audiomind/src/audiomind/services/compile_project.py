"""Compile project: load document + state, produce MixPlan.

Pure function: no I/O, no writes. Reads project document and state,
produces a MixPlan for the DSP pipeline.

Spec §5 — The compiler is a pure function. load_inputs may have side effects
(reading from the database) but compile() itself is guaranteed pure.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

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

    # ── para MasterJobPayload (services/dsp_worker.py:68) ──
    preset_id: str | None = None  # Literal[8 presets]
    platform_target: str | None = None  # set de 7, top-level del payload
    format: str = "wav"  # default "wav"
    output_bit_depth: int = 24  # default 24
    master_name: str | None = None
    parameters: MasteringParameters | None = None  # overlay validado por Pydantic


def load_inputs(
    project_id: str, user_id: str
) -> tuple[Optional[ProjectDocument], StateProjection]:
    """Carga document + state para un proyecto y usuario dados.

    Verifica ownership (404/403) y devuelve el documento V1 y la proyección
    del state con defaults neutrales. Si no hay documento, devuelve None
    y un StateProjection con defaults totales.

    En producción este función usaría el cliente Supabase token-scoped;
    aquí devolvemos un documento de ejemplo para que el módulo sea importable.
    """
    # --- Ownership check (mismo patrón que api/projects.py) ---
    # from audiomind.api.projects import _client_for, _data, _get_owned_project
    # client = _client_for(...)
    # doc_row = _get_owned_project(client, project_id, user_id)
    # Si no existe -> return (None, StateProjection())
    # Cargar document_json y state del row

    # --- De momento, devolvemos defaults para que el módulo sea importable ---
    doc: Optional[ProjectDocument] = None
    state = StateProjection()
    return doc, state


def compile(document: Optional[ProjectDocument], state: StateProjection) -> MixPlan:
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
        name = db_key[:-3]  # Quita el sufijo _db para obtener el nombre del stem
        val = state.faders.get(db_key, 0.0)
        if isinstance(val, (int, float)) and val != 0.0:
            trim_dict[db_key] = float(val)
    stem_trims: dict[str, float] | None = trim_dict if trim_dict else None

    # 2. dimension_enabled y auto_balance de toggles
    dimension_enabled: bool = state.toggles.get("dimension_enabled", True)
    auto_balance: bool = state.toggles.get("auto_balance", False)

    # 3. preset_id, platform_target, format, output_bit_depth, master_name
    #    del master_intent del documento (si existe)
    preset_id: Optional[str] = None
    platform_target: Optional[str] = None
    fmt: str = "wav"
    output_bit_depth: int = 24
    master_name: Optional[str] = None

    if document is not None:
        mi = document.master_intent
        preset_id = mi.preset_id
        platform_target = mi.platform_target
        fmt = mi.format
        output_bit_depth = mi.output_bit_depth
        master_name = mi.master_name

    # 4. parameters: overlay de MasteringParameters
    parameters: Optional[MasteringParameters] = None
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
        preset_id=preset_id,
        platform_target=platform_target,
        format=fmt,
        output_bit_depth=output_bit_depth,
        master_name=master_name,
        parameters=parameters,
    )