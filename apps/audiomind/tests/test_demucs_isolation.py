"""Demucs process isolation — contract tests.

These tests never load the real model. They pin the behaviour that makes the
isolation trustworthy:

* ``split_audio`` dispatches to a child process by default and returns the
  child's result verbatim (same keys, same stems)
* the child is invoked with the precision baked into the image, so it cannot
  silently trigger a request-time download
* a non-zero child exit raises instead of returning a half-built result
* stems missing on disk are treated as a failure, not a partial success
* isolation can be turned off for in-process runs

The regression this guards: HTDemucs does not return memory to the OS, so an
in-process run left the Uvicorn worker unable to serve the next mastering job
(kernel SIGKILL -> HTTP 502).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from audiomind.processing import splitter
from audiomind.processing.splitter import STEM_NAMES


def _fake_stems(target: Path) -> dict[str, str]:
    target.mkdir(parents=True, exist_ok=True)
    out = {}
    for name in STEM_NAMES:
        path = target / f"{name}.wav"
        path.write_bytes(b"RIFFfake")
        out[name] = str(path)
    return out


def _patch_subprocess(monkeypatch, *, returncode=0, payload=None, stderr=""):
    """Replace subprocess.run and capture the argv the parent built."""
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")

        # argv is INPUT OUTPUT_DIR MODEL PRECISION RESULT_JSON THREADS; the
        # result file is positional (-2), not the last argument.
        result_file = Path(cmd[-2])
        if returncode == 0 and payload is not None:
            result_file.write_text(json.dumps(payload), encoding="utf-8")
        return subprocess.CompletedProcess(
            args=cmd, returncode=returncode, stdout="", stderr=stderr
        )

    monkeypatch.setattr(splitter.subprocess, "run", fake_run)
    return captured


class TestIsolatedDispatch:
    def test_default_routes_through_a_child_process(self, tmp_path, monkeypatch):
        monkeypatch.setattr(splitter.settings, "demucs_isolated", True)
        source = tmp_path / "in.wav"
        source.write_bytes(b"RIFF")
        target = tmp_path / "stems"
        payload = {
            "stems": _fake_stems(target),
            "sample_rate": 44100,
            "duration_seconds": 12.5,
            "stem_audio_dir": str(target),
        }

        captured = _patch_subprocess(monkeypatch, payload=payload)
        result = splitter.split_audio(source, target)

        # The parent must actually have spawned a child.
        assert captured["cmd"][:3] == [sys.executable, "-m",
                                       "audiomind.processing.demucs_worker"]
        assert result["sample_rate"] == 44100
        assert result["duration_seconds"] == 12.5
        assert set(result["stems"]) == set(STEM_NAMES)

    def test_child_receives_a_thread_cap(self, tmp_path, monkeypatch):
        """Uncapped ONNX+OpenBLAS arenas SIGKILLed the child at startup."""
        monkeypatch.setattr(splitter.settings, "demucs_isolated", True)
        monkeypatch.setattr(splitter.settings, "demucs_threads", 4)
        source = tmp_path / "in.wav"
        source.write_bytes(b"RIFF")
        target = tmp_path / "stems"
        payload = {
            "stems": _fake_stems(target),
            "sample_rate": 44100,
            "duration_seconds": 1.0,
            "stem_audio_dir": str(target),
        }
        captured = _patch_subprocess(monkeypatch, payload=payload)

        splitter.split_audio(source, target)

        assert captured["cmd"][-1] == "4"

    def test_child_receives_the_baked_precision(self, tmp_path, monkeypatch):
        """A precision mismatch would make demucs-onnx download ~300 MB."""
        monkeypatch.setattr(splitter.settings, "demucs_isolated", True)
        monkeypatch.setattr(splitter.settings, "demucs_precision", "fp16weights")
        source = tmp_path / "in.wav"
        source.write_bytes(b"RIFF")
        target = tmp_path / "stems"
        payload = {
            "stems": _fake_stems(target),
            "sample_rate": 44100,
            "duration_seconds": 1.0,
            "stem_audio_dir": str(target),
        }
        captured = _patch_subprocess(monkeypatch, payload=payload)

        splitter.split_audio(source, target)

        assert "fp16weights" in captured["cmd"]

    def test_timeout_is_generous_enough_for_cpu_separation(self, tmp_path, monkeypatch):
        monkeypatch.setattr(splitter.settings, "demucs_isolated", True)
        monkeypatch.setattr(splitter.settings, "demucs_timeout_seconds", 1800)
        source = tmp_path / "in.wav"
        source.write_bytes(b"RIFF")
        target = tmp_path / "stems"
        payload = {
            "stems": _fake_stems(target),
            "sample_rate": 44100,
            "duration_seconds": 1.0,
            "stem_audio_dir": str(target),
        }
        captured = _patch_subprocess(monkeypatch, payload=payload)

        splitter.split_audio(source, target)

        # A 30s probe took 227s on 8 vCPU; a tight timeout would kill real work.
        assert captured["timeout"] >= 1800


class TestIsolatedFailureModes:
    def test_child_crash_raises_with_stderr_tail(self, tmp_path, monkeypatch):
        monkeypatch.setattr(splitter.settings, "demucs_isolated", True)
        source = tmp_path / "in.wav"
        source.write_bytes(b"RIFF")
        _patch_subprocess(monkeypatch, returncode=1, stderr="boom\nonnx failed here")

        with pytest.raises(RuntimeError, match="Demucs isolation failed"):
            splitter.split_audio(source, tmp_path / "stems")

    def test_missing_result_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(splitter.settings, "demucs_isolated", True)
        source = tmp_path / "in.wav"
        source.write_bytes(b"RIFF")
        _patch_subprocess(monkeypatch, returncode=0, payload=None)

        with pytest.raises(RuntimeError, match="no result file"):
            splitter.split_audio(source, tmp_path / "stems")

    def test_partial_stems_are_a_failure_not_a_partial_success(self, tmp_path, monkeypatch):
        """A silently missing stem would render a broken mix downstream."""
        monkeypatch.setattr(splitter.settings, "demucs_isolated", True)
        source = tmp_path / "in.wav"
        source.write_bytes(b"RIFF")
        target = tmp_path / "stems"
        target.mkdir(parents=True, exist_ok=True)
        partial = {name: str(target / f"{name}.wav") for name in ("drums", "bass")}
        for path in partial.values():
            Path(path).write_bytes(b"RIFF")
        payload = {
            "stems": partial,
            "sample_rate": 44100,
            "duration_seconds": 3.0,
            "stem_audio_dir": str(target),
        }
        _patch_subprocess(monkeypatch, payload=payload)

        with pytest.raises(RuntimeError) as excinfo:
            splitter.split_audio(source, target)

        message = str(excinfo.value)
        assert "no audio" in message
        assert "other" in message and "vocals" in message

    def test_timeout_is_reported_clearly(self, tmp_path, monkeypatch):
        monkeypatch.setattr(splitter.settings, "demucs_isolated", True)
        monkeypatch.setattr(splitter.settings, "demucs_timeout_seconds", 5)
        source = tmp_path / "in.wav"
        source.write_bytes(b"RIFF")

        def boom(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 5)

        monkeypatch.setattr(splitter.subprocess, "run", boom)

        with pytest.raises(TimeoutError, match="timed out after 5s"):
            splitter.split_audio(source, tmp_path / "stems")


class TestIsolationToggle:
    def test_can_fall_back_to_in_process(self, tmp_path, monkeypatch):
        """Needed for local debugging and for tests that stub the model."""
        monkeypatch.setattr(splitter.settings, "demucs_isolated", False)
        source = tmp_path / "in.wav"
        source.write_bytes(b"RIFF")

        def boom(*args, **kwargs):  # pragma: no cover - must never run
            raise AssertionError("subprocess must not be used when disabled")

        monkeypatch.setattr(splitter.subprocess, "run", boom)
        monkeypatch.setattr(
            splitter,
            "_split_audio_in_process",
            lambda *_a, **_k: {"stems": {}, "sample_rate": 44100,
                              "duration_seconds": 0.0, "stem_audio_dir": ""},
        )

        assert splitter.split_audio(source, tmp_path / "stems")["sample_rate"] == 44100


class TestWorkerContract:
    def test_worker_rejects_wrong_arity(self, capsys):
        from audiomind.processing.demucs_worker import main

        assert main(["only", "three", "args"]) == 2
        assert "usage" in capsys.readouterr().err

    def test_worker_caps_threads_before_importing_onnx(self):
        """The cap must land in os.environ BEFORE numpy/onnxruntime import.

        Both libraries read these at import time, so setting them afterwards has
        no effect — which is what let the child be SIGKILLed on startup.
        """
        import inspect

        from audiomind.processing import demucs_worker

        source = inspect.getsource(demucs_worker.separate)
        cap_at = source.find('os.environ[var] = threads')
        imports_at = source.find("import demucs_onnx")

        assert cap_at != -1, "worker must set the thread cap"
        assert imports_at != -1
        assert cap_at < imports_at, (
            "thread cap must be set before importing demucs_onnx — those "
            "libraries read the env at import time"
        )

    def test_worker_writes_the_result_contract(self, tmp_path):
        """The parent parses exactly these keys; drift here breaks the mix."""
        from audiomind.processing.demucs_worker import STEM_NAMES as WORKER_STEMS
        from audiomind.processing.splitter import STEM_NAMES as PARENT_STEMS

        assert WORKER_STEMS == PARENT_STEMS