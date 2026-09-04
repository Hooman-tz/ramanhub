"""Human-quotable public identifiers for citable records.

A UUID is the right primary key and the wrong thing to print in a paper.
`RH-S-000042` can be read aloud, typed from a printed figure caption, and
searched for — which is the whole job of an accession number in every
existing scientific data repository (GenBank's `MN908947`, PDB's `6VXX`,
Zenodo's record IDs). UUIDs stay the primary key and the foreign-key target;
accessions are a second, stable, *public* handle.

Backed by a Postgres sequence rather than `count(*) + 1`, because the latter
races under concurrent inserts and reuses numbers after a delete — and a
citable identifier that ever points at two different records is worse than
no identifier.

Sequences are deliberately NOT transactional: a rolled-back insert burns its
number. That's correct here. A gap in the accession series is harmless; a
reused accession would break every citation that already quoted it.
"""
from __future__ import annotations

from sqlalchemy import Sequence, text
from sqlalchemy.orm import Session

from app.db.base import Base

# One sequence per record type, so spectra and findings number
# independently — RH-S-000001 and RH-F-000001 can coexist.
#
# Bound to Base.metadata so `create_all` emits them. Production gets these
# from the Alembic migration, but the test harness builds its schema with
# `create_all` alone (see tests/conftest.py) — without the metadata binding,
# every accession-assigning insert would fail there with "relation
# spectrum_accession_seq does not exist".
SPECTRUM_ACCESSION_SEQ = Sequence("spectrum_accession_seq", start=1, metadata=Base.metadata)
FINDING_ACCESSION_SEQ = Sequence("finding_accession_seq", start=1, metadata=Base.metadata)
DATASET_ACCESSION_SEQ = Sequence("dataset_accession_seq", start=1, metadata=Base.metadata)

PREFIX = "RH"
SPECTRUM_KIND = "S"
FINDING_KIND = "F"
DATASET_KIND = "D"

# Zero-padding width. Six digits keeps identifiers visually uniform up to a
# million records; past that they simply get longer rather than wrapping.
_WIDTH = 6


def format_accession(kind: str, number: int) -> str:
    return f"{PREFIX}-{kind}-{number:0{_WIDTH}d}"


# A sequence name can't be supplied as a bind parameter — nextval() takes a
# regclass, so the identifier has to appear literally in the statement. The
# statements are therefore built once here, from constants, and looked up by
# key: no caller-supplied string ever reaches SQL text. (Module 5: "use an
# ORM with parameterized queries, never hand-built SQL strings".)
_NEXTVAL_STATEMENTS = {
    SPECTRUM_KIND: text("SELECT nextval('spectrum_accession_seq')"),
    FINDING_KIND: text("SELECT nextval('finding_accession_seq')"),
    DATASET_KIND: text("SELECT nextval('dataset_accession_seq')"),
}


def next_accession(db: Session, kind: str) -> str:
    """Reserve and format the next accession for `kind`.

    Call this at INSERT time only. Each call consumes a number.
    """
    try:
        statement = _NEXTVAL_STATEMENTS[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown accession kind: {kind!r}") from exc
    return format_accession(kind, int(db.execute(statement).scalar_one()))


def next_spectrum_accession(db: Session) -> str:
    return next_accession(db, SPECTRUM_KIND)


def next_finding_accession(db: Session) -> str:
    return next_accession(db, FINDING_KIND)


def next_dataset_accession(db: Session) -> str:
    return next_accession(db, DATASET_KIND)
