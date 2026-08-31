"""Tests for `scripts/import_scimago.py` — the SCImago journal-rank CSV
importer (M6.1).

A 3-row fixture exercises: two ISSNs on one row (one `Journal` row each,
sharing `issn_l`), dash / comma-decimal normalization, a row with no usable
ISSN (skipped), and that a second run upserts in place (no duplicate rows,
no growth).
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models.journal import Journal
from scripts.import_scimago import import_scimago

CSV_TEXT = (
    "Rank;Title;Type;Issn;SJR;SJR Best Quartile;H index;Country\n"
    "1;Journal One;journal;03701573, 18734782;12,345;Q1;100;Netherlands\n"
    "2;Journal Two;journal;0028-0836;8,5;Q2;200;United Kingdom\n"
    "3;Journal Three;journal;-;;-;0;\n"
)


@pytest.fixture()
def csv_path(tmp_path):
    path = tmp_path / "scimagojr.csv"
    path.write_text(CSV_TEXT, encoding="utf-8")
    return str(path)


def _count(db_session) -> int:
    return db_session.execute(
        select(func.count()).select_from(Journal).where(Journal.source == "scimago")
    ).scalar_one()


def test_import_populates_journals_one_row_per_issn(csv_path, db_session):
    counts = import_scimago(csv_path, db_session)

    assert counts == {"rows": 3, "added": 3, "updated": 0, "issns": 3}
    assert _count(db_session) == 3

    # Both ISSNs from row 1 resolve, share issn_l, carry the comma-decimal SJR.
    by_electronic = db_session.execute(
        select(Journal).where(Journal.issn == "18734782")
    ).scalar_one()
    assert by_electronic.title == "Journal One"
    assert by_electronic.issn_l == "03701573"
    assert by_electronic.sjr == 12.345
    assert by_electronic.quartile == "Q1"
    assert by_electronic.h_index == 100

    # Dash-form ISSN normalized to 8 chars, no dash.
    row_two = db_session.execute(
        select(Journal).where(Journal.issn == "00280836")
    ).scalar_one()
    assert row_two.title == "Journal Two"
    assert row_two.country == "United Kingdom"

    # Row 3 had no usable ISSN -> nothing written for it.
    assert db_session.execute(
        select(func.count()).select_from(Journal).where(Journal.title == "Journal Three")
    ).scalar_one() == 0


def test_import_is_idempotent(csv_path, db_session):
    import_scimago(csv_path, db_session)
    first = _count(db_session)
    counts = import_scimago(csv_path, db_session)
    second = _count(db_session)

    assert first == second == 3
    # Second run updated the same rows, added nothing.
    assert counts == {"rows": 3, "added": 0, "updated": 3, "issns": 3}


def test_second_file_tops_up_without_dropping_the_first(tmp_path, db_session):
    first = tmp_path / "a.csv"
    first.write_text(CSV_TEXT, encoding="utf-8")
    second = tmp_path / "b.csv"
    second.write_text(
        "Rank;Title;Type;Issn;SJR;SJR Quartile;H index;Country\n"
        "1;Journal Four;journal;1111-2222;0,4;Q3;10;France\n",
        encoding="utf-8",
    )

    import_scimago(str(first), db_session)
    import_scimago(str(second), db_session)  # default = upsert, no wipe

    assert _count(db_session) == 4  # 3 from a.csv still present + 1 new
    j4 = db_session.execute(
        select(Journal).where(Journal.issn == "11112222")
    ).scalar_one()
    assert j4.title == "Journal Four"
    assert j4.quartile == "Q3"  # parsed from the "SJR Quartile" header


def test_replace_wipes_first(csv_path, tmp_path, db_session):
    import_scimago(csv_path, db_session)
    other = tmp_path / "c.csv"
    other.write_text(
        "Rank;Title;Type;Issn;SJR;SJR Best Quartile;H index;Country\n"
        "1;Only Journal;journal;9999-8888;1,0;Q1;5;Germany\n",
        encoding="utf-8",
    )
    import_scimago(str(other), db_session, replace=True)

    assert _count(db_session) == 1
