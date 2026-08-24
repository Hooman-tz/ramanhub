"""ZIP bundle export: everything a Finding contains, in one download.

The point is that a bundle is *self-contained and reproducible*. Someone who
downloads it should be able to redo the analysis without visiting the site
again, and should be able to cite it without hunting for the accession. So a
bundle carries, per member spectrum, both the raw and the processed arrays,
plus the processing ledger that turns one into the other — not just a folder
of numbers.

Layout:

    RH-F-000042/
      README.txt          what this is, who made it, how to cite it
      CITATION.bib        BibTeX for the finding
      manifest.json       machine-readable index: members, ledgers, checksums
      spectra/
        RH-S-000001_raw.csv
        RH-S-000001_processed.csv
        RH-S-000001_ledger.json
      ...

Written with `zipfile` into an in-memory buffer rather than streamed
incrementally. A Raman spectrum is tens of kilobytes and a finding holds at
most a couple of hundred, so the whole bundle is single-digit megabytes —
well inside what a request can hold, and streaming a ZIP correctly (which
needs either a seekable target or ZIP64 streaming) is real complexity to buy
nothing at this size. `MAX_BUNDLE_SPECTRA` keeps that assumption true.
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime

import numpy as np

from app.export import citation as citation_mod
from app.export import tabular

MAX_BUNDLE_SPECTRA = 200


def _readme(finding_title: str, accession: str, citation_text: str, n: int) -> str:
    return (
        f"{finding_title}\n"
        f"{'=' * len(finding_title)}\n\n"
        f"RamanHub finding {accession}\n"
        f"Exported {datetime.now(UTC).isoformat(timespec='seconds')}\n\n"
        f"This bundle contains {n} spectr{'um' if n == 1 else 'a'}.\n\n"
        "For each one you get three files:\n"
        "  *_raw.csv        the original measurement, exactly as uploaded\n"
        "  *_processed.csv  the same data with the processing pipeline applied\n"
        "  *_ledger.json    the pipeline itself: every step, its version and\n"
        "                   its parameters, in the order applied\n\n"
        "The ledger is what makes this reproducible: raw + ledger regenerates\n"
        "processed exactly, so you can verify the processing rather than\n"
        "trusting it. manifest.json lists the same information in a\n"
        "machine-readable form, with a SHA-256 of every file.\n\n"
        "HOW TO CITE\n"
        "-----------\n"
        f"{citation_text}\n\n"
        "CITATION.bib holds the same citation in BibTeX form.\n"
    )


def build_bundle(
    *,
    accession: str,
    title: str,
    subject: citation_mod.CitationSubject,
    members: list[dict],
    license_name: str | None = None,
) -> bytes:
    """Build the ZIP.

    `members` is a list of dicts, each carrying:
        accession, title, label,
        raw (wavenumbers, intensities), processed (wavenumbers, intensities),
        ledger (list of step dicts, possibly empty), metadata (dict)
    """
    citation_text = citation_mod.to_text(subject)
    buffer = io.BytesIO()
    manifest: dict = {
        "finding": {
            "accession": accession,
            "title": title,
            "doi": subject.doi,
            "license": license_name,
            "url": subject.url,
            "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "citation": citation_text,
        "spectra": [],
    }

    root = accession or "ramanhub-finding"

    # ZIP_DEFLATED: spectra are highly repetitive ASCII numbers and compress
    # by roughly an order of magnitude, which matters on a platform whose
    # hosting case rests on download traffic.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:

        def write(path: str, data: str | bytes) -> str:
            payload = data.encode() if isinstance(data, str) else data
            archive.writestr(f"{root}/{path}", payload)
            return hashlib.sha256(payload).hexdigest()

        for member in members:
            stem = member["accession"] or str(member.get("id", "spectrum"))
            entry: dict = {
                "accession": member["accession"],
                "title": member.get("title"),
                "label": member.get("label"),
                "files": {},
                "ledger_steps": len(member.get("ledger") or []),
            }

            for stage in ("raw", "processed"):
                arrays = member.get(stage)
                if arrays is None:
                    continue
                wavenumbers, intensities = arrays
                if np.asarray(wavenumbers).size == 0:
                    continue
                text = "".join(
                    tabular.to_delimited(
                        wavenumbers,
                        intensities,
                        fmt="csv",
                        metadata={**member.get("metadata", {}), "stage": stage},
                    )
                )
                path = f"spectra/{stem}_{stage}.csv"
                entry["files"][stage] = {
                    "path": path,
                    "sha256": write(path, text),
                    "n_points": int(np.asarray(wavenumbers).size),
                }

            ledger_path = f"spectra/{stem}_ledger.json"
            entry["files"]["ledger"] = {
                "path": ledger_path,
                "sha256": write(
                    ledger_path,
                    json.dumps(
                        {
                            "spectrum": member["accession"],
                            "steps": member.get("ledger") or [],
                        },
                        indent=2,
                    ),
                ),
            }
            manifest["spectra"].append(entry)

        write("CITATION.bib", citation_mod.to_bibtex(subject))
        write("README.txt", _readme(title, accession, citation_text, len(members)))
        # Manifest last: it records checksums of everything written before it,
        # so it can't checksum itself.
        archive.writestr(f"{root}/manifest.json", json.dumps(manifest, indent=2))

    return buffer.getvalue()
