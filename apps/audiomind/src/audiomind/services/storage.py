"""Cloudflare R2 object storage (S3-compatible).

R2 is the durable home of generated audio. The container filesystem is
ephemeral on Railway: a WAV written to ``outputs/`` disappears on redeploy,
and a mix that "finished" then 404s for the user. R2 keeps the bytes.

Design rules
------------
* **No credential defaults.** Every value comes from the environment
  (``config.Settings``). A credential in source is a leaked credential, and a
  silent default means an unconfigured deployment still appears to work.
* **Fail loud, not silent.** If the operator asked for R2 and the upload
  fails, that is an error -- NOT a quiet fall back to a local temp file that
  the next restart will delete. A "successful" mix whose file is already
  doomed is the worst possible outcome.
* **Lazy client.** The boto3 client is built on first use so importing this
  module never requires credentials (tests import it freely).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from audiomind.config import settings

logger = logging.getLogger(__name__)

_client_lock = threading.Lock()
_client: Any = None


class StorageError(RuntimeError):
    """Raised when an object store operation cannot be completed."""


def get_s3_client() -> Any:
    """Build (once) and return the boto3 S3 client pointed at R2.

    Raises ``StorageError`` when R2 is not fully configured: callers must
    decide explicitly whether to degrade, they must not do it by accident.
    """
    global _client
    if _client is not None:
        return _client

    if not settings.r2_is_configured:
        missing = [
            name
            for name, value in (
                ("r2_endpoint", settings.r2_endpoint),
                ("r2_access_key_id", settings.r2_access_key_id),
                ("r2_secret_access_key", settings.r2_secret_access_key),
                ("r2_bucket", settings.r2_bucket),
            )
            if not value
        ]
        raise StorageError(
            f"Cloudflare R2 is not configured; missing: {', '.join(missing)}. "
            "Set AUDIOMIND_R2_ENDPOINT, AUDIOMIND_R2_ACCESS_KEY_ID, "
            "AUDIOMIND_R2_SECRET_ACCESS_KEY and AUDIOMIND_R2_BUCKET."
        )

    with _client_lock:
        if _client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:  # pragma: no cover - dependency guard
                raise StorageError(
                    "boto3 is required for R2 storage. Install it with "
                    "`pip install boto3`."
                ) from exc

            # R2 needs path-style addressing against the account endpoint and
            # no SigV4 chunked upload quirks; retries cover transient 5xx.
            _client = boto3.client(
                "s3",
                endpoint_url=settings.r2_endpoint,
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                region_name="auto",
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
            logger.info("R2 client ready for bucket %s", settings.r2_bucket)
    return _client


def reset_client() -> None:
    """Drop the cached client. Used by tests that change settings."""
    global _client
    with _client_lock:
        _client = None


def build_key(prefix: str, *parts: str) -> str:
    """Compose a stable, collision-free object key.

    The session/job id keeps two runs of the same track apart, so a re-mix
    overwrites only its own output instead of the previously served WAV.
    """
    segments = [str(part).strip("/") for part in (prefix, *parts) if part]
    return "/".join(segment for segment in segments if segment)


def upload_file(
    local_path: str,
    key: str,
    content_type: str = "audio/wav",
) -> str:
    """Upload a local file to R2 and return its key.

    The upload is verified with ``head_object`` instead of trusting the
    response: a silently-truncated audio file that the client then tries to
    stream is a far worse failure than an explicit error at write time.
    """
    client = get_s3_client()
    try:
        client.upload_file(
            local_path,
            settings.r2_bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )
        head = client.head_object(Bucket=settings.r2_bucket, Key=key)
    except Exception as exc:
        raise StorageError(f"R2 upload failed for {key!r}: {exc}") from exc

    size = int(head.get("ContentLength", 0))
    if size <= 0:
        raise StorageError(f"R2 stored an empty object for {key!r}")
    logger.info("Uploaded %s to R2 (%d bytes)", key, size)
    return key


def public_url(key: str) -> str | None:
    """Public URL of an object, when the bucket exposes one.

    Returns ``None`` for a private bucket; the caller should then serve a
    presigned URL instead of inventing a link that 403s.
    """
    if not settings.r2_public_url or not key:
        return None
    return f"{settings.r2_public_url.rstrip('/')}/{key.lstrip('/')}"


def presigned_url(key: str, expires_in: int = 3600) -> str:
    """Time-limited download URL. Works with a fully private bucket."""
    client = get_s3_client()
    try:
        url: str = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.r2_bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url
    except Exception as exc:
        raise StorageError(f"Could not presign {key!r}: {exc}") from exc


def presigned_put_url(
    key: str,
    content_type: str = "audio/wav",
    expires_in: int = 900,
) -> str:
    """Time-limited upload (PUT) URL for a browser direct-to-R2 upload.

    This is the write twin of :func:`presigned_url`. The Studio browser sends
    the audio bytes straight to R2 with an HTTP PUT instead of routing a
    60 MB WAV through the FastAPI container, which on Railway Free (512 MB)
    is what pushed the OOM killer into the mastering path. The key is chosen
    by the caller (deterministic, e.g. ``projects/{id}/originals/{asset}.wav``)
    so the follow-up "register asset" call can name the same object without
    the server ever seeing the bytes.

    ``ContentType`` is part of the signature, so the browser must PUT with the
    exact same header it was presigned for or R2 rejects the request.
    """
    client = get_s3_client()
    try:
        url: str = client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.r2_bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=expires_in,
        )
        return url
    except Exception as exc:
        raise StorageError(f"Could not presign PUT for {key!r}: {exc}") from exc


def download_to(key: str, local_path: str) -> str:
    """Fetch an object from R2 to a local path and return it."""
    client = get_s3_client()
    try:
        client.download_file(settings.r2_bucket, key, local_path)
    except Exception as exc:
        raise StorageError(f"R2 download failed for {key!r}: {exc}") from exc
    return local_path


def delete_file(key: str) -> None:
    """Delete an object. Missing keys are not an error (idempotent delete)."""
    client = get_s3_client()
    try:
        client.delete_object(Bucket=settings.r2_bucket, Key=key)
    except Exception as exc:
        logger.warning("R2 delete failed for %r: %s", key, exc)


def exists(key: str) -> bool:
    """Whether an object exists in the bucket."""
    client = get_s3_client()
    try:
        client.head_object(Bucket=settings.r2_bucket, Key=key)
    except Exception:
        return False
    return True
