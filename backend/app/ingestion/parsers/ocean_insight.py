"""Ocean Insight / Ocean Optics (SpectraSuite, OceanView) plain-text spectral
file parser.

These files are ASCII, with a `key: value` header block followed by a
`>>>>>Begin Spectral Data<<<<<` marker and whitespace/tab-delimited
(wavenumber, intensity) pairs, terminated by `>>>>>End Spectral Data<<<<<`.
This is the one vendor parser in this pass with full, tested `parse()`
coverage — the others are format-detection plus best-effort extraction.

Real-world header conventions this handles:
    Spectrometers: USB2000+H15466
    Integration Time (usec): 100000
    Scans to average: 3
    Electric dark correction enabled: true
    Nonlinearity correction enabled: true
    Boxcar width: 2
    XAxis mode: Raman Shift
    Date: Thu Jan 01 00:00:00 GMT 2026
    Excitation Wavelength (nm): 785.0
"""
from __future__ import annotations

from app.schemas.ingestion import ExtractedMetadata

BEGIN_MARKER = ">>>>>Begin Spectral Data<<<<<"
END_MARKER = ">>>>>End Spectral Data<<<<<"

# Recognized header keys are matched case-insensitively, with optional units
# in parentheses stripped before lookup.
_INTEGRATION_TIME_KEYS = {
    "integration time (usec)": 1 / 1000,
    "integration time (us)": 1 / 1000,
    "integration time (msec)": 1.0,
    "integration time (ms)": 1.0,
    "integration time (sec)": 1000.0,
    "integration time (s)": 1000.0,
}


def _header_block(raw_text: str) -> str:
    """Return only the header portion, before the spectral data marker."""
    idx = raw_text.find(BEGIN_MARKER)
    return raw_text if idx == -1 else raw_text[:idx]


def _parse_header_lines(header_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in header_text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key and value:
            fields[key] = value
    return fields


class OceanInsightParser:
    vendor_format = "ocean_insight"
    version = "1.0"

    def can_parse(self, raw_bytes: bytes, filename: str) -> bool:
        try:
            text = raw_bytes[:8192].decode("utf-8", errors="ignore")
        except Exception:  # noqa: BLE001 - can_parse must never raise
            return False
        if BEGIN_MARKER in text:
            return True
        lowered = text.lower()
        # Fallback signature: plain-text header mentioning Ocean-style keys
        # without the exact marker (some export variants trim it).
        return "spectrasuite" in lowered or "oceanview" in lowered

    def parse(self, raw_bytes: bytes) -> ExtractedMetadata:
        text = raw_bytes.decode("utf-8", errors="ignore")
        header_text = _header_block(text)
        fields = _parse_header_lines(header_text)

        instrument_model: str | None = None
        instrument_vendor: str | None = None
        for key in ("spectrometers", "spectrometer"):
            if key in fields:
                instrument_model = fields[key]
                instrument_vendor = "Ocean Insight"
                break

        integration_time_ms: float | None = None
        for key, to_ms in _INTEGRATION_TIME_KEYS.items():
            if key in fields:
                try:
                    integration_time_ms = float(fields[key]) * to_ms
                except ValueError:
                    pass
                break

        accumulations: int | None = None
        if "scans to average" in fields:
            try:
                accumulations = int(float(fields["scans to average"]))
            except ValueError:
                pass

        acquisition_datetime = fields.get("date")

        laser_wavelength_nm: float | None = None
        for key in ("excitation wavelength (nm)", "laser wavelength (nm)"):
            if key in fields:
                try:
                    laser_wavelength_nm = float(fields[key])
                except ValueError:
                    pass
                break

        sample_description = fields.get("data from") or fields.get("comment")

        # Anything else recognized-but-unmapped goes into raw_extra_fields as
        # flat scalars, bounded by ExtractedMetadata's own validator.
        mapped_keys = {
            "spectrometers",
            "spectrometer",
            "date",
            "scans to average",
            "excitation wavelength (nm)",
            "laser wavelength (nm)",
            "data from",
            "comment",
        } | set(_INTEGRATION_TIME_KEYS.keys())
        raw_extra: dict[str, str | float | int] = {}
        for key, value in fields.items():
            if key in mapped_keys:
                continue
            if len(raw_extra) >= 15:
                break
            raw_extra[key[:100]] = value[:500]

        return ExtractedMetadata(
            modality="raman",
            instrument_vendor=instrument_vendor,
            instrument_model=instrument_model,
            laser_wavelength_nm=laser_wavelength_nm,
            integration_time_ms=integration_time_ms,
            accumulations=accumulations,
            acquisition_datetime=acquisition_datetime,
            sample_description=sample_description,
            raw_extra_fields=raw_extra,
        )
