"""Tests for app.ingestion.structure — working out where a file's spectra are.

The load-bearing property under test is that a layout is only ever accepted
when it actually produces a canonical spectrum from the real bytes. The LLM
rung is mocked everywhere: what matters is that a wrong answer from it is
rejected, not that a model can be coaxed into a right one.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.ingestion import structure
from app.ingestion.structure import (
    build_preview,
    compute_structure_hash,
    detect_layout_heuristic,
    extract_trace,
    resolve_layout,
    verify_layout,
)
from app.schemas.ingestion import FileLayout, TraceSpec


def _run(coro):
    return asyncio.run(coro)


def _two_column(points: int = 40) -> bytes:
    lines = ["# Renishaw export", "# Laser 785 nm"]
    lines += [f"{100 + index * 0.5:.4f}\t{1000 + index:.3f}" for index in range(points)]
    return "\n".join(lines).encode()


def _column_major(traces: int = 3, points: int = 40) -> bytes:
    header = "Wavenumber\t" + "\t".join(f"sample_{n}" for n in range(traces))
    lines = [header]
    for index in range(points):
        x = 100 + index * 0.5
        row = [f"{x:.4f}"] + [f"{(n + 1) * 100 + index:.3f}" for n in range(traces)]
        lines.append("\t".join(row))
    return "\n".join(lines).encode()


def _row_major(traces: int = 3, points: int = 40) -> bytes:
    axis = ["wavenumber"] + [f"{100 + index * 0.5:.4f}" for index in range(points)]
    lines = [",".join(axis)]
    for n in range(traces):
        lines.append(
            ",".join([f"sample_{n}"] + [f"{(n + 1) * 100 + index:.3f}" for index in range(points)])
        )
    return "\n".join(lines).encode()


def _stacked_blocks(traces: int = 3, points: int = 40) -> bytes:
    blocks = []
    for n in range(traces):
        rows = [f"{100 + index * 0.5:.4f} {(n + 1) * 100 + index:.3f}" for index in range(points)]
        blocks.append(f"# spectrum {n}\n" + "\n".join(rows))
    return "\n\n".join(blocks).encode()


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("delimiter", "expected"),
    [("\t", "\t"), (",", ","), (";", ";"), ("|", "|"), (" ", "whitespace")],
)
def test_build_preview_detects_the_delimiter(delimiter, expected):
    body = "\n".join(
        delimiter.join([f"{100 + i * 0.5:.2f}", f"{i}.0", f"{i * 2}.0"]) for i in range(20)
    )
    preview = build_preview(body.encode())
    assert preview.delimiter == expected
    assert preview.column_count == 3


def test_build_preview_detects_a_comma_decimal_separator():
    """European exports write 1234,5 — read as a comma delimiter, every value
    would be split in half."""
    body = "\n".join(f"{100 + i * 0.5:.2f};{i},5".replace(".", ",") for i in range(20))
    preview = build_preview(body.encode())
    assert preview.decimal_separator == ","
    assert preview.delimiter == ";"
    assert preview.column_count == 2


def test_build_preview_reports_numeric_fractions_and_comments():
    preview = build_preview(_two_column())
    assert preview.leading_comment_lines == 2
    assert preview.numeric_fraction == [1.0, 1.0]
    assert preview.column_count == 2


def test_build_preview_survives_an_empty_body():
    preview = build_preview(b"")
    assert preview.column_count == 0
    assert preview.rows == []


# ---------------------------------------------------------------------------
# Structure signature
# ---------------------------------------------------------------------------


def test_structure_hash_separates_headerless_files_of_different_widths():
    """Both files normalize to an empty header, so a header hash alone would
    collide and one would be read with the other's layout."""
    narrow = build_preview(b"\n".join(f"{i}.0 {i}.5".encode() for i in range(20)))
    wide = build_preview(b"\n".join(f"{i}.0 {i}.5 {i}.7 {i}.9".encode() for i in range(20)))
    assert compute_structure_hash(narrow) != compute_structure_hash(wide)


def test_structure_hash_is_stable_across_runs_of_the_same_format():
    first = build_preview(_column_major())
    second = build_preview(_column_major(points=90))
    assert compute_structure_hash(first) == compute_structure_hash(second)


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------


def test_heuristic_resolves_a_plain_two_column_file():
    layout = detect_layout_heuristic(build_preview(_two_column()))
    assert layout is not None
    assert layout.orientation == "column_major"
    assert [trace.index for trace in layout.traces] == [1]


def test_heuristic_finds_every_trace_in_a_column_major_file():
    layout = detect_layout_heuristic(build_preview(_column_major(traces=4)))
    assert layout is not None
    assert [trace.index for trace in layout.traces] == [1, 2, 3, 4]
    assert [trace.label for trace in layout.traces] == [f"sample_{n}" for n in range(4)]
    assert layout.header_rows == 1


def test_heuristic_declines_a_row_major_file():
    """Row-major reads as one long header row plus label columns — exactly the
    ambiguity that should be escalated rather than guessed."""
    assert detect_layout_heuristic(build_preview(_row_major())) is None


def test_heuristic_declines_a_file_with_a_non_numeric_middle_column():
    body = "\n".join(f"{100 + i * 0.5:.2f}\tlabel_{i}\t{i}.0" for i in range(20))
    assert detect_layout_heuristic(build_preview(body.encode())) is None


# ---------------------------------------------------------------------------
# Applying a layout
# ---------------------------------------------------------------------------


def test_extract_trace_reads_each_column_major_trace_separately():
    raw = _column_major(traces=3, points=10)
    layout = detect_layout_heuristic(build_preview(raw))
    first_x, first_y = extract_trace(raw, layout, 1)
    _, third_y = extract_trace(raw, layout, 3)
    assert first_x.size == 10
    assert first_y[0] == 100.0
    assert third_y[0] == 300.0


def test_extract_trace_reads_a_row_major_file():
    raw = _row_major(traces=3, points=10)
    layout = FileLayout(
        orientation="row_major",
        delimiter=",",
        header_rows=0,
        x_index=0,
        label_index=0,
        traces=[TraceSpec(index=1, label="sample_0"), TraceSpec(index=3, label="sample_2")],
        source="llm",
    )
    x, y = extract_trace(raw, layout, 1)
    assert x.size == 10
    assert x[0] == 100.0
    assert y[0] == 100.0
    _, third_y = extract_trace(raw, layout, 3)
    assert third_y[0] == 300.0


def test_extract_trace_reads_stacked_blocks():
    raw = _stacked_blocks(traces=3, points=10)
    layout = FileLayout(
        orientation="stacked_blocks",
        delimiter="whitespace",
        traces=[TraceSpec(index=n) for n in range(3)],
        source="llm",
    )
    _, first = extract_trace(raw, layout, 0)
    _, last = extract_trace(raw, layout, 2)
    assert first[0] == 100.0
    assert last[0] == 300.0


def test_extract_trace_skips_ragged_rows_rather_than_failing():
    body = "100.0\t1.0\n101.0\tbroken\n102.0\t3.0\n103.0\t4.0"
    layout = FileLayout(delimiter="\t", traces=[TraceSpec(index=1)])
    x, y = extract_trace(body.encode(), layout, 1)
    assert list(x) == [100.0, 102.0, 103.0]
    assert list(y) == [1.0, 3.0, 4.0]


# ---------------------------------------------------------------------------
# Verification — the gate that makes an LLM guess safe to act on
# ---------------------------------------------------------------------------


def test_verify_accepts_a_correct_layout():
    raw = _column_major()
    assert verify_layout(raw, detect_layout_heuristic(build_preview(raw))) is True


def test_verify_rejects_a_transposed_layout():
    """Reading a column-major file as row-major yields two rows of mixed text
    and numbers, not an ascending axis."""
    raw = _column_major()
    wrong = FileLayout(
        orientation="row_major",
        delimiter="\t",
        header_rows=0,
        x_index=0,
        traces=[TraceSpec(index=1)],
        source="llm",
    )
    assert verify_layout(raw, wrong) is False


def test_verify_rejects_a_layout_pointing_at_a_label_column():
    raw = _row_major()
    wrong = FileLayout(
        orientation="column_major",
        delimiter=",",
        header_rows=0,
        x_index=0,
        traces=[TraceSpec(index=1)],
        source="llm",
    )
    assert verify_layout(raw, wrong) is False


def test_verify_rejects_a_layout_with_no_traces():
    assert verify_layout(_two_column(), FileLayout(delimiter="\t", traces=[])) is False


def test_verify_rejects_an_out_of_range_trace():
    raw = _two_column()
    layout = FileLayout(delimiter="\t", traces=[TraceSpec(index=7)])
    assert verify_layout(raw, layout) is False


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------


def test_resolve_layout_stops_at_the_heuristic_without_calling_the_model(db_session):
    with patch.object(structure, "detect_layout_via_llm", AsyncMock()) as llm:
        layout, source = _run(resolve_layout(_column_major(), db_session))
    assert source == "heuristic"
    assert len(layout.traces) == 3
    llm.assert_not_awaited()


def test_resolve_layout_reuses_a_cached_layout(db_session):
    raw = _column_major()
    _run(resolve_layout(raw, db_session))
    with patch.object(structure, "detect_layout_heuristic") as heuristic:
        layout, source = _run(resolve_layout(raw, db_session))
    assert source == "cache"
    assert len(layout.traces) == 3
    heuristic.assert_not_called()


def test_resolve_layout_falls_through_to_the_model(db_session):
    raw = _row_major(traces=3, points=30)
    answer = FileLayout(
        orientation="row_major",
        delimiter=",",
        header_rows=0,
        x_index=0,
        label_index=0,
        traces=[TraceSpec(index=n + 1, label=f"sample_{n}") for n in range(3)],
        confidence=0.9,
        source="llm",
    )
    with patch.object(structure, "detect_layout_via_llm", AsyncMock(return_value=answer)):
        layout, source = _run(resolve_layout(raw, db_session, filename="map.csv"))
    assert source == "llm"
    assert [trace.index for trace in layout.traces] == [1, 2, 3]


def test_resolve_layout_rejects_an_unverifiable_model_answer(db_session):
    """A confident but wrong answer must not survive: it fails verification,
    the wide retry fails too, and the caller is told to ask the user."""
    raw = _row_major()
    wrong = FileLayout(
        orientation="column_major",
        delimiter=",",
        traces=[TraceSpec(index=1)],
        confidence=1.0,
        source="llm",
    )
    with patch.object(structure, "detect_layout_via_llm", AsyncMock(return_value=wrong)):
        layout, source = _run(resolve_layout(raw, db_session))
    assert layout is None
    assert source == "unresolved"


def test_resolve_layout_does_not_cache_an_unverified_layout(db_session):
    raw = _row_major()
    wrong = FileLayout(delimiter=",", traces=[TraceSpec(index=1)], source="llm")
    with patch.object(structure, "detect_layout_via_llm", AsyncMock(return_value=wrong)):
        _run(resolve_layout(raw, db_session))
    preview = build_preview(raw)
    assert structure.cached_layout(db_session, compute_structure_hash(preview)) is None


def test_a_user_declared_layout_wins_over_a_guess(db_session):
    raw = _column_major()
    layout, _ = _run(resolve_layout(raw, db_session))
    assert layout.source == "heuristic"
    declared = layout.model_copy(update={"source": "user", "traces": layout.traces[:1]})
    structure.store_layout(db_session, compute_structure_hash(build_preview(raw)), declared)
    reloaded = structure.cached_layout(db_session, compute_structure_hash(build_preview(raw)))
    assert reloaded.source == "user"
    assert len(reloaded.traces) == 1


# ---------------------------------------------------------------------------
# Repairing a model's trace list
#
# The model's real contribution is orientation and which column is the axis.
# Which columns hold numbers is something the preview measured exactly, so
# where the two disagree the measurement wins.
# ---------------------------------------------------------------------------


def _labelled_middle_column(points: int = 25) -> bytes:
    lines = ["Wavenumber\tSampleID\tIntensityA\tIntensityB"]
    for index in range(points):
        lines.append(
            f"{100 + index * 0.5:.4f}\tS{index % 3}\t{1000 + index:.3f}\t{2000 + index:.3f}"
        )
    return "\n".join(lines).encode()


def test_a_model_answer_naming_the_axis_and_a_text_column_is_repaired():
    raw = _labelled_middle_column()
    preview = build_preview(raw)
    # The classic wrong answer: traces numbered 0,1 as if they were counters.
    wrong = FileLayout(
        orientation="column_major",
        delimiter="\t",
        header_rows=1,
        x_index=0,
        traces=[TraceSpec(index=0), TraceSpec(index=1)],
        source="llm",
    )
    repaired = structure._repair_traces(wrong, preview)
    assert [trace.index for trace in repaired.traces] == [2, 3]
    assert [trace.label for trace in repaired.traces] == ["IntensityA", "IntensityB"]
    assert verify_layout(raw, repaired) is True


def test_repair_leaves_a_correct_answer_alone():
    raw = _column_major(traces=3)
    preview = build_preview(raw)
    correct = FileLayout(
        orientation="column_major",
        delimiter="\t",
        header_rows=1,
        x_index=0,
        traces=[TraceSpec(index=n, label=f"sample_{n - 1}") for n in (1, 2, 3)],
        source="llm",
    )
    repaired = structure._repair_traces(correct, preview)
    assert [t.label for t in repaired.traces] == ["sample_0", "sample_1", "sample_2"]


def test_repair_does_not_touch_row_major_answers():
    """Only column-major traces are columns; a row-major trace list is rows,
    which the per-column statistics say nothing about."""
    raw = _row_major()
    preview = build_preview(raw)
    layout = FileLayout(
        orientation="row_major",
        delimiter=",",
        x_index=0,
        label_index=0,
        traces=[TraceSpec(index=1), TraceSpec(index=2)],
        source="llm",
    )
    assert structure._repair_traces(layout, preview).traces == layout.traces
