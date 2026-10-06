"""The Demucs ONNX precision baked into the image must match what runtime asks for.

demucs-onnx keys its download cache by precision. If the Dockerfile bakes one
precision and ``split_audio()`` asks for another, nothing raises: the first
separation simply downloads the missing graph *inside the request*, which is
the request-time download that OOM-killed the container.

These tests read the Dockerfile as text and compare it against the settings
default, so the two cannot drift apart unnoticed.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from audiomind.config import Settings

BACKEND_DIR = Path(__file__).resolve().parent.parent
DOCKERFILE = BACKEND_DIR / "Dockerfile"

#: Weights baked at build time. demucs-onnx downloads whatever the runtime
#: asks for and nothing else, so this is the single most expensive mismatch.
BAKED_MODEL = "htdemucs"


def _dockerfile_text() -> str:
    if not DOCKERFILE.exists():  # pragma: no cover - Dockerfile ships with the repo
        pytest.skip(f"Dockerfile not found at {DOCKERFILE}")
    return DOCKERFILE.read_text(encoding="utf-8")


class TestDockerfilePrewarm:
    """The build step that bakes the ONNX graph into the image."""

    def test_prewarm_bakes_the_model_the_app_actually_uses(self) -> None:
        """prewarm() defaults to htdemucs_ft, which splitter.py never loads."""
        match = re.search(r"prewarm\(\[(?P<model>'[^']+')\]", _dockerfile_text())
        assert match, "no prewarm([...]) call found in the Dockerfile"

        baked = match.group("model").strip("'")
        assert baked == BAKED_MODEL, (
            f"Dockerfile bakes '{baked}' but processing/splitter.py calls "
            f"separate(model='{BAKED_MODEL}'). The runtime would download the "
            "other graph on first use."
        )

    def test_baked_precision_matches_runtime_precision(self) -> None:
        """The invariant: bake and request must name the same precision."""
        match = re.search(r"prewarm\([^)]*precision='(?P<precision>\w+)'", _dockerfile_text())
        assert match, "no precision= argument in the Dockerfile prewarm call"

        baked = match.group("precision")
        requested = Settings().demucs_precision
        assert baked == requested, (
            f"Dockerfile bakes '{baked}' but runtime requests '{requested}'. "
            "demucs-onnx keys its cache by precision, so the missing graph is "
            "downloaded inside the request (the original OOM)."
        )

    def test_prewarm_log_does_not_use_json_dumps_on_paths(self) -> None:
        """prewarm() returns dict[str, Path]; json.dumps() fails on PosixPath."""
        prewarm_line = next(
            line
            for line in _dockerfile_text().splitlines()
            if "prewarm(" in line
        )
        assert "json.dumps" not in prewarm_line, (
            "json.dumps() on prewarm()'s dict[str, Path] raises TypeError and "
            "fails the whole build after the weights already downloaded"
        )


class TestSplitterRequestsBakedPrecision:
    """split_audio() must pass the precision explicitly, not inherit a default."""

    def test_split_audio_passes_precision_from_settings(self) -> None:
        splitter = (BACKEND_DIR / "src/audiomind/processing/splitter.py").read_text(
            encoding="utf-8"
        )
        assert "precision=settings.demucs_precision" in splitter, (
            "split_audio() must pass precision=settings.demucs_precision so the "
            "request cannot silently diverge from the baked weights"
        )

    def test_default_precision_is_fp16weights(self) -> None:
        """fp32 is ~302 MiB of weights; fp16weights is ~158 MiB."""
        assert Settings().demucs_precision == "fp16weights"

    def test_invalid_precision_is_rejected_at_startup(self) -> None:
        """A typo must fail loudly, not silently trigger a runtime download."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            Settings(demucs_precision="fp16")  # type: ignore[arg-type]
