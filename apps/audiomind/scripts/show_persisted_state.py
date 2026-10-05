"""Show what is actually persisted in Supabase right now. Read-only."""

from __future__ import annotations

import pathlib

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
    env = load_env()
    url = env["AUDIOMIND_SUPABASE_URL"]
    key = env["AUDIOMIND_SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}

    params = {
        "select": "job_id,kind,status,lease_expires_at",
        "order": "created_at.desc",
        "limit": "5",
    }
    response = httpx.get(f"{url}/rest/v1/dsp_jobs", headers=headers, params=params, timeout=30.0)
    rows = response.json()
    if response.status_code != 200:
        print(f"dsp_jobs  -> ERROR {response.status_code}: {response.text[:200]}")
        rows = []
    else:
        print(f"dsp_jobs  -> {len(rows)} fila(s)")
    for row in rows:
        print(f"   {row['job_id']:<22} {row['kind']:<7} {row['status']:<11} lease={row.get('lease_expires_at')}")

    response = httpx.get(
        f"{url}/rest/v1/sessions",
        headers=headers,
        params={"select": "session_id,status", "limit": "5"},
        timeout=30.0,
    )
    rows = response.json()
    print(f"sessions  -> {len(rows)} fila(s) [{response.status_code}]")
    for row in rows:
        print(f"   {row['session_id']:<38} {row['status']}")


if __name__ == "__main__":
    main()
