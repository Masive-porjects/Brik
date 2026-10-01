"""Guard the SQL migration against the Python model that writes it.

There is no migration runner in this repo: the schema lives in the Supabase
dashboard and this file is the only version-controlled record of it. That makes
drift the real risk, and drift fails *at runtime*, in production, on the first
insert -- PostgREST rejects a column that does not exist, and a status value
outside a CHECK constraint takes the whole insert down with it.

Both failure modes are pure naming agreements, so they can be checked without a
database. That is what this module does: it parses the migration and holds it
against ``JobRecord`` / ``SupabaseJobStore``, so renaming a Pydantic field or
the table name fails here instead of in a deploy.

It deliberately does NOT try to validate the SQL against a real Postgres: no
driver is available in this environment (see docs). Syntax errors still need
`psql` or the Supabase SQL editor.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from audiomind.services.job_store import JobRecord, JobStatus, SupabaseJobStore

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "20260930183000_create_dsp_jobs.sql"
)

# Postgres types this table is allowed to use. Anchoring the regex to a known
# type list is what keeps constraint continuations (``check (...)``) from being
# mistaken for column definitions.
COLUMN_TYPES = (
    "text|integer|bigint|jsonb|timestamptz|uuid|boolean|real|double precision"
)
COLUMN_RE = re.compile(
    rf"^\s{{4}}(?P<name>[a-z_][a-z0-9_]*)\s+(?:{COLUMN_TYPES})\b", re.MULTILINE
)


def _migration_text() -> str:
    assert MIGRATION.exists(), f"missing migration: {MIGRATION}"
    return MIGRATION.read_text(encoding="utf-8")


def _table_block(sql: str, table: str) -> str:
    """Return the ``create table`` body for ``table``, so the parser below only
    ever looks at that table and not at comments or other statements."""
    start = sql.index(f"create table if not exists public.{table} (")
    depth = 0
    for index in range(start, len(sql)):
        if sql[index] == "(":
            depth += 1
        elif sql[index] == ")":
            depth -= 1
            if depth == 0:
                return sql[start:index]
    raise AssertionError(f"unbalanced parentheses in the {table} definition")


def test_table_name_matches_the_store() -> None:
    """A table rename on either side is invisible until a deploy 404s."""
    assert (
        f"create table if not exists public.{SupabaseJobStore.TABLE} ("
        in _migration_text()
    )


def test_every_model_field_has_a_column() -> None:
    """A Pydantic field with no column makes ``insert`` fail on every job.

    This is the drift that cost a production deploy once already: the model
    grew a field and nobody could tell because nothing compared the two.
    """
    columns = set(
        COLUMN_RE.findall(_table_block(_migration_text(), SupabaseJobStore.TABLE))
    )
    missing = sorted(set(JobRecord.model_fields) - columns)
    assert not missing, f"columns missing in SQL: {missing}"


def test_every_column_is_a_model_field() -> None:
    """The reverse drift: a column nothing writes is dead weight, and a typo
    like ``lease_expires`` instead of ``lease_expires_at`` shows up here rather
    than as a silently-NULL lease that never expires."""
    columns = set(
        COLUMN_RE.findall(_table_block(_migration_text(), SupabaseJobStore.TABLE))
    )
    extra = sorted(columns - set(JobRecord.model_fields))
    assert not extra, f"columns not in JobRecord (typo?): {extra}"


def test_status_check_allows_exactly_the_enum() -> None:
    """If the CHECK and the StrEnum disagree, valid jobs are rejected by
    Postgres and the failure looks like an unrelated 500 on submit."""
    sql = _migration_text()
    match = re.search(
        r"status\s+text[^)]*?check\s*\(\s*status\s+in\s*\((?P<values>[^)]*)\)",
        sql,
        re.DOTALL,
    )
    assert match, "no CHECK constraint on dsp_jobs.status"
    allowed = {value.strip().strip("'") for value in match.group("values").split(",")}
    assert allowed == {status.value for status in JobStatus}


def test_progress_check_is_zero_to_hundred() -> None:
    """The model documents progress as 0..100 and the frontend renders it as a
    percentage; a wider column would let a bad write show '140%' in the UI."""
    sql = _migration_text()
    assert re.search(
        r"progress\s+integer[^)]*?check\s*\(\s*progress\s+between\s+0\s+and\s+100",
        sql,
        re.DOTALL,
    ), "no 0..100 CHECK constraint on dsp_jobs.progress"


def test_result_is_jsonb_not_text() -> None:
    """The read path reaches inside ``result`` to re-sign ``r2_key``. As text
    the value round-trips as a string and that lookup silently yields nothing,
    so the client would get no download URL and no error to explain why."""
    assert re.search(r"\n\s{4}result\s+jsonb\b", _migration_text())


def test_lease_is_a_timestamp_not_text() -> None:
    """The lease is compared against now() to detect dead workers. As text the
    comparison is a lexicographic string compare, which is only correct for
    one exact ISO format and silently wrong for anything else."""
    assert re.search(r"\n\s{4}lease_expires_at\s+timestamptz\b", _migration_text())


def test_rls_is_enabled_without_permissive_policies() -> None:
    """Job rows carry R2 keys and analysis payloads. The backend reads them
    with the service_role key (which bypasses RLS) and the browser polls our
    FastAPI endpoint instead of this table, so there should be no policy at
    all. A stray policy here silently opens the table to the anon key."""
    sql = _migration_text()
    assert re.search(r"alter table public\.dsp_jobs enable row level security", sql)
    assert "create policy" not in sql.lower(), "dsp_jobs must not have RLS policies"


def test_migration_is_idempotent() -> None:
    """Re-running it must not explode: the dashboard is the real deploy path
    here, so people WILL paste it twice."""
    assert "create table if not exists" in _migration_text()
    assert "create index if not exists" in _migration_text()


def test_does_not_touch_existing_tables() -> None:
    """This migration is additive. It must not alter, drop or reference the
    tables the rest of the platform already depends on, or a paste into the
    dashboard could take the library down."""
    sql = _migration_text().lower()
    for statement in ("drop table", "drop column", "alter column", "truncate"):
        assert statement not in sql, f"migration must not contain `{statement}`"
    for existing in ("public.tracks", "public.masters", "public.profiles"):
        assert existing not in sql, f"migration must not reference {existing}"


@pytest.mark.parametrize(
    "path",
    sorted(Path(__file__).resolve().parents[3].glob("supabase/migrations/*.sql")),
)
def test_every_migration_declares_a_table(path: Path) -> None:
    """Cheap sanity net so an accidentally empty migration file is caught."""
    assert "create table" in path.read_text(encoding="utf-8").lower()
