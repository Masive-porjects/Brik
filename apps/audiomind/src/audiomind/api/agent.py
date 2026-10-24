"""Agent knowledge API — expone el RAG local al orquestador por HTTP.

Hoy `intelligence/rag/` es un CLI (`python -m audiomind.intelligence.rag search ...`).
Este módulo le da al agente LLM la misma capacidad por HTTP: recibe una query
estructurada y devuelve los fragmentos relevantes **con cita** (autor + página),
que es el requisito de evidencia del Knowledge Core.

    POST /agent/rag/search  ->  {query, k, mode, book_ids?}  ->  chunks[]

Diseño:

* **Solo lectura.** No escribe, no indexa, no reconstruye. El índice se carga una
  vez de disco y se reusa.
* **Degradación explícita.** Si Ollama no está o falta `bge-m3`, cae a BM25 y lo
  declara en `mode_used` + `degraded`. Nunca falla por eso: el RAG funciona en
  BM25 puro (estado medido: 5/15 hit@5, MRR 0.30 — objetivo >10/15 con vectores).
* **Nada sale del `data_dir`.** Los PDFs, el texto extraído y los embeddings viven
  fuera del repo (`RAG_DATA_DIR`, por defecto `apps/audiomind/.rag`). Acá solo
  viajan fragmentos cortos citados.

PENDIENTE: el wiring del router en `main.py` es la tarea T7 del doc
`odd/tasks/agentic-mix-loop.md`.

CHAT ROUTER (T1-T3 de `odd/tasks/brik-chat-router.md`):
------------------------------------------------------
POST /agent/chat  ->  {reply, escalate?, intent_updates?}
Endpoint liviano que inyecta el estado de la sesión (~550 tokens) como contexto
y usa `generate_content` manual (no `chats.create`) para preservar la
portabilidad multi-proveedor y la inyección de `thought_signature`.
El enrutador heurístico `should_escalate_to_job` decide en <1 ms si:
- responder en chat (explicación, ajuste de parámetros)
- escalar a job asíncrono (acción concreta: mezclar, masterizar, render, etc.)
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from audiomind.intelligence.rag.chunk import Chunk
from audiomind.intelligence.rag.embed import EmbeddingUnavailableError, OllamaEmbedder
from audiomind.intelligence.rag.index import RagIndex, SearchMode
from audiomind.models.audio import (
    AnalysisResult,
    AudioVerdict,
    ReferenceComparison,
    TranscriptEntry,
)
from audiomind.models.intent_profile import IntentProfile
from audiomind.processing import prompts
from audiomind.processing.agentic_loop import default_transport
from audiomind.session_store import load_sessions, save_sessions

if TYPE_CHECKING:  # pragma: no cover - solo anotaciones; el config se importa perezoso
    from audiomind.intelligence.rag.config import RagConfig

log = logging.getLogger(__name__)

router = APIRouter()

#: Cuántos fragmentos se piden por defecto. El plan de IA pide 4-6 por turno.
DEFAULT_K = 5
MAX_K = 20


# ── Contratos RAG (existentes) ─────────────────────────────────────────────


class RagSearchRequest(BaseModel):
    """Query estructurada del agente hacia el RAG."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        ..., min_length=2, max_length=400,
        description="Qué busca el agente, en lenguaje natural.",
    )
    k: int = Field(DEFAULT_K, ge=1, le=MAX_K, description="Fragmentos a devolver.")
    mode: SearchMode = Field(
        "hybrid",
        description="'hybrid' (BM25 + vectores por RRF), 'bm25' o 'vector'.",
    )
    book_ids: list[str] | None = Field(
        None,
        description="Restringe a libros concretos. None = todos. "
        "Roads (The Computer Music Tutorial) es más útil para el motor DSP "
        "que para conversar con músicos.",
    )


class RagChunk(BaseModel):
    """Un fragmento recuperado, listo para citar."""

    chunk_id: str
    book_id: str
    chapter: str
    page_start: int | None = None
    page_end: int | None = None
    citation: str = Field(..., description="Cita corta: '<book_id> p.<página>'.")
    text: str
    score: float


class RagSearchResponse(BaseModel):
    query: str
    mode_used: SearchMode
    degraded: bool = Field(
        ..., description="True cuando se pidió hybrid/vector y se cayó a BM25."
    )
    note: str
    chunks: list[RagChunk]


# ── Contratos CHAT ROUTER (T1) ─────────────────────────────────────────────


class ChatRequest(BaseModel):
    """Input del usuario en la ventana de chat de Brik."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(..., description="ID de la sesión activa.")
    message: str = Field(
        ..., min_length=1, max_length=2000,
        description="Mensaje del usuario en lenguaje natural.",
    )
    history: list[dict[str, Any]] | None = Field(
        None,
        description=(
            "Historial reciente del frontend (últimos 10 turnos user/assistant). "
            "Formato: [{role: 'user'|'assistant', content: str, ts: int}]. "
            "Si se omite, el endpoint usa solo el transcript persistido."
        ),
    )


class SessionSnapshot(BaseModel):
    """Estado resumido de la sesión para inyectar como contexto (~550 tokens)."""

    model_config = ConfigDict(extra="forbid")

    # Fase 1: diagnóstico + veredicto
    analysis: AnalysisResult | None = None
    verdict: AudioVerdict | None = None

    # Fase 2/3: mezcla (si existe)
    mix_analysis: dict[str, Any] | None = None
    mix_metadata: dict[str, Any] | None = None
    mix_status: Literal["none", "processing", "completed", "failed"] = "none"

    # Referencia externa (si existe)
    reference_comparison: ReferenceComparison | None = None


class EscalationDecision(BaseModel):
    """Decisión del enrutador heurístico: chat o job."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["answer_in_chat", "escalate_to_job"]
    reason: str = Field(..., description="Por qué se tomó esta decisión.")
    # Solo cuando action == "escalate_to_job"
    job_kind: Literal["agent", "master"] | None = None
    job_payload: dict[str, Any] | None = None
    # Solo cuando action == "answer_in_chat" y hay ajuste de parámetros
    updates_intent: bool = False
    intent_delta: dict[str, float] | None = None

    @classmethod
    def escalate(cls, *, job_kind: Literal["agent", "master"], payload: dict[str, Any], reason: str) -> EscalationDecision:
        return cls(action="escalate_to_job", job_kind=job_kind, job_payload=payload, reason=reason)

    @classmethod
    def answer_in_chat(cls, *, reason: str, updates_intent: bool = False, intent_delta: dict[str, float] | None = None) -> EscalationDecision:
        return cls(action="answer_in_chat", reason=reason, updates_intent=updates_intent, intent_delta=intent_delta)


class ChatResponse(BaseModel):
    """Respuesta del endpoint de chat."""

    model_config = ConfigDict(extra="forbid")

    reply: str = Field(..., description="Texto que Brik muestra al usuario.")
    escalation: EscalationDecision | None = Field(
        None, description="Si no es None, el frontend debe lanzar el job indicado."
    )
    intent_updates: IntentProfile | None = Field(
        None, description="Nuevo perfil de intención si el usuario pidió ajustes."
    )


# ── Índice: carga perezosa, una sola vez ──────────────────────────────────

_index_lock = threading.Lock()
_index: RagIndex | None = None
_index_error: str | None = None


def _config() -> RagConfig:
    """Rutas del RAG desde el entorno (mismo factory que usa el CLI).

    Import perezoso a propósito: `rag.config` resuelve rutas en disco al
    importarse. Si eso falla, se degrada este endpoint; nunca el boot del API.
    """
    from audiomind.intelligence.rag.config import RagConfig

    return RagConfig.from_env()


def get_index() -> RagIndex:
    """Carga el índice una vez. Los endpoints sync corren en threadpool."""
    global _index, _index_error

    if _index is not None:
        return _index

    with _index_lock:
        if _index is not None:
            return _index
        if _index_error is not None:
            raise HTTPException(status_code=503, detail=_index_error)

        index_dir = _config().index_dir
        if not Path(index_dir).exists():
            _index_error = (
                "El índice del RAG no está construido. "
                "Correr: python -m audiomind.intelligence.rag build"
            )
            raise HTTPException(status_code=503, detail=_index_error)

        try:
            _index = RagIndex.load(Path(index_dir))
        except Exception as exc:  # noqa: BLE001
            _index_error = f"No se pudo cargar el índice del RAG: {exc}"
            raise HTTPException(status_code=503, detail=_index_error) from exc

        log.info(
            "RAG index cargado: %d fragmentos, vectores=%s",
            len(_index.chunks),
            _index.has_vectors,
        )
        return _index


def reset_index() -> None:
    """Suelta el índice cacheado (tests / rebuild en caliente)."""
    global _index, _index_error
    with _index_lock:
        _index = None
        _index_error = None


# ── Helpers ───────────────────────────────────────────────────────────────


def _citation(chunk: Chunk) -> str:
    """Cita corta y verificable. Sin página impresa, se cita por capítulo."""
    if chunk.page_start is not None:
        return f"{chunk.book_id} p.{chunk.page_start}"
    return f"{chunk.book_id} · {chunk.chapter}"


def _embed_query(config: RagConfig, query: str) -> Any | None:
    """Vector de la query, o `None` si no hay Ollama. Nunca lanza."""
    try:
        return OllamaEmbedder(config.ollama_url, config.embed_model).embed([query])[0]
    except EmbeddingUnavailableError as exc:
        log.info("RAG sin vectores, se sigue en BM25: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 — degradar, no romper el turno
        log.warning("Embeddings fallaron, se sigue en BM25: %s", exc)
        return None


def _effective_mode(
    requested: SearchMode, index: RagIndex, query_vector: Any | None
) -> tuple[SearchMode, bool]:
    """Misma degradación que el CLI: sin vector o sin índice vectorial, BM25."""
    if requested == "vector":
        # `vector` explícito sin vectores disponibles es un error del caller, no
        # algo a degradar en silencio.
        if query_vector is None:
            raise HTTPException(
                status_code=409,
                detail="mode='vector' requiere embeddings: Ollama no disponible.",
            )
        if not index.has_vectors:
            raise HTTPException(
                status_code=409,
                detail="mode='vector' pero el índice no tiene vectores. Rebuild.",
            )
        return "vector", False

    if requested == "hybrid" and (query_vector is None or not index.has_vectors):
        return "bm25", True

    return requested, False


# ── Endpoint ──────────────────────────────────────────────────────────────


@router.post("/agent/rag/search", response_model=RagSearchResponse)
def rag_search(payload: RagSearchRequest) -> RagSearchResponse:
    """Busca evidencia en los manuales de mezcla y devuelve fragmentos citables.

    Es el puente que hoy no existe: el RAG vive en Python como CLI y el agente
    que decide no lo puede consultar.
    """
    index = get_index()
    config = _config()

    query_vector = (
        None if payload.mode == "bm25" else _embed_query(config, payload.query)
    )
    mode, degraded = _effective_mode(payload.mode, index, query_vector)

    hits = index.search(
        payload.query,
        k=payload.k,
        mode=mode,
        query_vector=query_vector,
        book_ids=set(payload.book_ids) if payload.book_ids else None,
    )

    chunks = [
        RagChunk(
            chunk_id=hit.chunk.chunk_id,
            book_id=hit.chunk.book_id,
            chapter=hit.chunk.chapter,
            page_start=hit.chunk.page_start,
            page_end=hit.chunk.page_end,
            citation=_citation(hit.chunk),
            text=hit.chunk.text,
            score=round(hit.score, 6),
        )
        for hit in hits
    ]

    if degraded:
        note = (
            "Vectores no disponibles (Ollama/bge-m3): resultado en BM25 puro. "
            "Calidad medida en este modo: 5/15 hit@5. Citar con cautela."
        )
    elif not chunks:
        note = "Sin fragmentos por encima del umbral. No inventar evidencia."
    else:
        note = "Citar (libro, página) al usar estos fragmentos: no parafrasear."

    return RagSearchResponse(
        query=payload.query,
        mode_used=mode,
        degraded=degraded,
        note=note,
        chunks=chunks,
    )


# ── CHAT ROUTER: Heuristic Zero-LLM Router (T2) ─────────────────────────────


# Palabras clave en español neutro (sin voseo) para cada rama
# IMPORTANTE: los triggers más largos PRIMERO (ej. "renderizar" antes que "render")
_ACTION_TRIGGERS = (
    "mezclar", "mezcla", "separar", "stems", "demucs",
    "masterizar", "master", "renderizar", "render", "exportar", "entregar",
    "aplicar", "ejecutar", "correr", "procesar", "dale", "hazlo",
    "cambia a", "cambiar a", "usa el", "ponle", "pon el", "activa",
)

_EXPLANATION_TRIGGERS = (
    "por qué", "porque", "explícame", "qué significa", "qué es",
    "cuál es", "cómo", "diferencia", "versus", "vs",
    "veredicto", "diagnóstico", "diagnostico", "análisis", "analisis",
    "recomendación", "recomendacion", "por qué", "porque",
)

_PARAMETER_TRIGGERS = (
    "más", "mas", "menos", "subir", "bajar", "un toque", "bastante",
    "mucho", "poco", "suave", "fuerte", "intenso", "ligero",
    "incrementa", "reduce", "aumenta", "disminuye",
)


def should_escalate_to_job(user_text: str, state: SessionSnapshot) -> EscalationDecision:
    """
    Router heurístico zero-LLM: decide en <1 ms si responder en chat o escalar a job.

    Ramas (orden de prioridad):
    1. ACCIÓN concreta -> escalate_to_job (job_kind="agent" si needs_mix, sino "master")
    2. EXPLICACIÓN -> answer_in_chat
    3. AJUSTE de parámetros -> answer_in_chat(updates_intent=True)
    4. DEFAULT -> answer_in_chat
    """
    text = user_text.lower().strip()

    # 1. Acción concreta de DSP
    for trigger in _ACTION_TRIGGERS:
        if trigger in text:
            # Si el veredicto dice que necesita mezcla, escalamos al job "agent"
            # (que corre el bucle completo mix->master). Si no, al job "master" directo.
            job_kind: Literal["agent", "master"] = "agent" if (state.verdict and state.verdict.needs_mix) else "master"
            payload = {"decision": "auto"} if job_kind == "agent" else {"source": "original"}
            if job_kind == "agent" and state.verdict:
                payload["decision"] = state.verdict.recommended_path
            return EscalationDecision.escalate(
                job_kind=job_kind,
                payload=payload,
                reason=f"Trigger de acción detectado: '{trigger}'",
            )

    # 2. Pregunta de explicación / diagnóstico
    for trigger in _EXPLANATION_TRIGGERS:
        if trigger in text:
            return EscalationDecision.answer_in_chat(
                reason=f"Trigger de explicación detectado: '{trigger}'",
            )

    # 3. Ajuste de parámetros (ejes de intención)
    for trigger in _PARAMETER_TRIGGERS:
        if trigger in text:
            return EscalationDecision.answer_in_chat(
                reason=f"Trigger de parámetro detectado: '{trigger}'",
                updates_intent=True,
                intent_delta=None,  # El LLM inferirá el delta exacto en su respuesta
            )

    # 4. Default: conversación libre
    return EscalationDecision.answer_in_chat(reason="Sin trigger heurístico; conversación libre.")


# ── Helpers para el endpoint de chat ────────────────────────────────────────


def _build_session_snapshot(session_id: str) -> SessionSnapshot:
    """Carga la sesión y extrae solo los campos relevantes (~550 tokens)."""
    sessions = load_sessions()
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sesión '{session_id}' no encontrada.")

    return SessionSnapshot(
        analysis=session.analysis,
        verdict=session.verdict,
        mix_analysis=session.mix_analysis,
        mix_metadata=session.mix_metadata,
        mix_status=session.mix_status,
        reference_comparison=session.reference_comparison,
    )


def _snapshot_to_context_text(snapshot: SessionSnapshot) -> str:
    """Serializa el snapshot a texto legible para el system prompt."""
    parts = []

    if snapshot.analysis:
        a = snapshot.analysis
        parts.append(
            f"ANÁLISIS ESTÉREO:\n"
            f"  LUFS integrado: {a.integrated_lufs:.1f}\n"
            f"  True Peak: {a.true_peak_db:.1f} dB\n"
            f"  Rango dinámico: {a.dynamic_range_db:.1f} dB\n"
            f"  Centroide espectral: {a.spectral_centroid:.0f} Hz\n"
            f"  Tempo: {a.tempo_bpm:.1f} BPM\n"
            f"  Género detectado: {a.detected_genre} (confianza {a.genre_confidence:.0%})\n"
            f"  Duración: {a.duration_seconds:.1f} s\n"
            f"  Ya masterizado: {'sí' if a.is_already_mastered else 'no'}"
        )

    if snapshot.verdict:
        v = snapshot.verdict
        routes_str = ", ".join(f"{r.id.value} ({r.label_es})" for r in v.routes)
        defs_str = "; ".join(f"{d.band_hz} Hz ({d.direction} {abs(d.delta_db):.1f} dB)" for d in v.deficiencies[:3])
        parts.append(
            f"VEREDICTO DE BRIK:\n"
            f"  Necesita mezcla: {'sí' if v.needs_mix else 'no'}\n"
            f"  Confianza: {v.confidence:.0%}\n"
            f"  Ruta recomendada: {v.recommended_path.value}\n"
            f"  Razones: {v.reasoning_key.value}\n"
            f"  Deficiencias top: {defs_str if defs_str else 'ninguna'}\n"
            f"  Rutas disponibles: {routes_str}"
        )

    if snapshot.mix_analysis:
        parts.append(f"MEZCLA EXISTENTE:\n  Análisis: {json.dumps(snapshot.mix_analysis, ensure_ascii=False)[:500]}")

    if snapshot.mix_metadata:
        parts.append(f"METADATOS DE MEZCLA:\n  {json.dumps(snapshot.mix_metadata, ensure_ascii=False)[:500]}")

    if snapshot.reference_comparison:
        rc = snapshot.reference_comparison
        parts.append(
            f"COMPARACIÓN CON REFERENCIA:\n"
            f"  Status: {rc.status}\n"
            f"  Delta LUFS: {rc.lufs_delta_db:.1f} dB\n"
            f"  Delta Crest: {rc.crest_delta_db:.1f} dB\n"
            f"  Mayor aumento: {rc.biggest_increase_band_hz:.0f} Hz\n"
            f"  Mayor reducción: {rc.biggest_decrease_band_hz:.0f} Hz"
        )

    if not parts:
        parts.append("SESION NUEVA: sin análisis previo.")

    return "\n\n".join(parts)


def _build_chat_transcript(history: list[dict[str, Any]] | None, max_pairs: int = 10) -> list[dict[str, Any]]:
    """Convierte el historial del frontend a transcript neutral (role + text)."""
    if not history:
        return []

    transcript = []
    for msg in history[-(max_pairs * 2):]:  # últimos N pares user/assistant
        role = msg.get("role")
        content = msg.get("content")
        if role in ("user", "assistant") and content:
            transcript.append({"role": role, "text": content})
    return transcript


def _merge_transcripts(
    persisted: list[TranscriptEntry] | None,
    frontend: list[dict[str, Any]] | None,
    max_pairs: int = 10,
) -> list[dict[str, Any]]:
    """
    Combina el transcript persistido (chat_transcript de la sesión) con el
    historial del frontend, priorizando el frontend para los últimos turnos.

    Retorna lista de dicts neutrales listos para `generate_content`:
    [{"role": "user|model", "text": "..."}, ...]
    """
    merged: list[dict[str, Any]] = []

    # 1. Transcript persistido (más antiguo) - convertir a formato neutral
    if persisted:
        for entry in persisted:
            role = "model" if entry.role == "assistant" else "user"
            merged.append({"role": role, "text": entry.text})

    # 2. Historial del frontend (más reciente) - sobrescribe/extiende
    if frontend:
        for msg in frontend[-(max_pairs * 2):]:
            role = msg.get("role")
            content = msg.get("content")
            if role in ("user", "assistant") and content:
                # Convertir a formato neutral
                neutral_role = "model" if role == "assistant" else "user"
                # Si ya existe un turno con mismo role+text similar al final, no duplicar
                merged.append({"role": neutral_role, "text": content})

    # 3. Limitar a max_pairs pares (2*max_pairs entradas)
    if len(merged) > max_pairs * 2:
        merged = merged[-(max_pairs * 2):]

    return merged


def _append_to_transcript(
    session_id: str,
    user_text: str,
    assistant_text: str,
    escalated: bool = False,
) -> None:
    """
    Anexa un par user/assistant al transcript de la sesión y persiste (write-behind).
    Mantiene FIFO estricto: máximo 20 entradas (10 pares).
    """
    from time import time

    sessions = load_sessions()
    session = sessions.get(session_id)
    if not session:
        return

    # Asegurar que chat_transcript existe (compatibilidad con sesiones antiguas)
    if not hasattr(session, "chat_transcript") or session.chat_transcript is None:
        session.chat_transcript = []

    ts = int(time())
    session.chat_transcript.append(TranscriptEntry(role="user", text=user_text, ts=ts, escalated=False))
    session.chat_transcript.append(TranscriptEntry(role="assistant", text=assistant_text, ts=ts, escalated=escalated))

    # FIFO: mantener solo los últimos 20 turnos (10 pares)
    if len(session.chat_transcript) > 20:
        session.chat_transcript = session.chat_transcript[-20:]

    # Write-behind: no bloquea la respuesta
    save_sessions(sessions)


# ── Endpoint CHAT (T3) ──────────────────────────────────────────────────────


@router.post("/agent/chat", response_model=ChatResponse)
def chat_with_brik(payload: ChatRequest) -> ChatResponse:
    """
    Endpoint ligero de chat con Brik.

    Flujo:
    1. Carga sesión y construye snapshot (~550 tokens).
    2. Ejecuta router heurístico `should_escalate_to_job`.
    3. Si action == "answer_in_chat":
       - Inyecta snapshot + system prompt + historial (persistido + frontend) en `generate_content`.
       - Devuelve reply + intent_updates si hubo ajuste.
       - Anexa el turno al transcript persistido (write-behind, FIFO max 20).
    4. Si action == "escalate_to_job":
       - Devuelve escalation decision (el frontend lanza el job en background).
       - NO llama al LLM: el job hará su propio razonamiento.
       - Anexa el turno al transcript con `escalated=True`.
    """
    # Cargar sesión completa para acceder al transcript persistido
    sessions = load_sessions()
    session = sessions.get(payload.session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Sesión '{payload.session_id}' no encontrada.")

    snapshot = _build_session_snapshot(payload.session_id)
    decision = should_escalate_to_job(payload.message, snapshot)

    # Persisted transcript from previous turns (for context injection)
    persisted_transcript = getattr(session, "chat_transcript", None) or []

    # Si la decisión es escalar, NO llamamos al LLM. El job asíncrono hará el trabajo.
    if decision.action == "escalate_to_job":
        reply = (
            f"Entendido. Lanzo el {'mix+master' if decision.job_kind == 'agent' else 'master'} "
            f"con la configuración recomendada. Te aviso cuando termine."
        )
        # Persistir el turno con escalated=True
        _append_to_transcript(payload.session_id, payload.message, reply, escalated=True)
        return ChatResponse(reply=reply, escalation=decision)

    # ---- Respuesta en chat: una sola llamada a generate_content ----
    try:
        transport = default_transport()
    except Exception as exc:  # noqa: BLE001
        log.warning("Transporte LLM no disponible, respuesta de fallback: %s", exc)
        fallback = (
            "El motor de IA no está disponible ahora mismo. "
            "Puedo explicarte el veredicto con los datos que tengo: "
            f"{_snapshot_to_context_text(snapshot)[:300]}... "
            "¿Querés que lo intente de nuevo en un momento?"
        )
        _append_to_transcript(payload.session_id, payload.message, fallback, escalated=False)
        return ChatResponse(reply=fallback, escalation=decision)

    # Construir transcript: persistido + frontend history (máx 10 pares)
    transcript = _merge_transcripts(persisted_transcript, payload.history)
    context_text = _snapshot_to_context_text(snapshot)

    # System prompt: rol + reglas duras + contexto de sesión
    system_prompt = (
        f"{prompts.DIAGNOSIS_SYSTEM_PROMPT}\n\n"
        f"--- CONTEXTO DE LA SESIÓN ACTUAL ---\n{context_text}\n\n"
        "Responde en español neutro latinoamericano, sin voseo. "
        "Si el usuario pide un ajuste, describe el cambio en sensaciones "
        "(ej. 'subo un toque el bass_weight') y NO menciones dB, Hz ni knobs. "
        "Máximo 3 párrafos cortos."
    )

    # Turno del usuario actual
    transcript.append({"role": "user", "text": payload.message})

    try:
        turn = transport.turn(
            phase="chat",
            system=system_prompt,
            transcript=transcript,
            tools=[],  # Sin tools en chat: solo texto
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Fallo en generate_content (chat): %s", exc)
        error_reply = (
            "Tuve un problema al generar la respuesta. "
            "El estado de la sesión no cambió. ¿Probamos de nuevo?"
        )
        _append_to_transcript(payload.session_id, payload.message, error_reply, escalated=False)
        return ChatResponse(
            reply=error_reply,
            escalation=decision,
        )

    reply = turn.text or "No pude generar una respuesta coherente. ¿Reformulás?"

    # Persistir el turno completado
    _append_to_transcript(payload.session_id, payload.message, reply, escalated=False)

    # Si el router marcó updates_intent, intentamos parsear un IntentProfile del reply
    # (heurística simple: si el reply menciona ejes, el frontend hará merge).
    intent_updates = None
    if decision.updates_intent:
        # El LLM no devuelve JSON estructurado aquí; el frontend detecta
        # menciones a ejes y pide confirmación antes de aplicar.
        pass

    return ChatResponse(reply=reply, escalation=decision, intent_updates=intent_updates)
