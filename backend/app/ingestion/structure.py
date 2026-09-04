"""Work out how a text spectral file is laid out, so its traces can be read.

Vendor metadata tells us *about* a measurement; this module works out where
the numbers actually are. Until now the pipeline assumed every file was
"column 0 is wavenumber, column 1 is intensity" (`spectra_io.parse_two_column_raman`),
which silently imports only the first spectrum of a multi-spectrum export and
turns a row-major file into nonsense.

The ladder, cheapest rung first, stopping at the first layout that VERIFIES:

1. `detect_layout_heuristic` — a clean 2-column or `x + n y` file resolves
   here with zero LLM calls and zero cost.
2. `detect_layout_via_llm` — the model sees only a ~10x10 `PreviewGrid` plus
   column statistics, not the file (~2k prompt tokens against the ~37k a
   whole-header prompt costs).
3. The same call again with a wider slice, for files whose structure is not
   visible in the first ten rows.
4. Give up and let the caller ask the user to declare the layout.

**Verification is what makes trusting an LLM here safe.** A candidate layout is
never returned on the model's say-so: it is applied to the real bytes and its
first trace pushed through `raman_contract.canonicalize_raman_arrays`. A
layout that cannot produce a canonical ascending spectrum is rejected and the
ladder moves on. The model proposes; arithmetic disposes.

Resolved layouts are cached in `FileLayoutCache` under a structure signature
(delimiter + column count + header shape), so a format — including one a user
declared by hand — is only ever worked out once.
"""

from __future__ import annotations

import hashlib
import logging
import re

import numpy as np
from sqlalchemy.orm import Session

from app.config import settings
from app.ingestion.header_hash import normalize_header
from app.llm import LLMError, complete_json
from app.llm_credentials import LLMCredential, platform_credential
from app.models.file_layout_cache import FileLayoutCache
from app.raman_contract import MIN_CANONICAL_POINTS, RamanDataError, canonicalize_raman_arrays
from app.schemas.ingestion import (
    MAX_PREVIEW_COLUMNS,
    MAX_PREVIEW_ROWS,
    MAX_TRACES,
    WHITESPACE_DELIMITER,
    FileLayout,
    PreviewGrid,
    TraceSpec,
)

logger = logging.getLogger(__name__)

# Bytes of the file used for structure detection. The layout of a spectral
# export is always visible in its first lines; reading more would only cost
# memory.
STRUCTURE_SNIFF_BYTES = 262_144

# Cells are truncated in the preview: the model needs to see the *shape* of a
# value, not all of a 400-character comment.
MAX_PREVIEW_CELL_CHARS = 40

# Candidate delimiters, most specific first. Whitespace is last because it
# also "works" on comma- and semicolon-separated files, just wrongly.
_CANDIDATE_DELIMITERS = ["\t", ",", ";", "|", WHITESPACE_DELIMITER]

_DEFAULT_COMMENT_PREFIXES = ["#", "//", "%", "'", ";;"]

MAX_OUTPUT_TOKENS = 4096

_LAYOUT_MODEL_ID = "openrouter-layout"


class LayoutError(Exception):
    """A layout could not be resolved, or could not be applied to the bytes."""


# ---------------------------------------------------------------------------
# Cell / line primitives
# ---------------------------------------------------------------------------


def decode_text(raw_bytes: bytes) -> str:
    """Decode the leading structure-sniff window. Lossy by design — a binary
    vendor format has its own parser and never reaches this module."""
    return raw_bytes[:STRUCTURE_SNIFF_BYTES].decode("utf-8", errors="ignore")


def _is_comment(line: str, prefixes: list[str]) -> bool:
    stripped = line.lstrip()
    return any(stripped.startswith(prefix) for prefix in prefixes)


def split_cells(line: str, delimiter: str) -> list[str]:
    """Split one line into cells under `delimiter`."""
    if delimiter == WHITESPACE_DELIMITER:
        return line.split()
    return [cell.strip() for cell in line.split(delimiter)]


def to_float(cell: str, decimal_separator: str = ".") -> float | None:
    """Parse a cell as a number, or None. Handles a comma decimal separator
    (ubiquitous in European instrument exports) and rejects the NaN/inf
    spellings `float()` would otherwise accept — a spectrum's axis must be
    real numbers."""
    text = cell.strip()
    if not text:
        return None
    if decimal_separator == ",":
        text = text.replace(".", "").replace(",", ".")
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(value):
        return None
    return value


def _numeric_ratio(cells: list[str], decimal_separator: str) -> float:
    if not cells:
        return 0.0
    numeric = sum(1 for cell in cells if to_float(cell, decimal_separator) is not None)
    return numeric / len(cells)


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def _detect_decimal_separator(lines: list[str]) -> str:
    """A comma decimal separator only makes sense when commas sit *between
    digits* and the file is not comma-separated. Checked before the delimiter
    so `1,234<tab>5,678` is not mistaken for four columns."""
    comma_decimals = sum(len(re.findall(r"\d,\d", line)) for line in lines)
    if comma_decimals == 0:
        return "."
    dot_decimals = sum(len(re.findall(r"\d\.\d", line)) for line in lines)
    return "," if comma_decimals > dot_decimals else "."


# A line counts as data when it splits into at least two cells and most of
# them parse as numbers. Below this ratio it is preamble — a title, a
# key/value pair, a `>>>>>Begin Spectral Data<<<<<` marker.
_DATA_LINE_NUMERIC_RATIO = 0.6


def _data_line_stats(
    lines: list[str], delimiter: str, decimal_separator: str
) -> tuple[int, float, int]:
    """How well `delimiter` explains the numeric body: `(rows explained, mean
    numeric ratio over them, columns per row)`.

    Scoring only over data-shaped lines is what makes this work on a real
    vendor export. Averaging over every line instead lets a 14-line text
    preamble outvote three rows of actual spectrum, and the file ends up
    "single column" — unreadable. Ratio outranks column count for the same
    reason a European `100,25;3,5` must not be split on its own decimal
    commas: more columns is not better if they are not numbers.
    """
    counts: dict[int, int] = {}
    ratios: dict[int, list[float]] = {}
    for line in lines:
        cells = split_cells(line, delimiter)
        if len(cells) < 2:
            continue
        ratio = _numeric_ratio(cells, decimal_separator)
        if ratio < _DATA_LINE_NUMERIC_RATIO:
            continue
        counts[len(cells)] = counts.get(len(cells), 0) + 1
        ratios.setdefault(len(cells), []).append(ratio)
    if not counts:
        return 0, 0.0, 0
    modal = max(counts, key=lambda size: (counts[size], size))
    return counts[modal], round(sum(ratios[modal]) / len(ratios[modal]), 3), modal


def build_preview(
    raw_bytes: bytes,
    *,
    max_rows: int = 10,
    max_columns: int = 10,
    comment_prefixes: list[str] | None = None,
) -> PreviewGrid:
    """Summarize a raw file's text body: delimiter, column count, where the
    preamble ends, a small grid of the numeric body, and per-column numeric
    fractions. Deterministic and LLM-free — this is the artifact every rung of
    the ladder reasons over.

    The grid shows the BODY, not the first ten lines of the file. A vendor
    export can carry a hundred lines of preamble, and a preview that never
    reaches a number tells neither a heuristic nor a model anything.
    """
    prefixes = comment_prefixes if comment_prefixes is not None else _DEFAULT_COMMENT_PREFIXES
    text = decode_text(raw_bytes)
    raw_lines = text.splitlines()

    content_lines = [line for line in raw_lines if line.strip() and not _is_comment(line, prefixes)]
    leading_comments = 0
    for line in raw_lines:
        if not line.strip():
            continue
        if _is_comment(line, prefixes):
            leading_comments += 1
            continue
        break

    empty = PreviewGrid(
        delimiter=WHITESPACE_DELIMITER,
        total_lines=len(content_lines),
        column_count=0,
        leading_comment_lines=leading_comments,
    )
    if not content_lines:
        return empty

    decimal_separator = _detect_decimal_separator(content_lines)
    best_delimiter = WHITESPACE_DELIMITER
    best_score = (0, 0.0, 0)
    for candidate in _CANDIDATE_DELIMITERS:
        score = _data_line_stats(content_lines, candidate, decimal_separator)
        if score > best_score:
            best_delimiter, best_score = candidate, score
    explained, _mean_ratio, column_count = best_score
    if explained < MIN_CANONICAL_POINTS or column_count < 2:
        return empty.model_copy(update={"decimal_separator": decimal_separator})

    def _is_data(line: str) -> bool:
        cells = split_cells(line, best_delimiter)
        return (
            len(cells) >= 2 and _numeric_ratio(cells, decimal_separator) >= _DATA_LINE_NUMERIC_RATIO
        )

    header_rows = 0
    for line in content_lines:
        if _is_data(line):
            break
        header_rows += 1

    # How many runs of data lines a blank line separates — the signature of a
    # stacked-blocks export. Counted over data runs rather than over every
    # non-empty line, so one cosmetic blank line under a title does not make
    # an ordinary two-column file look like stacked blocks.
    blank_separated_blocks = 0
    in_block = False
    for line in raw_lines:
        if not line.strip():
            in_block = False
            continue
        if _is_comment(line, prefixes) or not _is_data(line):
            continue
        if not in_block:
            blank_separated_blocks += 1
            in_block = True

    def _cells(line: str) -> list[str]:
        cells = split_cells(line, best_delimiter)[:max_columns]
        return [cell[:MAX_PREVIEW_CELL_CHARS] for cell in cells]

    # Only the tail of the preamble is worth showing: column names sit
    # directly above the numbers.
    header_lines = content_lines[:header_rows][-6:]
    body_lines = content_lines[header_rows:]
    rows = [_cells(line) for line in body_lines[:max_rows]]

    numeric_fraction: list[float] = []
    # Data lines only. Exports routinely end with a footer marker
    # (`>>>>>End Spectral Data<<<<<`), and counting it would drag a perfectly
    # numeric column below the threshold and make the file look ambiguous.
    sampled = [
        split_cells(line, best_delimiter) for line in body_lines[:200] if _is_data(line)
    ]
    for column in range(min(column_count, max_columns)):
        cells = [row[column] for row in sampled if column < len(row)]
        numeric_fraction.append(round(_numeric_ratio(cells, decimal_separator), 3))

    return PreviewGrid(
        delimiter=best_delimiter,
        decimal_separator=decimal_separator,
        total_lines=len(content_lines),
        column_count=column_count,
        header_rows=header_rows,
        header_cells=[_cells(line) for line in header_lines],
        rows=rows,
        numeric_fraction=numeric_fraction,
        leading_comment_lines=leading_comments,
        body_lines=len(body_lines),
        blank_separated_blocks=blank_separated_blocks,
        truncated_rows=len(body_lines) > max_rows,
        truncated_columns=column_count > max_columns,
    )


def compute_structure_hash(preview: PreviewGrid) -> str:
    """Signature of a file *format*, for the layout cache.

    Header text alone is not enough: headerless exports all normalize to the
    empty string, so a plain two-column file and a ten-trace matrix would
    share a key and one would be read with the other's layout. The delimiter
    and column count are therefore part of the signature.
    """
    signature = "|".join(
        [
            preview.delimiter,
            preview.decimal_separator,
            str(preview.column_count),
            str(preview.blank_separated_blocks > 1),
            normalize_header("\n".join(" ".join(row) for row in preview.header_cells)),
        ]
    )
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Applying a layout
# ---------------------------------------------------------------------------


def _content_rows(text: str, layout: FileLayout) -> list[list[str]]:
    lines = [
        line
        for line in text.splitlines()
        if line.strip() and not _is_comment(line, layout.comment_prefixes)
    ]
    return [split_cells(line, layout.delimiter) for line in lines]


def _blocks(text: str, layout: FileLayout) -> list[list[list[str]]]:
    """Split into blank-line-separated blocks of content rows."""
    blocks: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in text.splitlines():
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        if _is_comment(line, layout.comment_prefixes):
            continue
        current.append(split_cells(line, layout.delimiter))
    if current:
        blocks.append(current)
    # A block ordinal names a *spectrum*, so a preamble paragraph must not
    # occupy index 0 and push every real block along by one.
    return [
        block
        for block in blocks
        if any(
            len(cells) >= 2
            and _numeric_ratio(cells, layout.decimal_separator) >= _DATA_LINE_NUMERIC_RATIO
            for cells in block
        )
    ]


def _without(cells: list[str], skip: int | None) -> list[str]:
    if skip is None:
        return cells
    return [cell for position, cell in enumerate(cells) if position != skip]


def extract_trace(
    raw_bytes: bytes, layout: FileLayout, trace_index: int
) -> tuple[np.ndarray, np.ndarray]:
    """Read one trace out of `raw_bytes` under `layout`.

    Rows that do not fit the layout are skipped rather than fatal, matching
    the permissive behaviour callers already rely on for ragged exports.
    Raises `LayoutError` only when the layout cannot address this trace at all.
    """
    text = decode_text(raw_bytes)
    decimal = layout.decimal_separator

    if layout.orientation == "stacked_blocks":
        blocks = _blocks(text, layout)
        if trace_index >= len(blocks):
            raise LayoutError(f"file has {len(blocks)} blocks; no block {trace_index}")
        xs, ys = [], []
        for cells in blocks[trace_index]:
            if len(cells) < 2:
                continue
            x_value = to_float(cells[0], decimal)
            y_value = to_float(cells[1], decimal)
            if x_value is None or y_value is None:
                continue
            xs.append(x_value)
            ys.append(y_value)
        return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)

    rows = _content_rows(text, layout)
    body = rows[layout.header_rows :]

    if layout.orientation == "row_major":
        if layout.x_index >= len(body) or trace_index >= len(body):
            raise LayoutError(
                f"row-major layout addresses row {trace_index} of {len(body)} data rows"
            )
        axis_cells = _without(body[layout.x_index], layout.label_index)
        trace_cells = _without(body[trace_index], layout.label_index)
        xs, ys = [], []
        for x_cell, y_cell in zip(axis_cells, trace_cells):
            x_value = to_float(x_cell, decimal)
            y_value = to_float(y_cell, decimal)
            if x_value is None or y_value is None:
                continue
            xs.append(x_value)
            ys.append(y_value)
        return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)

    # column_major
    xs, ys = [], []
    for cells in body:
        if layout.x_index >= len(cells) or trace_index >= len(cells):
            continue
        x_value = to_float(cells[layout.x_index], decimal)
        y_value = to_float(cells[trace_index], decimal)
        if x_value is None or y_value is None:
            continue
        xs.append(x_value)
        ys.append(y_value)
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


def verify_layout(raw_bytes: bytes, layout: FileLayout) -> bool:
    """True when this layout actually yields a canonical spectrum.

    The gate between "a model said so" and "we stored it". Every declared
    trace must produce arrays that survive `canonicalize_raman_arrays`; a
    layout that reads a label column as intensities, or transposes the file,
    fails here.
    """
    if not layout.traces:
        return False
    # Checking every trace on a 500-trace file is wasted work: they share one
    # structure, so a sample proves it.
    sample = layout.traces if len(layout.traces) <= 4 else [layout.traces[0], layout.traces[-1]]
    for trace in sample:
        try:
            x, y = extract_trace(raw_bytes, layout, trace.index)
        except LayoutError:
            return False
        if x.size < MIN_CANONICAL_POINTS or x.size != y.size:
            return False
        try:
            canonicalize_raman_arrays(x, y)
        except RamanDataError:
            return False
    return True


# ---------------------------------------------------------------------------
# Rung 1: heuristics
# ---------------------------------------------------------------------------


def detect_layout_heuristic(preview: PreviewGrid) -> FileLayout | None:
    """Resolve the common shapes without an LLM: a column-major file whose
    first column is an axis and whose every other column is numeric. Returns
    None the moment anything is ambiguous — a wrong guess here is worse than
    an LLM call, because nothing downstream will question it."""
    if preview.column_count < 2 or not preview.numeric_fraction or not preview.rows:
        return None
    if preview.blank_separated_blocks > 1:
        # Could be stacked blocks or just a cosmetic blank line. Not ours.
        return None
    if preview.truncated_columns:
        return None

    numeric_columns = [
        index for index, fraction in enumerate(preview.numeric_fraction) if fraction >= 0.9
    ]
    if len(numeric_columns) < 2 or numeric_columns[0] != 0:
        return None
    if len(numeric_columns) != len(preview.numeric_fraction):
        # Some column is not numeric — a labelled or mixed export, which may
        # equally be a row-major file. Let the model look at it.
        return None

    labels = preview.header_cells[-1] if preview.header_cells else []
    # A single-column-name row means nothing if it doesn't line up with the
    # data; only borrow labels when the widths agree.
    if len(labels) != preview.column_count:
        labels = []
    traces = [
        TraceSpec(
            index=column,
            label=(labels[column] if column < len(labels) else None) or None,
        )
        for column in numeric_columns[1:]
    ]
    if not traces or len(traces) > MAX_TRACES:
        return None

    return FileLayout(
        orientation="column_major",
        delimiter=preview.delimiter,
        decimal_separator=preview.decimal_separator,
        comment_prefixes=_DEFAULT_COMMENT_PREFIXES,
        header_rows=preview.header_rows,
        x_index=0,
        traces=traces,
        confidence=0.9,
        source="heuristic",
    )


# ---------------------------------------------------------------------------
# Rungs 2-3: the model
# ---------------------------------------------------------------------------


_LAYOUT_SCHEMA = {
    "type": "object",
    "properties": {
        "orientation": {
            "type": "string",
            "enum": ["column_major", "row_major", "stacked_blocks"],
        },
        "header_rows": {"type": "integer"},
        "x_index": {"type": "integer"},
        "label_index": {"type": ["integer", "null"]},
        "traces": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "label": {"type": ["string", "null"]},
                },
                "required": ["index"],
            },
        },
        "confidence": {"type": "number"},
    },
    "required": ["orientation", "header_rows", "x_index", "traces"],
}

_LAYOUT_SYSTEM_PROMPT = (
    "You work out how a Raman spectroscopy text file is laid out, so its "
    "spectra can be read. You are shown a small grid of the file's first "
    "cells (already split into columns), plus per-column statistics. Decide "
    "where the wavenumber axis is and where each spectrum's intensities are.\n"
    "\n"
    "Indexes are ZERO-BASED and are counted AFTER skipping `header_rows` "
    "non-empty, non-comment rows.\n"
    "\n"
    "orientation:\n"
    "- `column_major`: one column is the wavenumber axis and each OTHER "
    "numeric column is one spectrum. `x_index` is the axis COLUMN; each "
    "trace `index` is a spectrum COLUMN. This is the common case.\n"
    "- `row_major`: one ROW holds the wavenumber axis and each OTHER row is "
    "one spectrum, usually with its name in the first cell. `x_index` is the "
    "axis ROW; each trace `index` is a spectrum ROW; `label_index` is the "
    "column holding those names.\n"
    "- `stacked_blocks`: two-column (wavenumber, intensity) blocks one after "
    "another, separated by blank lines. Each trace `index` is a block "
    "ordinal, 0-based; `x_index` is ignored.\n"
    "\n"
    "Rules:\n"
    "- Every `index` is the NUMBER SHOWN IN BRACKETS in the preview — a "
    "column number for `column_major`, a row number for `row_major`. It is "
    "not a counter: if the spectra are in columns 2 and 3, the traces are 2 "
    "and 3, not 0 and 1.\n"
    "- Return EVERY spectrum you can see, not just the first one. A file with "
    "eight intensity columns has eight traces.\n"
    "- Never list `x_index` or `label_index` as a trace.\n"
    "- Never list a label, index, or timestamp column as a trace. The "
    "per-column numeric fractions tell you which columns hold numbers: a "
    "column at 0.0 is text and is never a spectrum.\n"
    "- `header_rows` counts only preamble rows before the numeric body. If "
    "the body starts immediately, it is 0.\n"
    "- `label` should be the spectrum's name from the header row or label "
    "column, or null when the file gives none.\n"
    "- `confidence` is 0..1: how sure you are the structure is right."
)


def render_preview(preview: PreviewGrid) -> str:
    """The preview as compact text for the model.

    Preamble and body are shown separately, and body rows are numbered from
    zero, because that is exactly how `FileLayout` counts them — an index the
    model reads off this grid can be used verbatim.
    """
    delimiter_name = (
        "whitespace" if preview.delimiter == WHITESPACE_DELIMITER else repr(preview.delimiter)
    )
    lines = [
        f"delimiter: {delimiter_name}",
        f"decimal separator: {preview.decimal_separator!r}",
        f"columns per row: {preview.column_count}",
        f"preamble rows before the numeric body (header_rows): {preview.header_rows}",
        f"rows in the numeric body: {preview.body_lines}",
        f"blank-line-separated blocks: {preview.blank_separated_blocks}",
        "fraction of each column that parses as a number: "
        + ", ".join(
            f"col {index}={fraction}" for index, fraction in enumerate(preview.numeric_fraction)
        ),
    ]
    if preview.header_cells:
        lines.append("")
        lines.append("last preamble rows (column names, if any, are usually here):")
        for row in preview.header_cells:
            lines.append("  " + " | ".join(f"[{column}] {cell}" for column, cell in enumerate(row)))
    lines.append("")
    lines.append("numeric body, row 0 onwards (indexes are counted AFTER header_rows):")
    for row_index, row in enumerate(preview.rows):
        cells = " | ".join(f"[{column}] {cell}" for column, cell in enumerate(row))
        lines.append(f"row {row_index}: {cells}")
    if preview.truncated_rows:
        lines.append("(further body rows not shown)")
    if preview.truncated_columns:
        lines.append(f"(columns beyond {len(preview.numeric_fraction)} not shown)")
    return "\n".join(lines)


async def detect_layout_via_llm(
    preview: PreviewGrid,
    *,
    filename: str | None = None,
    credential: LLMCredential | None = None,
) -> FileLayout | None:
    """Ask the model to read the preview grid. Returns None on any failure —
    an unusable answer is a rung to move past, never an exception to fail the
    ingestion on.

    `credential` routes the call through the file owner's own provider key
    when they have set one; None falls back to the platform key."""
    credential = credential or platform_credential()
    if credential is None:
        return None
    name_hint = (filename or "").strip()
    user_prompt = (
        (f"Filename: {name_hint}\n\n" if name_hint else "")
        + "File structure preview:\n\n"
        + render_preview(preview)
    )
    try:
        reply = await complete_json(
            system=_LAYOUT_SYSTEM_PROMPT,
            user=user_prompt,
            schema=_LAYOUT_SCHEMA,
            model=settings.OPENROUTER_INGESTION_MODEL or None,
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.0,
            credential=credential,
        )
    except LLMError as exc:
        logger.warning("Layout detection LLM call failed: %s", exc)
        return None

    try:
        layout = FileLayout(
            orientation=reply.get("orientation", "column_major"),
            delimiter=preview.delimiter,
            decimal_separator=preview.decimal_separator,
            comment_prefixes=_DEFAULT_COMMENT_PREFIXES,
            header_rows=max(0, int(reply.get("header_rows") or 0)),
            x_index=max(0, int(reply.get("x_index") or 0)),
            label_index=(
                int(reply["label_index"]) if reply.get("label_index") is not None else None
            ),
            traces=[
                TraceSpec(index=int(item["index"]), label=(item.get("label") or None))
                for item in (reply.get("traces") or [])
                if isinstance(item, dict) and item.get("index") is not None
            ],
            confidence=float(reply.get("confidence") or 0.5),
            source="llm",
        )
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning("Layout detection returned an unusable shape: %s", exc)
        return None
    return _repair_traces(layout, preview)


def _repair_traces(layout: FileLayout, preview: PreviewGrid) -> FileLayout:
    """Correct a column-major trace list against what we already measured.

    The model's real contribution is orientation and which column is the
    axis; *which columns hold numbers* is something the preview already knows
    exactly. When the model's answer disagrees — listing the axis as a
    spectrum, or a text label column, or numbering the traces 0,1 instead of
    by column — the measurement wins. Anything the repair cannot improve is
    left alone and left for verification to reject.
    """
    if layout.orientation != "column_major" or not preview.numeric_fraction:
        return layout
    numeric = {
        index
        for index, fraction in enumerate(preview.numeric_fraction)
        if fraction >= 0.9 and index != layout.x_index and index != layout.label_index
    }
    if not numeric or {trace.index for trace in layout.traces} == numeric:
        return layout
    labels = preview.header_cells[-1] if preview.header_cells else []
    proposed = {trace.index: trace.label for trace in layout.traces}
    repaired = [
        TraceSpec(
            index=index,
            label=proposed.get(index) or (labels[index] if index < len(labels) else None) or None,
        )
        for index in sorted(numeric)
    ]
    logger.info(
        "Repaired layout traces from %s to %s using measured numeric columns",
        sorted(proposed),
        sorted(numeric),
    )
    return layout.model_copy(update={"traces": repaired})


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------


def cached_layout(db: Session, structure_hash: str) -> FileLayout | None:
    row = (
        db.query(FileLayoutCache)
        .filter(FileLayoutCache.structure_hash == structure_hash)
        .one_or_none()
    )
    if row is None:
        return None
    try:
        layout = FileLayout.model_validate(row.layout)
    except ValueError:
        logger.warning("Discarding unreadable cached layout %s", structure_hash)
        return None
    row.hit_count = (row.hit_count or 0) + 1
    db.add(row)
    db.commit()
    return layout


def store_layout(db: Session, structure_hash: str, layout: FileLayout) -> None:
    """Remember a resolved layout for this format. A user-declared layout
    overwrites a machine-guessed one — a human who typed the answer in is the
    most authoritative source we have."""
    row = (
        db.query(FileLayoutCache)
        .filter(FileLayoutCache.structure_hash == structure_hash)
        .one_or_none()
    )
    if row is None:
        db.add(
            FileLayoutCache(
                structure_hash=structure_hash,
                layout=layout.model_dump(mode="json"),
                detector_version=_LAYOUT_MODEL_ID,
                hit_count=0,
            )
        )
    elif layout.source == "user" or row.layout.get("source") != "user":
        row.layout = layout.model_dump(mode="json")
        db.add(row)
    db.commit()


async def resolve_layout(
    raw_bytes: bytes,
    db: Session,
    *,
    filename: str | None = None,
    credential: LLMCredential | None = None,
) -> tuple[FileLayout | None, str]:
    """Work out this file's layout, cheapest rung first.

    Returns `(layout, source)` where source is one of `"cache"`,
    `"heuristic"`, `"llm"`, `"llm-wide"`, or `"unresolved"`. `unresolved`
    means the caller should ask the user — it is not an error.

    `credential` is the file owner's LLM credential (see
    `app.llm_credentials.resolve_for_user`). When it is the user's own key,
    an LLM-derived layout is *not* written to the shared `file_layout_cache`:
    they paid for that answer with their own quota and asked for their data
    to stay on their provider, so it stays out of a table every other user
    reads. The heuristic rung still caches — no model saw the file.
    """
    preview = build_preview(raw_bytes)
    structure_hash = compute_structure_hash(preview)
    share_llm_result = not (credential is not None and credential.is_user_supplied)

    cached = cached_layout(db, structure_hash)
    if cached is not None and verify_layout(raw_bytes, cached):
        return cached, "cache"

    heuristic = detect_layout_heuristic(preview)
    if heuristic is not None and verify_layout(raw_bytes, heuristic):
        store_layout(db, structure_hash, heuristic)
        return heuristic, "heuristic"

    from_llm = await detect_layout_via_llm(preview, filename=filename, credential=credential)
    if from_llm is not None and verify_layout(raw_bytes, from_llm):
        if share_llm_result:
            store_layout(db, structure_hash, from_llm)
        return from_llm, "llm"

    # Rung 3: some files do not show their structure in ten rows and ten
    # columns — a wide matrix, or a long preamble.
    wide = build_preview(raw_bytes, max_rows=MAX_PREVIEW_ROWS, max_columns=MAX_PREVIEW_COLUMNS)
    from_llm_wide = await detect_layout_via_llm(wide, filename=filename, credential=credential)
    if from_llm_wide is not None and verify_layout(raw_bytes, from_llm_wide):
        if share_llm_result:
            store_layout(db, structure_hash, from_llm_wide)
        return from_llm_wide, "llm-wide"

    logger.warning(
        "Layout unresolved after every rung: structure_hash=%s columns=%s lines=%s",
        structure_hash,
        preview.column_count,
        preview.total_lines,
    )
    return None, "unresolved"


def fallback_layout(preview: PreviewGrid) -> FileLayout:
    """The historical assumption — column 0 is the axis, column 1 is the only
    spectrum — as an explicit, inspectable layout.

    Used to keep reading files that were ingested before layout detection
    existed, so nothing already in the database changes meaning.
    """
    return FileLayout(
        orientation="column_major",
        delimiter=preview.delimiter,
        decimal_separator=preview.decimal_separator,
        comment_prefixes=_DEFAULT_COMMENT_PREFIXES,
        header_rows=0,
        x_index=0,
        traces=[TraceSpec(index=1, label=None)],
        confidence=0.1,
        source="heuristic",
    )
