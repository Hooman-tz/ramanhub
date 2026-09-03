"""Tests for `app.ingestion.filename_overlay` — the deterministic, regex-based
overlay that fills ONLY the metadata fields a parser / the LLM left null.

Guarantees exercised:
* it never overwrites a value that came from the file itself
* the nm range guard: a laser wavelength must be 200-1100 nm, so a Raman-shift
  range endpoint / grating value in the filename is NOT written
* the documented patterns: `(\\d{3,4})nm`, `x(\\d+)`, material words
"""
from __future__ import annotations

import pytest

from app.ingestion.filename_overlay import apply
from app.schemas.ingestion import ExtractedMetadata


def _empty() -> ExtractedMetadata:
    return ExtractedMetadata(modality="raman")


def test_fills_wavelength_objective_and_material_from_filename():
    out = apply(_empty(), "polystyrene_532nm_10s_x50.txt")
    assert out.laser_wavelength_nm == 532.0
    assert out.objective_magnification == 50.0
    assert out.integration_time_ms == 10_000.0
    assert out.sample_description == "polystyrene"


def test_objective_trailing_x_form():
    assert apply(_empty(), "sample_100x_785nm.txt").objective_magnification == 100.0


def test_does_not_overwrite_file_derived_values():
    from_file = ExtractedMetadata(
        modality="raman",
        laser_wavelength_nm=633.0,
        objective_magnification=20.0,
        sample_description="calcite (from header)",
        integration_time_ms=500.0,
    )
    out = apply(from_file, "silicon_532nm_x50_2s.txt")
    # Every field already set by the file is preserved verbatim.
    assert out.laser_wavelength_nm == 633.0
    assert out.objective_magnification == 20.0
    assert out.sample_description == "calcite (from header)"
    assert out.integration_time_ms == 500.0


def test_partial_fill_only_touches_null_fields():
    partial = ExtractedMetadata(modality="raman", laser_wavelength_nm=785.0)
    out = apply(partial, "graphene_532nm_x100.txt")
    assert out.laser_wavelength_nm == 785.0  # kept
    assert out.objective_magnification == 100.0  # filled
    assert out.sample_description == "graphene"  # filled


@pytest.mark.parametrize(
    "filename",
    [
        "quartz_3200_x50.txt",  # 3200 = Raman-shift endpoint, not a laser
        "sample_1800nm_grating.txt",  # 1800 nm is outside 200-1100
        "scan_150nm_uv.txt",  # 150 nm below the floor
        "blank_1_x10.txt",  # bare "1" is not a wavelength
    ],
)
def test_nm_range_guard_rejects_implausible_wavelengths(filename):
    out = apply(_empty(), filename)
    assert out.laser_wavelength_nm is None


def test_nm_range_guard_accepts_edge_values():
    assert apply(_empty(), "x_1064nm.txt").laser_wavelength_nm == 1064.0
    assert apply(_empty(), "x_244nm.txt").laser_wavelength_nm == 244.0


def test_no_filename_is_a_noop():
    empty = _empty()
    assert apply(empty, None) is empty
    assert apply(empty, "") is empty


def test_unrecognised_filename_returns_input_unchanged():
    empty = _empty()
    assert apply(empty, "IMG_4021.txt") is empty


def test_wavenumber_range_token_not_mistaken_for_objective_or_time():
    # "100-3200" splits into "100" and "3200"; neither is nm-suffixed, and
    # "3200" must not become an objective or an integration time.
    out = apply(_empty(), "mystery_100-3200cm-1.txt")
    assert out.laser_wavelength_nm is None
    assert out.objective_magnification is None
    assert out.integration_time_ms is None


def test_laser_power_and_accumulations_tokens():
    out = apply(_empty(), "aspirin_785nm_20mW_16accum.txt")
    assert out.laser_power_mw == 20.0
    assert out.accumulations == 16
    assert out.sample_description == "aspirin"
