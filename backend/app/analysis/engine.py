"""Deterministic, versioned PCA and PCA+k-means analysis implementation."""
from __future__ import annotations

import hashlib
import hmac
import json
import platform
import sys
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import numpy as np
from sqlalchemy.orm import Session

from app.config import settings
from app.models.analysis import AnalysisRun
from app.models.processing_ledger import ProcessingLedger
from app.models.raw_file import RawFile
from app.models.spectrum import Spectrum
from app.processing.algorithms.registry import get_spec
from app.processing.cache import get_or_compute
from app.processing.ledger import compute_ledger_hash
from app.raman_contract import RAMAN_CANONICALIZATION_VERSION, canonicalize_raman_arrays
from app.schemas.ledger import Ledger, LedgerStep
from app.spectra_io import load_raw_spectrum, parse_two_column_raman
from app.storage.s3_client import download_bytes

ANALYSIS_CONTRACT_VERSION = "analysis-1"
MAX_ANALYSIS_SPECTRA = 100
MIN_ANALYSIS_POINTS = 16


class AnalysisCancelled(RuntimeError):
    """Raised when a worker observes a cancellation request."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def output_hash(value: dict) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def job_envelope(run: AnalysisRun) -> dict:
    """The complete immutable payload that a local or hosted worker verifies."""
    return {
        "contract_version": ANALYSIS_CONTRACT_VERSION,
        "run_id": str(run.id),
        "owner_id": str(run.owner_id),
        "dataset_id": str(run.dataset_id),
        "analysis_type": run.analysis_type,
        "execution_backend": run.execution_backend,
        "parameters": run.parameters,
        "input_manifest": run.input_manifest,
        "software_versions": run.software_versions,
        "max_attempts": run.max_attempts,
    }


def sign_run(run: AnalysisRun) -> str:
    message = canonical_json(job_envelope(run)).encode()
    return hmac.new(settings.JWT_SECRET.encode(), message, hashlib.sha256).hexdigest()


def valid_signature(run: AnalysisRun) -> bool:
    return hmac.compare_digest(run.job_signature, sign_run(run))


def software_versions() -> dict[str, str]:
    return {
        "analysis_contract": ANALYSIS_CONTRACT_VERSION,
        "numpy": np.__version__,
        "python": platform.python_version(),
        "runtime": sys.implementation.name,
        "raman_canonicalization": RAMAN_CANONICALIZATION_VERSION,
    }


def load_spectrum_arrays(spectrum: Spectrum, db: Session) -> tuple[np.ndarray, np.ndarray]:
    if spectrum.current_ledger_id is not None:
        ledger_row = db.get(ProcessingLedger, spectrum.current_ledger_id)
        if ledger_row is not None:
            ledger = Ledger(
                schema_version=ledger_row.schema_version,
                raw_file_id=ledger_row.raw_file_id,
                steps=[LedgerStep.model_validate(step) for step in ledger_row.steps],
            )
            return get_or_compute(spectrum.raw_file_id, ledger, db)
    raw_file = db.get(RawFile, spectrum.raw_file_id)
    if raw_file is None:
        raise ValueError("Analysis input no longer has a raw file.")
    return load_raw_spectrum(raw_file)


def load_manifest_arrays(entry: dict[str, str | None], db: Session) -> tuple[np.ndarray, np.ndarray]:
    """Resolve only immutable raw/ledger revisions captured by a signed run."""
    if entry["canonicalization_version"] != RAMAN_CANONICALIZATION_VERSION:
        raise ValueError(
            "The exact Raman canonicalization version for this run is unavailable; "
            "create a new analysis run with the current contract."
        )
    raw_file_id = UUID(str(entry["raw_file_id"]))
    raw_file = db.get(RawFile, raw_file_id)
    if raw_file is None:
        raise ValueError("Analysis input raw file no longer exists.")
    if raw_file.content_hash != entry["raw_checksum_sha256"] or raw_file.storage_version != entry["raw_storage_version"]:
        raise ValueError("Analysis input raw file revision changed after this run was queued.")
    raw_bytes = download_bytes(raw_file.storage_bucket, raw_file.storage_key)
    actual_checksum = hashlib.sha256(raw_bytes).hexdigest()
    if actual_checksum != entry["raw_checksum_sha256"]:
        raise ValueError("Analysis input bytes failed their queued checksum verification.")
    wavenumbers, intensities = parse_two_column_raman(raw_bytes)
    canonical_x, canonical_y, _flags = canonicalize_raman_arrays(wavenumbers, intensities)
    ledger_id = entry.get("ledger_id")
    if ledger_id is None:
        return canonical_x, canonical_y
    ledger_row = db.get(ProcessingLedger, UUID(str(ledger_id)))
    if ledger_row is None or ledger_row.raw_file_id != raw_file.id:
        raise ValueError("Analysis input processing revision changed after this run was queued.")
    ledger_steps = [LedgerStep.model_validate(step) for step in ledger_row.steps]
    calculated_ledger_hash = compute_ledger_hash(ledger_row.raw_file_id, ledger_row.schema_version, ledger_steps)
    if calculated_ledger_hash != entry["ledger_hash"] or ledger_row.ledger_hash != calculated_ledger_hash:
        raise ValueError("Analysis input processing ledger failed its queued integrity check.")
    return replay_captured_ledger_steps(ledger_steps, canonical_x, canonical_y)


def replay_captured_ledger_steps(
    ledger_steps: list[LedgerStep], wavenumbers: np.ndarray, intensities: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Replay only implementations whose exact captured versions are shipped."""
    canonical_x, canonical_y = wavenumbers, intensities
    for step in sorted(ledger_steps, key=lambda value: value.order):
        spec = get_spec(step.type)
        if spec.version != step.version:
            raise ValueError(
                f"Processing algorithm {step.type!r} version {step.version!r} is unavailable; "
                "this reproducible run cannot be replayed with a different implementation."
            )
        if spec.kind == "axis_aware":
            canonical_x, canonical_y = spec.apply(canonical_x, canonical_y, **step.params)
        else:
            canonical_y = spec.apply(canonical_y, **step.params)
    return canonical_x, canonical_y


def build_input_manifest(spectra: Iterable[Spectrum], db: Session) -> list[dict[str, str | None]]:
    manifest: list[dict[str, str | None]] = []
    for spectrum in spectra:
        raw_file = db.get(RawFile, spectrum.raw_file_id)
        ledger = db.get(ProcessingLedger, spectrum.current_ledger_id) if spectrum.current_ledger_id else None
        if raw_file is None:
            raise ValueError("Analysis input no longer has a raw file.")
        manifest.append(
            {
                "spectrum_id": str(spectrum.id),
                "raw_file_id": str(raw_file.id),
                "raw_checksum_sha256": raw_file.content_hash,
                "raw_storage_version": raw_file.storage_version,
                "ledger_id": str(ledger.id) if ledger else None,
                "ledger_hash": ledger.ledger_hash if ledger else None,
                "canonicalization_version": spectrum.canonicalization_version,
            }
        )
    return manifest


def _shared_grid(arrays: list[tuple[np.ndarray, np.ndarray]], grid_points: int) -> tuple[np.ndarray, np.ndarray]:
    if len(arrays) < 2:
        raise ValueError("At least two spectra are required for multi-spectrum analysis.")
    left = max(float(x[0]) for x, _y in arrays)
    right = min(float(x[-1]) for x, _y in arrays)
    shortest_span = min(float(x[-1] - x[0]) for x, _y in arrays)
    if right <= left or (right - left) / shortest_span < 0.8:
        raise ValueError("Selected spectra do not share enough wavenumber overlap (minimum 80%).")
    grid = np.linspace(left, right, grid_points)
    matrix = np.vstack([np.interp(grid, x, y) for x, y in arrays])
    return grid, matrix


def _kmeans(scores: np.ndarray, clusters: int, max_iterations: int = 100) -> np.ndarray:
    if not 2 <= clusters <= scores.shape[0]:
        raise ValueError("Cluster count must be between 2 and the number of selected spectra.")
    # Deterministic initialization: the first rows in the immutable dataset order.
    centroids = scores[:clusters].copy()
    labels = np.zeros(scores.shape[0], dtype=int)
    for _ in range(max_iterations):
        new_labels = np.argmin(((scores[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2), axis=1)
        new_centroids = np.vstack(
            [scores[new_labels == label].mean(axis=0) if np.any(new_labels == label) else centroids[label] for label in range(clusters)]
        )
        if np.array_equal(new_labels, labels) and np.allclose(new_centroids, centroids):
            return new_labels
        labels, centroids = new_labels, new_centroids
    return labels


def execute_pca_arrays(
    spectrum_ids: list[str],
    arrays: list[tuple[np.ndarray, np.ndarray]],
    *,
    parameters: dict,
    cancelled: callable,
) -> tuple[dict, dict]:
    if cancelled():
        raise AnalysisCancelled()
    grid_points = int(parameters.get("grid_points", 128))
    requested_components = int(parameters.get("components", 2))
    if not MIN_ANALYSIS_POINTS <= grid_points <= 512:
        raise ValueError(f"grid_points must be between {MIN_ANALYSIS_POINTS} and 512")

    if cancelled():
        raise AnalysisCancelled()
    if any(x.size < MIN_ANALYSIS_POINTS or y.size < MIN_ANALYSIS_POINTS for x, y in arrays):
        raise ValueError(f"Each spectrum needs at least {MIN_ANALYSIS_POINTS} canonical points.")
    grid, matrix = _shared_grid(arrays, grid_points)
    column_mean = matrix.mean(axis=0)
    centered = matrix - column_mean
    scale = centered.std(axis=0)
    scale[scale == 0] = 1.0
    standardized = centered / scale
    _u, singular_values, vt = np.linalg.svd(standardized, full_matrices=False)
    components = min(requested_components, standardized.shape[0], standardized.shape[1])
    if components < 1:
        raise ValueError("The selected spectra cannot produce a PCA component.")
    scores = standardized @ vt[:components].T
    variance = singular_values**2
    ratio = variance[:components] / variance.sum() if variance.sum() else np.zeros(components)
    output = {
        "analysis_type": "pca",
        "spectrum_ids": spectrum_ids,
        "grid_wavenumbers": [float(value) for value in grid],
        "scores": [[float(value) for value in row] for row in scores],
        "components": [[float(value) for value in row] for row in vt[:components]],
        "explained_variance_ratio": [float(value) for value in ratio],
    }
    if parameters.get("clusters") is not None:
        labels = _kmeans(scores, int(parameters["clusters"]))
        output["analysis_type"] = "pca_kmeans"
        output["cluster_labels"] = [int(value) for value in labels]
    checks = {
        "spectrum_count": len(spectrum_ids),
        "grid_points": grid_points,
        "overlap_minimum_fraction": 0.8,
        "all_inputs_canonical": True,
        "status": "passed",
    }
    return output, checks


def execute_pca(
    spectra: list[Spectrum],
    db: Session,
    *,
    parameters: dict,
    cancelled: callable,
) -> tuple[dict, dict]:
    arrays = [load_spectrum_arrays(spectrum, db) for spectrum in spectra]
    return execute_pca_arrays(
        [str(spectrum.id) for spectrum in spectra],
        arrays,
        parameters=parameters,
        cancelled=cancelled,
    )


def execute_run(
    run: AnalysisRun,
    db: Session,
    *,
    cancelled: callable | None = None,
) -> tuple[dict, dict, str]:
    if not valid_signature(run):
        raise ValueError("Analysis job signature is invalid.")
    cancelled = cancelled or (lambda: bool(run.cancel_requested))
    # Copy signed payload before cache writes, which can commit and expire ORM
    # instances. Nothing mutable on Spectrum participates after this point.
    manifest = [dict(entry) for entry in run.input_manifest]
    parameters = dict(run.parameters)
    arrays = [load_manifest_arrays(entry, db) for entry in manifest]
    output, checks = execute_pca_arrays(
        [str(entry["spectrum_id"]) for entry in manifest],
        arrays,
        parameters=parameters,
        cancelled=cancelled,
    )
    return output, checks, output_hash(output)


def build_citation(run: AnalysisRun, digest: str | None = None) -> dict[str, str]:
    return {
        "label": f"Spectra Insight analysis run {run.id}",
        "contract_version": ANALYSIS_CONTRACT_VERSION,
        "output_hash": digest or run.output_hash or "",
        "created_at": (run.created_at or datetime.now(UTC)).isoformat(),
    }