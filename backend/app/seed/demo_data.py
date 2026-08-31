"""Demo/test data: a demo user publishing three synthetic Raman spectra,
plus votes and comments so the Trending feed has content, plus a
drag-and-droppable sample file written to `sample-data/` at the repo root.

Run with:
    uv run python -m app.seed.demo_data      (or `make seed-demo`)

Each spectrum is synthesized to exercise a different part of the
preprocessing suite:

- Polystyrene: clean, sharp bands at the textbook positions — the sanity
  check, and the DOI-verified example for the trust-tier search filter.
- Rhodamine 6G (SERS): real bands drowned under a large exponential
  fluorescence background — the showcase for airPLS/AsLS baseline removal.
- Calcite: clean bands plus injected cosmic-ray spikes — the showcase for
  the despiking step.

Files are written in Horiba LabSpec ASCII format because that's a format
the deterministic parser recognizes, so ingestion of the sample file works
end-to-end without an LLM API key.

Idempotent: if the demo user already exists, the script reports and exits
without touching anything (drop the user's rows to re-seed).
"""
from __future__ import annotations

import hashlib
import io
from datetime import UTC, datetime

import numpy as np

from app.config import REPO_ROOT, settings
from app.db.base import SessionLocal
from app.models.enums import Modality, SpectrumState, UploadStatus
from app.models.raw_file import RawFile
from app.models.social import Comment, Vote
from app.models.spectrum import Spectrum
from app.models.user import User
from app.spectra_io import compute_snr
from app.storage.s3_client import upload_bytes

DEMO_GOOGLE_SUB = "ramanhub-demo-seed"
DEMO_EMAIL = "demo@ramanhub.example"

# Fixed RNG seed: re-running produces byte-identical files, so re-seeding a
# wiped database (or regenerating sample-data/) never churns content hashes.
RNG_SEED = 20260819


def _gaussian(x: np.ndarray, center: float, amplitude: float, width: float) -> np.ndarray:
    return amplitude * np.exp(-((x - center) ** 2) / (2 * width**2))


def synthesize_spectrum(
    peaks: list[tuple[float, float, float]],
    *,
    fluorescence: float = 0.0,
    noise: float = 1.0,
    spikes: list[tuple[int, float]] | None = None,
    seed: int = RNG_SEED,
) -> tuple[np.ndarray, np.ndarray]:
    """Return `(wavenumbers, intensities)` on a 200-3200 cm-1 grid (2 cm-1
    step). `peaks` are (center, amplitude, width) Gaussians; `fluorescence`
    scales a broad decaying-exponential background; `spikes` are
    (index, amplitude) cosmic-ray hits."""
    x = np.arange(200.0, 3200.0, 2.0)
    y = np.full_like(x, 40.0)  # detector offset
    for center, amplitude, width in peaks:
        y += _gaussian(x, center, amplitude, width)
    if fluorescence:
        normalized = (x - x.min()) / (x.max() - x.min())
        y += fluorescence * np.exp(-2.5 * normalized)
    y += np.random.default_rng(seed).normal(0.0, noise, size=x.shape)
    for index, amplitude in spikes or []:
        y[index] += amplitude
    return x, y


def to_horiba_ascii(
    x: np.ndarray,
    y: np.ndarray,
    *,
    title: str,
    laser_nm: int,
    acq_time_s: float,
    accumulations: int,
) -> bytes:
    """Serialize in Horiba LabSpec ASCII export format — `#key:\\tvalue`
    header lines then two-column data — which the deterministic Horiba
    parser recognizes (see app/ingestion/parsers/horiba.py)."""
    buffer = io.StringIO()
    buffer.write("#Acquired:\t08/19/2026 10:00:00\n")
    buffer.write(f"#Title:\t{title}\n")
    buffer.write(f"#Acq. time (s):\t{acq_time_s:g}\n")
    buffer.write(f"#Accumulations:\t{accumulations}\n")
    buffer.write(f"#Range (cm-1):\t{x.min():.0f} - {x.max():.0f}\n")
    buffer.write("#Grating:\t1800\n")
    buffer.write("#Objective:\tx50\n")
    buffer.write(f"#Laser:\t{laser_nm}\n")
    buffer.write("#Spectro:\tiHR320\n")
    for wn, intensity in zip(x, y, strict=True):
        buffer.write(f"{wn:.2f}\t{intensity:.3f}\n")
    return buffer.getvalue().encode()


DEMO_SPECTRA = [
    {
        "title": "Polystyrene film — reference standard",
        "material_type": "polystyrene",
        "laser_nm": 532,
        "acq_time_s": 10.0,
        "accumulations": 4,
        # Textbook polystyrene bands; the 1001 cm-1 ring-breathing mode dominates.
        "peaks": [
            (620.9, 30, 6), (795.8, 18, 7), (1001.4, 100, 4.5), (1031.8, 45, 5),
            (1155.3, 20, 6), (1450.5, 30, 8), (1583.1, 25, 7), (1602.3, 55, 6),
        ],
        "noise": 1.5,
        "fluorescence": 0.0,
        "spikes": [],
        "doi": "10.0000/ramanhub-demo.polystyrene",
        "description": "Synthetic demo spectrum with textbook polystyrene band positions. "
        "The DOI is a placeholder to demonstrate the DOI-verified trust tier — this is "
        "generated data, not a measurement.",
    },
    {
        "title": "Rhodamine 6G on Ag colloid (SERS)",
        "material_type": "rhodamine 6g",
        "laser_nm": 633,
        "acq_time_s": 5.0,
        "accumulations": 2,
        "peaks": [
            (611, 55, 6), (773, 40, 7), (1183, 35, 7),
            (1363, 85, 7), (1509, 100, 8), (1649, 70, 7),
        ],
        "noise": 4.0,
        "fluorescence": 900.0,
        "spikes": [],
        "doi": None,
        "description": "Synthetic demo: real bands sitting on a large fluorescence "
        "background. Try a fluorescence-suppression step (airPLS) in the pipeline "
        "builder and watch the baseline drop out.",
    },
    {
        "title": "Calcite crystal — with cosmic-ray spikes",
        "material_type": "calcite",
        "laser_nm": 785,
        "acq_time_s": 30.0,
        "accumulations": 1,
        "peaks": [(281, 60, 6), (712, 25, 5), (1086, 100, 4.5), (1435, 12, 8)],
        "noise": 2.0,
        "fluorescence": 60.0,
        "spikes": [(400, 850.0), (401, 400.0), (950, 700.0), (1210, 900.0)],
        "doi": None,
        "description": "Synthetic demo: calcite bands plus injected cosmic-ray spikes. "
        "Try the despike step first — then see what normalization looks like without it.",
    },
]

# One extra material for the drag-and-drop sample file, distinct from the
# seeded spectra so uploading it demonstrably adds something new.
SAMPLE_FILE_SPEC = {
    "title": "Acetaminophen powder",
    "laser_nm": 785,
    "acq_time_s": 15.0,
    "accumulations": 3,
    "peaks": [
        (329, 25, 6), (390, 30, 6), (465, 20, 6), (651, 45, 6), (797, 35, 6),
        (857, 60, 6), (968, 25, 6), (1168, 40, 7), (1236, 55, 7), (1323, 70, 8),
        (1561, 50, 8), (1648, 45, 8),
    ],
    "noise": 2.0,
    "fluorescence": 120.0,
    "spikes": [(700, 600.0)],
}


def write_sample_file() -> str:
    """Write the drag-and-droppable demo file to `sample-data/` at the repo
    root; returns its path."""
    x, y = synthesize_spectrum(
        SAMPLE_FILE_SPEC["peaks"],
        fluorescence=SAMPLE_FILE_SPEC["fluorescence"],
        noise=SAMPLE_FILE_SPEC["noise"],
        spikes=SAMPLE_FILE_SPEC["spikes"],
    )
    payload = to_horiba_ascii(
        x, y,
        title=SAMPLE_FILE_SPEC["title"],
        laser_nm=SAMPLE_FILE_SPEC["laser_nm"],
        acq_time_s=SAMPLE_FILE_SPEC["acq_time_s"],
        accumulations=SAMPLE_FILE_SPEC["accumulations"],
    )
    sample_dir = REPO_ROOT / "sample-data"
    sample_dir.mkdir(exist_ok=True)
    path = sample_dir / "horiba_acetaminophen_785nm.txt"
    path.write_bytes(payload)
    return str(path)


def _make_user(session, *, google_sub: str, email: str, name: str) -> User:
    user = User(google_sub=google_sub, email=email, display_name=name)
    session.add(user)
    session.flush()
    return user


def run() -> None:
    session = SessionLocal()
    try:
        existing = session.query(User).filter_by(google_sub=DEMO_GOOGLE_SUB).one_or_none()
        if existing is not None:
            print("Demo data already seeded (demo user exists) — nothing to do.")
            return

        demo = _make_user(
            session, google_sub=DEMO_GOOGLE_SUB, email=DEMO_EMAIL, name="RamanHub Demo"
        )
        voters = [
            _make_user(
                session,
                google_sub=f"{DEMO_GOOGLE_SUB}-voter-{i}",
                email=f"demo-voter-{i}@ramanhub.example",
                name=f"Demo Scientist {i}",
            )
            for i in (1, 2)
        ]

        now = datetime.now(UTC)
        spectra: list[Spectrum] = []
        for spec in DEMO_SPECTRA:
            x, y = synthesize_spectrum(
                spec["peaks"],
                fluorescence=spec["fluorescence"],
                noise=spec["noise"],
                spikes=spec["spikes"],
            )
            payload = to_horiba_ascii(
                x, y,
                title=spec["title"],
                laser_nm=spec["laser_nm"],
                acq_time_s=spec["acq_time_s"],
                accumulations=spec["accumulations"],
            )
            content_hash = hashlib.sha256(payload).hexdigest()
            filename = f"{spec['material_type'].replace(' ', '_')}_{spec['laser_nm']}nm.txt"
            storage_key = f"{demo.id}/{content_hash}/{filename}"
            upload_bytes(settings.S3_BUCKET_RAW, storage_key, payload, content_type="text/plain")

            raw_file = RawFile(
                owner_id=demo.id,
                modality=Modality.raman,
                storage_bucket=settings.S3_BUCKET_RAW,
                storage_key=storage_key,
                original_filename=filename,
                content_hash=content_hash,
                file_size_bytes=len(payload),
                vendor_format="horiba_labspec",
                upload_status=UploadStatus.uploaded,
            )
            session.add(raw_file)
            session.flush()

            confirmed_metadata = {
                "laser_wavelength_nm": spec["laser_nm"],
                "integration_time_ms": spec["acq_time_s"] * 1000,
                "accumulations": spec["accumulations"],
                "instrument_vendor": "Horiba",
                "instrument_model": "iHR320",
                "spectral_range_cm1": f"{x.min():.0f}-{x.max():.0f}",
            }
            spectrum = Spectrum(
                raw_file_id=raw_file.id,
                owner_id=demo.id,
                modality=Modality.raman,
                title=spec["title"],
                description=spec["description"],
                confirmed_metadata=confirmed_metadata,
                material_type=spec["material_type"],
                excitation_wavelength_nm=float(spec["laser_nm"]),
                snr=compute_snr(y),
                license_id="CC-BY-4.0",
                state=SpectrumState.published,
                published_at=now,
                doi=spec["doi"],
            )
            session.add(spectrum)
            session.flush()
            spectra.append(spectrum)

        # Social layer: votes + comments so Trending isn't empty. The SERS
        # spectrum gets both voters, calcite one — a visible ranking.
        session.add(Vote(spectrum_id=spectra[1].id, user_id=voters[0].id))
        session.add(Vote(spectrum_id=spectra[1].id, user_id=voters[1].id))
        session.add(Vote(spectrum_id=spectra[2].id, user_id=voters[0].id))
        session.add(
            Comment(
                spectrum_id=spectra[1].id,
                user_id=voters[0].id,
                body="Nice demo of a fluorescence-dominated acquisition — airPLS with "
                "lambda around 1e5 recovers the band shape well.",
            )
        )
        session.add(
            Comment(
                spectrum_id=spectra[2].id,
                user_id=voters[1].id,
                body="Good spike-removal test case. The despike step's defaults catch "
                "all four hits without touching the 1086 band.",
            )
        )

        session.commit()
        print(f"Seeded demo user + {len(spectra)} published spectra, votes, and comments.")
        sample_path = write_sample_file()
        print(f"Sample upload file written to {sample_path}")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    run()
