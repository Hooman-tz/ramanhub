"""Pinned items and the contribution-activity chart.

Pins are what turn a profile from a log into a portfolio, so the rules worth
pinning down are the ones that keep them honest: you can only pin your own
work, and the cap actually binds.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.activity import compute_activity
from app.auth.deps import get_current_user, get_current_user_optional
from app.db.session import get_db
from app.models.curation import MAX_PINS
from app.models.enums import SpectrumState
from app.models.spectrum import Spectrum
from app.routers import findings, pins, spectra, users


@pytest.fixture()
def pin_client(db_session):
    test_app = FastAPI()
    for module in (spectra, findings, users, pins):
        test_app.include_router(module.router)

    def _override_get_db():
        yield db_session

    current = {"user": None}

    def _override_get_current_user():
        if current["user"] is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return current["user"]

    test_app.dependency_overrides[get_db] = _override_get_db
    test_app.dependency_overrides[get_current_user] = _override_get_current_user
    test_app.dependency_overrides[get_current_user_optional] = lambda: current["user"]

    client = TestClient(test_app)
    client.set_current_user = lambda user: current.__setitem__("user", user)
    return client


@pytest.fixture()
def handled(make_user, db_session):
    def _make():
        user = make_user()
        user.handle = f"u{uuid.uuid4().hex[:10]}"
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return _make


def _make_spectrum(client, raw_file, db_session, published=True):
    resp = client.post("/spectra", json={"raw_file_id": str(raw_file.id)})
    assert resp.status_code == 201, resp.text
    spectrum = db_session.get(Spectrum, uuid.UUID(resp.json()["id"]))
    if published:
        spectrum.state = SpectrumState.published
        spectrum.published_at = datetime.now(UTC)
        db_session.add(spectrum)
        db_session.commit()
    return spectrum


# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------


def test_pin_and_unpin(pin_client, handled, make_raw_file, db_session):
    owner = handled()
    pin_client.set_current_user(owner)
    spectrum = _make_spectrum(pin_client, make_raw_file(owner), db_session)

    created = pin_client.post("/pins", json={"kind": "spectrum", "id": str(spectrum.id)})
    assert created.status_code == 201
    assert [p["id"] for p in created.json()] == [str(spectrum.id)]

    after = pin_client.delete(f"/pins/spectrum/{spectrum.id}")
    assert after.json() == []


def test_you_cannot_pin_someone_elses_work(pin_client, handled, make_raw_file, db_session):
    """Pinning another person's spectrum to your own profile would
    misrepresent who produced it — so this checks ownership, not merely
    whether you can read the thing."""
    owner, stranger = handled(), handled()
    pin_client.set_current_user(owner)
    spectrum = _make_spectrum(pin_client, make_raw_file(owner), db_session)

    pin_client.set_current_user(stranger)
    resp = pin_client.post("/pins", json={"kind": "spectrum", "id": str(spectrum.id)})

    assert resp.status_code == 404
    assert pin_client.get(f"/users/{stranger.handle}/pins").json() == []


def test_the_pin_cap_binds(pin_client, handled, make_raw_file, db_session):
    """Four slots force a choice. A profile that can pin twenty items has
    ranked nothing, which is the whole reason the cap exists."""
    owner = handled()
    pin_client.set_current_user(owner)

    for _ in range(MAX_PINS):
        spectrum = _make_spectrum(pin_client, make_raw_file(owner), db_session)
        assert pin_client.post("/pins", json={"kind": "spectrum", "id": str(spectrum.id)}).status_code == 201

    extra = _make_spectrum(pin_client, make_raw_file(owner), db_session)
    resp = pin_client.post("/pins", json={"kind": "spectrum", "id": str(extra.id)})

    assert resp.status_code == 409
    assert "unpin one first" in resp.json()["detail"]


def test_pinning_twice_is_idempotent(pin_client, handled, make_raw_file, db_session):
    """The UI button is a toggle; a double submit must not 500 or duplicate."""
    owner = handled()
    pin_client.set_current_user(owner)
    spectrum = _make_spectrum(pin_client, make_raw_file(owner), db_session)

    pin_client.post("/pins", json={"kind": "spectrum", "id": str(spectrum.id)})
    again = pin_client.post("/pins", json={"kind": "spectrum", "id": str(spectrum.id)})

    assert again.status_code == 201
    assert len(again.json()) == 1


def test_pins_are_publicly_readable(pin_client, handled, make_raw_file, db_session):
    owner = handled()
    pin_client.set_current_user(owner)
    spectrum = _make_spectrum(pin_client, make_raw_file(owner), db_session)
    pin_client.post("/pins", json={"kind": "spectrum", "id": str(spectrum.id)})

    pin_client.set_current_user(None)
    assert len(pin_client.get(f"/users/{owner.handle}/pins").json()) == 1


def test_bad_kind_is_rejected(pin_client, handled):
    pin_client.set_current_user(handled())
    resp = pin_client.post("/pins", json={"kind": "nonsense", "id": str(uuid.uuid4())})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------


def test_activity_returns_one_entry_per_day_requested(handled, db_session):
    summary = compute_activity(handled().id, db_session, days=30)
    assert len(summary.days) == 30
    assert summary.total == 0
    assert summary.current_streak == 0


def test_activity_counts_a_published_spectrum(pin_client, handled, make_raw_file, db_session):
    owner = handled()
    pin_client.set_current_user(owner)
    _make_spectrum(pin_client, make_raw_file(owner), db_session)

    summary = compute_activity(owner.id, db_session, days=30)
    assert summary.total == 1
    assert summary.days[-1].spectra == 1
    assert summary.current_streak == 1


def test_activity_ignores_drafts(pin_client, handled, make_raw_file, db_session):
    """A draft is not a contribution to the commons, and counting them would
    make the chart inflatable by clicking 'new spectrum' repeatedly."""
    owner = handled()
    pin_client.set_current_user(owner)
    _make_spectrum(pin_client, make_raw_file(owner), db_session, published=False)

    assert compute_activity(owner.id, db_session, days=30).total == 0


def test_activity_keeps_kinds_separate(pin_client, handled, make_raw_file, db_session):
    """Publishing a spectrum and writing a comment are different acts with
    different costs; one blended number tells you neither."""
    owner = handled()
    pin_client.set_current_user(owner)
    _make_spectrum(pin_client, make_raw_file(owner), db_session)

    summary = compute_activity(owner.id, db_session, days=30)
    today = summary.days[-1]
    assert (today.spectra, today.findings, today.comments) == (1, 0, 0)


def test_activity_window_is_bounded(handled, db_session):
    """A request for ten years must not build a ten-year array."""
    assert len(compute_activity(handled().id, db_session, days=10_000).days) <= 730


def test_old_events_fall_outside_the_window(pin_client, handled, make_raw_file, db_session):
    owner = handled()
    pin_client.set_current_user(owner)
    spectrum = _make_spectrum(pin_client, make_raw_file(owner), db_session)
    spectrum.published_at = datetime.now(UTC) - timedelta(days=400)
    db_session.add(spectrum)
    db_session.commit()

    assert compute_activity(owner.id, db_session, days=30).total == 0


@pytest.mark.parametrize("session_tz", ["Pacific/Kiritimati", "Pacific/Niue"])
def test_activity_buckets_in_utc_whatever_the_session_timezone(
    pin_client, handled, make_raw_file, db_session, session_tz
):
    """The contribution chart must not move when the DB session's clock does.

    This is a regression test for a bug that only showed itself after 17:00
    local in America/Vancouver: the calendar was built from
    `datetime.now(UTC).date()`, but the SQL used a bare `date(published_at)`,
    which Postgres resolves in the SESSION timezone. Today's upload was then
    filed under yesterday and today's square rendered empty.

    Asserting against a fixed real timezone would only fail for part of the
    day, so instead the session clock is forced to the two extremes either
    side of the date line: UTC+14 and UTC-11. One of them is guaranteed to
    be on a different calendar day from UTC at every instant, so the old
    code fails this at any hour.
    """
    owner = handled()
    pin_client.set_current_user(owner)
    _make_spectrum(pin_client, make_raw_file(owner), db_session)

    db_session.execute(text(f"SET TIME ZONE '{session_tz}'"))
    try:
        summary = compute_activity(owner.id, db_session, days=30)
    finally:
        db_session.execute(text("SET TIME ZONE 'UTC'"))

    today_utc = datetime.now(UTC).date()
    assert summary.total == 1
    assert summary.days[-1].date == today_utc
    assert summary.days[-1].spectra == 1, (
        f"published now landed outside today's UTC bucket with session "
        f"timezone {session_tz}: {[(str(d.date), d.spectra) for d in summary.days if d.spectra]}"
    )
