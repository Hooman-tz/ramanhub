"""Tests for `GET /v1/findings/{id}/overlay` — the mean + deviation-band
endpoint (M6.1).

Covers the member-count branches (0 / 1 / 2 overlapping / 2 non-overlapping),
array alignment, `std == 0` for a single member, and the visibility rule: a
draft member spectrum is excluded for a viewer who does not own it.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import (
    get_current_full_user,
    get_current_user,
    get_current_user_optional,
)
from app.db.session import get_db
from app.models.enums import FindingState, Modality, SpectrumState
from app.models.finding import Finding, FindingSpectrum
from app.models.spectrum import Spectrum
from app.routers import findings

RAMP_A = b"100 1.0\n200 2.0\n300 5.0\n400 2.0\n500 1.0\n600 3.0\n"
RAMP_B = b"100 2.0\n200 1.0\n300 4.0\n400 3.0\n500 2.0\n600 1.0\n"
FAR_RANGE = b"5000 1.0\n5200 2.0\n5400 5.0\n5600 2.0\n5800 1.0\n6000 3.0\n"


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    app.include_router(findings.router)
    current: dict[str, object] = {"user": None}

    def _get_db():
        yield db_session

    def _get_user():
        if current["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current["user"]

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = _get_user
    app.dependency_overrides[get_current_full_user] = _get_user
    app.dependency_overrides[get_current_user_optional] = lambda: current["user"]

    c = TestClient(app)
    c.set_current_user = lambda u: current.__setitem__("user", u)
    return c


def _spectrum(db_session, owner, raw_file, state=SpectrumState.published) -> Spectrum:
    spectrum = Spectrum(
        raw_file_id=raw_file.id,
        owner_id=owner.id,
        modality=Modality.raman,
        title="Test spectrum",
        state=state,
        canonicalization_version="raman-1",
    )
    db_session.add(spectrum)
    db_session.commit()
    db_session.refresh(spectrum)
    return spectrum


def _finding(db_session, owner, state=FindingState.published) -> Finding:
    finding = Finding(owner_id=owner.id, title="Overlay finding", state=state)
    db_session.add(finding)
    db_session.commit()
    db_session.refresh(finding)
    return finding


def _attach(db_session, finding, spectrum, position=0, label=None) -> None:
    db_session.add(
        FindingSpectrum(
            finding_id=finding.id,
            spectrum_id=spectrum.id,
            position=position,
            label=label,
        )
    )
    db_session.commit()


def test_zero_members_returns_empty_payload(client, db_session, make_user):
    owner = make_user()
    finding = _finding(db_session, owner)
    client.set_current_user(owner)

    body = client.get(f"/v1/findings/{finding.id}/overlay").json()

    assert body == {
        "grid_wavenumbers": [],
        "mean": [],
        "std": [],
        "n": 0,
        "members": [],
    }


def test_single_member_returns_zero_std(client, db_session, make_user, make_raw_file):
    owner = make_user()
    finding = _finding(db_session, owner)
    spectrum = _spectrum(db_session, owner, make_raw_file(owner, content=RAMP_A))
    _attach(db_session, finding, spectrum, label="only")
    client.set_current_user(owner)

    body = client.get(f"/v1/findings/{finding.id}/overlay?grid=64").json()

    assert body["n"] == 1
    assert len(body["grid_wavenumbers"]) == len(body["mean"]) == len(body["std"]) == 64
    assert all(v == 0.0 for v in body["std"])
    assert body["members"] == [{"spectrum_id": str(spectrum.id), "label": "only"}]


def test_two_overlapping_members_align(client, db_session, make_user, make_raw_file):
    owner = make_user()
    finding = _finding(db_session, owner)
    a = _spectrum(db_session, owner, make_raw_file(owner, content=RAMP_A))
    b = _spectrum(db_session, owner, make_raw_file(owner, content=RAMP_B))
    _attach(db_session, finding, a, position=0)
    _attach(db_session, finding, b, position=1)
    client.set_current_user(owner)

    body = client.get(f"/v1/findings/{finding.id}/overlay?grid=128").json()

    assert body["n"] == 2
    assert len(body["grid_wavenumbers"]) == len(body["mean"]) == len(body["std"]) == 128
    assert any(v > 0.0 for v in body["std"])


def test_two_non_overlapping_members_still_align(
    client, db_session, make_user, make_raw_file
):
    owner = make_user()
    finding = _finding(db_session, owner)
    a = _spectrum(db_session, owner, make_raw_file(owner, content=RAMP_A))
    b = _spectrum(db_session, owner, make_raw_file(owner, content=FAR_RANGE))
    _attach(db_session, finding, a, position=0)
    _attach(db_session, finding, b, position=1)
    client.set_current_user(owner)

    body = client.get(f"/v1/findings/{finding.id}/overlay?grid=32").json()

    # No shared range -> falls back to the first member's own curve.
    assert body["n"] == 2
    assert len(body["grid_wavenumbers"]) == len(body["mean"]) == len(body["std"]) == 32


def test_draft_member_hidden_from_non_owner(
    client, db_session, make_user, make_raw_file
):
    owner, viewer = make_user(), make_user()
    finding = _finding(db_session, owner)
    published = _spectrum(db_session, owner, make_raw_file(owner, content=RAMP_A))
    draft = _spectrum(
        db_session,
        owner,
        make_raw_file(owner, content=RAMP_B),
        state=SpectrumState.draft,
    )
    _attach(db_session, finding, published, position=0, label="pub")
    _attach(db_session, finding, draft, position=1, label="draft")

    # Owner sees both.
    client.set_current_user(owner)
    owner_body = client.get(f"/v1/findings/{finding.id}/overlay?grid=32").json()
    assert owner_body["n"] == 2

    # A different viewer sees only the published member.
    client.set_current_user(viewer)
    viewer_body = client.get(f"/v1/findings/{finding.id}/overlay?grid=32").json()
    assert viewer_body["n"] == 1
    assert viewer_body["members"] == [{"spectrum_id": str(published.id), "label": "pub"}]
    assert all(v == 0.0 for v in viewer_body["std"])
