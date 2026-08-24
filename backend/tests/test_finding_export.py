"""Finding-level export: citation, and the ZIP bundle.

The bundle is the "take this away and reproduce it" artifact, so the bar is
that raw + ledger genuinely regenerates processed — not that a zip file
came back.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

import pytest

from tests.test_findings import _finding, _spectrum


def _data_rows(text: str) -> list[str]:
    return [
        line
        for line in text.splitlines()
        if line and not line.startswith("#") and not line.startswith("wavenumber")
    ]


def _crop(client, raw_file_id: str, spectrum_id: str) -> None:
    resp = client.post(
        f"/raw-files/{raw_file_id}/ledgers",
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


def _published_finding(client, make_raw_file, owner):
    """A published finding holding one published, cropped spectrum."""
    raw_file = make_raw_file(owner)
    spectrum = client.post("/spectra", json={"raw_file_id": str(raw_file.id)}).json()
    _crop(client, str(raw_file.id), spectrum["id"])
    published_spectrum = client.post(
        f"/spectra/{spectrum['id']}/publish", json={"license_id": "CC-BY-4.0"}
    ).json()

    finding = _finding(client, title="Bundled finding")
    client.post(f"/findings/{finding['id']}/spectra", json={"spectrum_id": spectrum["id"]})
    resp = client.post(f"/findings/{finding['id']}/publish", json={"license_id": "CC-BY-4.0"})
    assert resp.status_code == 200, resp.text
    return resp.json(), published_spectrum


# ------------------------------------------------------------------ citation


@pytest.mark.parametrize("fmt", ["bibtex", "ris", "text"])
def test_finding_citation_renders(fclient, make_user, make_raw_file, fmt):
    owner = make_user()
    fclient.set_current_user(owner)
    finding, _ = _published_finding(fclient, make_raw_file, owner)

    resp = fclient.get(f"/findings/{finding['id']}/citation?format={fmt}")

    assert resp.status_code == 200, resp.text
    assert finding["accession"] in resp.text


def test_finding_citation_names_the_contributor(fclient, make_user, make_raw_file):
    owner = make_user()
    owner.display_name = "Ada Lovelace"
    fclient.set_current_user(owner)
    finding, _ = _published_finding(fclient, make_raw_file, owner)

    text = fclient.get(f"/findings/{finding['id']}/citation?format=text").text

    assert "Ada Lovelace" in text


def test_finding_citation_can_be_downloaded(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    finding, _ = _published_finding(fclient, make_raw_file, owner)

    resp = fclient.get(f"/findings/{finding['id']}/citation?download=true")

    assert ".bib" in resp.headers["content-disposition"]


# -------------------------------------------------------------------- bundle


def _bundle(client, finding):
    resp = client.get(f"/findings/{finding['id']}/bundle")
    assert resp.status_code == 200, resp.text
    return resp, zipfile.ZipFile(io.BytesIO(resp.content))


def test_bundle_layout_is_complete(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    finding, spectrum = _published_finding(fclient, make_raw_file, owner)

    resp, archive = _bundle(fclient, finding)
    root = finding["accession"]
    names = archive.namelist()

    assert resp.headers["content-type"] == "application/zip"
    assert root in resp.headers["content-disposition"]
    assert f"{root}/README.txt" in names
    assert f"{root}/CITATION.bib" in names
    assert f"{root}/manifest.json" in names
    assert f"{root}/spectra/{spectrum['accession']}_raw.csv" in names
    assert f"{root}/spectra/{spectrum['accession']}_processed.csv" in names
    assert f"{root}/spectra/{spectrum['accession']}_ledger.json" in names


def test_bundle_ledger_records_the_applied_steps(fclient, make_user, make_raw_file):
    """The ledger is what makes the bundle reproducible rather than just a
    folder of numbers."""
    owner = make_user()
    fclient.set_current_user(owner)
    finding, spectrum = _published_finding(fclient, make_raw_file, owner)

    _resp, archive = _bundle(fclient, finding)
    ledger = json.loads(
        archive.read(f"{finding['accession']}/spectra/{spectrum['accession']}_ledger.json")
    )

    assert ledger["spectrum"] == spectrum["accession"]
    assert ledger["steps"][0]["type"] == "raman.crop"


def test_bundle_raw_and_processed_actually_differ(fclient, make_user, make_raw_file):
    """Guards against writing both files from the same arrays — which would
    look right in the listing and be useless in practice."""
    owner = make_user()
    fclient.set_current_user(owner)
    finding, spectrum = _published_finding(fclient, make_raw_file, owner)

    _resp, archive = _bundle(fclient, finding)
    root, stem = finding["accession"], spectrum["accession"]
    raw = archive.read(f"{root}/spectra/{stem}_raw.csv").decode()
    processed = archive.read(f"{root}/spectra/{stem}_processed.csv").decode()

    assert raw != processed
    # make_raw_file writes 6 points; the crop keeps 3.
    assert len(_data_rows(raw)) == 6
    assert len(_data_rows(processed)) == 3


def test_bundle_manifest_checksums_verify(fclient, make_user, make_raw_file):
    """A manifest whose checksums don't verify is worse than no manifest."""
    owner = make_user()
    fclient.set_current_user(owner)
    finding, _ = _published_finding(fclient, make_raw_file, owner)

    _resp, archive = _bundle(fclient, finding)
    root = finding["accession"]
    manifest = json.loads(archive.read(f"{root}/manifest.json"))

    assert manifest["finding"]["accession"] == root
    assert manifest["citation"]
    for entry in manifest["spectra"]:
        for record in entry["files"].values():
            payload = archive.read(f"{root}/{record['path']}")
            assert hashlib.sha256(payload).hexdigest() == record["sha256"]


def test_bundle_readme_explains_how_to_cite(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    finding, _ = _published_finding(fclient, make_raw_file, owner)

    _resp, archive = _bundle(fclient, finding)
    readme = archive.read(f"{finding['accession']}/README.txt").decode()

    assert "HOW TO CITE" in readme
    assert finding["accession"] in readme


def test_bundle_is_public_for_a_published_finding(fclient, make_user, make_raw_file):
    owner = make_user()
    fclient.set_current_user(owner)
    finding, _ = _published_finding(fclient, make_raw_file, owner)

    fclient.set_current_user(None)
    assert fclient.get(f"/findings/{finding['id']}/bundle").status_code == 200


def test_draft_finding_export_is_private(fclient, make_user, make_raw_file):
    owner = make_user()
    other = make_user()
    fclient.set_current_user(owner)
    spectrum = _spectrum(fclient, make_raw_file, owner, publish=True)
    finding = _finding(fclient, title="Private draft")
    fclient.post(f"/findings/{finding['id']}/spectra", json={"spectrum_id": spectrum["id"]})

    for viewer in (other, None):
        fclient.set_current_user(viewer)
        assert fclient.get(f"/findings/{finding['id']}/bundle").status_code == 404
        assert fclient.get(f"/findings/{finding['id']}/citation").status_code == 404
