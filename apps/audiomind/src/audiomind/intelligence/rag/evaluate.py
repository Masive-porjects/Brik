"""Retrieval evaluation against a versioned set of questions.

Each question lists the (book, printed page range) where the answer lives.
A question is a HIT@k when any of the top-k chunks comes from an expected
book and overlaps an expected page range. Questions and page numbers are
metadata, not book text, so ``eval_questions.json`` is safe to version.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audiomind.intelligence.rag.chunk import Chunk

QUESTIONS_PATH = Path(__file__).with_name("eval_questions.json")


@dataclass(frozen=True)
class Expected:
    """Where the answer lives: printed pages, or PDF pages (0-based index)
    for books without printed numbering (the Spanish 5th-edition ebook)."""

    book_id: str
    page_start: int
    page_end: int
    by_pdf_index: bool = False


@dataclass(frozen=True)
class Question:
    qid: str
    question: str
    expected: tuple[Expected, ...]


def load_questions(path: Path = QUESTIONS_PATH) -> list[Question]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [
        Question(
            qid=row["id"],
            question=row["question"],
            expected=tuple(_expected(e) for e in row["expected"]),
        )
        for row in rows
    ]


def _expected(entry: dict[str, Any]) -> Expected:
    by_pdf = "pdf_pages" in entry
    pages: list[int] = entry["pdf_pages"] if by_pdf else entry["pages"]
    if not pages:
        raise ValueError(f"expected entry without pages: {entry}")
    return Expected(str(entry["book_id"]), int(pages[0]), int(pages[-1]), by_pdf)


def _overlaps(chunk: Chunk, e: Expected) -> bool:
    if e.by_pdf_index:
        start, end = chunk.pdf_start, chunk.pdf_end
    elif chunk.page_start is None or chunk.page_end is None:
        return False
    else:
        start, end = chunk.page_start, chunk.page_end
    return start <= e.page_end and end >= e.page_start


def is_hit(chunk: Chunk, expected: tuple[Expected, ...]) -> bool:
    return any(chunk.book_id == e.book_id and _overlaps(chunk, e) for e in expected)


def first_hit_rank(chunks: list[Chunk], expected: tuple[Expected, ...]) -> int | None:
    """1-based rank of the first relevant chunk, ``None`` if absent."""
    for rank, chunk in enumerate(chunks, start=1):
        if is_hit(chunk, expected):
            return rank
    return None
