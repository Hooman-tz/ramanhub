"""Tests for `POST /raw-files/{id}/name-suggestion` — the advisory short
display name offered during import.

The shared LLM client (`app.llm.complete_json`) is always mocked; the real API
is never called.

The theme of every case here is that naming is a *convenience on top of an
upload*. A missing key, an unreachable model, or a reply that fails validation
must all come back as `200 {"suggested_title": null}` with a reason, never as
an error that could strand someone mid-import. Only the two conditions that are
genuinely the caller's fault — asking about someone else's file, or asking
before parsing has produced anything — are 4xx.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.llm import LLMError


@pytest.fixture()
def name_client(db_session):
    """A TestClient with only the raw-files router mounted."""
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from app.auth.deps import get_current_user
    from app.db.session import get_db
    from app.routers import raw_files

    test_app = FastAPI()
    test_app.include_router(raw_files.router)

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


def _url(raw_file) -> str:
    return f"/raw-files/{raw_file.id}/name-suggestion"


def test_suggests_a_short_display_name(name_client, make_user, make_raw_file):
    user = make_user()
    raw_file = make_raw_file(user)
    name_client.set_current_user(user)

    with (
        patch("app.routers.raw_files.llm_available_for", return_value=True),
        patch(
            "app.routers.raw_files.complete_json",
            new=AsyncMock(return_value={"title": "Polystyrene reference 785 nm"}),
        ) as mock_complete,
    ):
        res = name_client.post(_url(raw_file))

    assert res.status_code == 200
    assert res.json() == {
        "suggested_title": "Polystyrene reference 785 nm",
        "reason": None,
    }
    # The filename is signal the parsed header often lacks, so it must reach
    # the model alongside the metadata.
    prompt = mock_complete.await_args.kwargs["user"]
    assert "spectrum.txt" in prompt
    assert "Test Vendor" in prompt


def test_spaces_and_parentheses_are_allowed(name_client, make_user, make_raw_file):
    """A display name is not a filename — the old filename regex rejected the
    exact shape we now want."""
    user = make_user()
    raw_file = make_raw_file(user)
    name_client.set_current_user(user)

    with (
        patch("app.routers.raw_files.llm_available_for", return_value=True),
        patch(
            "app.routers.raw_files.complete_json",
            new=AsyncMock(return_value={"title": "Calcite (natural) 532 nm"}),
        ),
    ):
        res = name_client.post(_url(raw_file))

    assert res.json()["suggested_title"] == "Calcite (natural) 532 nm"


@pytest.mark.parametrize(
    "reply",
    [
        {"title": "path/to/file"},          # slashes are not a display name
        {"title": "x" * 81},                 # past the length cap
        {"title": ""},                       # empty
        {"title": 42},                        # not a string
        {},                                   # key missing entirely
    ],
)
def test_unusable_reply_degrades_to_null(name_client, make_user, make_raw_file, reply):
    user = make_user()
    raw_file = make_raw_file(user)
    name_client.set_current_user(user)

    with (
        patch("app.routers.raw_files.llm_available_for", return_value=True),
        patch("app.routers.raw_files.complete_json", new=AsyncMock(return_value=reply)),
    ):
        res = name_client.post(_url(raw_file))

    assert res.status_code == 200
    assert res.json()["suggested_title"] is None
    assert res.json()["reason"]


def test_llm_error_degrades_to_null(name_client, make_user, make_raw_file):
    user = make_user()
    raw_file = make_raw_file(user)
    name_client.set_current_user(user)

    with (
        patch("app.routers.raw_files.llm_available_for", return_value=True),
        patch(
            "app.routers.raw_files.complete_json",
            new=AsyncMock(side_effect=LLMError("upstream is down")),
        ),
    ):
        res = name_client.post(_url(raw_file))

    assert res.status_code == 200
    assert res.json()["suggested_title"] is None


def test_no_model_configured_never_calls_the_client(
    name_client, make_user, make_raw_file
):
    user = make_user()
    raw_file = make_raw_file(user)
    name_client.set_current_user(user)

    with (
        patch("app.routers.raw_files.llm_available_for", return_value=False),
        patch("app.routers.raw_files.complete_json", new=AsyncMock()) as mock_complete,
    ):
        res = name_client.post(_url(raw_file))

    assert res.status_code == 200
    assert res.json()["suggested_title"] is None
    mock_complete.assert_not_awaited()


def test_another_users_file_is_not_found(name_client, make_user, make_raw_file):
    owner = make_user()
    raw_file = make_raw_file(owner)
    name_client.set_current_user(make_user())

    with patch("app.routers.raw_files.complete_json", new=AsyncMock()) as mock_complete:
        res = name_client.post(_url(raw_file))

    assert res.status_code == 404
    mock_complete.assert_not_awaited()


def test_unknown_id_is_not_found(name_client, make_user):
    name_client.set_current_user(make_user())
    assert name_client.post(f"/raw-files/{uuid.uuid4()}/name-suggestion").status_code == 404
    assert name_client.post("/raw-files/not-a-uuid/name-suggestion").status_code == 404


def test_rejects_a_file_with_nothing_parsed_yet(
    name_client, db_session, make_user, make_raw_file
):
    from app.models.ingestion_job import IngestionJob

    user = make_user()
    raw_file = make_raw_file(user)
    job = db_session.query(IngestionJob).filter(IngestionJob.raw_file_id == raw_file.id).one()
    job.extracted_metadata_raw = None
    job.extracted_metadata_confirmed = None
    db_session.commit()
    name_client.set_current_user(user)

    with patch("app.routers.raw_files.complete_json", new=AsyncMock()) as mock_complete:
        res = name_client.post(_url(raw_file))

    assert res.status_code == 400
    mock_complete.assert_not_awaited()
