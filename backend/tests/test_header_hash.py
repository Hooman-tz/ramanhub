from __future__ import annotations

from app.ingestion.header_hash import compute_header_hash, normalize_header


def test_same_template_different_run_hashes_identically():
    header_a = "Date: Thu Jan 01 00:00:00 GMT 2026\nIntegration Time (usec): 100000"
    header_b = "Date: Fri Feb 02 08:30:15 GMT 2026\nIntegration Time (usec): 100000"
    assert compute_header_hash(header_a) == compute_header_hash(header_b)


def test_different_template_hashes_differently():
    header_a = "Integration Time (usec): 100000\nSpectrometers: USB2000"
    header_b = "Integration Time (usec): 100000\nSpectrometers: USB4000"
    assert compute_header_hash(header_a) != compute_header_hash(header_b)


def test_whitespace_differences_are_normalized():
    header_a = "Spectrometers: USB2000\nAccumulations: 3"
    header_b = "Spectrometers:   USB2000  \n\n  Accumulations:    3   "
    assert compute_header_hash(header_a) == compute_header_hash(header_b)


def test_date_and_time_substrings_are_blanked_out():
    normalized = normalize_header("Date: 2026-01-31 12:00:00, Value: 42")
    assert "2026-01-31" not in normalized
    assert "12:00:00" not in normalized
    assert "<DATE>" in normalized


def test_hash_is_deterministic_sha256_hex():
    digest = compute_header_hash("Spectrometers: USB2000")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)
