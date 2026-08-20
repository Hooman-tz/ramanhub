"""Tests for the local-filesystem storage backend (STORAGE_BACKEND=local),
and for the demo-data generators that rely on it producing files the rest
of the pipeline can actually consume."""
from __future__ import annotations

import numpy as np
import pytest

from app.config import settings
from app.ingestion.parsers.horiba import HoribaParser
from app.seed.demo_data import DEMO_SPECTRA, synthesize_spectrum, to_horiba_ascii
from app.storage import s3_client


@pytest.fixture()
def local_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "STORAGE_LOCAL_DIR", str(tmp_path))
    return tmp_path


def test_roundtrip(local_storage):
    s3_client.upload_bytes("raw-spectra", "user/abc/file.txt", b"100 1.0\n200 2.0\n")

    assert s3_client.download_bytes("raw-spectra", "user/abc/file.txt") == b"100 1.0\n200 2.0\n"
    assert (local_storage / "raw-spectra" / "user" / "abc" / "file.txt").is_file()


def test_object_exists(local_storage):
    assert not s3_client.object_exists("raw-spectra", "nope")
    s3_client.upload_bytes("raw-spectra", "yes", b"data")
    assert s3_client.object_exists("raw-spectra", "yes")


def test_missing_object_raises(local_storage):
    with pytest.raises(FileNotFoundError):
        s3_client.download_bytes("raw-spectra", "never/uploaded")


def test_traversal_key_is_rejected(local_storage):
    """Keys are server-generated today, but a hostile filename reaching a
    key must not become path traversal."""
    with pytest.raises(ValueError, match="escapes"):
        s3_client.upload_bytes("raw-spectra", "../../outside", b"x")
    with pytest.raises(ValueError, match="escapes"):
        s3_client.download_bytes("raw-spectra", "../secrets")


def test_relative_local_dir_is_anchored_at_repo_root(monkeypatch, tmp_path):
    """A relative STORAGE_LOCAL_DIR must resolve against the repo root, not
    the process CWD — the same anchoring rule (and the same footgun) as the
    .env file."""
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "STORAGE_LOCAL_DIR", "storage-data-test")
    monkeypatch.chdir(tmp_path)

    from app.config import REPO_ROOT

    path = s3_client._local_path("bucket", "key")
    assert str(path).startswith(str(REPO_ROOT))


# --- Demo-data generators ----------------------------------------------------


def test_demo_files_are_recognized_by_the_horiba_parser():
    """The point of using Horiba ASCII format: ingestion of the sample file
    must parse deterministically, with no LLM fallback (no API key needed)."""
    parser = HoribaParser()
    for spec in DEMO_SPECTRA:
        x, y = synthesize_spectrum(spec["peaks"], noise=spec["noise"])
        payload = to_horiba_ascii(
            x, y, title=spec["title"], laser_nm=spec["laser_nm"],
            acq_time_s=spec["acq_time_s"], accumulations=spec["accumulations"],
        )
        assert parser.can_parse(payload, "demo.txt"), spec["title"]
        metadata = parser.parse(payload)
        assert metadata.laser_wavelength_nm == spec["laser_nm"]
        assert metadata.integration_time_ms == spec["acq_time_s"] * 1000


def test_demo_files_load_as_two_column_spectra():
    """`load_raw_spectrum`'s permissive text parse must read the data body
    (header lines are #-prefixed and skipped)."""
    spec = DEMO_SPECTRA[0]
    x, y = synthesize_spectrum(spec["peaks"], noise=spec["noise"])
    payload = to_horiba_ascii(
        x, y, title=spec["title"], laser_nm=spec["laser_nm"],
        acq_time_s=spec["acq_time_s"], accumulations=spec["accumulations"],
    )

    wavenumbers = []
    for line in payload.decode().splitlines():
        if line.startswith("#"):
            continue
        wavenumbers.append(float(line.split()[0]))
    assert len(wavenumbers) == x.size
    assert wavenumbers[0] == pytest.approx(200.0)


def test_generation_is_deterministic():
    """Fixed RNG seed: re-running the seed never churns content hashes."""
    spec = DEMO_SPECTRA[1]
    _x1, y1 = synthesize_spectrum(spec["peaks"], fluorescence=spec["fluorescence"], noise=spec["noise"])
    _x2, y2 = synthesize_spectrum(spec["peaks"], fluorescence=spec["fluorescence"], noise=spec["noise"])
    np.testing.assert_array_equal(y1, y2)
