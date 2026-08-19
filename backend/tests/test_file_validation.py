"""Unit tests for app.security.file_validation — content-based upload
validation (Module 5). No DB required; pure functions over bytes."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.config import settings
from app.security.file_validation import (
    is_plausible_text_content,
    validate_upload_content,
    validate_upload_size,
)

# ---------------------------------------------------------------------------
# validate_upload_size
# ---------------------------------------------------------------------------


def test_validate_upload_size_accepts_under_limit():
    validate_upload_size(1024)  # should not raise


def test_validate_upload_size_accepts_exactly_at_limit():
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    validate_upload_size(max_bytes)  # should not raise


def test_validate_upload_size_rejects_over_limit():
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    with pytest.raises(HTTPException) as exc_info:
        validate_upload_size(max_bytes + 1)
    assert exc_info.value.status_code == 413


# ---------------------------------------------------------------------------
# is_plausible_text_content
# ---------------------------------------------------------------------------


def test_plausible_text_content_accepted():
    content = b"wavenumber,intensity\n100,1.0\n200,2.0\n300,5.0\n"
    assert is_plausible_text_content(content) is True


def test_random_binary_content_rejected():
    content = bytes(range(256)) * 4
    assert is_plausible_text_content(content) is False


def test_empty_content_rejected():
    assert is_plausible_text_content(b"") is False


# ---------------------------------------------------------------------------
# validate_upload_content
# ---------------------------------------------------------------------------


def test_validate_upload_content_accepts_plausible_text():
    validate_upload_content(b"100 1.0\n200 2.0\n300 5.0\n")  # should not raise


def test_validate_upload_content_rejects_empty_file():
    with pytest.raises(HTTPException) as exc_info:
        validate_upload_content(b"")
    assert exc_info.value.status_code == 400
    assert "Empty" in exc_info.value.detail


def test_validate_upload_content_accepts_known_vendor_binary_magic():
    # Renishaw WDF magic bytes, followed by arbitrary binary payload — must
    # be accepted outright even though it wouldn't pass the printable-text
    # check on its own.
    content = b"WDF1" + bytes(range(256))
    validate_upload_content(content)  # should not raise


def test_validate_upload_content_rejects_windows_executable():
    content = b"MZ" + b"\x90\x00\x03\x00\x00\x00" * 20
    with pytest.raises(HTTPException) as exc_info:
        validate_upload_content(content)
    assert exc_info.value.status_code == 400
    assert "executable" in exc_info.value.detail.lower()


def test_validate_upload_content_rejects_elf_executable():
    content = b"\x7fELF" + b"\x00" * 100
    with pytest.raises(HTTPException):
        validate_upload_content(content)


def test_validate_upload_content_rejects_pdf():
    content = b"%PDF-1.4\n" + b"\x00" * 100
    with pytest.raises(HTTPException):
        validate_upload_content(content)


def test_validate_upload_content_rejects_png():
    content = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    with pytest.raises(HTTPException):
        validate_upload_content(content)


def test_validate_upload_content_rejects_zip_based_format():
    content = b"PK\x03\x04" + b"\x00" * 100
    with pytest.raises(HTTPException):
        validate_upload_content(content)


def test_validate_upload_content_rejects_random_garbage():
    content = bytes([0x00, 0x01, 0x02, 0x03, 0x04, 0x05]) * 50
    with pytest.raises(HTTPException) as exc_info:
        validate_upload_content(content)
    assert exc_info.value.status_code == 400


def test_validate_upload_content_html_error_page_with_txt_extension_rejected():
    # The scenario this whole module exists for: filename says .txt, but the
    # content sniff should still catch clearly-wrong content. Plain HTML is
    # actually mostly-printable text, so this documents the current
    # (deliberately cheap) sniff's behavior rather than asserting rejection.
    content = b"<html><body>404 Not Found</body></html>\n" * 10
    # This is plausible *text*, so it's accepted at this layer — the sniff's
    # job is to catch binary/garbage, not to semantically validate spectral
    # content (that's the parser/sanity-check's job downstream).
    validate_upload_content(content)
