"""Owner-chosen colour + symbol for a project (analysis dataset).

A dataset is the product's "project folder", but until now it had no visual
identity: every project rendered as an identical row of text, so the Office
could not tell two of them apart at a glance.

Two presentation columns, deliberately `varchar` and not a `PgEnum`. The
palette is presentation, it will grow, and extending a Postgres enum costs a
migration every time. The allowed values are enforced in Pydantic
(`ProjectColor` / `ProjectIcon` in `app/routers/analysis.py`), which is also
where the single source of truth for the palette lives; the readers fall back
to the first slot on an unknown value, so a value written by a newer API is a
cosmetic mismatch and never a crash.

Existing rows are backfilled by rotating the palette per owner, ordered by
creation. Leaving them all on the `teal`/`folder` default would make every
pre-existing project look identical on first load — i.e. the feature would
look broken to exactly the users who have the most projects.

Revision ID: b6d3e0f2a915
Revises: d5f91c3a7b28
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b6d3e0f2a915"
down_revision: str | Sequence[str] | None = "d5f91c3a7b28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept in lockstep with PROJECT_COLORS / PROJECT_ICONS in
# `app/routers/analysis.py`. Only used for the one-time backfill below.
_COLORS = "teal,amber,blue,violet,rose,green,cyan,slate"
_ICONS = "folder,flask,atom,microscope,beaker,dna,layers,hexagon"


def upgrade() -> None:
    op.add_column(
        "analysis_datasets",
        sa.Column("color", sa.String(16), nullable=False, server_default="teal"),
    )
    op.add_column(
        "analysis_datasets",
        sa.Column("icon", sa.String(24), nullable=False, server_default="folder"),
    )

    # Rotate the palette per owner so one user's projects are mutually
    # distinct. `- 1` because row_number() is 1-based while the modulo wants a
    # 0-based index; `+ 1` again on the subscript because Postgres arrays are
    # 1-indexed. `mod(...)` rather than the `%` operator: a literal `%` in a
    # raw `op.execute` string is ambiguous with the DBAPI's pyformat
    # placeholder and has to be escaped, which is easy to get wrong.
    op.execute(
        f"""
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (PARTITION BY owner_id ORDER BY created_at, id) - 1 AS rn
            FROM analysis_datasets
        )
        UPDATE analysis_datasets AS d
        SET color = (string_to_array('{_COLORS}', ','))[mod(ranked.rn, 8) + 1],
            icon  = (string_to_array('{_ICONS}', ','))[mod(ranked.rn, 8) + 1]
        FROM ranked
        WHERE ranked.id = d.id
        """
    )


def downgrade() -> None:
    op.drop_column("analysis_datasets", "icon")
    op.drop_column("analysis_datasets", "color")
