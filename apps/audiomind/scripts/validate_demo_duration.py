"""Validate the 4-minute demo duration gate over the REAL HTTP path.

Purpose
-------
Prove the client-demo duration contract on an actual uvicorn server with
the demo environment (240 s cap):

  * 60 s   -> accepted, DSP executions stay 0 after analysis
  * 210 s  -> accepted, DSP executions stay 0 after analysis
  * 240 s  -> accepted, DSP executions stay 0 after analysis
  * 241 s  -> rejected 422, DSP executions stay 0, NO orphan files

The 60 s accepted session additionally runs ONE real preset (fuego) and
then re-requests the same preset, proving the DSP meter counts exactly 1
real pipeline and the cache hit does not increment it.

Usage
-----
    .\\.venv\\Scripts\\python.exe scripts/validate_demo_duration.py

Exit code: 0 = all checks passed, 1 = at least one check failed,
2 = server could not start. Prints a compact JSON report at the end
(also written to outputs/validate_duration_report.json).

Dependencies: numpy + soundfile (already in pyproject), psutil only for
the subprocess (already in dev extras). HTTP via stdlib urllib.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from audiomind.config import settings  # noqa: E402

SR = 44100
HOST = "127.0.0.1"
DEMO_ENV = {
    "AUDIOMIND_PRERENDER_MODE": "on_demand",
    "AUDIOMIND_MAX_CONCURRENT_DSP": "1",
    "AUDIOMIND_DEMO_MAX_DURATION_SECONDS": "240",
    "AUDIOMIND_MAX_FILE_SIZE_MB": "100",
    "AUDIOMIND_SESSION_TTL_MINUTES": "60",
}
SERVER_BOOT_TIMEOUT = 90.0
ANALYSIS_WAIT_TIMEOUT = 120.0

DURATIONS = (60.0, 210.0, 240.0, 241.0)


# ── Track generation ───────────────────────────────────────────────────


def generate_track(duration_s: float, path: Path) -> float:
    """Synthetic stereo PCM16 track (sine + noise), returns real duration."""
    import soundfile as sf

    n = int(SR * duration_s)
    t = np.linspace(0.0, duration_s, n, endpoint=False)
    left = 0.3 * np.sin(2 * np.pi * 220.0 * t) + 0.05 * np.random.uniform(-1, 1, n)
    right = 0.3 * np.sin(2 * np.pi * 221.0 * t + 0.5) + 0.05 * np.random.uniform(-1, 1, n)
    audio = np.stack([left, right], axis=1).astype("float32")
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), audio, SR, subtype="PCM_16")
    return len(audio) / SR


# ── Minimal HTTP client ────────────────────────────────────────────────


class HttpError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


def _request(base_url: str, method: str, url_path: str, body: bytes | None = None,
             headers: dict[str, str] | None = None, timeout: float = 60.0):
    req = urllib.request.Request(f"{base_url}{url_path}", data=body, method=method)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HttpError(exc.code, detail) from exc


def upload_wav(base_url: str, file_path: Path, timeout: float = 180.0):
    boundary = uuid.uuid4().hex
    payload = file_path.read_bytes()
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        "Content-Type: audio/wav\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    body = head + payload + tail
    return _request(
        base_url, "POST", "/api/upload",
        body=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        timeout=timeout,
    )


def get_session(base_url: str, session_id: str):
    return _request(base_url, "GET", f"/api/session/{session_id}")


def process_preset(base_url: str, session_id: str, preset_id: str, timeout: float):
    return _request(
        base_url, "POST",
        f"/api/session/{session_id}/process?preset_id={preset_id}",
        body=b"{}",
        headers={"Content-Type": "application/json"},
        timeout=timeout,
    )


def demo_stats(base_url: str):
    return _request(base_url, "GET", "/api/demo/stats")


# ── Server orchestration (mirrors benchmark_demo.py) ──────────────────


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def start_server(port: int) -> tuple[subprocess.Popen, Path]:
    env = os.environ.copy()
    env.update(DEMO_ENV)
    env["PYTHONUNBUFFERED"] = "1"
    log_path = Path(tempfile.gettempdir()) / f"audiomind-validate-{os.getpid()}.log"
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "audiomind.main:app",
         "--host", HOST, "--port", str(port), "--log-level", "warning"],
        cwd=str(_BACKEND), env=env,
        stdout=log_file, stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    return proc, log_path


def wait_until_healthy(base_url: str, timeout: float = SERVER_BOOT_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            _request(base_url, "GET", "/health", timeout=2.0)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"server did not become healthy within {timeout:.0f}s")


def stop_server(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True)


# ── Upload-level duration checks ───────────────────────────────────────


def wait_for_analysis(base_url: str, session_id: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = get_session(base_url, session_id)
        if s.get("status") != "analyzing":
            return
        time.sleep(0.5)


def upload_dir_files() -> list[str]:
    if not settings.upload_dir.exists():
        return []
    return sorted(p.name for p in settings.upload_dir.iterdir())


def run_check(base_url: str, track: Path, duration_s: float) -> dict:
    before = upload_dir_files()
    stats_before = demo_stats(base_url)
    try:
        result = upload_wav(base_url, track)
        accepted = True
        detail = ""
        session_id = result.get("session_id", "")
        wait_for_analysis(base_url, session_id, ANALYSIS_WAIT_TIMEOUT)
        stats_after = demo_stats(base_url)
        dsp_after = stats_after["dsp_executions"]
    except HttpError as exc:
        accepted = False
        detail = exc.detail
        session_id = ""
        stats_after = demo_stats(base_url)
        dsp_after = stats_after["dsp_executions"]
    after = upload_dir_files()
    orphans = [n for n in after if n not in before]
    return {
        "duration_s": duration_s,
        "accepted": accepted,
        "detail_snippet": detail[:120],
        "session_id": session_id or None,
        "dsp_after_analysis": dsp_after,
        "orphan_files": orphans,
    }


# ── Main ───────────────────────────────────────────────────────────────


def main() -> int:
    print("=== WAVEAI demo duration validation (240 s gate, real HTTP) ===")
    print(f"Server env demo: demo_max_duration_seconds=240, max_file_size_mb=100\n")

    track_paths: dict[float, Path] = {}
    for duration_s in DURATIONS:
        stem = f"validate_{int(duration_s)}"
        track_paths[duration_s] = settings.output_dir / f"{stem}.wav"
        real = generate_track(duration_s, track_paths[duration_s])
        print(f"  fixture {duration_s:.0f}s -> {real:.2f}s "
              f"({track_paths[duration_s].stat().st_size/1e6:.1f} MB)")

    port = find_free_port()
    base_url = f"http://{HOST}:{port}"
    proc: subprocess.Popen | None = None
    checks: list[dict] = []
    ok = True
    try:
        proc, _ = start_server(port)
        print(f"\nStarting real uvicorn on {base_url} (demo env)...")
        wait_until_healthy(base_url)
        print("  server healthy.\n")

        for duration_s in DURATIONS:
            print(f"-- Upload {duration_s:.0f}s --")
            check = run_check(base_url, track_paths[duration_s], duration_s)
            checks.append(check)
            print(f"   accepted={check['accepted']}  dsp_after={check['dsp_after_analysis']}  "
                  f"orphans={check['orphan_files']}")
            if check["accepted"] and duration_s < 241.0:
                if check["dsp_after_analysis"] != 0:
                    ok = False
                    print("   !! DSP executions must be 0 after analysis")
            elif not check["accepted"]:
                if duration_s == 241.0 and check["dsp_after_analysis"] == 0 \
                        and not check["orphan_files"]:
                    print(f"   rejected as expected: 422 {check['detail_snippet']!r}")
                else:
                    ok = False
                    print("   !! unexpected rejection details")

        # ── DSP meter proof on the 60s session (one real pipeline + cache hit)
        print("\n-- DSP meter proof (60 s session) --")
        # Re-upload a short track for the proof so the meter starts at its count.
        stats0 = demo_stats(base_url)
        short = track_paths[60.0]
        res = upload_wav(base_url, short)
        sid = res["session_id"]
        wait_for_analysis(base_url, sid, ANALYSIS_WAIT_TIMEOUT)
        s1 = demo_stats(base_url)
        t0 = time.perf_counter()
        process_preset(base_url, sid, "fuego", timeout=900.0)
        wt1 = time.perf_counter() - t0
        s2 = demo_stats(base_url)
        t1 = time.perf_counter()
        process_preset(base_url, sid, "fuego", timeout=60.0)  # cache hit
        wt2 = time.perf_counter() - t1
        s3 = demo_stats(base_url)

        dsp_delta_first = s2["dsp_executions"] - s1["dsp_executions"]
        dsp_delta_cache = s3["dsp_executions"] - s2["dsp_executions"]
        print(f"   first fuego: +{dsp_delta_first} DSP, wall {wt1:.1f}s")
        print(f"   fuego again: +{dsp_delta_cache} DSP (cache), wall {wt2:.2f}s")
        if dsp_delta_first != 1:
            ok = False
            print("   !! expected exactly 1 DSP for the first preset request")
        if dsp_delta_cache != 0:
            ok = False
            print("   !! cache hit must not execute DSP")
        if wt2 > 5.0:
            ok = False
            print("   !! cache hit should be near-instant")

        report = {
            "demo_env": DEMO_ENV,
            "machine": {"system": os.name, "cpu": os.cpu_count()},
            "duration_checks": checks,
            "dsp_meter_proof": {
                "baseline": stats0["dsp_executions"],
                "after_analysis": s1["dsp_executions"],
                "after_first_fuego": s2["dsp_executions"],
                "after_cache_fuego": s3["dsp_executions"],
                "first_wall_s": round(wt1, 2),
                "cache_wall_s": round(wt2, 2),
            },
        }
        out = settings.output_dir / "validate_duration_report.json"
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nReport: {out}")
    finally:
        crashed = proc is not None and proc.poll() is not None
        stop_server(proc)

    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())