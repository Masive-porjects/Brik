"""Agentic mix loop — el agente orquesta el flujo Mix -> Master por Tool Calling.

Reemplaza el flujo lineal (`build_mix` -> `process_audio`) por un flujo donde un
agente LLM decide paso a paso, actuando como un ingeniero:

    ┌─ FASE 1 · DIAGNÓSTICO ──────────────────────────────────────────────┐
    │  analyze_original_audio  ->  métricas del estéreo, sin separar nada │
    │  El LLM redacta el diagnóstico en lenguaje natural desde las cifras │
    ├─ FASE 2 · DESMONTAJE ───────────────────────────────────────────────┤
    │  trigger_stem_separation -> 4 stems de Demucs, cacheados en disco   │
    ├─ FASE 3 · BUCLE DE MEZCLA (máx MAX_MIX_ITERATIONS) ─────────────────┤
    │  render_mix            -> construye el bus (único punto con costo)  │
    │  analyze_mix_bus       -> lee qc_report/balance_report del render   │
    │  adjust_stem_parameters-> IntentProfile -> mix_mapper -> faders     │
    │  search_knowledge      -> evidencia citada del RAG (si hay RAG)     │
    ├─ FASE 4 · CIERRE ──────────────────────────────────────────────────┤
    │  send_to_master        -> empuja el bus al mastering engine         │
    └─────────────────────────────────────────────────────────────────────┘

Desviaciones deliberadas de la spec original (evidencia en
``odd/tasks/agentic-mix-loop.md`` § Correcciones):

* ``render_mix`` es una herramienta NUEVA. Sin ella el bucle no itera:
  ``adjust_stem_parameters`` solo muta intención, no audio.
* ``analyze_mix_bus`` NO llama a ``quality_checks.run_qc_checks``. Lee los
  reportes que ``build_mix`` ya calcula en la misma pasada
  (``mix_engine.py:1205`` ``qc_report``, ``:1236`` ``balance_report``).
  ``run_qc_checks`` exige el bus POST-bus-compressor
  (``quality_checks.py:183-189``): audita lo que se entrega. Medir un
  sumatorio de stems daría cifras que no son las del mix entregado.
* ``search_knowledge`` es la SEXTA herramienta que la spec no listaba. Sin
  ella el endpoint del RAG (``api/agent.py``) queda huérfano y el modelo nunca
  ve la evidencia que el proyecto indexó. Es opcional: sin un callable de RAG
  inyectado, no se registra y el agente ve exactamente las seis pedidas.
* Faders/ecualización se mueven SOLO vía ``IntentProfile`` -> ``mix_mapper``.
  El LLM nunca emite knobs (``docs/archive/PLAN.md:70``).

El transporte del LLM vive en ``audiomind.processing.gemini_transport`` y se
importa de forma diferida en ``default_transport`` para no crear un ciclo.
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from audiomind.analysis.analyzer import analyze_audio
from audiomind.analysis.verdict import AudioVerdict
from audiomind.config import settings
from audiomind.models.audio import AnalysisResult, ReferenceComparison
from audiomind.models.intent_profile import IntentProfile
from audiomind.processing import prompts
from audiomind.processing.character import CHARACTER_PROFILE, is_known_profile
from audiomind.processing.engine import process_audio
from audiomind.processing.mapper import map_intent_to_mastering
from audiomind.processing.mix_engine import build_mix
from audiomind.processing.mix_mapper import MixSettings, map_intent_to_mix
from audiomind.processing.splitter import STEM_NAMES, split_audio
from audiomind.session_store import load_sessions

log = logging.getLogger(__name__)

#: Tope duro de iteraciones del bucle de mezcla (S3.c).
MAX_MIX_ITERATIONS = 3

#: Intentos de máster por corrida: el primero + UNA corrección acotada.
#: La spec (§13.4.7) permite una sola corrección por pasada — medir, mover UN
#: parámetro, volver a medir, parar. El techo es presupuesto real: se gasta.
MAX_MASTER_ITERATIONS = 2

#: Guardrail dinámico (§13.4.8): si el crest factor del máster baja más que
#: esto respecto del audio que ENTRA al máster, el intento se revierte.
MAX_CREST_DROP_DB = 4.0

#: Tolerancia de sonoridad. El motor apunta a ``target_lufs_db``; errarle más
#: que esto es una medición que no convergió.
MAX_LUFS_ERROR_DB = 1.0

#: Techo de true peak. Por encima de esto el máster pide clipping en la
#: decodificación del consumidor.
MAX_TRUE_PEAK_DB = -1.0

#: Turnos de la ventana de corrección: una lectura + una corrección. Un techo
#: duro, para que un modelo charlatán no gaste turnos sin converger.
MAX_FEEDBACK_TURNS = 2

#: Lo único que puede llamar el modelo dentro de la ventana de corrección.
#: ``render_mix`` afuera: la corrección es del máster, no una re-mezcla.
MASTER_FEEDBACK_TOOLS: tuple[str, ...] = (
    "analyze_master_output",
    "send_to_master",
)

#: Los knobs que ``send_to_master`` puede mover. Una corrección cambia UNO.
_MASTER_KNOBS: tuple[str, ...] = ("target_lufs_db", "output_bit_depth")

#: Consulta al RAG: ``(query, k) -> [{"citation", "text", "book_id", ...}]``.
#: Sin inyección, el agente no ve la herramienta de conocimiento.
RAGQuery = Callable[[str, int], list[dict[str, Any]]]

ToolName = Literal[
    "analyze_original_audio",
    "trigger_stem_separation",
    "render_mix",
    "analyze_mix_bus",
    "adjust_stem_parameters",
    "search_knowledge",
    "send_to_master",
]


# ══════════════════════════════════════════════════════════════════════════
# Definiciones Pydantic para el Tool Calling (S2)
# ══════════════════════════════════════════════════════════════════════════
# Cada modelo es el ARGUMENTO de una herramienta. `extra="forbid"` es la misma
# disciplina que `IntentProfile`: un argumento inventado por el modelo es un bug
# del modelo, no un valor a ignorar silenciosamente.


class AnalyzeOriginalAudioArgs(BaseModel):
    """S2.1 — análisis del estéreo original, SIN separar."""

    model_config = ConfigDict(extra="forbid")

    file_path: str = Field(..., description="Ruta del audio original a analizar.")


class TriggerStemSeparationArgs(BaseModel):
    """S2.2 — separación a 4 stems con Demucs."""

    model_config = ConfigDict(extra="forbid")

    file_path: str = Field(..., description="Ruta del audio a separar.")


class RenderMixArgs(BaseModel):
    """Render del bus con la intención pendiente. Único punto con costo real."""

    model_config = ConfigDict(extra="forbid")

    with_versions: bool = Field(
        False,
        description="Renderizar las 5 versiones derivadas (vocal_up, instrumental, "
        "tv_mix...). Costoso y NO necesario dentro del bucle.",
    )
    character: str | None = Field(
        None,
        description="Perfil de carácter (atmósfera) del render. None = etapa "
        "Character apagada: el bus queda idéntico al render sin carácter.",
    )
    character_seed: int | None = Field(
        None,
        description="Semilla del lecho estocástico del carácter. Solo se aplica "
        "si se pidió un perfil.",
    )

    @field_validator("character")
    @classmethod
    def _validate_character(cls, value: str | None) -> str | None:
        """Mismo contrato estricto que ``MixJobRequest``: un perfil desconocido
        es un argumento inválido, no un no-op silencioso."""
        if value is None or is_known_profile(value):
            return value
        raise ValueError(
            f"character {value!r} not allowed; expected {CHARACTER_PROFILE!r}"
        )


class AnalyzeMixBusArgs(BaseModel):
    """S2.3 — lectura de los reportes del último render. Sin side effects."""

    model_config = ConfigDict(extra="forbid")


class AdjustStemParametersArgs(BaseModel):
    """S2.4 — ajuste de faders/ecualización vía intención semántica.

    Nota de contrato: el agente mueve los 9 ejes del ``IntentProfile``, nunca
    valores en dB. El mapper decide qué parámetro toca cada eje.
    """

    model_config = ConfigDict(extra="forbid")

    intent: IntentProfile = Field(
        ...,
        description="Perfil de intención completo. Los ejes en 0.5 son neutrales.",
    )
    rationale: str = Field(
        "",
        max_length=400,
        description="Por qué el agente mueve estos ejes (trazabilidad del bucle).",
    )


class SearchKnowledgeArgs(BaseModel):
    """Consulta al RAG local. Sólo disponible si se inyectó un ``RAGQuery``."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ..., min_length=2, max_length=400, description="Qué busca el agente."
    )
    k: int = Field(5, ge=1, le=20, description="Fragmentos a devolver.")


class SendToMasterArgs(BaseModel):
    """S2.5 — cierre: empuja el bus (u original) al mastering engine."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["mix", "original"] = Field(
        "mix", description="Qué se masteriza. 'mix' exige un render completado."
    )
    target_lufs_db: float | None = Field(
        None, ge=-24.0, le=0.0, description="Sonoridad objetivo. None = automático."
    )
    output_bit_depth: Literal[16, 24, 32] = 24


class AnalyzeMasterOutputArgs(BaseModel):
    """S2.6 — lectura de las métricas del máster vigente. Sin side effects."""

    model_config = ConfigDict(extra="forbid")


TOOL_ARG_MODELS: dict[str, type[BaseModel]] = {
    "analyze_original_audio": AnalyzeOriginalAudioArgs,
    "trigger_stem_separation": TriggerStemSeparationArgs,
    "render_mix": RenderMixArgs,
    "analyze_mix_bus": AnalyzeMixBusArgs,
    "adjust_stem_parameters": AdjustStemParametersArgs,
    "search_knowledge": SearchKnowledgeArgs,
    "send_to_master": SendToMasterArgs,
    "analyze_master_output": AnalyzeMasterOutputArgs,
}

#: Herramientas que la spec pidió (S2). ``search_knowledge`` queda afuera: es
#: la extensión opcional que puentea la capa de conocimiento.
_SPEC_TOOLS: tuple[str, ...] = (
    "analyze_original_audio",
    "trigger_stem_separation",
    "render_mix",
    "analyze_mix_bus",
    "adjust_stem_parameters",
    "send_to_master",
)

_TOOL_DOCS: dict[str, str] = {
    "analyze_original_audio": (
        "Mide el archivo estéreo original (LUFS, true peak, rango dinámico, "
        "centroide espectral, tempo, crest, género detectado) SIN separar. "
        "Usar primero, en Fase 1."
    ),
    "trigger_stem_separation": (
        "Separa el audio en 4 stems (vocals, drums, bass, other) con Demucs. "
        "Es caro y lento: invocar una sola vez, en Fase 2, cuando ya exista "
        "diagnóstico."
    ),
    "render_mix": (
        "Construye el bus de mezcla con la intención ajustada y devuelve su "
        "ruta. Es la operación más costosa del bucle: llamarla solo después "
        "de adjust_stem_parameters. Acepta un perfil de carácter opcional "
        "(atmósfera deliberada, no un eje de intención); sin perfil, la etapa "
        "Character queda apagada y el bus es idéntico al render sin carácter."
    ),
    "analyze_mix_bus": (
        "Devuelve qc_report y balance_report del último render (mono, fase, "
        "sibilancia 5k, muddy 250, honky 500, low-level listen, LUFS por "
        "stem). Lectura pura, sin costo."
    ),
    "adjust_stem_parameters": (
        "Mueve los faders y la ecualización a partir de los 9 ejes de "
        "intención. Nunca acepta valores en dB: el mapper traduce."
    ),
    "search_knowledge": (
        "Busca en los manuales de mezcla indexados y devuelve fragmentos "
        "citables (libro, página). Usar para justificar una decisión con "
        "evidencia, no para mover ejes."
    ),
    "send_to_master": (
        "Cierra la mezcla y empuja el bus al mastering engine. Última "
        "llamada, Fase 4."
    ),
    "analyze_master_output": (
        "Devuelve LUFS integrado, true peak, crest, LRA y el delta de crest "
        "contra la entrada del máster vigente, más cuántas correcciones "
        "quedan. Lectura pura, sin costo."
    ),
}


def tool_definitions(
    *, include_rag: bool = False, names: tuple[str, ...] | None = None
) -> list[dict[str, Any]]:
    """Definiciones listas para el `tools=[...]` de Gemini function calling.

    El JSON Schema sale de Pydantic — una sola fuente de verdad entre el
    schema que ve el modelo y el modelo que valida la respuesta.

    ``names`` acota la lista: la ventana de corrección del máster expone sólo
    sus dos herramientas, para que el modelo no vuelva a mezclar.
    """
    if names is not None:
        selected = list(names)
    else:
        selected = [*_SPEC_TOOLS, "search_knowledge"] if include_rag else list(_SPEC_TOOLS)
    return [
        {
            "name": name,
            "description": _TOOL_DOCS[name],
            "parameters": TOOL_ARG_MODELS[name].model_json_schema(),
        }
        for name in selected
    ]


class ToolResult(BaseModel):
    """Envelope único de toda herramienta: el modelo nunca ve una excepción."""

    ok: bool
    tool: str
    detail: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

    @classmethod
    def fail(cls, tool: str, error: str) -> ToolResult:
        return cls(ok=False, tool=tool, detail=error, error=error)


# ══════════════════════════════════════════════════════════════════════════
# La decisión de ruta (S5, S10)
# ══════════════════════════════════════════════════════════════════════════

#: La ruta que el usuario pide. ``auto`` delega en el veredicto de Brik; las
#: otras dos son la última palabra del usuario y pisan lo que Brik opine.
Decision = Literal["auto", "mix_then_master", "master_only"]

#: La ruta que REALMENTE se corrió. ``auto`` nunca llega acá: se resuelve.
AppliedDecision = Literal["mix_then_master", "master_only"]


class DecisionRecord(BaseModel):
    """Qué se pidió y qué se aplicó — las dos, porque no siempre coinciden.

    ``requested="auto"`` con ``applied="master_only"`` es la UI diciendo "Brik
    eligió la ruta corta, y podés cambiarla". Colapsar los dos campos en un
    solo valor borraría justo la información que hace explicable la decisión.
    """

    model_config = ConfigDict(extra="forbid")

    requested: Decision = Field(
        "auto",
        description="Lo que pidió el usuario. 'auto' = decidir con el veredicto.",
    )
    applied: AppliedDecision = Field(
        ..., description="La ruta que efectivamente se ejecutó."
    )


# ══════════════════════════════════════════════════════════════════════════
# Estado del agente
# ══════════════════════════════════════════════════════════════════════════


@dataclass
class AgentState:
    """Todo lo que el agente acumula entre llamadas a herramientas."""

    session_id: str
    input_path: Path

    #: Consulta al RAG. ``None`` = el agente no ve ``search_knowledge``.
    rag: RAGQuery | None = None

    #: Veredicto de Brik sobre este audio (``audiomind.analysis.verdict``).
    #: ``None`` = nadie lo calculó, y la compuerta cae en el comportamiento
    #: histórico de cuatro fases. Es el artefacto que explica la ruta elegida.
    verdict: AudioVerdict | None = None

    #: Comparación contra la referencia que subió el usuario. ``None`` = no hay
    #: referencia. Antes de esta feature la referencia moría en la sesión: se
    #: persistía en ``SessionData`` y nunca llegaba al modelo que decide.
    reference_comparison: ReferenceComparison | None = None

    #: ``True`` cuando la referencia subida ya está masterizada. Fuerza la ruta
    #: corta: comparar dos masters no justifica re-mezclar.
    reference_is_mastered: bool = False

    # S5/S10 — qué ruta se pidió y cuál se aplicó.
    decision: DecisionRecord = field(
        default_factory=lambda: DecisionRecord(
            requested="auto", applied="mix_then_master"
        )
    )

    # Fase 1
    analysis: AnalysisResult | None = None
    diagnosis: str | None = None
    # Fase 2
    stems: dict[str, str] = field(default_factory=dict)
    # Fase 3
    intent: IntentProfile = field(default_factory=IntentProfile.neutral)
    pending_settings: MixSettings | None = None
    render: dict[str, Any] | None = None
    iteration: int = 0
    # Fase 4
    mix_path: str | None = None
    master_path: str | None = None

    #: Payload del máster VIGENTE (el que ``master_path`` apunta hoy). Un
    #: intento revertido por el guardrail de crest NO lo reemplaza: su archivo
    #: queda en disco como evidencia, pero no es el máster del usuario.
    master_payload: dict[str, Any] | None = None
    #: Args con los que se hizo el último máster ACEPTADO. Una corrección tiene
    #: que diferir en exactamente un knob: "mover un parámetro" hecho código,
    #: no una sugerencia del prompt.
    master_args: dict[str, Any] | None = None
    #: Intentos exitosos de masterización, revertidos incluidos. Es el
    #: presupuesto que consume ``MAX_MASTER_ITERATIONS``.
    master_runs: int = 0

    #: Todo ``ToolResult`` que pasó por ``dispatch``, en orden de ejecución.
    #: Es la evidencia de "qué corrió y cómo salió": se registra, no se deduce
    #: del estado resultante (deducir "se separó" de que hay 4 stems es una
    #: inferencia, no un hecho medido).
    tool_log: list[ToolResult] = field(default_factory=list)

    @property
    def stems_dir(self) -> Path:
        """Debe coincidir EXACTAMENTE con `mix_engine.py:741`, o se pierde."""
        return settings.output_dir / self.session_id / "stems"

    @property
    def can_master(self) -> bool:
        """Espejo de la regla de la API: solo un mix `completed` se puede masterizar."""
        return self.mix_path is not None and self.render is not None


# ══════════════════════════════════════════════════════════════════════════
# Implementación de herramientas
# ══════════════════════════════════════════════════════════════════════════


def _analyze_original_audio(
    state: AgentState, args: AnalyzeOriginalAudioArgs
) -> ToolResult:
    """S2.1 — métricas del original. No separa nada."""
    try:
        state.analysis = analyze_audio(args.file_path)
    except Exception as exc:  # noqa: BLE001 — el envelope absorbe el fallo
        return ToolResult.fail("analyze_original_audio", f"análisis falló: {exc}")

    a = state.analysis
    return ToolResult(
        ok=True,
        tool="analyze_original_audio",
        detail="Métricas del estéreo original listas para diagnóstico.",
        payload={
            "integrated_lufs": a.integrated_lufs,
            "true_peak_db": a.true_peak_db,
            "dynamic_range_db": a.dynamic_range_db,
            "spectral_centroid": a.spectral_centroid,
            "crest_factor_db": a.crest_factor_db,
            "tempo_bpm": a.tempo_bpm,
            "detected_genre": a.detected_genre,
            "genre_confidence": a.genre_confidence,
            "is_already_mastered": a.is_already_mastered,
            "mastering_confidence": a.mastering_confidence,
            # Fase 2 lo necesita tal cual: `build_mix` sólo separa este archivo.
            "input_path": str(state.input_path),
        },
    )


def _trigger_stem_separation(
    state: AgentState, args: TriggerStemSeparationArgs
) -> ToolResult:
    """S2.2 — separa a 4 stems y los deja en el dir que `build_mix` consume.

    No usa `separate_jobs.py`: ese camino es asíncrono, durable y escribe en R2,
    y `build_mix` re-separaría de todos modos (`mix_engine.py:742`). Al escribir
    en `settings.output_dir/<session_id>/stems` con los mismos argumentos, el
    manifiesto de `splitter` hace que el render posterior reúse estos stems en
    vez de volver a pagar Demucs.
    """
    requested = Path(args.file_path)
    if requested.resolve() != state.input_path.resolve():
        # `build_mix` separa SIEMPRE `state.input_path` en `state.stems_dir`.
        # Separar otro archivo no alimenta el render y paga Demucs en vano; el
        # manifiesto no matchearía y la caché se perdería en silencio.
        return ToolResult.fail(
            "trigger_stem_separation",
            "file_path debe ser el input de la sesión "
            f"({state.input_path}), porque build_mix sólo separa ese archivo.",
        )

    try:
        started = time.perf_counter()
        result = split_audio(args.file_path, output_dir=state.stems_dir)
        elapsed = time.perf_counter() - started
        state.stems = {name: str(p) for name, p in result["stems"].items()}
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail("trigger_stem_separation", f"separación falló: {exc}")

    cache_hit = bool(result.get("cache_hit"))
    log.info(
        "[TIMING] trigger_stem_separation %.2fs  demucs=%s  -> %s",
        elapsed,
        "NO CORRIÓ (cache HIT)" if cache_hit else "CORRIÓ",
        state.stems_dir,
    )

    missing = [name for name in STEM_NAMES if name not in state.stems]
    if missing:
        return ToolResult.fail(
            "trigger_stem_separation", f"stems faltantes: {', '.join(missing)}"
        )

    return ToolResult(
        ok=True,
        tool="trigger_stem_separation",
        detail=f"4 stems listos en {state.stems_dir} ({elapsed:.2f}s).",
        payload={
            "stems": state.stems,
            "stems_dir": str(state.stems_dir),
            "seconds": round(elapsed, 2),
            "demucs_ran": not cache_hit,
        },
    )


def _render_mix(state: AgentState, args: RenderMixArgs) -> ToolResult:
    """Construye el bus con la intención pendiente. ÚNICO punto con costo real.

    Aplica lo que `adjust_stem_parameters` dejó pendiente y devuelve, en la
    misma pasada, el `qc_report` y el `balance_report` que el motor ya calcula.
    """
    settings_ = state.pending_settings or MixSettings()
    # Un seed sin perfil no tiene etapa que sembrar: se descarta para que la
    # ruta neutral siga siendo la misma de siempre (etapa Character apagada).
    character = args.character
    character_seed = args.character_seed if character is not None else None
    try:
        started = time.perf_counter()
        state.render = build_mix(
            session_id=state.session_id,
            input_path=state.input_path,
            stem_trims=settings_.stem_trims,
            auto_balance=settings_.auto_balance,
            with_versions=args.with_versions,
            character=character,
            character_seed=character_seed,
        )
        render_seconds = time.perf_counter() - started
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail("render_mix", f"render falló: {exc}")

    state.pending_settings = None
    state.iteration += 1
    state.mix_path = state.render.get("mix_path")

    log.info(
        "[TIMING] render_mix %.2fs (splitter.py registra arriba si Demucs corrió)",
        render_seconds,
    )

    return ToolResult(
        ok=True,
        tool="render_mix",
        detail=(
            f"Bus renderizado en {render_seconds:.2f}s (iteración {state.iteration})."
        ),
        payload={
            "mix_path": state.mix_path,
            "iteration": state.iteration,
            "applied_stem_trims": settings_.stem_trims,
            "character": character,
            "seconds": round(render_seconds, 2),
        },
    )


def bus_metrics(state: AgentState) -> dict[str, Any]:
    """Métricas del bus del último render. Fuente ÚNICA de esta lista de campos.

    La consumen la herramienta ``analyze_mix_bus`` y el armado del resultado
    HTTP del job. Duplicar los campos dejaría al frontend viendo métricas que la
    herramienta nunca midió, y nada fallaría.
    """
    render = state.render or {}
    return {
        "qc_report": render.get("qc_report") or {},
        "balance_report": render.get("balance_report"),
        "trim_report": render.get("trim_report"),
        "stem_presence": render.get("stem_presence"),
        "stem_lufs": (render.get("mix_metadata") or {}).get("stem_lufs"),
        "tempo_bpm": render.get("tempo_bpm"),
        "genre": render.get("genre"),
        "iteration": state.iteration,
    }


def _analyze_mix_bus(state: AgentState, args: AnalyzeMixBusArgs) -> ToolResult:
    """S2.3 — lectura pura de los reportes del último render. Cero side effects.

    No vuelve a medir: `quality_checks.run_qc_checks` exige el bus
    POST-bus-compressor y `build_mix` ya lo corrió (`mix_engine.py:1205`).
    """
    if state.render is None:
        return ToolResult.fail(
            "analyze_mix_bus", "no hay render previo: llamar render_mix primero."
        )

    payload = bus_metrics(state)
    flagged = _flagged(payload)

    return ToolResult(
        ok=True,
        tool="analyze_mix_bus",
        detail=(
            f"QC iteración {state.iteration}: "
            + ("todo OK." if not flagged else f"marcado -> {', '.join(flagged)}")
        ),
        payload=payload,
    )


def _adjust_stem_parameters(
    state: AgentState, args: AdjustStemParametersArgs
) -> ToolResult:
    """S2.4 — intención -> knobs vía `mix_mapper`. Nunca dB crudos."""
    settings_ = map_intent_to_mix(args.intent)
    state.intent = args.intent
    state.pending_settings = settings_

    return ToolResult(
        ok=True,
        tool="adjust_stem_parameters",
        detail="Intención ajustada; hace falta render_mix para materializarla.",
        payload={
            "stem_trims": settings_.stem_trims,
            "dimension_enabled": settings_.dimension_enabled,
            "auto_balance": settings_.auto_balance,
            "rationale": args.rationale,
        },
    )


def _search_knowledge(state: AgentState, args: SearchKnowledgeArgs) -> ToolResult:
    """Evidencia citada del RAG. Sólo existe si se inyectó un ``RAGQuery``."""
    if state.rag is None:
        return ToolResult.fail(
            "search_knowledge", "no hay RAG inyectado en esta corrida."
        )
    try:
        chunks = state.rag(args.query, args.k)
    except Exception as exc:  # noqa: BLE001 — el RAG caído no corta el bucle
        return ToolResult.fail("search_knowledge", f"consulta al RAG falló: {exc}")

    citations = [c.get("citation", "") for c in chunks if c.get("citation")]
    return ToolResult(
        ok=True,
        tool="search_knowledge",
        detail=(
            "Sin fragmentos: decidí con las mediciones."
            if not chunks
            else f"{len(chunks)} fragmentos. Citar: {'; '.join(citations)}"
        ),
        payload={"query": args.query, "chunks": chunks},
    )


def _source_crest_db(state: AgentState, source: str) -> float | None:
    """Crest factor del audio que ENTRA al máster. Medido, nunca inferido.

    El original ya viene medido de la fase 1. Para el bus no hace falta volver
    a medir el archivo: el QC del render ya calculó el crest del bus en
    ``low_level_listen`` (``quality_checks._crest_db``). Se lee de ahí: es una
    lectura, no DSP nuevo.
    """
    if source == "mix":
        report = (state.render or {}).get("qc_report") or {}
        details = (report.get("low_level_listen") or {}).get("details") or {}
        value = details.get("crest_db")
    else:
        value = state.analysis.crest_factor_db if state.analysis else None
    return None if value is None else float(value)


def _lufs_error(payload: dict[str, Any]) -> float | None:
    """Cuánto se desvió el máster de su objetivo. ``None`` = sin objetivo."""
    lufs = payload.get("integrated_lufs")
    target = payload.get("target_lufs_db")
    if lufs is None or target is None:
        return None
    return round(float(lufs) - float(target), 2)


def master_measurements(state: AgentState) -> dict[str, Any]:
    """Métricas del máster VIGENTE y qué falta para converger.

    Fuente ÚNICA de esta lista de campos: la consumen la herramienta
    ``analyze_master_output`` y la decisión de abrir la ventana de corrección.
    Duplicarlos dejaría al modelo viendo números que el guardrail no mira.
    """
    master = state.master_payload or {}
    error = _lufs_error(master)
    crest_delta = master.get("crest_delta_db")
    peak = master.get("true_peak_db")

    # Se normaliza a float una sola vez: los payloads vienen de un dict
    # heterogéneo (JSON del motor), así que el tipo real es Any y el
    # estrechamiento a ``float | None`` tiene que ser explícito.
    crest_delta_db: float | None = (
        None if crest_delta is None else float(crest_delta)
    )
    peak_db: float | None = None if peak is None else float(peak)

    squashed = crest_delta_db is not None and crest_delta_db < -MAX_CREST_DROP_DB
    unmet: list[str] = []
    if squashed and crest_delta_db is not None:
        unmet.append(
            f"el crest bajó {abs(crest_delta_db):.1f} dB respecto de la "
            f"entrada (límite {MAX_CREST_DROP_DB:.0f} dB)"
        )
    if peak_db is not None and peak_db > MAX_TRUE_PEAK_DB:
        unmet.append(
            f"true peak {peak_db:.1f} dBTP por encima del techo "
            f"{MAX_TRUE_PEAK_DB:.1f} dBTP"
        )
    if error is not None and abs(error) > MAX_LUFS_ERROR_DB:
        unmet.append(
            f"sonoridad {float(master['integrated_lufs']):.1f} LUFS contra un "
            f"objetivo de {float(master['target_lufs_db']):.1f} LUFS "
            f"(error {error:+.1f} dB)"
        )

    return {
        "integrated_lufs": master.get("integrated_lufs"),
        "true_peak_db": peak_db,
        "crest_factor_db": master.get("crest_factor_db"),
        "lra": master.get("lra"),
        "target_lufs_db": master.get("target_lufs_db"),
        "lufs_error_db": error,
        "source": master.get("source"),
        "source_crest_factor_db": master.get("source_crest_factor_db"),
        "crest_delta_db": crest_delta_db,
        "crest_warning": bool(squashed),
        "attempts": state.master_runs,
        "corrections_left": max(0, MAX_MASTER_ITERATIONS - state.master_runs),
        "unmet": unmet,
    }


def _measured(value: Any, unit: str) -> str:
    """Un número con su unidad, o la verdad cuando no se midió."""
    return "sin medir" if value is None else f"{float(value):.1f} {unit}"


def _master_summary(payload: dict[str, Any]) -> str:
    """La lectura del máster en una línea que el modelo pueda citar."""
    summary = (
        f"Máster vigente: {_measured(payload['integrated_lufs'], 'LUFS')}, "
        f"true peak {_measured(payload['true_peak_db'], 'dBTP')}, "
        f"crest {_measured(payload['crest_factor_db'], 'dB')} "
        f"(delta {_measured(payload['crest_delta_db'], 'dB')} vs la entrada)."
    )
    unmet = payload.get("unmet") or []
    if unmet:
        return (
            f"{summary} No converge: {'; '.join(unmet)}. "
            f"Quedan {payload['corrections_left']} correcciones."
        )
    return f"{summary} Converge: no hace falta corregir."


def _analyze_master_output(
    state: AgentState, args: AnalyzeMasterOutputArgs
) -> ToolResult:
    """S2.6 — lectura pura del máster vigente. Cero side effects, cero costo."""
    if state.master_payload is None:
        return ToolResult.fail(
            "analyze_master_output",
            "no hay máster todavía: correr send_to_master primero.",
        )

    payload = master_measurements(state)
    return ToolResult(
        ok=True,
        tool="analyze_master_output",
        detail=_master_summary(payload),
        payload=payload,
    )


def _send_to_master(state: AgentState, args: SendToMasterArgs) -> ToolResult:
    """S2.5 — cierra la mezcla y empuja el bus al mastering engine.

    La mezcla final entra a `engine.process_audio`, el mismo motor que sirve a
    la API de mastering. La intención que movió la mezcla mueve también el
    master (`map_intent_to_mastering`), y `mix_metadata` viaja al motor para el
    handshake adaptativo (`MOTOR_DSP_MIX_Y_MASTER.md` §3).

    Desde la fase de corrección esta herramienta es un intento MÁS, no un
    cierre ciego, y por eso aplica tres reglas que el modelo no puede saltar:

    * **Presupuesto**: ``MAX_MASTER_ITERATIONS`` intentos por corrida.
    * **Un parámetro por corrección** (§13.4.7): sin esto no se sabría qué
      movimiento causó el cambio, y "medir → mover → medir" pierde sentido.
    * **Guardrail de crest** (§13.4.8): si el crest baja más de
      ``MAX_CREST_DROP_DB`` respecto de la entrada, el intento se revierte y el
      máster anterior sigue vigente. Se revierte NO moviendo el puntero: el
      archivo del intento queda en disco, pero ``master_path`` no cambia.
    """
    if state.master_runs >= MAX_MASTER_ITERATIONS:
        return ToolResult.fail(
            "send_to_master",
            f"presupuesto de máster agotado: {MAX_MASTER_ITERATIONS} intentos "
            f"({MAX_MASTER_ITERATIONS - 1} corrección). No hay más correcciones.",
        )

    if args.source == "mix" and not state.can_master:
        return ToolResult.fail(
            "send_to_master",
            "source='mix' sin render completado: correr render_mix primero.",
        )

    dumped = args.model_dump()
    if state.master_args is not None:
        if args.source != state.master_args.get("source"):
            return ToolResult.fail(
                "send_to_master",
                "una corrección NO cambia la fuente: masterizá el mismo audio "
                "que la pasada anterior.",
            )
        changed = [
            knob
            for knob in _MASTER_KNOBS
            if dumped.get(knob) != state.master_args.get(knob)
        ]
        if not changed:
            return ToolResult.fail(
                "send_to_master",
                "una corrección tiene que mover UN parámetro: estos argumentos "
                "repiten la pasada anterior.",
            )
        if len(changed) > 1:
            return ToolResult.fail(
                "send_to_master",
                f"una corrección mueve UN parámetro y recibí {len(changed)}: "
                f"{', '.join(changed)}.",
            )

    source_path = state.mix_path if args.source == "mix" else str(state.input_path)
    if not source_path:
        return ToolResult.fail("send_to_master", "no hay audio fuente disponible.")
    if not Path(source_path).is_file():
        return ToolResult.fail(
            "send_to_master", f"el audio fuente no existe: {source_path}"
        )

    params = map_intent_to_mastering(state.intent)
    if args.target_lufs_db is not None:
        params.target_lufs_db = args.target_lufs_db
    params.output_bit_depth = args.output_bit_depth

    attempt = state.master_runs + 1
    # La corrección escribe SU archivo: reusar el nombre de la primera pasada
    # haría imposible revertir el intento — el máster bueno ya no existiría.
    suffix = "" if attempt == 1 else f"_pass{attempt}"
    output_path = (
        settings.output_dir / f"{state.session_id}_agentic_mastered{suffix}.wav"
    ).resolve()

    try:
        started = time.perf_counter()
        result = process_audio(
            input_path=source_path,
            output_path=output_path,
            params=params,
            analysis_result=state.analysis,
            # Sólo tiene sentido cuando lo masterizado ES la mezcla.
            mix_metadata=(
                (state.render or {}).get("mix_metadata")
                if args.source == "mix"
                else None
            ),
        )
        elapsed = time.perf_counter() - started
    except Exception as exc:  # noqa: BLE001 — el envelope absorbe el fallo
        return ToolResult.fail("send_to_master", f"mastering falló: {exc}")

    written = str(result.get("output_path") or output_path)
    crest = result.get("crest_factor_db")
    source_crest = _source_crest_db(state, args.source)
    crest_delta = (
        round(float(crest) - source_crest, 2)
        if crest is not None and source_crest is not None
        else None
    )
    squashed = crest_delta is not None and crest_delta < -MAX_CREST_DROP_DB
    reverted = squashed and state.master_payload is not None

    payload: dict[str, Any] = {
        "source": args.source,
        "source_path": source_path,
        "master_path": written,
        "attempt": attempt,
        "target_lufs_db": params.target_lufs_db,
        "output_bit_depth": result.get("output_bit_depth"),
        "integrated_lufs": result.get("integrated_lufs"),
        "true_peak_db": result.get("true_peak_db"),
        "crest_factor_db": crest,
        "lra": result.get("lra"),
        "duration_seconds": result.get("duration_seconds"),
        "source_crest_factor_db": source_crest,
        "crest_delta_db": crest_delta,
        "crest_warning": bool(squashed),
        "reverted": reverted,
        "revert_reason": (
            f"el crest bajó {abs(crest_delta):.1f} dB respecto de la entrada "
            f"(límite {MAX_CREST_DROP_DB:.0f} dB): se mantiene el máster anterior"
            if reverted and crest_delta is not None
            else None
        ),
        "seconds": round(elapsed, 2),
    }

    state.master_runs = attempt
    if reverted:
        payload["active_master_path"] = (state.master_payload or {}).get("master_path")
    else:
        state.master_path = written
        state.master_payload = payload
        state.master_args = dumped
        payload["active_master_path"] = written

    log.info("[TIMING] send_to_master %.2fs -> %s", elapsed, written)

    detail = f"Master listo en {written} ({elapsed:.2f}s)."
    if reverted:
        detail = (
            f"Corrección revertida: {payload['revert_reason']}. "
            f"El máster vigente sigue siendo {payload['active_master_path']}."
        )
    elif squashed:
        detail += " El crest quedó aplastado respecto de la entrada."

    return ToolResult(
        ok=True,
        tool="send_to_master",
        detail=detail,
        payload=payload,
    )


TOOL_IMPLS: dict[str, Callable[[AgentState, Any], ToolResult]] = {
    "analyze_original_audio": _analyze_original_audio,
    "trigger_stem_separation": _trigger_stem_separation,
    "render_mix": _render_mix,
    "analyze_mix_bus": _analyze_mix_bus,
    "adjust_stem_parameters": _adjust_stem_parameters,
    "search_knowledge": _search_knowledge,
    "send_to_master": _send_to_master,
    "analyze_master_output": _analyze_master_output,
}

#: Orden contractual de las fases (S3). El agente no puede saltearlo.
PHASE_GATE: dict[str, str] = {
    "analyze_original_audio": "phase1",
    "trigger_stem_separation": "phase2",
    "render_mix": "phase3",
    "analyze_mix_bus": "phase3",
    "adjust_stem_parameters": "phase3",
    "search_knowledge": "phase3",
    "send_to_master": "phase4",
    "analyze_master_output": "phase4",
}


def dispatch(
    state: AgentState,
    tool: str,
    raw_args: dict[str, Any],
    *,
    allowed: tuple[str, ...] | None = None,
) -> ToolResult:
    """Ejecuta la herramienta y la registra en ``state.tool_log``.

    Punto ÚNICO de paso: las cuatro fases entran por acá (por diseño, ver
    ``phase1_diagnose``), así que el log tampoco puede perder el camino de
    argumentos inválidos ni el de herramienta desconocida.

    ``allowed`` acota lo que una ventana concreta acepta (la corrección del
    máster). Se aplica acá y no en cada fase para que el rechazo también quede
    registrado como evidencia.
    """
    result = _dispatch(state, tool, raw_args, allowed=allowed)
    state.tool_log.append(result)
    return result


def _dispatch(
    state: AgentState,
    tool: str,
    raw_args: dict[str, Any],
    *,
    allowed: tuple[str, ...] | None = None,
) -> ToolResult:
    """Valida argumentos contra el modelo Pydantic y ejecuta la herramienta.

    Un argumento inválido no explota: vuelve como `ToolResult.fail` para que el
    modelo se corrija en el turno siguiente.
    """
    if allowed is not None and tool not in allowed:
        return ToolResult.fail(
            tool,
            f"herramienta no disponible en esta ventana: {tool} "
            f"(sólo {', '.join(allowed)}).",
        )

    model = TOOL_ARG_MODELS.get(tool)
    if model is None:
        return ToolResult.fail(tool, f"herramienta desconocida: {tool}")

    try:
        args = model.model_validate(raw_args)
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail(tool, f"argumentos inválidos: {exc}")

    return TOOL_IMPLS[tool](state, args)


# ══════════════════════════════════════════════════════════════════════════
# Transporte del LLM
# ══════════════════════════════════════════════════════════════════════════


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    #: Blob OPACO del proveedor que debe devolverse tal cual al repetir la
    #: llamada en el historial. Gemini lo llama ``thought_signature`` y rechaza
    #: con 400 el turno que repite una llamada sin él. Viaja en base64 para que
    #: el transcript neutro siga siendo serializable; los demás proveedores lo
    #: ignoran.
    thought_signature: str | None = None


class ModelTurn(BaseModel):
    """Un turno del modelo: texto, o las llamadas a herramienta a ejecutar.

    Gemini puede devolver VARIAS llamadas en un mismo turno; se ejecutan todas
    en orden antes de volver a preguntarle.
    """

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)


class TransportUnavailableError(RuntimeError):
    """Ningún transporte pudo responder. Nunca se sustituye por una adivinanza.

    Todos los proveedores levantan ESTE error, para que quien llame al bucle no
    necesite saber cuál está configurado.
    """


def assign_call_ids(
    transcript: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Copia del transcript con un ``id`` por llamada y por su respuesta.

    El formato neutro (ver arriba) no lleva ids, pero OpenAI y Anthropic exigen
    uno que ligue cada ``function_call`` con su resultado. El id se deriva de la
    POSICIÓN, no de un contador global: reconstruir el mismo transcript da los
    mismos ids, así que reintentar un turno no los baraja.

    Una misma herramienta puede llamarse varias veces en el historial; las
    respuestas se emparejan FIFO con la llamada pendiente más antigua del mismo
    nombre. Una respuesta sin llamada previa recibe un id propio en vez de
    romper: que el proveedor decida si eso es un error.
    """
    out: list[dict[str, Any]] = []
    pending: dict[str, deque[str]] = defaultdict(deque)

    for entry in transcript:
        copied = dict(entry)
        if "function_call" in copied:
            call = dict(copied["function_call"])
            call_id = f"call_{len(out)}"
            call["id"] = call_id
            pending[str(call.get("name", ""))].append(call_id)
            copied["function_call"] = call
        elif "response" in copied:
            queue = pending.get(str(copied.get("name", "")))
            copied["id"] = queue.popleft() if queue else f"call_{len(out)}"
        out.append(copied)

    return out


class ModelTransport(Protocol):
    """Puerto hacia el LLM. Se inyecta para poder testear las fases sin red."""

    def turn(
        self,
        *,
        phase: str,
        system: str,
        transcript: Sequence[dict[str, Any]],
        tools: Sequence[dict[str, Any]],
    ) -> ModelTurn: ...


def default_transport(**kwargs: Any) -> ModelTransport:
    """El transporte real, elegido por configuración.

    El registro vive en ``transport_factory``: ``LLM_PROVIDER`` en el ``.env``
    decide entre Gemini, cualquier endpoint OpenAI-compatible (DeepSeek, Ollama)
    y Anthropic. Import diferido: evita un ciclo de imports.
    """
    from audiomind.processing.transport_factory import build_transport

    return build_transport(**kwargs)


# ══════════════════════════════════════════════════════════════════════════
# Transcript — formato neutro que los transportes traducen
# ══════════════════════════════════════════════════════════════════════════
# Entradas posibles:
#   {"role": "user"|"model", "text": str}
#   {"role": "model", "function_call": {"name": str, "args": dict}}
#   {"role": "tool", "name": str, "response": dict}
# La llamada puede llevar además ``thought_signature`` (str base64, opcional):
# el sello opaco con que un modelo con razonamiento firma la llamada. Se
# conserva porque el proveedor exige verlo de vuelta en el historial.


def _record_exchange(
    transcript: list[dict[str, Any]], call: ToolCall, result: ToolResult
) -> None:
    """Registra la llamada del modelo y su respuesta, en ese orden.

    El SDK exige ver el `function_call` antes de su `function_response`; sin la
    llamada en el historial, Gemini rechaza el turno. La firma de pensamiento,
    cuando existe, viaja pegada a la llamada por el mismo motivo.
    """
    recorded: dict[str, Any] = {"name": call.name, "args": call.args}
    if call.thought_signature:
        recorded["thought_signature"] = call.thought_signature
    transcript.append({"role": "model", "function_call": recorded})
    transcript.append(
        {"role": "tool", "name": result.tool, "response": result.model_dump()}
    )


def _flagged(payload: dict[str, Any]) -> list[str]:
    """Lo que el QC marcó en el último render. Lista vacía = limpio."""
    flagged = (
        (payload.get("qc_report") or {}).get("summary") or {}
    ).get("flagged") or []
    return [str(item) for item in flagged]


# ══════════════════════════════════════════════════════════════════════════
# Orquestador secuencial — las 4 fases (S3)
# ══════════════════════════════════════════════════════════════════════════


def _tools_for(state: AgentState) -> list[dict[str, Any]]:
    return tool_definitions(include_rag=state.rag is not None)


def _verdict_block(state: AgentState) -> str:
    """El veredicto de Brik como bloque de contexto, o "" si no hay.

    Delegado a ``prompts.verdict_block``: la traduccion de Hz a sensaciones vive
    con el resto del texto que lee el modelo, no en el orquestador.

    Sin veredicto devuelve ``""`` EXACTO (no un bloque vacío): el turno queda
    byte a byte como estaba antes de que la feature existiera, que es lo que
    permite que los tests de compatibilidad sigan pasando sin tocarlos.
    """
    block = prompts.verdict_block(state.verdict, applied=state.decision.applied)
    return f"\n\n{block}" if block else ""


def _reference_block(state: AgentState) -> str:
    """La referencia del usuario como contexto, o "" si no hay una lista.

    Solo ``status="ready"`` es evidencia: un ``error`` o un ``no_reference`` es
    una comparación que no corrió, y mostrarla sería presentar como medición
    algo que nunca se midió.
    """
    comparison = state.reference_comparison
    if comparison is None or comparison.status != "ready":
        return ""
    return (
        "\n\n<referencia>\n"
        + json.dumps(comparison.model_dump(mode="json"), indent=2, ensure_ascii=False)
        + "\n</referencia>"
    )


def phase1_diagnose(
    state: AgentState, transport: ModelTransport, transcript: list[dict[str, Any]]
) -> str:
    """FASE 1 · DIAGNÓSTICO (S3.a).

    Analiza el original, le pasa las mediciones al modelo y el modelo redacta
    ``state.diagnosis``. Acá NO se separa nada: el diagnóstico precede a la
    separación, para que el agente sepa POR QUÉ va a separar.

    La herramienta se invoca por ``dispatch`` (el mismo camino que usan los
    turnos del modelo) para que haya una sola senda de ejecución.
    """
    result = dispatch(
        state, "analyze_original_audio", {"file_path": str(state.input_path)}
    )
    if not result.ok:
        raise RuntimeError(f"Fase 1 falló: {result.error}")
    transcript.append(
        {
            "role": "user",
            "text": (
                prompts.context_block(state.intent.model_dump(), result.payload)
                + _verdict_block(state)
                + _reference_block(state)
                + "\n\n<mediciones>\n"
                + json.dumps(result.payload, indent=2, ensure_ascii=False)
                + "\n</mediciones>"
            ),
        }
    )

    turn = transport.turn(
        phase="phase1",
        system=prompts.DIAGNOSIS_SYSTEM_PROMPT,
        transcript=transcript,
        tools=[],
    )
    state.diagnosis = turn.text
    if turn.text:
        transcript.append({"role": "model", "text": turn.text})
    return state.diagnosis


def phase2_separate(
    state: AgentState, transport: ModelTransport, transcript: list[dict[str, Any]]
) -> list[ToolResult]:
    """FASE 2 · DESMONTAJE (S3.b). Separación a stems, una sola vez."""
    result = dispatch(
        state, "trigger_stem_separation", {"file_path": str(state.input_path)}
    )
    if not result.ok:
        raise RuntimeError(f"Fase 2 falló: {result.error}")

    # La separación la ordena el orquestador, no el modelo: no hay function_call
    # que responder, así que el resultado viaja como directiva de turno.
    transcript.append(
        {
            "role": "user",
            "text": (
                f"Separación lista: {result.payload['stems_dir']}. "
                "Ahora dirigí el bucle de mezcla."
            ),
        }
    )
    return [result]


def phase3_mix_loop(
    state: AgentState,
    transport: ModelTransport,
    transcript: list[dict[str, Any]],
) -> list[ToolResult]:
    """FASE 3 · BUCLE DE MEZCLA (S3.c) — hasta ``MAX_MIX_ITERATIONS`` vueltas.

    Cada vuelta el modelo elige la herramienta. El render es la única operación
    con costo real, así que el prompt le exige ajustar la intención ANTES de
    renderizar.

    Corte anticipado: si ``analyze_mix_bus`` no marca nada, el bucle converge y
    sobra iteración. El guardrail de crest (>4 dB de caída -> revertir) todavía
    NO está implementado.
    """
    results: list[ToolResult] = []
    system = prompts.mix_loop_system_prompt(MAX_MIX_ITERATIONS)
    tools = _tools_for(state)

    for _ in range(MAX_MIX_ITERATIONS):
        turn = transport.turn(
            phase="phase3", system=system, transcript=transcript, tools=tools
        )

        if not turn.tool_calls:
            if turn.text:
                transcript.append({"role": "model", "text": turn.text})
            break

        for call in turn.tool_calls:
            result = dispatch(state, call.name, call.args)
            results.append(result)
            _record_exchange(transcript, call, result)

            if not result.ok:
                return results
            if result.tool == "send_to_master":
                return results

        # Convergencia: se cierra el bucle cuando el QC no marca nada.
        last = results[-1]
        if last.tool == "analyze_mix_bus" and not _flagged(last.payload):
            break

    return results


def _force_master_only_source(state: AgentState, call: ToolCall) -> ToolCall:
    """Con la compuerta cerrada, el modelo no tiene voto sobre la fuente.

    ``master_only`` masteriza el original: pedir ``mix`` por inercia haría
    fallar el envelope pidiendo un render que esa ruta nunca produjo. La
    decisión ya está tomada; se aplica acá, no en el prompt.
    """
    if state.decision.applied != "master_only":
        return call
    if call.args.get("source") not in (None, "original"):
        log.warning(
            "Ruta 'master_only': se ignora source=%r y se masteriza el original.",
            call.args.get("source"),
        )
    return call.model_copy(update={"args": {**call.args, "source": "original"}})


def _last_master(state: AgentState) -> ToolResult:
    """El último ``send_to_master`` exitoso del log, si hubo alguno."""
    for result in reversed(state.tool_log):
        if result.tool == "send_to_master" and result.ok:
            return result
    return ToolResult.fail("send_to_master", "no hay máster en el log.")


def _master_feedback_loop(
    state: AgentState,
    transport: ModelTransport,
    transcript: list[dict[str, Any]],
    *,
    accepted: ToolResult,
) -> ToolResult:
    """Ventana de corrección: medir → mover UN parámetro → medir, o parar.

    Se abre SÓLO si una medición dice que el máster no convergió (crest
    aplastado, techo de true peak pasado, sonoridad fuera de objetivo). Un
    máster sano no gasta un turno más: el bucle cierra donde cerraba antes.

    Dentro de la ventana el modelo ve dos herramientas y nada más. El
    presupuesto, el "un parámetro" y el guardrail de crest viven en
    ``_send_to_master``: acá sólo se acota el alcance y se corta el bucle.
    """
    measurements = master_measurements(state)
    if not measurements["unmet"]:
        return accepted

    transcript.append(
        {
            "role": "user",
            "text": (
                _master_summary(measurements)
                + "\n\nEl máster no convergió. Podés corregirlo una sola vez: "
                "mové UN parámetro con `send_to_master` después de mirar las "
                "mediciones con `analyze_master_output`. Si no hay nada que "
                "corregir, respondé con texto y el bucle cierra."
            ),
        }
    )

    system = prompts.master_feedback_system_prompt(
        MAX_MASTER_ITERATIONS,
        max_crest_drop_db=MAX_CREST_DROP_DB,
        max_true_peak_db=MAX_TRUE_PEAK_DB,
    )
    tools = tool_definitions(names=MASTER_FEEDBACK_TOOLS)

    for _ in range(MAX_FEEDBACK_TURNS):
        turn = transport.turn(
            phase="phase4", system=system, transcript=transcript, tools=tools
        )

        if not turn.tool_calls:
            if turn.text:
                transcript.append({"role": "model", "text": turn.text})
            return accepted

        for call in turn.tool_calls:
            if call.name == "send_to_master":
                call = _force_master_only_source(state, call)
            result = dispatch(
                state, call.name, call.args, allowed=MASTER_FEEDBACK_TOOLS
            )
            _record_exchange(transcript, call, result)

            if not result.ok:
                # Una corrección fallida NO borra el máster aceptado: ese audio
                # existe, se midió y es lo que el usuario se lleva. El intento
                # queda registrado en el log del job como evidencia.
                return accepted
            if result.tool == "send_to_master":
                if result.payload.get("reverted"):
                    return accepted
                return result

    return accepted


def phase4_send_to_master(
    state: AgentState, transport: ModelTransport, transcript: list[dict[str, Any]]
) -> ToolResult:
    """FASE 4 · CIERRE (S3.d) — máster y, si no convergió, UNA corrección.

    Con la compuerta cerrada (``applied="master_only"``) el argumento se FUERZA
    a ``source="original"``: ver ``_force_master_only_source``.

    Si la fase 3 ya masterizó (el modelo puede cerrar el bucle de mezcla
    llamando ``send_to_master``), no se vuelve a pagar el motor: se entra
    directo a la ventana de corrección.
    """
    if state.master_runs >= 1:
        return _master_feedback_loop(
            state, transport, transcript, accepted=_last_master(state)
        )

    turn = transport.turn(
        phase="phase4",
        system=prompts.mix_loop_system_prompt(MAX_MIX_ITERATIONS),
        transcript=transcript,
        tools=_tools_for(state),
    )

    call = turn.tool_calls[0] if turn.tool_calls else ToolCall(name="send_to_master")
    if call.name != "send_to_master":
        log.warning("Fase 4 recibió %s; se fuerza send_to_master.", call.name)
        call = ToolCall(name="send_to_master")

    call = _force_master_only_source(state, call)
    result = dispatch(state, call.name, call.args)
    _record_exchange(transcript, call, result)
    if not result.ok:
        return result

    return _master_feedback_loop(state, transport, transcript, accepted=result)


def resolve_decision(
    requested: Decision,
    verdict: AudioVerdict | None = None,
    reference_is_mastered: bool = False,
) -> AppliedDecision:
    """Resolver qué ruta corre de verdad. PURA: no toca el estado ni el audio.

    El orden de prioridad es la regla de negocio, y cada escalón existe por un
    motivo distinto:

    1. **La elección explícita del usuario gana siempre.** Es "la última palabra
       la decide el usuario" hecho código, y también la garantía de que Brik no
       puede decidir sola por accidente.
    2. **Una referencia masterizada fuerza la ruta corta**, incluso sobre un
       veredicto que pida mezclar. Comparar dos masters no justifica re-mezclar:
       la referencia ya es el estándar al que se quiere llegar.
    3. **``auto`` sigue el veredicto.** ``needs_mix`` manda.
    4. **Sin veredicto, la ruta histórica.** Cuatro fases, exactamente como
       antes de esta feature. Un audio sin clasificar nunca cambia de
       comportamiento en silencio.
    """
    if requested == "mix_then_master" or requested == "master_only":
        return requested

    if reference_is_mastered:
        return "master_only"

    if verdict is not None:
        return "mix_then_master" if verdict.needs_mix else "master_only"

    # Sin veredicto: comportamiento histórico. La feature es opt-in de hecho.
    return "mix_then_master"


def run(
    session_id: str,
    input_path: str | Path,
    transport: ModelTransport | None = None,
    rag: RAGQuery | None = None,
    prompt: str | None = None,
    decision: Decision = "auto",
    verdict: AudioVerdict | None = None,
    reference_comparison: ReferenceComparison | None = None,
    reference_is_mastered: bool = False,
    initial_intent: IntentProfile | None = None,
    **transport_kwargs: Any,
) -> AgentState:
    """Corre el flujo: diagnóstico -> [desmontaje -> bucle] -> cierre.

    Las fases 2 y 3 son CONDICIONALES desde esta feature. Con
    ``applied="master_only"`` no se separa ni se mezcla: la fase 4 masteriza el
    original (``SendToMasterArgs.source="original"``, que el motor soporta desde
    antes — lo que el orquestador nunca ofrecía). Ese es el ahorro real: Demucs
    es la operación más cara del sistema y se evita por completo.

    ``transport`` es inyectable (tests sin red). Si se omite, se construye el
    transporte real según ``LLM_PROVIDER``; sin credencial utilizable eso levanta
    ``TransportUnavailableError`` en vez de seguir a ciegas.

    ``prompt`` es el pedido en lenguaje natural del usuario. Viaja en el turno
    inicial, que las fases reciben, así que tanto el diagnóstico como el bucle
    lo ven. ``None`` o vacío deja ese turno EXACTAMENTE como estaba antes de que
    el parámetro existiera.

    ``decision`` es la última palabra del usuario (``auto`` = delegar en Brik).
    ``verdict`` y ``reference_comparison`` son los artefactos que la explican.
    ``chat_transcript`` (si existe en la sesión) se inyecta como contexto previo
    para que el agente "recuerde" la conversación.
    ``initial_intent`` es el punto de partida del TRATAMIENTO: el intent con el
    que terminó el barrido anterior de esta sesión. ``None`` arranca en
    ``IntentProfile.neutral()``, el comportamiento histórico exacto.
    Todo con default: llamar ``run()`` como se llamaba antes corre las cuatro
    fases igual que siempre.
    """
    if transport is None:
        transport = default_transport(**transport_kwargs)

    state = AgentState(session_id=session_id, input_path=Path(input_path), rag=rag)
    # El tratamiento heredado entra ANTES de la fase 1: el contexto del
    # diagnóstico (``prompts.context_block(state.intent...)``) ya lo ve, así
    # que el segundo barrido diagnostica desde donde quedó, no desde cero.
    if initial_intent is not None:
        state.intent = initial_intent
    state.verdict = verdict
    state.reference_comparison = reference_comparison
    state.reference_is_mastered = reference_is_mastered
    state.decision = DecisionRecord(
        requested=decision,
        applied=resolve_decision(decision, verdict, reference_is_mastered),
    )

    # ── Cargar transcript persistido de la sesión (T5) ──────────────────────
    # Máx 10 pares (20 entradas) para controlar tokens. Los turnos más recientes
    # del chat tienen prioridad sobre el historial más antiguo.
    prior_transcript: list[dict[str, Any]] = []
    try:
        sessions = load_sessions()
        session = sessions.get(session_id)
        if session and getattr(session, "chat_transcript", None):
            for entry in session.chat_transcript:
                role = "model" if entry.role == "assistant" else "user"
                prior_transcript.append({"role": role, "text": entry.text})
            # Limitar a últimos 10 pares
            if len(prior_transcript) > 20:
                prior_transcript = prior_transcript[-20:]
    except Exception as exc:  # noqa: BLE001
        # Si falla la carga, seguimos sin transcript previo (degradación grácil)
        logging.getLogger(__name__).debug("No se pudo cargar chat_transcript: %s", exc)

    instruction = f"Mezclar y masterizar: {state.input_path}"
    if prompt and prompt.strip():
        instruction = f"{instruction}\n\nPedido del usuario: {prompt.strip()}"

    # Transcript inicial = persistido + turno actual
    transcript: list[dict[str, Any]] = prior_transcript + [{"role": "user", "text": instruction}]

    phase1_diagnose(state, transport, transcript)
    if state.decision.applied == "mix_then_master":
        phase2_separate(state, transport, transcript)
        phase3_mix_loop(state, transport, transcript)
    phase4_send_to_master(state, transport, transcript)

    return state
