"""Accession numbers and profile handles — the two citable public
identifiers.

The invariant that matters most here: an accession must never name two
different records. A citation quoting RH-S-000042 has to keep meaning the
same thing forever.
"""
from __future__ import annotations

import pytest

from app.models.accession import (
    format_accession,
    next_accession,
    next_finding_accession,
    next_spectrum_accession,
)
from app.models.handles import (
    RESERVED_HANDLES,
    InvalidHandleError,
    suggest_handle,
    uniquify_handle,
    validate_handle,
)

# ---------------------------------------------------------------- accession


def test_format_is_zero_padded_and_prefixed():
    assert format_accession("S", 42) == "RH-S-000042"
    assert format_accession("F", 1) == "RH-F-000001"


def test_format_does_not_wrap_past_the_padding_width():
    """Past a million records identifiers just get longer — they must never
    truncate, which would start reusing names."""
    assert format_accession("S", 12345678) == "RH-S-12345678"


def test_unknown_kind_is_rejected(db_session):
    with pytest.raises(ValueError, match="Unknown accession kind"):
        next_accession(db_session, "Z")


def test_accessions_are_unique_and_increasing(db_session):
    issued = [next_spectrum_accession(db_session) for _ in range(5)]
    assert len(set(issued)) == 5
    assert issued == sorted(issued)


def test_spectra_and_findings_number_independently(db_session):
    """Two series, so RH-S-000001 and RH-F-000001 can both exist."""
    spectrum = next_spectrum_accession(db_session)
    finding = next_finding_accession(db_session)

    assert spectrum.startswith("RH-S-")
    assert finding.startswith("RH-F-")


def test_accession_survives_a_rollback_without_being_reused(db_session):
    """Sequences are non-transactional on purpose. A rolled-back insert
    burns its number — a gap is harmless, a reused accession would break
    every citation that already quoted it."""
    first = next_spectrum_accession(db_session)
    db_session.rollback()
    second = next_spectrum_accession(db_session)

    assert first != second


def test_spectrum_creation_assigns_an_accession(app_client, make_user, make_raw_file):
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)

    body = app_client.post("/spectra", json={"raw_file_id": str(raw_file.id)}).json()

    assert body["accession"].startswith("RH-S-")


def test_a_fork_gets_its_own_accession(app_client, make_user, make_raw_file):
    """Two records sharing a citable identifier is precisely what
    accessions must never allow."""
    owner = make_user()
    app_client.set_current_user(owner)
    raw_file = make_raw_file(owner)
    source = app_client.post("/spectra", json={"raw_file_id": str(raw_file.id)}).json()
    published = app_client.post(
        f"/spectra/{source['id']}/publish", json={"license_id": "CC-BY-4.0"}
    )
    assert published.status_code == 200, published.text

    forker = make_user()
    app_client.set_current_user(forker)
    fork = app_client.post(f"/spectra/{source['id']}/fork").json()

    assert fork["accession"] != source["accession"]
    assert fork["accession"].startswith("RH-S-")


# ------------------------------------------------------------------- handles


@pytest.mark.parametrize("handle", ["ada", "ada-lovelace", "user123", "a1b"])
def test_valid_handles_are_accepted(handle):
    assert validate_handle(handle) == handle


def test_handles_are_normalized_to_lowercase():
    assert validate_handle("  Ada-Lovelace  ") == "ada-lovelace"


@pytest.mark.parametrize(
    "handle",
    [
        "ab",  # too short
        "a" * 31,  # too long
        "-ada",  # leading dash
        "ada-",  # trailing dash
        "ada--lovelace",  # doubled dash
        "ada lovelace",  # space
        "ada_lovelace",  # underscore
        "ada.lovelace",  # dot — would need escaping in a citation string
        "adá",  # non-ASCII
        "ada/../etc",  # path traversal shape
    ],
)
def test_invalid_handles_are_rejected(handle):
    with pytest.raises(InvalidHandleError):
        validate_handle(handle)


@pytest.mark.parametrize("handle", ["api", "login", "search", "settings", "admin"])
def test_reserved_handles_are_rejected(handle):
    """A handle must never be able to shadow an application route."""
    with pytest.raises(InvalidHandleError, match="reserved"):
        validate_handle(handle)


def test_every_reserved_handle_would_otherwise_be_valid():
    """Guards the reserved list against rot: an entry that fails format
    validation anyway is dead weight and hides a typo."""
    for reserved in RESERVED_HANDLES:
        assert 3 <= len(reserved) <= 30, reserved
        # Reserved words must be rejected *as reserved*, not incidentally.
        with pytest.raises(InvalidHandleError, match="reserved"):
            validate_handle(reserved)


def test_suggest_derives_from_the_email_local_part():
    assert suggest_handle("ada.lovelace@example.com", "Ada Lovelace") == "ada-lovelace"


def test_suggest_falls_back_to_the_display_name():
    """An email local part too short or entirely reserved still has to
    yield something usable."""
    assert suggest_handle("me@example.com", "Ada Lovelace") == "ada-lovelace"


def test_suggest_never_raises_on_unusable_input():
    """A name in a non-Latin script must not dead-end sign-in."""
    assert suggest_handle("api@example.com", "上海") == "researcher"


def test_suggest_output_is_always_valid():
    for email, name in [
        ("ada.lovelace@x.com", "Ada Lovelace"),
        ("a@x.com", None),
        ("api@x.com", "上海"),
        ("UPPER.CASE@x.com", "Upper Case"),
        ("weird---dashes@x.com", None),
    ]:
        assert validate_handle(suggest_handle(email, name))


def test_uniquify_suffixes_on_collision():
    taken = {"ada", "ada-2"}
    assert uniquify_handle("ada", lambda h: h in taken) == "ada-3"


def test_uniquify_returns_the_base_when_free():
    assert uniquify_handle("ada", lambda _h: False) == "ada"


def test_uniquify_keeps_long_handles_within_the_length_cap():
    base = "a" * 30
    taken = {base}
    result = uniquify_handle(base, lambda h: h in taken)

    assert len(result) <= 30
    assert validate_handle(result)


# ------------------------------------------------------------ public profile


def test_public_profile_counts_published_work(fclient, make_user, make_raw_file):
    """Regression: `finding_count` was declared on the response model but
    never populated, so every profile reported 0 findings no matter how many
    the contributor had published."""
    from tests.test_findings import _finding, _spectrum

    owner = make_user()
    owner.handle = "ada-counts"
    fclient.set_current_user(owner)

    spectrum = _spectrum(fclient, make_raw_file, owner, publish=True)
    finding = _finding(fclient, title="Counted")
    fclient.post(f"/findings/{finding['id']}/spectra", json={"spectrum_id": spectrum["id"]})
    fclient.post(f"/findings/{finding['id']}/publish", json={"license_id": "CC-BY-4.0"})

    body = fclient.get("/users/by-handle/ada-counts").json()

    assert body["spectrum_count"] == 1
    assert body["finding_count"] == 1


def test_public_profile_excludes_unpublished_work(fclient, make_user, make_raw_file):
    """Counts must cover published work only — reporting how much
    unpublished work someone has is exactly what the draft state exists to
    keep private."""
    from tests.test_findings import _finding, _spectrum

    owner = make_user()
    owner.handle = "ada-private"
    fclient.set_current_user(owner)

    _spectrum(fclient, make_raw_file, owner, publish=False)
    _finding(fclient, title="Still a draft")

    body = fclient.get("/users/by-handle/ada-private").json()

    assert body["spectrum_count"] == 0
    assert body["finding_count"] == 0


def test_public_profile_never_exposes_email(fclient, make_user):
    """PublicProfileOut is a separate model from UserOut precisely so a
    field added to the authenticated shape can't leak onto a public page."""
    owner = make_user()
    owner.handle = "ada-noemail"
    fclient.set_current_user(owner)

    body = fclient.get("/users/by-handle/ada-noemail").json()

    assert "email" not in body


def test_public_profile_404s_for_unknown_handle(fclient):
    assert fclient.get("/users/by-handle/nobody-here").status_code == 404
