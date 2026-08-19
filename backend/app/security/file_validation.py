"""Content-based validation for uploaded raw spectrum files.

Per raman-platform-architecture-v2.md's MODULE 5: "Validate uploaded files by
content, not file extension; enforce a size limit". Filenames/extensions are
entirely client-supplied and trivially spoofed, so every check here looks at
the actual bytes:

- reject empty files
- reject anything over `settings.MAX_UPLOAD_SIZE_MB`
- accept known vendor binary formats by magic bytes (Renishaw WDF, WITec/OLE2,
  Bruker OPUS, ...)
- reject common "dangerous"/unexpected binary formats by magic bytes
  (executables, archives, images, PDFs) that a spectral data file should
  never actually be, regardless of what extension it was uploaded with
- otherwise require the file to look like plausible text (mostly
  printable/whitespace bytes in a leading sample), since every vendor format
  we don't have a magic-byte signature for is a plain-text header/data
  export

This is deliberately a cheap, dependency-free sniff — not a full file-type
classifier — matched to the threat model of a research data-sharing upload
endpoint (reject obviously-wrong content early, before it's written to
storage or queued for parsing), not a general-purpose antivirus.
"""
from __future__ import annotations

from fastapi import HTTPException, status

from app.config import settings

# Known binary magic-byte signatures for vendor formats we deterministically
# parse — always acceptable even though they're not plausible text.
KNOWN_VENDOR_BINARY_MAGICS: tuple[bytes, ...] = (
    b"WDF1",  # Renishaw WiRE
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",  # OLE2 compound file (WITec, legacy Office)
    b"\x0a\x0a\xfe\xfe",  # Bruker OPUS
)

# Magic-byte signatures for common binary formats a Raman spectrum upload
# should never actually be. Checked (and rejected, with a specific reason)
# before falling back to the generic printable-text ratio check below, since
# they'd otherwise just fail that check anyway with a less useful message.
_DANGEROUS_BINARY_MAGICS: tuple[bytes, ...] = (
    b"MZ",  # Windows PE/DLL/EXE
    b"\x7fELF",  # Linux ELF executable
    b"\xca\xfe\xba\xbe",  # Java class file / Mach-O fat binary
    b"\xfe\xed\xfa\xce",  # Mach-O 32-bit
    b"\xfe\xed\xfa\xcf",  # Mach-O 64-bit
    b"\xce\xfa\xed\xfe",  # Mach-O 32-bit (reverse byte order)
    b"\xcf\xfa\xed\xfe",  # Mach-O 64-bit (reverse byte order)
    b"PK\x03\x04",  # ZIP-based (docx/xlsx/jar/apk/...)
    b"%PDF-",  # PDF
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"\xff\xd8\xff",  # JPEG
    b"GIF87a",  # GIF
    b"GIF89a",  # GIF
)

# How much of the file's leading bytes to sample for the printable-text
# check — enough to catch a non-text file confidently without reading (and
# holding in memory) arbitrarily large uploads just to validate them.
_SNIFF_SAMPLE_BYTES = 8192
_PRINTABLE_RATIO_THRESHOLD = 0.85


def is_plausible_text_content(raw_bytes: bytes) -> bool:
    """True if a leading sample of `raw_bytes` is mostly printable ASCII /
    common whitespace — the shape of a plain-text vendor header/data export.
    """
    if not raw_bytes:
        return False
    sample = raw_bytes[:_SNIFF_SAMPLE_BYTES]
    printable = sum(1 for b in sample if b in (9, 10, 13) or 32 <= b <= 126)
    return (printable / len(sample)) >= _PRINTABLE_RATIO_THRESHOLD


def validate_upload_size(size_bytes: int) -> None:
    """Hard size cap, enforced as early as possible (before any content
    sniffing or storage write). Raises 413 if exceeded."""
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if size_bytes > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB}MB upload limit",
        )


def validate_upload_content(raw_bytes: bytes) -> None:
    """Content-sniff an upload's bytes; raises 400 with a clear reason if the
    content doesn't look like a recognizable spectral data file. Never
    trusts the filename/extension — only the bytes themselves.
    """
    if not raw_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty file")

    if any(raw_bytes.startswith(magic) for magic in KNOWN_VENDOR_BINARY_MAGICS):
        return

    if any(raw_bytes.startswith(magic) for magic in _DANGEROUS_BINARY_MAGICS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content looks like an executable or unsupported binary format",
        )

    if not is_plausible_text_content(raw_bytes):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File content does not look like a recognizable spectral data file",
        )
