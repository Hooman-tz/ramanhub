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


# ---------------------------------------------------------------------------
# POST /spectra/{id}/preview — the uncommitted, hypothetical view
# ---------------------------------------------------------------------------


def _ledger_rows(db_session) -> int:
    from app.models.processing_ledger import ProcessingLedger

    return db_session.query(ProcessingLedger).count()


def _cache_rows(db_session) -> int:
    from app.models.processed_cache import ProcessedCache

    return db_session.query(ProcessedCache).count()


CROP_STEP = {"type": "raman.crop", "params": {"min_cm1": 150, "max_cm1": 450}, "order": 0}


def test_preview_matches_what_applying_the_same_pipeline_produces(
    data_client, make_user, make_raw_file
):
    """The contract that makes preview worth having: what you are shown before
    Apply is what you get after it. If these ever diverge, the preview is a
    lie and users will stop trusting it — so this compares the arrays, not
    just their shapes."""
    owner = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)

    previewed = data_client.post(
        f"/spectra/{spectrum['id']}/preview", json={"steps": [CROP_STEP]}
    ).json()

    _apply_crop(data_client, raw_file, spectrum["id"])
    committed = data_client.get(f"/spectra/{spectrum['id']}/data").json()

    assert previewed["wavenumbers"] == committed["wavenumbers"]
    assert previewed["intensities"] == committed["intensities"]


def test_preview_writes_nothing(data_client, db_session, make_user, make_raw_file):
    """The whole reason preview has its own compute path. Previewing must not
    litter the ledger or cache tables with every intermediate pipeline a user
    clicked through on the way to the one they meant.

    A committed pipeline is applied FIRST so the baseline counts are non-zero.
    Asserting 0 == 0 would pass even if the commit path were broken too, which
    would make this test look green while proving nothing.
    """
    owner = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)

    _apply_crop(data_client, raw_file, spectrum["id"])
    ledgers_before, cache_before = _ledger_rows(db_session), _cache_rows(db_session)
    assert ledgers_before > 0 and cache_before > 0, "baseline must be non-zero to mean anything"

    # Four DISTINCT pipelines, none of them the committed one — so any of them
    # being persisted would move the counts.
    for max_cm1 in (350, 400, 500, 550):
        resp = data_client.post(
            f"/spectra/{spectrum['id']}/preview",
            json={
                "steps": [
                    {"type": "raman.crop", "params": {"min_cm1": 150, "max_cm1": max_cm1}, "order": 0}
                ]
            },
        )
        assert resp.status_code == 200, resp.text

    assert _ledger_rows(db_session) == ledgers_before
    assert _cache_rows(db_session) == cache_before


def test_preview_does_not_change_the_attached_ledger(data_client, make_user, make_raw_file):
    owner = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)
    _apply_crop(data_client, raw_file, spectrum["id"])

    data_client.post(f"/spectra/{spectrum['id']}/preview", json={"steps": [{"type": "raman.snv", "params": {}, "order": 0}]})

    # Still the cropped axis from the committed ledger, not the SNV preview.
    assert data_client.get(f"/spectra/{spectrum['id']}/data").json()["wavenumbers"] == [
        200.0,
        300.0,
        400.0,
    ]


def test_preview_with_no_steps_returns_the_raw_spectrum(data_client, make_user, make_raw_file):
    """Legal on purpose: it is what makes "remove the last step" previewable
    all the way back to an empty pipeline."""
    owner = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)

    body = data_client.post(f"/spectra/{spectrum['id']}/preview", json={"steps": []}).json()

    assert body["wavenumbers"] == [100.0, 200.0, 300.0, 400.0, 500.0, 600.0]


def test_preview_of_a_draft_is_not_readable_by_others(data_client, make_user, make_raw_file):
    """Preview replays arbitrary processing over the raw arrays, so it is a
    read of the underlying data and must be gated exactly like /data. A
    preview endpoint that skipped this would be a way to read other people's
    drafts one pipeline at a time."""
    owner = make_user()
    other = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)

    data_client.set_current_user(other)
    assert data_client.post(f"/spectra/{spectrum['id']}/preview", json={"steps": []}).status_code == 404

    data_client.set_current_user(None)
    assert data_client.post(f"/spectra/{spectrum['id']}/preview", json={"steps": []}).status_code == 404


def test_preview_rejects_an_unknown_step_type(data_client, make_user, make_raw_file):
    owner = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)

    resp = data_client.post(
        f"/spectra/{spectrum['id']}/preview",
        json={"steps": [{"type": "raman.not_a_real_step", "params": {}, "order": 0}]},
    )

    assert resp.status_code == 422


def test_preview_rejects_params_that_fail_the_schema(data_client, make_user, make_raw_file):
    """Validation is deliberately the same as the commit path's, so a preview
    can never accept a pipeline that Apply would then reject."""
    owner = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)

    resp = data_client.post(
        f"/spectra/{spectrum['id']}/preview",
        json={"steps": [{"type": "raman.crop", "params": {"min_cm1": "not a number"}, "order": 0}]},
    )

    assert resp.status_code == 422


def test_a_step_that_cannot_run_on_this_spectrum_is_422_not_500(
    data_client, make_user, make_raw_file
):
    """Schema-valid params can still be impossible for a particular spectrum —
    here a crop window entirely outside the measured range. That is a client
    error about this spectrum, and the message names the failing step so the
    UI can point at it."""
    owner = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)

    resp = data_client.post(
        f"/spectra/{spectrum['id']}/preview",
        json={
            "steps": [
                {"type": "raman.crop", "params": {"min_cm1": 9000, "max_cm1": 9500}, "order": 0}
            ]
        },
    )

    assert resp.status_code == 422
    assert "raman.crop" in resp.json()["detail"]


def test_preview_caps_the_number_of_steps(data_client, make_user, make_raw_file):
    owner = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)

    resp = data_client.post(
        f"/spectra/{spectrum['id']}/preview",
        json={"steps": [{"type": "raman.snv", "params": {}, "order": i} for i in range(40)]},
    )

    assert resp.status_code == 422


def test_preview_applies_steps_in_order_not_request_order(data_client, make_user, make_raw_file):
    """Step order is scientifically load-bearing, so `order` — not position in
    the list — is what decides the sequence."""
    owner = make_user()
    data_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _spectrum(data_client, raw_file)

    shuffled = data_client.post(
        f"/spectra/{spectrum['id']}/preview",
        json={
            "steps": [
                {"type": "raman.snv", "params": {}, "order": 1},
                {"type": "raman.crop", "params": {"min_cm1": 150, "max_cm1": 450}, "order": 0},
            ]
        },
    ).json()
    in_order = data_client.post(
        f"/spectra/{spectrum['id']}/preview",
        json={
            "steps": [
                {"type": "raman.crop", "params": {"min_cm1": 150, "max_cm1": 450}, "order": 0},
                {"type": "raman.snv", "params": {}, "order": 1},
            ]
        },
    ).json()

    assert shuffled == in_order
    assert shuffled["wavenumbers"] == [200.0, 300.0, 400.0]


def test_preview_downsamples_above_max_points(data_client, make_user, make_raw_file):
    owner = make_user()
    data_client.set_current_user(owner)
    lines = "".join(f"{i} {np.sin(i / 50.0):.6f}\n" for i in range(5000))
    raw_file = make_raw_file(owner, content=lines.encode())
    spectrum = _spectrum(data_client, raw_file)

    body = data_client.post(
        f"/spectra/{spectrum['id']}/preview", json={"steps": [], "max_points": 500}
    ).json()

    assert body["downsampled"] is True
    assert body["total_points"] == 5000
    assert len(body["wavenumbers"]) <= 500
