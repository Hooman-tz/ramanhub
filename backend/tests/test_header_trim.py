"""Tests for `app.ingestion.jobs._extract_header_text`.

This function decides two things at once: what the LLM is shown, and what the
vendor-parse cache is keyed on. Both used to be "the first 64 kB of the file",
which for a text spectrum means the whole thing — so these tests pin the
trimming behaviour against the real vendor files in `sample-data/`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.ingestion.header_hash import compute_header_hash
from app.ingestion.jobs import _extract_header_text, _looks_like_data_row

SAMPLE_DIR = Path(__file__).resolve().parent.parent.parent / "sample-data"
HORIBA = SAMPLE_DIR / "horiba_acetaminophen_785nm.txt"
CELLULOSE = SAMPLE_DIR / "horiba_alpha_cellulose_785nm.txt"


def _header_of(path: Path) -> str:
    return _extract_header_text(path.read_bytes())


@pytest.mark.skipif(not HORIBA.exists(), reason="sample-data not present")
def test_recovers_the_whole_horiba_header_and_none_of_the_data():
    header = _header_of(HORIBA)

    # Every metadata field a parser would want must survive intact.
    for expected in (
        "#Acquired:",
        "#Title:\tAcetaminophen powder",
        "#Acq. time (s):\t15",
        "#Accumulations:\t3",
        "#Range (cm-1):\t200 - 3198",
        "#Grating:\t1800",
        "#Objective:\tx50",
        "#Laser:\t785",
        "#Spectro:\tiHR320",
    ):
        assert expected in header

    assert len(header.splitlines()) == 9
    # The first data row must NOT be there.
    assert "200.00" not in header


@pytest.mark.skipif(not HORIBA.exists(), reason="sample-data not present")
def test_trims_away_the_overwhelming_majority_of_the_file():
    """The point of the change. The header is a rounding error inside the
    file, and sending the rest costs ~100x the tokens for no information."""
    raw = HORIBA.read_bytes()
    header = _extract_header_text(raw)

    assert len(raw) > 20_000
    assert len(header) < 300
    assert len(header) < len(raw) / 50


@pytest.mark.skipif(not HORIBA.exists(), reason="sample-data not present")
def test_two_spectra_from_one_instrument_no_longer_hash_by_their_data():
    """Before trimming, `compute_header_hash` ran over the intensity values,
    so no two spectra ever shared a VendorParseCache entry and every upload
    paid for a model call. The hashes here still differ (the #Title: line
    differs, which is correct) — what matters is that they are now decided by
    nine header lines rather than by fifteen hundred rows of numbers."""
    a, b = _header_of(HORIBA), _header_of(CELLULOSE)

    assert len(a.splitlines()) == len(b.splitlines()) == 9
    assert compute_header_hash(a) != compute_header_hash(b)

    # Identical headers hash identically — which is what lets a re-upload of
    # the same acquisition template hit the cache.
    assert compute_header_hash(a) == compute_header_hash(_header_of(HORIBA))


@pytest.mark.skipif(not HORIBA.exists(), reason="sample-data not present")
def test_hash_is_stable_when_only_the_spectrum_data_changes():
    """The concrete cache win: same header, different measurements -> same
    key. This is the case that was broken."""
    raw = HORIBA.read_bytes()
    lines = raw.decode().splitlines()
    header, data = lines[:9], lines[9:]

    perturbed = "\n".join(header + [row.replace(".0", ".7") for row in data]).encode()

    assert compute_header_hash(_extract_header_text(raw)) == compute_header_hash(
        _extract_header_text(perturbed)
    )


def test_a_bare_numeric_line_inside_a_header_is_not_a_cutoff():
    """Some vendors put a lone value on its own line. Cutting at the first
    numeric-looking line would silently truncate the header there, which is
    why the rule requires several consecutive data rows."""
    raw = b"#Grating\n1800\n#Laser\n785\n#Spectro\niHR320\n10 1\n11 2\n12 3\n13 4\n"
    header = _extract_header_text(raw)

    assert "1800" in header
    assert "iHR320" in header
    assert "10 1" not in header


def test_headerless_file_yields_an_empty_header():
    """Deliberate: there is no metadata to extract, and a stable empty hash
    lets every such file share one cache entry rather than each paying for a
    model call to be told there is nothing there."""
    assert _extract_header_text(b"200,1.0\n201,1.1\n202,1.2\n203,1.3\n") == ""


def test_undecodable_binary_is_bounded_by_the_char_cap():
    """A binary header decoded with errors='ignore' can be one enormous line
    with no recognizable data rows. The cap is what stops that becoming the
    prompt."""
    header = _extract_header_text(bytes(range(256)) * 100)

    assert len(header) <= settings.LLM_HEADER_MAX_CHARS


def test_char_cap_is_enforced_even_for_a_long_text_header():
    raw = ("\n".join(f"#Field{i}: value{i}" for i in range(5000))).encode()
    assert len(_extract_header_text(raw)) <= settings.LLM_HEADER_MAX_CHARS


@pytest.mark.parametrize(
    "line",
    ["200.00\t161.082", "  200,1.0", "1.5e3 2.5E-2", "-200.0;  -1.0", "42", "1 2 3 4 5"],
)
def test_data_rows_are_recognized(line):
    assert _looks_like_data_row(line)


@pytest.mark.parametrize(
    "line",
    ["#Laser:\t785", "Laser 785", "", "   ", "#Range (cm-1):\t200 - 3198", "200.00 abc"],
)
def test_non_data_rows_are_not(line):
    assert not _looks_like_data_row(line)
