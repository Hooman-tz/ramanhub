"""Tests for `POST /v1/lab/consult` — the read-only "lab consultant" LLM
advice endpoint.

Covers: the 503 when no LLM key is configured, the 404 (never 403) for
another user's spectrum, the step_type / param post-filter that drops
garbage the model returns, the zero-side-effects guarantee, and the
500-char cap on `question`.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import app.routers.lab_consult as lab_consult
from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.analysis import AnalysisRun
from app.models.enums import Modality
from app.models.ingestion_job import IngestionJob
from app.models.processed_cache import ProcessedCache
from app.models.processing_ledger import ProcessingLedger
from app.models.spectrum import Spectrum


@pytest.fixture()
def consult_client(db_session):
    test_app = FastAPI()
    test_app.include_router(lab_consult.router)

    def _override_get_db():
        yield db_session

    current = {"user": None}

    def _override_get_current_user():
        if current["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current["user"]

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_current_user] = _override_get_current_user

    client = TestClient(test_app)
    client.set_current_user = lambda user: current.__setitem__("user", user)
    return client


def _make_spectrum(db_session, owner, raw_file) -> Spectrum:
    spectrum = Spectrum(
        raw_file_id=raw_file.id,
        owner_id=owner.id,
        modality=Modality.raman,
        title="Test spectrum",
    )
    db_session.add(spectrum)
    db_session.commit()
    db_session.refresh(spectrum)
    return spectrum


def _patch_llm(monkeypatch, *, configured=True, reply=None):
    monkeypatch.setattr(lab_consult, "llm_configured", lambda: configured)

    async def _fake_complete_json(**kwargs):
        _fake_complete_json.calls.append(kwargs)
        return reply if reply is not None else {
            "observations": [],
            "suggested_preprocessing": [],
            "suggested_analyses": [],
            "caveats": [],
        }

    _fake_complete_json.calls = []
    monkeypatch.setattr(lab_consult, "complete_json", _fake_complete_json)
    return _fake_complete_json


def test_503_when_no_llm_key(consult_client, monkeypatch, make_user, make_raw_file, db_session):
    fake = _patch_llm(monkeypatch, configured=False)
    owner = make_user()
    consult_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _make_spectrum(db_session, owner, raw_file)

    resp = consult_client.post(
        "/v1/lab/consult", json={"spectrum_ids": [str(spectrum.id)]}
    )

    assert resp.status_code == 503
    assert fake.calls == []


def test_404_for_another_users_spectrum(
    consult_client, monkeypatch, make_user, make_raw_file, db_session
):
    fake = _patch_llm(monkeypatch, configured=True)
    owner = make_user()
    other = make_user()
    raw_file = make_raw_file(owner)
    spectrum = _make_spectrum(db_session, owner, raw_file)

    consult_client.set_current_user(other)
    resp = consult_client.post(
        "/v1/lab/consult", json={"spectrum_ids": [str(spectrum.id)]}
    )

    assert resp.status_code == 404
    assert fake.calls == []


def test_missing_spectrum_id_is_404(consult_client, monkeypatch, make_user):
    _patch_llm(monkeypatch, configured=True)
    owner = make_user()
    consult_client.set_current_user(owner)

    resp = consult_client.post(
        "/v1/lab/consult",
        json={"spectrum_ids": ["00000000-0000-0000-0000-000000000000"]},
    )
    assert resp.status_code == 404


def test_post_filter_drops_garbage(
    consult_client, monkeypatch, make_user, make_raw_file, db_session
):
    reply = {
        "observations": ["low SNR in the fingerprint region", 42, ""],
        "suggested_preprocessing": [
            # valid step, one good param (string -> int), one unknown param
            {
                "step_type": "raman.snv",
                "params": {"ddof": "1", "totally_made_up": 9},
                "rationale": "normalize scatter",
            },
            # unknown step type -> whole item dropped
            {"step_type": "raman.summon_daemon", "params": {}, "rationale": "no"},
            # valid step, but every param is uncoercible -> params end up empty
            {
                "step_type": "raman.smooth.savitzky_golay",
                "params": {"window_length": 1.5, "polyorder": "abc"},
                "rationale": "smooth",
            },
            "not even a dict",
        ],
        "suggested_analyses": [
            {"analysis_type": "pca", "rationale": "cluster structure"},
            {"analysis_type": "tarot_reading", "rationale": "vibes"},
            {"analysis_type": "pca_kmeans", "rationale": "grouping"},
        ],
        "caveats": ["advice only", 123],
    }
    _patch_llm(monkeypatch, configured=True, reply=reply)
    owner = make_user()
    consult_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _make_spectrum(db_session, owner, raw_file)

    resp = consult_client.post(
        "/v1/lab/consult", json={"spectrum_ids": [str(spectrum.id)]}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["observations"] == ["low SNR in the fingerprint region"]
    assert body["caveats"] == ["advice only"]

    steps = body["suggested_preprocessing"]
    assert [s["step_type"] for s in steps] == [
        "raman.snv",
        "raman.smooth.savitzky_golay",
    ]
    assert steps[0]["params"] == {"ddof": 1}  # coerced, unknown key dropped
    assert steps[1]["params"] == {}  # both params uncoercible -> dropped

    assert [a["analysis_type"] for a in body["suggested_analyses"]] == [
        "pca",
        "pca_kmeans",
    ]


def test_no_side_effects(
    consult_client, monkeypatch, make_user, make_raw_file, db_session
):
    reply = {
        "observations": ["ok"],
        "suggested_preprocessing": [
            {"step_type": "raman.snv", "params": {}, "rationale": "r"}
        ],
        "suggested_analyses": [{"analysis_type": "pca", "rationale": "r"}],
        "caveats": [],
    }
    _patch_llm(monkeypatch, configured=True, reply=reply)
    owner = make_user()
    consult_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _make_spectrum(db_session, owner, raw_file)

    def _counts() -> dict:
        return {
            "ledgers": db_session.query(ProcessingLedger).count(),
            "cache": db_session.query(ProcessedCache).count(),
            "runs": db_session.query(AnalysisRun).count(),
            "jobs": db_session.query(IngestionJob).count(),
            "spectra": db_session.query(Spectrum).count(),
        }

    before = _counts()
    resp = consult_client.post(
        "/v1/lab/consult",
        json={"spectrum_ids": [str(spectrum.id)], "question": "what next?"},
    )
    assert resp.status_code == 200, resp.text

    assert _counts() == before
    db_session.expire(spectrum)
    assert spectrum.current_ledger_id is None


def test_question_length_cap(
    consult_client, monkeypatch, make_user, make_raw_file, db_session
):
    _patch_llm(monkeypatch, configured=True)
    owner = make_user()
    consult_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    spectrum = _make_spectrum(db_session, owner, raw_file)

    ok = consult_client.post(
        "/v1/lab/consult",
        json={"spectrum_ids": [str(spectrum.id)], "question": "x" * 500},
    )
    assert ok.status_code == 200, ok.text

    too_long = consult_client.post(
        "/v1/lab/consult",
        json={"spectrum_ids": [str(spectrum.id)], "question": "x" * 501},
    )
    assert too_long.status_code == 422
