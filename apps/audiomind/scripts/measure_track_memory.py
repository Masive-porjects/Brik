"""Measure how much RAM each source track needs once decoded to float32.

Master survived a 99s / 25 MiB WAV earlier (29s) but was Killed at 18s on a
real user track. This prints duration and decoded float32 size per track so we
can see whether the 8x oversampled limiter (see AGENTS.md) pushes long tracks
past the container limit.
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile

import soundfile as sf

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from supabase import create_client  # noqa: E402

from audiomind.config import settings  # noqa: E402


def main() -> None:
    client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    rows = (
        client.table("tracks")
        .select("id,user_id,storage_path,status")
        .not_.is_("storage_path", "null")
        .limit(8)
        .execute()
        .data
        or []
    )
    bucket = client.storage.from_(settings.supabase_originals_bucket)
    print(f"bucket: {settings.supabase_originals_bucket}\n")

    for row in rows:
        try:
            raw = bucket.download(row["storage_path"])
        except Exception as err:  # noqa: BLE001
            print(f"err {row['id'][:8]}: {str(err)[:60]}")
            continue

        path = os.path.join(tempfile.gettempdir(), "measure_in.wav")
        with open(path, "wb") as handle:
            handle.write(raw)

        try:
            info = sf.info(path)
        except Exception as err:  # noqa: BLE001
            print(f"err decodificando {row['id'][:8]}: {str(err)[:60]}")
            continue

        samples = info.frames * info.channels
        f32_mb = samples * 4 / 1048576
        f64_mb = samples * 8 / 1048576
        print(
            f"{info.duration:7.1f}s {info.samplerate}Hz {info.channels}ch "
            f"{info.subtype:9} src={len(raw) / 1048576:6.1f}MiB  "
            f"f32={f32_mb:7.1f}MB  f64={f64_mb:7.1f}MB  "
            f"f32x8oversample={f32_mb * 8 / 1024:7.2f}GB  "
            f"[{row['status']}]"
        )


if __name__ == "__main__":
    main()