"""Catalog of the source books — metadata only, never their content.

``book_id`` is the stable key used in chunks and citations. ``method``
says how text is obtained: ``text`` reads the PDF text layer, ``ocr``
renders each page and runs Tesseract (scanned books, or PDFs whose fonts
remap characters so the text layer is unreadable).

``reference_for_code`` marks the edition the Mix Engine already cites
("Owsinski pág. 32" in ``magic_frequencies.py``, ``dynamics.py``…): the
assistant must cite page numbers from that same edition.
"""

from dataclasses import dataclass
from typing import Literal

ExtractMethod = Literal["text", "ocr"]


@dataclass(frozen=True)
class Book:
    book_id: str
    filename: str
    title: str
    author: str
    edition: str
    language: Literal["es", "en"]
    method: ExtractMethod
    priority: int  # 1 = ingest first
    reference_for_code: bool = False

    @property
    def tesseract_lang(self) -> str:
        return {"es": "spa", "en": "eng"}[self.language]

    def citation(self, page: int | None, pdf_index: int | None = None) -> str:
        """Human citation; printed page preferred, PDF page as fallback
        (books without printed numbering, e.g. the 5th-edition ebook)."""
        if page is not None:
            where = f", pág. {page}"
        elif pdf_index is not None:
            where = f", pág. PDF {pdf_index + 1}"
        else:
            where = ""
        return f"{self.author}, {self.title} ({self.edition}){where}"


BOOKS: tuple[Book, ...] = (
    Book(
        book_id="owsinski-meh-1e-en",
        filename="pdf-the-mixing-engineers-handbookpdf_compress.pdf",
        title="The Mixing Engineer's Handbook",
        author="Bobby Owsinski",
        edition="1.ª ed., 1999",
        language="en",
        method="ocr",  # scanned images, no text layer
        priority=1,
        reference_for_code=True,
    ),
    Book(
        book_id="owsinski-meh-5e-es",
        filename="ilide.info-the-mixing-engineer-s-handbook-espanol.pdf",
        title="Manual del ingeniero de mezcla",
        author="Bobby Owsinski",
        edition="5.ª ed., 2022",
        language="es",
        method="text",
        priority=1,
    ),
    Book(
        book_id="gibson-art-of-mixing-es",
        filename="pdf-the-art-of-mixing-esp_compress.pdf",
        title="El arte de la mezcla",
        author="David Gibson",
        edition="edición en español",
        language="es",
        method="ocr",  # text layer uses remapped glyphs ("Rdi muåi" = "Una guía")
        priority=2,
    ),
    Book(
        book_id="roads-computer-music-tutorial-en",
        filename="computer-music-tutorial-curtis-roads.pdf",
        title="The Computer Music Tutorial",
        author="Curtis Roads",
        edition="1996",
        language="en",
        method="ocr",  # tiff2pdf scan, 1253 pages
        priority=3,
    ),
)


def get_book(book_id: str) -> Book:
    for book in BOOKS:
        if book.book_id == book_id:
            return book
    raise KeyError(f"Unknown book_id {book_id!r}")
