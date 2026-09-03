"""Co-author credits and next steps on a Finding.

Two rules carry most of the weight here:

- An unknown handle is refused, not dropped. A silently-ignored typo credits
  nobody while looking like it worked, and a credit is exactly the kind of
  thing an author will not go back and re-check.
- Sending the list replaces it. A merge-only update would make removing
  someone impossible, which is the case that actually matters.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.models.finding import FindingCoAuthor
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


@pytest.fixture()
def handled_user(db_session, make_user):
    """A user with a profile handle, since credits are addressed by handle."""

    def _make(handle: str, name: str = "Collaborator"):
        user = make_user()
        user.profile_handle = handle
        user.display_name = name
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _make


def test_create_with_co_authors_and_next_steps(client, make_user, handled_user):
    author = make_user()
    ada = handled_user("ada")
    lin = handled_user("lin", "Lin")
    client.set_current_user(author)

    res = client.post(
        "/v1/findings",
        json={
            "title": "Perovskite ageing",
            "abstract_md": "what we saw",
            "next_steps_md": "Repeat at 90% RH; need a humidity stage.",
            "co_author_handles": ["ada", "@lin"],
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()

    assert body["next_steps_md"] == "Repeat at 90% RH; need a humidity stage."
    # Order is meaningful in an author list and must survive the round trip.
    assert [c["handle"] for c in body["co_authors"]] == ["ada", "lin"]
    assert [c["position"] for c in body["co_authors"]] == [0, 1]
    assert {c["user_id"] for c in body["co_authors"]} == {str(ada.id), str(lin.id)}
    assert body["co_authors"][1]["display_name"] == "Lin"


def test_a_leading_at_sign_is_accepted(client, make_user, handled_user):
    author = make_user()
    handled_user("ada")
    client.set_current_user(author)

    res = client.post(
        "/v1/findings",
        json={"title": "T", "co_author_handles": ["@ada"]},
    )
    assert res.status_code == 201
    assert [c["handle"] for c in res.json()["co_authors"]] == ["ada"]


def test_unknown_handle_is_refused_and_creates_nothing(client, db_session, make_user, handled_user):
    author = make_user()
    handled_user("ada")
    client.set_current_user(author)

    res = client.post(
        "/v1/findings",
        json={"title": "T", "co_author_handles": ["ada", "nobody-here"]},
    )
    assert res.status_code == 422
    assert "nobody-here" in res.json()["detail"]

    # The whole request is rejected — a partially-credited finding would be
    # worse than none, since the author would think the list stuck.
    assert db_session.query(FindingCoAuthor).count() == 0
    listed = client.get("/v1/findings").json()
    assert listed == []


def test_the_owner_is_not_credited_twice(client, make_user, db_session):
    author = make_user()
    author.profile_handle = "owner"
    db_session.add(author)
    db_session.commit()
    client.set_current_user(author)

    res = client.post(
        "/v1/findings",
        json={"title": "T", "co_author_handles": ["owner"]},
    )
    assert res.status_code == 201
    assert res.json()["co_authors"] == []


def test_patch_replaces_the_author_list(client, make_user, handled_user):
    author = make_user()
    handled_user("ada")
    handled_user("lin")
    handled_user("kay")
    client.set_current_user(author)

    created = client.post(
        "/v1/findings",
        json={"title": "T", "co_author_handles": ["ada", "lin"]},
    ).json()

    # Replace, not merge: dropping "lin" has to actually drop them.
    patched = client.patch(
        f"/v1/findings/{created['id']}",
        json={"co_author_handles": ["kay", "ada"]},
    )
    assert patched.status_code == 200
    assert [c["handle"] for c in patched.json()["co_authors"]] == ["kay", "ada"]


def test_an_empty_list_clears_the_credits(client, make_user, handled_user):
    author = make_user()
    handled_user("ada")
    client.set_current_user(author)

    created = client.post("/v1/findings", json={"title": "T", "co_author_handles": ["ada"]}).json()
    assert len(created["co_authors"]) == 1

    cleared = client.patch(f"/v1/findings/{created['id']}", json={"co_author_handles": []})
    assert cleared.status_code == 200
    assert cleared.json()["co_authors"] == []


def test_omitting_the_field_leaves_credits_alone(client, make_user, handled_user):
    author = make_user()
    handled_user("ada")
    client.set_current_user(author)

    created = client.post("/v1/findings", json={"title": "T", "co_author_handles": ["ada"]}).json()

    # Editing the title must not wipe the author list.
    patched = client.patch(f"/v1/findings/{created['id']}", json={"title": "New title"})
    assert patched.status_code == 200
    assert [c["handle"] for c in patched.json()["co_authors"]] == ["ada"]


def test_a_repeated_handle_is_credited_once(client, make_user, handled_user):
    author = make_user()
    handled_user("ada")
    client.set_current_user(author)

    res = client.post(
        "/v1/findings",
        json={"title": "T", "co_author_handles": ["ada", "ADA", "ada"]},
    )
    assert res.status_code == 201
    assert [c["handle"] for c in res.json()["co_authors"]] == ["ada"]


def test_next_steps_can_be_edited_and_cleared(client, make_user):
    author = make_user()
    client.set_current_user(author)

    created = client.post("/v1/findings", json={"title": "T", "next_steps_md": "first plan"}).json()
    assert created["next_steps_md"] == "first plan"

    updated = client.patch(
        f"/v1/findings/{created['id']}", json={"next_steps_md": "revised plan"}
    ).json()
    assert updated["next_steps_md"] == "revised plan"

    cleared = client.patch(f"/v1/findings/{created['id']}", json={"next_steps_md": ""}).json()
    assert cleared["next_steps_md"] is None


def test_the_author_list_is_capped(client, make_user):
    author = make_user()
    client.set_current_user(author)

    res = client.post(
        "/v1/findings",
        json={"title": "T", "co_author_handles": [f"h{i}" for i in range(21)]},
    )
    assert res.status_code == 422
