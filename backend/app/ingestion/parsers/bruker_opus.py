"""Bruker OPUS binary spectral file parser.

OPUS files (used by Bruker FT-Raman/FT-IR instruments) are a block-structured
binary format whose first 4 bytes are a fixed magic number, commonly cited
as `0A 0A FE FE` (the value referenced by existing open-source OPUS readers).
After the magic comes a block directory of fixed-size entries, each pointing
at a data or parameter block; parameters are stored under short (3-char)
tags such as `LWN` (laser wavenumber), `RES` (resolution), `NSS` (number of
sample scans), `DAT`/`TIM` (date/time), `INS` (instrument name).

Fully walking the block directory to decode those parameter blocks (which
mixes packed binary and text-in-binary encodings) is a significant
undertaking and out of scope for this pass. `can_parse` is a solid magic-byte
sniff; `parse()` is best-effort only — it returns vendor identity and
attempts a loose scan for an embedded instrument-name string, leaving the
rest null (documented limitation).
"""
from __future__ import annotations

import re

from app.schemas.ingestion import ExtractedMetadata

OPUS_MAGIC = b"\x0a\x0a\xfe\xfe"

_PRINTABLE_RUN_RE = re.compile(rb"[ -~]{4,40}")


class BrukerOpusParser:
    vendor_format = "bruker_opus"
    version = "0.1-partial"

    def can_parse(self, raw_bytes: bytes, filename: str) -> bool:
        return raw_bytes[:4] == OPUS_MAGIC

    def parse(self, raw_bytes: bytes) -> ExtractedMetadata:
        instrument_model: str | None = None
        for run in _PRINTABLE_RUN_RE.finditer(raw_bytes[:8192]):
            candidate = run.group(0).decode("ascii", errors="ignore")
            if any(token in candidate for token in ("Bruker", "OPUS", "IFS", "MPA", "Vertex")):
                instrument_model = candidate.strip()
                break

        return ExtractedMetadata(
            modality="raman",
            instrument_vendor="Bruker",
            instrument_model=instrument_model,
        )
