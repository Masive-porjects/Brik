"""Apply the public.masters status migration.

DDL needs a SQL execution channel; PostgREST alone cannot run ALTER TABLE. This
tries the common `exec_sql` RPC first, then `execute_sql`, and reports which one
the project exposes so the migration is not silently skipped.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from supabase import create_client  # noqa: E402

from audiomind.config import settings  # noqa: E402

SQL = """
ALTER TABLE public.masters ADD COLUMN IF NOT EXISTS status text;
UPDATE public.masters SET status = 'completed' WHERE status IS NULL;
"""


def main() -> None:
    client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    # Already applied?
    try:
        client.table("masters").select("status").limit(1).execute()
        print("status YA existe - no hace falta migrar")
        return
    except Exception:  # noqa: BLE001
        print("status falta, aplicando...")

    for rpc in ("exec_sql", "execute_sql", "run_sql", "sql"):
        try:
            result = client.rpc(rpc, {"query": SQL, "sql": SQL}).execute()
            print(f"aplicada via RPC '{rpc}' -> {result}")
            return
        except Exception as err:  # noqa: BLE001
            print(f"  rpc '{rpc}': {str(err)[:110]}")

    print("\nNo hay canal DDL expuesto por el proyecto.")
    print("Ejecuta esto en Supabase -> SQL Editor:\n")
    print(SQL.strip())


if __name__ == "__main__":
    main()