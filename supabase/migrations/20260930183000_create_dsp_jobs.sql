-- Durable job state, so a job survives the process that is running it.
--
-- WHY THIS TABLE EXISTS
-- Mastering and mixing run in the background: the endpoint answers 202 with a
-- job id and the browser polls until the job reaches a terminal status. With
-- only the in-memory store, the record died with the process -- so any Railway
-- redeploy, health-check restart or worker crash during a render turned into a
-- permanent 404 on a job the DSP had already paid for. The audio itself was
-- already durable in Cloudflare R2; this table makes the *pointer* to it
-- durable too.
--
-- THE LEASE
-- A worker stamps `lease_expires_at` when it picks a job up and extends it with
-- `heartbeat()` while it works. A reader whose clock is past that instant
-- treats the job as dead and reclaimable. This is what stops a job that was
-- interrupted mid-flight from being reported as permanently "processing" to a
-- browser that will poll it forever.
--
-- SCOPE / SAFETY
-- Purely additive: ONE new table, nothing else referenced. `tracks`, `masters`,
-- `profiles`, `track_events` and the R2 buckets are untouched.
--
-- WHO CAN READ IT
-- RLS is enabled with NO policies. The backend authenticates with the Supabase
-- *service_role* key, which bypasses RLS; the browser never touches this table,
-- it polls our FastAPI endpoint instead. Job rows carry R2 keys and analysis
-- payloads, and the download URL is signed server-side for that reason.
--
-- THIS FILE WAS RECONSTRUCTED
-- It went missing from the repository while the live table had been created by
-- hand instead, which is exactly how `meta` and `lease_expires_at` came to be
-- absent in production: `tests/test_dsp_jobs_migration.py` asserts every
-- `JobRecord` field has a column here, and it was failing on a clean checkout
-- because this file did not exist. The live table was repaired by
-- 20261005180000_repair_job_and_session_schema.sql.

create table if not exists public.dsp_jobs (
    -- Opaque id from `job_store.new_job_id`: kind prefix + uuid4 hex. Generated
    -- by the app so a worker handed an id can register the record under THAT id.
    job_id text primary key,

    -- "master" or "mix", so one table serves both pipelines and a reader can
    -- filter without knowing which endpoint produced the row.
    kind text not null,

    -- Mirrors the Python `JobStatus` StrEnum. CHECKed against the enum so a
    -- typo cannot become a status the poller does not recognise and therefore
    -- never resolves.
    status text not null default 'processing'
        check (status in ('processing', 'completed', 'error')),

    -- 0..100, best-effort, mirroring the DSP chain. UI feedback only: the
    -- CHECK keeps a bad write from rendering as "140%" in the browser.
    progress integer not null default 0
        check (progress between 0 and 100),

    -- Free-form stage label mirroring the DSP chain.
    stage text,

    -- Session this job belongs to, so a reload can reattach to its job.
    session_id text,

    -- Submit-time input, kept separate from `result` so a reader can tell what
    -- the job was asked to do from what it produced. The mastering endpoint
    -- needs its `track_id` back to answer the poll, and that is input, not a
    -- deliverable.
    meta jsonb not null default '{}'::jsonb,

    -- Kind-specific output: R2 key, download URL, analysis payload.
    result jsonb not null default '{}'::jsonb,

    error text,

    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    -- Worker heartbeat deadline. Nullable on purpose: a terminal job clears its
    -- lease, and a job that was never leased has no expiry. Compared against
    -- now() to detect dead workers, so it must be timestamptz -- as text the
    -- comparison would be lexicographic and silently wrong for any other ISO
    -- variant.
    lease_expires_at timestamptz
);

comment on table public.dsp_jobs is
    'Durable AudioMind background job state. Read/written by AudioMind with the service_role key.';
comment on column public.dsp_jobs.meta is
    'Submit-time job input (track_id, preset_id, ...) separate from result, which holds only the deliverable.';
comment on column public.dsp_jobs.lease_expires_at is
    'Worker heartbeat deadline. Null once the job is terminal; a reader past this instant treats the job as dead and reclaimable.';

-- The poll endpoint filters on job_id (already covered by the primary key), but
-- the janitor that reclaims dead work scans the lease, and that scan is
-- sequential over every row without this.
create index if not exists dsp_jobs_lease_expires_at_idx
    on public.dsp_jobs (lease_expires_at)
    where lease_expires_at is not null;

-- Housekeeping. The app does not delete job rows on its own, so this grows one
-- row per job. A terminal job older than a week carries no value: its audio
-- lives in R2 under its own lifecycle. Left commented out on purpose, same
-- reasoning as `sessions` -- pg_cron has to be enabled per project, and
-- surprising a project with a background writer is not this migration's call.
--
--   delete from public.dsp_jobs
--    where status in ('completed', 'error')
--      and updated_at < now() - interval '7 days';

-- RLS on, zero policies: service_role bypasses it, anon/authenticated get
-- nothing. See the header note before changing this.
alter table public.dsp_jobs enable row level security;