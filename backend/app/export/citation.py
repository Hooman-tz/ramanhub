"""Citation export: BibTeX, RIS, and plain text.

This is the incentive layer. Scientists share data when sharing earns
credit, and credit runs on citations — so "cite this dataset" is not a
convenience feature, it is the reason a contributor uploads at all. It's
also why the accession, ORCID and DOI work exists: this module is where all
three finally pay off.

Type choices follow the DataCite/Zenodo convention for research data:
`@misc` in BibTeX (there is no `@dataset` in standard BibTeX styles — natbib
and friends silently drop unknown entry types, and a citation that vanishes
at typeset time is worse than a slightly generic one), and `TY  - DATA` in
RIS, which does have a data type.

When a spectrum links a published paper, the paper's DOI is cited as the
primary reference and the dataset accession rides along in `note`. Citing
the peer-reviewed article is what the author actually wants credit for, and
it's what the DOI-verified trust tier means.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

# BibTeX keys must be ASCII-safe and free of the characters that terminate a
# field or a key. Anything outside this set gets dropped.
_KEY_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")

RAMANHUB_PUBLISHER = "RamanHub"


@dataclass
class CitationSubject:
    """Everything a citation needs, decoupled from the ORM.

    Taking a plain dataclass rather than a `Spectrum` row keeps this module
    testable without a database and lets a Finding, a collection, or a future
    record type reuse it unchanged.
    """

    accession: str | None
    title: str | None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    url: str | None = None
    license_name: str | None = None
    orcids: list[str] = field(default_factory=list)
    kind: str = "dataset"
    version: str | None = None


def _bibtex_key(subject: CitationSubject) -> str:
    """A stable, collision-resistant citation key.

    Built from the first author's surname plus the accession, because the
    accession is globally unique — so two datasets by the same author in the
    same year can't collide, which is the classic BibTeX key failure.
    """
    surname = ""
    if subject.authors:
        surname = subject.authors[0].split()[-1] if subject.authors[0].split() else ""
    parts = [p for p in (surname, subject.accession or "", str(subject.year or "")) if p]
    key = "".join(parts) or "ramanhub"
    return "".join(ch for ch in key if ch in _KEY_SAFE) or "ramanhub"


def _escape_bibtex(value: str) -> str:
    """Escape the characters that would break out of a BibTeX field."""
    out = value.replace("\\", "\\textbackslash{}")
    for ch in ("{", "}", "$", "&", "%", "#", "_", "~", "^"):
        out = out.replace(ch, f"\\{ch}")
    return out.replace("\n", " ").strip()


def _author_list(subject: CitationSubject) -> list[str]:
    return subject.authors or ["RamanHub contributor"]


def to_bibtex(subject: CitationSubject) -> str:
    authors = " and ".join(_escape_bibtex(a) for a in _author_list(subject))
    fields: list[tuple[str, str]] = [
        ("title", _escape_bibtex(subject.title or subject.accession or "Untitled spectrum")),
        ("author", authors),
        ("year", str(subject.year or datetime.now(UTC).year)),
        ("publisher", RAMANHUB_PUBLISHER),
        # howpublished is what most styles actually render for @misc, so the
        # dataset nature shows up in the typeset output rather than only in
        # the .bib source.
        ("howpublished", f"RamanHub {subject.kind}"),
    ]
    if subject.doi:
        fields.append(("doi", _escape_bibtex(subject.doi)))
    if subject.url:
        fields.append(("url", subject.url))
    if subject.version:
        fields.append(("version", _escape_bibtex(subject.version)))

    note_bits = [b for b in (subject.accession, subject.license_name) if b]
    if note_bits:
        fields.append(("note", _escape_bibtex(" · ".join(note_bits))))

    body = ",\n".join(f"  {name} = {{{value}}}" for name, value in fields)
    return f"@misc{{{_bibtex_key(subject)},\n{body}\n}}\n"


def to_ris(subject: CitationSubject) -> str:
    lines = ["TY  - DATA"]
    for author in _author_list(subject):
        lines.append(f"AU  - {author}")
    lines.append(f"TI  - {subject.title or subject.accession or 'Untitled spectrum'}")
    lines.append(f"PY  - {subject.year or datetime.now(UTC).year}")
    lines.append(f"PB  - {RAMANHUB_PUBLISHER}")
    if subject.doi:
        lines.append(f"DO  - {subject.doi}")
    if subject.url:
        lines.append(f"UR  - {subject.url}")
    if subject.accession:
        lines.append(f"AN  - {subject.accession}")
    if subject.license_name:
        lines.append(f"C1  - License: {subject.license_name}")
    for orcid in subject.orcids:
        lines.append(f"C2  - ORCID: {orcid}")
    lines.append("ER  - ")
    # RIS is specified with CRLF line endings; some reference managers
    # (older EndNote in particular) fail to parse LF-only files.
    return "\r\n".join(lines) + "\r\n"


def to_text(subject: CitationSubject) -> str:
    """A one-line citation to paste into an email or a figure caption."""
    authors = _author_list(subject)
    if len(authors) > 3:
        author_str = f"{authors[0]} et al."
    else:
        author_str = ", ".join(authors)

    parts = [
        f"{author_str} ({subject.year or datetime.now(UTC).year}).",
        f"{subject.title or subject.accession or 'Untitled spectrum'}.",
        f"{RAMANHUB_PUBLISHER}.",
    ]
    if subject.accession:
        parts.append(f"{subject.accession}.")
    if subject.doi:
        parts.append(f"https://doi.org/{subject.doi}")
    elif subject.url:
        parts.append(subject.url)
    if subject.license_name:
        parts.append(f"Licensed under {subject.license_name}.")
    return " ".join(parts)


FORMATTERS = {"bibtex": to_bibtex, "ris": to_ris, "text": to_text}

MEDIA_TYPES = {
    "bibtex": "application/x-bibtex",
    "ris": "application/x-research-info-systems",
    "text": "text/plain",
}

FILE_EXTENSIONS = {"bibtex": "bib", "ris": "ris", "text": "txt"}


def render(subject: CitationSubject, fmt: str) -> str:
    try:
        return FORMATTERS[fmt](subject)
    except KeyError as exc:
        raise ValueError(f"Unsupported citation format: {fmt!r}") from exc
