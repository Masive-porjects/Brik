#!/usr/bin/env python3
"""
Script de validación de credenciales R2 (Cloudflare).

Uso:
    1. Exporta las NUEVAS credenciales como variables de entorno:
       export AUDIOMIND_R2_ENDPOINT="https://<account-id>.r2.cloudflarestorage.com"
       export AUDIOMIND_R2_ACCESS_KEY_ID="<NUEVO_ACCESS_KEY>"
       export AUDIOMIND_R2_SECRET_ACCESS_KEY="<NUEVO_SECRET_KEY>"
       export AUDIOMIND_R2_BUCKET="<nombre-bucket>"

    2. Ejecuta: python scripts/verify_r2_keys.py

Hace:
    - Conexión al endpoint S3-compatible
    - Verifica que el bucket existe y es accesible
    - Sube un objeto de prueba (1 byte: b"x")
    - Lista objetos (confirma que aparece)
    - Borra el objeto de prueba
    - Reporta OK/FAIL con detalles

Exit codes: 0 = éxito, 1 = fallo de credenciales/conexión, 2 = fallo de permisos/bucket
"""

import os
import sys
import tempfile
from pathlib import Path

try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError, EndpointConnectionError
except ImportError:
    print("❌ boto3 no instalado. Ejecuta: pip install boto3")
    sys.exit(1)


def get_env(key: str, default: str = "") -> str:
    """Lee variable de entorno o falla con mensaje claro."""
    val = os.environ.get(key, default)
    if not val:
        print(f"❌ Variable de entorno requerida no seteada: {key}")
        print(f"   Ejemplo: export {key}=<valor>")
        sys.exit(1)
    return val


def main() -> int:
    # ── Leer credenciales desde entorno ──────────────────────────────
    endpoint = get_env("AUDIOMIND_R2_ENDPOINT")
    access_key = get_env("AUDIOMIND_R2_ACCESS_KEY_ID")
    secret_key = get_env("AUDIOMIND_R2_SECRET_ACCESS_KEY")
    bucket = get_env("AUDIOMIND_R2_BUCKET")

    # Normalizar endpoint (debe terminar en / para boto3)
    if not endpoint.endswith("/"):
        endpoint += "/"

    print(f"🔧 Validando credenciales R2...")
    print(f"   Endpoint: {endpoint}")
    print(f"   Bucket:   {bucket}")
    print(f"   Access Key: {access_key[:8]}...{access_key[-4:] if len(access_key) > 12 else '***'}")

    # ── Crear cliente S3 compatible ──────────────────────────────────
    try:
        s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",  # R2 ignora region pero boto3 la requiere
        )
    except Exception as e:
        print(f"❌ Error creando cliente S3: {e}")
        return 1

    # ── Test 1: Listar buckets (valida credenciales + endpoint) ──────
    try:
        resp = s3.list_buckets()
        bucket_names = [b["Name"] for b in resp.get("Buckets", [])]
        if bucket not in bucket_names:
            print(f"❌ Bucket '{bucket}' NO encontrado en la cuenta.")
            print(f"   Buckets disponibles: {bucket_names or '(ninguno)'}")
            return 2
        print(f"✅ Conexión R2 OK (endpoint: {endpoint})")
        print(f"✅ Bucket '{bucket}' accesible")
    except EndpointConnectionError:
        print(f"❌ No se puede conectar al endpoint: {endpoint}")
        print("   Verifica que el Account ID y la URL sean correctos.")
        return 1
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied"):
            print(f"❌ Credenciales inválidas o sin permisos: {e.response['Error']['Message']}")
            return 1
        print(f"❌ Error de API listando buckets: {e}")
        return 1
    except NoCredentialsError:
        print("❌ boto3 no encontró credenciales (revisa env vars).")
        return 1

    # ── Test 2: Subir / listar / borrar objeto de 1 byte ─────────────
    test_key = "verify_r2_keys_test_object"
    test_body = b"x"  # 1 byte

    try:
        # Subida
        s3.put_object(Bucket=bucket, Key=test_key, Body=test_body, ContentType="application/octet-stream")
        print(f"✅ Subida test-object (1 byte) OK")

        # Listado (verifica que existe)
        resp = s3.list_objects_v2(Bucket=bucket, Prefix=test_key, MaxKeys=1)
        if "Contents" not in resp or not any(obj["Key"] == test_key for obj in resp["Contents"]):
            print(f"❌ Objeto subido no aparece en listado")
            return 2
        print(f"✅ Listado objetos OK")

        # Borrado
        s3.delete_object(Bucket=bucket, Key=test_key)
        print(f"✅ Borrado test-object OK")

        # Verificar que ya no está
        resp = s3.list_objects_v2(Bucket=bucket, Prefix=test_key, MaxKeys=1)
        if "Contents" in resp and any(obj["Key"] == test_key for obj in resp["Contents"]):
            print(f"⚠️  Objeto aún visible tras borrado (eventual consistency)")
        else:
            print(f"✅ Borrado confirmado (objeto ya no lista)")

    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "AccessDenied":
            print(f"❌ Permisos insuficientes: el token necesita Object Read & Write en este bucket")
            return 2
        print(f"❌ Error operando objeto: {e}")
        return 2

    print(f"\n🎉 Credenciales NUEVAS validadas correctamente")
    return 0


if __name__ == "__main__":
    sys.exit(main())