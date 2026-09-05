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
    render_preview,
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
    assert source in {"ranked", "heuristic"}
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


def _unrankable(rows: int = 40) -> bytes:
    """A file every deterministic rung declines, so the model rungs are
    reached. No column is monotonic (so ranking has no axis to propose) and
    one column is text (so the heuristic bails on a mixed export). The tests
    below are about what happens to a model answer; without this they would
    silently start testing the ranker instead."""
    return "\n".join(
        ",".join(
            "tag" if column == 1 else str((index * 7 + column * 13) % 23)
            for column in range(4)
        )
        for index in range(rows)
    ).encode()


def test_resolve_layout_falls_through_to_the_model(db_session):
    raw = _unrankable()
    answer = FileLayout(
        orientation="column_major",
        delimiter=",",
        header_rows=0,
        x_index=0,
        # Column 1 is the text column, so the model's answer names column 2 —
        # it has to be verifiable, or this would test rejection instead.
        traces=[TraceSpec(index=2, label=None)],
        confidence=0.9,
        source="llm",
    )
    with patch.object(structure, "detect_layout_via_llm", AsyncMock(return_value=answer)):
        layout, source = _run(resolve_layout(raw, db_session, filename="map.csv"))
    assert source == "llm", "a file ranking cannot explain must still reach the model"
    assert layout.source == "llm"


def test_resolve_layout_rejects_an_unverifiable_model_answer(db_session):
    """A confident but wrong answer must not survive: it fails verification,
    the wide retry fails too, and the caller is told to ask the user."""
    raw = _unrankable()
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
    raw = _unrankable()
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


# ---------------------------------------------------------------------------
# patch sampling — the head window alone is blind to most of a file
# ---------------------------------------------------------------------------


def _two_column_block(start_wavenumber: int, rows: int = 60) -> str:
    return "\n".join(f"{start_wavenumber + i}.0\t{100 + i}.5" for i in range(rows))


def test_patches_sample_four_regions_beyond_the_head_window():
    raw = ("\n".join(f"{200 + i}.0\t{i}.5" for i in range(400))).encode()
    preview = build_preview(raw)

    assert [patch.label for patch in preview.patches] == ["25%", "50%", "75%", "tail"]
    starts = [patch.start_row for patch in preview.patches]
    assert starts == sorted(starts), "patches must be ordered and non-overlapping"
    # The last patch reaches the real end of the body.
    assert preview.patches[-1].start_row + len(preview.patches[-1].rows) == preview.body_lines


def test_a_body_the_head_window_already_covers_gets_no_patches():
    """Sampling a 8-row file five times would just re-print it."""
    raw = ("\n".join(f"{200 + i}.0\t{i}.5" for i in range(8))).encode()
    assert build_preview(raw).patches == []


def test_patches_do_not_overlap_on_a_short_body():
    raw = ("\n".join(f"{200 + i}.0\t{i}.5" for i in range(30))).encode()
    preview = build_preview(raw)
    seen: list[int] = []
    for sample in preview.patches:
        assert all(start + 6 <= sample.start_row for start in seen)
        seen.append(sample.start_row)


def test_a_restarting_axis_is_visible_in_the_samples():
    """Stacked blocks are the case the old head-only window could not see:
    the second block begins at body row 60."""
    raw = (_two_column_block(200) + "\n\n" + _two_column_block(200)).encode()
    preview = build_preview(raw)

    assert preview.blank_separated_blocks == 2
    rendered = render_preview(preview)
    # The axis restarting at 200.0 well down the body is the whole signal.
    midpoint = [p for p in preview.patches if p.start_row == 60]
    assert midpoint and midpoint[0].rows[0][0] == "200.0"
    assert "sample at 50% of the body" in rendered


def test_a_trailing_footer_reaches_the_model():
    body = "\n".join(f"{200 + i}.0,{i}.5" for i in range(300))
    raw = (body + "\n>>>>>End Spectral Data<<<<<\n").encode()
    rendered = render_preview(build_preview(raw))
    assert ">>>>>End Spectral Data<<<<<" in rendered


# ---------------------------------------------------------------------------
# wide files — column sampling
# ---------------------------------------------------------------------------


def _wide_matrix(columns: int, rows: int = 50) -> bytes:
    header = "\t".join(["wavenumber"] + [f"s{i}" for i in range(columns - 1)])
    body = [
        "\t".join([f"{200 + r}.0"] + [f"{r + c}.00" for c in range(columns - 1)])
        for r in range(rows)
    ]
    return (header + "\n" + "\n".join(body)).encode()


def test_wide_files_show_head_middle_and_tail_columns():
    preview = build_preview(_wide_matrix(200))
    assert preview.column_count == 200
    assert preview.truncated_columns is True
    shown = preview.columns_shown
    assert len(shown) == 12
    assert shown[:5] == [0, 1, 2, 3, 4], "the axis end of the file must be visible"
    assert shown[-4:] == [196, 197, 198, 199], "so must the far end"
    assert any(90 < index < 110 for index in shown), "and something from the middle"


def test_numeric_fractions_cover_every_column_not_just_the_printed_ones():
    """One float per column is cheap, and 'are all 200 columns numeric?' is
    the question that distinguishes a trace matrix from a labelled export."""
    preview = build_preview(_wide_matrix(200))
    assert len(preview.numeric_fraction) == 200
    assert all(fraction >= 0.9 for fraction in preview.numeric_fraction)


def test_rendered_columns_are_labelled_with_absolute_indexes():
    """On a wide file the printed columns are not contiguous, so an index the
    model reads off the grid must still be usable verbatim."""
    rendered = render_preview(build_preview(_wide_matrix(200)))
    assert "[199]" in rendered
    assert "showing 12 of 200 columns" in rendered
    # ...and the whole-file summary it needs to conclude "axis + 199 traces".
    assert "200 of 200" in rendered


def test_narrow_files_are_unchanged_and_show_every_column():
    preview = build_preview(_wide_matrix(4))
    assert preview.columns_shown == [0, 1, 2, 3]
    assert preview.truncated_columns is False


def test_patch_sampling_does_not_change_the_layout_cache_key():
    """`compute_structure_hash` keys on format, not on sampled rows — so
    richer sampling must not invalidate every cached layout."""
    raw = _wide_matrix(8)
    assert compute_structure_hash(build_preview(raw)) == compute_structure_hash(
        build_preview(raw, max_rows=40, max_columns=25)
    )


# ---------------------------------------------------------------------------
# reading the numbers out must not inherit the detection window
# ---------------------------------------------------------------------------


def test_a_large_file_extracts_every_point():
    """`extract_trace` used to share the 256 KB structure-sniff window, so a
    747 KB export silently yielded 20,978 of its 60,000 points — no error, no
    QC flag, and `verify_layout` passed. A short spectrum is worse than a
    rejected one, because nothing downstream can tell it was short."""
    points = 60_000
    raw = ("\n".join(f"{200 + i * 0.1:.1f}\t{(i * 37) % 900}.5" for i in range(points))).encode()
    assert len(raw) > structure.STRUCTURE_SNIFF_BYTES, "fixture must exceed the sniff window"

    preview = build_preview(raw)
    layout = FileLayout(
        orientation="column_major",
        delimiter=preview.delimiter,
        decimal_separator=preview.decimal_separator,
        comment_prefixes=["#"],
        header_rows=preview.header_rows,
        x_index=0,
        traces=[TraceSpec(index=1, label=None)],
        confidence=1.0,
        source="user",
    )
    x, y = extract_trace(raw, layout, 1)
    assert x.size == points
    assert y.size == points


def test_detection_still_only_reads_the_sniff_window():
    """The bound is right for detection — it just must not reach extraction."""
    big = ("\n".join(f"{200 + i * 0.1:.1f}\t{i}.5" for i in range(60_000))).encode()
    assert len(structure.decode_text(big)) <= structure.STRUCTURE_SNIFF_BYTES
    assert len(structure.decode_text(big, whole_file=True)) > structure.STRUCTURE_SNIFF_BYTES


# ---------------------------------------------------------------------------
# deterministic ranking — choosing between layouts that all "verify"
# ---------------------------------------------------------------------------


def test_axis_score_separates_an_axis_from_an_intensity_column():
    axis = [200.0 + i for i in range(300)]
    intensity = [float((i * 37) % 900) for i in range(300)]
    assert structure.axis_score(axis) > 0.9
    assert structure.axis_score(intensity) == 0.0


def test_axis_score_accepts_a_descending_axis():
    """Descending axes are common; canonicalization sorts them later."""
    assert structure.axis_score([800.0 - i for i in range(300)]) > 0.9


def test_axis_score_ranks_a_timestamp_below_a_real_axis():
    """Monotonic and evenly spaced, but nowhere near a Raman shift."""
    stamps = [1.7e9 + i for i in range(300)]
    axis = [200.0 + i for i in range(300)]
    assert 0.0 < structure.axis_score(stamps) < structure.axis_score(axis)


def test_axis_restarts_finds_block_boundaries_without_a_separator():
    series = [200.0 + (i % 60) for i in range(180)]
    assert structure.axis_restarts(series) == [60, 120]
    assert structure.axis_restarts([200.0 + i for i in range(60)]) == []


def test_ranking_picks_the_real_axis_when_it_is_not_column_zero():
    """The old heuristic assumed column 0 and produced a layout that *verified*
    while being wrong: an index column sorts and dedupes to a handful of points,
    so a 300-point spectrum was stored as a few."""
    raw = (
        "\n".join(f"{i % 7}\t{(i * 3) % 11}\t{200 + i}.0\t{(i * 37) % 900}.5" for i in range(300))
    ).encode()
    layout = structure.detect_layout_by_ranking(raw, build_preview(raw))
    assert layout is not None
    assert layout.x_index == 2
    x, _y = extract_trace(raw, layout, 3)
    assert x.size == 300, "the whole spectrum, not the few unique values of an index column"


def test_ranking_resolves_a_wide_matrix_without_a_model():
    header = "\t".join(["wavenumber"] + [f"s{i}" for i in range(39)])
    body = [
        "\t".join([f"{200 + r}.0"] + [f"{(r * 7 + c) % 900}.0" for c in range(39)])
        for r in range(300)
    ]
    raw = (header + "\n" + "\n".join(body)).encode()
    layout = structure.detect_layout_by_ranking(raw, build_preview(raw))
    assert layout is not None
    assert layout.orientation == "column_major"
    assert len(layout.traces) == 39


def test_ranking_resolves_a_row_major_file_without_a_model():
    raw = (
        "wavenumber," + ",".join(f"{200 + i}.0" for i in range(200)) + "\n"
        + "\n".join(
            f"s{t}," + ",".join(f"{(i * 7 + t) % 900}.5" for i in range(200)) for t in range(3)
        )
    ).encode()
    layout = structure.detect_layout_by_ranking(raw, build_preview(raw))
    assert layout is not None
    assert layout.orientation == "row_major"
    assert len(layout.traces) == 3


@pytest.mark.parametrize("separator", ["\n", "\n\n"])
def test_ranking_resolves_stacked_blocks_with_or_without_a_blank_line(separator):
    """A blank line is the easy case. An export that simply concatenates its
    blocks has no marker at all except the axis starting over — and the old
    pipeline read those two blocks as one spectrum."""
    block = "\n".join(f"{200 + i}.0\t{100 + (i * 7) % 50}.5" for i in range(60))
    raw = (block + separator + block).encode()
    layout = structure.detect_layout_by_ranking(raw, build_preview(raw))
    assert layout is not None
    assert layout.orientation == "stacked_blocks"
    assert len(layout.traces) == 2
    for index in range(2):
        x, _y = extract_trace(raw, layout, index)
        assert x.size == 60


def test_ranking_declines_rather_than_guessing():
    """A wrong deterministic answer is worse than an LLM call, because nothing
    downstream questions it."""
    raw = _unrankable()
    assert structure.rank_candidates(raw, build_preview(raw)) == []
    assert structure.detect_layout_by_ranking(raw, build_preview(raw)) is None


def test_ranked_layouts_are_still_gated_on_arithmetic():
    """Ranking proposes; `verify_layout` disposes. Every candidate returned by
    the ladder has been applied to the real bytes."""
    raw = _column_major(traces=3)
    layout = structure.detect_layout_by_ranking(raw, build_preview(raw))
    assert layout is not None and verify_layout(raw, layout)
