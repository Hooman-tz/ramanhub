"""Export format tests.

The bar for a data format is a ROUND TRIP: parse what was written and get
the original numbers back. "It produced some text" is not a passing grade
for a repository whose whole promise is that other people can use the data.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from app.export import jcampdx, tabular
from app.export.citation import CitationSubject, render, to_bibtex, to_ris, to_text

X = np.array([100.0, 200.5, 300.25, 400.125])
Y = np.array([1.5, -2.25, 3.125, 0.0])


# ------------------------------------------------------------------ tabular


def _parse_delimited(text: str, delimiter: str):
    rows = [
        line for line in text.splitlines() if line and not line.startswith("#")
    ]
    assert rows[0].split(delimiter) == ["wavenumber_cm-1", "intensity"]
    x, y = [], []
    for line in rows[1:]:
        a, b = line.split(delimiter)
        x.append(float(a))
        y.append(float(b))
    return np.array(x), np.array(y)


@pytest.mark.parametrize(("fmt", "delimiter"), [("csv", ","), ("tsv", "\t")])
def test_delimited_round_trips_exactly(fmt, delimiter):
    text = "".join(tabular.to_delimited(X, Y, fmt=fmt))
    x, y = _parse_delimited(text, delimiter)

    # Exact equality, not approx: repr-grade formatting must not quantize.
    assert np.array_equal(x, X)
    assert np.array_equal(y, Y)


def test_delimited_preserves_full_float_precision():
    """A fixed %.6f would silently truncate this; SNV output lives at this
    scale, so the loss would be real."""
    precise = np.array([1234.5678901234567])
    text = "".join(tabular.to_delimited(precise, precise, fmt="csv"))
    _x, y = _parse_delimited(text, ",")

    assert y[0] == precise[0]


def test_header_comment_carries_provenance():
    text = "".join(
        tabular.to_delimited(X, Y, metadata={"accession": "RH-S-000001", "license": "CC-BY-4.0"})
    )
    assert "# accession: RH-S-000001" in text
    assert "# license: CC-BY-4.0" in text


def test_header_comment_can_be_suppressed():
    text = "".join(
        tabular.to_delimited(
            X, Y, metadata={"accession": "RH-S-000001"}, include_header_comment=False
        )
    )
    assert not text.startswith("#")


def test_header_comment_omits_empty_values():
    lines = tabular.build_header_comment({"a": "x", "b": None, "c": ""})
    assert lines == ["# a: x"]


def test_unsupported_tabular_format_is_rejected():
    with pytest.raises(ValueError, match="Unsupported tabular format"):
        list(tabular.to_delimited(X, Y, fmt="xlsx"))


def test_json_round_trips():
    payload = json.loads(tabular.to_json(X, Y, {"accession": "RH-S-000001"}))

    assert payload["wavenumbers"] == list(X)
    assert payload["intensities"] == list(Y)
    assert payload["n_points"] == 4
    assert payload["metadata"]["accession"] == "RH-S-000001"


# ----------------------------------------------------------------- JCAMP-DX


def _parse_jcamp(text: str):
    """Minimal JCAMP-DX reader — enough to prove what we wrote is
    parseable by the labels a real reader keys on."""
    labels, x, y = {}, [], []
    in_data = False
    for line in text.splitlines():
        if line.startswith("##XYDATA"):
            in_data = True
            continue
        if line.startswith("##END"):
            break
        if line.startswith("##"):
            key, _, value = line[2:].partition("=")
            labels[key.strip()] = value.strip()
            continue
        if in_data and line.strip():
            a, b = line.split(",")
            x.append(float(a))
            y.append(float(b))
    return labels, np.array(x), np.array(y)


def test_jcamp_round_trips_the_arrays():
    text = "".join(jcampdx.to_jcampdx(X, Y, title="Test"))
    _labels, x, y = _parse_jcamp(text)

    assert np.array_equal(x, X)
    assert np.array_equal(y, Y)


def test_jcamp_declares_the_required_labels():
    """A reader that can't find these treats the file as malformed."""
    text = "".join(jcampdx.to_jcampdx(X, Y, title="Test"))
    labels, _x, _y = _parse_jcamp(text)

    assert labels["TITLE"] == "Test"
    assert labels["JCAMP-DX"] == jcampdx.JCAMP_VERSION
    assert labels["DATA TYPE"] == "RAMAN SPECTRUM"
    assert labels["XUNITS"] == "1/CM"
    assert int(labels["NPOINTS"]) == len(X)


def test_jcamp_npoints_matches_the_data_block():
    """A mismatch here is the single most common way a JCAMP file breaks a
    reader."""
    text = "".join(jcampdx.to_jcampdx(X, Y))
    labels, x, _y = _parse_jcamp(text)

    assert int(labels["NPOINTS"]) == len(x)


def test_jcamp_first_and_last_x_match_the_data():
    text = "".join(jcampdx.to_jcampdx(X, Y))
    labels, x, _y = _parse_jcamp(text)

    assert float(labels["FIRSTX"]) == x[0]
    assert float(labels["LASTX"]) == x[-1]


def test_jcamp_puts_ramanhub_fields_in_the_user_namespace():
    """RamanHub-specific provenance must not masquerade as standard JCAMP
    labels — that's what the $ prefix is reserved for."""
    text = "".join(
        jcampdx.to_jcampdx(X, Y, metadata={"accession": "RH-S-000001", "doi": "10.1/x"})
    )
    assert "##$ACCESSION=RH-S-000001" in text
    assert "##$DOI=10.1/x" in text


def test_jcamp_sanitizes_values_that_would_corrupt_the_format():
    """'=' terminates a JCAMP label, so it can't survive inside a value."""
    text = "".join(jcampdx.to_jcampdx(X, Y, title="Bad=Title\nInjected"))
    labels, _x, _y = _parse_jcamp(text)

    assert "=" not in labels["TITLE"]
    assert "\n" not in labels["TITLE"]
    assert "INJECTED" not in labels


def test_jcamp_rejects_mismatched_arrays():
    with pytest.raises(ValueError, match="match in length"):
        list(jcampdx.to_jcampdx(X, Y[:2]))


def test_jcamp_handles_an_empty_spectrum():
    text = "".join(jcampdx.to_jcampdx(np.array([]), np.array([])))
    labels, x, _y = _parse_jcamp(text)

    assert int(labels["NPOINTS"]) == 0
    assert x.size == 0


# ----------------------------------------------------------------- citation


def _subject(**overrides) -> CitationSubject:
    base = {
        "accession": "RH-S-000042",
        "title": "Alpha cellulose at 785 nm",
        "authors": ["Ada Lovelace"],
        "year": 2026,
        "url": "https://serds.ca/s/RH-S-000042",
        "license_name": "CC BY 4.0",
        "orcids": ["0000-0002-1825-0097"],
    }
    base.update(overrides)
    return CitationSubject(**base)


def test_bibtex_has_the_expected_shape():
    out = to_bibtex(_subject())

    assert out.startswith("@misc{")
    assert "title = {Alpha cellulose at 785 nm}" in out
    assert "author = {Ada Lovelace}" in out
    assert "year = {2026}" in out
    assert "publisher = {RamanHub}" in out
    assert out.rstrip().endswith("}")


def test_bibtex_key_includes_the_accession():
    """Two datasets by the same author in the same year must not collide —
    the classic BibTeX key failure."""
    a = to_bibtex(_subject(accession="RH-S-000001"))
    b = to_bibtex(_subject(accession="RH-S-000002"))

    assert a.split(",")[0] != b.split(",")[0]


def test_bibtex_escapes_characters_that_would_break_the_field():
    out = to_bibtex(_subject(title="50% signal & {braces} $math$ _under_"))

    assert r"\%" in out and r"\&" in out and r"\{" in out and r"\$" in out
    # Balanced braces: an unescaped one would terminate the field early.
    assert out.count("{") == out.count("}")


def test_bibtex_joins_multiple_authors_with_and():
    out = to_bibtex(_subject(authors=["Ada Lovelace", "Grace Hopper"]))
    assert "author = {Ada Lovelace and Grace Hopper}" in out


def test_bibtex_includes_doi_when_present():
    assert "doi = {10.1021/example}" in to_bibtex(_subject(doi="10.1021/example"))


def test_ris_has_the_expected_shape():
    out = to_ris(_subject())

    assert out.startswith("TY  - DATA")
    assert "AU  - Ada Lovelace" in out
    assert "AN  - RH-S-000042" in out
    assert out.rstrip().endswith("ER  -")


def test_ris_uses_crlf_line_endings():
    """Older EndNote fails to parse LF-only RIS."""
    assert "\r\n" in to_ris(_subject())


def test_ris_includes_every_author_and_orcid():
    out = to_ris(_subject(authors=["A B", "C D"], orcids=["0000-0002-1825-0097"]))

    assert out.count("AU  - ") == 2
    assert "C2  - ORCID: 0000-0002-1825-0097" in out


def test_text_citation_is_one_readable_line():
    out = to_text(_subject())

    assert "\n" not in out
    assert "Ada Lovelace (2026)" in out
    assert "RH-S-000042" in out
    assert "CC BY 4.0" in out


def test_text_citation_prefers_doi_over_url():
    out = to_text(_subject(doi="10.1021/example"))

    assert "https://doi.org/10.1021/example" in out
    assert "serds.ca" not in out


def test_text_citation_abbreviates_long_author_lists():
    out = to_text(_subject(authors=["A B", "C D", "E F", "G H"]))
    assert "et al." in out


def test_citation_survives_missing_metadata():
    """A draft with no title, no authors and no DOI must still produce
    something citable rather than crashing."""
    bare = CitationSubject(accession=None, title=None)

    for fmt in ("bibtex", "ris", "text"):
        assert render(bare, fmt).strip()


def test_unsupported_citation_format_is_rejected():
    with pytest.raises(ValueError, match="Unsupported citation format"):
        render(_subject(), "endnote")
