"""Clean pages → retrieval chunks with chapter + page-range metadata.

Chunks are built from whole paragraphs up to ``target_words``, carry a
small paragraph overlap so an idea split across chunks stays findable,
and NEVER cross a chapter boundary (a chunk mixing two chapters cites
badly and retrieves worse). Oversized paragraphs are split by sentence.

The chapter comes from the page's hint (running footer / figure numbers)
and from heading paragraphs, both normalized to ``"Cap. N"``.
"""

import re
from dataclasses import asdict, dataclass
from typing import Any

from audiomind.intelligence.rag.chapters import canonical_chapter
from audiomind.intelligence.rag.clean import CleanPage

TARGET_WORDS = 320
MAX_WORDS = 480
OVERLAP_WORDS = 60
MIN_CHUNK_WORDS = 25

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    book_id: str
    chapter: str
    page_start: int | None
    page_end: int | None
    pdf_start: int
    pdf_end: int
    text: str

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, row: dict[str, Any]) -> "Chunk":
        return cls(**row)


@dataclass(frozen=True)
class _Para:
    text: str
    pdf_index: int
    printed: int | None


def heading_chapter(paragraph: str) -> str | None:
    """Canonical chapter if ``paragraph`` is a short chapter/part heading."""
    if len(paragraph) > 80:
        return None
    return canonical_chapter(paragraph.strip())


def _split_long(paragraph: str) -> list[str]:
    """Split an oversized paragraph into sentence groups ≤ MAX_WORDS."""
    if len(paragraph.split()) <= MAX_WORDS:
        return [paragraph]
    parts: list[str] = []
    current: list[str] = []
    for sentence in _SENTENCE_END.split(paragraph):
        if current and len(" ".join(current + [sentence]).split()) > MAX_WORDS:
            parts.append(" ".join(current))
            current = []
        current.append(sentence)
    if current:
        parts.append(" ".join(current))
    return parts


def chunk_book(
    book_id: str,
    pages: list[CleanPage],
    target_words: int = TARGET_WORDS,
    overlap_words: int = OVERLAP_WORDS,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    chapter = ""
    buffer: list[_Para] = []

    def flush(keep_overlap: bool) -> None:
        nonlocal buffer
        if not buffer:
            return
        printed = [p.printed for p in buffer if p.printed is not None]
        chunks.append(
            Chunk(
                chunk_id=f"{book_id}#{len(chunks):05d}",
                book_id=book_id,
                chapter=chapter,
                page_start=min(printed) if printed else None,
                page_end=max(printed) if printed else None,
                pdf_start=buffer[0].pdf_index,
                pdf_end=buffer[-1].pdf_index,
                text="\n\n".join(p.text for p in buffer),
            )
        )
        if not keep_overlap:
            buffer = []
            return
        tail: list[_Para] = []
        words = 0
        for para in reversed(buffer):
            words += len(para.text.split())
            if words > overlap_words:
                break
            tail.insert(0, para)
        buffer = tail

    def enter(label: str) -> None:
        nonlocal chapter
        if label != chapter:
            flush(keep_overlap=False)  # never carry text across chapters
            chapter = label

    for page in pages:
        if page.chapter_hint:
            enter(page.chapter_hint)
        for paragraph in page.paragraphs:
            label = heading_chapter(paragraph)
            if label:
                enter(label)
                continue
            for piece in _split_long(paragraph):
                buffer.append(_Para(piece, page.pdf_index, page.printed_page))
                if sum(len(p.text.split()) for p in buffer) >= target_words:
                    flush(keep_overlap=True)
    flush(keep_overlap=False)
    return [c for c in chunks if c.word_count >= MIN_CHUNK_WORDS]
