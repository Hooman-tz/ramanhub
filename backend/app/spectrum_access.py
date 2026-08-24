"""Resolve a `Spectrum` row to the numeric arrays callers actually work on.

Separate from `app.spectra_io` on purpose. `spectra_io` is the low-level
"RawFile bytes -> numpy" layer, and `app.processing.cache` imports it; a
ledger-aware resolver has to import `processing.cache` in turn, so putting
it back in `spectra_io` would close an import cycle. This module sits one
level up from both.

Everything that needs "the spectrum as the user currently sees it" — search
similarity, peak detection, PCA, export — goes through
`load_spectrum_arrays` here, so the processed-if-ledgered-else-raw rule is
stated once rather than re-derived per caller.
"""
from __future__ import annotations

import numpy as np
from sqlalchemy.orm import Session

from app.models.processing_ledger import ProcessingLedger
from app.models.raw_file import RawFile
from app.models.spectrum import Spectrum
from app.processing.cache import get_or_compute
from app.schemas.ledger import Ledger, LedgerStep
from app.spectra_io import load_raw_spectrum


def load_spectrum_arrays(spectrum: Spectrum, db: Session) -> tuple[np.ndarray, np.ndarray]:
    """Resolve `(wavenumbers, intensities)` for a spectrum using the
    "processed-if-ledgered, else raw" rule shared by
    `app.routers.spectra._recompute_derived_fields` and Module 3's
    visualization endpoints.

    Returns two empty arrays (never raises) when the raw file row is
    missing, so a single broken row can't fail a bulk caller iterating the
    whole corpus.
    """
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
        return np.array([]), np.array([])
    return load_raw_spectrum(raw_file)


def load_raw_arrays(spectrum: Spectrum, db: Session) -> tuple[np.ndarray, np.ndarray]:
    """The raw, never-processed arrays for a spectrum — the immutable
    original. Used by export (`stage=raw`) and by the raw-overlay toggle."""
    raw_file = db.get(RawFile, spectrum.raw_file_id)
    if raw_file is None:
        return np.array([]), np.array([])
    return load_raw_spectrum(raw_file)
