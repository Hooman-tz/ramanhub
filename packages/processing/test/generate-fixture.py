"""Generate the parity fixture: run every step through the real server-side
registry and record the exact arrays it produced.

The TypeScript ports in `src/algorithms.ts` are only useful if they agree with
`backend/app/processing/algorithms/`. This script is the source of that
agreement — it imports the actual registry the API uses, so the fixture cannot
drift from the server by being hand-written.

Run from the repo root, with the backend's environment:

    cd backend && uv run python ../packages/processing/test/generate-fixture.py

Regenerate whenever a Python algorithm changes; `parity.test.ts` then either
confirms the port still matches or fails loudly.
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

from app.processing.algorithms.registry import apply_step  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent / "parity-fixture.json"


def synthetic_spectrum() -> tuple[np.ndarray, np.ndarray]:
    """A deterministic spectrum with everything the toolbox reacts to: sharp
    bands, a broad fluorescence background, noise, and two cosmic-ray spikes."""
    rng = np.random.default_rng(20260903)
    x = np.linspace(200.0, 3200.0, 500)

    y = np.zeros_like(x)
    for center, height, width in [
        (520.0, 900.0, 8.0),
        (1001.0, 1400.0, 6.0),
        (1350.0, 600.0, 25.0),
        (1580.0, 1100.0, 12.0),
        (2900.0, 800.0, 40.0),
    ]:
        y += height * np.exp(-0.5 * ((x - center) / width) ** 2)

    # Broad fluorescence background plus a slope, then noise.
    y += 2500.0 * np.exp(-0.5 * ((x - 1900.0) / 1100.0) ** 2) + 0.12 * x + 150.0
    y += rng.normal(0.0, 6.0, x.size)

    # Two narrow cosmic rays.
    y[125] += 5000.0
    y[350] += 4200.0
    return x, y


X, Y = synthetic_spectrum()
REFERENCE = list(np.asarray(Y * 0.85 + 40.0, dtype=float))

# (case name, [(step_type, params), ...]) — single steps plus one real pipeline.
CASES: list[tuple[str, list[tuple[str, dict]]]] = [
    ("despike-default", [("raman.despike", {})]),
    ("despike-tight", [("raman.despike", {"threshold": 4.0, "max_width": 2})]),
    ("savgol-smooth", [("raman.smooth.savitzky_golay", {"window_length": 9, "polyorder": 3})]),
    (
        "savgol-derivative",
        [("raman.smooth.savitzky_golay", {"window_length": 11, "polyorder": 2, "deriv": 1})],
    ),
    ("airpls", [("raman.fluorescence_suppression.airpls", {"lambda_": 100, "max_iter": 15})]),
    ("airpls-stiff", [("raman.fluorescence_suppression.airpls", {"lambda_": 10000, "max_iter": 8})]),
    ("baseline-als", [("raman.baseline.als", {"lam": 1e5, "p": 0.01, "max_iter": 10})]),
    ("baseline-polynomial", [("raman.baseline.polynomial", {"degree": 5})]),
    ("snv", [("raman.snv", {})]),
    ("msc", [("raman.msc", {"reference_source": {"type": "array", "values": REFERENCE}})]),
    ("normalize-minmax", [("raman.normalize.minmax", {})]),
    ("normalize-vector", [("raman.normalize.vector", {})]),
    ("normalize-area", [("raman.normalize.area", {})]),
    ("normalize-peak", [("raman.normalize.peak", {"wavenumber": 1001.0, "tolerance": 15.0})]),
    ("normalize-peak-global", [("raman.normalize.peak", {})]),
    ("crop", [("raman.crop", {"min_cm1": 400.0, "max_cm1": 1800.0})]),
    ("resample-count", [("raman.resample", {"num_points": 512})]),
    ("resample-step", [("raman.resample", {"step_cm1": 2.0})]),
    (
        "full-pipeline",
        [
            ("raman.despike", {}),
            ("raman.fluorescence_suppression.airpls", {"lambda_": 100, "max_iter": 15}),
            ("raman.smooth.savitzky_golay", {"window_length": 9, "polyorder": 3}),
            ("raman.crop", {"min_cm1": 300.0, "max_cm1": 1900.0}),
            ("raman.snv", {}),
        ],
    ),
]


def main() -> None:
    cases = []
    for name, steps in CASES:
        w, y = X.copy(), Y.copy()
        for step_type, params in steps:
            w, y = apply_step(step_type, w, y, params)
        cases.append(
            {
                "name": name,
                "steps": [{"type": t, "params": p} for t, p in steps],
                "wavenumbers": [float(v) for v in w],
                "intensities": [float(v) for v in y],
            }
        )

    OUT.write_text(
        json.dumps(
            {
                "input": {
                    "wavenumbers": [float(v) for v in X],
                    "intensities": [float(v) for v in Y],
                },
                "cases": cases,
            }
        )
    )
    print(f"wrote {OUT} — {len(cases)} cases")


if __name__ == "__main__":
    main()
