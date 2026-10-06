"""Verify the mastering engine end to end against the deployed dev backend.

The earlier attempts failed with "No input audio source provided" because they
sent only ``track_id``. ``dsp_worker.run_master_job`` resolves its input in
this order (dsp_worker.py:296):

    payload.input_audio_url  or  payload.input_storage_path
      -> else look up public.tracks.storage_path by track_id

``/api/upload`` creates a *session*, not a ``tracks`` row, so a session id is
never enough. The fix is to hand the worker a real HTTP URL, which
``download_storage_file`` accepts verbatim (supabase_client.py:84).

Uses an object that already exists in R2 (a previously completed mix) as input,
so this exercises download -> 13-stage DSP -> upload -> persist with no local
audio and no test fixture in the repo.
"""

from __future__ import annotations

import pathlib
import sys
import time
import uuid

import httpx

BASE = "https://waveia-dev.up.railway.app"

# A real master already in the bucket: 25 MiB WAV, produced by a mix job that
# completed in production. Public read on this bucket is enabled.
R2_PUBLIC = "https://pub-6487bc12fa164ec4ac8ba8fa065acb19.r2.dev"
INPUT_KEY = (
    "mixes/26dadea6-37ad-40c1-bdd3-92861abc1704/"
    "26dadea6-37ad-40c1-bdd3-92861abc1704_mix.wav"
)

TERMINAL = {"completed", "error", "failed", "cancelled"}


def main() -> None:
    source = f"{R2_PUBLIC}/{INPUT_KEY}"

    head = httpx.head(source, timeout=60.0, follow_redirects=True)
    head.raise_for_status()
    size_mb = int(head.headers.get("content-length", 0)) / 1048576
    print(f"input: {size_mb:.1f} MiB WAV (R2, public)")

    payload = {
        # No such row in public.tracks: the worker must use input_audio_url
        # rather than falling back to a DB lookup.
        "track_id": str(uuid.uuid4()),
        "input_audio_url": source,
        "preset_id": "universal",
        "format": "wav",
        # is_async defaults to False, so the endpoint runs the whole 13-stage
        # pipeline inline and returns the complete MasterJobResult. Nothing is
        # written to dsp_jobs on this path, so there is nothing to poll.
        "is_async": False,
    }

    started = time.monotonic()
    submitted = httpx.post(f"{BASE}/api/jobs/master", json=payload, timeout=1800.0)
    elapsed = time.monotonic() - started
    print(f"submit (sync): HTTP {submitted.status_code} en {elapsed:.0f}s")

    if submitted.status_code != 200:
        print(submitted.text[:800])
        sys.exit(1)

    state = submitted.json()
    status = state.get("status")
    print(f"status: {status}\n")
    print("result:")
    for field, value in state.items():
        if field in ("metrics", "validation", "report"):
            print(f"  {field:<16} = {value if value else 'null'}")
        else:
            print(f"  {field:<16} = {str(value)[:76]}")

    if status != "completed":
        print("\nFALLO - el master no completo")
        sys.exit(1)

    # Prove the artifact really exists, not just that the call returned 200.
    download_url = state.get("download_url")
    storage_path = state.get("storage_path")
    print()
    if download_url:
        head = httpx.head(download_url, timeout=180.0, follow_redirects=True)
        size_mb = int(head.headers.get("content-length", 0)) / 1048576
        print(f"OK - master descargable: {size_mb:.1f} MiB")
        print(f"     storage_path: {storage_path}")
    else:
        print(f"sin download_url; storage_path: {storage_path}")
        sys.exit(1)

    print("\nOK - motor de master verificado end to end")


if __name__ == "__main__":
    main()
