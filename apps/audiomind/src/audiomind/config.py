from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

# Path to the backend/ directory (parent of src/)
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    app_name: str = "AudioMind"
    debug: bool = True

    # File storage
    upload_dir: Path = _BACKEND_DIR / "uploads"
    output_dir: Path = _BACKEND_DIR / "outputs"
    samples_dir: Path = _BACKEND_DIR / "samples"
    projects_dir: Path = _BACKEND_DIR / "projects"
    # Pre-built mastered tracks (hackathon / demo speedup)
    prebuilt_dir: Path = _BACKEND_DIR / "prebuilt"
    max_file_size_mb: int = 50

    # Processing
    target_lufs: float = -14.0
    sample_rate: int = 44100

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    # CORS: local dev origins + the production Studio (Railway). The railway
    # origin is in the default so a deployment that doesn't override these is
    # never blocked — a CORS-silent 502 makes the frontend "freeze" mid-master.
    cors_origins: list[str] = [
        "https://studio-production-f546.up.railway.app",
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    # CORS regex net: any *.vercel.app origin reaches the public demo without
    # re-adding each Vercel project hash on every redeploy (the demo project
    # keeps changing its .vercel.app hash). The demo service is public anyway
    # (no license key); this only relaxes browser-origin checks, not transport
    # access. Set AUDIOMIND_CORS_ORIGIN_REGEX="" to disable and go back to the
    # exact allowlist only.
    cors_origin_regex: str = r"https://.*\.vercel\.app"

    # License
    license_key: str = ""  # AUDIOMIND_LICENSE_KEY env var

    # ── Client demo mode ────────────────────────────────────────────────
    # All demo knobs default to the historic "master all presets" behavior
    # so a deployment that sets no env vars is byte-for-byte the same as
    # before this feature. The demo deployment (Vercel/Railway) overrides:
    #   AUDIOMIND_PRERENDER_MODE=on_demand          (no automatic preset DSP)
    #   AUDIOMIND_MAX_CONCURRENT_DSP=1              (serialize heavy DSP)
    #   AUDIOMIND_DEMO_MAX_DURATION_SECONDS=240     (demo upload cap: 4 min)
    #   AUDIOMIND_MAX_FILE_SIZE_MB=100              (demo covers 4-min PCM24
    #                                                44.1k stereo ≈ 63.5 MB)
    #   AUDIOMIND_SESSION_TTL_MINUTES=60            (janitor prunes idle uploads)
    prerender_mode: Literal["all", "on_demand"] = "all"
    max_concurrent_dsp: int = 2
    demo_max_duration_seconds: float = 0.0
    session_ttl_minutes: int = 0

    # ── Supabase Cloud Integration (Fase 6) ─────────────────────────────
    supabase_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AUDIOMIND_SUPABASE_URL",
            "SUPABASE_URL",
            "NEXT_PUBLIC_SUPABASE_URL",
        ),
    )
    supabase_service_role_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AUDIOMIND_SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_SERVICE_ROLE_KEY",
            "SUPABASE_SERVICE_KEY",
        ),
    )
    supabase_anon_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AUDIOMIND_SUPABASE_ANON_KEY",
            "SUPABASE_ANON_KEY",
            "NEXT_PUBLIC_SUPABASE_ANON_KEY",
        ),
    )
    supabase_originals_bucket: str = Field(
        default="audio-originals",
        validation_alias=AliasChoices(
            "AUDIOMIND_SUPABASE_ORIGINALS_BUCKET",
            "SUPABASE_ORIGINALS_BUCKET",
        ),
    )
    supabase_masters_bucket: str = Field(
        default="audio-masters",
        validation_alias=AliasChoices(
            "AUDIOMIND_SUPABASE_MASTERS_BUCKET",
            "SUPABASE_MASTERS_BUCKET",
        ),
    )

    model_config = {
        "env_prefix": "AUDIOMIND_",
        "env_file": str(_BACKEND_DIR / ".env"),
        "env_file_encoding": "utf-8",
    }


settings = Settings()

# Ensure directories exist
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)
settings.samples_dir.mkdir(parents=True, exist_ok=True)
settings.projects_dir.mkdir(parents=True, exist_ok=True)
settings.prebuilt_dir.mkdir(parents=True, exist_ok=True)
