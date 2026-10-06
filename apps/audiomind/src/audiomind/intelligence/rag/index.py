"""Local hybrid index: BM25 (exact terms) + vectors (meaning), fused by RRF.

Vectors alone miss exact technical tokens ("1176", "400 Hz", "hi-hat");
BM25 alone misses paraphrases ("que pegue más" ↔ "punch"). Reciprocal
Rank Fusion combines both rankings without having to calibrate scores.

Without embeddings (Ollama absent) the index still works in BM25-only
mode, so the pipeline degrades instead of failing.
"""

import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import numpy.typing as npt

from audiomind.intelligence.rag.chunk import Chunk

SearchMode = Literal["bm25", "vector", "hybrid"]

RRF_K = 60
_BM25_K1 = 1.5
_BM25_B = 0.75
_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a al algo como con de del el en es esta este la las le lo los mas me mi muy "
    "no o para pero por que se si sin su sus te tu un una uno y ya "
    "an and are as at be but by for from has have in is it its of on or "
    "that the this to was were will with you your".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase, fold accents (canción → cancion), drop stopwords."""
    folded = unicodedata.normalize("NFKD", text.lower())
    ascii_text = "".join(c for c in folded if not unicodedata.combining(c))
    return [t for t in _TOKEN.findall(ascii_text) if t not in _STOPWORDS]


class BM25:
    def __init__(self, documents: list[list[str]]) -> None:
        self.doc_freqs = [Counter(doc) for doc in documents]
        self.doc_lens = [len(doc) for doc in documents]
        self.avg_len = sum(self.doc_lens) / max(len(documents), 1)
        df: Counter[str] = Counter()
        for freqs in self.doc_freqs:
            df.update(freqs.keys())
        n = len(documents)
        self.idf = {
            term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()
        }

    def scores(self, query: list[str]) -> list[float]:
        result: list[float] = []
        for freqs, length in zip(self.doc_freqs, self.doc_lens, strict=True):
            score = 0.0
            for term in query:
                tf = freqs.get(term, 0)
                if tf:
                    norm = _BM25_K1 * (1 - _BM25_B + _BM25_B * length / self.avg_len)
                    score += self.idf[term] * tf * (_BM25_K1 + 1) / (tf + norm)
            result.append(score)
        return result


def rrf_fuse(rankings: list[list[int]], k: int = RRF_K) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion of several rankings (lists of doc indices).

    Returns ``(doc, score)`` pairs, best first; ties break by doc index so
    results are deterministic.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking):
            scores[doc] = scores.get(doc, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


class RagIndex:
    def __init__(
        self, chunks: list[Chunk], embeddings: npt.NDArray[np.float32] | None = None
    ) -> None:
        if embeddings is not None and len(embeddings) != len(chunks):
            raise ValueError("embeddings rows must match chunks")
        self.chunks = chunks
        self.embeddings = embeddings
        self.bm25 = BM25([tokenize(c.text + " " + c.chapter) for c in chunks])

    @property
    def has_vectors(self) -> bool:
        return self.embeddings is not None

    def _allowed(self, book_ids: set[str] | None) -> list[int]:
        return [
            i
            for i, c in enumerate(self.chunks)
            if book_ids is None or c.book_id in book_ids
        ]

    def search(
        self,
        query: str,
        k: int = 5,
        mode: SearchMode = "hybrid",
        query_vector: npt.NDArray[np.float32] | None = None,
        book_ids: set[str] | None = None,
        depth: int = 50,
    ) -> list[Hit]:
        allowed = self._allowed(book_ids)
        rankings: list[list[int]] = []
        if mode in ("bm25", "hybrid"):
            bm25 = self.bm25.scores(tokenize(query))
            ranked = sorted((i for i in allowed if bm25[i] > 0), key=lambda i: -bm25[i])
            rankings.append(ranked[:depth])
        if mode in ("vector", "hybrid"):
            if self.embeddings is None or query_vector is None:
                if mode == "vector":
                    raise ValueError(
                        "vector search needs embeddings and a query vector"
                    )
            else:
                sims = self.embeddings @ query_vector
                rankings.append(sorted(allowed, key=lambda i: -float(sims[i]))[:depth])
        return [Hit(self.chunks[i], score) for i, score in rrf_fuse(rankings)[:k]]

    # ── persistence (data dir only — never the repo) ─────────────────
    def save(self, directory: Path, model: str | None) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "chunks.jsonl").open("w", encoding="utf-8") as fh:
            for chunk in self.chunks:
                fh.write(json.dumps(chunk.to_json(), ensure_ascii=False) + "\n")
        if self.embeddings is not None:
            np.save(directory / "embeddings.npy", self.embeddings)
        meta = {
            "chunks": len(self.chunks),
            "embed_model": model if self.embeddings is not None else None,
            "dim": int(self.embeddings.shape[1])
            if self.embeddings is not None
            else None,
        }
        (directory / "meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, directory: Path) -> "RagIndex":
        with (directory / "chunks.jsonl").open(encoding="utf-8") as fh:
            chunks = [Chunk.from_json(json.loads(line)) for line in fh if line.strip()]
        vectors_path = directory / "embeddings.npy"
        embeddings = np.load(vectors_path) if vectors_path.exists() else None
        return cls(chunks, embeddings)
