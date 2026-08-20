"""Guest ("try before login") sessions: guests can upload and run the
processing tools, but identity-carrying actions — publish, vote, comment,
profile linking — are gated to full accounts, and signing in migrates a
guest's work to the real account."""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.deps import SESSION_COOKIE_NAME
from app.db.session import get_db
from app.models.processing_ledger import ProcessingLedger
from app.models.raw_file import RawFile
from app.models.spectrum import Spectrum
from app.models.user import User
from app.routers import auth as auth_router
from app.routers.auth import migrate_guest_data
from tests._social_app import build_social_client


@pytest.fixture()
def make_guest(db_session):
    def _make() -> User:
        token = uuid.uuid4().hex
        guest = User(
            google_sub=f"guest:{token}",
            email=f"guest-{token}@guest.invalid",
            display_name="Guest",
            is_guest=True,
        )
        db_session.add(guest)
        db_session.commit()
        db_session.refresh(guest)
        return guest

    return _make


# --- POST /auth/guest ---------------------------------------------------------


def test_guest_endpoint_creates_user_and_sets_session_cookie(db_session):
    app = FastAPI()
    app.include_router(auth_router.router)

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)

    resp = client.post("/auth/guest")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_guest"] is True
    assert SESSION_COOKIE_NAME in resp.cookies
    created = db_session.get(User, uuid.UUID(body["id"]))
    assert created is not None and created.is_guest


# --- What guests can and cannot do --------------------------------------------


def test_guest_can_create_draft_and_ledger(app_client, make_guest, make_raw_file):
    guest = make_guest()
    app_client.set_current_user(guest)
    raw_file = make_raw_file(guest)

    resp = app_client.post("/spectra", json={"raw_file_id": str(raw_file.id)})
    assert resp.status_code == 201, resp.text
    assert resp.json()["state"] == "draft"

    ledger = app_client.post(
        f"/raw-files/{raw_file.id}/ledgers",
        json={"steps": [{"type": "raman.snv", "params": {}, "order": 0}]},
    )
    assert ledger.status_code == 201, ledger.text


def test_guest_cannot_publish(app_client, make_guest, make_raw_file):
    guest = make_guest()
    app_client.set_current_user(guest)
    raw_file = make_raw_file(guest)
    spectrum = app_client.post("/spectra", json={"raw_file_id": str(raw_file.id)}).json()

    resp = app_client.post(
        f"/spectra/{spectrum['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )

    assert resp.status_code == 403
    assert "Sign in" in resp.json()["detail"]


def test_guest_cannot_vote_or_comment(db_session, make_guest, make_user, make_raw_file):
    client = build_social_client(db_session)
    owner = make_user()
    client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = client.post("/spectra", json={"raw_file_id": str(raw_file.id)}).json()
    published = client.post(
        f"/spectra/{spectrum['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert published.status_code == 200, published.text

    guest = make_guest()
    client.set_current_user(guest)
    assert client.post(f"/spectra/{spectrum['id']}/votes").status_code == 403
    assert (
        client.post(
            f"/spectra/{spectrum['id']}/comments", json={"body": "hi"}
        ).status_code
        == 403
    )


# --- Sign-in migration ----------------------------------------------------------


def test_migrate_guest_data_reassigns_work_and_deactivates_guest(
    db_session, make_guest, make_user, make_raw_file, app_client
):
    guest = make_guest()
    app_client.set_current_user(guest)
    raw_file = make_raw_file(guest)
    spectrum = app_client.post("/spectra", json={"raw_file_id": str(raw_file.id)}).json()
    app_client.post(
        f"/raw-files/{raw_file.id}/ledgers",
        json={"steps": [{"type": "raman.snv", "params": {}, "order": 0}]},
    )

    real = make_user()
    moved = migrate_guest_data(guest, real, db_session)
    db_session.commit()

    assert moved >= 3  # raw file + spectrum + ledger
    assert db_session.get(RawFile, raw_file.id).owner_id == real.id
    assert db_session.get(Spectrum, uuid.UUID(spectrum["id"])).owner_id == real.id
    assert (
        db_session.query(ProcessingLedger).filter_by(created_by=guest.id).count() == 0
    )
    assert guest.is_active is False

    # The migrated draft is now readable by the real account, not the guest.
    app_client.set_current_user(real)
    assert app_client.get(f"/spectra/{spectrum['id']}").status_code == 200
    app_client.set_current_user(guest)
    assert app_client.get(f"/spectra/{spectrum['id']}").status_code == 404
