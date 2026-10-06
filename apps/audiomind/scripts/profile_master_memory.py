"""Profile peak RSS of the real mastering chain, 44.1kHz vs 48kHz.

Facts so far:
  * mix works on Railway (200 in 227s) once the 8 GB limit actually applied
  * master worked on a 44.1kHz / 99s / 25 MiB WAV (29s)
  * master was Killed at 18s on a 48kHz / 53s / 9.7 MiB track

The 48kHz source forces a resample to 44.1kHz, which the 44.1kHz source did
not. This runs the same ``process_audio`` the worker calls and prints peak
memory per stage so we can see whether resampling or the oversampled clipper
blows up.

tracemalloc only sees Python allocations; peak RSS comes from ``ru_maxrss``.
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import time
import tracemalloc

import numpy as np
import soundfile as sf

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from supabase import create_client  # noqa: E402

from audiomind.config import settings  # noqa: E402
from audiomind.models.audio import MasteringParameters  # noqa: E402
from audiomind.processing.engine import process_audio  # noqa: E402

try:  # optional; gives real process RSS on Windows too
    import psutil

    _PROC = psutil.Process()
except Exception:  # noqa: BLE001
    _PROC = None


def rss_mb() -> float:
    """Current process RSS in MiB."""
    if _PROC is not None:
        return _PROC.memory_info().rss / 1048576
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


class Peak:
    """Tracks peak RSS while work runs."""

    def __init__(self) -> None:
        self.peak = 0.0

    def sample(self) -> float:
        self.peak = max(self.peak, rss_mb())
        return self.peak


def run(label: str, path: str) -> None:
    print(f"\n{'=' * 68}\n{label}\n{'=' * 68}")
    peak = Peak()
    before = rss_mb()

    info = sf.info(path)
    print(f"input      : {info.duration:7.1f}s {info.samplerate}Hz {info.channels}ch {info.subtype}")
    peak.sample()

    out_path = path.replace(".wav", "_mastered.wav")
    params = MasteringParameters()
    tracemalloc.start()
    started = time.monotonic()
    result = process_audio(input_path=path, output_path=out_path, params=params)
    elapsed = time.monotonic() - started
    py_current, py_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    out_info = sf.info(out_path)
    print(f"output     : {out_path.rsplit(chr(92), 1)[-1]}")
    print(f"             {out_info.duration:.1f}s {out_info.samplerate}Hz "
          f"{out_info.subtype} {out_info.frames * out_info.channels * 3 / 1048576:.1f}MB")
    print(f"elapsed    : {elapsed:7.1f}s")
    print(f"RSS peak   : {peak.sample():8.1f}MB  (creció {peak.peak - before:+.1f}MB)")
    print(f"py alloc   : {py_peak/1048576:8.1f}MB peak")
    metrics = result.get("metrics") or {}
    if isinstance(metrics, dict):
        print(f"lufs={metrics.get('integrated_lufs')}  peak={metrics.get('true_peak_db')}")


def main() -> None:
    client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    rows = (
        client.table("tracks")
        .select("id,storage_path,status")
        .not_.is_("storage_path", "null")
        .limit(10)
        .execute()
        .data
        or []
    )
    bucket = client.storage.from_(settings.supabase_originals_bucket)

    picked: dict[int, str] = {}
    for row in rows:
        try:
            raw = bucket.download(row["storage_path"])
        except Exception:  # noqa: BLE001
            continue
        path = os.path.join(tempfile.gettempdir(), f"prof_{row['id'][:8]}.wav")
        with open(path, "wb") as handle:
            handle.write(raw)
        info = sf.info(path)
        # one representative track per sample rate
        picked.setdefault(info.samplerate, path)

    for sr in sorted(picked):
        run(f"fuente {sr} Hz", picked[sr])

    print(f"\nlimite Railway configurado: {settings.max_concurrent_dsp} DSP concurrente")


if __name__ == "__main__":
    main()