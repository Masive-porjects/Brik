"""Cache tests for ``splitter.split_audio``.

Demucs costs ~28 s per 10 s of audio (measured), and ``split_audio`` is called
by ``build_mix`` on every render. Without a cache the agentic loop pays that
cost on every iteration.

The dangerous case is the one that gets a test first: a cache must NEVER hand
back stems that belong to a different input. Wrong stems are silent corruption,
so reuse is gated on a manifest that records the input's hash, the model and
the precision.

The separator itself is stubbed: these tests are about the decision to reuse,
not about Demucs.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from audiomind.processing import splitter
from audiomind.processing.splitter import STEM_NAMES, split_audio

SR = 44100


def _write_audio(path: Path, freq: float) -> Path:
    """A tiny real WAV, so the input hash has something to chew on."""
    t = np.linspace(0, 0.05, int(SR * 0.05), endpoint=False)
    stereo = np.stack(
        [np.sin(2 * np.pi * freq * t), np.sin(2 * np.pi * freq * t)], axis=1
    ).astype(np.float32)
    sf.write(str(path), stereo, SR, subtype="PCM_16")
    return path


@pytest.fixture
def fake_demucs(monkeypatch):
    """Replace the separator and count how many times it actually ran."""
    calls: list[tuple[str, str, str]] = []

    def fake(input_path, output_dir, model):
        calls.append((str(input_path), str(output_dir), model))
        target = Path(output_dir).resolve()
        target.mkdir(parents=True, exist_ok=True)
        stems = {}
        for name in STEM_NAMES:
            stem_path = target / f"{name}.wav"
            sf.write(
                str(stem_path),
                np.zeros((256, 2), dtype=np.float32),
                SR,
                subtype="PCM_16",
            )
            stems[name] = str(stem_path)
        return {
            "stems": stems,
            "sample_rate": SR,
            "duration_seconds": 0.005,
            "stem_audio_dir": str(target),
        }

    monkeypatch.setattr(splitter, "_split_audio_isolated", fake)
    return calls


class TestReuse:
    def test_the_first_call_runs_demucs(self, fake_demucs, tmp_path):
        source = _write_audio(tmp_path / "a.wav", 220.0)
        out = tmp_path / "stems"

        result = split_audio(source, output_dir=out)

        assert len(fake_demucs) == 1
        assert set(result["stems"]) == set(STEM_NAMES)
        assert result.get("cache_hit") is not True

    def test_the_second_call_reuses_the_stems(self, fake_demucs, tmp_path):
        source = _write_audio(tmp_path / "a.wav", 220.0)
        out = tmp_path / "stems"

        split_audio(source, output_dir=out)
        second = split_audio(source, output_dir=out)

        assert len(fake_demucs) == 1, "la 2da llamada volvio a pagar Demucs"
        assert second["cache_hit"] is True
        assert set(second["stems"]) == set(STEM_NAMES)

    def test_reuse_does_not_rewrite_the_stem_files(self, fake_demucs, tmp_path):
        source = _write_audio(tmp_path / "a.wav", 220.0)
        out = tmp_path / "stems"

        split_audio(source, output_dir=out)
        before = {
            name: (out / f"{name}.wav").stat().st_mtime_ns for name in STEM_NAMES
        }
        split_audio(source, output_dir=out)
        after = {
            name: (out / f"{name}.wav").stat().st_mtime_ns for name in STEM_NAMES
        }

        assert before == after, "los stems se reescribieron: no hubo reuso real"


class TestInvalidation:
    def test_a_different_input_never_reuses(self, fake_demucs, tmp_path):
        """The case that would silently corrupt audio. Nailed down hard."""
        first = _write_audio(tmp_path / "a.wav", 220.0)
        second = _write_audio(tmp_path / "b.wav", 440.0)
        out = tmp_path / "stems"

        split_audio(first, output_dir=out)
        split_audio(second, output_dir=out)

        assert len(fake_demucs) == 2, "reuso los stems de OTRO input"

    def test_a_different_model_never_reuses(self, fake_demucs, tmp_path):
        source = _write_audio(tmp_path / "a.wav", 220.0)
        out = tmp_path / "stems"

        split_audio(source, output_dir=out, model="htdemucs")
        split_audio(source, output_dir=out, model="htdemucs_ft")

        assert len(fake_demucs) == 2

    def test_a_missing_stem_file_invalidates_the_cache(self, fake_demucs, tmp_path):
        source = _write_audio(tmp_path / "a.wav", 220.0)
        out = tmp_path / "stems"

        split_audio(source, output_dir=out)
        (out / "vocals.wav").unlink()
        split_audio(source, output_dir=out)

        assert len(fake_demucs) == 2, "acepto un cache incompleto"

    def test_a_corrupt_manifest_is_ignored_not_fatal(self, fake_demucs, tmp_path):
        source = _write_audio(tmp_path / "a.wav", 220.0)
        out = tmp_path / "stems"

        split_audio(source, output_dir=out)
        (out / "_stems_manifest.json").write_text("{ no es json", encoding="utf-8")

        result = split_audio(source, output_dir=out)

        assert len(fake_demucs) == 2
        assert result["stems"]

    def test_a_manifest_with_a_bad_hash_never_reuses(self, fake_demucs, tmp_path):
        source = _write_audio(tmp_path / "a.wav", 220.0)
        out = tmp_path / "stems"

        split_audio(source, output_dir=out)
        manifest_path = out / "_stems_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["input_sha256"] = "0" * 64
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        split_audio(source, output_dir=out)

        assert len(fake_demucs) == 2
