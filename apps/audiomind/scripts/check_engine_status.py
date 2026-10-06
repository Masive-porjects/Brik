"""Answer 'do both engines work right now?' from persisted evidence.

Reads every dsp_jobs row in Supabase and reports, per engine kind, whether any
job ever reached a terminal success and what artifact it produced. This is the
only claim that survives a container restart: a job row in the DB is proof the
DSP finished, independent of the 502 the client may have seen.
"""

from __future__ import annotations

import pathlib
from collections import Counter

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

    response = httpx.get(
        f"{url}/rest/v1/dsp_jobs",
        headers=headers,
        params={"select": "job_id,kind,status,result", "order": "created_at.desc", "limit": "50"},
        timeout=40.0,
    )
    rows = response.json()

    tally: dict[str, Counter] = {}
    for row in rows:
        result = row.get("result") or {}
        artifact = result.get("r2_key") or result.get("storage_path") or ""
        tally.setdefault(row["kind"], Counter())
        if row["status"] == "completed":
            tally[row["kind"]]["completed"] += 1
            if artifact:
                tally[row["kind"]]["con_artefacto"] += 1
        else:
            tally[row["kind"]][row["status"]] += 1

    print(f"jobs totales registrados: {len(rows)}\n")
    for kind, counts in tally.items():
        print(f"  MOTOR '{kind}':")
        for status, count in counts.most_common():
            print(f"      {status:<22} {count}")
        print()

    print("ULTIMOS 12:")
    for row in rows[:12]:
        result = row.get("result") or {}
        note = (
            result.get("r2_key")
            or result.get("storage_path")
            or result.get("error")
            or ""
        )
        print(f"  {row['job_id']:<24} {row['kind']:<7} {row['status']:<10} {str(note)[:58]}")


if __name__ == "__main__":
    main()
