"""Local paths and tool locations for the RAG pipeline (env-overridable)."""

import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePath

#: Levels between this file and the project dir: rag/intelligence/audiomind/src.
_PROJECT_DIR_DEPTH = 4


def _resolve_dirs(config_file: PurePath) -> tuple[PurePath, PurePath]:
    """Resolve ``(project_dir, repo_root)`` from this module's path, never raising.

    Both layouts keep the module at ``<project>/src/audiomind/intelligence/rag``:
    the monorepo (``<repo>/apps/audiomind``) and the Docker image, where the
    Dockerfile copies ``apps/audiomind`` straight to ``/app``. Only the monorepo
    has an ``apps`` level above the project dir, so in the image the project dir
    stands in for the repo root.

    Walking to the project dir is bounded on purpose. Indexing ``Path.parents``
    blind is what took the API down on boot: on ``/app`` there is no second
    ancestor, so ``parents[1]`` raised ``IndexError`` at import time.
    """
    ancestors = list(config_file.parents)
    project_dir = (
        ancestors[_PROJECT_DIR_DEPTH]
        if len(ancestors) > _PROJECT_DIR_DEPTH
        else config_file.parent
    )

    if project_dir.parent.name == "apps":
        return project_dir, project_dir.parent.parent
    return project_dir, project_dir


_AUDIOMIND_DIR, _REPO_ROOT = _resolve_dirs(Path(__file__).resolve())

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
