"""Tests for DELETE /spectra/{id} — owner-only hard delete of a non-published
draft and every artefact that only exists to support it."""
from __future__ import annotations

import uuid

from app.config import settings
from app.models.ingestion_job import IngestionJob
from app.models.processing_ledger import ProcessingLedger
from app.models.raw_file import RawFile
from app.models.spectrum import Spectrum


def _make_draft(app_client, owner, raw_file) -> dict:
    resp = app_client.post(
        "/spectra",
        json={"raw_file_id": str(raw_file.id), "title": "Draft", "material_type": "quartz"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _publish(app_client, spectrum_id, raw_file) -> dict:
    ledger = app_client.post(
        f"/raw-files/{raw_file.id}/ledgers",
        json={"steps": [{"type": "raman.snv", "params": {}, "order": 0}]},
    )
    assert ledger.status_code == 201, ledger.text
    patched = app_client.patch(
        f"/spectra/{spectrum_id}", json={"current_ledger_id": ledger.json()["ledger_id"]}
    )
    assert patched.status_code == 200, patched.text
    published = app_client.post(
        f"/spectra/{spectrum_id}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert published.status_code == 200, published.text
    return published.json()


def test_owner_deletes_draft_cascades(
    app_client, make_user, make_raw_file, db_session, fake_s3
):
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    draft = _make_draft(app_client, owner, raw_file)

    # Give the draft a processing ledger so there's a ProcessingLedger row to
    # clean up too.
    ledger = app_client.post(
        f"/raw-files/{raw_file.id}/ledgers",
        json={"steps": [{"type": "raman.snv", "params": {}, "order": 0}]},
    )
    assert ledger.status_code == 201, ledger.text
    app_client.patch(
        f"/spectra/{draft['id']}", json={"current_ledger_id": ledger.json()["ledger_id"]}
    )

    raw_file_id = raw_file.id
    storage_key = raw_file.storage_key

    resp = app_client.delete(f"/spectra/{draft['id']}")
    assert resp.status_code == 204, resp.text
    assert resp.content == b""

    assert db_session.get(Spectrum, uuid.UUID(draft["id"])) is None
    assert db_session.get(RawFile, raw_file_id) is None
    assert (
        db_session.query(IngestionJob).filter_by(raw_file_id=raw_file_id).first() is None
    )
    assert (
        db_session.query(ProcessingLedger).filter_by(raw_file_id=raw_file_id).first()
        is None
    )
    assert (settings.S3_BUCKET_RAW, storage_key) not in fake_s3


def test_delete_is_owner_scoped(app_client, make_user, make_raw_file, db_session):
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    draft = _make_draft(app_client, owner, raw_file)

    other = make_user()
    app_client.set_current_user(other)
    resp = app_client.delete(f"/spectra/{draft['id']}")
    assert resp.status_code in (403, 404)

    # Still there for the real owner.
    assert db_session.get(Spectrum, uuid.UUID(draft["id"])) is not None


def test_delete_unknown_spectrum_is_404(app_client, make_user):
    user = make_user()
    app_client.set_current_user(user)
    assert app_client.delete(f"/spectra/{uuid.uuid4()}").status_code == 404


def test_delete_requires_auth(app_client, make_user, make_raw_file):
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    draft = _make_draft(app_client, owner, raw_file)

    app_client.set_current_user(None)
    assert app_client.delete(f"/spectra/{draft['id']}").status_code == 401


def test_cannot_delete_published_spectrum(
    app_client, make_user, make_raw_file, db_session, fake_s3
):
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    draft = _make_draft(app_client, owner, raw_file)
    _publish(app_client, draft["id"], raw_file)

    resp = app_client.delete(f"/spectra/{draft['id']}")
    assert resp.status_code == 409, resp.text
    assert db_session.get(Spectrum, uuid.UUID(draft["id"])) is not None
