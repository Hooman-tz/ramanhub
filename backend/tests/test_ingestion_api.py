"""Integration tests for the ingestion API: POST /raw-files, GET/PATCH
/ingestion-jobs/{id}.

Same pragmatic DB-availability pattern as tests/test_auth.py and
tests/test_models_smoke.py: these tests need Postgres-native types (UUID,
JSONB, native ENUM) that don't work against sqlite, so they run only when
DATABASE_URL points at a reachable Postgres and are skipped otherwise.

Storage (`upload_bytes` / `download_bytes`) is mocked with an in-memory dict
— no real S3/MinIO is required. Uploaded content is a real Ocean Insight
fixture, so the deterministic parser handles it end-to-end without needing
to mock the LLM client.
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

from app import llm as llm_module
from app import spectra_io
from app.auth.jwt import encode_session_token
from app.db.base import Base
from app.db.session import get_db
from app.ingestion import jobs as jobs_module
from app.models.analysis import AnalysisDataset, AnalysisDatasetSpectrum
from app.models.enums import FieldDataType, IngestionStatus, Modality
from app.models.field_registry import MetadataFieldDefinition
from app.models.file_layout_cache import FileLayoutCache
from app.models.ingestion_job import IngestionJob
from app.models.raw_file import RawFile
from app.models.spectrum import Spectrum
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
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
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
        # The confirm endpoint now creates a private draft Spectrum that
        # references raw_files.id; clear it before raw_files or the DELETE
        # trips spectra_raw_file_id_fkey and poisons every later test.
        session.query(Spectrum).delete()
        # A multi-spectrum upload also creates a dataset grouping its drafts;
        # clear the membership rows and the dataset before users, or the
        # DELETE trips analysis_datasets_owner_id_fkey.
        session.query(AnalysisDatasetSpectrum).delete()
        session.query(AnalysisDataset).delete()
        session.query(RawFile).delete()
        session.query(VendorParseCache).delete()
        session.query(FileLayoutCache).delete()
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
        # The layout-declaration endpoint re-reads the bytes to check the
        # owner's answer against them.
        patch.object(ingestion_jobs_router, "download_bytes", side_effect=_download),
        # Reading a spectrum's own trace back out of the raw object.
        patch.object(spectra_io, "download_bytes", side_effect=_download),
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
def test_upload_creates_pending_job_then_worker_succeeds(test_app, db_session, fake_storage):
    user = _make_user(db_session, "sub-upload-1", "upload1@example.com")

    resp = run_async(_upload_ocean_insight_file(test_app, user))
    assert resp.status_code == 202
    body = resp.json()
    assert "raw_file_id" in body
    assert "ingestion_job_id" in body

    db_session.expire_all()
    job = db_session.get(IngestionJob, uuid.UUID(body["ingestion_job_id"]))
    assert job is not None
    assert job.status == IngestionStatus.pending

    # The API does not parse request-bound uploads. A durable worker claims
    # and runs this persisted job independently.
    jobs_module.run_ingestion_job(job.id)
    db_session.expire_all()
    job = db_session.get(IngestionJob, job.id)
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
    jobs_module.run_ingestion_job(uuid.UUID(job_id))
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
    assert body["draft_spectrum_id"] is not None

    # Confirming a durable job is safe to repeat: it returns the same draft
    # instead of creating another private spectrum.
    repeat = run_async(_run())
    assert repeat.status_code == 200
    assert repeat.json()["draft_spectrum_id"] == body["draft_spectrum_id"]


@requires_db
def test_confirm_metadata_rejects_unknown_fields(test_app, db_session, fake_storage):
    user = _make_user(db_session, "sub-confirm-2", "confirm2@example.com")
    upload_resp = run_async(_upload_ocean_insight_file(test_app, user))
    job_id = upload_resp.json()["ingestion_job_id"]
    jobs_module.run_ingestion_job(uuid.UUID(job_id))
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


@requires_db
def test_direct_duplicate_upload_reuses_private_raw_file_and_job(test_app, db_session, fake_storage):
    user = _make_user(db_session, "sub-dedupe-1", "dedupe@example.com")

    first = run_async(_upload_ocean_insight_file(test_app, user))
    second = run_async(_upload_ocean_insight_file(test_app, user))

    assert first.status_code == second.status_code == 202
    assert second.json()["deduplicated"] is True
    assert second.json()["raw_file_id"] == first.json()["raw_file_id"]
    assert second.json()["ingestion_job_id"] == first.json()["ingestion_job_id"]


# ---------------------------------------------------------------------------
# Multi-spectrum files
#
# A Raman export routinely holds more than one spectrum. These cover the whole
# path: detect the layout, make one draft per trace, group them, and — the
# regression that matters most — keep each draft reading its OWN column.
# ---------------------------------------------------------------------------


def _column_major_bytes(traces: int = 3, points: int = 30) -> bytes:
    header = "Wavenumber\t" + "\t".join(f"sample_{n}" for n in range(traces))
    lines = [header]
    for index in range(points):
        row = [f"{100 + index * 0.5:.4f}"]
        row += [f"{(n + 1) * 1000 + index:.3f}" for n in range(traces)]
        lines.append("\t".join(row))
    return "\n".join(lines).encode()


def _undetectable_bytes(rows: int = 40) -> bytes:
    """A file every deterministic rung declines: no column or row is monotonic
    (so ranking has no axis to propose) and one column is text (so the
    heuristic bails on a mixed export). Row-major files used to serve this
    purpose, but ranking resolves those now.
    """
    return "\n".join(
        ",".join(
            "tag" if column == 1 else str((index * 7 + column * 13) % 23)
            for column in range(4)
        )
        for index in range(rows)
    ).encode()


def _row_major_bytes(traces: int = 3, points: int = 30) -> bytes:
    axis = ["wavenumber"] + [f"{100 + index * 0.5:.4f}" for index in range(points)]
    lines = [",".join(axis)]
    for n in range(traces):
        lines.append(
            ",".join(
                [f"sample_{n}"] + [f"{(n + 1) * 1000 + index:.3f}" for index in range(points)]
            )
        )
    return "\n".join(lines).encode()


async def _upload_bytes(test_app, user, content: bytes, filename: str):
    token = encode_session_token(user)
    async with _client(test_app) as client:
        client.cookies.set("session", token)
        return await client.post(
            "/raw-files", files={"file": (filename, content, "text/plain")}
        )


def _confirm(test_app, user, job_id: str):
    token = encode_session_token(user)

    async def _run():
        async with _client(test_app) as client:
            client.cookies.set("session", token)
            return await client.patch(
                f"/ingestion-jobs/{job_id}",
                json={"metadata": {"modality": "raman", "instrument_vendor": "Test"}},
            )

    return run_async(_run())


def _ingest(test_app, db_session, user, content: bytes, filename: str, *, llm: bool = True) -> str:
    resp = run_async(_upload_bytes(test_app, user, content, filename))
    assert resp.status_code == 202, resp.text
    job_id = resp.json()["ingestion_job_id"]
    if llm:
        jobs_module.run_ingestion_job(uuid.UUID(job_id))
    else:
        # No key configured => `llm_configured()` is False and the model rungs
        # are skipped, which is also how a real deployment behaves without
        # OPENROUTER_API_KEY. Keeps these tests off the network.
        with patch.object(llm_module.settings, "OPENROUTER_API_KEY", ""):
            jobs_module.run_ingestion_job(uuid.UUID(job_id))
    db_session.expire_all()
    return job_id


@requires_db
def test_a_multi_spectrum_file_becomes_one_draft_per_trace(test_app, db_session, fake_storage):
    user = _make_user(db_session, "sub-multi-1", "multi1@example.com")
    job_id = _ingest(test_app, db_session, user, _column_major_bytes(), "three_samples.txt")

    job = db_session.get(IngestionJob, uuid.UUID(job_id))
    assert job.status == IngestionStatus.succeeded
    assert job.layout_source in {"ranked", "heuristic"}
    assert len(job.file_layout["traces"]) == 3
    assert job.sanity_check_flags["array.multi_trace"]

    assert _confirm(test_app, user, job_id).status_code == 200
    db_session.expire_all()

    drafts = (
        db_session.query(Spectrum)
        .filter(Spectrum.raw_file_id == job.raw_file_id)
        .order_by(Spectrum.source_trace_index)
        .all()
    )
    assert [draft.source_trace_index for draft in drafts] == [1, 2, 3]
    assert [draft.source_trace_label for draft in drafts] == ["sample_0", "sample_1", "sample_2"]

    from app.models.analysis import AnalysisDatasetSpectrum

    job = db_session.get(IngestionJob, uuid.UUID(job_id))
    assert job.draft_dataset_id is not None
    assert job.draft_spectrum_id == drafts[0].id
    members = (
        db_session.query(AnalysisDatasetSpectrum)
        .filter(AnalysisDatasetSpectrum.dataset_id == job.draft_dataset_id)
        .all()
    )
    assert len(members) == 3


@requires_db
def test_each_draft_reads_its_own_trace(test_app, db_session, fake_storage):
    """The regression this whole change exists to prevent: two spectra from
    one file must not serve each other's numbers."""
    from app.processing.cache import compute_cache_key
    from app.spectra_io import load_spectrum_trace

    user = _make_user(db_session, "sub-multi-2", "multi2@example.com")
    job_id = _ingest(test_app, db_session, user, _column_major_bytes(), "three_samples.txt")
    assert _confirm(test_app, user, job_id).status_code == 200
    db_session.expire_all()

    job = db_session.get(IngestionJob, uuid.UUID(job_id))
    drafts = (
        db_session.query(Spectrum)
        .filter(Spectrum.raw_file_id == job.raw_file_id)
        .order_by(Spectrum.source_trace_index)
        .all()
    )
    loaded = [load_spectrum_trace(draft, db_session) for draft in drafts]
    first_intensities = [float(intensities[0]) for _x, intensities in loaded]
    assert first_intensities == [1000.0, 2000.0, 3000.0]
    # Shared wavenumber axis, distinct intensities.
    assert all(list(loaded[0][0]) == list(x) for x, _y in loaded)

    keys = {compute_cache_key(job.raw_file_id, "ledger-hash", d.source_trace_index) for d in drafts}
    assert len(keys) == 3
    # The first trace keeps the key it had when a file could only hold one
    # spectrum, so nothing cached before this change is orphaned.
    assert compute_cache_key(job.raw_file_id, "ledger-hash") in keys


@requires_db
def test_reconfirming_a_multi_spectrum_file_does_not_duplicate_drafts(
    test_app, db_session, fake_storage
):
    user = _make_user(db_session, "sub-multi-3", "multi3@example.com")
    job_id = _ingest(test_app, db_session, user, _column_major_bytes(), "three_samples.txt")
    assert _confirm(test_app, user, job_id).status_code == 200
    db_session.expire_all()
    job = db_session.get(IngestionJob, uuid.UUID(job_id))
    drafts = db_session.query(Spectrum).filter(Spectrum.raw_file_id == job.raw_file_id).all()
    drafts[0].title = "Renamed by the scientist"
    db_session.commit()

    assert _confirm(test_app, user, job_id).status_code == 200
    db_session.expire_all()
    again = db_session.query(Spectrum).filter(Spectrum.raw_file_id == job.raw_file_id).all()
    assert len(again) == 3
    assert {d.title for d in again} >= {"Renamed by the scientist"}


# ---------------------------------------------------------------------------
# Asking the owner when detection gives up
# ---------------------------------------------------------------------------


def _declare(test_app, user, job_id: str, layout: dict):
    token = encode_session_token(user)

    async def _run():
        async with _client(test_app) as client:
            client.cookies.set("session", token)
            return await client.post(f"/ingestion-jobs/{job_id}/layout", json={"layout": layout})

    return run_async(_run())


@requires_db
def test_an_unresolvable_file_asks_the_owner_instead_of_failing(
    test_app, db_session, fake_storage
):
    """A file no deterministic rung can explain, and with no LLM key there is
    no rung left. The upload must survive as a question, not die as a
    failure."""
    user = _make_user(db_session, "sub-layout-1", "layout1@example.com")
    job_id = _ingest(test_app, db_session, user, _undetectable_bytes(), "opaque.csv", llm=False)

    job = db_session.get(IngestionJob, uuid.UUID(job_id))
    assert job.status == IngestionStatus.needs_input
    assert job.layout_source == "unresolved"
    # Everything already worked out is kept, so answering is the only work left.
    assert job.extracted_metadata_raw is not None
    assert job.structure_preview["column_count"] == 4
    raw_file = db_session.get(RawFile, job.raw_file_id)
    assert raw_file.upload_status.value == "uploaded"


@requires_db
def test_a_declared_layout_that_cannot_be_read_is_refused(test_app, db_session, fake_storage):
    user = _make_user(db_session, "sub-layout-2", "layout2@example.com")
    job_id = _ingest(test_app, db_session, user, _undetectable_bytes(), "opaque.csv", llm=False)

    resp = _declare(
        test_app,
        user,
        job_id,
        {"orientation": "column_major", "delimiter": ",", "traces": [{"index": 1}]},
    )
    assert resp.status_code == 422
    db_session.expire_all()
    assert db_session.get(IngestionJob, uuid.UUID(job_id)).status == IngestionStatus.needs_input


@requires_db
def test_a_declared_layout_finishes_the_job_and_is_remembered(
    test_app, db_session, fake_storage
):
    from app.ingestion.structure import build_preview, cached_layout, compute_structure_hash

    user = _make_user(db_session, "sub-layout-3", "layout3@example.com")
    content = _row_major_bytes()
    job_id = _ingest(test_app, db_session, user, content, "transposed.csv", llm=False)

    resp = _declare(
        test_app,
        user,
        job_id,
        {
            "orientation": "row_major",
            "delimiter": ",",
            "header_rows": 0,
            "x_index": 0,
            "label_index": 0,
            "traces": [
                {"index": 1, "label": "sample_0"},
                {"index": 2, "label": "sample_1"},
                {"index": 3, "label": "sample_2"},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    db_session.expire_all()
    job = db_session.get(IngestionJob, uuid.UUID(job_id))
    assert job.status == IngestionStatus.succeeded
    assert job.layout_source == "user"

    assert _confirm(test_app, user, job_id).status_code == 200
    db_session.expire_all()
    drafts = db_session.query(Spectrum).filter(Spectrum.raw_file_id == job.raw_file_id).all()
    assert len(drafts) == 3

    # The next upload of this format must not ask again.
    remembered = cached_layout(db_session, compute_structure_hash(build_preview(content)))
    assert remembered is not None
    assert remembered.source == "user"
