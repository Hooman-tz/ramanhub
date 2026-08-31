"""Import SCImago Journal Rank CSV(s) into the `journals` table.

The SCImago export is semicolon-delimited. Relevant columns:

    Issn                "03701573, 18734782"  (space/comma-separated 8-digit
                        codes, sometimes two — print + electronic)
    Title               journal name
    SJR                 score, comma decimal ("12,345" -> 12.345)
    SJR Best Quartile   Q1..Q4 (or "-" / blank)   [per-category exports use
                        the header "SJR Quartile" instead]
    H index             integer
    Country             publisher country

One `Journal` row is written per ISSN so a later lookup by *either* ISSN
resolves the same journal.

Default mode is an **upsert**: new ISSNs are inserted, existing
`source="scimago"` rows are updated in place. Nothing is deleted, so you can
safely run it more than once and feed several files (e.g. the full export
plus per-subject-category top-ups). Pass `--replace` to wipe every
`source="scimago"` row first (a clean full re-import).

    uv run python -m scripts.import_scimago scimagojr.csv
    uv run python -m scripts.import_scimago --replace full-export.csv
    uv run python -m scripts.import_scimago cat-a.csv cat-b.csv
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.journals import normalize_issn
from app.models.journal import Journal

_ISSN_SPLIT = re.compile(r"[,\s]+")
_VALID_QUARTILES = {"Q1", "Q2", "Q3", "Q4"}


def _parse_sjr(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.strip().replace(",", "."))
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value.strip())
    except ValueError:
        return None


def _issns_on_row(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for chunk in _ISSN_SPLIT.split(raw):
        norm = normalize_issn(chunk)
        if norm and norm not in out:
            out.append(norm)
    return out


def import_scimago(
    csv_paths: str | list[str], db: Session, *, replace: bool = False
) -> dict[str, int]:
    """Upsert the `journals` table from one or more SCImago CSVs. With
    `replace=True`, every `source="scimago"` row is dropped first. Returns
    `{"rows", "added", "updated", "issns"}`."""
    if isinstance(csv_paths, str):
        csv_paths = [csv_paths]

    if replace:
        db.query(Journal).filter(Journal.source == "scimago").delete(
            synchronize_session=False
        )
        db.flush()

    existing: dict[str, Journal] = {
        j.issn: j
        for j in db.query(Journal).filter(Journal.source == "scimago").all()
    }

    total_rows = 0
    added = 0
    updated = 0
    issn_entries = 0

    for csv_path in csv_paths:
        with open(csv_path, newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle, delimiter=";"))
        total_rows += len(rows)

        for row in rows:
            issns = _issns_on_row(row.get("Issn"))
            if not issns:
                continue
            title = (row.get("Title") or "").strip()
            sjr = _parse_sjr(row.get("SJR"))
            quartile = (
                row.get("SJR Best Quartile") or row.get("SJR Quartile") or ""
            ).strip().upper()
            quartile = quartile if quartile in _VALID_QUARTILES else None
            h_index = _parse_int(row.get("H index"))
            country = (row.get("Country") or "").strip() or None
            issn_l = issns[0]

            for issn in issns:
                issn_entries += 1
                current = existing.get(issn)
                if current is None:
                    current = Journal(issn=issn, source="scimago")
                    db.add(current)
                    existing[issn] = current
                    added += 1
                else:
                    updated += 1
                current.issn_l = issn_l
                current.title = title
                current.sjr = sjr
                current.quartile = quartile
                current.h_index = h_index
                current.country = country

    db.commit()
    counts = {
        "rows": total_rows,
        "added": added,
        "updated": updated,
        "issns": issn_entries,
    }
    print(
        f"SCImago import: {counts['rows']} CSV rows -> "
        f"{counts['added']} new + {counts['updated']} updated ISSN rows"
    )
    return counts


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    replace = "--replace" in argv
    paths_in = [a for a in argv if a != "--replace"]
    if not paths_in:
        print(
            "usage: uv run python -m scripts.import_scimago [--replace] "
            "<scimagojr.csv> [more.csv ...]",
            file=sys.stderr,
        )
        return 2

    resolved: list[str] = []
    for raw in paths_in:
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.is_file():
            print(f"file not found: {path}", file=sys.stderr)
            return 1
        resolved.append(str(path))

    db = SessionLocal()
    try:
        import_scimago(resolved, db, replace=replace)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
