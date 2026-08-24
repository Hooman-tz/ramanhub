"""Tests for `/spectra/{id}/download` and `/spectra/{id}/citation`.

Access control gets the most attention here: a download endpoint that skips
the owner-or-public rule is the most direct possible way to exfiltrate
another user's draft data.
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.routers import export, ledgers, spectra


@pytest.fixture()
def export_client(db_session):
    test_app = FastAPI()
    test_app.include_router(spectra.router)
    test_app.include_router(ledgers.router)
    test_app.include_router(export.router)

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


def _new_spectrum(client, raw_file, **fields) -> dict:
    payload = {"raw_file_id": str(raw_file.id), **fields}
    resp = client.post("/spectra", json=payload)
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


def _data_rows(text: str, delimiter: str = ","):
    return [
        line.split(delimiter)
        for line in text.splitlines()
        if line and not line.startswith("#") and not line.startswith("wavenumber")
    ]


# ------------------------------------------------------------------ formats


@pytest.mark.parametrize(
    ("fmt", "expected_media_type"),
    [
        ("csv", "text/csv"),
        ("tsv", "text/tab-separated-values"),
        ("json", "application/json"),
        ("jcamp", "chemical/x-jcamp-dx"),
    ],
)
def test_every_format_downloads(export_client, make_user, make_raw_file, fmt, expected_media_type):
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file)

    resp = export_client.get(f"/spectra/{spectrum['id']}/download?format={fmt}")

    assert resp.status_code == 200, resp.text
    assert expected_media_type in resp.headers["content-type"]
    assert "attachment" in resp.headers["content-disposition"]


def test_download_filename_uses_the_accession(export_client, make_user, make_raw_file):
    """The accession is the citable name; a file called <uuid>.csv on
    someone's disk is unidentifiable a month later."""
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file)

    resp = export_client.get(f"/spectra/{spectrum['id']}/download")

    assert spectrum["accession"] in resp.headers["content-disposition"]


def test_csv_contains_the_raw_values(export_client, make_user, make_raw_file):
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file)

    rows = _data_rows(export_client.get(f"/spectra/{spectrum['id']}/download").text)

    # make_raw_file's default fixture content.
    assert [r[0] for r in rows] == ["100.0", "200.0", "300.0", "400.0", "500.0", "600.0"]


def test_processed_stage_reflects_the_applied_ledger(
    export_client, make_user, make_raw_file
):
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file)
    _apply_crop(export_client, raw_file, spectrum["id"])

    rows = _data_rows(export_client.get(f"/spectra/{spectrum['id']}/download").text)

    assert [r[0] for r in rows] == ["200.0", "300.0", "400.0"]


def test_raw_stage_bypasses_the_ledger(export_client, make_user, make_raw_file):
    """Reproducing an analysis from scratch requires the untouched
    original."""
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file)
    _apply_crop(export_client, raw_file, spectrum["id"])

    rows = _data_rows(
        export_client.get(f"/spectra/{spectrum['id']}/download?stage=raw").text
    )

    assert len(rows) == 6


def test_export_records_the_processing_steps(export_client, make_user, make_raw_file):
    """A downloaded file must carry its own history — the ledger is the
    point of the platform."""
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file)
    _apply_crop(export_client, raw_file, spectrum["id"])

    text = export_client.get(f"/spectra/{spectrum['id']}/download").text

    assert "raman.crop@" in text
    assert "# stage: processed" in text


def test_raw_export_says_so(export_client, make_user, make_raw_file):
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file)

    text = export_client.get(f"/spectra/{spectrum['id']}/download?stage=raw").text

    assert "no processing applied" in text


def test_header_comment_can_be_turned_off(export_client, make_user, make_raw_file):
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file)

    text = export_client.get(
        f"/spectra/{spectrum['id']}/download?include_header_comment=false"
    ).text

    assert not text.startswith("#")


def test_json_export_carries_metadata(export_client, make_user, make_raw_file):
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file, title="Cellulose")

    payload = json.loads(
        export_client.get(f"/spectra/{spectrum['id']}/download?format=json").text
    )

    assert payload["n_points"] == 6
    assert payload["metadata"]["title"] == "Cellulose"
    assert payload["metadata"]["accession"] == spectrum["accession"]


def test_unknown_format_is_rejected(export_client, make_user, make_raw_file):
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file)

    assert (
        export_client.get(f"/spectra/{spectrum['id']}/download?format=xlsx").status_code == 422
    )


# ----------------------------------------------------------------- citation


@pytest.mark.parametrize("fmt", ["bibtex", "ris", "text"])
def test_citation_formats_render(export_client, make_user, make_raw_file, fmt):
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file, title="Cellulose")

    resp = export_client.get(f"/spectra/{spectrum['id']}/citation?format={fmt}")

    assert resp.status_code == 200, resp.text
    assert spectrum["accession"] in resp.text


def test_citation_is_inline_by_default(export_client, make_user, make_raw_file):
    """So the UI can render a copy-to-clipboard block without kicking off a
    file download."""
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file)

    resp = export_client.get(f"/spectra/{spectrum['id']}/citation")

    assert "content-disposition" not in resp.headers


def test_citation_can_be_downloaded(export_client, make_user, make_raw_file):
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file)

    resp = export_client.get(f"/spectra/{spectrum['id']}/citation?download=true")

    assert ".bib" in resp.headers["content-disposition"]


def test_citation_includes_the_license_once_published(
    export_client, make_user, make_raw_file
):
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file)
    published = export_client.post(
        f"/spectra/{spectrum['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert published.status_code == 200, published.text

    text = export_client.get(f"/spectra/{spectrum['id']}/citation?format=text").text

    assert "Attribution" in text or "CC" in text


# ----------------------------------------------------------- access control


def test_cannot_download_someone_elses_draft(export_client, make_user, make_raw_file):
    """The most direct exfiltration path there is — it must 404 for
    everyone but the owner."""
    owner = make_user()
    other = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file)

    for viewer in (other, None):
        export_client.set_current_user(viewer)
        for fmt in ("csv", "tsv", "json", "jcamp"):
            assert (
                export_client.get(
                    f"/spectra/{spectrum['id']}/download?format={fmt}"
                ).status_code
                == 404
            )
        assert (
            export_client.get(f"/spectra/{spectrum['id']}/download?stage=raw").status_code
            == 404
        )
        assert export_client.get(f"/spectra/{spectrum['id']}/citation").status_code == 404


def test_published_spectra_download_anonymously(export_client, make_user, make_raw_file):
    """Zero-friction reuse of public data is the whole point of the
    commons."""
    owner = make_user()
    export_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _new_spectrum(export_client, raw_file)
    export_client.post(f"/spectra/{spectrum['id']}/publish", json={"license_id": "CC-BY-4.0"})

    export_client.set_current_user(None)

    assert export_client.get(f"/spectra/{spectrum['id']}/download").status_code == 200
    assert export_client.get(f"/spectra/{spectrum['id']}/citation").status_code == 200


def test_download_404s_for_unknown_spectrum(export_client, make_user):
    export_client.set_current_user(make_user())
    missing = "00000000-0000-0000-0000-000000000000"

    assert export_client.get(f"/spectra/{missing}/download").status_code == 404
    assert export_client.get(f"/spectra/{missing}/citation").status_code == 404
