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
* ``GET    /projects/{id}/document``            read the V1 project document.
* ``PUT    /projects/{id}/document``            write it (optimistic locking).
* ``DELETE /projects/{id}/document``            reset it to the bootstrap.

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

Document vs. live state
-----------------------
The two documents do not overlap. ``project_states`` holds the LIVE mix
(faders, toggles, undo/redo); ``project_documents`` holds intention and
structure (stem identity, pending AI proposals, master intent). The frontend
autosave store is the single writer of ``project_states`` (ownership invariant
I1), and nothing in this module's document endpoints writes that table — a
proposal becomes audible only when the user applies it through the normal
autosave path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from audiomind.api.auth import UserContext, get_user_context
from audiomind.models.project_document import ProjectDocument, default_document
from audiomind.services import storage, supabase_client
from audiomind.services.separate_jobs import submit_separate_job

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


class DocumentPut(BaseModel):
    """Body of ``PUT /projects/{id}/document``.

    ``expected_version`` is the row version the client last read (0 when it is
    creating the document for the first time). The server refuses the write
    with 409 when the row has moved past it, which is what keeps a stale tab
    from silently overwriting a newer document.
    """

    model_config = ConfigDict(extra="forbid")

    document: ProjectDocument
    expected_version: int = 0


class DocumentOut(BaseModel):
    """A project document plus the row version it was read from or written as."""

    project_id: str
    version: int
    document: ProjectDocument
    updated_at: str | None = None


class SeparateRequest(BaseModel):
    """Body of ``POST /projects/{id}/separate``."""

    asset_id: str = Field(..., max_length=64)
    model: str = Field(default="htdemucs", max_length=40)


class SeparateSubmitOut(BaseModel):
    """Answer to a separation submit.

    ``reused`` is true when a finished separation of these exact bytes already
    existed and its stems were handed straight back (no new job was queued).
    """

    job_id: str
    project_id: str
    asset_id: str
    status: str
    reused: bool = False
    result: dict[str, Any] | None = None


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


def _get_owned_asset(
    client: Any, project_id: str, asset_id: str, user_id: str
) -> dict[str, Any]:
    """Fetch an asset that lives in a project the caller owns, or 404.

    Same "not yours" == "does not exist" contract as the project lookup, so an
    endpoint never confirms another user's asset id.
    """
    resp = (
        client.table("audio_assets")
        .select("*")
        .eq("id", asset_id)
        .eq("project_id", project_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = _data(resp)
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archivo no encontrado.",
        )
    return rows[0]


def _get_document_row(
    client: Any, project_id: str, user_id: str
) -> dict[str, Any] | None:
    """Fetch the caller's document row for a project, or ``None``.

    ``None`` is not an error: it is the bootstrap case (no row yet), which
    ``GET`` answers with the default document at version 0. Filtering by
    ``user_id`` keeps the same "not yours" == "does not exist" answer as the
    rest of the module.
    """
    resp = (
        client.table("project_documents")
        .select("*")
        .eq("project_id", project_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    rows = _data(resp)
    return rows[0] if rows else None


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


# ── Stem separation (async, idempotent) ────────────────────────────────────


@router.post(
    "/{project_id}/separate",
    response_model=SeparateSubmitOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def separate_stems(
    project_id: str,
    payload: SeparateRequest,
    background_tasks: BackgroundTasks,
    ctx: Annotated[UserContext, Depends(get_user_context)],
) -> SeparateSubmitOut:
    """Kick off (or reuse) an async Demucs separation of an original asset.

    Returns immediately with a job id; the client polls
    ``GET /api/jobs/separate/{job_id}``. Separating the same audio twice is
    idempotent: when a finished separation of these exact bytes already exists
    for this project, its stems are handed straight back (``reused: true``)
    without running Demucs again.

    The original asset's ``media_hash`` (reported by the browser at upload) is
    the idempotency key. When it is missing the worker computes it from the
    bytes, so a first separation still dedupes correctly on the next submit.
    """
    client = _client_for(ctx)
    _get_owned_project(client, project_id, ctx.user_id)
    asset = _get_owned_asset(client, project_id, payload.asset_id, ctx.user_id)
    if asset.get("kind") != "original":
        raise HTTPException(
            status_code=422,
            detail="Solo se pueden separar archivos de tipo original.",
        )

    outcome = submit_separate_job(
        user_id=ctx.user_id,
        project_id=project_id,
        asset_id=payload.asset_id,
        media_hash=asset.get("media_hash"),
        model=payload.model,
        background_tasks=background_tasks,
    )
    return SeparateSubmitOut(
        job_id=outcome.job_id,
        project_id=project_id,
        asset_id=payload.asset_id,
        status=outcome.status,
        reused=outcome.reused,
        result=outcome.result,
    )


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


# ── Project document (intention + structure) ───────────────────────────────


@router.get("/{project_id}/document", response_model=DocumentOut)
async def get_document(
    project_id: str,
    ctx: Annotated[UserContext, Depends(get_user_context)],
) -> DocumentOut:
    """Read the V1 project document for a project the caller owns.

    No row answers with the bootstrap document at ``version: 0`` WITHOUT
    persisting anything, so reading a fresh project never creates state. A row
    whose ``document_json`` no longer satisfies schema V1 is a server-side
    defect, not a client error, and answers 500.
    """
    client = _client_for(ctx)
    _get_owned_project(client, project_id, ctx.user_id)
    row = _get_document_row(client, project_id, ctx.user_id)
    if row is None:
        return DocumentOut(
            project_id=project_id,
            version=0,
            document=default_document(),
            updated_at=None,
        )
    try:
        document = ProjectDocument.model_validate(row.get("document_json"))
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="El documento almacenado no cumple el esquema V1.",
        ) from exc
    return DocumentOut(
        project_id=project_id,
        version=int(row.get("version") or 0),
        document=document,
        updated_at=row.get("updated_at"),
    )


@router.put("/{project_id}/document", response_model=DocumentOut)
async def put_document(
    project_id: str,
    payload: DocumentPut,
    ctx: Annotated[UserContext, Depends(get_user_context)],
) -> DocumentOut:
    """Write the V1 project document with optimistic concurrency.

    The client sends the ``expected_version`` it last read and the row's
    ``version`` must match it, else 409: a stale writer loses instead of
    overwriting. ``version`` lives only in the row, never inside the JSON,
    which is what makes that comparison single-sourced and drift-free.

    Server-stamped fields: ``updated_at`` always comes from the server clock
    (a client value is ignored), ``schema_version`` is pinned to 1 by the
    model's ``Literal``, and ``updated_by`` comes from the validated payload
    (default ``user``). This endpoint never writes ``project_states``
    (ownership invariant I1: the frontend store is that table's only writer).
    """
    client = _client_for(ctx)
    _get_owned_project(client, project_id, ctx.user_id)

    document = payload.document
    stamped = _now_iso()
    document.updated_at = stamped
    document_json = document.model_dump(mode="json")

    conflict = HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "El documento fue modificado en otro lugar; recarga y vuelve a "
            "intentarlo."
        ),
    )

    row = _get_document_row(client, project_id, ctx.user_id)
    if row is not None:
        current = int(row.get("version") or 0)
        if current != payload.expected_version:
            raise conflict
        new_version = current + 1
        resp = (
            client.table("project_documents")
            .update(
                {
                    "version": new_version,
                    "document_json": document_json,
                    "updated_at": stamped,
                }
            )
            .eq("project_id", project_id)
            .eq("user_id", ctx.user_id)
            # Conditional write: the WHERE repeats the version we read, so a
            # racing writer that bumped it in between makes this match 0 rows.
            .eq("version", current)
            .execute()
        )
        if not _data(resp):
            # Lost the race between the read above and this write.
            raise conflict
    else:
        if payload.expected_version != 0:
            raise conflict
        new_version = 1
        insert_row = {
            "project_id": project_id,
            "user_id": ctx.user_id,
            "version": new_version,
            "document_json": document_json,
            "updated_at": stamped,
        }
        # The UNIQUE constraint on project_id is the first-write race guard:
        # two clients both PUTting version 0 cannot both insert, so the loser
        # violates the constraint. Translate that into the same 409 a stale
        # expected_version gets rather than surfacing a 500.
        try:
            client.table("project_documents").insert(insert_row).execute()
        except Exception as exc:
            raise conflict from exc

    return DocumentOut(
        project_id=project_id,
        version=new_version,
        document=document,
        updated_at=stamped,
    )


@router.delete(
    "/{project_id}/document",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    project_id: str,
    ctx: Annotated[UserContext, Depends(get_user_context)],
) -> Response:
    """Delete the project document, resetting intent to the bootstrap default.

    After this, ``GET`` answers ``version: 0`` with ``default_document()``
    again — nothing is seeded back, and the row is recreated only by a later
    PUT. Ownership follows the module's rule: the statement runs through the
    token-scoped client (so RLS enforces ``auth.uid() = user_id``) AND filters
    ``user_id`` explicitly, which fails closed even if a policy were
    misconfigured. ``project_states`` is deliberately untouched: the live mix
    belongs to the frontend store (ownership invariant I1).
    """
    client = _client_for(ctx)
    _get_owned_project(client, project_id, ctx.user_id)
    if _get_document_row(client, project_id, ctx.user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Documento no encontrado.",
        )
    # Delete filtered by project_id AND user_id: RLS already fences the row,
    # the explicit predicate makes ownership visible and fails closed. The
    # existence check above is what turns "no row" into a 404; the delete
    # itself is not inspected because PostgREST may answer DELETE with an
    # empty representation.
    (
        client.table("project_documents")
        .delete()
        .eq("project_id", project_id)
        .eq("user_id", ctx.user_id)
        .execute()
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
