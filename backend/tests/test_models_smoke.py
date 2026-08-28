"""Smoke tests for the ORM model layer.

Postgres-native types (UUID, native ENUM, JSONB, gen_random_uuid()) make
sqlite-in-memory an unsafe stand-in here, so these tests are pragmatic:

- Always run (no DB required): assert every model imports cleanly, is
  registered on `Base.metadata`, and exposes the expected columns/types via
  SQLAlchemy inspection.
- Only if `DATABASE_URL` points at a reachable Postgres: actually issue
  `Base.metadata.create_all()` / `drop_all()` against it as a real
  round-trip check. Skipped (not failed) when no DB is reachable, e.g. in CI
  without a Postgres service.
"""
import uuid

import pytest
from sqlalchemy import inspect

from app import models
from app.db.base import Base

ALL_MODEL_CLASSES = [
    models.User,
    models.License,
    models.RawFile,
    models.IngestionJob,
    models.VendorParseCache,
    models.MetadataFieldDefinition,
    models.LedgerStepDefinition,
    models.Spectrum,
    models.ProcessingLedger,
    models.ProcessingRoutine,
    models.ProcessedCache,
]


def test_all_models_registered_on_metadata():
    table_names = set(Base.metadata.tables.keys())
    expected = {
        "users",
        "licenses",
        "raw_files",
        "ingestion_jobs",
        "vendor_parse_cache",
        "metadata_field_definitions",
        "ledger_step_definitions",
        "spectra",
        "processing_ledgers",
        "processing_routines",
        "processed_cache",
    }
    assert expected <= table_names


@pytest.mark.parametrize("model_cls", ALL_MODEL_CLASSES)
def test_model_has_mapped_table(model_cls):
    mapper = inspect(model_cls)
    assert mapper.local_table is not None
    assert len(mapper.columns) > 0


def test_user_expected_columns():
    columns = {c.name for c in inspect(models.User).columns}
    assert columns == {
        "id",
        "google_sub",
        "email",
        "display_name",
        "avatar_url",
        "orcid_id",
        "orcid_verified_at",
        "orcid_name",
        "profile_handle",
        "bio",
        "affiliation",
        "research_interests",
        "is_profile_public",
        "is_moderator",
        "deleted_at",
        "is_active",
        "is_guest",
        "created_at",
        "updated_at",
    }


def test_raw_file_foreign_keys_point_at_users():
    fk_targets = {
        fk.target_fullname for col in models.RawFile.__table__.columns for fk in col.foreign_keys
    }
    assert "users.id" in fk_targets


def test_spectrum_foreign_keys():
    fk_targets = {
        fk.target_fullname for col in models.Spectrum.__table__.columns for fk in col.foreign_keys
    }
    assert {"raw_files.id", "users.id", "processing_ledgers.id", "licenses.id"} <= fk_targets


def test_unique_constraints_present():
    metadata_field_uniques = {
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in models.MetadataFieldDefinition.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("field_key", "modality") in metadata_field_uniques

    ledger_step_uniques = {
        tuple(sorted(c.name for c in constraint.columns))
        for constraint in models.LedgerStepDefinition.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("algorithm_version", "modality", "step_type") in ledger_step_uniques


def test_indexed_columns_present():
    indexed_columns = {
        "raw_files": "content_hash",
        "vendor_parse_cache": "header_hash",
        "processing_ledgers": "ledger_hash",
        "processed_cache": "cache_key",
    }
    for table_name, column_name in indexed_columns.items():
        table = Base.metadata.tables[table_name]
        col = table.columns[column_name]
        assert col.index or col.unique, f"{table_name}.{column_name} should be indexed or unique"


def _live_database_url() -> str | None:
    """Return a connectable *test* database URL (a `<dbname>_test` sibling of
    the dev DATABASE_URL — see tests/_db_url.py), or None if no Postgres is
    reachable at all. Never points at the real dev database, since this test
    does a full create_all/drop_all round-trip."""
    from tests._db_url import get_test_database_url

    return get_test_database_url()


@pytest.mark.skipif(
    _live_database_url() is None,
    reason="No reachable DATABASE_URL — skipping live create_all/drop_all round-trip",
)
def test_create_all_round_trip_against_live_postgres():
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    url = _live_database_url()
    engine = create_engine(url)

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        license_row = models.License(id="TEST-LICENSE", name="Test", url="https://example.com")
        user_row = models.User(google_sub=str(uuid.uuid4()), email="test@example.com")
        session.add_all([license_row, user_row])
        session.commit()

        assert session.get(models.License, "TEST-LICENSE") is not None
        assert session.query(models.User).filter_by(email="test@example.com").one() is not None

        # Clean up just the two rows this test inserted, rather than
        # `Base.metadata.drop_all(engine)`: this points at the same shared
        # `<dbname>_test` physical database as conftest.py's session-scoped
        # `engine` fixture (see tests/_db_url.py). Dropping every table here
        # was wiping them out from under every DB-backed test file that
        # happens to run later in the same pytest session, causing spurious
        # `UndefinedTable` failures unrelated to those files' own code.
        session.delete(license_row)
        session.delete(user_row)
        session.commit()
