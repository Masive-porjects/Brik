"""Raw page text → clean paragraphs + the PRINTED page number.

Citations must use the printed page ("Owsinski pág. 32"), not the PDF
index: the printed number is read from the page header/footer when OCR
catches it, and inferred from the nearest trustworthy detection when it
does not (see ``reconcile_page_numbers``).
"""

import re
from collections import Counter
from dataclasses import dataclass

from audiomind.intelligence.rag.chapters import canonical_chapter, chapter_from_figures

_PAGE_NUMBER_LINE = re.compile(r"^\s*(\d{1,4})\s*$")
# "582 Part 4 Sound Analysis" / "Chapter 5 Equalization 33"
_NUMBER_AT_EDGE = re.compile(r"^\s*(\d{1,4})\s+\D.{0,80}$|^.{0,80}\D\s+(\d{1,4})\s*$")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_EDGE_LINES = 2  # header/footer lines inspected at each end of the page
_RUNNING_HEADER_MIN_SHARE = 0.03
_CONSENSUS_WINDOW = 6  # pages
_VOTE_WINDOW = 10  # pages
# Lines that are layout noise, not content: credits, image placeholders.
_NOISE_LINE = re.compile(
    r"^(©|\(c\)\s*\d{4}|courtesy\b|cortes[ií]a\b|￼+$)", re.IGNORECASE
)


@dataclass(frozen=True)
class CleanPage:
    pdf_index: int
    printed_page: int | None
    paragraphs: tuple[str, ...]
    chapter_hint: str | None = None  # from running footer or figure numbers


def _lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]


def _edge_key(line: str) -> str:
    """Normalize a header/footer line so it repeats across pages."""
    return re.sub(r"\d+", "", line).strip().lower()


def detect_printed_number(lines: list[str]) -> int | None:
    """Printed page number from the first/last non-empty lines, if any."""
    content = [line for line in lines if line.strip()]
    edges = content[:_EDGE_LINES] + content[-_EDGE_LINES:]
    for line in edges:
        match = _PAGE_NUMBER_LINE.match(line)
        if match:
            return int(match.group(1))
    for line in edges:
        if len(line) <= 90:
            match = _NUMBER_AT_EDGE.match(line)
            if match:
                return int(match.group(1) or match.group(2))
    return None


def running_headers(pages: dict[int, str]) -> set[str]:
    """Header/footer lines that repeat on many pages (book title, part…)."""
    counts: Counter[str] = Counter()
    for text in pages.values():
        content = [line for line in _lines(text) if line.strip()]
        edges = {
            _edge_key(line) for line in content[:_EDGE_LINES] + content[-_EDGE_LINES:]
        }
        counts.update(key for key in edges if key)
    threshold = max(5, int(len(pages) * _RUNNING_HEADER_MIN_SHARE))
    return {key for key, count in counts.items() if count >= threshold}


def _is_chapter_footer(line: str) -> bool:
    """Running footer like "Chapter Five 31" (chapter label + page number)."""
    return canonical_chapter(line) is not None and bool(re.search(r"\d\s*$", line))


def chapter_hint(text: str) -> str | None:
    """Chapter of a page: its running footer first, else its figure numbers."""
    content = [line.strip() for line in _lines(text) if line.strip()]
    for line in content[:_EDGE_LINES] + content[-_EDGE_LINES:]:
        if _is_chapter_footer(line):
            return canonical_chapter(line)
    return chapter_from_figures(text)


def to_paragraphs(text: str, drop: set[str] | None = None) -> tuple[str, ...]:
    """Join wrapped lines into paragraphs; blank lines separate paragraphs.

    Hyphenated line breaks are re-joined ("fre-\\nquency" → "frequency");
    standalone page numbers, running headers/footers and layout noise
    (credits, image placeholders) are dropped.
    """
    drop = drop or set()
    lines = _lines(_HYPHEN_BREAK.sub(r"\1\2", text.replace("\r\n", "\n")))
    content_idx = [i for i, line in enumerate(lines) if line.strip()]
    edge_idx = set(content_idx[:_EDGE_LINES] + content_idx[-_EDGE_LINES:])
    paragraphs: list[str] = []
    current: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        is_edge = i in edge_idx
        if is_edge and (
            _PAGE_NUMBER_LINE.match(stripped)
            or _edge_key(stripped) in drop
            or _is_chapter_footer(stripped)
        ):
            continue
        if _NOISE_LINE.match(stripped):
            continue
        if not stripped:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(re.sub(r"\s+", " ", stripped))
    if current:
        paragraphs.append(" ".join(current))
    return tuple(p for p in paragraphs if len(p) > 1)


def reconcile_page_numbers(
    detected: dict[int, int], indices: list[int]
) -> dict[int, int | None]:
    """Printed page for every PDF index, from noisy per-page detections.

    The ``pdf_index - printed`` offset is NOT constant across a book (a
    scan missing a leaf, unnumbered plates), so it is resolved LOCALLY:

    1. A detection is kept only if another detection within
       ``_CONSENSUS_WINDOW`` pages agrees on the same offset — a lone
       figure label or year is OCR noise.
    2. Every page takes the MAJORITY offset among the kept detections
       within ``_VOTE_WINDOW`` pages (two agreeing noise labels lose to
       the surrounding real page numbers); the nearest kept detection
       breaks ties and covers pages with no kept neighbour in range.
    """
    offsets = {index: index - number for index, number in detected.items()}
    kept = sorted(
        index
        for index, offset in offsets.items()
        if any(
            other != index
            and abs(other - index) <= _CONSENSUS_WINDOW
            and offsets[other] == offset
            for other in offsets
        )
    )
    result: dict[int, int | None] = {}
    for index in indices:
        if not kept:
            result[index] = None
            continue
        nearest = min(kept, key=lambda k: (abs(k - index), k > index))
        votes = Counter(offsets[k] for k in kept if abs(k - index) <= _VOTE_WINDOW)
        offset = offsets[nearest]
        if votes:
            best = max(votes.values())
            leaders = {o for o, count in votes.items() if count == best}
            if offset not in leaders:
                offset = min(
                    leaders,
                    key=lambda o: min(abs(k - index) for k in kept if offsets[k] == o),
                )
        printed = index - offset
        result[index] = printed if printed >= 1 else None
    return result


def clean_book(pages: dict[int, str]) -> list[CleanPage]:
    """Clean every page and attach its printed page number and chapter hint."""
    drop = running_headers(pages)
    detected = {
        index: number
        for index, text in pages.items()
        if (number := detect_printed_number(_lines(text))) is not None
    }
    indices = sorted(pages)
    printed = reconcile_page_numbers(detected, indices)
    return [
        CleanPage(
            index,
            printed[index],
            to_paragraphs(pages[index], drop),
            chapter_hint(pages[index]),
        )
        for index in indices
    ]
