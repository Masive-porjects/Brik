"""Exercise /api/session/{id}/mix against the deployed dev backend.

The mix endpoint runs HTDemucs stem separation, which is where the container
was being OOM-killed. Reports HTTP status, wall time and the job payload so a
pass is distinguishable from a 502.

Read-only against production: it creates one throwaway session.
"""

from __future__ import annotations

import pathlib
import sys
import time

import httpx

BASE = "https://waveia-dev.up.railway.app"
SAMPLE = pathlib.Path("samples/mix_probe.wav")


def build_probe_tone() -> pathlib.Path:
    """30 s stereo WAV: long enough for Demucs to chunk it like real audio."""
    import numpy as np
    import soundfile as sf

    SAMPLE.parent.mkdir(parents=True, exist_ok=True)
    rate = 44100
    t = np.linspace(0, 30, rate * 30, endpoint=False, dtype=np.float32)
    # Bass + mid + hat-ish content so the separator has something to split.
    mono = (
        0.30 * np.sin(2 * np.pi * 55 * t)
        + 0.18 * np.sin(2 * np.pi * 220 * t)
        + 0.08 * np.sin(2 * np.pi * 3000 * t)
    ).astype(np.float32)
    stereo = np.stack([mono, mono * 0.9], axis=1)
    sf.write(str(SAMPLE), stereo, rate, subtype="PCM_16")
    return SAMPLE


def main() -> None:
    sample = SAMPLE if SAMPLE.exists() else build_probe_tone()
    size_mb = sample.stat().st_size / 1048576
    print(f"probe: {sample} ({size_mb:.2f} MiB)")

    # POST /api/upload creates its own session (api/upload.py) and returns it;
    # there is no session_id parameter to pass in. Using a pre-made session here
    # leaves the mix endpoint looking for an upload that belongs to it.
    with sample.open("rb") as handle:
        uploaded = httpx.post(
            f"{BASE}/api/upload",
            files={"file": ("mix_probe.wav", handle, "audio/wav")},
            timeout=180.0,
        )
    print(f"upload: HTTP {uploaded.status_code}")
    uploaded.raise_for_status()
    session_id = uploaded.json()["session_id"]
    print(f"session: {session_id}")

    print("mezclando (HTDemucs, esto es lo que antes mataba el contenedor)...")
    started = time.monotonic()
    try:
        response = httpx.post(
            f"{BASE}/api/session/{session_id}/mix", json={}, timeout=900.0
        )
    except httpx.TimeoutException:
        elapsed = time.monotonic() - started
        print(f"TIMEOUT tras {elapsed:.0f}s - el contenedor murio o no termino")
        sys.exit(1)

    elapsed = time.monotonic() - started
    print(f"\nmix: HTTP {response.status_code} en {elapsed:.0f}s")
    print(response.text[:1200])

    if response.status_code != 200:
        sys.exit(1)
    print("\nOK - el mix completo sin OOM")


if __name__ == "__main__":
    main()
