-- Project document: intention + structure, the fourth Moises-style table.
--
-- WHY THIS EXISTS
-- ``project_states`` (20261008120000) holds the LIVE mix: faders, toggles,
-- undo/redo, written only by the Studio autosave store (ownership invariant
-- I1). This table holds the other half of the project, the part that is NOT
-- live state:
--
--   * ``structure``  — identity and presentation of the 4 Demucs stems
--                      (display_name, order, group_id, color) plus UI groups.
--   * ``mix_intent`` — pending AI proposals. A proposal is intent only; it is
--                      NEVER audible until the user applies it to
--                      ``project_states``.
--   * ``master_intent`` — preset/platform/format/bit-depth/parameter overlay
--                      that the compiler projects onto MasterJobPayload.
--
-- The two tables deliberately do NOT share keys, so there is no precedence to
-- define and no merge to write: one datum, one house, one writer. That is what
-- keeps the backend free of split-brain.
--
-- ONE ROW PER PROJECT
-- ``project_id`` is UNIQUE, so the document is a 1:1 store, not a history.
-- Versioning is handled by the ``version`` column below, not by extra rows.
--
-- SAFE TO RUN MORE THAN ONCE
-- ``if not exists`` for the table/index and drop-then-create for the policies:
-- the dashboard is the deploy path, so a double paste must be a no-op.

create table if not exists public.project_documents (
    id uuid primary key default gen_random_uuid(),

    -- Owning project, exactly one document each. ON DELETE CASCADE so
    -- deleting a project removes its intention/structure with it.
    project_id uuid not null unique references public.projects (id) on delete cascade,

    -- Denormalized owner, same as its sibling tables: the RLS predicate
    -- (auth.uid() = user_id) needs no join, and deleting a user in
    -- auth.users cascades here without walking public.projects.
    user_id uuid not null references auth.users (id) on delete cascade,

    -- Optimistic-concurrency counter. It lives ONLY here and never inside
    -- document_json: a single source of truth cannot drift from itself. The
    -- PUT endpoint compares the client's expected_version against this column
    -- and writes conditionally (``... .eq("version", expected)``), so a stale
    -- writer loses with 409 instead of silently overwriting a newer document.
    -- Every successful write bumps it by exactly 1; a missing row reads as
    -- version 0 (the bootstrap default document, never persisted).
    version integer not null default 1,

    -- The validated V1 document (structure + mix_intent + master_intent).
    -- JSONB rather than a column per knob: the shape is specified once by the
    -- backend schema (spec project_document_v1_spec.md §3) and evolves by
    -- schema_version, while a column-per-field insert would silently drop any
    -- key Postgres does not know about. ``schema_version``, ``updated_by`` and
    -- ``updated_at`` live INSIDE this payload and are stamped by the server on
    -- every write, so a client cannot forge them.
    document_json jsonb not null,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

comment on table public.project_documents is
    'Intention + structure of one project (V1 document as JSONB), one row per project. The LIVE mix lives in project_states; RLS-fenced by user_id.';
comment on column public.project_documents.project_id is
    'Owning project; UNIQUE enforces the 1:1 document store (at most one document per project).';
comment on column public.project_documents.version is
    'Optimistic-concurrency counter, row-level only. Deliberately NOT part of document_json: one source, no drift. Missing row == version 0 (bootstrap).';
comment on column public.project_documents.document_json is
    'Validated V1 document (structure, mix_intent, master_intent). schema_version/updated_by/updated_at live inside and are stamped server-side on every write.';

-- Index only on user_id. ``project_id`` needs none of its own: the UNIQUE
-- constraint above already builds a b-tree index on it, so a plain
-- ``project_id`` index would be a duplicate that costs a write on every PUT
-- and buys no read. ``user_id`` has no such constraint and is probed by both
-- the RLS predicate (auth.uid() = user_id) and the ON DELETE CASCADE from
-- auth.users, so keeping it indexed keeps per-user reads and user deletion
-- O(log n).
create index if not exists project_documents_user_id_idx
    on public.project_documents (user_id);

alter table public.project_documents enable row level security;

-- Drop-then-create keeps a re-paste idempotent (Postgres has no
-- ``create policy if not exists`` before v15, and the dashboard is v14+).
drop policy if exists "document_select_own" on public.project_documents;
create policy "document_select_own"
    on public.project_documents for select
    using (auth.uid() = user_id);

drop policy if exists "document_insert_own" on public.project_documents;
create policy "document_insert_own"
    on public.project_documents for insert
    with check (auth.uid() = user_id);

drop policy if exists "document_update_own" on public.project_documents;
create policy "document_update_own"
    on public.project_documents for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "document_delete_own" on public.project_documents;
create policy "document_delete_own"
    on public.project_documents for delete
    using (auth.uid() = user_id);
