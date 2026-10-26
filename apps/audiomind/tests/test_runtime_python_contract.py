"""The image, CI and the package metadata must name the same Python.

The 2026-10-22 outage was not a Python bug, but the Python split hid it: the
image and CI ran 3.11 while development ran 3.12, so ``pip`` resolved librosa
0.11.0 in production and 1.0.0 on the machine where the DSP tests were written.
Neither side was wrong on its own and no gate compared them, so the difference
only surfaced as a rhythm confidence that passed locally and failed in the
container.

These tests read the three declarations as text and compare them, so the next
drift fails CI instead of production.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent.parent
DOCKERFILE = BACKEND_DIR / "Dockerfile"
PYPROJECT = BACKEND_DIR / "pyproject.toml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "studio-ci.yml"


def _read(path: Path) -> str:
    if not path.exists():  # pragma: no cover - these files ship with the repo
        pytest.skip(f"{path} not found")
    return path.read_text(encoding="utf-8")


def _minor(version: str) -> tuple[int, int]:
    major, minor = version.split(".")[:2]
    return int(major), int(minor)


def _dockerfile_python() -> tuple[int, int]:
    match = re.search(r"^FROM python:(\d+\.\d+)", _read(DOCKERFILE), re.MULTILINE)
    assert match, "no `FROM python:<version>` line in the Dockerfile"
    return _minor(match.group(1))


def _pyproject_floor() -> tuple[int, int]:
    match = re.search(r'requires-python\s*=\s*">=(\d+\.\d+)"', _read(PYPROJECT))
    assert match, "no requires-python floor in pyproject.toml"
    return _minor(match.group(1))


def _ci_python() -> tuple[int, int]:
    match = re.search(r'python-version:\s*"(\d+\.\d+)"', _read(CI_WORKFLOW))
    assert match, "no python-version in the CI workflow"
    return _minor(match.group(1))


def test_dockerfile_python_satisfies_the_package_floor() -> None:
    """A floor above the image lets pip resolve modules the image cannot import."""
    floor = _pyproject_floor()
    image = _dockerfile_python()
    assert image >= floor, (
        f"the image runs Python {image[0]}.{image[1]} but pyproject allows "
        f">= {floor[0]}.{floor[1]}: a dependency resolution that needs the "
        "newer interpreter would install cleanly and fail in the container"
    )


def test_ci_python_matches_the_image_python() -> None:
    """CI must resolve dependencies with the interpreter production runs."""
    image = _dockerfile_python()
    ci = _ci_python()
    assert ci == image, (
        f"CI runs Python {ci[0]}.{ci[1]} but the image runs "
        f"{image[0]}.{image[1]}. A dependency that resolves differently on "
        "each side is invisible to the whole suite (librosa 0.11 vs 1.0 was "
        "exactly that gap)."
    )
