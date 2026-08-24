"""Spectrum draft/published/embargoed state machine, plus the single
row-level access-control helper the rest of this module's security rests on.

`embargo_release_at` is evaluated at read time (`effective_state` /
`require_owner_or_public`) rather than via a background sweeper that flips
`state` in the DB — there's no scheduler infra yet, and read-time evaluation
is simpler and can't drift.
"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.enums import SpectrumState
from app.models.spectrum import Spectrum
from app.models.user import User


def _as_aware_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


def _is_private(spectrum: Spectrum) -> bool:
    """True if `spectrum` should NOT be visible to a non-owner right now."""
    if spectrum.state == SpectrumState.draft:
        return True
    if spectrum.state == SpectrumState.embargoed:
        release_at = spectrum.embargo_release_at
        if release_at is None:
            return True
        return _as_aware_utc(release_at) > datetime.now(UTC)
    return False  # published


def require_owner_or_public(resource, user: User | None) -> None:
    """The single load-bearing row-level access-control gate for this
    module. Call it immediately after loading any owner-scoped,
    state-gated resource (currently `Spectrum`; any future resource with
    the same `owner_id` + `state`/`embargo_release_at` shape should reuse
    this rather than reimplementing the check) and BEFORE returning it (or
    data derived from it, e.g. its ledger steps) from a read endpoint.

    Contract:
      - `resource` must expose `.owner_id` and either `.state` == "draft" /
        an embargoed state with `.embargo_release_at`, or be otherwise
        public.
      - `user` is the requester, or `None` if unauthenticated.
      - If `user` owns `resource` (`user is not None and resource.owner_id
        == user.id`): always allowed, regardless of state — owners can
        always see their own drafts/embargoed items.
      - Otherwise: allowed only if the resource is NOT private (i.e. it's
        published, or embargoed with `embargo_release_at` already in the
        past).
      - On denial: raises `HTTPException(404)` — deliberately 404, never
        403, so unauthorized requesters cannot distinguish "doesn't exist"
        from "exists but is private". Every router in this module MUST
        preserve this 404-not-403 choice when using this helper.

    Usage pattern in a router:
        spectrum = db.get(Spectrum, spectrum_id)
        if spectrum is None:
            raise HTTPException(status_code=404, detail="Not found")
        require_owner_or_public(spectrum, user)  # may itself raise 404
        ...
    """
    is_owner = user is not None and resource.owner_id == user.id
    if is_owner:
        return
    if _is_private(resource):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def require_finding_readable(finding, user: User | None) -> None:
    """The Finding equivalent of `require_owner_or_public`.

    Written separately rather than reusing that helper, even though the two
    are nearly identical. `_is_private` compares `resource.state` against
    `SpectrumState.draft`; a `FindingState.draft` would compare equal to it
    only because both are `str` enums that happen to share the value
    "draft". That is an accident of the mixin, not a designed relationship,
    and it would break silently the moment either enum's values diverged —
    failing OPEN, exposing every draft Finding. Access control should not
    rest on a coincidence.

    Same 404-not-403 contract: a non-owner cannot distinguish "no such
    Finding" from "someone's private draft".
    """
    from app.models.enums import FindingState

    if user is not None and finding.owner_id == user.id:
        return
    if finding.state != FindingState.published:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def effective_state(spectrum: Spectrum) -> str:
    """Return `"published"` if `spectrum` is embargoed and its
    `embargo_release_at` has already passed, else the raw `state` value.
    Computed at read time — no background job flips `state` in the DB."""
    if (
        spectrum.state == SpectrumState.embargoed
        and spectrum.embargo_release_at is not None
        and _as_aware_utc(spectrum.embargo_release_at) <= datetime.now(UTC)
    ):
        return SpectrumState.published.value
    state = spectrum.state
    return state.value if isinstance(state, SpectrumState) else state


def publish(spectrum: Spectrum, license_id: str, db: Session, doi: str | None = None) -> Spectrum:
    """Draft -> published. Requires `license_id`. Sets `published_at=now()`.

    `doi` (Module 4/Module 3 integration seam): if provided (non-empty),
    sets `spectrum.doi` before committing. A non-null `doi` is what marks a
    spectrum "DOI-verified" for the Module 4 trust-tier search filter, as
    opposed to "community" (no DOI). `doi` is expected to come from Module
    3's DOI lookup feature; this module doesn't validate/resolve it, just
    stores whatever the caller passes.
    """
    if spectrum.state != SpectrumState.draft:
        raise HTTPException(status_code=400, detail="Only draft spectra can be published")
    if not license_id:
        raise HTTPException(status_code=422, detail="license_id is required to publish")
    spectrum.license_id = license_id
    spectrum.state = SpectrumState.published
    spectrum.published_at = datetime.now(UTC)
    if doi:
        spectrum.doi = doi
    db.add(spectrum)
    db.commit()
    db.refresh(spectrum)
    return spectrum


def embargo(
    spectrum: Spectrum,
    license_id: str,
    embargo_release_at: datetime,
    db: Session,
    doi: str | None = None,
) -> Spectrum:
    """Draft -> embargoed. Requires `license_id` and a future
    `embargo_release_at`. `doi` behaves as in `publish` above — sets
    `spectrum.doi` if provided, before committing."""
    if spectrum.state != SpectrumState.draft:
        raise HTTPException(status_code=400, detail="Only draft spectra can be embargoed")
    if not license_id:
        raise HTTPException(status_code=422, detail="license_id is required")
    release_at = _as_aware_utc(embargo_release_at)
    if release_at <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="embargo_release_at must be in the future")
    spectrum.license_id = license_id
    spectrum.state = SpectrumState.embargoed
    spectrum.embargo_release_at = release_at
    if doi:
        spectrum.doi = doi
    db.add(spectrum)
    db.commit()
    db.refresh(spectrum)
    return spectrum


def release_embargo_early(spectrum: Spectrum, db: Session) -> Spectrum:
    """Embargoed -> published, immediately. Ownership must already have been
    checked by the caller (routers do this before invoking state-machine
    transitions, consistent with `publish`/`embargo` above)."""
    if spectrum.state != SpectrumState.embargoed:
        raise HTTPException(status_code=400, detail="Only embargoed spectra can be released early")
    spectrum.state = SpectrumState.published
    spectrum.published_at = datetime.now(UTC)
    db.add(spectrum)
    db.commit()
    db.refresh(spectrum)
    return spectrum
