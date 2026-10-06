-- Add the missing lifecycle column to public.masters.
--
-- run_master_job upserts ``status`` in its master_record (dsp_worker.py:458),
-- but the table never had that column, so every insert failed with
--   42703 column masters.status does not exist
-- The failure is swallowed by a `logger.warning` at dsp_worker.py:476, which is
-- why the API still answered 200 and reported success: the file was already
-- uploaded to `audio-masters` BEFORE the DB write, so the master was
-- downloadable but invisible to the user's library.
--
-- Same class of drift as 20261005180000_repair_job_and_session_schema.sql.

ALTER TABLE public.masters
    ADD COLUMN IF NOT EXISTS status text;

-- Backfill existing rows so historical masters are not left NULL.
UPDATE public.masters
   SET status = 'completed'
 WHERE status IS NULL;

COMMENT ON COLUMN public.masters.status IS
    'Lifecycle state of the master: completed | error.';