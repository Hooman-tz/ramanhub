"""Integration tests for the ingestion API: POST /raw-files, GET/PATCH
/ingestion-jobs/{id}.

Same pragmatic DB-availability pattern as tests/test_auth.py and
tests/test_models_smoke.py: these tests need Postgres-native types (UUID,
JSONB, native ENUM) that don't work against sqlite, so they run only when
DATABASE_URL points at a reachable Postgres and are skipped otherwise.

Storage (`upload_bytes` / `download_bytes`) is mocked with an in-memory dict
— no real S3/MinIO is required. Uploaded content is a real Ocean Insight
fixture, so the deterministic parser handles it end-to-end without needing
to mock the Anthropic client.
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.auth.jwt import encode_session_token
from app.db.base import Base
from app.db.session import get_db
from app.ingestion import jobs as jobs_module
from app.models.enums import FieldDataType, IngestionStatus, Modality
from app.models.field_registry import MetadataFieldDefinition
from app.models.ingestion_job import IngestionJob
from app.models.raw_file import RawFile
from app.models.user import User
from app.models.vendor_parse_cache import VendorParseCache
from app.routers import ingestion_jobs as ingestion_jobs_router
from app.routers import raw_files as raw_files_router
from tests._db_url import get_test_database_url

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "headers" / "ocean_insight_sample.txt"
)

# Uses a dedicated `<dbname>_test` database, never the dev DATABASE_URL —
# see tests/_db_url.py.
DB_URL = get_test_database_url()
requires_db = pytest.mark.skipif(DB_URL is None, reason="No reachable DATABASE_URL")


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(DB_URL)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    Base.metadata.create_all(eng)
    yield eng
    # Deliberately NOT dropping tables here (used to call
    # `Base.metadata.drop_all(eng)`) — see the identical note in
    # tests/test_auth.py's `engine` fixture: this points at the same
    # physical test DB as conftest.py's session-scoped `engine` fixture, and
    # dropping tables at this module's teardown was wiping them out from
    # under every DB-backed test file that runs later in the same pytest
    # session, causing spurious `UndefinedTable` failures elsewhere.
    # `create_all` above is idempotent; conftest.py's session fixture still
    # drops everything once, at the very end of the whole suite.


@pytest.fixture()
def db_session(engine):
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.query(IngestionJob).delete()
        session.query(RawFile).delete()
        session.query(VendorParseCache).delete()
        session.query(MetadataFieldDefinition).delete()
        session.query(User).delete()
        session.commit()
        session.close()


@pytest.fixture()
def fake_storage(engine):
    """In-memory object store standing in for S3/MinIO. Patches both the
    router's upload path and the background job's download path, and points
    the background job's DB session factory at the same test engine."""
    store: dict[tuple[str, str], bytes] = {}

    def _upload(bucket, key, data, content_type=None):
        store[(bucket, key)] = data

    def _download(bucket, key):
        return store[(bucket, key)]

    test_session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    with (
        patch.object(raw_files_router, "upload_bytes", side_effect=_upload),
        patch.object(jobs_module, "download_bytes", side_effect=_download),
        patch.object(jobs_module, "SessionLocal", test_session_factory),
    ):
        yield store


@pytest.fixture()
def test_app(db_session):
    app = FastAPI()
    app.include_router(raw_files_router.router)
    app.include_router(ingestion_jobs_router.router)

    def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    return app


def _client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver")


def _make_user(db_session, google_sub: str, email: str) -> User:
    user = User(google_sub=google_sub, email=email, display_name="Test User")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


async def _upload_ocean_insight_file(test_app, user):
    token = encode_session_token(user)
    content = FIXTURE_PATH.read_bytes()
    async with _client(test_app) as client:
        client.cookies.set("session", token)
        resp = await client.post(
            "/raw-files",
            files={"file": ("sample.txt", content, "text/plain")},
        )
    return resp


@requires_db
def test_upload_creates_pending_job_then_succeeds(test_app, db_session, fake_storage):
    user = _make_user(db_session, "sub-upload-1", "upload1@example.com")

    resp = run_async(_upload_ocean_insight_file(test_app, user))
    assert resp.status_code == 202
    body = resp.json()
    assert "raw_file_id" in body
    assert "ingestion_job_id" in body

    # By the time the ASGI response has been returned, the BackgroundTask
    # (run via Starlette's background-task mechanism) has already executed.
    db_session.expire_all()
    job = db_session.get(IngestionJob, uuid.UUID(body["ingestion_job_id"]))
    assert job is not None
    assert job.status == IngestionStatus.succeeded
    assert job.parser_used == "ocean_insight"
    assert job.extracted_metadata_raw is not None
    assert job.extracted_metadata_raw["instrument_vendor"] == "Ocean Insight"


@requires_db
def test_upload_rejects_garbage_content(test_app, db_session, fake_storage):
    user = _make_user(db_session, "sub-upload-2", "upload2@example.com")
    token = encode_session_token(user)

    async def _run():
        async with _client(test_app) as client:
            client.cookies.set("session", token)
            resp = await client.post(
                "/raw-files",
                files={
                    "file": (
                        "garbage.bin",
                        b"\x00\x01\x02\x03\x04\x05" * 20,
                        "application/octet-stream",
                    )
                },
            )
        return resp

    resp = run_async(_run())
    assert resp.status_code == 400


@requires_db
def test_confirm_metadata_writes_confirmed_field_and_reruns_sanity_check(
    test_app, db_session, fake_storage
):
    db_session.add(
        MetadataFieldDefinition(
            modality=Modality.raman,
            field_key="laser_wavelength_nm",
            data_type=FieldDataType.number,
            required=False,
            allowed_values=[532, 633, 785, 1064],
        )
    )
    db_session.commit()

    user = _make_user(db_session, "sub-confirm-1", "confirm1@example.com")
    upload_resp = run_async(_upload_ocean_insight_file(test_app, user))
    job_id = upload_resp.json()["ingestion_job_id"]
    token = encode_session_token(user)

    async def _run():
        async with _client(test_app) as client:
            client.cookies.set("session", token)
            resp = await client.patch(
                f"/ingestion-jobs/{job_id}",
                json={
                    "metadata": {
                        "modality": "raman",
                        "instrument_vendor": "Ocean Insight",
                        "integration_time_ms": 100.0,
                        "laser_wavelength_nm": 660.0,  # not in the allowed set -> flagged
                    }
                },
            )
        return resp

    resp = run_async(_run())
    assert resp.status_code == 200
    body = resp.json()
    assert body["extracted_metadata_confirmed"]["laser_wavelength_nm"] == 660.0
    assert body["confirmed_at"] is not None
    assert "laser_wavelength_nm" in (body["sanity_check_flags"] or {})


@requires_db
def test_confirm_metadata_rejects_unknown_fields(test_app, db_session, fake_storage):
    user = _make_user(db_session, "sub-confirm-2", "confirm2@example.com")
    upload_resp = run_async(_upload_ocean_insight_file(test_app, user))
    job_id = upload_resp.json()["ingestion_job_id"]
    token = encode_session_token(user)

    async def _run():
        async with _client(test_app) as client:
            client.cookies.set("session", token)
            resp = await client.patch(
                f"/ingestion-jobs/{job_id}",
                json={"metadata": {"modality": "raman", "sneaky_nested": {"a": 1}}},
            )
        return resp

    resp = run_async(_run())
    assert resp.status_code == 422


@requires_db
def test_second_user_cannot_read_or_patch_another_users_job(test_app, db_session, fake_storage):
    owner = _make_user(db_session, "sub-owner-1", "owner1@example.com")
    other = _make_user(db_session, "sub-other-1", "other1@example.com")

    upload_resp = run_async(_upload_ocean_insight_file(test_app, owner))
    job_id = upload_resp.json()["ingestion_job_id"]
    other_token = encode_session_token(other)

    async def _run():
        async with _client(test_app) as client:
            client.cookies.set("session", other_token)
            get_resp = await client.get(f"/ingestion-jobs/{job_id}")
            patch_resp = await client.patch(
                f"/ingestion-jobs/{job_id}",
                json={"metadata": {"modality": "raman"}},
            )
        return get_resp, patch_resp

    get_resp, patch_resp = run_async(_run())
    assert get_resp.status_code == 404
    assert patch_resp.status_code == 404


@requires_db
def test_unauthenticated_upload_requires_auth(test_app, db_session, fake_storage):
    async def _run():
        async with _client(test_app) as client:
            resp = await client.post(
                "/raw-files",
                files={"file": ("sample.txt", b"hello world", "text/plain")},
            )
        return resp

    resp = run_async(_run())
    assert resp.status_code == 401
