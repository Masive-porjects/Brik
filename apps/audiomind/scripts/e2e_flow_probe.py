"""End-to-end flow probe against a DEPLOYED AudioMind service.

Runs the real pipeline over HTTP against production, so no local DSP is
involved: session -> upload -> read-back -> master job -> R2 output -> mix.

Usage:
  <repo>\\.venv\\Scripts\\python.exe apps\\audiomind\\scripts\\e2e_flow_probe.py <base-url> [...]
"""

from __future__ import annotations

import io
import json
import math
import struct
import sys
import time
import wave

import httpx

SECONDS = 6
RATE = 44_100
CHANNELS = 2


def make_wav() -> bytes:
    """Build a small stereo WAV: 220 Hz + 330 Hz with a slow tremolo."""
    frames = bytearray()
    total = RATE * SECONDS
    for i in range(total):
        tremolo = 0.65 + 0.35 * math.sin(2 * math.pi * 1.5 * i / RATE)
        left = int(12000 * tremolo * math.sin(2 * math.pi * 220 * i / RATE))
        right = int(9000 * tremolo * math.sin(2 * math.pi * 330 * i / RATE))
        frames += struct.pack("<hh", left, right)

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(CHANNELS)
        handle.setsampwidth(2)
        handle.setframerate(RATE)
        handle.writeframes(bytes(frames))
    return buffer.getvalue()


def short(payload: object, limit: int = 700) -> str:
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2, default=str)
    return text if len(text) <= limit else text[:limit] + " ...(truncado)"


def probe(base: str) -> bool:
    ok = True
    print()
    print("#" * 70)
    print(f"# OBJETIVO: {base}")
    print("#" * 70)

    with httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0), follow_redirects=True) as client:

        def step(label: str, condition: bool, detail: str = "") -> None:
            nonlocal ok
            if not condition:
                ok = False
            mark = "OK  " if condition else "FAIL"
            print(f"  [{mark}] {label}")
            if detail:
                for line in detail.splitlines():
                    print(f"          {line}")

        # 0. health
        response = client.get(f"{base}/health")
        step("health", response.status_code == 200, short(response.json()))

        # 1. new session (only proves session creation works)
        response = client.post(f"{base}/api/session/new")
        step("POST /api/session/new", response.status_code == 200, short(response.text))
        if response.status_code != 200:
            return False

        # 2. upload
        audio = make_wav()
        print(f"          wav local = {len(audio)/1024:.0f} KB, {SECONDS}s")
        response = client.post(
            f"{base}/api/upload",
            files={"file": ("probe.wav", audio, "audio/wav")},
        )
        step("POST /api/upload", response.status_code == 200, short(response.text))
        upload: dict = {}
        if response.status_code == 200:
            try:
                upload = response.json()
            except Exception:  # noqa: BLE001
                pass

        # NOTE: /api/upload creates its OWN session and returns that id. All
        # session-scoped calls below must use the id from the upload response,
        # not the one from /api/session/new, which stays empty.
        session_id = upload.get("session_id")
        if not session_id:
            step("session_id devuelto por upload", False, short(upload))
            return False
        print(f"          session_id (del upload) = {session_id}")

        # 3. session readable
        response = client.get(f"{base}/api/session/{session_id}")
        step("GET /api/session/{id}", response.status_code == 200, short(response.text))
        session: dict = {}
        if response.status_code == 200:
            try:
                session = response.json()
            except Exception:  # noqa: BLE001
                pass

        # 4. raw audio read-back from R2 (or wherever storage landed)
        response = client.get(f"{base}/api/session/{session_id}/raw")
        detail = f"HTTP {response.status_code}, {len(response.content)} bytes"
        if response.status_code == 200 and response.content[:4] != b"RIFF":
            detail += "\nAVISO: la respuesta no empieza con RIFF, no parece un WAV"
            ok = False
        step("GET /api/session/{id}/raw (audio de vuelta desde R2)", response.status_code == 200, detail)

        # 5. master job (stateless + async -> should return a job id fast)
        job_payload = {
            "track_id": str(upload.get("track_id") or session.get("track_id") or session_id),
            "preset_id": "warm",
            "format": "wav",
            "output_bit_depth": 24,
            "master_name": "probe_master",
            "is_async": True,
        }
        started = time.time()
        response = client.post(f"{base}/api/jobs/master", json=job_payload)
        elapsed = time.time() - started
        step(
            f"POST /api/jobs/master (async,Submission en {elapsed:.1f}s)",
            response.status_code in (200, 201, 202),
            short(response.text),
        )
        job_id = None
        if response.status_code in (200, 201, 202):
            try:
                job_id = response.json().get("job_id")
            except Exception:  # noqa: BLE001
                pass

        # 6. poll the job
        if job_id:
            print(f"          job_id = {job_id}")
            final: dict = {}
            for attempt in range(40):
                response = client.get(f"{base}/api/jobs/master/{job_id}")
                if response.status_code == 200:
                    try:
                        final = response.json()
                    except Exception:  # noqa: BLE001
                        pass
                status = str(final.get("status") or final.get("state") or "?")
                if status.lower() in {"completed", "succeeded", "done", "error", "failed"}:
                    break
                time.sleep(5)
            step(
                "GET /api/jobs/master/{job_id} llego a un estado terminal",
                str(final.get("status", "")).lower() in {"completed", "succeeded", "done"},
                short(final),
            )
            download_url = final.get("download_url") or ""
            r2_key = final.get("r2_key") or ""
            print(f"          r2_key      = {r2_key or '(vacio)'}")
            print(f"          download_url= {download_url[:80] or '(vacio)'}")
            if download_url:
                probe_response = client.get(download_url)
                step(
                    "GET download_url (objeto R2 real)",
                    probe_response.status_code == 200 and len(probe_response.content) > 1000,
                    f"HTTP {probe_response.status_code}, {len(probe_response.content)/1024:.0f} KB",
                )
        else:
            step("job_id asignado", False, "no se obtuvo job_id; no se puede seguir el master")

        # 7. mix
        started = time.time()
        response = client.post(f"{base}/api/session/{session_id}/mix", json={})
        elapsed = time.time() - started
        step(
            f"POST /api/session/{{id}}/mix ({elapsed:.1f}s)",
            response.status_code in (200, 201, 202),
            short(response.text),
        )

        # 8. jobs health
        response = client.get(f"{base}/api/jobs/health")
        step("GET /api/jobs/health", response.status_code == 200, short(response.text))

    return ok


def main() -> int:
    targets = sys.argv[1:] or ["https://waveia-dev.up.railway.app", "https://waveia-production.up.railway.app"]
    results: dict[str, bool] = {}
    for base in targets:
        try:
            results[base] = probe(base)
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] la prueba contra {base} lanzo {type(exc).__name__}: {exc}")
            results[base] = False

    print()
    print("=" * 70)
    print("RESUMEN")
    print("=" * 70)
    for base, ok in results.items():
        print(f"  {'FLUJO COMPLETO OK' if ok else 'FLUJO ROTO':<20} {base}")
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())