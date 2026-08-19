"""Horiba LabSpec (LabSpec 5/6) ASCII header parser.

LabSpec's plain-text export convention prefixes header lines with a single
`#` and a `key : value` (or `key : value` without spaces) pair, e.g.:

    #Acq. time (s):	10
    #Accumulations:	4
    #Range (cm-1):	100 - 3200
    #Windows:	1
    #Grating:	1800
    #Objective:	x50
    #Laser:	532nm edge
    #Spectro:	iHR320
    #Acquired:	01/31/2024 12:00:00

This is text-based, so — unlike the purely binary vendor formats — we give
it real (if not exhaustive) field extraction, not just detection.
"""
from __future__ import annotations

import re

from app.schemas.ingestion import ExtractedMetadata

# Header keys that, when found (as single-# comment lines), are strong
# evidence of a Horiba LabSpec export.
_SIGNATURE_KEYS = {"laser", "objective", "grating", "spectro", "acquired", "accumulations"}

_HEADER_LINE_RE = re.compile(r"^#(?!#)\s*([^:]+?)\s*:\s*(.*)$")
_LEADING_NUMBER_RE = re.compile(r"[-+]?\d*\.?\d+")


def _parse_header_lines(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        match = _HEADER_LINE_RE.match(line.strip())
        if match:
            key = match.group(1).strip().lower()
            value = match.group(2).strip()
            if key and value:
                fields[key] = value
    return fields


def _leading_number(value: str) -> float | None:
    match = _LEADING_NUMBER_RE.search(value)
    if match:
        try:
            return float(match.group(0))
        except ValueError:
            return None
    return None


class HoribaParser:
    vendor_format = "horiba_labspec"
    version = "0.2-partial"

    def can_parse(self, raw_bytes: bytes, filename: str) -> bool:
        try:
            text = raw_bytes[:8192].decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            return False
        if "jcamp" in text.lower():
            # Avoid colliding with JCAMP-DX (##-prefixed) headers.
            return False
        hits = 0
        for line in text.splitlines():
            stripped = line.strip()
            match = _HEADER_LINE_RE.match(stripped)
            if match and match.group(1).strip().lower() in _SIGNATURE_KEYS:
                hits += 1
        return hits >= 2

    def parse(self, raw_bytes: bytes) -> ExtractedMetadata:
        text = raw_bytes.decode("utf-8", errors="ignore")
        fields = _parse_header_lines(text)

        integration_time_ms: float | None = None
        for key in ("acq. time (s)", "acquisition time (s)", "exposure time (s)"):
            if key in fields:
                seconds = _leading_number(fields[key])
                if seconds is not None:
                    integration_time_ms = seconds * 1000.0
                break

        accumulations: int | None = None
        if "accumulations" in fields:
            number = _leading_number(fields["accumulations"])
            if number is not None:
                accumulations = int(number)

        laser_wavelength_nm: float | None = None
        if "laser" in fields:
            laser_wavelength_nm = _leading_number(fields["laser"])

        grating_lines_mm: float | None = None
        if "grating" in fields:
            grating_lines_mm = _leading_number(fields["grating"])

        objective_magnification: float | None = None
        if "objective" in fields:
            objective_magnification = _leading_number(fields["objective"])

        instrument_model = fields.get("spectro")
        acquisition_datetime = fields.get("acquired")

        spectral_range_cm1: str | None = None
        for key in ("range (cm-1)", "range"):
            if key in fields:
                range_value = fields[key]
                # Normalize "100 - 3200" -> "100-3200"
                parts = re.split(r"\s*-\s*", range_value)
                if len(parts) == 2:
                    spectral_range_cm1 = f"{parts[0]}-{parts[1]}"
                else:
                    spectral_range_cm1 = range_value
                break

        return ExtractedMetadata(
            modality="raman",
            instrument_vendor="Horiba",
            instrument_model=instrument_model,
            laser_wavelength_nm=laser_wavelength_nm,
            integration_time_ms=integration_time_ms,
            accumulations=accumulations,
            spectral_range_cm1=spectral_range_cm1,
            acquisition_datetime=acquisition_datetime,
            grating_lines_mm=grating_lines_mm,
            objective_magnification=objective_magnification,
        )
