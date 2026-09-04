"""Shared pytest fixtures.

DB-backed tests require a reachable Postgres at `DATABASE_URL` (same default
as the app — see `app/config.py`); they're skipped automatically (not
failed) when it isn't reachable, mirroring the pattern already used in
`tests/test_models_smoke.py`.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from hashlib import sha256

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 - registers every model on Base.metadata, so

# `create_all` below builds the full schema even when running a single test
# file that doesn't import any model itself (without this, which tables
# exist depends on which test modules pytest happened to collect).
from app.config import settings
from app.db.base import Base
from tests._db_url import get_test_database_url

DB_URL = get_test_database_url()


def _seed_registry(engine) -> None:
    from app.seed.seed_data import (
        seed_ledger_step_definitions,
        seed_licenses,
        seed_metadata_field_definitions,
    )

    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        seed_licenses(session)
        seed_metadata_field_definitions(session)
        seed_ledger_step_definitions(session)
        session.commit()
    finally:
        session.close()


@pytest.fixture(scope="session")
def engine():
    if DB_URL is None:
        pytest.skip("No reachable Postgres DATABASE_URL")
    eng = create_engine(DB_URL)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    Base.metadata.create_all(eng)
    _seed_registry(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    """A Session bound to a per-test transaction that's rolled back at
    teardown, so tests never see each other's writes (but do see the
    session-scoped seed data committed in `engine`)."""
    connection = engine.connect()
    transaction = connection.begin()
    TestingSessionLocal = sessionmaker(bind=connection, autoflush=False, autocommit=False, future=True)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture()
def make_user(db_session):
    from app.models.user import User

    def _make(email: str | None = None) -> User:
        user = User(
            google_sub=str(uuid.uuid4()),
            email=email or f"{uuid.uuid4()}@example.com",
            display_name="Test User",
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _make


@pytest.fixture()
def fake_s3(monkeypatch):
    """In-memory stand-in for `app.storage.s3_client`, so tests don't need a
    real MinIO/S3 endpoint. Patches the names as imported into every module
    that calls them directly: `app.processing.cache` (processed-output
    cache reads/writes) and `app.spectra_io` (raw-spectrum loading) — a
    plain `monkeypatch.setattr("app.storage.s3_client.download_bytes", ...)`
    would NOT be enough, since both modules did `from ... import
    download_bytes`, which binds their own local name to the original
    function object rather than looking it up on the module each call."""
    store: dict[tuple[str, str], bytes] = {}

    def upload_bytes(bucket, key, data, content_type=None):
        store[(bucket, key)] = data

    def download_bytes(bucket, key):
        return store[(bucket, key)]

    def delete_object(bucket, key):
        store.pop((bucket, key), None)

    monkeypatch.setattr("app.processing.cache.upload_bytes", upload_bytes)
    monkeypatch.setattr("app.processing.cache.download_bytes", download_bytes)
    monkeypatch.setattr("app.spectra_io.download_bytes", download_bytes)
    monkeypatch.setattr("app.analysis.engine.download_bytes", download_bytes)
    # The fork endpoint copies raw bytes through its own imported names.
    monkeypatch.setattr("app.routers.spectra.upload_bytes", upload_bytes)
    monkeypatch.setattr("app.routers.spectra.download_bytes", download_bytes)
    # The delete endpoint removes raw / processed objects best-effort.
    monkeypatch.setattr("app.routers.spectra.delete_object", delete_object)
    return store


@pytest.fixture()
def make_raw_file(db_session, fake_s3):
    from app.models.enums import IngestionStatus, Modality, UploadStatus
    from app.models.ingestion_job import IngestionJob
    from app.models.raw_file import RawFile

    def _make(
        owner,
        content: bytes = b"100 1.0\n200 2.0\n300 5.0\n400 2.0\n500 1.0\n600 3.0\n",
        laser_wavelength_nm: float = 785.0,
    ):
        key = f"{uuid.uuid4()}.txt"
        fake_s3[(settings.S3_BUCKET_RAW, key)] = content
        raw_file = RawFile(
            owner_id=owner.id,
            modality=Modality.raman,
            storage_bucket=settings.S3_BUCKET_RAW,
            storage_key=key,
            original_filename="spectrum.txt",
            content_hash=sha256(content).hexdigest(),
            storage_version=f"sha256:{sha256(content).hexdigest()}",
            file_size_bytes=len(content),
            upload_status=UploadStatus.parsed,
            checksum_verified_at=datetime.now(UTC),
        )
        db_session.add(raw_file)
        db_session.commit()
        db_session.refresh(raw_file)
        job = IngestionJob(
            raw_file_id=raw_file.id,
            status=IngestionStatus.succeeded,
            parser_used="test",
            parser_version="test-1",
            parser_confidence=1.0,
            canonicalization_version="raman-1",
            extracted_metadata_raw={
                "modality": "raman",
                "instrument_vendor": "Test Vendor",
                "laser_wavelength_nm": laser_wavelength_nm,
                "spectral_range_cm1": "100-2000",
                "sample_description": "Test sample",
            },
            extracted_metadata_confirmed={
                "modality": "raman",
                "instrument_vendor": "Test Vendor",
                "laser_wavelength_nm": laser_wavelength_nm,
                "spectral_range_cm1": "100-2000",
                "sample_description": "Test sample",
            },
            sanity_check_flags={},
            confirmed_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
        )
        db_session.add(job)
        db_session.commit()
        return raw_file

    return _make


@pytest.fixture()
def app_client(db_session):
    """A FastAPI TestClient wired with only this module's routers (spectra,
    ledgers, routines), `get_db` overridden to the test's `db_session`, and
    `get_current_user`/`get_current_user_optional` overridden to whatever
    user `client.set_current_user(...)` last set (`None` = anonymous)."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from app.auth.deps import get_current_user, get_current_user_optional
    from app.db.session import get_db
    from app.routers import ledgers, routines, spectra

    test_app = FastAPI()
    test_app.include_router(spectra.router)
    test_app.include_router(ledgers.router)
    test_app.include_router(routines.router)

    def _override_get_db():
        yield db_session

    current = {"user": None}

    def _override_get_current_user():
        if current["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current["user"]

    def _override_get_current_user_optional():
        return current["user"]

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_current_user] = _override_get_current_user
    test_app.dependency_overrides[get_current_user_optional] = _override_get_current_user_optional

    client = TestClient(test_app)
    client.set_current_user = lambda user: current.__setitem__("user", user)
    return client


@pytest.fixture()
def lab_client(db_session):
    """Like `app_client`, but with the analysis and findings routers mounted
    too.

    Forking data crosses three routers — `/spectra/{id}/fork`,
    `/analysis/datasets/...`, `/v1/findings/{id}/fork-data` — so exercising it
    end to end needs all of them in one app. Kept separate from `app_client`
    rather than widening it, so the existing suite keeps testing the processing
    module in isolation.

    Also overrides `get_current_full_user`, which publishing depends on, and
    honours `User.is_guest` so guest-rejection paths stay testable.
    """
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from app.auth.deps import (
        get_current_full_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.db.session import get_db
    from app.routers import analysis, findings, ledgers, routines, spectra

    test_app = FastAPI()
    for router in (spectra.router, ledgers.router, routines.router, analysis.router, findings.router):
        test_app.include_router(router)

    def _override_get_db():
        yield db_session

    current = {"user": None}

    def _override_get_current_user():
        if current["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current["user"]

    def _override_get_current_full_user():
        user = _override_get_current_user()
        if getattr(user, "is_guest", False):
            raise HTTPException(status_code=403, detail="Sign in to do this")
        return user

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_current_user] = _override_get_current_user
    test_app.dependency_overrides[get_current_full_user] = _override_get_current_full_user
    test_app.dependency_overrides[get_current_user_optional] = lambda: current["user"]

    client = TestClient(test_app)
    client.set_current_user = lambda user: current.__setitem__("user", user)
    return client
