"""JCAMP-DX export (IUPAC's spectroscopic interchange format).

Why this matters more than CSV: JCAMP-DX is what a spectroscopist's existing
software already opens — WiRE, LabSpec, OMNIC, KnowItAll, spectragryph. A CSV
makes them write a parser; a .jdx file just opens. For a repository whose
value proposition is that other people can actually use your data, that
difference is the product.

Scope, stated plainly: this writes JCAMP-DX 4.24 `(XY..XY)` in plain ASCII —
one x,y pair per line, no compression. The format also defines packed forms
(DIF/SQZ/PAC) that are far more compact, but they are also where nearly every
JCAMP interoperability bug in the wild lives. Uncompressed XY is the most
broadly readable form, and at Raman spectrum sizes (a few thousand points)
the file is tens of kilobytes either way. Compression would be optimizing the
axis that doesn't hurt.

Reference: McDonald & Wilks, "JCAMP-DX: A Standard Form for Exchange of
Infrared Spectra in Computer Readable Form", Appl. Spectrosc. 42 (1988) 151.
"""
from __future__ import annotations

from collections.abc import Iterator

import numpy as np

JCAMP_VERSION = "4.24"

# JCAMP labels are terminated by '=', so a '=' inside a free-text value would
# corrupt the record. Same for newlines, which would start a spurious label.
_UNSAFE_IN_VALUE = str.maketrans({"=": "-", "\r": " ", "\n": " ", "$": "-"})


def _clean(value: object) -> str:
    return str(value).translate(_UNSAFE_IN_VALUE).strip()


def to_jcampdx(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    title: str = "Spectrum",
    metadata: dict | None = None,
) -> Iterator[str]:
    """Yield a JCAMP-DX document line by line.

    `metadata` keys that map onto standard JCAMP labels are emitted as those
    labels; everything else becomes a `$`-prefixed user-defined label, which
    is exactly what that prefix is reserved for. That keeps RamanHub-specific
    provenance (accession, ledger hash, license) in the file without
    pretending it is part of the standard.
    """
    metadata = metadata or {}
    x = np.asarray(wavenumbers, dtype=float)
    y = np.asarray(intensities, dtype=float)
    if x.size != y.size:
        raise ValueError("jcampdx: wavenumber and intensity arrays must match in length")

    yield f"##TITLE={_clean(title)}\n"
    yield f"##JCAMP-DX={JCAMP_VERSION}\n"
    yield "##DATA TYPE=RAMAN SPECTRUM\n"
    yield "##ORIGIN=RamanHub\n"
    yield f"##OWNER={_clean(metadata.get('contributor') or 'unknown')}\n"

    if metadata.get("laser_wavelength_nm"):
        # There is no standard JCAMP label for Raman excitation, so it goes
        # in the user-defined namespace rather than being forced into an
        # unrelated standard one.
        yield f"##$LASER_WAVELENGTH_NM={_clean(metadata['laser_wavelength_nm'])}\n"

    yield "##XUNITS=1/CM\n"
    yield "##YUNITS=ARBITRARY UNITS\n"

    if x.size:
        yield f"##FIRSTX={float(x[0])!r}\n"
        yield f"##LASTX={float(x[-1])!r}\n"
        yield f"##MINY={float(np.min(y))!r}\n"
        yield f"##MAXY={float(np.max(y))!r}\n"
    yield "##XFACTOR=1.0\n"
    yield "##YFACTOR=1.0\n"
    yield f"##NPOINTS={x.size}\n"

    # RamanHub provenance, in the user-defined ($) namespace.
    for key in ("accession", "doi", "license", "orcid", "url", "ledger_hash", "processing"):
        value = metadata.get(key)
        if value:
            yield f"##${key.upper()}={_clean(value)}\n"

    yield "##XYDATA=(XY..XY)\n"
    for xi, yi in zip(x, y, strict=True):
        yield f"{float(xi)!r}, {float(yi)!r}\n"
    yield "##END=\n"
