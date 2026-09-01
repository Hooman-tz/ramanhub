"""`findings.repo_url` — optional link to the code/analysis repo behind a
write-up. Round-trips through create + patch; rejects a non-URL value.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.routers import findings


@pytest.fixture()
def client(db_session):
    app = FastAPI()
    app.include_router(findings.router)

    current: dict[str, object] = {"user": None}

    def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    app.dependency_overrides[get_current_user_optional] = lambda: current["user"]

    c = TestClient(app)
    c.set_current_user = lambda u: current.__setitem__("user", u)
    return c


def test_repo_url_defaults_to_null_and_round_trips_on_create(client, make_user):
    client.set_current_user(make_user())

    plain = client.post("/v1/findings", json={"title": "No repo"})
    assert plain.status_code == 201, plain.text
    assert plain.json()["repo_url"] is None

    with_repo = client.post(
        "/v1/findings",
        json={"title": "With repo", "repo_url": "https://github.com/acme/raman-analysis"},
    )
    assert with_repo.status_code == 201, with_repo.text
    fid = with_repo.json()["id"]
    assert with_repo.json()["repo_url"] == "https://github.com/acme/raman-analysis"

    fetched = client.get(f"/v1/findings/{fid}")
    assert fetched.json()["repo_url"] == "https://github.com/acme/raman-analysis"


def test_repo_url_is_editable_and_clearable_via_patch(client, make_user):
    client.set_current_user(make_user())
    fid = client.post("/v1/findings", json={"title": "Editable"}).json()["id"]

    set_resp = client.patch(
        f"/v1/findings/{fid}", json={"repo_url": "https://gitlab.com/team/notebooks"}
    )
    assert set_resp.status_code == 200, set_resp.text
    assert set_resp.json()["repo_url"] == "https://gitlab.com/team/notebooks"

    cleared = client.patch(f"/v1/findings/{fid}", json={"repo_url": ""})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["repo_url"] is None


def test_repo_url_must_look_like_a_url(client, make_user):
    client.set_current_user(make_user())

    bad = client.post("/v1/findings", json={"title": "Bad repo", "repo_url": "github.com/acme/x"})
    assert bad.status_code == 422, bad.text
