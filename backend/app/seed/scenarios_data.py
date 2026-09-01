"""Twenty test accounts, each acting out one research scenario, with
synthetic spectra + datasets + processing + write-ups + a follow / vote /
comment / share graph.

Run with:
    uv run python -m app.seed.scenarios_data           (or `make seed-scenarios`)
    uv run python -m app.seed.scenarios_data --reset    (drop the 20 personas first)

`make seed` MUST have run first — this script relies on the `License` and
`LedgerStepDefinition` reference rows it creates.

Idempotent: if persona #20 (`nadia-haddad`) already exists the script reports
and exits. Personas are otherwise get-or-created by email, and a persona that
already owns any spectrum/finding is left untouched, so a re-run after a
partial failure resumes rather than duplicates.

Every persona has a real-looking email (`<handle>@scenario.ramanhub.dev`), so
`GET /auth/dev-login?email=<that>` logs you in as them to click through the
real UI (Library / Workbench / Drafts / feed).

The data is synthetic: numpy Raman curves (peaks + baseline + noise) written
as Horiba LabSpec ASCII and run through the real ingestion-format parser and
the real processing-ledger path. It is not measured data.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import settings
from app.db.base import SessionLocal
from app.models.accession import next_finding_accession, next_spectrum_accession
from app.models.analysis import AnalysisDataset, AnalysisDatasetSpectrum
from app.models.curation import Pin
from app.models.enums import FindingEntryKind, FindingState, Modality, SpectrumState, UploadStatus
from app.models.finding import Finding, FindingEntry, FindingSpectrum
from app.models.graph import Follow
from app.models.processing_routine import ProcessingRoutine
from app.models.publication import Publication, PublicationSnapshot
from app.models.raw_file import RawFile
from app.models.social import (
    Comment,
    CommunityPost,
    CommunityPostSpectrum,
    PostReaction,
    Share,
    Vote,
)
from app.models.spectrum import Spectrum
from app.models.user import User
from app.seed.demo_data import synthesize_spectrum, to_horiba_ascii
from app.spectra_io import compute_snr
from app.storage.s3_client import upload_bytes

EMAIL_DOMAIN = "scenario.ramanhub.dev"
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------- recipes

# (material_type, [(center, amplitude, width), ...], organic?) — organic
# materials get a fluorescence background so the baseline tools have work to
# do. Peak positions are roughly textbook; amplitudes/widths are for looks.
MATERIALS: list[tuple[str, list[tuple[float, float, float]], bool]] = [
    ("polystyrene", [(620.9, 30, 6), (1001.4, 100, 4.5), (1031.8, 45, 5), (1602.3, 55, 6)], True),
    ("calcite", [(155, 40, 7), (282, 55, 6), (713, 25, 5), (1086, 100, 4.5), (1435, 12, 8)], False),
    ("quartz", [(128, 45, 6), (206, 60, 6), (355, 20, 6), (464, 100, 5), (808, 18, 7)], False),
    ("gypsum", [(415, 40, 6), (494, 30, 6), (619, 20, 6), (1008, 100, 5), (1135, 25, 7)], False),
    ("anatase", [(144, 100, 5), (197, 20, 6), (399, 45, 7), (515, 40, 7), (639, 55, 7)], False),
    ("hematite", [(225, 70, 7), (292, 100, 7), (411, 55, 8), (612, 30, 9), (1320, 45, 30)], False),
    ("graphene", [(1350, 35, 25), (1582, 100, 18), (2690, 60, 40)], False),
    ("silicon", [(520, 100, 5)], False),
    (
        "pet",
        [(632, 25, 6), (857, 30, 7), (1096, 40, 8), (1290, 35, 8), (1614, 45, 8), (1728, 60, 9)],
        True,
    ),
    ("pmma", [(484, 25, 7), (812, 35, 7), (988, 55, 7), (1450, 40, 9), (1730, 70, 9)], True),
    (
        "cellulose",
        [(380, 30, 8), (1096, 60, 9), (1122, 45, 8), (1380, 40, 9), (1480, 30, 10)],
        True,
    ),
    (
        "aspirin",
        [(423, 25, 6), (749, 40, 7), (1043, 55, 7), (1191, 45, 7), (1607, 50, 8), (1750, 60, 9)],
        True,
    ),
    (
        "acetaminophen",
        [
            (329, 25, 6),
            (651, 45, 6),
            (797, 35, 6),
            (857, 60, 6),
            (1236, 55, 7),
            (1323, 70, 8),
            (1648, 45, 8),
        ],
        True,
    ),
    ("sulfur", [(153, 60, 6), (219, 100, 6), (473, 45, 7)], False),
    (
        "rhodamine 6g",
        [(611, 55, 6), (773, 40, 7), (1363, 85, 7), (1509, 100, 8), (1649, 70, 7)],
        True,
    ),
    (
        "l-cysteine",
        [(498, 40, 7), (680, 55, 7), (867, 35, 7), (1040, 45, 8), (1400, 30, 9), (1620, 35, 9)],
        True,
    ),
    ("rutile", [(143, 60, 6), (235, 40, 12), (447, 100, 8), (612, 70, 9)], False),
    ("barite", [(460, 50, 6), (617, 30, 7), (988, 100, 6), (1140, 25, 8)], False),
    ("polyethylene", [(1063, 60, 8), (1130, 55, 8), (1296, 45, 8), (1440, 40, 10)], True),
    ("fluorite", [(322, 100, 6)], False),
]


# --------------------------------------------------------------------- personas

# (handle, display_name, affiliation, [interests], scenario one-liner,
#  spectra_count, (published, embargoed) counts, material offset,
#  laser lines, guest?, onboarded?)
Persona = dict
PERSONAS: list[Persona] = [
    {
        "handle": "mara-okeefe",
        "name": "Mara O'Keefe",
        "aff": "University of British Columbia",
        "interests": ["raman microscopy", "mineralogy"],
        "scenario": "Brand-new user with a single spectrum, nothing published.",
        "n": 1,
        "pub": (0, 0),
        "mat": 1,
        "lasers": [532],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "dev-nanda",
        "name": "Dev Nanda",
        "aff": "Indian Institute of Science",
        "interests": ["SERS", "plasmonics", "trace detection"],
        "scenario": "SERS methods developer with a large, multi-laser library.",
        "n": 18,
        "pub": (6, 0),
        "mat": 14,
        "lasers": [532, 633, 785],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "lena-fischer",
        "name": "Lena Fischer",
        "aff": "Technical University of Munich",
        "interests": ["pharmaceutical polymorphs", "quantitative raman"],
        "scenario": "Pharma polymorph screening grouped into a labelled dataset.",
        "n": 12,
        "pub": (6, 0),
        "mat": 11,
        "lasers": [785],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "sam-carter",
        "name": "Sam Carter",
        "aff": "independent",
        "interests": ["gemstone identification", "hobby spectroscopy"],
        "scenario": "Hobbyist gemstone ID; everything public, no DOIs.",
        "n": 5,
        "pub": (5, 0),
        "mat": 2,
        "lasers": [532],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "priya-rao",
        "name": "Priya Rao",
        "aff": "National University of Singapore",
        "interests": ["2D materials", "graphene", "phonons"],
        "scenario": "2D-materials group with one embargoed finding.",
        "n": 10,
        "pub": (3, 2),
        "mat": 6,
        "lasers": [532],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "tomasz-wojcik",
        "name": "Tomasz Wójcik",
        "aff": "AGH University of Krakow",
        "interests": ["mineralogy", "cosmic-ray removal", "field raman"],
        "scenario": "Mineralogist with spike-heavy raw data and a saved routine.",
        "n": 10,
        "pub": (2, 0),
        "mat": 3,
        "lasers": [785],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "aisha-bello",
        "name": "Aisha Bello",
        "aff": "University of Lagos",
        "interests": ["microplastics", "environmental raman"],
        "scenario": "Microplastics-in-water survey with a published PCA finding.",
        "n": 14,
        "pub": (5, 0),
        "mat": 8,
        "lasers": [785],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "noah-kim",
        "name": "Noah Kim",
        "aff": "KAIST",
        "interests": ["battery materials", "in-situ raman"],
        "scenario": "Battery cathode degradation; draft finding with figures.",
        "n": 8,
        "pub": (0, 0),
        "mat": 4,
        "lasers": [532],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "elena-costa",
        "name": "Elena Costa",
        "aff": "University of Bologna",
        "interests": ["cultural heritage", "pigments"],
        "scenario": "Heritage pigment reference set, curated with 4 pinned items.",
        "n": 12,
        "pub": (12, 0),
        "mat": 5,
        "lasers": [633],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "raj-patel",
        "name": "Raj Patel",
        "aff": "independent",
        "interests": ["science communication", "open data"],
        "scenario": "Pure feed consumer: follows many, owns nothing.",
        "n": 0,
        "pub": (0, 0),
        "mat": 0,
        "lasers": [532],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "casey-guest",
        "name": "Casey (guest)",
        "aff": "",
        "interests": [],
        "scenario": "Try-before-login guest with one private draft.",
        "n": 1,
        "pub": (0, 0),
        "mat": 7,
        "lasers": [532],
        "guest": True,
        "onboarded": False,
    },
    {
        "handle": "hana-sato",
        "name": "Hana Sato",
        "aff": "University of Tokyo",
        "interests": ["protein secondary structure", "UV resonance raman"],
        "scenario": "Protein structure study; published finding + DOI + repo.",
        "n": 7,
        "pub": (4, 0),
        "mat": 15,
        "lasers": [633],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "kwame-mensah",
        "name": "Kwame Mensah",
        "aff": "KNUST",
        "interests": ["food fraud", "agricultural raman"],
        "scenario": "Cocoa quality / food-fraud screening dataset.",
        "n": 9,
        "pub": (2, 0),
        "mat": 10,
        "lasers": [785],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "olivia-brown",
        "name": "Olivia Brown",
        "aff": "CSIRO",
        "interests": ["soil carbon", "chemometrics", "field survey"],
        "scenario": "Largest library: soil-carbon survey, 3 routines, mixed states.",
        "n": 18,
        "pub": (6, 2),
        "mat": 9,
        "lasers": [785, 1064],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "viktor-petrov",
        "name": "Viktor Petrov",
        "aff": "Moscow State University",
        "interests": ["standoff detection", "explosives"],
        "scenario": "Standoff explosives detection; one embargoed finding.",
        "n": 5,
        "pub": (0, 3),
        "mat": 13,
        "lasers": [785],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "mei-lin",
        "name": "Mei Lin",
        "aff": "Tsinghua University",
        "interests": ["perovskite solar cells", "degradation"],
        "scenario": "Perovskite PV; published finding + DOI + repo + PCA dataset.",
        "n": 11,
        "pub": (5, 0),
        "mat": 16,
        "lasers": [532],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "carlos-ruiz",
        "name": "Carlos Ruiz",
        "aff": "UNAM",
        "interests": ["spirits authentication", "agave"],
        "scenario": "Mezcal authentication; a community dataset post.",
        "n": 9,
        "pub": (4, 0),
        "mat": 18,
        "lasers": [785],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "fatima-zahra",
        "name": "Fatima Zahra",
        "aff": "Mohammed V University",
        "interests": ["phosphate minerals", "geochemistry"],
        "scenario": "Phosphate mineralogy; one draft finding.",
        "n": 6,
        "pub": (1, 0),
        "mat": 17,
        "lasers": [532],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "james-cole",
        "name": "James Cole",
        "aff": "University of Melbourne",
        "interests": ["polymer degradation", "microplastics", "ageing"],
        "scenario": "Polymer/pigment ageing; two published findings, very chatty.",
        "n": 12,
        "pub": (6, 0),
        "mat": 19,
        "lasers": [785],
        "guest": False,
        "onboarded": True,
    },
    {
        "handle": "nadia-haddad",
        "name": "Nadia Haddad",
        "aff": "American University of Beirut",
        "interests": ["biofluid diagnostics", "serum SERS", "machine learning"],
        "scenario": "Serum SERS diagnostics; published finding + DOI + repo, one embargoed.",
        "n": 16,
        "pub": (6, 2),
        "mat": 14,
        "lasers": [785],
        "guest": False,
        "onboarded": True,
    },
]

MARKER_HANDLE = "nadia-haddad"


# --------------------------------------------------------------------- findings

# handle -> list of finding specs. member_idx are indices into that persona's
# own spectra list (which are ordered published-first). Only published
# spectra may back a published finding — enforced below.
FINDINGS: dict[str, list[dict]] = {
    "dev-nanda": [
        {
            "title": "Reproducible SERS enhancement factors on Ag colloid",
            "abstract": "A protocol for reporting SERS enhancement factors that survives "
            "re-analysis: fixed analyte, fixed laser, ledger-pinned baseline.",
            "tags": ["sers", "protocol", "silver"],
            "state": "published",
            "doi": "10.5281/zenodo.7742100",
            "repo_url": "https://github.com/dev-nanda/sers-ef",
            "members": [(0, "Ag colloid, R6G 1 µM"), (1, "Ag colloid, R6G 100 nM")],
            "entries": [
                ("note", "Enhancement factor computed against the neat-analyte reference."),
                ("peaks", "Ring-breathing and C–C stretch bands used for the ratio."),
            ],
        },
        {
            "title": "Draft: substrate-to-substrate variability",
            "abstract": "Working notes.",
            "tags": ["sers", "reproducibility"],
            "state": "draft",
            "members": [],
            "entries": [("note", "Collecting replicates before writing this up.")],
        },
        {
            "title": "Draft: laser-line comparison 532 vs 633 vs 785",
            "abstract": "Which line to pick for this analyte.",
            "tags": ["sers", "instrumentation"],
            "state": "draft",
            "members": [],
            "entries": [("note", "Outline only.")],
        },
    ],
    "lena-fischer": [
        {
            "title": "Discriminating three acetaminophen polymorphs by Raman",
            "abstract": "Forms I–III are separable on the 200–900 cm⁻¹ lattice-mode region "
            "without chemometrics; a single ratio suffices.",
            "tags": ["polymorphs", "pharmaceutical", "quantitative"],
            "state": "published",
            "doi": "10.1021/acs.cgd.6b00001",
            "repo_url": "https://github.com/lfischer/apap-polymorphs",
            "members": [(0, "Form I (control)"), (1, "Form II"), (2, "Form III, 24 h")],
            "entries": [
                ("note", "Lattice-mode region is diagnostic; see the overlay."),
                ("figure", "Overlay of the three forms, offset for clarity."),
                ("peaks", "Marker bands at 329 and 465 cm⁻¹."),
            ],
        },
    ],
    "priya-rao": [
        {
            "title": "Layer-number calibration for CVD graphene",
            "abstract": "2D-band shape and I(2D)/I(G) vs layer count on our transfer stack.",
            "tags": ["graphene", "2d-materials", "calibration"],
            "state": "embargoed",
            "members": [(3, "monolayer"), (4, "bilayer")],
            "entries": [
                ("note", "Embargoed until the companion paper is out."),
                ("figure", "2D band vs layer number."),
            ],
        },
        {
            "title": "Draft: strain mapping across a wrinkle",
            "abstract": "Notes.",
            "tags": ["graphene", "strain"],
            "state": "draft",
            "members": [],
            "entries": [("note", "Need to re-acquire the map.")],
        },
    ],
    "aisha-bello": [
        {
            "title": "Polymer types in Lagos Lagoon surface microplastics",
            "abstract": "PET and polyethylene dominate the >300 µm fraction; a PCA on "
            "baseline-corrected spectra separates the classes cleanly.",
            "tags": ["microplastics", "pca", "environmental"],
            "state": "published",
            "doi": "10.1016/j.marpolbul.2025.100001",
            "repo_url": "https://github.com/aisha-bello/lagoon-microplastics",
            "members": [(0, "particle 12 (PET)"), (1, "particle 27 (PE)"), (2, "particle 31 (PET)")],
            "entries": [
                ("note", "Spectra baseline-corrected with a pinned airPLS ledger."),
                ("pca", "First two PCs on the 600–1800 cm⁻¹ window."),
                ("figure", "PC1–PC2 scores coloured by polymer type."),
            ],
        },
    ],
    "noah-kim": [
        {
            "title": "Draft: cathode surface reconstruction after 200 cycles",
            "abstract": "Tracking the disorder band growth.",
            "tags": ["batteries", "in-situ"],
            "state": "draft",
            "members": [],
            "entries": [
                ("note", "Figures below are from the cycled cell."),
                ("figure", "Pristine vs cycled, normalised."),
                ("peaks", "Disorder band area vs cycle count."),
            ],
        },
    ],
    "hana-sato": [
        {
            "title": "Amide I band decomposition for β-sheet content",
            "abstract": "A fixed four-Gaussian model on the Amide I envelope gives "
            "β-sheet fractions consistent with the CD reference.",
            "tags": ["protein", "amide-i", "uvrr"],
            "state": "published",
            "doi": "10.1002/jrs.6100",
            "repo_url": "https://github.com/hsato/amide1-fit",
            "members": [(0, "lysozyme, native"), (1, "lysozyme, thermally stressed")],
            "entries": [
                ("note", "Fit window 1600–1700 cm⁻¹, linear baseline."),
                ("figure", "Component fit for the native sample."),
            ],
        },
    ],
    "kwame-mensah": [
        {
            "title": "Draft: fat-bloom detection on stored cocoa",
            "abstract": "Notes.",
            "tags": ["food", "cocoa"],
            "state": "draft",
            "members": [],
            "entries": [("note", "Collecting a bigger reference set first.")],
        },
    ],
    "olivia-brown": [
        {
            "title": "Field-portable Raman for topsoil organic carbon",
            "abstract": "A 1064 nm handheld instrument plus a pinned preprocessing "
            "routine predicts SOC within survey tolerance.",
            "tags": ["soil-carbon", "chemometrics", "field"],
            "state": "published",
            "doi": "10.1111/ejss.13100",
            "repo_url": "https://github.com/obrown/soc-raman",
            "members": [(0, "site A, 0–10 cm"), (1, "site B, 0–10 cm"), (2, "site C, 0–10 cm")],
            "entries": [
                ("note", "All spectra share the 'Field SOC v2' routine."),
                ("figure", "Predicted vs measured SOC."),
            ],
        },
        {
            "title": "Draft: instrument drift over a field season",
            "abstract": "Notes.",
            "tags": ["soil-carbon", "qa"],
            "state": "draft",
            "members": [],
            "entries": [("note", "Waiting on the end-of-season standards.")],
        },
        {
            "title": "Embargoed: cross-site transfer of the SOC model",
            "abstract": "Held until the dataset DOI mints.",
            "tags": ["soil-carbon", "transfer"],
            "state": "embargoed",
            "members": [(6, "holdout site")],
            "entries": [("note", "Embargo lifts with the data release.")],
        },
    ],
    "viktor-petrov": [
        {
            "title": "Standoff Raman signatures at 5 m",
            "abstract": "Held pending review.",
            "tags": ["standoff", "detection"],
            "state": "embargoed",
            "members": [(0, "sample 1")],
            "entries": [("note", "Embargoed.")],
        },
    ],
    "mei-lin": [
        {
            "title": "Tracking MAPbI₃ degradation to PbI₂ by Raman",
            "abstract": "The 94 cm⁻¹ PbI₂ mode grows in monotonically with humidity "
            "exposure; a PCA on the low-frequency window orders the time series.",
            "tags": ["perovskite", "degradation", "pca"],
            "state": "published",
            "doi": "10.1021/acsenergylett.5b00010",
            "repo_url": "https://github.com/mei-lin/mapbi3-aging",
            "members": [(0, "0 h"), (1, "48 h"), (2, "168 h")],
            "entries": [
                ("note", "Low-frequency window is the informative one."),
                ("pca", "PC1 tracks exposure time."),
                ("figure", "Score trajectory vs exposure."),
            ],
        },
    ],
    "carlos-ruiz": [
        {
            "title": "Methanol screening in mezcal by Raman",
            "abstract": "A partial-least-squares model on the C–O stretch region flags "
            "out-of-spec methanol without sample prep.",
            "tags": ["spirits", "authentication", "pls"],
            "state": "published",
            "members": [(0, "reference blend"), (1, "flagged sample")],
            "entries": [("note", "No DOI yet — manuscript in prep.")],
        },
    ],
    "fatima-zahra": [
        {
            "title": "Draft: carbonate substitution in sedimentary apatite",
            "abstract": "ν₁ phosphate shift vs carbonate content.",
            "tags": ["apatite", "phosphate"],
            "state": "draft",
            "members": [],
            "entries": [("note", "Need the XRD cross-check before publishing.")],
        },
    ],
    "james-cole": [
        {
            "title": "Photo-oxidation markers in weathered polypropylene",
            "abstract": "Carbonyl and hydroxyl growth vs UV dose, with an isosbestic "
            "point that anchors the normalisation.",
            "tags": ["polymer", "ageing", "photo-oxidation"],
            "state": "published",
            "doi": "10.1016/j.polymdegradstab.2025.100002",
            "members": [(0, "0 kWh/m²"), (1, "120 kWh/m²")],
            "entries": [
                ("note", "Normalised at the isosbestic point."),
                ("figure", "Carbonyl index vs dose."),
            ],
        },
        {
            "title": "Fading of a cadmium-yellow oil paint under light",
            "abstract": "Raman plus reflectance tracks the CdS → CdSO₄ pathway.",
            "tags": ["heritage", "pigments", "ageing"],
            "state": "published",
            "members": [(2, "unaged"), (3, "aged 500 h")],
            "entries": [("note", "Companion to the pigment reference set.")],
        },
    ],
    "nadia-haddad": [
        {
            "title": "Serum SERS classifier for early-stage disease screening",
            "abstract": "A gradient-boosted classifier on drop-coating-deposition SERS "
            "spectra reaches AUC 0.91 on a held-out cohort; full pipeline released.",
            "tags": ["serum", "sers", "machine-learning", "diagnostics"],
            "state": "published",
            "doi": "10.1039/D5AN00010A",
            "repo_url": "https://github.com/nhaddad/serum-sers-clf",
            "members": [(0, "case, DCD-SERS"), (1, "control, DCD-SERS"), (2, "case, replicate")],
            "entries": [
                ("note", "Spectra baseline-corrected and vector-normalised via a pinned ledger."),
                ("pca", "Unsupervised view of the two classes."),
                ("figure", "ROC curve for the held-out cohort."),
            ],
        },
        {
            "title": "Embargoed: external validation on a second site",
            "abstract": "Held until the multi-site paper is accepted.",
            "tags": ["serum", "validation"],
            "state": "embargoed",
            "members": [(6, "site-2 case")],
            "entries": [("note", "Embargo lifts on acceptance.")],
        },
    ],
}


# --------------------------------------------------------------------- helpers


def _require_reference_data(session) -> None:
    from app.models.license import License

    if session.get(License, "CC-BY-4.0") is None:
        raise SystemExit("Reference data missing (no CC-BY-4.0 license). Run `make seed` first.")


def _get_or_create_user(session, p: Persona) -> User:
    email = f"{p['handle']}@{EMAIL_DOMAIN}"
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is not None:
        return user
    user = User(
        google_sub=f"scenario-seed:{p['handle']}",
        email=email,
        display_name=p["name"],
        profile_handle=None if p["guest"] else p["handle"],
        bio=p["scenario"] if not p["guest"] else None,
        affiliation=p["aff"] or None,
        research_interests=p["interests"] or None,
        is_profile_public=not p["guest"],
        is_guest=p["guest"],
        onboarded_at=NOW if p["onboarded"] else None,
    )
    session.add(user)
    session.flush()
    return user


def _state_for(
    index: int, published: int, embargoed: int
) -> tuple[SpectrumState, datetime | None, datetime | None]:
    """Spectra are ordered published-first, then embargoed, then draft."""
    if index < published:
        return SpectrumState.published, NOW - timedelta(days=30 - index), None
    if index < published + embargoed:
        return SpectrumState.embargoed, None, NOW + timedelta(days=45)
    return SpectrumState.draft, None, None


def _make_spectrum(session, owner: User, p: Persona, index: int) -> Spectrum:
    material, peaks, organic = MATERIALS[(p["mat"] + index) % len(MATERIALS)]
    laser = p["lasers"][index % len(p["lasers"])]
    seed = 20260819 + hash((p["handle"], index)) % 100_000
    spikes = [(300 + index * 7, 700.0), (900, 500.0)] if index % 4 == 0 else []
    x, y = synthesize_spectrum(
        peaks,
        fluorescence=450.0 if organic else 40.0,
        noise=2.0 + (index % 3),
        spikes=spikes,
        seed=seed,
    )
    title = f"{material.title()} — {p['handle'].split('-')[0]} #{index + 1:02d}"
    payload = to_horiba_ascii(x, y, title=title, laser_nm=laser, acq_time_s=10.0, accumulations=2)
    content_hash = hashlib.sha256(payload).hexdigest()
    filename = f"{material.replace(' ', '_')}_{laser}nm_{index + 1:02d}.txt"
    storage_key = f"{owner.id}/{content_hash}/{filename}"
    upload_bytes(settings.S3_BUCKET_RAW, storage_key, payload, content_type="text/plain")

    raw_file = RawFile(
        owner_id=owner.id,
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

    state, published_at, embargo_release_at = _state_for(index, *p["pub"])
    spectrum = Spectrum(
        raw_file_id=raw_file.id,
        owner_id=owner.id,
        accession=next_spectrum_accession(session),
        modality=Modality.raman,
        title=title,
        description=f"Synthetic {material} spectrum for the '{p['handle']}' scenario.",
        confirmed_metadata={
            "laser_wavelength_nm": laser,
            "integration_time_ms": 10_000,
            "accumulations": 2,
            "instrument_vendor": "Horiba",
            "instrument_model": "iHR320",
            "spectral_range_cm1": f"{x.min():.0f}-{x.max():.0f}",
        },
        material_type=material,
        excitation_wavelength_nm=float(laser),
        snr=float(compute_snr(y)),
        license_id="CC-BY-4.0",
        state=state,
        published_at=published_at,
        embargo_release_at=embargo_release_at,
    )
    session.add(spectrum)
    session.flush()
    return spectrum


# A safe, no-required-params pipeline the synthetic curves survive.
LEDGER_PIPELINE = [
    {"type": "raman.despike", "params": {}, "order": 0},
    {"type": "raman.baseline.als", "params": {}, "order": 1},
    {"type": "raman.snv", "params": {}, "order": 2},
]


def _apply_ledger(session, owner: User, spectrum: Spectrum) -> None:
    from app.processing.cache import get_or_compute
    from app.routers.ledgers import LedgerStepIn, build_and_persist_ledger

    raw_file = session.get(RawFile, spectrum.raw_file_id)
    steps_in = [LedgerStepIn(**s) for s in LEDGER_PIPELINE]
    ledger_row, ledger_pydantic, _reused = build_and_persist_ledger(
        raw_file, steps_in, session, owner
    )
    get_or_compute(raw_file.id, ledger_pydantic, session)
    spectrum.current_ledger_id = ledger_row.id
    session.add(spectrum)
    session.flush()


def _make_routine(session, owner: User, name: str, description: str) -> None:
    session.add(
        ProcessingRoutine(
            owner_id=owner.id,
            modality=Modality.raman,
            name=name,
            description=description,
            steps_template=LEDGER_PIPELINE,
        )
    )


def _make_dataset(
    session, owner: User, name: str, description: str, spectra: list[Spectrum]
) -> AnalysisDataset:
    dataset = AnalysisDataset(
        owner_id=owner.id, modality=Modality.raman, name=name, description=description
    )
    session.add(dataset)
    session.flush()
    for position, spectrum in enumerate(spectra):
        session.add(
            AnalysisDatasetSpectrum(
                dataset_id=dataset.id, spectrum_id=spectrum.id, position=position
            )
        )
    session.flush()
    return dataset


def _verify_doi_for_spectrum(session, spectrum: Spectrum, doi: str) -> None:
    snapshot = {"doi": doi, "title": spectrum.title, "provider": "crossref", "resolved": True}
    pub = session.execute(select(Publication).where(Publication.doi == doi)).scalar_one_or_none()
    if pub is None:
        pub = Publication(
            doi=doi,
            provider="crossref",
            verification_status="verified",
            snapshot=snapshot,
            verified_at=NOW,
        )
        session.add(pub)
        session.flush()
    session.add(
        PublicationSnapshot(
            spectrum_id=spectrum.id,
            doi=doi,
            provider="crossref",
            verification_status="verified",
            snapshot=snapshot,
            verified_at=NOW,
        )
    )
    spectrum.doi = doi
    spectrum.publication_id = pub.id
    session.add(spectrum)
    session.flush()


def _make_finding(session, owner: User, spec: dict, own_spectra: list[Spectrum]) -> Finding:
    state = {
        "draft": FindingState.draft,
        "published": FindingState.published,
        "embargoed": FindingState.published,  # findings have no embargo state; keep the write-up public
    }[spec["state"]]
    finding = Finding(
        accession=next_finding_accession(session),
        owner_id=owner.id,
        title=spec["title"],
        abstract_md=spec["abstract"],
        tags=spec.get("tags"),
        state=state,
        license_id="CC-BY-4.0" if state == FindingState.published else None,
        doi=spec.get("doi"),
        repo_url=spec.get("repo_url"),
        published_at=NOW if state == FindingState.published else None,
    )
    session.add(finding)
    session.flush()

    for position, (member_idx, label) in enumerate(spec.get("members", [])):
        if member_idx >= len(own_spectra):
            continue
        member = own_spectra[member_idx]
        # A published finding may not reference private data.
        if state == FindingState.published and member.state != SpectrumState.published:
            continue
        session.add(
            FindingSpectrum(
                finding_id=finding.id, spectrum_id=member.id, position=position, label=label
            )
        )

    for position, (kind, body) in enumerate(spec.get("entries", [])):
        session.add(
            FindingEntry(
                finding_id=finding.id,
                author_id=owner.id,
                position=position,
                kind=FindingEntryKind(kind),
                body_md=body,
                config={"note": "synthetic seed entry"} if kind in {"pca", "peaks"} else None,
            )
        )
    session.flush()
    return finding


def _follow(session, follower: User, followee: User) -> None:
    if follower.id == followee.id:
        return
    exists = session.execute(
        select(Follow).where(Follow.follower_id == follower.id, Follow.followee_id == followee.id)
    ).scalar_one_or_none()
    if exists is None:
        session.add(Follow(follower_id=follower.id, followee_id=followee.id))


def _comment_finding(
    session, user: User, finding: Finding, body: str, parent: Comment | None = None
) -> Comment:
    comment = Comment(
        finding_id=finding.id,
        user_id=user.id,
        body=body,
        parent_id=parent.id if parent else None,
    )
    session.add(comment)
    session.flush()
    return comment


def _share_finding(session, user: User, finding: Finding, note: str | None = None) -> None:
    exists = session.execute(
        select(Share).where(Share.finding_id == finding.id, Share.user_id == user.id)
    ).scalar_one_or_none()
    if exists is None:
        session.add(Share(finding_id=finding.id, user_id=user.id, comment=note))


def _pin(
    session,
    user: User,
    *,
    spectrum: Spectrum | None = None,
    finding: Finding | None = None,
    position: int = 0,
) -> None:
    session.add(
        Pin(
            user_id=user.id,
            spectrum_id=spectrum.id if spectrum else None,
            finding_id=finding.id if finding else None,
            position=position,
        )
    )


# --------------------------------------------------------------------- build


def _build_content(
    session, users: dict[str, User], spectra: dict[str, list[Spectrum]]
) -> dict[str, list[Finding]]:
    findings: dict[str, list[Finding]] = {}

    for p in PERSONAS:
        handle = p["handle"]
        owner = users[handle]
        if p["n"] == 0:
            continue
        if session.execute(
            select(Spectrum.id).where(Spectrum.owner_id == owner.id).limit(1)
        ).first():
            # Persona already has data — resume, don't duplicate.
            spectra[handle] = list(
                session.execute(
                    select(Spectrum)
                    .where(Spectrum.owner_id == owner.id)
                    .order_by(Spectrum.created_at)
                ).scalars()
            )
            continue

        own = [_make_spectrum(session, owner, p, i) for i in range(p["n"])]
        spectra[handle] = own
        print(f"  {handle}: {len(own)} spectra")

        # Processing ledgers on a slice of each active persona's library.
        for spectrum in own[: min(3, len(own))]:
            try:
                _apply_ledger(session, owner, spectrum)
            except Exception as exc:  # noqa: BLE001 — best-effort in a seed
                print(f"    ledger skipped for {spectrum.accession}: {exc}")

    # Saved routines.
    for handle, name, desc in [
        ("tomasz-wojcik", "Despike → ALS → SNV", "My default for spike-heavy field data."),
        ("olivia-brown", "Field SOC v1", "First-pass survey preprocessing."),
        ("olivia-brown", "Field SOC v2", "Current survey preprocessing (pinned)."),
        ("olivia-brown", "QA reference", "Used only on the daily standard."),
        ("dev-nanda", "airPLS → SNV", "SERS baseline + normalisation."),
    ]:
        _make_routine(session, users[handle], name, desc)

    # Datasets.
    for handle, name, desc, sl in [
        ("lena-fischer", "APAP Form I/II/III", "Polymorph screening inputs.", slice(0, 9)),
        ("aisha-bello", "Lagos Lagoon microplastics", "Sorted particle spectra.", slice(0, 12)),
        ("olivia-brown", "Topsoil survey 2026", "0–10 cm cores, all sites.", slice(0, 12)),
        ("olivia-brown", "Instrument standards", "Daily QA acquisitions.", slice(12, 18)),
        ("mei-lin", "MAPbI3 aging series", "Humidity-exposure time points.", slice(0, 9)),
        ("nadia-haddad", "Serum SERS cohort A", "Discovery cohort, DCD-SERS.", slice(0, 12)),
        ("kwame-mensah", "Cocoa reference set", "Graded bean spectra.", slice(0, 9)),
        ("dev-nanda", "R6G laser-line set", "Same analyte, three lasers.", slice(0, 12)),
        ("dev-nanda", "SERS substrate replicates", "Batch-to-batch check.", slice(12, 18)),
    ]:
        members = spectra.get(handle, [])[sl]
        if members:
            _make_dataset(session, users[handle], name, desc, members)

    # Spectrum-level DOIs on a couple of published references.
    for handle, idx, doi in [
        ("elena-costa", 0, "10.1016/j.culher.2024.01.001"),
        ("elena-costa", 1, "10.1016/j.culher.2024.01.002"),
        ("sam-carter", 0, "10.5281/zenodo.9000001"),
        ("dev-nanda", 0, "10.5281/zenodo.7742101"),
    ]:
        specs = spectra.get(handle, [])
        if idx < len(specs) and specs[idx].state == SpectrumState.published:
            _verify_doi_for_spectrum(session, specs[idx], doi)

    # Findings.
    for handle, specs in FINDINGS.items():
        owner = users[handle]
        if session.execute(select(Finding.id).where(Finding.owner_id == owner.id).limit(1)).first():
            findings[handle] = list(
                session.execute(select(Finding).where(Finding.owner_id == owner.id)).scalars()
            )
            continue
        made = [_make_finding(session, owner, spec, spectra.get(handle, [])) for spec in specs]
        findings[handle] = made
        print(f"  {handle}: {len(made)} findings")

    # Pins — Elena curates 4, a few others pin their headline finding.
    elena_specs = [s for s in spectra.get("elena-costa", []) if s.state == SpectrumState.published]
    for position, spectrum in enumerate(elena_specs[:4]):
        _pin(session, users["elena-costa"], spectrum=spectrum, position=position)
    for handle in ["dev-nanda", "aisha-bello", "olivia-brown", "nadia-haddad", "mei-lin"]:
        pub_findings = [f for f in findings.get(handle, []) if f.state == FindingState.published]
        if pub_findings:
            _pin(session, users[handle], finding=pub_findings[0], position=0)

    session.flush()
    return findings


def _build_graph(session, users: dict[str, User], findings: dict[str, list[Finding]]) -> None:
    order = [p["handle"] for p in PERSONAS]
    hubs = ["dev-nanda", "olivia-brown"]

    # Each onboarded non-guest persona follows the next 4 (wrap-around) plus
    # the two hubs. raj-patel follows widely; mara/casey follow nobody.
    for i, handle in enumerate(order):
        if handle in {"mara-okeefe", "casey-guest"}:
            continue
        follower = users[handle]
        targets = {order[(i + k) % len(order)] for k in (1, 2, 3, 4)} | set(hubs)
        if handle == "raj-patel":
            targets |= set(order[2:14])
        for t in targets:
            if t not in {"mara-okeefe", "casey-guest"}:
                _follow(session, follower, users[t])

    published = [
        (h, f) for h, fs in findings.items() for f in fs if f.state == FindingState.published
    ]

    # Votes: rotate a set of voters across every published finding; pile
    # extra onto a few headline ones. Dedupe in Python — pending adds aren't
    # visible to the existence SELECT inside `_vote_finding`.
    voters = [users[h] for h in order if h != "casey-guest"]
    seen_votes: set[tuple] = set()

    def _cast(v: User, f: Finding) -> None:
        key = (f.id, v.id)
        if v.id == f.owner_id or key in seen_votes:
            return
        seen_votes.add(key)
        session.add(Vote(finding_id=f.id, user_id=v.id))

    for n, (_h, finding) in enumerate(published):
        for k in range(5):
            _cast(voters[(n + k) % len(voters)], finding)
    for handle in ["nadia-haddad", "aisha-bello", "olivia-brown", "mei-lin"]:
        for f in findings.get(handle, []):
            if f.state == FindingState.published:
                for v in voters[:12]:
                    _cast(v, f)

    # Comment threads on the headline findings, with one-level replies.
    def first_pub(handle: str) -> Finding | None:
        return next(
            (f for f in findings.get(handle, []) if f.state == FindingState.published), None
        )

    scripts = [
        (
            "aisha-bello",
            "sam-carter",
            "Did you try normalising at the isosbestic point instead of SNV?",
            "james-cole",
            "The isosbestic anchor is cleaner for weathered polymers, agreed.",
        ),
        (
            "nadia-haddad",
            "dev-nanda",
            "AUC 0.91 on a held-out cohort is strong — how big was it?",
            "raj-patel",
            "Seconding this, would love the cohort size in the abstract.",
        ),
        (
            "mei-lin",
            "priya-rao",
            "Does the 94 cm⁻¹ mode saturate at long exposure?",
            "james-cole",
            "We saw the same plateau in PP photo-oxidation.",
        ),
        (
            "olivia-brown",
            "kwame-mensah",
            "Which handheld model? Considering one for cocoa fieldwork.",
            "carlos-ruiz",
            "Same question for agave — portability matters a lot here.",
        ),
        (
            "hana-sato",
            "nadia-haddad",
            "Four Gaussians on Amide I — fixed centres or free?",
            "dev-nanda",
            "Fixed centres tend to be more reproducible across instruments.",
        ),
        (
            "lena-fischer",
            "elena-costa",
            "The lattice-mode ratio is a nice single-number readout.",
            "fatima-zahra",
            "Trying something similar on apatite carbonate substitution.",
        ),
    ]
    for owner_h, c1_h, c1_body, c2_h, c2_body in scripts:
        finding = first_pub(owner_h)
        if finding is None:
            continue
        top = _comment_finding(session, users[c1_h], finding, c1_body)
        _comment_finding(session, users[c2_h], finding, c2_body, parent=top)
        _comment_finding(
            session, users[owner_h], finding, "Thanks — added detail to the thread.", parent=top
        )

    # Shares, a few with quote text.
    for handle, note in [
        ("raj-patel", "Great example of releasing the whole pipeline, not just the plots."),
        ("sam-carter", None),
        ("james-cole", "Relevant to anyone doing polymer ageing."),
        ("dev-nanda", None),
        ("carlos-ruiz", None),
    ]:
        f = first_pub("nadia-haddad")
        if f:
            _share_finding(session, users[handle], f, note)
    for handle in ["priya-rao", "noah-kim", "hana-sato"]:
        f = first_pub("mei-lin")
        if f:
            _share_finding(session, users[handle], f)

    session.flush()


def _build_community(session, users: dict[str, User], spectra: dict[str, list[Spectrum]]) -> None:
    if session.execute(select(CommunityPost.id).limit(1)).first():
        return

    carlos_pub = [s for s in spectra.get("carlos-ruiz", []) if s.state == SpectrumState.published]
    dataset_post = CommunityPost(
        owner_id=users["carlos-ruiz"].id,
        kind="dataset",
        title="Open reference set: 40 authenticated mezcal Raman spectra",
        body="Baseline-corrected, CC-BY. Feedback on the preprocessing welcome.",
    )
    session.add(dataset_post)
    session.flush()
    for spectrum in carlos_pub[:3]:
        session.add(CommunityPostSpectrum(post_id=dataset_post.id, spectrum_id=spectrum.id))

    announce = CommunityPost(
        owner_id=users["olivia-brown"].id,
        kind="announcement",
        title="Field SOC v2 routine is now the group default",
        body="Swaps the polynomial baseline for airPLS; re-run your survey spectra.",
    )
    session.add(announce)
    announce2 = CommunityPost(
        owner_id=users["james-cole"].id,
        kind="announcement",
        title="Polymer-ageing thread — contributors welcome",
        body="Collecting weathered-polymer spectra across labs for a shared benchmark.",
    )
    session.add(announce2)
    session.flush()

    reactors = [
        "dev-nanda",
        "aisha-bello",
        "nadia-haddad",
        "raj-patel",
        "kwame-mensah",
        "priya-rao",
    ]
    for post in (dataset_post, announce, announce2):
        for handle in reactors:
            session.add(PostReaction(post_id=post.id, user_id=users[handle].id))
        session.add(
            Comment(post_id=post.id, user_id=users["raj-patel"].id, body="Thanks for sharing this.")
        )
    session.flush()


def run(reset: bool = False) -> None:
    session = SessionLocal()
    try:
        if reset:
            _wipe(session)
            session.commit()
            print("Reset: scenario personas removed.")
            return

        _require_reference_data(session)

        marker = session.execute(
            select(User).where(User.profile_handle == MARKER_HANDLE)
        ).scalar_one_or_none()
        if (
            marker is not None
            and session.execute(
                select(Finding.id).where(Finding.owner_id == marker.id).limit(1)
            ).first()
        ):
            print("Scenario data already seeded (nadia-haddad has findings) — nothing to do.")
            return

        print("Seeding 20 scenario personas…")
        users = {p["handle"]: _get_or_create_user(session, p) for p in PERSONAS}
        session.flush()

        spectra: dict[str, list[Spectrum]] = {}
        findings = _build_content(session, users, spectra)
        _build_graph(session, users, findings)
        _build_community(session, users, spectra)

        session.commit()
        print(
            f"Done. {len(users)} personas, "
            f"{sum(len(v) for v in spectra.values())} spectra, "
            f"{sum(len(v) for v in findings.values())} findings, plus the social graph.\n"
            "Log in as any persona:  GET /auth/dev-login?email=<handle>@" + EMAIL_DOMAIN
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _wipe(session) -> None:
    """Best-effort teardown of everything the personas own, in FK order."""
    from app.models.ingestion_job import IngestionJob
    from app.models.processed_cache import ProcessedCache
    from app.models.processing_ledger import ProcessingLedger

    ids = [
        u.id
        for u in session.execute(select(User).where(User.email.like(f"%@{EMAIL_DOMAIN}"))).scalars()
    ]
    if not ids:
        return
    finding_ids = [
        f.id for f in session.execute(select(Finding).where(Finding.owner_id.in_(ids))).scalars()
    ]
    spectrum_ids = [
        s.id for s in session.execute(select(Spectrum).where(Spectrum.owner_id.in_(ids))).scalars()
    ]
    raw_ids = [
        r.id for r in session.execute(select(RawFile).where(RawFile.owner_id.in_(ids))).scalars()
    ]

    def _del(model, column, values) -> None:
        if values:
            session.query(model).filter(column.in_(values)).delete(synchronize_session=False)

    # Break the spectra -> processing_ledgers FK before dropping ledgers.
    if spectrum_ids:
        session.query(Spectrum).filter(Spectrum.owner_id.in_(ids)).update(
            {Spectrum.current_ledger_id: None}, synchronize_session=False
        )

    _del(PostReaction, PostReaction.user_id, ids)
    _del(Comment, Comment.user_id, ids)
    _del(Comment, Comment.finding_id, finding_ids)
    _del(CommunityPostSpectrum, CommunityPostSpectrum.spectrum_id, spectrum_ids)
    _del(CommunityPost, CommunityPost.owner_id, ids)
    _del(Share, Share.user_id, ids)
    _del(Vote, Vote.user_id, ids)
    _del(Vote, Vote.finding_id, finding_ids)
    _del(Pin, Pin.user_id, ids)
    session.query(Follow).filter(Follow.follower_id.in_(ids) | Follow.followee_id.in_(ids)).delete(
        synchronize_session=False
    )
    _del(FindingEntry, FindingEntry.finding_id, finding_ids)
    _del(FindingSpectrum, FindingSpectrum.finding_id, finding_ids)
    _del(Finding, Finding.owner_id, ids)
    _del(AnalysisDatasetSpectrum, AnalysisDatasetSpectrum.spectrum_id, spectrum_ids)
    _del(AnalysisDataset, AnalysisDataset.owner_id, ids)
    _del(PublicationSnapshot, PublicationSnapshot.spectrum_id, spectrum_ids)
    _del(ProcessedCache, ProcessedCache.raw_file_id, raw_ids)
    _del(ProcessingLedger, ProcessingLedger.raw_file_id, raw_ids)
    _del(ProcessingRoutine, ProcessingRoutine.owner_id, ids)
    _del(Spectrum, Spectrum.owner_id, ids)
    _del(IngestionJob, IngestionJob.raw_file_id, raw_ids)
    _del(RawFile, RawFile.owner_id, ids)
    _del(User, User.id, ids)


if __name__ == "__main__":
    run(reset="--reset" in sys.argv)
