"""PDF → raw page text, via the text layer or Tesseract OCR.

Output: ``<data_dir>/pages/<book_id>.jsonl``, one ``{"pdf_index", "text"}``
object per page. Extraction is RESUMABLE: pages already present are
skipped, so a long OCR run (Roads: 1253 pages) can be interrupted and
continued. Heavy imports (pypdfium2) are lazy: install the ``rag`` extra.
"""

import json
import subprocess
import tempfile
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from audiomind.intelligence.rag.books import Book
from audiomind.intelligence.rag.config import RagConfig

OCR_DPI = 300


def pages_path(config: RagConfig, book: Book) -> Path:
    return config.pages_dir / f"{book.book_id}.jsonl"


def load_raw_pages(path: Path) -> dict[int, str]:
    """Read a pages JSONL into ``{pdf_index: text}`` (missing file → empty)."""
    if not path.exists():
        return {}
    pages: dict[int, str] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                pages[int(row["pdf_index"])] = str(row["text"])
    return pages


def _append_pages(path: Path, rows: Iterable[tuple[int, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for index, text in rows:
            fh.write(json.dumps({"pdf_index": index, "text": text}, ensure_ascii=False))
            fh.write("\n")


def _page_count(pdf_path: Path) -> int:
    import pypdfium2 as pdfium

    return len(pdfium.PdfDocument(str(pdf_path)))


def _text_layer_page(pdf_path: Path, index: int) -> str:
    import pypdfium2 as pdfium

    page = pdfium.PdfDocument(str(pdf_path))[index]
    return str(page.get_textpage().get_text_range())


def _ocr_page(
    pdf_path: Path, index: int, lang: str, tesseract_cmd: str, tessdata: Path | None
) -> str:
    """Render one page at OCR_DPI and run Tesseract on it.

    Tesseract writes its result to a UTF-8 file (``outbase.txt``) — reading
    stdout on Windows mangles accents depending on the console codepage.
    """
    import pypdfium2 as pdfium

    page = pdfium.PdfDocument(str(pdf_path))[index]
    image = page.render(scale=OCR_DPI / 72).to_pil().convert("L")
    with tempfile.TemporaryDirectory() as tmp:
        image_path = Path(tmp) / "page.png"
        out_base = Path(tmp) / "page"
        image.save(image_path)
        cmd = [tesseract_cmd, str(image_path), str(out_base), "-l", lang, "--psm", "3"]
        if tessdata is not None:
            cmd += ["--tessdata-dir", str(tessdata)]
        subprocess.run(cmd, check=True, capture_output=True)
        return out_base.with_suffix(".txt").read_text(encoding="utf-8")


def _extract_one(args: tuple[str, int, str, str, str, str | None]) -> tuple[int, str]:
    method, index, pdf, lang, tesseract_cmd, tessdata = args
    pdf_path = Path(pdf)
    if method == "text":
        return index, _text_layer_page(pdf_path, index)
    tess_dir = Path(tessdata) if tessdata else None
    return index, _ocr_page(pdf_path, index, lang, tesseract_cmd, tess_dir)


def extract_book(
    config: RagConfig, book: Book, workers: int = 4, limit: int | None = None
) -> int:
    """Extract every missing page of ``book``; return how many were added."""
    pdf_path = config.books_dir / book.filename
    if not pdf_path.exists():
        raise FileNotFoundError(f"{pdf_path} not found (set RAG_BOOKS_DIR)")
    out = pages_path(config, book)
    done = load_raw_pages(out)
    todo = [i for i in range(_page_count(pdf_path)) if i not in done]
    if limit is not None:
        todo = todo[:limit]
    tessdata = str(config.tessdata_dir) if config.tessdata_dir else None
    jobs = [
        (
            book.method,
            i,
            str(pdf_path),
            book.tesseract_lang,
            config.tesseract_cmd,
            tessdata,
        )
        for i in todo
    ]
    added = 0
    batch: list[tuple[int, str]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for index, text in pool.map(_extract_one, jobs, chunksize=1):
            batch.append((index, text))
            if len(batch) >= 10:  # flush often: progress survives interruptions
                _append_pages(out, batch)
                added += len(batch)
                batch = []
    if batch:
        _append_pages(out, batch)
        added += len(batch)
    return added
