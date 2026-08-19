"""WITec Project (.wip / .wid) binary spectral file parser.

WITec Project files are containers built on the Microsoft OLE2 Compound File
Binary Format, which carries a fixed, well-documented 8-byte magic signature
`D0 CF 11 E0 A1 B1 1A E1` at offset 0. That signature is what `can_parse`
sniffs on.

Full parsing requires walking the OLE2 directory/FAT structure to find the
`Data`/`TDGraph` streams WITec nests project trees under — a significant
undertaking and out of scope for this pass. `parse()` is best-effort only:
it returns the vendor identity and null for everything else (documented
limitation).
"""
from __future__ import annotations

from app.schemas.ingestion import ExtractedMetadata

OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class WitecParser:
    vendor_format = "witec_project"
    version = "0.1-partial"

    def can_parse(self, raw_bytes: bytes, filename: str) -> bool:
        if raw_bytes[:8] != OLE2_MAGIC:
            return False
        # OLE2 is a generic container (also used by legacy .doc/.xls); a
        # WITec-specific hint in the filename or embedded strings narrows
        # false positives without requiring full directory parsing.
        lowered_name = filename.lower()
        if lowered_name.endswith((".wip", ".wid")):
            return True
        return b"WITec" in raw_bytes[:65536]

    def parse(self, raw_bytes: bytes) -> ExtractedMetadata:
        return ExtractedMetadata(
            modality="raman",
            instrument_vendor="WITec",
        )
