"""Diff what run_master_job upserts into public.masters against the real table.

The full-flow probe failed with ``column masters.status does not exist``
(PostgreSQL 42703), the same class of drift we already fixed for dsp_jobs and
sessions. The upload to Storage happens BEFORE the DB write, so the file lands
in the bucket but the row — and everything sequenced after it
(update_track_status, log_track_event) — never happens.

This prints the table's real columns and marks which upsert fields have no
home, so the migration is written from evidence instead of guesswork.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from supabase import create_client  # noqa: E402

from audiomind.config import settings  # noqa: E402

# Mirrors the ``master_record`` dict built at dsp_worker.py:444-459.
UPSERT_FIELDS = {
    "id": "uuid primary key (master id)",
    "track_id": "uuid track this master belongs to",
    "user_id": "uuid owner",
    "name": "human label",
    "storage_path": "path inside audio-masters bucket",
    "format": "wav | mp3",
    "file_size_bytes": "integer",
    "integrated_lufs": "numeric loudness",
    "true_peak_db": "numeric peak",
    "parameters_applied": "jsonb of the MasteringParameters",
    "preset_name": "text preset id",
    "status": "text lifecycle state",
}


def main() -> None:
    client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    print("columnas reales de public.masters\n" + "=" * 62)
    rows = (
        client.table("masters")
        .select("*")
        .limit(1)
        .execute()
    )
    # PostgREST hides the schema; probe column-by-column instead.
    present: list[str] = []
    missing: list[tuple[str, str]] = []
    for field in UPSERT_FIELDS:
        try:
            client.table("masters").select(field).limit(1).execute()
            present.append(field)
        except Exception:  # noqa: BLE001
            missing.append((field, UPSERT_FIELDS[field]))

    for field in present:
        print(f"  OK       {field}")
    for field, note in missing:
        print(f"  FALTA    {field:<20} ({note})")

    print(f"\npresentes: {len(present)}   faltantes: {len(missing)}")
    if missing:
        print("\ncolumnas a agregar:")
        for field, _ in missing:
            print(f"  - {field}")

    # What rows exist today?
    count = len(client.table("masters").select("id").limit(1000).execute().data or [])
    print(f"\nfilas actuales en public.masters: {count}")
    if rows.data:
        print(f"campos devueltos por select('*'): {sorted(rows.data[0].keys())}")


if __name__ == "__main__":
    main()