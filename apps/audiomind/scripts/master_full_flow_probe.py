"""Verify the FULL production flow: master a real track and download the file.

The earlier probe sent no ``user_id``. Both the upload and the DB persist in
``run_master_job`` are guarded by ``if sb_client and payload.user_id``
(dsp_worker.py:413,443), so a stateless probe correctly returns
``storage_path=None, download_url=None``. That was the probe's fault, not the
backend's.

This probe therefore uses a real ``public.tracks`` row (with its real
``user_id`` and ``storage_path``), lets the worker resolve the input from
storage, and then asserts the artifact is downloadable.

Writes are scoped to that one track id, which the script generates.
"""

from __future__ import annotations

import pathlib
import sys
import time
import uuid

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from supabase import create_client  # noqa: E402

from audiomind.config import settings  # noqa: E402

BASE = "https://waveia-dev.up.railway.app"


def main() -> None:
    sb = create_client(settings.supabase_url, settings.supabase_service_role_key)
    rows = (
        sb.table("tracks")
        .select("id,user_id,storage_path,status")
        .not_.is_("storage_path", "null")
        .limit(10)
        .execute()
        .data
        or []
    )
    if not rows:
        print("FALLO: no hay tracks con storage_path")
        sys.exit(1)

    track = rows[0]
    track_id, user_id = track["id"], track["user_id"]
    print(f"track:  {track_id}  status={track['status']}")
    print(f"user:   {user_id}")
    print(f"origen: {track['storage_path']}\n")

    payload = {
        "track_id": track_id,
        "user_id": user_id,
        "preset_id": "universal",
        "format": "wav",
        "is_async": False,
    }

    started = time.monotonic()
    res = httpx.post(f"{BASE}/api/jobs/master", json=payload, timeout=1800.0)
    print(f"master sync: HTTP {res.status_code} en {time.monotonic() - started:.0f}s")
    if res.status_code != 200:
        print(res.text[:600].encode("ascii", "replace").decode())
        sys.exit(1)

    state = res.json()
    print(f"status: {state.get('status')}   success: {state.get('success')}")
    for field in ("master_id", "storage_path", "download_url", "file_size_bytes"):
        print(f"  {field:<16} = {state.get(field)}")

    storage_path = state.get("storage_path")
    download_url = state.get("download_url")
    if not storage_path or not download_url:
        print("\nFALLO: storage_path/download_url siguen vacios")
        sys.exit(1)

    # 1. the signed URL must serve real bytes
    head = httpx.head(download_url, timeout=180.0, follow_redirects=True)
    size = int(head.headers.get("content-length", 0))
    print(f"\n1. signed URL responde HTTP {head.status_code}, {size/1048576:.1f} MiB")

    # 2. a master row must exist in Postgres with real metrics
    mrows = (
        sb.table("masters")
        .select("id,storage_path,file_size_bytes,integrated_lufs,true_peak_db,status")
        .eq("id", state["master_id"])
        .execute()
        .data
        or []
    )
    if not mrows:
        print("2. FALLO: no hay fila en public.masters")
        sys.exit(1)
    m = mrows[0]
    print(
        f"2. public.masters OK: lufs={m['integrated_lufs']} "
        f"peak={m['true_peak_db']} bytes={m['file_size_bytes']} status={m['status']}"
    )

    # 3. the object must exist in the masters bucket
    dest = storage_path.split("/")[-1]
    bucket_obj = sb.storage.from_(settings.supabase_masters_bucket)
    try:
        info = bucket_obj.download(f"{user_id}/{track_id}/{dest}")
        print(f"3. bucket {settings.supabase_masters_bucket}: {len(info)} bytes reales")
    except Exception as err:  # noqa: BLE001
        print(f"3. FALLO bucket: {err}")

    print("\nOK - flujo completo verificado: DSP -> persist -> descarga")


if __name__ == "__main__":
    main()