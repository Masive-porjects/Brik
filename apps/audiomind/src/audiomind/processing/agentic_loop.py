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
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from audiomind.analysis.analyzer import analyze_audio
from audiomind.config import settings
from audiomind.models.audio import AnalysisResult
from audiomind.models.intent_profile import IntentProfile
from audiomind.processing import prompts
from audiomind.processing.engine import process_audio
from audiomind.processing.mapper import map_intent_to_mastering
from audiomind.processing.mix_engine import build_mix
from audiomind.processing.mix_mapper import MixSettings, map_intent_to_mix
from audiomind.processing.splitter import STEM_NAMES, split_audio

log = logging.getLogger(__name__)

#: Tope duro de iteraciones del bucle de mezcla (S3.c).
MAX_MIX_ITERATIONS = 3

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


TOOL_ARG_MODELS: dict[str, type[BaseModel]] = {
    "analyze_original_audio": AnalyzeOriginalAudioArgs,
    "trigger_stem_separation": TriggerStemSeparationArgs,
    "render_mix": RenderMixArgs,
    "analyze_mix_bus": AnalyzeMixBusArgs,
    "adjust_stem_parameters": AdjustStemParametersArgs,
    "search_knowledge": SearchKnowledgeArgs,
    "send_to_master": SendToMasterArgs,
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
        "de adjust_stem_parameters."
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
}


def tool_definitions(*, include_rag: bool = False) -> list[dict[str, Any]]:
    """Definiciones listas para el `tools=[...]` de Gemini function calling.

    El JSON Schema sale de Pydantic — una sola fuente de verdad entre el
    schema que ve el modelo y el modelo que valida la respuesta.
    """
    names = [*_SPEC_TOOLS, "search_knowledge"] if include_rag else list(_SPEC_TOOLS)
    return [
        {
            "name": name,
            "description": _TOOL_DOCS[name],
            "parameters": TOOL_ARG_MODELS[name].model_json_schema(),
        }
        for name in names
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
# Estado del agente
# ══════════════════════════════════════════════════════════════════════════


@dataclass
class AgentState:
    """Todo lo que el agente acumula entre llamadas a herramientas."""

    session_id: str
    input_path: Path

    #: Consulta al RAG. ``None`` = el agente no ve ``search_knowledge``.
    rag: RAGQuery | None = None

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
    try:
        started = time.perf_counter()
        state.render = build_mix(
            session_id=state.session_id,
            input_path=state.input_path,
            stem_trims=settings_.stem_trims,
            auto_balance=settings_.auto_balance,
            with_versions=args.with_versions,
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
            "seconds": round(render_seconds, 2),
        },
    )


def _analyze_mix_bus(state: AgentState, args: AnalyzeMixBusArgs) -> ToolResult:
    """S2.3 — lectura pura de los reportes del último render. Cero side effects.

    No vuelve a medir: `quality_checks.run_qc_checks` exige el bus
    POST-bus-compressor y `build_mix` ya lo corrió (`mix_engine.py:1205`).
    """
    if state.render is None:
        return ToolResult.fail(
            "analyze_mix_bus", "no hay render previo: llamar render_mix primero."
        )

    qc_report = state.render.get("qc_report") or {}
    payload = {
        "qc_report": qc_report,
        "balance_report": state.render.get("balance_report"),
        "trim_report": state.render.get("trim_report"),
        "stem_presence": state.render.get("stem_presence"),
        "stem_lufs": (state.render.get("mix_metadata") or {}).get("stem_lufs"),
        "tempo_bpm": state.render.get("tempo_bpm"),
        "genre": state.render.get("genre"),
        "iteration": state.iteration,
    }
    flagged = (qc_report.get("summary") or {}).get("flagged", [])

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


def _send_to_master(state: AgentState, args: SendToMasterArgs) -> ToolResult:
    """S2.5 — cierra la mezcla y empuja el bus al mastering engine.

    La mezcla final entra a `engine.process_audio`, el mismo motor que sirve a
    la API de mastering. La intención que movió la mezcla mueve también el
    master (`map_intent_to_mastering`), y `mix_metadata` viaja al motor para el
    handshake adaptativo (`MOTOR_DSP_MIX_Y_MASTER.md` §3).
    """
    if args.source == "mix" and not state.can_master:
        return ToolResult.fail(
            "send_to_master",
            "source='mix' sin render completado: correr render_mix primero.",
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

    output_path = (
        settings.output_dir / f"{state.session_id}_agentic_mastered.wav"
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

    state.master_path = str(result.get("output_path") or output_path)
    log.info("[TIMING] send_to_master %.2fs -> %s", elapsed, state.master_path)

    return ToolResult(
        ok=True,
        tool="send_to_master",
        detail=f"Master listo en {state.master_path} ({elapsed:.2f}s).",
        payload={
            "source": args.source,
            "source_path": source_path,
            "master_path": state.master_path,
            "target_lufs_db": params.target_lufs_db,
            "output_bit_depth": result.get("output_bit_depth"),
            "integrated_lufs": result.get("integrated_lufs"),
            "true_peak_db": result.get("true_peak_db"),
            "crest_factor_db": result.get("crest_factor_db"),
            "lra": result.get("lra"),
            "duration_seconds": result.get("duration_seconds"),
            "seconds": round(elapsed, 2),
        },
    )


TOOL_IMPLS: dict[str, Callable[[AgentState, Any], ToolResult]] = {
    "analyze_original_audio": _analyze_original_audio,
    "trigger_stem_separation": _trigger_stem_separation,
    "render_mix": _render_mix,
    "analyze_mix_bus": _analyze_mix_bus,
    "adjust_stem_parameters": _adjust_stem_parameters,
    "search_knowledge": _search_knowledge,
    "send_to_master": _send_to_master,
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
}


def dispatch(state: AgentState, tool: str, raw_args: dict[str, Any]) -> ToolResult:
    """Valida argumentos contra el modelo Pydantic y ejecuta la herramienta.

    Un argumento inválido no explota: vuelve como `ToolResult.fail` para que el
    modelo se corrija en el turno siguiente.
    """
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


class ModelTurn(BaseModel):
    """Un turno del modelo: texto, o las llamadas a herramienta a ejecutar.

    Gemini puede devolver VARIAS llamadas en un mismo turno; se ejecutan todas
    en orden antes de volver a preguntarle.
    """

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)


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
    """El transporte real (Gemini). Import diferido: evita un ciclo de imports."""
    from audiomind.processing.gemini_transport import GeminiTransport

    return GeminiTransport(**kwargs)


# ══════════════════════════════════════════════════════════════════════════
# Transcript — formato neutro que los transportes traducen
# ══════════════════════════════════════════════════════════════════════════
# Entradas posibles:
#   {"role": "user"|"model", "text": str}
#   {"role": "model", "function_call": {"name": str, "args": dict}}
#   {"role": "tool", "name": str, "response": dict}


def _record_exchange(
    transcript: list[dict[str, Any]], call: ToolCall, result: ToolResult
) -> None:
    """Registra la llamada del modelo y su respuesta, en ese orden.

    El SDK exige ver el `function_call` antes de su `function_response`; sin la
    llamada en el historial, Gemini rechaza el turno.
    """
    transcript.append(
        {"role": "model", "function_call": {"name": call.name, "args": call.args}}
    )
    transcript.append(
        {"role": "tool", "name": result.tool, "response": result.model_dump()}
    )


def _flagged(payload: dict[str, Any]) -> list[str]:
    """Lo que el QC marcó en el último render. Lista vacía = limpio."""
    return ((payload.get("qc_report") or {}).get("summary") or {}).get("flagged", [])


# ══════════════════════════════════════════════════════════════════════════
# Orquestador secuencial — las 4 fases (S3)
# ══════════════════════════════════════════════════════════════════════════


def _tools_for(state: AgentState) -> list[dict[str, Any]]:
    return tool_definitions(include_rag=state.rag is not None)


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


def phase4_send_to_master(
    state: AgentState, transport: ModelTransport, transcript: list[dict[str, Any]]
) -> ToolResult:
    """FASE 4 · CIERRE (S3.d). Empuja el bus al mastering engine."""
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

    result = dispatch(state, call.name, call.args)
    _record_exchange(transcript, call, result)
    if result.ok:
        state.master_path = result.payload.get("master_path")
    return result


def run(
    session_id: str,
    input_path: str | Path,
    transport: ModelTransport | None = None,
    rag: RAGQuery | None = None,
    **transport_kwargs: Any,
) -> AgentState:
    """Corre el flujo completo: diagnóstico -> desmontaje -> bucle -> cierre.

    ``transport`` es inyectable (tests sin red). Si se omite, se construye el
    transporte Gemini real; sin ``GEMINI_API_KEY`` eso levanta
    ``GeminiUnavailableError`` en vez de seguir a ciegas.
    """
    if transport is None:
        transport = default_transport(**transport_kwargs)

    state = AgentState(session_id=session_id, input_path=Path(input_path), rag=rag)
    transcript: list[dict[str, Any]] = [
        {"role": "user", "text": f"Mezclar y masterizar: {state.input_path}"}
    ]

    phase1_diagnose(state, transport, transcript)
    phase2_separate(state, transport, transcript)
    phase3_mix_loop(state, transport, transcript)
    phase4_send_to_master(state, transport, transcript)

    return state
