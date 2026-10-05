"""Dump the full persisted row of a job, to see what it actually produced.

Read-only. Usage: show_job_detail.py <job_id>
"""

from __future__ import annotations

import json
import pathlib
import sys

import httpx


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in pathlib.Path(".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: show_job_detail.py <job_id>")
        return

    job_id = sys.argv[1]
    env = load_env()
    url = env["AUDIOMIND_SUPABASE_URL"]
    key = env["AUDIOMIND_SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}

    response = httpx.get(
        f"{url}/rest/v1/dsp_jobs",
        headers=headers,
        params={"select": "*", "job_id": f"eq.{job_id}"},
        timeout=30.0,
    )
    rows = response.json()
    if not rows:
        print(f"no encontre {job_id} ({response.status_code})")
        return

    row = rows[0]
    print(f"=== {row['job_id']} ===")
    for field in ("kind", "status", "progress", "stage", "session_id", "error"):
        print(f"  {field:<11} = {row.get(field)}")

    print("\n  meta:")
    print(json.dumps(row.get("meta") or {}, indent=4, ensure_ascii=False)[:900])

    result = row.get("result") or {}
    print("\n  result:")
    for field, value in result.items():
        rendered = value if not isinstance(value, (dict, list)) else json.dumps(value, ensure_ascii=False)[:220]
        print(f"    {field:<18} = {str(rendered)[:230]}")


if __name__ == "__main__":
    main()
