"""Trigram search: one generated `search_text` per table, one GIN index each.

Every text search in the app was `ILIKE '%q%'`. No btree index can serve a
leading wildcard, so each of those was a sequential scan — including the
reference-library browse that fires while you type, over an 8.5k-row corpus.

`pg_trgm` fixes both halves of that at once: a GIN trigram index makes the scan
an index lookup, and `word_similarity()` gives a real relevance score, so
"calcite" can outrank "Sodium calcitrate" and "calcyte" can still find Calcite.

One blob column per table rather than one index per column. Per-column indexing
needed ~9 GIN indexes and still could not reach the JSONB columns
(`common_names`, `tags`, `research_interests`): a trigram index cannot be built
over `jsonb_array_elements_text()`, because set-returning functions are
forbidden in index expressions and generated columns alike. Flattening with
`#>> '{}'` (an IMMUTABLE `jsonb_extract_path_text`) sidesteps that. The
expressions live in `app/models/search_sql.py` and are copied here verbatim,
matching this tree's habit of keeping revisions self-contained. Postgres stores
the expression it was given, so editing that module does not alter an existing
column — a change there needs a new migration that drops and re-adds.

`ADD COLUMN ... GENERATED ALWAYS AS ... STORED` rewrites the table under an
ACCESS EXCLUSIVE lock, and computes every existing row on the way through, so
there is no backfill step. At current row counts (thousands) that is
sub-second; at ~1M rows this becomes a maintenance window.

Deliberately NOT `CREATE INDEX CONCURRENTLY`: it cannot run inside a
transaction block, and Alembic wraps migrations in one. If these tables ever
grow enough to need it, use `op.get_context().autocommit_block()`.

`downgrade()` leaves `pg_trgm` installed. Dropping an extension that a later
migration might depend on is a footgun, and the initial schema's decision not
to drop `pgcrypto` is the precedent.

Also adds the GIN index `/v1/feed`'s `tag` filter has always wanted: that
filter is JSONB containment (`@>`) on `findings.tags` and had no index at all.

Revision ID: c3f7a2b9d4e1
Revises: a4e1f7b3c8d2
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3f7a2b9d4e1"
down_revision: str | Sequence[str] | None = "a4e1f7b3c8d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# --- copied from app/models/search_sql.py; see this module's docstring -------
def _json_words(column: str) -> str:
    return f"regexp_replace({column} #>> '{{}}'::text[], '[][\",]', ' ', 'g')"


REFERENCE_SEARCH_SQL = (
    "coalesce(compound_name, '') || ' ' || "
    "coalesce(mineral_name, '') || ' ' || "
    "coalesce(chemical_formula, '') || ' ' || "
    "coalesce(cas_number, '') || ' ' || "
    f"coalesce({_json_words('common_names')}, '')"
)
SPECTRUM_SEARCH_SQL = (
    "coalesce(title, '') || ' ' || "
    "coalesce(material_type, '') || ' ' || "
    "coalesce(accession, '') || ' ' || "
    "left(coalesce(description, ''), 600)"
)
FINDING_SEARCH_SQL = (
    "coalesce(title, '') || ' ' || "
    "coalesce(accession, '') || ' ' || "
    f"coalesce({_json_words('tags')}, '') || ' ' || "
    "left(coalesce(abstract_md, ''), 600)"
)
USER_SEARCH_SQL = (
    "coalesce(display_name, '') || ' ' || "
    "coalesce(profile_handle, '') || ' ' || "
    "coalesce(orcid_name, '') || ' ' || "
    "coalesce(affiliation, '') || ' ' || "
    f"coalesce({_json_words('research_interests')}, '')"
)

_SEARCH_TEXT = {
    "reference_entries": REFERENCE_SEARCH_SQL,
    "spectra": SPECTRUM_SEARCH_SQL,
    "findings": FINDING_SEARCH_SQL,
    "users": USER_SEARCH_SQL,
}


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    for table, expression in _SEARCH_TEXT.items():
        op.add_column(
            table,
            sa.Column(
                "search_text",
                sa.Text(),
                sa.Computed(expression, persisted=True),
                nullable=True,
            ),
        )
        op.create_index(
            f"ix_{table}_search_trgm",
            table,
            ["search_text"],
            postgresql_using="gin",
            postgresql_ops={"search_text": "gin_trgm_ops"},
        )

    op.create_index(
        "ix_findings_tags_gin",
        "findings",
        ["tags"],
        postgresql_using="gin",
        postgresql_ops={"tags": "jsonb_path_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_findings_tags_gin", table_name="findings")
    for table in _SEARCH_TEXT:
        op.drop_index(f"ix_{table}_search_trgm", table_name=table)
        op.drop_column(table, "search_text")
