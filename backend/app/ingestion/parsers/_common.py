"""Small shared helpers for the deterministic vendor parsers."""
from __future__ import annotations

# Physical bounds for an excitation-laser wavelength, in nm. A header value
# outside this window is almost certainly a wavenumber, a grating value, or a
# pixel count mislabelled "wavelength" — never write it to
# `laser_wavelength_nm`. Kept in sync with
# `app.ingestion.filename_overlay.LASER_NM_MIN/MAX` and
# `app.ingestion.llm_fallback._LASER_NM_MIN/_MAX`.
LASER_NM_MIN = 200.0
LASER_NM_MAX = 1100.0


def plausible_laser_nm(value: float | None) -> float | None:
    """Return `value` only if it is a physically plausible laser wavelength
    in nm, else None. Guards the classic wavelength / wavenumber confusion.
    """
    if value is None:
        return None
    if LASER_NM_MIN <= value <= LASER_NM_MAX:
        return value
    return None
