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
    # Which store owns the session record: "auto" (Supabase when it is
    # configured AND its table probes clean, the file mirror otherwise),
    # "supabase" (force, no fallback) or "file" (never touch the network).
    #
    # "auto" is what production wants. "file" exists for the test suite: it
    # pins the backend at import time, BEFORE `api.upload` builds its in-memory
    # dict, so a developer's real credentials can never make the suite read or
    # write the production `sessions` table. That is the same class of leak as
    # the one the conftest storage fixture already prevents for R2.
    session_store_backend: str = Field(
        default="auto",
        validation_alias=AliasChoices(
            "AUDIOMIND_SESSION_STORE_BACKEND",
            "SESSION_STORE_BACKEND",
        ),
    )

    # ── Cloudflare R2 (S3-compatible object storage) ─────────────────────
    # Credentials are ENV-ONLY on purpose: there is deliberately NO default
    # value here. A credential baked into source is a leaked credential the
    # moment the file is read, logged, or committed, and it silently keeps
    # working in environments that were never configured. An unconfigured
    # deployment must fail loudly (see ``r2_is_configured``) instead of
    # quietly shipping uploads to an anonymous bucket.
    #
    # Both naming conventions are accepted so an operator can use either the
    # Cloudflare-flavoured ``CLOUDFLARE_R2_*`` or the project-wide
    # ``AUDIOMIND_R2_*`` prefix (the latter wins when both are set).
    r2_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AUDIOMIND_R2_ENDPOINT", "CLOUDFLARE_R2_ENDPOINT", "R2_ENDPOINT"
        ),
    )
    r2_access_key_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AUDIOMIND_R2_ACCESS_KEY_ID",
            "CLOUDFLARE_R2_ACCESS_KEY_ID",
            "R2_ACCESS_KEY_ID",
        ),
    )
    r2_secret_access_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AUDIOMIND_R2_SECRET_ACCESS_KEY",
            "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
            "R2_SECRET_ACCESS_KEY",
        ),
    )
    r2_bucket: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AUDIOMIND_R2_BUCKET",
            "CLOUDFLARE_R2_BUCKET",
            "R2_BUCKET_NAME",
        ),
    )
    # Public base URL of the bucket (r2.dev or a custom domain). Only used to
    # build shareable links; a private bucket can still be served through
    # presigned URLs, which need no public domain at all.
    r2_public_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "AUDIOMIND_R2_PUBLIC_URL",
            "CLOUDFLARE_R2_PUBLIC_URL",
            # Bare name, matching the alias set already accepted for
            # endpoint/keys/bucket. Without it an operator who names the other
            # five R2_* vars naturally is left with this one silently empty,
            # and every read falls back to a presigned URL.
            "R2_PUBLIC_URL",
        ),
    )

    # ── Durable job store ────────────────────────────────────────────────
    # A BackgroundTask dies with the worker process: if the container
    # restarts mid-job the task is gone and nothing ever marks it failed. A
    # lease (in seconds) lets the status endpoint recognise such an orphan and
    # report it as ``error`` instead of leaving the client polling a job that
    # will never finish.
    job_lease_seconds: int = 900

    model_config = {
        "env_prefix": "AUDIOMIND_",
        "env_file": str(_BACKEND_DIR / ".env"),
        "env_file_encoding": "utf-8",
    }

    @property
    def r2_is_configured(self) -> bool:
        """True only when every credential needed to reach the bucket is set."""
        return all(
            (
                self.r2_endpoint,
                self.r2_access_key_id,
                self.r2_secret_access_key,
                self.r2_bucket,
            )
        )


settings = Settings()

# Ensure directories exist
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)
settings.samples_dir.mkdir(parents=True, exist_ok=True)
settings.projects_dir.mkdir(parents=True, exist_ok=True)
settings.prebuilt_dir.mkdir(parents=True, exist_ok=True)
