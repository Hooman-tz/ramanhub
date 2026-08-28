"""Pure deterministic checks for analysis and discovery contracts."""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest

from app.analysis import engine
from app.discovery.raman_similarity import MIN_OVERLAP_FRACTION, compatible, overlap_fraction
from app.models.enums import Modality
from app.schemas.ledger import LedgerStep


def test_pca_output_is_deterministic_for_the_same_input(monkeypatch):
    first, second = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
    axis = np.linspace(100, 600, 16)
    arrays = {
        first.id: (axis, np.sin(axis / 80) + np.linspace(0, 1, 16)),
        second.id: (axis, np.cos(axis / 70) + np.linspace(0, 1, 16)),
    }
    monkeypatch.setattr(engine, "load_spectrum_arrays", lambda spectrum, _db: arrays[spectrum.id])

    output_one, checks_one = engine.execute_pca(
        [first, second], None, parameters={"components": 2, "grid_points": 16}, cancelled=lambda: False
    )
    output_two, checks_two = engine.execute_pca(
        [first, second], None, parameters={"components": 2, "grid_points": 16}, cancelled=lambda: False
    )

    assert checks_one == checks_two
    assert output_one == output_two
    assert len(output_one["scores"]) == 2


def test_analysis_rejects_insufficient_overlap(monkeypatch):
    first, second = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
    first_axis = np.linspace(100, 600, 16)
    second_axis = np.linspace(1000, 1500, 16)
    arrays = {
        first.id: (first_axis, np.arange(16, dtype=float)),
        second.id: (second_axis, np.arange(16, dtype=float)),
    }
    monkeypatch.setattr(engine, "load_spectrum_arrays", lambda spectrum, _db: arrays[spectrum.id])

    with pytest.raises(ValueError, match="overlap"):
        engine.execute_pca(
            [first, second], None, parameters={"components": 2, "grid_points": 16}, cancelled=lambda: False
        )


def test_similarity_compatibility_requires_overlap_and_matching_contracts():
    base = SimpleNamespace(
        qc_eligible=True,
        modality=Modality.raman,
        feature_version="raman-cosine-2",
        canonicalization_version="raman-1",
        wavenumber_min=100.0,
        wavenumber_max=600.0,
    )
    compatible_feature = SimpleNamespace(**(base.__dict__ | {"wavenumber_min": 150.0, "wavenumber_max": 550.0}))
    far_feature = SimpleNamespace(**(base.__dict__ | {"wavenumber_min": 1000.0, "wavenumber_max": 1500.0}))

    allowed, overlap = compatible(base, compatible_feature)
    denied, far_overlap = compatible(base, far_feature)

    assert allowed
    assert overlap >= MIN_OVERLAP_FRACTION
    assert not denied
    assert overlap_fraction(base, far_feature) == far_overlap == 0.0


def test_job_signature_covers_the_complete_execution_envelope():
    run = SimpleNamespace(
        id=uuid4(),
        owner_id=uuid4(),
        dataset_id=uuid4(),
        analysis_type="pca",
        execution_backend="local",
        parameters={"components": 2, "grid_points": 128},
        input_manifest=[{"spectrum_id": str(uuid4()), "ledger_hash": "immutable"}],
        software_versions={"analysis_contract": "analysis-1"},
        max_attempts=3,
        job_signature="",
    )
    run.job_signature = engine.sign_run(run)
    assert engine.valid_signature(run)

    run.parameters = {"components": 3, "grid_points": 128}
    assert not engine.valid_signature(run)


def test_analysis_observes_cancellation_before_work(monkeypatch):
    first, second = SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())
    axis = np.linspace(100, 600, 16)
    monkeypatch.setattr(
        engine,
        "load_spectrum_arrays",
        lambda spectrum, _db: (axis, np.arange(16, dtype=float) + (1 if spectrum.id == second.id else 0)),
    )

    with pytest.raises(engine.AnalysisCancelled):
        engine.execute_pca(
            [first, second],
            None,
            parameters={"components": 2, "grid_points": 16},
            cancelled=lambda: True,
        )


def test_analysis_refuses_to_replay_an_unavailable_algorithm_version(monkeypatch):
    captured_step = LedgerStep(
        step_id=uuid4(),
        type="raman.snv",
        version="retired-version",
        params={},
        order=0,
        applied_at="2026-01-01T00:00:00Z",
    )
    monkeypatch.setattr(engine, "get_spec", lambda _type: SimpleNamespace(version="current-version"))

    with pytest.raises(ValueError, match="unavailable"):
        engine.replay_captured_ledger_steps(
            [captured_step],
            np.linspace(100, 600, 16),
            np.arange(16, dtype=float),
        )