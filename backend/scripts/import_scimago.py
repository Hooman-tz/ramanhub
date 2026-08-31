"""Import the SCImago Journal Rank CSV into the `journals` table.

The SCImago export is semicolon-delimited. Relevant columns:

    Issn                "03701573, 18734782"  (space/comma-separated 8-digit
                        codes, sometimes two — print + electronic)
    Title               journal name
    SJR                 score, comma decimal ("12,345" -> 12.345)
    SJR Best Quartile   Q1..Q4 (or "-" / blank)
    H index             integer
    Country             publisher country

One `Journal` row is written per ISSN so a later lookup by *either* ISSN
resolves the same journal. The import is idempotent: every existing
`source="scimago"` row is deleted first, then the file is re-inserted.

    uv run python -m scripts.import_scimago path/to/scimagojr.csv
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


def import_scimago(csv_path: str, db: Session) -> dict[str, int]:
    """Replace all `source="scimago"` rows with the contents of `csv_path`.
    Returns counts: `{"rows", "journals", "issns"}`."""
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        rows = list(reader)

    db.query(Journal).filter(Journal.source == "scimago").delete(synchronize_session=False)
    db.flush()

    seen: set[str] = set()
    journals = 0
    issn_entries = 0
    for row in rows:
        issns = _issns_on_row(row.get("Issn"))
        if not issns:
            continue
        title = (row.get("Title") or "").strip()
        sjr = _parse_sjr(row.get("SJR"))
        quartile = (row.get("SJR Best Quartile") or "").strip().upper()
        quartile = quartile if quartile in _VALID_QUARTILES else None
        h_index = _parse_int(row.get("H index"))
        country = (row.get("Country") or "").strip() or None
        issn_l = issns[0]

        added_any = False
        for issn in issns:
            if issn in seen:
                continue
            seen.add(issn)
            db.add(
                Journal(
                    issn=issn,
                    issn_l=issn_l,
                    title=title,
                    sjr=sjr,
                    quartile=quartile,
                    h_index=h_index,
                    country=country,
                    source="scimago",
                )
            )
            issn_entries += 1
            added_any = True
        if added_any:
            journals += 1

    db.commit()
    counts = {"rows": len(rows), "journals": journals, "issns": issn_entries}
    print(
        f"SCImago import: {counts['rows']} CSV rows -> "
        f"{counts['journals']} journals, {counts['issns']} ISSN entries"
    )
    return counts


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(
            "usage: uv run python -m scripts.import_scimago <scimagojr.csv>",
            file=sys.stderr,
        )
        return 2

    path = Path(argv[0]).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        print(f"file not found: {path}", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        import_scimago(str(path), db)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
