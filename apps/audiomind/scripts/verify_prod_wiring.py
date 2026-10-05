"""Read-only verification of the production wiring: Supabase sessions schema, R2 bucket.

Prints evidence only. Mutates nothing. Never prints a secret value.
Run with: apps\\audiomind\\.venv\\Scripts\\python.exe scripts\\verify_prod_wiring.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def pick(env: dict[str, str], *names: str) -> str:
    for name in names:
        value = env.get(name, "").strip()
        if value:
            return value
    return ""


def check_supabase(env: dict[str, str]) -> None:
    print("=" * 70)
    print("SUPABASE")
    print("=" * 70)

    url = pick(env, "AUDIOMIND_SUPABASE_URL", "SUPABASE_URL")
    key = pick(
        env,
        "AUDIOMIND_SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "SUPABASE_SERVICE_KEY",
    )
    if not url or not key:
        print("  FAIL: falta SUPABASE_URL o la clave de service_role en .env")
        return

    print(f"  url    : {url}")
    print(f"  key    : service_role ({len(key)} chars, valor oculto)")

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    rest = f"{url}/rest/v1"

    with httpx.Client(timeout=20.0) as client:
        # 1. What columns does the table actually have?
        # NOTE: no trailing slash on the table path. PostgREST returns
        # PGRST125 "Invalid path specified in request URL" for `/sessions/`,
        # which looks exactly like a missing table and is not one.
        print("\n  [1] columnas reales de public.sessions")
        response = client.get(f"{rest}/sessions", headers={**headers, "Prefer": "count=exact"}, params={"select": "*", "limit": "1"})
        print(f"      HTTP {response.status_code}")
        if response.status_code == 200:
            rows = response.json()
            if rows:
                print(f"      columnas con datos: {sorted(rows[0].keys())}")
            else:
                print("      (tabla vacia: no hay filas para inferir columnas)")
            count = response.headers.get("content-range", "")
            print(f"      content-range: {count!r}  (vacio = 0 filas)")
        else:
            print(f"      {response.text[:200]}")

        # 2. What the backend actually asks for.
        print("\n  [2] lo que pide el backend: select('session_id')")
        response = client.get(f"{rest}/sessions", headers=headers, params={"select": "session_id", "limit": "1"})
        print(f"      HTTP {response.status_code}")
        if response.status_code == 200:
            print("      OK: la columna session_id existe")
        else:
            print(f"      FAIL: {response.text[:300]}")
            print("      -> el probe de SupabaseSessionBackend va a fallar y el")
            print("         sistema cae al FileSessionBackend sin log de error.")

        # 3. The other column the read path needs.
        print("\n  [3] lo que pide el backend: select('session_id, payload')")
        response = client.get(f"{rest}/sessions", headers=headers, params={"select": "session_id,payload", "limit": "1"})
        print(f"      HTTP {response.status_code}")
        if response.status_code != 200:
            print(f"      FAIL: {response.text[:300]}")

        # 4. dsp_jobs sanity, for contrast.
        print("\n  [4] contraste: public.dsp_jobs")
        response = client.get(f"{rest}/dsp_jobs", headers=headers, params={"select": "job_id", "limit": "1"})
        print(f"      select('job_id') -> HTTP {response.status_code} ({'OK' if response.status_code == 200 else 'FAIL'})")


def check_r2(env: dict[str, str]) -> None:
    print()
    print("=" * 70)
    print("CLOUDFLARE R2")
    print("=" * 70)

    endpoint = pick(env, "AUDIOMIND_R2_ENDPOINT", "R2_ENDPOINT")
    access = pick(env, "AUDIOMIND_R2_ACCESS_KEY_ID", "R2_ACCESS_KEY_ID")
    secret = pick(env, "AUDIOMIND_R2_SECRET_ACCESS_KEY", "R2_SECRET_ACCESS_KEY")
    bucket = pick(env, "AUDIOMIND_R2_BUCKET", "AUDIOMIND_R2_BUCKET_NAME", "R2_BUCKET_NAME", "R2_BUCKET")

    print(f"  endpoint : {endpoint or '(vacio)'}")
    print(f"  bucket   : {bucket or '(vacio)'}")
    print(f"  access   : {access[:6]}... ({len(access)} chars)" if access else "  access   : (vacio)")

    if not all([endpoint, access, secret, bucket]):
        print("  FAIL: faltan credenciales R2 en .env")
        return

    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        print("  SKIP: boto3 no instalado en este interprete")
        return

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access,
        aws_secret_access_key=secret,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )

    try:
        response = client.list_objects_v2(Bucket=bucket, MaxKeys=5)
        contents = response.get("Contents", [])
        count = response.get("KeyCount", 0)
        print(f"  LIST     -> OK. {count} objeto(s) (max 5 mostrados)")
        for item in contents:
            size_mb = item["Size"] / 1_048_576
            print(f"             {item['Key']}  ({size_mb:.2f} MB)")
        if not contents:
            print("             (bucket vacio o sin objetos en el prefijo raiz)")
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        print(f"  LIST     -> FAIL: {type(exc).__name__}: {exc}")
        print("             -> revisar R2_ENDPOINT / ACCESS_KEY / SECRET / BUCKET")

    # Count the real footprint across prefixes, to see what the app actually wrote.
    print("\n  [2] prefijos que escribe el backend")
    for prefix in ("masters/", "mixes/", "sessions/"):
        try:
            response = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
            total = response.get("KeyCount", 0)
            more = "..." if total else ""
            print(f"      {prefix:<12} {total} objeto(s) {more}")
        except Exception as exc:  # noqa: BLE001
            print(f"      {prefix:<12} FAIL: {type(exc).__name__}")


def main() -> int:
    if not ENV_FILE.exists():
        print(f"No existe {ENV_FILE}")
        return 1
    env = load_env()
    check_supabase(env)
    check_r2(env)
    print()
    print("Esto es solo lectura. No modifico nada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())