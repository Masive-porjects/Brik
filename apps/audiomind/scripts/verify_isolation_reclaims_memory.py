"""Prove the isolation actually reclaims memory — the bug this fixes.

Runs the real Demucs separation twice in this process and prints RSS before,
during and after. Without the child-process boundary, RSS stays elevated after
the call and the Uvicorn worker cannot serve the next mastering job (kernel
SIGKILL -> HTTP 502).

Run it directly:

    python scripts/verify_isolation_reclaims_memory.py
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import time

import soundfile as sf

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from audiomind.processing.splitter import STEM_NAMES, split_audio  # noqa: E402

try:
    import psutil

    PROC = psutil.Process()
except Exception:  # noqa: BLE001
    PROC = None


def rss_mb() -> float:
    if PROC is not None:
        return PROC.memory_info().rss / 1048576
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except OSError:
        pass
    return 0.0


def main() -> None:
    probe = pathlib.Path(__file__).resolve().parents[1] / "samples" / "mix_probe.wav"
    if not probe.exists():
        generate = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "generate_samples.py"
        print(f"falta {probe.name}; generá uno con: python {generate}")
        sys.exit(1)

    info = sf.info(str(probe))
    print(f"entrada: {probe.name}  {info.duration:.1f}s {info.samplerate}Hz")
    print(f"aislamiento: {__import__('audiomind.config', fromlist=['settings']).settings.demucs_isolated}\n")

    baseline = rss_mb()
    print(f"RSS inicial:  {baseline:8.1f} MB")

    retained = []
    for run in (1, 2):
        with tempfile.TemporaryDirectory() as scratch:
            target = pathlib.Path(scratch) / "stems"
            started = time.monotonic()
            result = split_audio(probe, target)
            elapsed = time.monotonic() - started

            missing = [n for n in STEM_NAMES if n not in result["stems"]]
            after = rss_mb()
            retained.append(after)

            print(
                f"\npasada {run}: {elapsed:6.1f}s  "
                f"stems={len(result['stems'])}  faltantes={missing or 'ninguno'}"
            )
            print(f"RSS post-llamada: {after:8.1f} MB  (delta {after - baseline:+.1f})")

    growth = retained[-1] - retained[0]
    print(f"\n{'=' * 60}")
    print(f"crecimiento entre pasadas: {growth:+.1f} MB")
    if growth < 150:
        print("OK - la memoria NO se acumula entre jobs (el contenedor sobrevive)")
        return
    print("FALLO - la memoria se acumula; el worker se va a morir")
    sys.exit(1)


if __name__ == "__main__":
    main()