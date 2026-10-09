"""Local paths and tool locations for the RAG pipeline (env-overridable)."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

_AUDIOMIND_DIR = Path(__file__).resolve().parents[4]  # apps/audiomind
_REPO_ROOT = _AUDIOMIND_DIR.parents[1]

_WINDOWS_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")


def _tesseract_cmd() -> str:
    explicit = os.environ.get("TESSERACT_CMD")
    if explicit:
        return explicit
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    if _WINDOWS_TESSERACT.exists():
        return str(_WINDOWS_TESSERACT)
    return "tesseract"


@dataclass(frozen=True)
class RagConfig:
    books_dir: Path
    data_dir: Path
    tesseract_cmd: str
    tessdata_dir: Path | None
    ollama_url: str
    embed_model: str

    @property
    def pages_dir(self) -> Path:
        return self.data_dir / "pages"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @classmethod
    def from_env(cls) -> "RagConfig":
        tessdata = os.environ.get("RAG_TESSDATA_DIR")
        return cls(
            books_dir=Path(
                os.environ.get(
                    "RAG_BOOKS_DIR", _REPO_ROOT / "Libros de Mezcla y Masterizacion"
                )
            ),
            data_dir=Path(os.environ.get("RAG_DATA_DIR", _AUDIOMIND_DIR / ".rag")),
            tesseract_cmd=_tesseract_cmd(),
            tessdata_dir=Path(tessdata) if tessdata else None,
            ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434"),
            embed_model=os.environ.get("RAG_EMBED_MODEL", "bge-m3"),
        )
