"""Generate the peak-detection parity fixture from the real Python detector.

`src/peaks.ts` is a second implementation of
`backend/app/processing/peaks.py`. Two independent implementations of the same
maths drift; this fixture is how that drift becomes visible instead of silent.

Agreement is asserted to within one 4 cm-1 bin, not bit-exactly — the ports use
different peak-picking primitives (scipy's `find_peaks` vs a hand-rolled scan)
and only need to agree about *which bands exist*.

Run from the backend environment:

    cd backend && uv run python ../packages/processing/test/generate-peaks-fixture.py
"""
from __future__ import annotations

import json
import pathlib
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "backend"))

from app.processing.peaks import PEAK_INDEX_VERSION, detect_peaks  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent / "peaks-fixture.json"


def gaussian(x, centre, amplitude, width):
    return amplitude * np.exp(-0.5 * ((x - centre) / width) ** 2)


def cases():
    x = np.linspace(100.0, 2000.0, 1900)
    rng = np.random.default_rng(11)
    three = gaussian(x, 512, 50, 8) + gaussian(x, 1085, 100, 6) + gaussian(x, 1600, 70, 10)

    return [
        ("clean_three_band", x, three + rng.normal(0, 0.3, x.size)),
        ("fluorescence_ramp", x, three + 800 * np.exp(-(x - 100) / 900) + 500),
        ("dc_pedestal", x, three + 4000.0),
        ("crowded", x, three + gaussian(x, 900, 25, 7) + gaussian(x, 1250, 18, 9)),
        ("flat", x, np.zeros(x.size)),
    ]


def main() -> None:
    out = []
    for name, x, y in cases():
        profile = detect_peaks(x, y)
        out.append(
            {
                "name": name,
                "wavenumbers": [float(v) for v in x],
                "intensities": [float(v) for v in y],
                "expected": {
                    "peaks": [
                        {"cm1": p.cm1, "relHeight": p.rel_height} for p in profile.peaks
                    ],
                    "primaryPeakCm1": profile.primary_peak_cm1,
                },
            }
        )
    OUT.write_text(
        json.dumps({"version": PEAK_INDEX_VERSION, "cases": out}, indent=None)
    )
    print(f"wrote {OUT} — {len(out)} cases")


if __name__ == "__main__":
    main()
