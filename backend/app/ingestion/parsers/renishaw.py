"""Renishaw WiRE (.wdf) binary spectral file parser.

WDF files are a block-structured binary container whose very first block
carries the 4-byte ASCII magic `WDF1` (little-endian block-type tag),
followed by a block-size/version header before the block directory table.
That magic is a reliable, well-documented sniff signature.

Full binary block parsing (walking the block directory table to pull
instrument/laser parameters out of the `WDF_BLOCKID_*` blocks) is a
significant undertaking and out of scope for this pass — `can_parse` is
solid, `parse()` is best-effort: it only attempts a loose textual scan for a
laser-wavelength-like substring and otherwise returns null fields.
"""
from __future__ import annotations

import re

from app.schemas.ingestion import ExtractedMetadata

WDF_MAGIC = b"WDF1"

_WAVELENGTH_RE = re.compile(rb"(\d{3,4})\s*nm")


class RenishawParser:
    vendor_format = "renishaw_wdf"
    version = "0.1-partial"

    def can_parse(self, raw_bytes: bytes, filename: str) -> bool:
        return raw_bytes[:4] == WDF_MAGIC

    def parse(self, raw_bytes: bytes) -> ExtractedMetadata:
        laser_wavelength_nm: float | None = None
        match = _WAVELENGTH_RE.search(raw_bytes[:4096])
        if match:
            try:
                laser_wavelength_nm = float(match.group(1))
            except ValueError:
                pass

        return ExtractedMetadata(
            modality="raman",
            instrument_vendor="Renishaw",
            laser_wavelength_nm=laser_wavelength_nm,
        )
