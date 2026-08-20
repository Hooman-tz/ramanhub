"""Idempotent seed data for local/dev environments.

Run with:
    uv run python -m app.seed.seed_data

Safe to re-run: every insert is guarded by a check-exists-first (upsert-style)
so re-running never duplicates rows or trips a unique constraint.
"""
from app.db.base import SessionLocal
from app.models.enums import FieldDataType, Modality
from app.models.field_registry import LedgerStepDefinition, MetadataFieldDefinition
from app.models.license import License
from app.processing.algorithms.registry import ALGORITHM_SPECS

LICENSES = [
    {
        "id": "CC-BY-4.0",
        "name": "Creative Commons Attribution 4.0",
        "url": "https://creativecommons.org/licenses/by/4.0/",
        "is_default": True,
    },
    {
        "id": "CC0-1.0",
        "name": "CC0 1.0 Universal (Public Domain)",
        "url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "is_default": False,
    },
]

# spectral_range_cm1 is stored as a "min-max" string, e.g. "200-3200", rather
# than a numeric pair — keeps this a single scalar field like the rest of the
# registry entries; parsing/splitting on "-" is left to the ingestion layer.
RAMAN_METADATA_FIELDS = [
    {
        "field_key": "laser_wavelength_nm",
        "data_type": FieldDataType.number,
        "required": True,
        "allowed_values": [532, 633, 785, 1064],
        "unit": "nm",
        "description": "Excitation laser wavelength.",
    },
    {
        "field_key": "laser_power_mw",
        "data_type": FieldDataType.number,
        "min_value": 0,
        "unit": "mW",
        "description": "Laser power at the sample.",
    },
    {
        "field_key": "integration_time_ms",
        "data_type": FieldDataType.number,
        "required": True,
        "min_value": 0,
        "unit": "ms",
        "description": "Exposure/integration time per acquisition.",
    },
    {
        "field_key": "accumulations",
        "data_type": FieldDataType.number,
        "min_value": 1,
        "description": "Number of co-added accumulations.",
    },
    {
        "field_key": "spectral_range_cm1",
        "data_type": FieldDataType.string,
        "unit": "cm-1",
        "description": 'Acquired spectral range, stored as "min-max", e.g. "200-3200".',
    },
    {
        "field_key": "resolution_cm1",
        "data_type": FieldDataType.number,
        "min_value": 0,
        "unit": "cm-1",
        "description": "Spectral resolution.",
    },
    {
        "field_key": "instrument_vendor",
        "data_type": FieldDataType.string,
        "description": "Instrument manufacturer, e.g. Renishaw, Horiba.",
    },
    {
        "field_key": "instrument_model",
        "data_type": FieldDataType.string,
        "description": "Instrument model.",
    },
    {
        "field_key": "acquisition_datetime",
        "data_type": FieldDataType.date,
        "description": "Date/time the spectrum was acquired.",
    },
    {
        "field_key": "sample_description",
        "data_type": FieldDataType.string,
        "description": "Free-text description of the sample.",
    },
    {
        "field_key": "grating_lines_mm",
        "data_type": FieldDataType.number,
        "description": "Diffraction grating groove density.",
    },
    {
        "field_key": "objective_magnification",
        "data_type": FieldDataType.number,
        "description": "Microscope objective magnification.",
    },
]

# Derived from the code-side algorithm registry rather than restated here,
# so a new (or re-versioned) algorithm can never ship with its DB-side
# `LedgerStepDefinition` row missing or its param schema out of date — which
# would make `validate_ledger_steps` reject ledgers the code can happily run.
RAMAN_LEDGER_STEPS = [
    {
        "step_type": spec.step_type,
        "algorithm_version": spec.version,
        "param_schema": spec.param_schema,
        "description": spec.description,
    }
    for spec in ALGORITHM_SPECS
]


def seed_licenses(session) -> None:
    for entry in LICENSES:
        existing = session.get(License, entry["id"])
        if existing is None:
            session.add(License(**entry))
        else:
            for key, value in entry.items():
                setattr(existing, key, value)


def seed_metadata_field_definitions(session) -> None:
    for entry in RAMAN_METADATA_FIELDS:
        existing = (
            session.query(MetadataFieldDefinition)
            .filter_by(modality=Modality.raman, field_key=entry["field_key"])
            .one_or_none()
        )
        if existing is None:
            session.add(MetadataFieldDefinition(modality=Modality.raman, **entry))
        else:
            for key, value in entry.items():
                setattr(existing, key, value)


def seed_ledger_step_definitions(session) -> None:
    for entry in RAMAN_LEDGER_STEPS:
        existing = (
            session.query(LedgerStepDefinition)
            .filter_by(
                modality=Modality.raman,
                step_type=entry["step_type"],
                algorithm_version=entry["algorithm_version"],
            )
            .one_or_none()
        )
        if existing is None:
            session.add(LedgerStepDefinition(modality=Modality.raman, **entry))
        else:
            for key, value in entry.items():
                setattr(existing, key, value)


def run() -> None:
    session = SessionLocal()
    try:
        seed_licenses(session)
        seed_metadata_field_definitions(session)
        seed_ledger_step_definitions(session)
        session.commit()
        print("Seed data applied successfully.")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    run()
