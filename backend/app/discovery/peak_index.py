"""Persist detected peaks per spectrum revision, so matching can prefilter.

A deliberate structural twin of `raman_similarity.py`: same source-hash cache
gate, same version check, same `begin_nested` insert-race handling, same
per-item commit in the warmer. Read either and you know the other.

Peak *detection* is pure DSP and lives in `app.processing.peaks`. This module
is the DB-aware half — it knows about `Session`, `Spectrum` and QC eligibility,
none of which may leak into the processing unit.
"""
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
from app.models.spectrum import Spectrum
from app.models.spectrum_peaks import SpectrumPeaks
from app.processing.peaks import (
    MAX_INDEXED_PEAKS,
    PEAK_INDEX_VERSION,
    bin_peaks,
    detect_peaks,
)
from app.raman_contract import RAMAN_CANONICALIZATION_VERSION

MIN_PEAK_POINTS = 16
#: A spectrum whose strongest band barely clears its own background carries no
#: usable identity. Indexing it would add bins that match everything.
MIN_PEAK_TO_BACKGROUND = 0.05


def _source_hash(spectrum: Spectrum, db: Session) -> str:
    raw_file = db.get(RawFile, spectrum.raw_file_id)
    ledger = (
        db.get(ProcessingLedger, spectrum.current_ledger_id)
        if spectrum.current_ledger_id
        else None
    )
    raw_checksum = raw_file.content_hash if raw_file is not None else ""
    ledger_hash = ledger.ledger_hash if ledger is not None else ""
    return hashlib.sha256(
        f"{raw_checksum}:{ledger_hash}:{PEAK_INDEX_VERSION}".encode()
    ).hexdigest()


def _qc_reasons(spectrum: Spectrum, x: np.ndarray, y: np.ndarray) -> list[str]:
    reasons: list[str] = []
    if spectrum.modality != Modality.raman:
        reasons.append("Only the Raman peak adapter is currently accepted.")
    if spectrum.canonicalization_version != RAMAN_CANONICALIZATION_VERSION:
        reasons.append(
            "Spectrum was not built with the current Raman canonicalization version."
        )
    if x.size < MIN_PEAK_POINTS or y.size < MIN_PEAK_POINTS:
        reasons.append(f"At least {MIN_PEAK_POINTS} canonical points are required.")
    if x.size and (not np.all(np.isfinite(x)) or not np.all(np.isfinite(y))):
        reasons.append("Canonical arrays contain non-finite values.")
    return reasons


def get_or_build_peak_index(spectrum: Spectrum, db: Session) -> SpectrumPeaks:
    """Build once per source+ledger revision and persist the peak list."""
    source_hash = _source_hash(spectrum, db)
    existing = (
        db.query(SpectrumPeaks)
        .filter(SpectrumPeaks.spectrum_id == spectrum.id)
        .one_or_none()
    )
    if (
        existing is not None
        and existing.source_hash == source_hash
        and existing.peak_index_version == PEAK_INDEX_VERSION
        and existing.canonicalization_version == (spectrum.canonicalization_version or "")
    ):
        return existing

    x, y = load_spectrum_arrays(spectrum, db)
    reasons = _qc_reasons(spectrum, x, y)

    peaks: list = []
    binned: list[int] = []
    primary_cm1 = None
    primary_prom = None
    ptb = None
    baseline_level = None
    noise_sigma = None

    if not reasons:
        try:
            profile = detect_peaks(x, y, max_peaks=MAX_INDEXED_PEAKS)
        except ValueError as exc:
            reasons.append(str(exc))
        else:
            baseline_level = profile.baseline_level
            noise_sigma = profile.noise_sigma
            ptb = profile.peak_to_background
            if not profile.peaks:
                reasons.append("No peaks rose above the noise floor.")
            elif profile.peak_to_background < MIN_PEAK_TO_BACKGROUND:
                reasons.append(
                    "Strongest band is not distinguishable from the background."
                )
            else:
                peaks = [p.as_dict() for p in profile.peaks]
                binned = bin_peaks(profile.peaks)
                primary_cm1 = profile.primary_peak_cm1
                primary_prom = profile.primary_peak_prominence

    values = {
        "modality": spectrum.modality,
        "peak_index_version": PEAK_INDEX_VERSION,
        "canonicalization_version": spectrum.canonicalization_version or "",
        "source_hash": source_hash,
        "primary_peak_cm1": primary_cm1,
        "primary_peak_prominence": primary_prom,
        "peak_to_background": ptb,
        "peak_count": len(peaks),
        "wavenumber_min": float(x[0]) if x.size else 0.0,
        "wavenumber_max": float(x[-1]) if x.size else 0.0,
        "baseline_level": baseline_level,
        "noise_sigma": noise_sigma,
        "peaks": peaks,
        "binned_cm1": binned,
        "qc_eligible": not reasons,
        "qc_reasons": reasons,
    }

    if existing is not None:
        for field, value in values.items():
            setattr(existing, field, value)
        db.add(existing)
        db.flush()
        return existing

    # A foreground match and the background warmer may race, exactly as they
    # can for similarity features. The savepoint preserves the winner's row.
    created = SpectrumPeaks(spectrum_id=spectrum.id, **values)
    try:
        with db.begin_nested():
            db.add(created)
            db.flush()
        return created
    except IntegrityError:
        return (
            db.query(SpectrumPeaks)
            .filter(SpectrumPeaks.spectrum_id == spectrum.id)
            .one()
        )


def warm_peak_indexes(spectrum_ids: list[UUID], db: Session) -> list[SpectrumPeaks]:
    spectra = db.query(Spectrum).filter(Spectrum.id.in_(spectrum_ids)).all()
    by_id = {spectrum.id: spectrum for spectrum in spectra}
    rows: list[SpectrumPeaks] = []
    for spectrum_id in spectrum_ids:
        spectrum = by_id.get(spectrum_id)
        if spectrum is None:
            continue
        try:
            rows.append(get_or_build_peak_index(spectrum, db))
            db.commit()
        except Exception:  # noqa: BLE001 - bad source data is an ineligible row, not a crash
            db.rollback()
    return rows
