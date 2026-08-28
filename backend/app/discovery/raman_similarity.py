"""Versioned Raman feature extraction and scientifically conservative matching."""
from __future__ import annotations

import hashlib
from uuid import UUID

import numpy as np
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analysis.engine import load_spectrum_arrays
from app.models.enums import Modality
from app.models.processing_ledger import ProcessingLedger
from app.models.raw_file import RawFile
from app.models.similarity import SimilarityFeature
from app.models.spectrum import Spectrum
from app.raman_contract import RAMAN_CANONICALIZATION_VERSION

FEATURE_VERSION = "raman-cosine-2"
FEATURE_POINTS = 512
FEATURE_GRID_MIN = 100.0
FEATURE_GRID_MAX = 4000.0
MIN_SIMILARITY_POINTS = 6
MIN_OVERLAP_FRACTION = 0.8


def _source_hash(spectrum: Spectrum, db: Session) -> str:
    raw_file = db.get(RawFile, spectrum.raw_file_id)
    ledger = db.get(ProcessingLedger, spectrum.current_ledger_id) if spectrum.current_ledger_id else None
    raw_checksum = raw_file.content_hash if raw_file is not None else ""
    ledger_hash = ledger.ledger_hash if ledger is not None else ""
    return hashlib.sha256(f"{raw_checksum}:{ledger_hash}:{FEATURE_VERSION}".encode()).hexdigest()


def _feature_vector(x: np.ndarray, y: np.ndarray) -> list[float]:
    """Represent physical peak positions without stretching each input range."""
    grid = np.linspace(FEATURE_GRID_MIN, FEATURE_GRID_MAX, FEATURE_POINTS)
    usable = (grid >= x[0]) & (grid <= x[-1])
    if usable.sum() < 2:
        raise ValueError("Spectrum does not cover enough of the Raman feature grid.")
    values = np.zeros(FEATURE_POINTS)
    interpolated = np.interp(grid[usable], x, y)
    values[usable] = interpolated - interpolated.mean()
    norm = float(np.linalg.norm(values))
    if norm == 0.0:
        raise ValueError("Spectrum has no variable intensity for similarity.")
    return [float(value) for value in values / norm]


def _qc_reasons(spectrum: Spectrum, x: np.ndarray, y: np.ndarray) -> list[str]:
    reasons: list[str] = []
    if spectrum.modality != Modality.raman:
        reasons.append("Only the Raman similarity adapter is currently accepted.")
    if spectrum.canonicalization_version != RAMAN_CANONICALIZATION_VERSION:
        reasons.append("Spectrum was not built with the current Raman canonicalization version.")
    if x.size < MIN_SIMILARITY_POINTS or y.size < MIN_SIMILARITY_POINTS:
        reasons.append(f"At least {MIN_SIMILARITY_POINTS} canonical points are required.")
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        reasons.append("Canonical arrays contain non-finite values.")
    if x.size > 1 and float(x[-1] - x[0]) <= 0:
        reasons.append("Wavenumber range is not positive.")
    if (spectrum.quality_flags or {}).get("array", "").startswith("canonical Raman array unavailable"):
        reasons.append("Canonical Raman array is unavailable.")
    return reasons


def get_or_build_feature(spectrum: Spectrum, db: Session) -> SimilarityFeature:
    """Build once per source+ledger revision and persist the compact vector."""
    source_hash = _source_hash(spectrum, db)
    existing = db.query(SimilarityFeature).filter(SimilarityFeature.spectrum_id == spectrum.id).one_or_none()
    if (
        existing is not None
        and existing.source_hash == source_hash
        and existing.feature_version == FEATURE_VERSION
        and existing.canonicalization_version == (spectrum.canonicalization_version or "")
    ):
        return existing

    x, y = load_spectrum_arrays(spectrum, db)
    reasons = _qc_reasons(spectrum, x, y)
    vector: list[float] = []
    if not reasons:
        try:
            vector = _feature_vector(x, y)
        except ValueError as exc:
            reasons.append(str(exc))
    values = {
        "modality": spectrum.modality,
        "feature_version": FEATURE_VERSION,
        "canonicalization_version": spectrum.canonicalization_version or "",
        "source_hash": source_hash,
        "wavenumber_min": float(x[0]) if x.size else 0.0,
        "wavenumber_max": float(x[-1]) if x.size else 0.0,
        "point_count": int(x.size),
        "qc_eligible": not reasons,
        "qc_reasons": reasons,
        "vector": vector,
    }
    if existing is not None:
        for field, value in values.items():
            setattr(existing, field, value)
        db.add(existing)
        db.flush()
        return existing

    # A foreground cold search and the background warmer may race. The
    # savepoint preserves previously warmed rows if this insert loses.
    created = SimilarityFeature(spectrum_id=spectrum.id, **values)
    try:
        with db.begin_nested():
            db.add(created)
            db.flush()
        return created
    except IntegrityError:
        return db.query(SimilarityFeature).filter(SimilarityFeature.spectrum_id == spectrum.id).one()


def overlap_fraction(left: SimilarityFeature, right: SimilarityFeature) -> float:
    overlap = max(0.0, min(left.wavenumber_max, right.wavenumber_max) - max(left.wavenumber_min, right.wavenumber_min))
    shortest_span = min(left.wavenumber_max - left.wavenumber_min, right.wavenumber_max - right.wavenumber_min)
    return overlap / shortest_span if shortest_span > 0 else 0.0


def compatible(left: SimilarityFeature, right: SimilarityFeature) -> tuple[bool, float]:
    if not left.qc_eligible or not right.qc_eligible:
        return False, 0.0
    if left.modality != right.modality or left.modality != Modality.raman:
        return False, 0.0
    if left.feature_version != right.feature_version:
        return False, 0.0
    if left.canonicalization_version != right.canonicalization_version:
        return False, 0.0
    overlap = overlap_fraction(left, right)
    return overlap >= MIN_OVERLAP_FRACTION, overlap


def cosine_feature_similarity(left: SimilarityFeature, right: SimilarityFeature) -> float:
    return float(np.dot(np.asarray(left.vector), np.asarray(right.vector)))


def warm_features(spectrum_ids: list[UUID], db: Session) -> list[SimilarityFeature]:
    spectra = db.query(Spectrum).filter(Spectrum.id.in_(spectrum_ids)).all()
    by_id = {spectrum.id: spectrum for spectrum in spectra}
    features: list[SimilarityFeature] = []
    for spectrum_id in spectrum_ids:
        spectrum = by_id.get(spectrum_id)
        if spectrum is None:
            continue
        try:
            features.append(get_or_build_feature(spectrum, db))
            # Commit each independent index update, so one unreadable raw file
            # cannot discard prior warming work or terminate the worker loop.
            db.commit()
        except Exception:  # noqa: BLE001 - invalid source data is an ineligible feature, not a worker crash
            db.rollback()
    return features