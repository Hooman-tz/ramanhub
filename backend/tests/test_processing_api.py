import uuid
from datetime import UTC, datetime, timedelta

from app.models.spectrum import Spectrum


def _create_spectrum(app_client, raw_file, title="Test spectrum"):
    resp = app_client.post("/spectra", json={"raw_file_id": str(raw_file.id), "title": title})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_draft_readable_by_owner_only(app_client, make_user, make_raw_file):
    owner = make_user()
    other = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(app_client, raw_file)
    assert spectrum["state"] == "draft"

    resp = app_client.get(f"/spectra/{spectrum['id']}")
    assert resp.status_code == 200
    assert resp.json()["state"] == "draft"

    app_client.set_current_user(other)
    resp = app_client.get(f"/spectra/{spectrum['id']}")
    assert resp.status_code == 404

    app_client.set_current_user(None)
    resp = app_client.get(f"/spectra/{spectrum['id']}")
    assert resp.status_code == 404


def test_publish_requires_license_id(app_client, make_user, make_raw_file):
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(app_client, raw_file)

    resp = app_client.post(f"/spectra/{spectrum['id']}/publish", json={})
    assert resp.status_code == 422


def test_publish_then_readable_by_anyone(app_client, make_user, make_raw_file):
    owner = make_user()
    other = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(app_client, raw_file)

    resp = app_client.post(
        f"/spectra/{spectrum['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "published"

    app_client.set_current_user(other)
    resp = app_client.get(f"/spectra/{spectrum['id']}")
    assert resp.status_code == 200
    assert resp.json()["state"] == "published"

    app_client.set_current_user(None)
    resp = app_client.get(f"/spectra/{spectrum['id']}")
    assert resp.status_code == 200


def test_embargoed_hidden_until_release_then_effective_state_flips(
    app_client, make_user, make_raw_file, db_session
):
    owner = make_user()
    other = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(app_client, raw_file)

    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    resp = app_client.post(
        f"/spectra/{spectrum['id']}/publish",
        json={"license_id": "CC-BY-4.0", "embargo_release_at": future},
    )
    assert resp.status_code == 200
    assert resp.json()["state"] == "embargoed"

    app_client.set_current_user(other)
    resp = app_client.get(f"/spectra/{spectrum['id']}")
    assert resp.status_code == 404

    app_client.set_current_user(None)
    resp = app_client.get(f"/spectra/{spectrum['id']}")
    assert resp.status_code == 404

    # owner can always see their own embargoed spectrum
    app_client.set_current_user(owner)
    resp = app_client.get(f"/spectra/{spectrum['id']}")
    assert resp.status_code == 200
    assert resp.json()["state"] == "embargoed"

    # simulate the release date having passed (freeze-by-value rather than
    # manipulating real time)
    row = db_session.get(Spectrum, uuid.UUID(spectrum["id"]))
    row.embargo_release_at = datetime.now(UTC) - timedelta(days=1)
    db_session.add(row)
    db_session.commit()

    app_client.set_current_user(other)
    resp = app_client.get(f"/spectra/{spectrum['id']}")
    assert resp.status_code == 200
    assert resp.json()["state"] == "published"


def test_embargo_requires_future_release_date(app_client, make_user, make_raw_file):
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(app_client, raw_file)

    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    resp = app_client.post(
        f"/spectra/{spectrum['id']}/publish",
        json={"license_id": "CC-BY-4.0", "embargo_release_at": past},
    )
    assert resp.status_code == 422


def test_release_embargo_early(app_client, make_user, make_raw_file):
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _create_spectrum(app_client, raw_file)

    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    app_client.post(
        f"/spectra/{spectrum['id']}/publish",
        json={"license_id": "CC-BY-4.0", "embargo_release_at": future},
    )

    resp = app_client.post(f"/spectra/{spectrum['id']}/release-embargo")
    assert resp.status_code == 200
    assert resp.json()["state"] == "published"


def test_create_ledger_and_dedupe(app_client, make_user, make_raw_file):
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)

    body = {"steps": [{"type": "raman.snv", "params": {}, "order": 1}]}
    resp1 = app_client.post(f"/raw-files/{raw_file.id}/ledgers", json=body)
    assert resp1.status_code == 201, resp1.text
    data1 = resp1.json()
    assert data1["reused_existing"] is False
    assert data1["processed"]["length"] > 0

    resp2 = app_client.post(f"/raw-files/{raw_file.id}/ledgers", json=body)
    assert resp2.status_code == 201
    data2 = resp2.json()
    assert data2["reused_existing"] is True
    assert data2["ledger_hash"] == data1["ledger_hash"]
    assert data2["ledger_id"] == data1["ledger_id"]


def test_create_ledger_unknown_step_type_rejected(app_client, make_user, make_raw_file):
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)

    body = {"steps": [{"type": "raman.not_a_real_step", "params": {}, "order": 1}]}
    resp = app_client.post(f"/raw-files/{raw_file.id}/ledgers", json=body)
    assert resp.status_code == 422


def test_create_ledger_with_invalid_params_rejected(app_client, make_user, make_raw_file):
    """Param-schema validation runs against the seeded `LedgerStepDefinition`
    rows, which are generated from the algorithm registry — so a new
    algorithm's schema is enforced the moment it ships."""
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)

    body = {
        "steps": [
            {
                "type": "raman.smooth.savitzky_golay",
                "params": {"window_length": "wide"},
                "order": 1,
            }
        ]
    }
    resp = app_client.post(f"/raw-files/{raw_file.id}/ledgers", json=body)
    assert resp.status_code == 422


def test_ledger_with_an_axis_changing_step_shortens_the_cached_axis(
    app_client, make_user, make_raw_file, db_session
):
    """`raman.crop` is one of two steps that rewrite the wavenumber axis, so
    the processed cache has to store the transformed axis rather than the raw
    one — otherwise every downstream reader (chart, SNR, similarity search)
    would pair cropped intensities with full-length wavenumbers."""
    from app.models.processing_ledger import ProcessingLedger
    from app.processing.cache import get_or_compute
    from app.schemas.ledger import Ledger, LedgerStep

    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)

    body = {
        "steps": [{"type": "raman.crop", "params": {"min_cm1": 150, "max_cm1": 450}, "order": 1}]
    }
    resp = app_client.post(f"/raw-files/{raw_file.id}/ledgers", json=body)
    assert resp.status_code == 201, resp.text
    # The fixture spectrum covers 100-600 cm-1 in 100 cm-1 steps; 150-450
    # keeps three points.
    assert resp.json()["processed"]["length"] == 3

    ledger_row = db_session.get(ProcessingLedger, uuid.UUID(resp.json()["ledger_id"]))
    ledger = Ledger(
        schema_version=ledger_row.schema_version,
        raw_file_id=ledger_row.raw_file_id,
        steps=[LedgerStep.model_validate(step) for step in ledger_row.steps],
    )
    wavenumbers, intensities = get_or_compute(raw_file.id, ledger, db_session)
    assert list(wavenumbers) == [200.0, 300.0, 400.0]
    assert wavenumbers.size == intensities.size
