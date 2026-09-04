"""The public reference library: browse, match, deconvolve, contribute, moderate.

Builds its own TestClient rather than extending `tests/conftest.py`, mirroring
`tests/test_search.py`'s stated convention so this file has no edit-conflict
surface with the shared fixture module.
"""
from __future__ import annotations

import numpy as np
import pytest

from app.discovery.peak_index import get_or_build_peak_index
from app.discovery.raman_similarity import get_or_build_feature
from app.models.enums import ReferenceCurationStatus, ReferenceTrustTier
from app.models.reference import ReferenceEntry
from app.models.spectrum import Spectrum


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def spectrum_bytes(peaks: list[tuple[float, float]], *, noise: float = 0.0, seed: int = 0) -> bytes:
    """A two-column Raman file with Gaussian bands at the given positions."""
    x = np.linspace(200.0, 1800.0, 800)
    y = np.zeros_like(x)
    for centre, amplitude in peaks:
        y = y + amplitude * np.exp(-0.5 * ((x - centre) / 10.0) ** 2)
    if noise:
        y = y + np.random.default_rng(seed).normal(0, noise, x.size)
    return "\n".join(f"{a:.4f} {b:.6f}" for a, b in zip(x, y)).encode()


@pytest.fixture()
def client(db_session):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from app.auth.deps import (
        get_current_full_user,
        get_current_moderator,
        get_current_user,
        get_current_user_optional,
    )
    from app.db.session import get_db
    from app.routers import reference_library, search, spectra

    test_app = FastAPI()
    test_app.include_router(spectra.router)
    test_app.include_router(search.router)
    test_app.include_router(reference_library.router)

    def _override_get_db():
        yield db_session

    current: dict = {"user": None, "moderator": False}

    def _require():
        if current["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current["user"]

    def _require_moderator():
        user = _require()
        if not current["moderator"]:
            raise HTTPException(status_code=403, detail="Moderator only")
        return user

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_current_user] = _require
    test_app.dependency_overrides[get_current_full_user] = _require
    test_app.dependency_overrides[get_current_moderator] = _require_moderator
    test_app.dependency_overrides[get_current_user_optional] = lambda: current["user"]

    c = TestClient(test_app)
    c.set_current_user = lambda user: current.__setitem__("user", user)
    c.set_moderator = lambda flag: current.__setitem__("moderator", flag)
    return c


def publish_spectrum(client, owner, make_raw_file, content: bytes) -> dict:
    client.set_current_user(owner)
    raw_file = make_raw_file(owner, content=content)
    resp = client.post("/spectra", json={"raw_file_id": str(raw_file.id)})
    assert resp.status_code == 201, resp.text
    spectrum = resp.json()
    resp = client.post(
        f"/spectra/{spectrum['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def make_reference(
    db_session,
    spectrum_id,
    *,
    name: str,
    tier: ReferenceTrustTier = ReferenceTrustTier.curated,
    source: str = "rruff",
    source_id: str | None = None,
    formula: str | None = None,
    common_names: list[str] | None = None,
) -> ReferenceEntry:
    entry = ReferenceEntry(
        spectrum_id=spectrum_id,
        compound_name=name,
        chemical_formula=formula,
        common_names=common_names or [],
        source=source,
        source_id=source_id or f"X{name}",
        source_dataset="test-set",
        trust_tier=tier,
        curation_status=ReferenceCurationStatus.approved,
    )
    db_session.add(entry)
    db_session.commit()
    db_session.refresh(entry)

    # Warm both indexes, exactly as the seeder and the contribute endpoint do.
    # A reference with no peak row is invisible to the prefilter — which is
    # correct behaviour (the background worker builds them), but it means a
    # test that inserts rows directly has to do the warming itself.
    spectrum = db_session.get(Spectrum, spectrum_id)
    get_or_build_feature(spectrum, db_session)
    get_or_build_peak_index(spectrum, db_session)
    db_session.commit()
    return entry


def seed_reference(client, db_session, owner, make_raw_file, *, name, peaks, **kw):
    published = publish_spectrum(client, owner, make_raw_file, spectrum_bytes(peaks))
    entry = make_reference(db_session, published["id"], name=name, **kw)
    return published, entry


# ---------------------------------------------------------------------------
# matching
# ---------------------------------------------------------------------------


def test_an_exact_copy_of_a_reference_is_the_top_match(
    client, db_session, make_user, make_raw_file
):
    owner = make_user()
    bands = [(500.0, 100.0), (1200.0, 60.0)]
    _ref_spectrum, entry = seed_reference(
        client, db_session, owner, make_raw_file, name="Calcite", peaks=bands
    )
    query = publish_spectrum(client, owner, make_raw_file, spectrum_bytes(bands))

    resp = client.post("/v1/library/match", json={"spectrum_id": query["id"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["matches"], "an identical reference must be found"
    top = body["matches"][0]
    assert top["reference"]["compound_name"] == "Calcite"
    assert top["similarity"] > 0.99
    assert body["mixture_suspected"] is False
    assert str(entry.id) == top["reference"]["id"]


def test_query_peaks_come_from_the_server_not_the_client(
    client, db_session, make_user, make_raw_file
):
    """`client_peaks_cm1` is advisory: it may widen the net, never define it."""
    owner = make_user()
    bands = [(500.0, 100.0), (1200.0, 60.0)]
    seed_reference(client, db_session, owner, make_raw_file, name="Calcite", peaks=bands)
    query = publish_spectrum(client, owner, make_raw_file, spectrum_bytes(bands))

    honest = client.post("/v1/library/match", json={"spectrum_id": query["id"]}).json()
    lying = client.post(
        "/v1/library/match",
        json={"spectrum_id": query["id"], "client_peaks_cm1": [111.0, 222.0, 333.0]},
    ).json()

    assert [p["cm1"] for p in lying["query_peaks"]] == [
        p["cm1"] for p in honest["query_peaks"]
    ]


def test_a_curated_entry_outranks_an_identical_community_one(
    client, db_session, make_user, make_raw_file
):
    """At equal similarity an unvetted submission must not displace a standard."""
    owner = make_user()
    bands = [(700.0, 100.0), (1400.0, 55.0)]
    content = spectrum_bytes(bands)

    community = publish_spectrum(client, owner, make_raw_file, content)
    curated = publish_spectrum(client, owner, make_raw_file, content)
    make_reference(
        db_session, community["id"], name="Community copy",
        tier=ReferenceTrustTier.community, source="user", source_id=None,
    )
    make_reference(
        db_session, curated["id"], name="Curated copy",
        tier=ReferenceTrustTier.curated, source_id="C1",
    )

    query = publish_spectrum(client, owner, make_raw_file, content)
    body = client.post("/v1/library/match", json={"spectrum_id": query["id"]}).json()

    names = [m["reference"]["compound_name"] for m in body["matches"]]
    assert names[0] == "Curated copy", names
    assert body["matches"][0]["similarity"] == pytest.approx(
        body["matches"][1]["similarity"], abs=1e-4
    )


def test_a_removed_reference_is_never_matched(
    client, db_session, make_user, make_raw_file
):
    owner = make_user()
    bands = [(500.0, 100.0), (1200.0, 60.0)]
    _s, entry = seed_reference(
        client, db_session, owner, make_raw_file, name="Calcite", peaks=bands
    )
    entry.curation_status = ReferenceCurationStatus.removed
    db_session.add(entry)
    db_session.commit()

    query = publish_spectrum(client, owner, make_raw_file, spectrum_bytes(bands))
    body = client.post("/v1/library/match", json={"spectrum_id": query["id"]}).json()
    assert all(m["reference"]["id"] != str(entry.id) for m in body["matches"])


def test_the_prefilter_narrows_a_corpus_large_enough_to_need_it(
    client, db_session, make_user, make_raw_file
):
    """If every reference is screened, the peak index is doing nothing."""
    from app.discovery.library_match import MIN_CANDIDATES

    owner = make_user()
    total = MIN_CANDIDATES + 8
    # A cluster of references sharing the query's band, plus well-separated
    # decoys that must be screened out.
    for i in range(MIN_CANDIDATES + 1):
        seed_reference(
            client, db_session, owner, make_raw_file, name=f"Near{i}",
            peaks=[(300.0 + i * 0.5, 100.0)], source_id=f"N{i}",
        )
    for i in range(total - (MIN_CANDIDATES + 1)):
        seed_reference(
            client, db_session, owner, make_raw_file, name=f"Far{i}",
            peaks=[(900.0 + i * 60.0, 100.0)], source_id=f"F{i}",
        )

    query = publish_spectrum(client, owner, make_raw_file, spectrum_bytes([(300.0, 100.0)]))
    body = client.post("/v1/library/match", json={"spectrum_id": query["id"]}).json()

    assert body["prefilter_stage"] == "narrow"
    assert body["candidates_screened"] < total
    assert body["matches"][0]["reference"]["compound_name"].startswith("Near")


def test_a_thin_corpus_still_answers_without_a_full_scan(
    client, db_session, make_user, make_raw_file
):
    """Few peak-sharing candidates is a success, not a shortfall.

    The regression this guards: an earlier ladder treated "fewer than N
    candidates" as failure and fell through to a full-corpus scan, which is
    precisely the cost the peak index exists to avoid.
    """
    owner = make_user()
    seed_reference(
        client, db_session, owner, make_raw_file, name="A",
        peaks=[(400.0, 100.0)], source_id="A1",
    )
    seed_reference(
        client, db_session, owner, make_raw_file, name="B",
        peaks=[(1500.0, 100.0)], source_id="B1",
    )

    query = publish_spectrum(client, owner, make_raw_file, spectrum_bytes([(400.0, 100.0)]))
    body = client.post("/v1/library/match", json={"spectrum_id": query["id"]}).json()

    assert body["prefilter_stage"] != "full"
    assert body["matches"][0]["reference"]["compound_name"] == "A"


def test_a_private_spectrum_is_not_found_rather_than_forbidden(
    client, db_session, make_user, make_raw_file
):
    owner = make_user()
    stranger = make_user()
    client.set_current_user(owner)
    raw_file = make_raw_file(owner, content=spectrum_bytes([(500.0, 100.0)]))
    draft = client.post("/spectra", json={"raw_file_id": str(raw_file.id)}).json()

    client.set_current_user(stranger)
    resp = client.post("/v1/library/match", json={"spectrum_id": draft["id"]})
    assert resp.status_code == 404


def test_a_two_component_query_reports_a_suspected_mixture(
    client, db_session, make_user, make_raw_file
):
    owner = make_user()
    seed_reference(
        client, db_session, owner, make_raw_file, name="A",
        peaks=[(500.0, 100.0)], source_id="A1",
    )
    seed_reference(
        client, db_session, owner, make_raw_file, name="B",
        peaks=[(1300.0, 100.0)], source_id="B1",
    )

    blend = publish_spectrum(
        client, owner, make_raw_file, spectrum_bytes([(500.0, 100.0), (1300.0, 90.0)])
    )
    body = client.post("/v1/library/match", json={"spectrum_id": blend["id"]}).json()

    assert body["mixture_suspected"] is True
    assert body["mixture_reason"]
    assert len(body["suggested_component_reference_ids"]) >= 2


# ---------------------------------------------------------------------------
# unmixing
# ---------------------------------------------------------------------------


def test_deconvolving_a_blend_returns_weights_that_sum_to_one(
    client, db_session, make_user, make_raw_file
):
    owner = make_user()
    _sa, a = seed_reference(
        client, db_session, owner, make_raw_file, name="A",
        peaks=[(500.0, 100.0)], source_id="A1",
    )
    _sb, b = seed_reference(
        client, db_session, owner, make_raw_file, name="B",
        peaks=[(1300.0, 100.0)], source_id="B1",
    )
    blend = publish_spectrum(
        client, owner, make_raw_file, spectrum_bytes([(500.0, 70.0), (1300.0, 30.0)])
    )

    resp = client.post(
        "/v1/library/unmix",
        json={"spectrum_id": blend["id"], "reference_ids": [str(a.id), str(b.id)]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert sum(c["weight"] for c in body["components"]) == pytest.approx(1.0)
    assert body["components"][0]["weight"] > body["components"][1]["weight"]
    assert body["r_squared"] > 0.9
    assert len(body["fitted"]) == len(body["grid_wavenumbers"]) == len(body["observed"])


def test_too_many_components_is_refused_by_the_schema(
    client, db_session, make_user, make_raw_file
):
    owner = make_user()
    query = publish_spectrum(client, owner, make_raw_file, spectrum_bytes([(500.0, 100.0)]))
    import uuid as _uuid

    resp = client.post(
        "/v1/library/unmix",
        json={
            "spectrum_id": query["id"],
            "reference_ids": [str(_uuid.uuid4()) for _ in range(7)],
        },
    )
    assert resp.status_code == 422


def test_an_unknown_reference_is_a_404(client, db_session, make_user, make_raw_file):
    import uuid as _uuid

    owner = make_user()
    query = publish_spectrum(client, owner, make_raw_file, spectrum_bytes([(500.0, 100.0)]))
    resp = client.post(
        "/v1/library/unmix",
        json={"spectrum_id": query["id"], "reference_ids": [str(_uuid.uuid4())]},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# browse
# ---------------------------------------------------------------------------


def test_browse_filters_by_name_formula_and_tier(
    client, db_session, make_user, make_raw_file
):
    owner = make_user()
    seed_reference(
        client, db_session, owner, make_raw_file, name="Calcite",
        peaks=[(1085.0, 100.0)], formula="CaCO3", source_id="R1",
    )
    seed_reference(
        client, db_session, owner, make_raw_file, name="Quartz",
        peaks=[(464.0, 100.0)], formula="SiO2", source_id="R2",
    )

    named = client.get("/v1/library/references", params={"q": "calc"}).json()
    assert [r["compound_name"] for r in named] == ["Calcite"]

    by_formula = client.get("/v1/library/references", params={"formula": "SiO2"}).json()
    assert [r["compound_name"] for r in by_formula] == ["Quartz"]

    community = client.get(
        "/v1/library/references", params={"trust_tier": "community"}
    ).json()
    assert community == []


def test_browse_hides_removed_entries(client, db_session, make_user, make_raw_file):
    owner = make_user()
    _s, entry = seed_reference(
        client, db_session, owner, make_raw_file, name="Calcite", peaks=[(1085.0, 100.0)]
    )
    entry.curation_status = ReferenceCurationStatus.removed
    db_session.add(entry)
    db_session.commit()

    assert client.get("/v1/library/references").json() == []
    assert client.get(f"/v1/library/references/{entry.id}").status_code == 404


def test_reference_detail_includes_its_peaks(client, db_session, make_user, make_raw_file):
    owner = make_user()
    _s, entry = seed_reference(
        client, db_session, owner, make_raw_file, name="Calcite", peaks=[(1085.0, 100.0)]
    )
    # Matching warms the peak index; before that the detail view simply has none.
    query = publish_spectrum(client, owner, make_raw_file, spectrum_bytes([(1085.0, 100.0)]))
    client.post("/v1/library/match", json={"spectrum_id": query["id"]})

    body = client.get(f"/v1/library/references/{entry.id}").json()
    assert body["compound_name"] == "Calcite"
    assert any(abs(p["cm1"] - 1085.0) < 5 for p in body["peaks"])


# ---------------------------------------------------------------------------
# contribute / moderate
# ---------------------------------------------------------------------------


def test_contributing_a_published_spectrum_makes_it_matchable_immediately(
    client, db_session, make_user, make_raw_file
):
    owner = make_user()
    bands = [(650.0, 100.0), (1350.0, 70.0)]
    mine = publish_spectrum(client, owner, make_raw_file, spectrum_bytes(bands))

    resp = client.post(
        "/v1/library/references",
        json={"spectrum_id": mine["id"], "compound_name": "My standard"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["trust_tier"] == "community"
    assert resp.json()["source"] == "user"

    query = publish_spectrum(client, owner, make_raw_file, spectrum_bytes(bands))
    body = client.post("/v1/library/match", json={"spectrum_id": query["id"]}).json()
    assert body["matches"][0]["reference"]["compound_name"] == "My standard"


def test_a_draft_cannot_become_a_reference(client, db_session, make_user, make_raw_file):
    """A reference's arrays are served to everyone who matches against it."""
    owner = make_user()
    client.set_current_user(owner)
    raw_file = make_raw_file(owner, content=spectrum_bytes([(500.0, 100.0)]))
    draft = client.post("/spectra", json={"raw_file_id": str(raw_file.id)}).json()

    resp = client.post(
        "/v1/library/references",
        json={"spectrum_id": draft["id"], "compound_name": "Leaky"},
    )
    assert resp.status_code == 409


def test_you_cannot_contribute_someone_elses_spectrum(
    client, db_session, make_user, make_raw_file
):
    owner = make_user()
    stranger = make_user()
    theirs = publish_spectrum(client, owner, make_raw_file, spectrum_bytes([(500.0, 100.0)]))

    client.set_current_user(stranger)
    resp = client.post(
        "/v1/library/references",
        json={"spectrum_id": theirs["id"], "compound_name": "Not mine"},
    )
    assert resp.status_code == 404


def test_reporting_flags_but_does_not_remove(client, db_session, make_user, make_raw_file):
    """Reporting raises a hand; it is not a veto."""
    owner = make_user()
    bands = [(500.0, 100.0)]
    _s, entry = seed_reference(
        client, db_session, owner, make_raw_file, name="Suspect", peaks=bands
    )
    client.set_current_user(owner)

    resp = client.post(
        f"/v1/library/references/{entry.id}/report", json={"reason": "Mislabelled"}
    )
    assert resp.status_code == 204

    db_session.refresh(entry)
    assert entry.flagged_for_review is True
    assert entry.report_count == 1

    query = publish_spectrum(client, owner, make_raw_file, spectrum_bytes(bands))
    body = client.post("/v1/library/match", json={"spectrum_id": query["id"]}).json()
    assert any(m["reference"]["id"] == str(entry.id) for m in body["matches"])


def test_only_a_moderator_can_remove_a_reference(
    client, db_session, make_user, make_raw_file
):
    owner = make_user()
    bands = [(500.0, 100.0)]
    _s, entry = seed_reference(
        client, db_session, owner, make_raw_file, name="Suspect", peaks=bands
    )

    client.set_current_user(owner)
    client.set_moderator(False)
    assert client.patch(
        f"/v1/library/references/{entry.id}", json={"curation_status": "removed"}
    ).status_code == 403

    client.set_moderator(True)
    resp = client.patch(
        f"/v1/library/references/{entry.id}", json={"curation_status": "removed"}
    )
    assert resp.status_code == 200

    assert client.get("/v1/library/references").json() == []
    query = publish_spectrum(client, owner, make_raw_file, spectrum_bytes(bands))
    body = client.post("/v1/library/match", json={"spectrum_id": query["id"]}).json()
    assert body["matches"] == []


# ---------------------------------------------------------------------------
# the commons must stay free of the reference corpus
# ---------------------------------------------------------------------------


def test_reference_spectra_are_excluded_from_the_public_commons(
    client, db_session, make_user, make_raw_file
):
    """Thousands of seeded minerals would otherwise bury real user uploads."""
    owner = make_user()
    ref_spectrum, _entry = seed_reference(
        client, db_session, owner, make_raw_file, name="Calcite", peaks=[(1085.0, 100.0)]
    )
    ordinary = publish_spectrum(client, owner, make_raw_file, spectrum_bytes([(700.0, 90.0)]))

    ids = [row["id"] for row in client.get("/search/spectra").json()]
    assert ordinary["id"] in ids
    assert ref_spectrum["id"] not in ids


def test_reference_spectra_are_excluded_from_similar_search(
    client, db_session, make_user, make_raw_file
):
    owner = make_user()
    bands = [(1085.0, 100.0)]
    ref_spectrum, _entry = seed_reference(
        client, db_session, owner, make_raw_file, name="Calcite", peaks=bands
    )
    mine = publish_spectrum(client, owner, make_raw_file, spectrum_bytes(bands))

    client.set_current_user(owner)
    resp = client.get(f"/search/similar/{mine['id']}")
    assert resp.status_code == 200
    ids = [row["spectrum"]["id"] for row in resp.json()]
    assert ref_spectrum["id"] not in ids


def test_deconvolution_is_rate_limited(client, db_session, make_user, make_raw_file, monkeypatch):
    """Unmixing downloads N+1 full spectra per call and solves a dense system,
    so its cost is object-storage egress. Unthrottled it is the cheapest way
    for a script to run up someone else's storage bill."""
    from app import ratelimit

    owner = make_user()
    _sa, a = seed_reference(
        client, db_session, owner, make_raw_file, name="A",
        peaks=[(500.0, 100.0)], source_id="A1",
    )
    _sb, b = seed_reference(
        client, db_session, owner, make_raw_file, name="B",
        peaks=[(1300.0, 100.0)], source_id="B1",
    )
    blend = publish_spectrum(
        client, owner, make_raw_file, spectrum_bytes([(500.0, 70.0), (1300.0, 30.0)])
    )
    client.set_current_user(owner)

    # A fresh limiter, so this test neither inherits nor leaks call counts.
    monkeypatch.setattr(
        ratelimit, "_library_unmix_limiter", ratelimit.RateLimiter(2, 3600)
    )

    body = {"spectrum_id": blend["id"], "reference_ids": [str(a.id), str(b.id)]}
    assert client.post("/v1/library/unmix", json=body).status_code == 200
    assert client.post("/v1/library/unmix", json=body).status_code == 200
    assert client.post("/v1/library/unmix", json=body).status_code == 429


def test_browse_lists_real_names_before_composition_strings(
    client, db_session, make_user, make_raw_file
):
    """A minority of imported entries carry a composition string instead of a
    name. Plain alphabetical sorting puts every one of those on the first page,
    which is the worst possible first impression of the library."""
    owner = make_user()
    seed_reference(
        client, db_session, owner, make_raw_file,
        name="(Pb1.924 Ba0.018 Ca0.007) O", peaks=[(500.0, 100.0)], source_id="U1",
    )
    seed_reference(
        client, db_session, owner, make_raw_file,
        name="Calcite", peaks=[(1085.0, 100.0)], source_id="U2",
    )

    names = [r["compound_name"] for r in client.get("/v1/library/references").json()]
    assert names[0] == "Calcite"
    assert names[-1].startswith("(")


# ---------------------------------------------------------------------------
# ranked, typo-tolerant browse
# ---------------------------------------------------------------------------


def test_browse_ranks_an_exact_name_above_a_substring_match(
    client, db_session, make_user, make_raw_file
):
    """The whole point of the change. Every one of these contains "calcite",
    so the old unanchored ILIKE matched all three and then handed them back in
    alphabetical order — putting "Calcite, magnesian" first and the thing the
    user actually typed second."""
    owner = make_user()
    for i, name in enumerate(["Sodium calcitrate", "Calcite, magnesian", "Calcite"]):
        seed_reference(
            client, db_session, owner, make_raw_file,
            name=name, peaks=[(1085.0 + i, 100.0)], source_id=f"K{i}",
        )

    names = [
        r["compound_name"]
        for r in client.get("/v1/library/references", params={"q": "calcite"}).json()
    ]
    assert names[0] == "Calcite"
    assert set(names) == {"Calcite", "Calcite, magnesian", "Sodium calcitrate"}


def test_browse_tolerates_a_typo(client, db_session, make_user, make_raw_file):
    """Pins TRIGRAM_THRESHOLD. Postgres' default word_similarity threshold is
    0.6, which scores calcyte->Calcite at 0.500 and therefore returns nothing
    at all; if someone restores the default, this fails loudly rather than
    quietly removing typo tolerance."""
    owner = make_user()
    seed_reference(
        client, db_session, owner, make_raw_file,
        name="Calcite", peaks=[(1085.0, 100.0)], source_id="T1",
    )
    seed_reference(
        client, db_session, owner, make_raw_file,
        name="Quartz", peaks=[(464.0, 100.0)], source_id="T2",
    )

    misspelled = client.get("/v1/library/references", params={"q": "calcyte"}).json()
    assert [r["compound_name"] for r in misspelled] == ["Calcite"]

    also_misspelled = client.get("/v1/library/references", params={"q": "quarz"}).json()
    assert [r["compound_name"] for r in also_misspelled] == ["Quartz"]


def test_browse_finds_an_entry_by_its_synonym(
    client, db_session, make_user, make_raw_file
):
    """`common_names` has existed since the model was written, documented as
    the reason "calcite" and "calcium carbonate" find the same entry, and was
    never actually searched. It is also the only column reached through the
    JSONB flattening, so this is the test that covers that expression."""
    owner = make_user()
    seed_reference(
        client, db_session, owner, make_raw_file,
        name="Calcite", peaks=[(1085.0, 100.0)], source_id="S1",
        common_names=["calcium carbonate", "limestone"],
    )
    seed_reference(
        client, db_session, owner, make_raw_file,
        name="Quartz", peaks=[(464.0, 100.0)], source_id="S2",
    )

    by_synonym = client.get(
        "/v1/library/references", params={"q": "calcium carbonate"}
    ).json()
    assert [r["compound_name"] for r in by_synonym] == ["Calcite"]

    by_other_synonym = client.get(
        "/v1/library/references", params={"q": "limestone"}
    ).json()
    assert [r["compound_name"] for r in by_other_synonym] == ["Calcite"]


def test_browse_ordering_is_unchanged_without_a_query(
    client, db_session, make_user, make_raw_file
):
    """Ranking applies only when there is something to rank against. With no
    `q`, the ordering must stay exactly what it was — curated first, real
    names before composition strings, then alphabetical."""
    owner = make_user()
    seed_reference(
        client, db_session, owner, make_raw_file,
        name="(Pb1.924 Ba0.018 Ca0.007) O", peaks=[(500.0, 100.0)], source_id="O1",
    )
    seed_reference(
        client, db_session, owner, make_raw_file,
        name="Zircon", peaks=[(1008.0, 100.0)], source_id="O2",
    )
    seed_reference(
        client, db_session, owner, make_raw_file,
        name="Albite", peaks=[(507.0, 100.0)], source_id="O3",
    )

    names = [r["compound_name"] for r in client.get("/v1/library/references").json()]
    assert names == ["Albite", "Zircon", "(Pb1.924 Ba0.018 Ca0.007) O"]


def test_browse_is_rate_limited(client, db_session, make_user, make_raw_file, monkeypatch):
    """The browse endpoint is public, unauthenticated and now fires once per
    debounced keystroke. It previously had no limit at all."""
    from app import ratelimit

    owner = make_user()
    seed_reference(
        client, db_session, owner, make_raw_file,
        name="Calcite", peaks=[(1085.0, 100.0)], source_id="RL1",
    )

    # A fresh limiter, so this test neither inherits nor leaks call counts.
    monkeypatch.setattr(
        ratelimit, "_search_browse_limiter", ratelimit.RateLimiter(2, 3600)
    )

    assert client.get("/v1/library/references", params={"q": "calc"}).status_code == 200
    assert client.get("/v1/library/references", params={"q": "calc"}).status_code == 200
    assert client.get("/v1/library/references", params={"q": "calc"}).status_code == 429
