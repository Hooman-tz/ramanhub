"""Thermo Scientific (OMNIC) JCAMP-DX spectral file parser.

Thermo's OMNIC software (DXR Raman series, Nicolet FTIR) supports exporting
to JCAMP-DX — the IUPAC/ASTM standard plain-text interchange format for
spectroscopic data. JCAMP-DX files are unambiguously identified by a
`##JCAMP-DX=` header line, with the rest of the header as `##KEY=VALUE`
lines, e.g.:

    ##TITLE=sample_001
    ##JCAMP-DX=5.01
    ##DATA TYPE=RAMAN SPECTRUM
    ##ORIGIN=Thermo Fisher Scientific
    ##DATE=2024/01/31
    ##TIME=12:00:00
    ##RESOLUTION=4
    ##LASER WAVELENGTH=785
    ##FIRSTX=100
    ##LASTX=3200
    ##XYDATA=(X++(Y..Y))

This is text-based, so we give it real (if not exhaustive) field extraction.
"""
from __future__ import annotations

from app.schemas.ingestion import ExtractedMetadata

_JCAMP_MARKER = "##JCAMP-DX="


def _parse_header_lines(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("##") or "=" not in stripped:
            continue
        key, _, value = stripped[2:].partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            fields[key] = value
        if key == "xydata":
            break  # header ends where numeric data begins
    return fields


class ThermoParser:
    vendor_format = "thermo_jcamp_dx"
    version = "0.2-partial"

    def can_parse(self, raw_bytes: bytes, filename: str) -> bool:
        try:
            text = raw_bytes[:4096].decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            return False
        return _JCAMP_MARKER in text.upper().replace(" ", "")

    def parse(self, raw_bytes: bytes) -> ExtractedMetadata:
        text = raw_bytes.decode("utf-8", errors="ignore")
        fields = _parse_header_lines(text)

        resolution_cm1: float | None = None
        if "resolution" in fields:
            try:
                resolution_cm1 = float(fields["resolution"])
            except ValueError:
                pass

        laser_wavelength_nm: float | None = None
        for key in ("laser wavelength", "$laser wavelength"):
            if key in fields:
                try:
                    laser_wavelength_nm = float(fields[key])
                except ValueError:
                    pass
                break

        spectral_range_cm1: str | None = None
        if "firstx" in fields and "lastx" in fields:
            spectral_range_cm1 = f"{fields['firstx']}-{fields['lastx']}"

        date = fields.get("date")
        time = fields.get("time")
        acquisition_datetime: str | None = None
        if date and time:
            acquisition_datetime = f"{date} {time}"
        elif date:
            acquisition_datetime = date

        instrument_vendor = fields.get("origin")
        sample_description = fields.get("title")

        return ExtractedMetadata(
            modality="raman",
            instrument_vendor=instrument_vendor or "Thermo Fisher Scientific",
            resolution_cm1=resolution_cm1,
            laser_wavelength_nm=laser_wavelength_nm,
            spectral_range_cm1=spectral_range_cm1,
            acquisition_datetime=acquisition_datetime,
            sample_description=sample_description,
        )
