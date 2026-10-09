"""Canonical chapter labels from noisy headings, footers and figure numbers.

"Chapter Five 31", "CAPÍTULO 5", "Capitulo cinco" and "Figura 5.3" all
mean chapter 5 → ``"Cap. 5"``. Parts become ``"Parte 2"``. OCR reads the
roman "II" as "ll", so ``l`` counts as ``i`` in roman numerals.
"""

import re
import unicodedata

_UNITS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}
_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}

_HEADING = re.compile(
    r"^(chapter|capitulo|part|parte)\s+"
    r"([0-9]{1,3}|[ivxlc]{1,6}|[a-z]+(?:[\s-][a-z]+)?)\b"
)
_FIGURE = re.compile(r"\b(?:figura|figure|fig\.)\s+(\d{1,2})\.\d{1,2}", re.IGNORECASE)
_DOT_LEADER = re.compile(r"\.{4,}|(?:\.\s){4,}")


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in folded if not unicodedata.combining(c)).strip()


def _roman(token: str) -> int | None:
    token = token.replace("l", "i") if set(token) <= {"i", "l"} else token
    if not token or any(c not in _ROMAN for c in token):
        return None
    total = 0
    for current, nxt in zip(token, token[1:] + " ", strict=True):
        value = _ROMAN[current]
        total += -value if nxt in _ROMAN and _ROMAN[nxt] > value else value
    return total if total > 0 else None


def _number(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    words = re.split(r"[\s-]+", token)
    if len(words) == 1 and words[0] in _UNITS:
        return _UNITS[words[0]]
    if words[0] in _TENS:
        rest = _UNITS.get(words[1], 0) if len(words) > 1 else 0
        return _TENS[words[0]] + rest if rest < 10 else None
    return _roman(token)


def canonical_chapter(line: str) -> str | None:
    """``"Cap. N"`` / ``"Parte N"`` for a heading or footer line, else None."""
    if _DOT_LEADER.search(line):  # table-of-contents entry, not a heading
        return None
    match = _HEADING.match(_fold(line))
    if not match:
        return None
    number = _number(match.group(2))
    if number is None:
        # "Chapter Twenty One" may have matched only "twenty": retry the word.
        number = _number(match.group(2).split()[0])
    if number is None or number > 99:
        return None
    kind = "Parte" if match.group(1) in ("part", "parte") else "Cap."
    return f"{kind} {number}"


def chapter_from_figures(text: str) -> str | None:
    """Chapter implied by the first ``Figura N.M`` reference on a page."""
    match = _FIGURE.search(text)
    return f"Cap. {int(match.group(1))}" if match else None
