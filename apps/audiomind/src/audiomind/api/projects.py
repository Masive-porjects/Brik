"""Multi-tenant "project document" API (Moises-style).

Endpoints that turn the anonymous, session-scoped backend into a per-user
document store:

* ``POST   /projects``                          create a project.
* ``GET    /projects``                          list the caller's projects.
* ``GET    /projects/{id}`                      read one project.
* ``POST   /projects/{id}/assets/presign``      mint a direct-to-R2 PUT URL
                                                and register the asset row.
* ``PATCH  /projects/{id}/assets/{asset_id}``   record upload introspection.
* ``GET    /projects/{id}/assets``              list a project's files.
* ``GET    /projects/{id}/state``               read the live mix state.
* ``PATCH  /projects/{id}/state``               upsert the live mix state.

Ownership model
---------------
Every endpoint depends on :func:`get_user_context`, so the caller is a
validated Supabase user. Rows are written through a **token-scoped** Supabase
client, which makes Postgres enforce ``auth.uid() = user_id`` (RLS) on every
statement. The ``user_id`` column is also filtered explicitly in each query:
redundant under RLS, but it is what makes ownership visible and testable with
a fake client, and it fails closed if a policy were ever misconfigured.

Mix state is stored as JSONB (``project_states.state``) rather than a column
per fader: the shape is owned by the Studio and will evolve, and a
column-per-field upsert would silently drop keys Postgres does not know about.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from audiomind.api.auth import UserContext, get_user_context
from audiomind.services import storage, supabase_client

router = APIRouter(prefix="/projects", tags=["projects"])

AssetKind = Literal["original", "stem", "master"]

#: Presigned PUT URLs only need to survive until the browser finishes the
#: upload; 15 minutes is generous for a local file and keeps a leaked URL
#: short-lived.
_PRESIGN_EXPIRES_SECONDS = 900

#: content-type → file extension for the deterministic R2 key. Anything
#: unrecognised falls back to ``bin`` (the key is a pointer, not a player).
_CONTENT_TYPE_EXT = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "audio/ogg": "ogg",
}


def _ext_for(content_type: str) -> str:
    return _CONTENT_TYPE_EXT.get(content_type.strip().lower(), "bin")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _client_for(ctx: UserContext) -> Any:
    """Token-scoped Supabase client (RLS enforces ownership).

    Returns ``None``-safe by raising 503: these endpoints exist to persist a
    document, and there is nowhere to persist it without Supabase. Local dev
    and the test suite inject a fake through ``get_supabase_client``.
    """
    client = supabase_client.get_supabase_client(ctx.token)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Supabase no está configurado; no se puede guardar el "
                "proyecto. Configurá AUDIOMIND_SUPABASE_URL y la service key."
            ),
        )
    return client


def _data(resp: Any) -> list[dict[str, Any]]:
    """Rows from a PostgREST response, tolerating an empty/None payload."""
    rows = getattr(resp, "data", None)
    if not rows:
        return []
    if isinstance(rows, dict):
        return [rows]
    return [row for row in rows if isinstance(row, dict)]


# ── Request / response models ──────────────────────────────────────────────


class ProjectCreate(BaseModel):
    name: str = Field(default="Untitled project", min_length=1, max_length=200)
    bpm: int | None = Field(default=None, ge=20, le=300)
    musical_key: str | None = Field(default=None, max_length=16)


class ProjectOut(BaseModel):
    id: str
    user_id: str
    name: str
    bpm: int | None = None
    musical_key: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class PresignRequest(BaseModel):
    kind: AssetKind
    stem_name: str | None = Field(default=None, max_length=16)
    original_filename: str | None = Field(default=None, max_length=300)
    content_type: str = Field(default="audio/wav", max_length=100)


class PresignOut(BaseModel):
    asset_id: str
    project_id: str
    r2_key: str
    put_url: str
    content_type: str
    expires_in: int


class AssetComplete(BaseModel):
    duration_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    format: str | None = Field(default=None, max_length=16)
    size_bytes: int | None = None
    media_hash: str | None = Field(default=None, max_length=64)


class AssetOut(BaseModel):
    id: str
    project_id: str
    user_id: str
    kind: str
    stem_name: str | None = None
    r2_key: str
    media_hash: str | None = None
    original_filename: str | None = None
    duration_seconds: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    format: str | None = None
    size_bytes: int | None = None
    created_at: str | None = None


class StateUpsert(BaseModel):
    state: dict[str, Any] = Field(default_factory=dict)
    undo_stack: list[Any] = Field(default_factory=list)


class StateOut(BaseModel):
    project_id: str
    state: dict[str, Any] = Field(default_factory=dict)
    undo_stack: list[Any] = Field(default_factory=list)
    updated_at: str | None = None


def _project_out(row: dict[str, Any]) -> ProjectOut:
    return ProjectOut(
        id=str(row.get("id", "")),
        user_id=str(row.get("user_id", "")),
        name=str(row.get("name", "")),
        bpm=row.get("bpm"),
        musical_key=row.get("musical_key"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def _asset_out(row: dict[str, Any]) -> AssetOut:
    return AssetOut(
        id=str(row.get("id", "")),
        project_id=str(row.get("project_id", "")),
        user_id=str(row.get("user_id", "")),
        kind=str(row.get("kind", "")),
        stem_name=row.get("stem_name"),
        r2_key=str(row.get("r2_key", "")),
        media_hash=row.get("media_hash"),
        original_filename=row.get("original_filename"),
        duration_seconds=row.get("duration_seconds"),
        sample_rate=row.get("sample_rate"),
        channels=row.get("channels"),
        format=row.get("format"),
        size_bytes=row.get("size_bytes"),
        created_at=row.get("created_at"),
    )


def _get_owned_project(
    client: Any, project_id: str, user_id: str
) -> dict[str, Any]:
    """Fetch a project the caller owns, or 404.

    Filtering by ``user_id`` makes "not yours" and "does not exist" the same
    answer, so the endpoint never confirms the existence of another user's
    project id.
    """
    resp = (
        client.table("projects")
        .select("*")
        .eq("id", project_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = _data(resp)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Proyecto no encontrado.",
        )
    return rows[0]


# ── Projects ───────────────────────────────────────────────────────────────


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    ctx: Annotated[UserContext, Depends(get_user_context)],
) -> ProjectOut:
    """Create a project owned by the caller."""
    client = _client_for(ctx)
    row = {
        "user_id": ctx.user_id,
        "name": payload.name.strip() or "Untitled project",
        "bpm": payload.bpm,
        "musical_key": payload.musical_key,
    }
    resp = client.table("projects").insert(row).execute()
    rows = _data(resp)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo crear el proyecto.",
        )
    return _project_out(rows[0])


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    ctx: Annotated[UserContext, Depends(get_user_context)],
) -> list[ProjectOut]:
    """List the caller's projects, most recently updated first."""
    client = _client_for(ctx)
    resp = (
        client.table("projects")
        .select("*")
        .eq("user_id", ctx.user_id)
        .execute()
    )
    rows = _data(resp)
    rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
    return [_project_out(row) for row in rows]


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: str,
    ctx: Annotated[UserContext, Depends(get_user_context)],
) -> ProjectOut:
    """Read one project the caller owns."""
    client = _client_for(ctx)
    return _project_out(_get_owned_project(client, project_id, ctx.user_id))


# ── Assets (direct-to-R2 upload) ───────────────────────────────────────────


@router.post(
    "/{project_id}/assets/presign",
    response_model=PresignOut,
    status_code=status.HTTP_201_CREATED,
)
async def presign_asset(
    project_id: str,
    payload: PresignRequest,
    ctx: Annotated[UserContext, Depends(get_user_context)],
) -> PresignOut:
    """Register an asset row and mint a direct-to-R2 PUT URL.

    The browser uploads the bytes straight to R2 (no FastAPI round-trip for a
    60 MB WAV), then calls ``PATCH .../assets/{asset_id}`` to record the
    decoded duration/sample-rate. The asset row is created here so the server
    owns both the ``asset_id`` and the deterministic ``r2_key`` before any
    bytes move.
    """
    client = _client_for(ctx)
    _get_owned_project(client, project_id, ctx.user_id)

    if payload.kind == "stem" and not payload.stem_name:
        raise HTTPException(
            status_code=422,
            detail="Un stem debe indicar stem_name (drums|bass|other|vocals).",
        )

    asset_id = str(uuid.uuid4())
    ext = _ext_for(payload.content_type)
    r2_key = f"projects/{project_id}/{payload.kind}/{asset_id}.{ext}"

    row = {
        "id": asset_id,
        "project_id": project_id,
        "user_id": ctx.user_id,
        "kind": payload.kind,
        "stem_name": payload.stem_name,
        "r2_key": r2_key,
        "original_filename": payload.original_filename,
    }
    resp = client.table("audio_assets").insert(row).execute()
    if not _data(resp):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo registrar el archivo.",
        )

    try:
        put_url = storage.presigned_put_url(
            r2_key,
            content_type=payload.content_type,
            expires_in=_PRESIGN_EXPIRES_SECONDS,
        )
    except storage.StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No se pudo generar el enlace de subida: {exc}",
        ) from exc

    return PresignOut(
        asset_id=asset_id,
        project_id=project_id,
        r2_key=r2_key,
        put_url=put_url,
        content_type=payload.content_type,
        expires_in=_PRESIGN_EXPIRES_SECONDS,
    )


@router.patch(
    "/{project_id}/assets/{asset_id}",
    response_model=AssetOut,
)
async def complete_asset(
    project_id: str,
    asset_id: str,
    payload: AssetComplete,
    ctx: Annotated[UserContext, Depends(get_user_context)],
) -> AssetOut:
    """Record upload introspection (duration, rate, size, media_hash).

    Called by the browser after its direct-to-R2 PUT succeeds. Only the
    caller's own asset in the caller's own project can be patched.
    """
    client = _client_for(ctx)
    _get_owned_project(client, project_id, ctx.user_id)

    patch: dict[str, Any] = {
        key: value
        for key, value in (
            ("duration_seconds", payload.duration_seconds),
            ("sample_rate", payload.sample_rate),
            ("channels", payload.channels),
            ("format", payload.format),
            ("size_bytes", payload.size_bytes),
            ("media_hash", payload.media_hash),
        )
        if value is not None
    }
    if not patch:
        raise HTTPException(
            status_code=422,
            detail="No hay campos para actualizar.",
        )

    resp = (
        client.table("audio_assets")
        .update(patch)
        .eq("id", asset_id)
        .eq("project_id", project_id)
        .eq("user_id", ctx.user_id)
        .execute()
    )
    rows = _data(resp)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archivo no encontrado.",
        )
    return _asset_out(rows[0])


@router.get("/{project_id}/assets", response_model=list[AssetOut])
async def list_assets(
    project_id: str,
    ctx: Annotated[UserContext, Depends(get_user_context)],
) -> list[AssetOut]:
    """List a project's files (original, stems, masters)."""
    client = _client_for(ctx)
    _get_owned_project(client, project_id, ctx.user_id)
    resp = (
        client.table("audio_assets")
        .select("*")
        .eq("project_id", project_id)
        .eq("user_id", ctx.user_id)
        .execute()
    )
    rows = _data(resp)
    rows.sort(key=lambda r: str(r.get("created_at") or ""))
    return [_asset_out(row) for row in rows]


# ── Mix state ──────────────────────────────────────────────────────────────


@router.get("/{project_id}/state", response_model=StateOut)
async def get_state(
    project_id: str,
    ctx: Annotated[UserContext, Depends(get_user_context)],
) -> StateOut:
    """Read the live mix state. An uninitialised project returns empty state."""
    client = _client_for(ctx)
    _get_owned_project(client, project_id, ctx.user_id)
    resp = (
        client.table("project_states")
        .select("*")
        .eq("project_id", project_id)
        .eq("user_id", ctx.user_id)
        .limit(1)
        .execute()
    )
    rows = _data(resp)
    if not rows:
        return StateOut(project_id=project_id, state={}, undo_stack=[])
    row = rows[0]
    return StateOut(
        project_id=project_id,
        state=row.get("state") or {},
        undo_stack=row.get("undo_stack") or [],
        updated_at=row.get("updated_at"),
    )


@router.patch("/{project_id}/state", response_model=StateOut)
async def upsert_state(
    project_id: str,
    payload: StateUpsert,
    ctx: Annotated[UserContext, Depends(get_user_context)],
) -> StateOut:
    """Upsert the live mix state (the autosave target).

    ``project_states.project_id`` is the primary key, so the upsert replaces
    whatever the caller last saved for this project and no history piles up.
    """
    client = _client_for(ctx)
    _get_owned_project(client, project_id, ctx.user_id)

    row = {
        "project_id": project_id,
        "user_id": ctx.user_id,
        "state": payload.state,
        "undo_stack": payload.undo_stack,
        "updated_at": _now_iso(),
    }
    resp = (
        client.table("project_states")
        .upsert(row, on_conflict="project_id")
        .execute()
    )
    rows = _data(resp)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="No se pudo guardar el estado de mezcla.",
        )
    stored = rows[0]
    return StateOut(
        project_id=project_id,
        state=stored.get("state") or payload.state,
        undo_stack=stored.get("undo_stack") or payload.undo_stack,
        updated_at=stored.get("updated_at"),
    )
