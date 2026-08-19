"""Compute a stable hash of a vendor file's header *template*, independent of
run-specific values (timestamps, etc.), so files produced by the same
instrument/software version hash identically and can share a
`VendorParseCache` entry.
"""
from __future__ import annotations

import hashlib
import re

# Matches common date/time-shaped substrings so they can be blanked out
# before hashing: ISO dates, US/EU slash dates, HH:MM(:SS) times, and
# "Mon DD YYYY"-style dates. Deliberately permissive (over-matching a
# non-date numeric run is fine — we only care about template stability).
_MONTHS = r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
_WEEKDAYS = r"Mon|Tue|Wed|Thu|Fri|Sat|Sun"

_DATE_RE = re.compile(
    rf"""
    \b({_WEEKDAYS})\s+({_MONTHS})[a-z]*\s+\d{{1,2}}\s+\d{{2}}:\d{{2}}:\d{{2}}\s+\S+\s+\d{{4}}\b
                                        # Java-style: "Thu Jan 01 00:00:00 GMT 2026"
    | \b\d{{4}}-\d{{2}}-\d{{2}}\b              # 2024-01-31
    | \b\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\b        # 1/31/2024, 31/01/24
    | \b({_MONTHS})[a-z]*\s+\d{{1,2}},?\s+\d{{4}}\b   # Jan 31, 2024
    | \b\d{{1,2}}:\d{{2}}(:\d{{2}})?(\s?[AaPp][Mm])?\b # 13:45:02, 1:45 PM
    """,
    re.VERBOSE,
)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_header(header_text: str) -> str:
    """Strip run-specific date/time substrings and collapse whitespace so the
    same header *template* normalizes identically regardless of the
    particular run it came from.
    """
    text = _DATE_RE.sub("<DATE>", header_text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def compute_header_hash(header_text: str) -> str:
    """Return the sha256 hex digest of the normalized header text."""
    normalized = normalize_header(header_text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
