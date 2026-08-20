"""Tests for `GET /spectra/{id}/data` — the chart-data endpoint (Module 3).

Covers the visibility gate it shares with every other spectrum read, the
LTTB downsampling contract, and `?raw=true`, which the pipeline builder uses
to draw the unprocessed spectrum behind the processed one.
"""
from __future__ import annotations

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.routers import ledgers, spectra, spectrum_data


@pytest.fixture()
def data_client(db_session):
    test_app = FastAPI()
    test_app.include_router(spectra.router)
    test_app.include_router(ledgers.router)
    test_app.include_router(spectrum_data.router)

    def _override_get_db():
        yield db_session

    current = {"user": None}

    def _override_get_current_user():
        if current["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current["user"]

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_current_user] = _override_get_current_user
    test_app.dependency_overrides[get_current_user_optional] = lambda: current["user"]

    client = TestClient(test_app)
    client.set_current_user = lambda user: current.__setitem__("user", user)
    return client


def _spectrum(client, raw_file) -> dict:
    resp = client.post("/spectra", json={"raw_file_id": str(raw_file.id)})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _apply_crop(client, raw_file, spectrum_id: str) -> None:
    resp = client.post(
        f"/raw-files/{raw_file.id}/ledgers",
        json={
            "steps": [
                {"type": "raman.crop", "params": {"min_cm1": 150, "max_cm1": 450}, "order": 0}
            ]
        },
    )
    assert resp.status_code == 201, resp.text
    patch = client.patch(
        f"/spectra/{spectrum_id}", json={"current_ledger_id": resp.json()["ledger_id"]}
    )
    assert patch.status_code == 200, patch.text


def test_returns_raw_arrays_when_no_ledger_is_attached(data_client, make_user, make_raw_file):
    owner = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)

    body = data_client.get(f"/spectra/{spectrum['id']}/data").json()

    assert body["wavenumbers"] == [100.0, 200.0, 300.0, 400.0, 500.0, 600.0]
    assert body["downsampled"] is False
    assert body["total_points"] == 6


def test_returns_processed_arrays_once_a_ledger_is_attached(
    data_client, make_user, make_raw_file
):
    owner = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)
    _apply_crop(data_client, raw_file, spectrum["id"])

    body = data_client.get(f"/spectra/{spectrum['id']}/data").json()

    assert body["wavenumbers"] == [200.0, 300.0, 400.0]


def test_raw_flag_bypasses_the_attached_ledger(data_client, make_user, make_raw_file):
    """What the builder's before/after overlay depends on: the same spectrum
    served unprocessed, with its own (uncropped) axis."""
    owner = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)
    _apply_crop(data_client, raw_file, spectrum["id"])

    body = data_client.get(f"/spectra/{spectrum['id']}/data?raw=true").json()

    assert body["wavenumbers"] == [100.0, 200.0, 300.0, 400.0, 500.0, 600.0]


def test_downsamples_above_max_points(data_client, make_user, make_raw_file):
    owner = make_user()
    data_client.set_current_user(owner)
    lines = "".join(f"{i} {np.sin(i / 50.0):.6f}\n" for i in range(5000))
    raw_file = make_raw_file(owner, content=lines.encode())
    spectrum = _spectrum(data_client, raw_file)

    body = data_client.get(f"/spectra/{spectrum['id']}/data?max_points=500").json()

    assert body["downsampled"] is True
    assert body["total_points"] == 5000
    assert len(body["wavenumbers"]) <= 500
    assert len(body["wavenumbers"]) == len(body["intensities"])


def test_draft_data_is_not_readable_by_others(data_client, make_user, make_raw_file):
    """The row-level access rule the architecture doc calls the one bug that
    would matter most — it has to hold on the data endpoint too, not just on
    the spectrum record."""
    owner = make_user()
    other = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)

    data_client.set_current_user(other)
    assert data_client.get(f"/spectra/{spectrum['id']}/data").status_code == 404
    assert data_client.get(f"/spectra/{spectrum['id']}/data?raw=true").status_code == 404

    data_client.set_current_user(None)
    assert data_client.get(f"/spectra/{spectrum['id']}/data").status_code == 404


def test_published_data_is_readable_anonymously(data_client, make_user, make_raw_file):
    owner = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)
    publish = data_client.post(
        f"/spectra/{spectrum['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert publish.status_code == 200, publish.text

    data_client.set_current_user(None)
    assert data_client.get(f"/spectra/{spectrum['id']}/data").status_code == 200


def test_rejects_non_positive_max_points(data_client, make_user, make_raw_file):
    owner = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)

    assert data_client.get(f"/spectra/{spectrum['id']}/data?max_points=0").status_code == 422
