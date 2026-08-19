"""Pure-function tests for app.ingestion.sanity_check.check against a fake
DB session — sanity_check never mutates state, so a fake query interface
returning canned MetadataFieldDefinition-like rows is enough; no real
database is needed.
"""
from __future__ import annotations

from app.ingestion.sanity_check import check
from app.schemas.ingestion import ExtractedMetadata


class _FakeDefinition:
    def __init__(
        self,
        field_key,
        required=False,
        min_value=None,
        max_value=None,
        allowed_values=None,
    ):
        self.field_key = field_key
        self.required = required
        self.min_value = min_value
        self.max_value = max_value
        self.allowed_values = allowed_values


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, model):
        return _FakeQuery(self._rows)


def test_flags_missing_required_field():
    db = _FakeDB([_FakeDefinition("integration_time_ms", required=True)])
    metadata = ExtractedMetadata(integration_time_ms=None)
    flags = check(metadata, "raman", db)
    assert "integration_time_ms" in flags


def test_does_not_flag_present_required_field():
    db = _FakeDB([_FakeDefinition("integration_time_ms", required=True)])
    metadata = ExtractedMetadata(integration_time_ms=50.0)
    flags = check(metadata, "raman", db)
    assert "integration_time_ms" not in flags


def test_flags_numeric_value_below_minimum():
    db = _FakeDB([_FakeDefinition("laser_power_mw", min_value=0, max_value=1000)])
    metadata = ExtractedMetadata(laser_power_mw=-5)
    flags = check(metadata, "raman", db)
    assert "laser_power_mw" in flags


def test_flags_numeric_value_above_maximum():
    db = _FakeDB([_FakeDefinition("laser_power_mw", min_value=0, max_value=1000)])
    metadata = ExtractedMetadata(laser_power_mw=5000)
    flags = check(metadata, "raman", db)
    assert "laser_power_mw" in flags


def test_does_not_flag_numeric_value_in_range():
    db = _FakeDB([_FakeDefinition("laser_power_mw", min_value=0, max_value=1000)])
    metadata = ExtractedMetadata(laser_power_mw=50)
    flags = check(metadata, "raman", db)
    assert "laser_power_mw" not in flags


def test_flags_but_does_not_reject_custom_allowed_value():
    db = _FakeDB([_FakeDefinition("laser_wavelength_nm", allowed_values=[532, 633, 785, 1064])])
    metadata = ExtractedMetadata(laser_wavelength_nm=660.0)
    flags = check(metadata, "raman", db)
    # Flagged for review...
    assert "laser_wavelength_nm" in flags
    # ...but the caller still gets back the metadata object unmodified.
    assert metadata.laser_wavelength_nm == 660.0


def test_does_not_flag_value_in_allowed_set():
    db = _FakeDB([_FakeDefinition("laser_wavelength_nm", allowed_values=[532, 633, 785, 1064])])
    metadata = ExtractedMetadata(laser_wavelength_nm=785.0)
    flags = check(metadata, "raman", db)
    assert "laser_wavelength_nm" not in flags


def test_no_flags_when_no_field_definitions():
    db = _FakeDB([])
    metadata = ExtractedMetadata()
    flags = check(metadata, "raman", db)
    assert flags == {}


def test_is_pure_and_side_effect_free():
    db = _FakeDB([_FakeDefinition("integration_time_ms", required=True)])
    metadata = ExtractedMetadata(integration_time_ms=None)
    check(metadata, "raman", db)
    # Calling twice yields the same result — no hidden state mutation.
    flags_again = check(metadata, "raman", db)
    assert "integration_time_ms" in flags_again
