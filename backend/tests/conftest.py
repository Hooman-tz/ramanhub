"""Shared pytest fixtures.

DB-backed tests require a reachable Postgres at `DATABASE_URL` (same default
as the app — see `app/config.py`); they're skipped automatically (not
failed) when it isn't reachable, mirroring the pattern already used in
`tests/test_models_smoke.py`.
"""
from __future__ import annotations

import uuid

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

    monkeypatch.setattr("app.processing.cache.upload_bytes", upload_bytes)
    monkeypatch.setattr("app.processing.cache.download_bytes", download_bytes)
    monkeypatch.setattr("app.spectra_io.download_bytes", download_bytes)
    # The fork endpoint copies raw bytes through its own imported names.
    monkeypatch.setattr("app.routers.spectra.upload_bytes", upload_bytes)
    monkeypatch.setattr("app.routers.spectra.download_bytes", download_bytes)
    return store


@pytest.fixture()
def make_raw_file(db_session, fake_s3):
    from app.models.enums import Modality, UploadStatus
    from app.models.raw_file import RawFile

    def _make(owner, content: bytes = b"100 1.0\n200 2.0\n300 5.0\n400 2.0\n500 1.0\n600 3.0\n"):
        key = f"{uuid.uuid4()}.txt"
        fake_s3[(settings.S3_BUCKET_RAW, key)] = content
        raw_file = RawFile(
            owner_id=owner.id,
            modality=Modality.raman,
            storage_bucket=settings.S3_BUCKET_RAW,
            storage_key=key,
            original_filename="spectrum.txt",
            content_hash=str(uuid.uuid4()),
            file_size_bytes=len(content),
            upload_status=UploadStatus.uploaded,
        )
        db_session.add(raw_file)
        db_session.commit()
        db_session.refresh(raw_file)
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
def fclient(db_session):
    """TestClient wired with the Findings/feed/social routers.

    Imports are function-local, matching `app_client` above: keeping router
    imports out of conftest's module scope means a collection-time import
    error in one router doesn't take down every DB-backed test file.
    """
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from app.auth.deps import (
        get_current_full_user,
        get_current_user,
        get_current_user_optional,
    )
    from app.db.session import get_db
    from app.routers import (
        comments,
        export,
        feed,
        findings,
        ledgers,
        spectra,
        users,
        votes,
    )

    test_app = FastAPI()
    for router in (
        spectra.router,
        findings.router,
        feed.router,
        votes.router,
        comments.router,
        users.router,
        export.router,
        ledgers.router,
    ):
        test_app.include_router(router)

    def _override_get_db():
        yield db_session

    current = {"user": None}

    def _override_get_current_user():
        if current["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current["user"]

    def _override_full_user():
        user = _override_get_current_user()
        if getattr(user, "is_guest", False):
            raise HTTPException(status_code=403, detail="Full account required")
        return user

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_current_user] = _override_get_current_user
    test_app.dependency_overrides[get_current_full_user] = _override_full_user
    test_app.dependency_overrides[get_current_user_optional] = lambda: current["user"]

    client = TestClient(test_app)
    client.set_current_user = lambda user: current.__setitem__("user", user)
    return client
