"""Supabase client integration for AudioMind worker and API.

Provides typed access to Supabase Storage and Postgres tables for
stateless DSP processing, decoupling the mastering engine from in-memory
sessions and enabling cloud-native workflow execution.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from supabase import Client, create_client

from audiomind.config import settings

logger = logging.getLogger(__name__)

# Cached default client instance
_default_client: Client | None = None


def get_supabase_client(token: str | None = None) -> Client | None:
    """Get or create a Supabase client.

    If ``token`` is provided, a client initialized with that user token
    is returned (for RLS enforcement). Otherwise, the service role key is
    preferred to allow worker operations, falling back to anon key.
    Returns None if Supabase credentials are not configured.
    """
    global _default_client

    url = settings.supabase_url.strip()
    if not url:
        return None

    # Determine key to use
    key = (
        token
        or settings.supabase_service_role_key.strip()
        or settings.supabase_anon_key.strip()
    )
    if not key:
        return None

    # If asking for a specific token or if service_role is not cached, create new
    if token:
        try:
            return create_client(url, key)
        except Exception as e:
            logger.warning("Failed to initialize token-specific Supabase client: %s", e)
            return None

    if _default_client is None:
        try:
            _default_client = create_client(url, key)
            logger.info("Supabase client initialized successfully against %s", url)
        except Exception as e:
            logger.error("Failed to initialize default Supabase client: %s", e)
            return None

    return _default_client


def download_storage_file(
    source: str,
    bucket: str | None = None,
    client: Client | None = None,
) -> bytes:
    """Download audio file bytes from an HTTP/signed URL or Supabase Storage path.

    Parameters
    ----------
    source:
        Either a full HTTP/HTTPS URL (e.g., signed URL) or a storage path within
        the specified bucket (e.g., ``userId/trackId.wav``).
    bucket:
        Supabase bucket name (defaults to ``settings.supabase_originals_bucket``).
    client:
        Optional Supabase client. If None, `get_supabase_client()` is used.
    """
    # 1. Direct HTTP/HTTPS download (works for pre-signed URLs or external sources)
    if source.startswith(("http://", "https://")):
        logger.info("Downloading audio via HTTP URL: %s...", source[:60])
        with httpx.Client(timeout=180.0, follow_redirects=True) as http_client:
            response = http_client.get(source)
            response.raise_for_status()
            return response.content

    # 2. Supabase Storage download
    resolved_bucket = bucket or settings.supabase_originals_bucket
    target_client = client or get_supabase_client()
    if target_client is None:
        raise RuntimeError(
            "Supabase client is not configured and source is not an HTTP URL."
        )

    clean_path = source
    # Strip optional prefix like "audio-originals:"
    if ":" in clean_path and not clean_path.startswith("http"):
        clean_path = clean_path.split(":", 1)[1]

    logger.info(
        "Downloading from Supabase Storage: bucket=%s path=%s",
        resolved_bucket,
        clean_path,
    )
    data = target_client.storage.from_(resolved_bucket).download(clean_path)
    return data


def upload_storage_file(
    file_bytes: bytes,
    destination_path: str,
    bucket: str | None = None,
    content_type: str = "audio/wav",
    client: Client | None = None,
) -> str:
    """Upload audio file bytes directly to Supabase Storage.

    Returns the clean destination storage path.
    """
    resolved_bucket = bucket or settings.supabase_masters_bucket
    target_client = client or get_supabase_client()
    if target_client is None:
        raise RuntimeError("Supabase client is not configured for storage upload.")

    clean_path = destination_path
    if ":" in clean_path and not clean_path.startswith("http"):
        clean_path = clean_path.split(":", 1)[1]

    clean_path = clean_path.lstrip("/")

    logger.info(
        "Uploading to Supabase Storage: bucket=%s path=%s (%d bytes)",
        resolved_bucket,
        clean_path,
        len(file_bytes),
    )

    target_client.storage.from_(resolved_bucket).upload(
        path=clean_path,
        file=file_bytes,
        file_options={"content-type": content_type, "upsert": "true"},
    )
    return clean_path


def create_or_update_master_record(
    client: Client,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Insert or upsert a master record in `public.masters`."""
    response = client.table("masters").upsert(record).execute()
    if response.data and isinstance(response.data, list) and len(response.data) > 0:
        item = response.data[0]
        if isinstance(item, dict):
            return dict(item)
    return record



def update_track_status(
    client: Client,
    track_id: str,
    status: str,
) -> None:
    """Update track status in `public.tracks` table."""
    try:
        client.table("tracks").update({"status": status}).eq("id", track_id).execute()
    except Exception as e:
        logger.warning(
            "Could not update track %s status to '%s': %s", track_id, status, e
        )


def log_track_event(
    client: Client,
    user_id: str,
    track_id: str,
    event_type: str,
    details: dict[str, Any] | None = None,
) -> None:
    """Record an audit entry in `public.track_events`."""
    try:
        client.table("track_events").insert(
            {
                "user_id": user_id,
                "track_id": track_id,
                "event_type": event_type,
                "details": details or {},
            }
        ).execute()
    except Exception as e:
        logger.warning(
            "Could not log track event '%s' for track %s: %s",
            event_type,
            track_id,
            e,
        )
