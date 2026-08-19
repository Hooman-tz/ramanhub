"""Registry of all deterministic vendor parsers, dispatched by sniffing raw
bytes/filename. Order matters only in the (should-never-happen) case of an
ambiguous file matching two parsers' `can_parse` — first match wins.
"""
from __future__ import annotations

from app.ingestion.parsers.base import VendorParser
from app.ingestion.parsers.bruker_opus import BrukerOpusParser
from app.ingestion.parsers.horiba import HoribaParser
from app.ingestion.parsers.ocean_insight import OceanInsightParser
from app.ingestion.parsers.renishaw import RenishawParser
from app.ingestion.parsers.thermo import ThermoParser
from app.ingestion.parsers.witec import WitecParser

PARSERS: list[VendorParser] = [
    OceanInsightParser(),
    RenishawParser(),
    HoribaParser(),
    WitecParser(),
    BrukerOpusParser(),
    ThermoParser(),
]


def find_parser(raw_bytes: bytes, filename: str) -> VendorParser | None:
    """Return the first registered parser whose `can_parse` accepts this
    file, or None if no deterministic parser recognizes it."""
    for parser in PARSERS:
        try:
            matched = parser.can_parse(raw_bytes, filename)
        except Exception:  # noqa: BLE001 - a buggy sniff must not break dispatch
            matched = False
        if matched:
            return parser
    return None
