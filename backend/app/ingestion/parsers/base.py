"""The `VendorParser` protocol every deterministic parser implements."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.schemas.ingestion import ExtractedMetadata


@runtime_checkable
class VendorParser(Protocol):
    """A deterministic parser for one vendor's raw spectral file format.

    `can_parse` must be a cheap, purely-inspective sniff (magic bytes /
    header markers) — it must never raise on garbage input, just return
    False. `parse` is only ever called after `can_parse` returned True.
    """

    vendor_format: str
    version: str

    def can_parse(self, raw_bytes: bytes, filename: str) -> bool: ...

    def parse(self, raw_bytes: bytes) -> ExtractedMetadata: ...
