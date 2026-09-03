"""Regression tests for reproducible multi-spectrum analysis contracts."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.analysis.engine import build_input_manifest, execute_run, sign_run, software_versions
from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.models.analysis import AnalysisDataset, AnalysisDatasetSpectrum, AnalysisRun
from app.models.enums import Modality, SpectrumState
from app.models.spectrum import Spectrum
from app.routers import analysis


def _analysis_client(db_session):
    app = FastAPI()
    app.include_router(analysis.router)
    current = {"user": None}

    def get_test_db():
        yield db_session

    def get_test_user():
        if current["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current["user"]

    app.dependency_overrides[get_db] = get_test_db
    app.dependency_overrides[get_current_user] = get_test_user
    app.dependency_overrides[get_current_user_optional] = lambda: current["user"]
    client = TestClient(app)
    client.set_current_user = lambda user: current.__setitem__("user", user)
    return client


def _spectrum(db_session, owner, raw_file, state=SpectrumState.draft):
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


def test_dataset_can_mix_owned_private_and_visible_public_spectra(
    db_session, make_user, make_raw_file
):
    owner, other = make_user(), make_user()
    private = _spectrum(db_session, owner, make_raw_file(owner))
    public = _spectrum(db_session, other, make_raw_file(other), SpectrumState.published)
    client = _analysis_client(db_session)
    client.set_current_user(owner)

    response = client.post(
        "/analysis/datasets",
        json={"name": "Mixed Raman set", "spectrum_ids": [str(private.id), str(public.id)]},
    )

    assert response.status_code == 201, response.text
    assert [item["id"] for item in response.json()["spectra"]] == [str(private.id), str(public.id)]
    repeated = client.post(
        "/analysis/datasets",
        json={"name": "Mixed Raman set", "spectrum_ids": [str(private.id), str(public.id)]},
    )
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["id"] == response.json()["id"]


def test_dataset_rejects_another_users_private_spectrum(db_session, make_user, make_raw_file):
    owner, other = make_user(), make_user()
    owned = _spectrum(db_session, owner, make_raw_file(owner))
    private_other = _spectrum(db_session, other, make_raw_file(other))
    client = _analysis_client(db_session)
    client.set_current_user(owner)

    response = client.post(
        "/analysis/datasets",
        json={"name": "Not allowed", "spectrum_ids": [str(owned.id), str(private_other.id)]},
    )

    assert response.status_code == 404


def test_analysis_run_records_manifest_signature_and_deterministic_output(
    db_session, make_user, make_raw_file
):
    owner = make_user()
    first = _spectrum(
        db_session,
        owner,
        make_raw_file(
            owner,
            b"100 1\n135 2\n170 3\n205 5\n240 4\n275 2\n310 1\n345 3\n380 4\n415 6\n450 4\n485 2\n520 1\n555 2\n590 3\n600 4\n",
        ),
    )
    second = _spectrum(
        db_session,
        owner,
        make_raw_file(
            owner,
            b"100 2\n135 3\n170 4\n205 7\n240 5\n275 3\n310 2\n345 4\n380 5\n415 8\n450 5\n485 3\n520 2\n555 3\n590 4\n600 5\n",
        ),
    )
    dataset = AnalysisDataset(owner_id=owner.id, modality=Modality.raman, name="Repeatable")
    db_session.add(dataset)
    db_session.flush()
    db_session.add_all(
        [
            AnalysisDatasetSpectrum(dataset_id=dataset.id, spectrum_id=first.id, position=0),
            AnalysisDatasetSpectrum(dataset_id=dataset.id, spectrum_id=second.id, position=1),
        ]
    )
    run = AnalysisRun(
        dataset_id=dataset.id,
        owner_id=owner.id,
        analysis_type="pca",
        parameters={"components": 2, "grid_points": 16},
        input_manifest=build_input_manifest([first, second], db_session),
        software_versions=software_versions(),
        quality_checks={"status": "pending"},
        job_signature="pending",
    )
    db_session.add(run)
    db_session.flush()
    run.job_signature = sign_run(run)
    db_session.commit()

    output_one, checks_one, hash_one = execute_run(run, db_session)
    output_two, checks_two, hash_two = execute_run(run, db_session)

    assert checks_one["status"] == checks_two["status"] == "passed"
    assert hash_one == hash_two
    assert output_one == output_two
    assert len(run.input_manifest) == 2
    assert run.input_manifest[0]["raw_checksum_sha256"]


def test_dataset_folder_lifecycle_create_empty_add_dedupe_remove_rename(
    db_session, make_user, make_raw_file
):
    owner = make_user()
    a = _spectrum(db_session, owner, make_raw_file(owner))
    b = _spectrum(db_session, owner, make_raw_file(owner, b"100 2\n200 3\n300 4\n400 3\n"))
    client = _analysis_client(db_session)
    client.set_current_user(owner)

    # create empty
    created = client.post("/analysis/datasets", json={"name": "Folder"})
    assert created.status_code == 201, created.text
    dataset_id = created.json()["id"]
    assert created.json()["spectra"] == []
    assert created.json()["modality"] == "raman"

    # add two
    added = client.post(
        f"/analysis/datasets/{dataset_id}/spectra",
        json={"spectrum_ids": [str(a.id), str(b.id)]},
    )
    assert added.status_code == 200, added.text
    assert [s["id"] for s in added.json()["spectra"]] == [str(a.id), str(b.id)]

    # add duplicate -> idempotent no-op
    again = client.post(
        f"/analysis/datasets/{dataset_id}/spectra",
        json={"spectrum_ids": [str(a.id)]},
    )
    assert again.status_code == 200, again.text
    assert [s["id"] for s in again.json()["spectra"]] == [str(a.id), str(b.id)]

    # remove one
    removed = client.delete(f"/analysis/datasets/{dataset_id}/spectra/{a.id}")
    assert removed.status_code == 204
    assert [s["id"] for s in client.get(f"/analysis/datasets/{dataset_id}").json()["spectra"]] == [
        str(b.id)
    ]

    # removing a non-member -> 404
    assert client.delete(f"/analysis/datasets/{dataset_id}/spectra/{a.id}").status_code == 404

    # rename + edit description
    patched = client.patch(
        f"/analysis/datasets/{dataset_id}", json={"name": "Renamed", "description": "notes"}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Renamed"
    assert patched.json()["description"] == "notes"


def test_dataset_rename_to_existing_name_conflicts(db_session, make_user, make_raw_file):
    owner = make_user()
    client = _analysis_client(db_session)
    client.set_current_user(owner)
    first = client.post("/analysis/datasets", json={"name": "Alpha"}).json()
    client.post("/analysis/datasets", json={"name": "Beta"})

    clash = client.patch(f"/analysis/datasets/{first['id']}", json={"name": "Beta"})
    assert clash.status_code == 409, clash.text


def test_delete_dataset_removes_membership_but_keeps_spectra(db_session, make_user, make_raw_file):
    owner = make_user()
    a = _spectrum(db_session, owner, make_raw_file(owner))
    b = _spectrum(db_session, owner, make_raw_file(owner, b"100 2\n200 3\n300 4\n400 3\n"))
    client = _analysis_client(db_session)
    client.set_current_user(owner)
    dataset_id = client.post(
        "/analysis/datasets", json={"name": "Trash me", "spectrum_ids": [str(a.id), str(b.id)]}
    ).json()["id"]

    resp = client.delete(f"/analysis/datasets/{dataset_id}")
    assert resp.status_code == 204

    assert db_session.get(AnalysisDataset, dataset_id) is None
    assert (
        db_session.query(AnalysisDatasetSpectrum)
        .filter(AnalysisDatasetSpectrum.dataset_id == dataset_id)
        .count()
        == 0
    )
    # spectra themselves survive
    assert db_session.get(Spectrum, a.id) is not None
    assert db_session.get(Spectrum, b.id) is not None


def test_delete_dataset_with_runs_conflicts(db_session, make_user, make_raw_file):
    owner = make_user()
    a = _spectrum(db_session, owner, make_raw_file(owner))
    b = _spectrum(db_session, owner, make_raw_file(owner, b"100 2\n200 3\n300 4\n400 3\n500 2\n600 3\n"))
    dataset = AnalysisDataset(owner_id=owner.id, modality=Modality.raman, name="Has runs")
    db_session.add(dataset)
    db_session.flush()
    db_session.add_all(
        [
            AnalysisDatasetSpectrum(dataset_id=dataset.id, spectrum_id=a.id, position=0),
            AnalysisDatasetSpectrum(dataset_id=dataset.id, spectrum_id=b.id, position=1),
        ]
    )
    db_session.commit()
    client = _analysis_client(db_session)
    client.set_current_user(owner)
    run = client.post(
        f"/analysis/datasets/{dataset.id}/runs",
        json={"analysis_type": "pca", "components": 2, "grid_points": 16},
    )
    assert run.status_code == 202, run.text

    assert client.delete(f"/analysis/datasets/{dataset.id}").status_code == 409


def test_run_requires_at_least_two_spectra(db_session, make_user, make_raw_file):
    owner = make_user()
    a = _spectrum(db_session, owner, make_raw_file(owner))
    client = _analysis_client(db_session)
    client.set_current_user(owner)
    dataset_id = client.post("/analysis/datasets", json={"name": "Too small"}).json()["id"]
    client.post(f"/analysis/datasets/{dataset_id}/spectra", json={"spectrum_ids": [str(a.id)]})

    resp = client.post(
        f"/analysis/datasets/{dataset_id}/runs",
        json={"analysis_type": "pca", "components": 2, "grid_points": 16},
    )
    assert resp.status_code == 422, resp.text
    assert "at least two spectra" in resp.json()["detail"]


def test_dataset_folder_mutations_reject_non_owner(db_session, make_user, make_raw_file):
    owner, other = make_user(), make_user()
    a = _spectrum(db_session, owner, make_raw_file(owner))
    b = _spectrum(db_session, owner, make_raw_file(owner, b"100 2\n200 3\n300 4\n400 3\n"))
    client = _analysis_client(db_session)
    client.set_current_user(owner)
    dataset_id = client.post(
        "/analysis/datasets", json={"name": "Private folder", "spectrum_ids": [str(a.id), str(b.id)]}
    ).json()["id"]

    client.set_current_user(other)
    assert client.get(f"/analysis/datasets/{dataset_id}").status_code == 404
    assert client.patch(f"/analysis/datasets/{dataset_id}", json={"name": "hijack"}).status_code == 404
    assert client.delete(f"/analysis/datasets/{dataset_id}").status_code == 404
    assert (
        client.post(
            f"/analysis/datasets/{dataset_id}/spectra", json={"spectrum_ids": [str(a.id)]}
        ).status_code
        == 404
    )
    assert client.delete(f"/analysis/datasets/{dataset_id}/spectra/{a.id}").status_code == 404


def test_run_cancel_transitions_pending_job_without_executing(db_session, make_user, make_raw_file):
    owner = make_user()
    first = _spectrum(db_session, owner, make_raw_file(owner))
    second = _spectrum(db_session, owner, make_raw_file(owner, b"100 2\n200 3\n300 4\n400 3\n500 2\n600 3\n"))
    dataset = AnalysisDataset(owner_id=owner.id, modality=Modality.raman, name="Cancel")
    db_session.add(dataset)
    db_session.flush()
    db_session.add_all(
        [
            AnalysisDatasetSpectrum(dataset_id=dataset.id, spectrum_id=first.id, position=0),
            AnalysisDatasetSpectrum(dataset_id=dataset.id, spectrum_id=second.id, position=1),
        ]
    )
    db_session.commit()
    client = _analysis_client(db_session)
    client.set_current_user(owner)
    run = client.post(
        f"/analysis/datasets/{dataset.id}/runs",
        json={"analysis_type": "pca", "components": 2, "grid_points": 16},
    )
    assert run.status_code == 202, run.text

    cancelled = client.post(f"/analysis/runs/{run.json()['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"