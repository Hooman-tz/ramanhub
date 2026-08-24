"""CSV / TSV / JSON export of a spectrum's arrays.

Numbers are formatted with `repr`-grade precision (`float` -> shortest string
that round-trips) rather than a fixed number of decimals. A fixed `%.6f`
would silently quantize the intensity axis, and on a normalized spectrum
(SNV output sits in roughly [-3, 3]) that is a real loss of information.

The comment header is opt-in because it is a compatibility trade: it makes a
CSV self-describing (which instrument, which processing, which accession —
the difference between an archivable file and an anonymous pile of numbers),
but some older analysis tools choke on leading `#` lines.
"""
from __future__ import annotations

import json
from collections.abc import Iterator

import numpy as np

DELIMITERS = {"csv": ",", "tsv": "\t"}


def _num(value: float) -> str:
    """Shortest string that round-trips back to the same float."""
    return repr(float(value))


def build_header_comment(metadata: dict, comment_prefix: str = "# ") -> list[str]:
    """Provenance lines for the top of a text export.

    Deliberately flat `key: value` pairs — parseable by eye and by a two-line
    script, without inventing a format anyone has to learn.
    """
    lines = [f"{comment_prefix}{key}: {value}" for key, value in metadata.items() if value not in (None, "")]
    return lines


def to_delimited(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    fmt: str = "csv",
    metadata: dict | None = None,
    include_header_comment: bool = True,
) -> Iterator[str]:
    """Yield the export line by line, so a large spectrum streams instead of
    being materialized whole in memory."""
    try:
        delimiter = DELIMITERS[fmt]
    except KeyError as exc:
        raise ValueError(f"Unsupported tabular format: {fmt!r}") from exc

    if include_header_comment and metadata:
        for line in build_header_comment(metadata):
            yield f"{line}\n"

    yield f"wavenumber_cm-1{delimiter}intensity\n"
    for x, y in zip(wavenumbers, intensities, strict=True):
        yield f"{_num(x)}{delimiter}{_num(y)}\n"


def to_json(
    wavenumbers: np.ndarray,
    intensities: np.ndarray,
    metadata: dict | None = None,
) -> str:
    """Single JSON document with the arrays alongside their metadata.

    Arrays rather than an array-of-objects: a spectrum is two parallel
    columns, and `[{"wavenumber": ..., "intensity": ...}, ...]` would roughly
    triple the payload to express the same thing.
    """
    return json.dumps(
        {
            "metadata": metadata or {},
            "wavenumbers": [float(v) for v in wavenumbers],
            "intensities": [float(v) for v in intensities],
            "n_points": len(wavenumbers),
        },
        indent=2,
    )
