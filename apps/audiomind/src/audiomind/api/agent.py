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
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from audiomind.intelligence.rag.chunk import Chunk
from audiomind.intelligence.rag.config import RagConfig
from audiomind.intelligence.rag.embed import EmbeddingUnavailableError, OllamaEmbedder
from audiomind.intelligence.rag.index import RagIndex, SearchMode

log = logging.getLogger(__name__)

router = APIRouter()

#: Cuántos fragmentos se piden por defecto. El plan de IA pide 4-6 por turno.
DEFAULT_K = 5
MAX_K = 20


# ── Contratos ─────────────────────────────────────────────────────────────


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


# ── Índice: carga perezosa, una sola vez ──────────────────────────────────

_index_lock = threading.Lock()
_index: RagIndex | None = None
_index_error: str | None = None


def _config() -> RagConfig:
    """Rutas del RAG desde el entorno (mismo factory que usa el CLI)."""
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
