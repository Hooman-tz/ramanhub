"""Multiplicative Scatter Correction (MSC).

Fits `spectrum ~= b * reference + a` via a degree-1 least-squares polynomial
fit, then corrects as `(spectrum - a) / b`.

v1 scope: `params["reference_source"]` must be `{"type": "array", "values":
[...]}` — an inline reference spectrum supplied by the caller, the same
length as `spectrum`. A `raw_file_id`-based reference (e.g. "use spectrum
X's processed output as the reference", or a corpus-average reference) is a
natural follow-up but is out of scope for this pass; the `reference_source`
envelope shape (`{"type": ..., ...}`) is deliberately left open so a future
`{"type": "raw_file", "raw_file_id": ..., "ledger_hash": ...}` variant can be
added without breaking existing ledgers (existing ones stay pinned to
`type: "array"` since the ledger is immutable/replayable as-is).
"""
from __future__ import annotations

import numpy as np

STEP_TYPE = "raman.msc"
VERSION = "1.0.0"
LABEL = "MSC (multiplicative scatter correction)"
CATEGORY = "normalization"
DESCRIPTION = (
    "Multiplicative Scatter Correction against a supplied reference spectrum."
)
PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "reference_source": {
            "type": "object",
            "title": "Reference spectrum",
            "description": 'Inline reference: {"type": "array", "values": [...]}, '
            "same length as the spectrum being corrected.",
        }
    },
    "required": ["reference_source"],
}


def apply(spectrum: np.ndarray, **params) -> np.ndarray:
    reference_source = params.get("reference_source")
    if not isinstance(reference_source, dict) or reference_source.get("type") != "array":
        raise ValueError(
            "msc requires params['reference_source'] = "
            "{'type': 'array', 'values': [...]} (inline reference spectrum)."
        )
    values = reference_source.get("values")
    if values is None:
        raise ValueError("msc: reference_source['values'] is required")

    x = np.asarray(spectrum, dtype=float)
    reference = np.asarray(values, dtype=float)
    if reference.shape != x.shape:
        raise ValueError(
            f"msc: reference length ({reference.shape[0]}) must match spectrum length ({x.shape[0]})"
        )

    slope, intercept = np.polyfit(reference, x, 1)
    if slope == 0:
        raise ValueError("msc: fitted slope is zero — reference is degenerate for this spectrum")
    return (x - intercept) / slope
