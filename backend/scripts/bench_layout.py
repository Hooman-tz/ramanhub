"""Which rung resolves each file, and does it store the right number of points?

Run from `backend/`:   uv run python scripts/bench_layout.py ../sample-data

Reports the two numbers that matter: how often a model is needed, and how
often a layout verifies while being wrong (silent wrongness).
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from app.ingestion.structure import (
    LayoutError,
    build_preview,
    detect_layout_by_ranking,
    detect_layout_heuristic,
    extract_trace,
    verify_layout,
)
from app.raman_contract import RamanDataError, canonicalize_raman_arrays


def corpus():
    """`(name, bytes, expected_points_per_spectrum, expected_spectra)`."""

    def block(start, n=60):
        return "\n".join(f"{start + i}.0\t{100 + (i * 7) % 50}.5" for i in range(n))

    two_col = "\n".join(f"{200 + i}.0\t{(i * 37) % 900}.5" for i in range(300))
    axis_col2 = "\n".join(
        f"{i % 7}\t{(i * 3) % 11}\t{200 + i}.0\t{(i * 37) % 900}.5" for i in range(300)
    )
    wide = "\t".join(["wavenumber"] + [f"s{i}" for i in range(39)]) + "\n" + "\n".join(
        "\t".join([f"{200 + r}.0"] + [f"{(r * 7 + c) % 900}.0" for c in range(39)])
        for r in range(300)
    )
    labelled = "Wavenumber\tSampleID\tA\tB\n" + "\n".join(
        f"{200 + i}.0\tS1\t{(i * 37) % 900}.5\t{(i * 11) % 700}.5" for i in range(300)
    )
    row_major = "wavenumber," + ",".join(f"{200 + i}.0" for i in range(200)) + "\n" + "\n".join(
        f"s{t}," + ",".join(f"{(i * 7 + t) % 900}.5" for i in range(200)) for t in range(3)
    )
    descending = "\n".join(f"{800 - i}.0\t{(i * 37) % 900}.5" for i in range(300))
    large = "\n".join(f"{200 + i * 0.1:.1f}\t{(i * 37) % 900}.5" for i in range(60_000))

    yield "plain 2-column", two_col.encode(), 300, 1
    yield "axis in column 2", axis_col2.encode(), 300, 3
    yield "wide matrix 40col", wide.encode(), 300, 39
    yield "label + traces", labelled.encode(), 300, 2
    yield "stacked blank-sep", (block(200) + "\n\n" + block(200)).encode(), 60, 2
    yield "stacked no-sep", (block(200) + "\n" + block(200)).encode(), 60, 2
    yield "row-major", row_major.encode(), 200, 3
    yield "descending axis", descending.encode(), 300, 1
    yield "large (60k pts)", large.encode(), 60_000, 1

    for path in sorted(pathlib.Path(sys.argv[1]).glob("*.txt")):
        raw = path.read_bytes()
        expected = sum(
            1
            for line in raw.decode("utf-8", "ignore").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        yield f"REAL {path.name[:26]}", raw, expected, 1



rows = []
for name, raw, expected, want_traces in corpus():
    pv = build_preview(raw)
    rank = detect_layout_by_ranking(raw, pv)
    heur = detect_layout_heuristic(pv)
    heur_ok = heur is not None and verify_layout(raw, heur)

    def points(layout, data=raw):
        """Points as *stored* — after canonicalization, which is where a
        wrong axis collapses to a handful of duplicate values."""
        if layout is None:
            return None
        try:
            x, y = extract_trace(data, layout, layout.traces[0].index)
            return int(canonicalize_raman_arrays(x, y)[0].size)
        except (LayoutError, RamanDataError, IndexError, ValueError):
            return None

    rows.append((
        name,
        "ranked" if rank else ("heuristic" if heur_ok else "LLM"),
        "heuristic" if heur_ok else "LLM",
        points(rank), points(heur) if heur_ok else None,
        expected, want_traces,
        len(rank.traces) if rank else None,
        len(heur.traces) if heur_ok else None,
    ))

w = max(len(r[0]) for r in rows)
print(f"{'file':<{w}}  {'before':<10} {'after':<10} {'pts before':>10} {'pts after':>10} {'expected':>9}  verdict")
print("-" * (w + 62))
llm_b = llm_a = wrong_b = wrong_a = 0
for name, after, before, pa, pb, exp, want_t, ta, tb in rows:
    llm_b += before == "LLM"
    llm_a += after == "LLM"
    # Wrong = right rung, wrong answer: either the wrong number of points, or
    # the wrong number of spectra (two blocks merged into one still has the
    # right point count).
    bad_b = before != "LLM" and (pb != exp or tb != want_t)
    bad_a = after != "LLM" and (pa != exp or ta != want_t)
    wrong_b += bad_b; wrong_a += bad_a
    verdict = "silently wrong BEFORE" if bad_b and not bad_a else ("STILL WRONG" if bad_a else "")
    print(f"{name:<{w}}  {before:<10} {after:<10} {pb!s:>10} {pa!s:>10} {exp:>9}  {verdict}")
n = len(rows)
print("-" * (w + 62))
print(f"needs a model : before {llm_b}/{n}   after {llm_a}/{n}")
print(f"silently wrong: before {wrong_b}/{n}   after {wrong_a}/{n}")
