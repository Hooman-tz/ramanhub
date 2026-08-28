"""Tests for Module 4a: /search/spectra, /search/similar/{id}, /library/mine.

Uses a locally-built TestClient (mirrors `conftest.py`'s `app_client`
fixture pattern) rather than importing/extending `app_client` itself, so
this file has no edit-conflict surface with `tests/conftest.py` while other
agents build Module 3/4b concurrently in the same worktree.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.models.publication import PublicationSnapshot
from app.models.social import Vote
from app.models.spectrum import Spectrum


@pytest.fixture()
def client(db_session):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from app.auth.deps import get_current_user, get_current_user_optional
    from app.db.session import get_db
    from app.routers import library, search, spectra

    test_app = FastAPI()
    test_app.include_router(spectra.router)
    test_app.include_router(search.router)
    test_app.include_router(library.router)

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

    c = TestClient(test_app)
    c.set_current_user = lambda user: current.__setitem__("user", user)
    return c


def _create_and_publish(
    client,
    owner,
    make_raw_file,
    *,
    content: bytes | None = None,
    material_type: str | None = None,
    laser_wavelength_nm: float | None = None,
    doi: str | None = None,
):
    client.set_current_user(owner)
    raw_file = make_raw_file(owner, content=content) if content is not None else make_raw_file(owner)

    body: dict = {"raw_file_id": str(raw_file.id)}
    if material_type is not None:
        body["material_type"] = material_type
    if laser_wavelength_nm is not None:
        body["confirmed_metadata"] = {"laser_wavelength_nm": laser_wavelength_nm}

    resp = client.post("/spectra", json=body)
    assert resp.status_code == 201, resp.text
    spectrum = resp.json()

    publish_body: dict = {"license_id": "CC-BY-4.0"}
    if doi is not None:
        publish_body["doi"] = doi
    resp = client.post(f"/spectra/{spectrum['id']}/publish", json=publish_body)
    assert resp.status_code == 200, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# /search/spectra
# ---------------------------------------------------------------------------


def test_material_type_filter_matches_substring(client, make_user, make_raw_file):
    owner = make_user()
    quartz = _create_and_publish(client, owner, make_raw_file, material_type="Quartz crystal")
    silicon = _create_and_publish(client, owner, make_raw_file, material_type="Silicon wafer")

    resp = client.get("/search/spectra", params={"material_type": "quartz"})
    assert resp.status_code == 200
    assert all("owner_id" not in row for row in resp.json())
    ids = [row["id"] for row in resp.json()]
    assert quartz["id"] in ids
    assert silicon["id"] not in ids


def test_excitation_wavelength_tolerance_matching(client, make_user, make_raw_file):
    owner = make_user()
    near = _create_and_publish(client, owner, make_raw_file, laser_wavelength_nm=532.0)
    far = _create_and_publish(client, owner, make_raw_file, laser_wavelength_nm=785.0)

    resp = client.get(
        "/search/spectra",
        params={"excitation_wavelength_nm": 530.0, "excitation_wavelength_tolerance_nm": 5.0},
    )
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert near["id"] in ids
    assert far["id"] not in ids


def test_min_snr_filter(client, make_user, make_raw_file):
    owner = make_user()
    sharp = _create_and_publish(client, owner, make_raw_file, material_type="min-snr-test")
    flat_content = b"100 1.00\n200 1.01\n300 0.99\n400 1.02\n500 0.98\n600 1.00\n"
    flat = _create_and_publish(
        client, owner, make_raw_file, content=flat_content, material_type="min-snr-test"
    )

    resp = client.get("/search/spectra", params={"material_type": "min-snr-test"})
    assert resp.status_code == 200
    rows = {row["id"]: row["snr"] for row in resp.json()}
    sharp_snr, flat_snr = rows[sharp["id"]], rows[flat["id"]]
    assert sharp_snr is not None and flat_snr is not None
    assert sharp_snr > flat_snr

    threshold = (sharp_snr + flat_snr) / 2
    resp = client.get(
        "/search/spectra", params={"material_type": "min-snr-test", "min_snr": threshold}
    )
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert sharp["id"] in ids
    assert flat["id"] not in ids


def test_trust_tier_filter(client, make_user, make_raw_file, db_session):
    owner = make_user()
    verified = _create_and_publish(client, owner, make_raw_file)
    verified_row = db_session.get(Spectrum, uuid.UUID(verified["id"]))
    verified_row.doi = "10.1234/example"
    db_session.add(
        PublicationSnapshot(
            spectrum_id=verified_row.id,
            doi="10.1234/example",
            provider="crossref",
            verification_status="verified",
            snapshot={"doi": "10.1234/example", "title": "Verified Raman record"},
        )
    )
    db_session.commit()
    community = _create_and_publish(client, owner, make_raw_file)

    resp = client.get("/search/spectra", params={"trust_tier": "doi_verified"})
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert verified["id"] in ids
    assert community["id"] not in ids

    resp = client.get("/search/spectra", params={"trust_tier": "community"})
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert community["id"] in ids
    assert verified["id"] not in ids


def test_drafts_never_appear_in_search(client, make_user, make_raw_file):
    owner = make_user()
    client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    resp = client.post(
        "/spectra", json={"raw_file_id": str(raw_file.id), "material_type": "draft-material-xyz"}
    )
    assert resp.status_code == 201

    resp = client.get("/search/spectra", params={"material_type": "draft-material-xyz"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_ordering_by_published_at_not_votes(client, make_user, make_raw_file, db_session):
    owner = make_user()
    older = _create_and_publish(client, owner, make_raw_file, material_type="order-test")
    newer = _create_and_publish(client, owner, make_raw_file, material_type="order-test")

    # Pin published_at explicitly so ordering doesn't depend on real clock
    # resolution between the two publish calls above.
    older_row = db_session.get(Spectrum, uuid.UUID(older["id"]))
    older_row.published_at = datetime.now(UTC) - timedelta(days=1)
    newer_row = db_session.get(Spectrum, uuid.UUID(newer["id"]))
    newer_row.published_at = datetime.now(UTC)
    db_session.add_all([older_row, newer_row])
    db_session.commit()

    # Give the OLDER spectrum lots of votes and the newer one none. Ordering
    # must be completely unaffected — core search is quarantined from
    # Module 4b's social/vote signal.
    for _ in range(5):
        voter = make_user()
        db_session.add(Vote(spectrum_id=older_row.id, user_id=voter.id))
    db_session.commit()

    resp = client.get("/search/spectra", params={"material_type": "order-test"})
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert ids.index(newer["id"]) < ids.index(older["id"])


# ---------------------------------------------------------------------------
# /search/similar/{spectrum_id}
# ---------------------------------------------------------------------------


def test_similarity_search_ranks_identical_above_different(client, make_user, make_raw_file):
    owner = make_user()
    base_content = b"100 1.0\n200 2.0\n300 5.0\n400 2.0\n500 1.0\n600 3.0\n"
    different_content = b"100 5.0\n200 4.0\n300 0.5\n400 4.0\n500 5.0\n600 0.2\n"

    target = _create_and_publish(client, owner, make_raw_file, content=base_content)
    twin = _create_and_publish(client, owner, make_raw_file, content=base_content)
    different = _create_and_publish(client, owner, make_raw_file, content=different_content)

    resp = client.get(f"/search/similar/{target['id']}")
    assert resp.status_code == 200
    results = resp.json()
    by_id = {row["spectrum"]["id"]: row["similarity"] for row in results}

    assert twin["id"] in by_id
    assert different["id"] in by_id
    assert target["id"] not in by_id  # target never compared against itself
    assert by_id[twin["id"]] > by_id[different["id"]]
    assert by_id[twin["id"]] == pytest.approx(1.0, abs=1e-6)


def test_similarity_search_excludes_non_overlapping_spectra(client, make_user, make_raw_file):
    owner = make_user()
    near = _create_and_publish(
        client,
        owner,
        make_raw_file,
        content=b"100 1\n200 3\n300 5\n400 3\n500 1\n600 2\n",
    )
    far = _create_and_publish(
        client,
        owner,
        make_raw_file,
        content=b"1000 1\n1100 3\n1200 5\n1300 3\n1400 1\n1500 2\n",
    )
    twin = _create_and_publish(
        client,
        owner,
        make_raw_file,
        content=b"100 2\n200 4\n300 7\n400 4\n500 2\n600 3\n",
    )

    response = client.get(f"/search/similar/{near['id']}")
    assert response.status_code == 200, response.text
    ids = {row["spectrum"]["id"] for row in response.json()}
    assert twin["id"] in ids
    assert far["id"] not in ids


def test_similarity_search_target_must_be_owned_or_public(client, make_user, make_raw_file):
    owner = make_user()
    other = make_user()
    client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    resp = client.post("/spectra", json={"raw_file_id": str(raw_file.id)})
    draft = resp.json()

    client.set_current_user(other)
    resp = client.get(f"/search/similar/{draft['id']}")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# /library/mine
# ---------------------------------------------------------------------------


def test_library_mine_shows_all_states_and_isolates_other_users(client, make_user, make_raw_file):
    owner = make_user()
    other = make_user()

    client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    resp = client.post(
        "/spectra",
        json={"raw_file_id": str(raw_file.id), "title": "draft one", "material_type": "quartz"},
    )
    assert resp.status_code == 201
    draft = resp.json()

    published = _create_and_publish(client, owner, make_raw_file, material_type="quartz")

    client.set_current_user(owner)
    resp = client.get("/library/mine")
    assert resp.status_code == 200
    states_by_id = {row["id"]: row["state"] for row in resp.json()}
    assert states_by_id[draft["id"]] == "draft"
    assert states_by_id[published["id"]] == "published"

    client.set_current_user(other)
    resp = client.get("/library/mine")
    assert resp.status_code == 200
    assert resp.json() == []

    client.set_current_user(None)
    resp = client.get("/library/mine")
    assert resp.status_code == 401


def test_library_mine_filters_like_search(client, make_user, make_raw_file):
    owner = make_user()
    client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    resp = client.post(
        "/spectra",
        json={"raw_file_id": str(raw_file.id), "material_type": "graphene"},
    )
    graphene_draft = resp.json()
    resp = client.post(
        "/spectra",
        json={"raw_file_id": str(raw_file.id), "material_type": "polymer"},
    )
    polymer_draft = resp.json()

    resp = client.get("/library/mine", params={"material_type": "graphene"})
    assert resp.status_code == 200
    ids = [row["id"] for row in resp.json()]
    assert graphene_draft["id"] in ids
    assert polymer_draft["id"] not in ids
