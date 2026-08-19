"""Shared helper for loading vendor header fixture bytes in parser tests."""
from __future__ import annotations

from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "headers"


def load(filename: str) -> bytes:
    return (FIXTURES_DIR / filename).read_bytes()


OCEAN_INSIGHT = "ocean_insight_sample.txt"
HORIBA = "horiba_labspec_sample.txt"
THERMO = "thermo_jcamp_sample.txt"
RENISHAW = "renishaw_sample.wdf"
WITEC = "witec_sample.wip"
BRUKER_OPUS = "bruker_opus_sample.opus"

ALL_FIXTURES = (OCEAN_INSIGHT, HORIBA, THERMO, RENISHAW, WITEC, BRUKER_OPUS)
