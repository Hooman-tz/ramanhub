"""Tests for POST /spectra/{id}/fork — copying a readable spectrum into the
caller's workspace so they can process it (ledger creation requires owning
the raw file; forking is how anyone experiments on public spectra)."""
from __future__ import annotations

import uuid


def _publish_spectrum_with_ledger(app_client, owner, raw_file) -> dict:
    spectrum = app_client.post(
        "/spectra",
        json={"raw_file_id": str(raw_file.id), "title": "Source", "material_type": "quartz"},
    ).json()
    ledger = app_client.post(
        f"/raw-files/{raw_file.id}/ledgers",
        json={"steps": [{"type": "raman.snv", "params": {}, "order": 0}]},
    )
    assert ledger.status_code == 201, ledger.text
    patched = app_client.patch(
        f"/spectra/{spectrum['id']}", json={"current_ledger_id": ledger.json()["ledger_id"]}
    )
    assert patched.status_code == 200, patched.text
    published = app_client.post(
        f"/spectra/{spectrum['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert published.status_code == 200, published.text
    return published.json()


def test_fork_published_spectrum_copies_content_and_replays_ledger(
    app_client, make_user, make_raw_file, fake_s3
):
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    source = _publish_spectrum_with_ledger(app_client, owner, raw_file)

    forker = make_user()
    app_client.set_current_user(forker)
    resp = app_client.post(f"/spectra/{source['id']}/fork")

    assert resp.status_code == 201, resp.text
    fork = resp.json()
    assert fork["owner_id"] == str(forker.id)
    assert fork["state"] == "draft"
    assert fork["title"] == "Source (fork)"
    assert fork["material_type"] == "quartz"
    assert fork["raw_file_id"] != source["raw_file_id"]
    # The ledger was replayed onto the fork's own raw file.
    assert fork["current_ledger_id"] is not None
    assert fork["current_ledger_id"] != source["current_ledger_id"]
    assert [s["type"] for s in fork["ledger_steps"]] == ["raman.snv"]
    # Publish state / license / DOI are NOT copied.
    assert fork["license_id"] is None
    assert fork["doi"] is None

    # The raw bytes were physically copied to a forker-scoped key.
    fork_keys = [key for (_bucket, key) in fake_s3 if key.startswith(str(forker.id))]
    assert len(fork_keys) == 1


def test_forker_can_process_their_fork(app_client, make_user, make_raw_file):
    """The whole point: ledger creation on the forked raw file succeeds for
    the forker (it 404s on the source's raw file, which they don't own)."""
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    source = _publish_spectrum_with_ledger(app_client, owner, raw_file)

    forker = make_user()
    app_client.set_current_user(forker)
    fork = app_client.post(f"/spectra/{source['id']}/fork").json()

    denied = app_client.post(
        f"/raw-files/{source['raw_file_id']}/ledgers",
        json={"steps": [{"type": "raman.snv", "params": {}, "order": 0}]},
    )
    assert denied.status_code == 404

    allowed = app_client.post(
        f"/raw-files/{fork['raw_file_id']}/ledgers",
        json={
            "steps": [
                {"type": "raman.snv", "params": {}, "order": 0},
                {"type": "raman.normalize.minmax", "params": {}, "order": 1},
            ]
        },
    )
    assert allowed.status_code == 201, allowed.text


def test_cannot_fork_someone_elses_draft(app_client, make_user, make_raw_file):
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    draft = app_client.post("/spectra", json={"raw_file_id": str(raw_file.id)}).json()

    other = make_user()
    app_client.set_current_user(other)
    assert app_client.post(f"/spectra/{draft['id']}/fork").status_code == 404


def test_fork_requires_authentication(app_client, make_user, make_raw_file):
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    source = _publish_spectrum_with_ledger(app_client, owner, raw_file)

    app_client.set_current_user(None)
    assert app_client.post(f"/spectra/{source['id']}/fork").status_code == 401


def test_fork_of_unknown_spectrum_is_404(app_client, make_user):
    user = make_user()
    app_client.set_current_user(user)
    assert app_client.post(f"/spectra/{uuid.uuid4()}/fork").status_code == 404


def test_forked_draft_is_invisible_to_the_source_owner(
    app_client, make_user, make_raw_file
):
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    source = _publish_spectrum_with_ledger(app_client, owner, raw_file)

    forker = make_user()
    app_client.set_current_user(forker)
    fork = app_client.post(f"/spectra/{source['id']}/fork").json()

    app_client.set_current_user(owner)
    assert app_client.get(f"/spectra/{fork['id']}").status_code == 404
