"""Tests for the analysis endpoints (`/spectra/{id}/peaks`, `/analysis/pca`,
`/analysis/hca`).

The access-control block at the bottom is the important part: the
multi-spectrum endpoints take a LIST of IDs, which is exactly the shape that
invites a check-the-first-one-only bug. Owning one input must never grant
read access to someone else's draft in the same request.
"""
from __future__ import annotations

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.routers import analysis, ledgers, spectra


@pytest.fixture()
def analysis_client(db_session):
    test_app = FastAPI()
    test_app.include_router(spectra.router)
    test_app.include_router(ledgers.router)
    test_app.include_router(analysis.router)

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


def _peaky_content(centers=(600.0, 1200.0), offset=0.0) -> bytes:
    """A two-column text spectrum with Gaussian bands at `centers` — the
    same shape `make_raw_file` writes, just with real peaks in it."""
    x = np.linspace(400.0, 1800.0, 400)
    y = np.zeros_like(x) + offset
    for center in centers:
        y += 100.0 * np.exp(-((x - center) ** 2) / (2 * 15.0**2))
    return "".join(f"{a:.4f} {b:.6f}\n" for a, b in zip(x, y, strict=True)).encode()


def _make_spectrum(client, make_raw_file, owner, centers=(600.0, 1200.0), publish=False) -> str:
    raw_file = make_raw_file(owner, content=_peaky_content(centers))
    resp = client.post("/spectra", json={"raw_file_id": str(raw_file.id)})
    assert resp.status_code == 201, resp.text
    spectrum_id = resp.json()["id"]
    if publish:
        pub = client.post(f"/spectra/{spectrum_id}/publish", json={"license_id": "CC-BY-4.0"})
        assert pub.status_code == 200, pub.text
    return spectrum_id


# ------------------------------------------------------------------ catalog


def test_catalog_exposes_schemas_for_every_analysis(analysis_client):
    body = analysis_client.get("/analysis/catalog").json()

    for key in ("peaks", "pca", "hca"):
        assert body[key]["version"]
        assert body[key]["param_schema"]["type"] == "object"
        assert isinstance(body[key]["defaults"], dict)


def test_catalog_defaults_are_all_declared_in_the_schema(analysis_client):
    """The frontend renders inputs from `param_schema` and seeds them from
    `defaults`; a default with no matching property would render nothing."""
    body = analysis_client.get("/analysis/catalog").json()

    for key in ("peaks", "pca", "hca"):
        properties = set(body[key]["param_schema"]["properties"])
        assert set(body[key]["defaults"]) <= properties


# -------------------------------------------------------------------- peaks


def test_detects_the_known_bands(analysis_client, make_user, make_raw_file):
    owner = make_user()
    analysis_client.set_current_user(owner)
    spectrum_id = _make_spectrum(analysis_client, make_raw_file, owner)

    body = analysis_client.get(f"/spectra/{spectrum_id}/peaks").json()

    assert len(body["peaks"]) == 2
    found = [p["wavenumber"] for p in body["peaks"]]
    assert abs(found[0] - 600.0) < 6.0
    assert abs(found[1] - 1200.0) < 6.0


def test_peak_response_echoes_params_and_version(analysis_client, make_user, make_raw_file):
    """A peak list quoted in a Finding has to carry what produced it, or it
    isn't reproducible."""
    owner = make_user()
    analysis_client.set_current_user(owner)
    spectrum_id = _make_spectrum(analysis_client, make_raw_file, owner)

    body = analysis_client.get(f"/spectra/{spectrum_id}/peaks?max_peaks=1").json()

    assert body["params"]["max_peaks"] == 1
    assert body["version"]
    assert body["stage"] in {"raw", "processed"}
    assert len(body["peaks"]) == 1


def test_peaks_carry_width_and_area(analysis_client, make_user, make_raw_file):
    owner = make_user()
    analysis_client.set_current_user(owner)
    spectrum_id = _make_spectrum(analysis_client, make_raw_file, owner)

    peaks = analysis_client.get(f"/spectra/{spectrum_id}/peaks").json()["peaks"]

    for peak in peaks:
        assert peak["fwhm_cm1"] > 0
        assert peak["area"] > 0
        assert peak["prominence"] > 0


def test_peaks_404_for_unknown_spectrum(analysis_client, make_user):
    analysis_client.set_current_user(make_user())
    missing = "00000000-0000-0000-0000-000000000000"
    assert analysis_client.get(f"/spectra/{missing}/peaks").status_code == 404


def test_peaks_reject_out_of_range_params(analysis_client, make_user, make_raw_file):
    owner = make_user()
    analysis_client.set_current_user(owner)
    spectrum_id = _make_spectrum(analysis_client, make_raw_file, owner)

    assert (
        analysis_client.get(f"/spectra/{spectrum_id}/peaks?prominence_fraction=2").status_code
        == 422
    )
    assert analysis_client.get(f"/spectra/{spectrum_id}/peaks?max_peaks=0").status_code == 422


# ---------------------------------------------------------------------- PCA


def test_pca_returns_scores_aligned_with_requested_ids(
    analysis_client, make_user, make_raw_file
):
    owner = make_user()
    analysis_client.set_current_user(owner)
    ids = [
        _make_spectrum(analysis_client, make_raw_file, owner, centers=(600.0, 1200.0)),
        _make_spectrum(analysis_client, make_raw_file, owner, centers=(900.0, 1500.0)),
        _make_spectrum(analysis_client, make_raw_file, owner, centers=(600.0, 1210.0)),
    ]

    resp = analysis_client.post("/analysis/pca", json={"spectrum_ids": ids, "n_components": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["spectrum_ids"] == ids
    assert len(body["scores"]) == 3
    assert body["n_components"] == 2
    assert len(body["loadings"]) == 2
    assert len(body["loadings"][0]) == len(body["wavenumbers"])


def test_pca_requires_at_least_two_spectra(analysis_client, make_user, make_raw_file):
    owner = make_user()
    analysis_client.set_current_user(owner)
    one = _make_spectrum(analysis_client, make_raw_file, owner)

    assert analysis_client.post("/analysis/pca", json={"spectrum_ids": [one]}).status_code == 422


def test_pca_rejects_duplicate_ids(analysis_client, make_user, make_raw_file):
    """Duplicates would show up as two identical points in the plot and a
    zero-distance pair in HCA — a confusing figure, not an error the user
    would spot."""
    owner = make_user()
    analysis_client.set_current_user(owner)
    one = _make_spectrum(analysis_client, make_raw_file, owner)

    resp = analysis_client.post("/analysis/pca", json={"spectrum_ids": [one, one]})
    assert resp.status_code == 422
    assert "Duplicate" in resp.json()["detail"]


def test_pca_404s_on_unknown_member(analysis_client, make_user, make_raw_file):
    owner = make_user()
    analysis_client.set_current_user(owner)
    one = _make_spectrum(analysis_client, make_raw_file, owner)
    missing = "00000000-0000-0000-0000-000000000000"

    resp = analysis_client.post("/analysis/pca", json={"spectrum_ids": [one, missing]})
    assert resp.status_code == 404


def test_pca_422s_on_non_overlapping_spectra(analysis_client, make_user, make_raw_file):
    """Two spectra measured over disjoint ranges can't be compared without
    extrapolating — that has to surface as a clear error, not a silent
    plot."""
    owner = make_user()
    analysis_client.set_current_user(owner)

    low = make_raw_file(owner, content=b"100 1.0\n110 5.0\n120 2.0\n130 1.0\n")
    high = make_raw_file(owner, content=b"900 1.0\n910 5.0\n920 2.0\n930 1.0\n")
    ids = []
    for raw_file in (low, high):
        resp = analysis_client.post("/spectra", json={"raw_file_id": str(raw_file.id)})
        ids.append(resp.json()["id"])

    resp = analysis_client.post("/analysis/pca", json={"spectrum_ids": ids})
    assert resp.status_code == 422
    assert "overlapping" in resp.json()["detail"]


# ---------------------------------------------------------------------- HCA


def test_hca_returns_a_tree(analysis_client, make_user, make_raw_file):
    owner = make_user()
    analysis_client.set_current_user(owner)
    ids = [
        _make_spectrum(analysis_client, make_raw_file, owner, centers=(600.0, 1200.0)),
        _make_spectrum(analysis_client, make_raw_file, owner, centers=(900.0, 1500.0)),
        _make_spectrum(analysis_client, make_raw_file, owner, centers=(605.0, 1205.0)),
    ]

    resp = analysis_client.post(
        "/analysis/hca", json={"spectrum_ids": ids, "n_clusters": 2}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert len(body["linkage_matrix"]) == 2
    assert sorted(body["leaf_order"]) == [0, 1, 2]
    # The two 600/1200 spectra are the same material; the 900/1500 is not.
    assert body["labels"][0] == body["labels"][2] != body["labels"][1]


def test_hca_rejects_ward_with_correlation(analysis_client, make_user, make_raw_file):
    owner = make_user()
    analysis_client.set_current_user(owner)
    ids = [
        _make_spectrum(analysis_client, make_raw_file, owner),
        _make_spectrum(analysis_client, make_raw_file, owner, centers=(900.0,)),
    ]

    resp = analysis_client.post(
        "/analysis/hca",
        json={"spectrum_ids": ids, "metric": "correlation", "method": "ward"},
    )
    assert resp.status_code == 422
    assert "euclidean" in resp.json()["detail"]


# ----------------------------------------------------------- access control


def test_peaks_on_someone_elses_draft_are_404(analysis_client, make_user, make_raw_file):
    owner = make_user()
    other = make_user()
    analysis_client.set_current_user(owner)
    spectrum_id = _make_spectrum(analysis_client, make_raw_file, owner)

    analysis_client.set_current_user(other)
    assert analysis_client.get(f"/spectra/{spectrum_id}/peaks").status_code == 404

    analysis_client.set_current_user(None)
    assert analysis_client.get(f"/spectra/{spectrum_id}/peaks").status_code == 404


def test_peaks_on_published_spectra_are_public(analysis_client, make_user, make_raw_file):
    owner = make_user()
    analysis_client.set_current_user(owner)
    spectrum_id = _make_spectrum(analysis_client, make_raw_file, owner, publish=True)

    analysis_client.set_current_user(None)
    assert analysis_client.get(f"/spectra/{spectrum_id}/peaks").status_code == 200


def test_pca_cannot_read_someone_elses_draft_via_a_mixed_list(
    analysis_client, make_user, make_raw_file
):
    """The bug this endpoint's shape invites: owning one member of the list
    must NOT leak the intensity values of another user's draft through the
    returned scores. Every ID is checked individually."""
    owner = make_user()
    attacker = make_user()

    analysis_client.set_current_user(owner)
    victim_draft = _make_spectrum(analysis_client, make_raw_file, owner)

    analysis_client.set_current_user(attacker)
    mine = _make_spectrum(analysis_client, make_raw_file, attacker, centers=(900.0,))
    published = _make_spectrum(
        analysis_client, make_raw_file, attacker, centers=(700.0,), publish=True
    )

    resp = analysis_client.post(
        "/analysis/pca", json={"spectrum_ids": [mine, published, victim_draft]}
    )
    assert resp.status_code == 404

    resp = analysis_client.post(
        "/analysis/hca", json={"spectrum_ids": [mine, published, victim_draft]}
    )
    assert resp.status_code == 404


def test_pca_over_published_spectra_works_anonymously(
    analysis_client, make_user, make_raw_file
):
    owner = make_user()
    analysis_client.set_current_user(owner)
    ids = [
        _make_spectrum(analysis_client, make_raw_file, owner, centers=(600.0,), publish=True),
        _make_spectrum(analysis_client, make_raw_file, owner, centers=(900.0,), publish=True),
    ]

    analysis_client.set_current_user(None)
    resp = analysis_client.post("/analysis/pca", json={"spectrum_ids": ids})
    assert resp.status_code == 200, resp.text
