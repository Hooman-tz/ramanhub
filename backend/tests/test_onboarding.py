"""M3c: onboarding endpoints (handle availability, suggestions, the
finish-setup write)."""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.deps import get_current_full_user, get_current_user_optional
from app.db.session import get_db
from app.models.graph import Follow, HandleHistory
from app.models.user import User
from app.routers import onboarding as onboarding_router


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    app.include_router(onboarding_router.router)

    state = {"user": None}

    def _override_get_db():
        yield db_session

    def _override_full_user():
        if state["user"] is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Not authenticated")
        return state["user"]

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_full_user] = _override_full_user
    app.dependency_overrides[get_current_user_optional] = lambda: state["user"]

    tc = TestClient(app)
    tc.set_current_user = lambda u: state.__setitem__("user", u)
    return tc


def _mk_user(db_session, **kw) -> User:
    defaults = {
        "email": f"{uuid.uuid4().hex[:10]}@example.com",
        "google_sub": None,
        "display_name": "Someone",
        "is_profile_public": True,
    }
    defaults.update(kw)
    user = User(**defaults)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# --- GET /v1/users/handle-available ----------------------------------------


def test_handle_available_free(client):
    resp = client.get("/v1/users/handle-available", params={"handle": "Fresh-Handle"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"available": True, "normalized": "fresh-handle", "reason": None}


def test_handle_available_taken_by_user(client, db_session):
    _mk_user(db_session, profile_handle="already-taken")
    resp = client.get("/v1/users/handle-available", params={"handle": "already-taken"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["available"] is False
    assert body["reason"]


def test_handle_available_taken_by_history(client, db_session):
    u = _mk_user(db_session, profile_handle="current-one")
    db_session.add(HandleHistory(handle="retired-one", user_id=u.id))
    db_session.commit()
    resp = client.get("/v1/users/handle-available", params={"handle": "retired-one"})
    assert resp.json()["available"] is False


def test_handle_available_reserved(client):
    resp = client.get("/v1/users/handle-available", params={"handle": "admin"})
    body = resp.json()
    assert body["available"] is False
    assert "reserved" in body["reason"].lower()


def test_handle_available_invalid(client):
    resp = client.get("/v1/users/handle-available", params={"handle": "no"})
    body = resp.json()
    assert body["available"] is False
    assert body["reason"]


# --- GET /v1/users/suggested ---------------------------------------------


def test_suggested_orders_by_followers_and_excludes_self_and_followed(client, db_session):
    me = _mk_user(db_session, profile_handle=f"me-{uuid.uuid4().hex[:6]}")
    popular = _mk_user(db_session, profile_handle=f"pop-{uuid.uuid4().hex[:6]}")
    quiet = _mk_user(db_session, profile_handle=f"quiet-{uuid.uuid4().hex[:6]}")
    followed = _mk_user(db_session, profile_handle=f"fol-{uuid.uuid4().hex[:6]}")
    private = _mk_user(db_session, profile_handle=f"prv-{uuid.uuid4().hex[:6]}", is_profile_public=False)
    guest = _mk_user(db_session, profile_handle=f"gst-{uuid.uuid4().hex[:6]}", is_guest=True)

    for follower in (_mk_user(db_session), _mk_user(db_session), _mk_user(db_session)):
        db_session.add(Follow(follower_id=follower.id, followee_id=popular.id))
    db_session.add(Follow(follower_id=me.id, followee_id=followed.id))
    db_session.commit()

    client.set_current_user(me)
    resp = client.get("/v1/users/suggested", params={"limit": 25})
    assert resp.status_code == 200
    handles = [row["profile_handle"] for row in resp.json()]

    assert popular.profile_handle in handles
    assert quiet.profile_handle in handles
    assert me.profile_handle not in handles
    assert followed.profile_handle not in handles
    assert private.profile_handle not in handles
    assert guest.profile_handle not in handles
    # Popular (3 followers) sorts ahead of quiet (0).
    assert handles.index(popular.profile_handle) < handles.index(quiet.profile_handle)
    popular_row = next(r for r in resp.json() if r["profile_handle"] == popular.profile_handle)
    assert popular_row["follower_count"] == 3


def test_suggested_limit_capped(client, db_session):
    resp = client.get("/v1/users/suggested", params={"limit": 999})
    assert resp.status_code == 422


# --- POST /v1/users/me/onboarding --------------------------------------


def test_onboarding_sets_fields_and_onboarded_at(client, db_session):
    user = _mk_user(db_session, profile_handle=None, display_name=None, onboarded_at=None)
    client.set_current_user(user)

    resp = client.post(
        "/v1/users/me/onboarding",
        json={
            "handle": "Dr-Spectra",
            "display_name": "Dr Spectra",
            "interests": ["raman", " sers ", ""],
            "is_profile_public": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["profile_handle"] == "dr-spectra"
    assert body["display_name"] == "Dr Spectra"
    assert body["onboarded_at"] is not None
    db_session.refresh(user)
    assert user.research_interests == ["raman", "sers"]
    assert user.is_profile_public is True


def test_onboarding_conflict_on_taken_handle(client, db_session):
    _mk_user(db_session, profile_handle="spoken-for")
    user = _mk_user(db_session, profile_handle=None)
    client.set_current_user(user)

    resp = client.post(
        "/v1/users/me/onboarding",
        json={"handle": "spoken-for", "display_name": "Late"},
    )
    assert resp.status_code == 409


def test_onboarding_records_handle_history_on_change(client, db_session):
    user = _mk_user(db_session, profile_handle="old-handle")
    client.set_current_user(user)

    resp = client.post(
        "/v1/users/me/onboarding",
        json={"handle": "new-handle", "display_name": "Renamed"},
    )
    assert resp.status_code == 200
    row = db_session.query(HandleHistory).filter_by(handle="old-handle").one()
    assert row.user_id == user.id
    db_session.refresh(user)
    assert user.profile_handle == "new-handle"


def test_onboarding_rejects_reserved_handle(client, db_session):
    user = _mk_user(db_session, profile_handle=None)
    client.set_current_user(user)
    resp = client.post(
        "/v1/users/me/onboarding",
        json={"handle": "settings", "display_name": "Nope"},
    )
    assert resp.status_code == 422
