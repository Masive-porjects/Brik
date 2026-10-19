"""The RAG config must resolve its paths in the monorepo and inside the image.

The Dockerfile copies ``apps/audiomind`` straight to ``/app``, so this module
ends up at ``/app/src/audiomind/intelligence/rag/config.py``: one level less
than in the monorepo. Resolving the repo root by indexing ``Path.parents``
raised ``IndexError`` there at import time and took the whole API down on boot.
"""

from pathlib import PurePosixPath

from audiomind.intelligence.rag import config


def test_monorepo_layout_returns_the_repo_root() -> None:
    project_dir, repo_root = config._resolve_dirs(
        PurePosixPath("/repo/apps/audiomind/src/audiomind/intelligence/rag/config.py")
    )

    assert project_dir == PurePosixPath("/repo/apps/audiomind")
    assert repo_root == PurePosixPath("/repo")


def test_container_layout_falls_back_to_the_project_dir() -> None:
    """The image has no ``apps`` level: the project dir is the root."""

    project_dir, repo_root = config._resolve_dirs(
        PurePosixPath("/app/src/audiomind/intelligence/rag/config.py")
    )

    assert project_dir == PurePosixPath("/app")
    assert repo_root == PurePosixPath("/app")


def test_shallow_path_never_raises() -> None:
    """A relocated module must degrade, not blow up at import time."""

    project_dir, repo_root = config._resolve_dirs(PurePosixPath("/config.py"))

    assert project_dir == PurePosixPath("/")
    assert repo_root == PurePosixPath("/")


def test_local_checkout_resolves_the_monorepo_root() -> None:
    """Whatever the machine, the checkout layout still finds ``apps/audiomind``."""

    assert (config._REPO_ROOT / "apps" / "audiomind").is_dir()
