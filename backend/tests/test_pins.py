"""M6.3: pins — the owner-curated top of a profile.

Covers the MAX_PINS ceiling, ownership + published-state gating, the public
read ordering, position renormalization on unpin, and idempotent re-pin.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.curation import MAX_PINS
from app.models.enums import Modality, SpectrumState
from app.models.spectrum import Spectrum
from app.models.user import User
from app.routers import pins as pins_router


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    app.include_router(pins_router.router)
    state = {"user": None}

    def _override_get_db():
        yield db_session

    def _override_current_user():
        if state["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return state["user"]

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_current_user] = _override_current_user

    tc = TestClient(app)
    tc.set_current_user = lambda u: state.__setitem__("user", u)
    return tc


def _mk_user(db_session, handle: str) -> User:
    user = User(
        email=f"{uuid.uuid4().hex[:10]}@example.com",
        display_name="Dr Pin",
        is_profile_public=True,
        profile_handle=handle,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _spectrum(db_session, make_raw_file, owner, *, published=True, title="S", accession=None):
    raw = make_raw_file(owner)
    spec = Spectrum(
        raw_file_id=raw.id,
        owner_id=owner.id,
        modality=Modality.raman,
        title=title,
        accession=accession,
        state=SpectrumState.published if published else SpectrumState.draft,
        published_at=datetime.now(UTC) if published else None,
    )
    db_session.add(spec)
    db_session.commit()
    db_session.refresh(spec)
    return spec


def test_pin_up_to_max_then_reject(client, db_session, make_raw_file):
    owner = _mk_user(db_session, "pinner")
    client.set_current_user(owner)
    specs = [
        _spectrum(db_session, make_raw_file, owner, title=f"S{i}", accession=f"RH-S-{i:06d}")
        for i in range(MAX_PINS + 1)
    ]

    for i in range(MAX_PINS):
        resp = client.post("/pins", json={"kind": "spectrum", "id": str(specs[i].id)})
        assert resp.status_code == 201, resp.text
        assert len(resp.json()) == i + 1

    resp = client.post("/pins", json={"kind": "spectrum", "id": str(specs[MAX_PINS].id)})
    assert resp.status_code == 409


def test_cannot_pin_someone_elses_item(client, db_session, make_raw_file):
    owner = _mk_user(db_session, "owner-a")
    other = _mk_user(db_session, "owner-b")
    theirs = _spectrum(db_session, make_raw_file, other, accession="RH-S-999001")

    client.set_current_user(owner)
    resp = client.post("/pins", json={"kind": "spectrum", "id": str(theirs.id)})
    assert resp.status_code == 404


def test_cannot_pin_a_draft(client, db_session, make_raw_file):
    owner = _mk_user(db_session, "drafter")
    draft = _spectrum(db_session, make_raw_file, owner, published=False)

    client.set_current_user(owner)
    resp = client.post("/pins", json={"kind": "spectrum", "id": str(draft.id)})
    assert resp.status_code == 422


def test_public_pins_list_is_ordered_with_titles(client, db_session, make_raw_file):
    owner = _mk_user(db_session, "curator")
    client.set_current_user(owner)
    a = _spectrum(db_session, make_raw_file, owner, title="Alpha", accession="RH-S-000101")
    b = _spectrum(db_session, make_raw_file, owner, title="Bravo", accession="RH-S-000102")
    client.post("/pins", json={"kind": "spectrum", "id": str(a.id)})
    client.post("/pins", json={"kind": "spectrum", "id": str(b.id)})

    client.set_current_user(None)
    resp = client.get("/users/curator/pins")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert [r["position"] for r in rows] == [0, 1]
    assert [r["title"] for r in rows] == ["Alpha", "Bravo"]
    assert [r["accession"] for r in rows] == ["RH-S-000101", "RH-S-000102"]


def test_unpin_renormalizes_positions(client, db_session, make_raw_file):
    owner = _mk_user(db_session, "renorm")
    client.set_current_user(owner)
    specs = [
        _spectrum(db_session, make_raw_file, owner, title=f"S{i}", accession=f"RH-S-{i:06d}")
        for i in range(3)
    ]
    for s in specs:
        client.post("/pins", json={"kind": "spectrum", "id": str(s.id)})

    # Drop the middle one; the trailing pin must slide from position 2 to 1.
    resp = client.delete(f"/pins/spectrum/{specs[1].id}")
    assert resp.status_code == 200
    rows = resp.json()
    assert [r["position"] for r in rows] == [0, 1]
    assert [r["id"] for r in rows] == [str(specs[0].id), str(specs[2].id)]


def test_repin_is_idempotent(client, db_session, make_raw_file):
    owner = _mk_user(db_session, "idem")
    client.set_current_user(owner)
    spec = _spectrum(db_session, make_raw_file, owner, accession="RH-S-000501")

    first = client.post("/pins", json={"kind": "spectrum", "id": str(spec.id)})
    second = client.post("/pins", json={"kind": "spectrum", "id": str(spec.id)})
    assert first.status_code == 201
    assert second.status_code == 201
    assert len(second.json()) == 1
