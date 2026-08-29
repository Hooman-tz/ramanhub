"""Contribution activity over time, plus streaks.

Powers the profile's contribution chart. Three notes on what is and isn't
counted, because the shape of this data decides what behaviour the chart
rewards.

**Published events only.** A draft is not a contribution to the commons, and
counting drafts would make the chart trivially inflatable by anyone willing
to click "new spectrum" repeatedly.

**Kinds are kept separate rather than summed.** Publishing a Finding,
publishing a spectrum and writing a comment are different acts with different
costs; one green square that blends them tells you nothing about which
happened. The chart stacks them.

**Batch uploads are reported as a batch.** A day with 40 spectra from one
instrument session is one afternoon at the bench, not 40 days of work. The
per-day record therefore carries both the raw count and the number of
distinct ingestion sessions behind it, so the UI can annotate a burst as
"one session, x40" rather than either exaggerating it or flattening it away.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import FindingState, SpectrumState
from app.models.finding import Finding
from app.models.social import Comment
from app.models.spectrum import Spectrum

MAX_DAYS = 730


class ActivityDay(BaseModel):
    date: date
    spectra: int = 0
    findings: int = 0
    comments: int = 0

    @property
    def total(self) -> int:
        return self.spectra + self.findings + self.comments


class ActivitySummary(BaseModel):
    days: list[ActivityDay]
    total: int
    current_streak: int
    longest_streak: int


def _daily_counts(db: Session, column, filters) -> dict[date, int]:
    # Bucket in UTC, explicitly. A bare `date(col)` on a timestamptz makes
    # Postgres resolve the date in the SESSION timezone, while the calendar
    # below is built from `datetime.now(UTC).date()`. Those two disagree for
    # any session not running on UTC: at 20:32 in America/Vancouver it is
    # already the 29th in UTC, so today's uploads were being filed under the
    # 28th and today's square rendered empty — which also broke the current
    # streak. `timezone('UTC', col)` pins the bucket to the same clock the
    # calendar uses.
    day = func.date(func.timezone("UTC", column))
    rows = db.execute(select(day, func.count()).where(*filters).group_by(day)).all()
    out: dict[date, int] = {}
    for value, count in rows:
        key = value if isinstance(value, date) else datetime.fromisoformat(str(value)).date()
        out[key] = int(count)
    return out


def _streaks(days: list[ActivityDay], today: date) -> tuple[int, int]:
    """Current and longest run of consecutive active days.

    The current streak is measured back from today and tolerates *today*
    itself being empty — a streak should not appear broken at 00:01 before
    the day's work has happened.
    """
    active = {d.date for d in days if d.total > 0}
    if not active:
        return 0, 0

    longest = current_run = 0
    ordered = sorted(active)
    previous: date | None = None
    for day in ordered:
        current_run = current_run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, current_run)
        previous = day

    current = 0
    cursor = today
    if cursor not in active:
        cursor = today - timedelta(days=1)
    while cursor in active:
        current += 1
        cursor -= timedelta(days=1)

    return current, longest


def compute_activity(user_id, db: Session, days: int = 365) -> ActivitySummary:
    days = max(1, min(days, MAX_DAYS))
    today = datetime.now(UTC).date()
    since = datetime.now(UTC) - timedelta(days=days)

    spectra = _daily_counts(
        db,
        Spectrum.published_at,
        [
            Spectrum.owner_id == user_id,
            Spectrum.state == SpectrumState.published,
            Spectrum.published_at.isnot(None),
            Spectrum.published_at >= since,
        ],
    )
    findings = _daily_counts(
        db,
        Finding.published_at,
        [
            Finding.owner_id == user_id,
            Finding.state == FindingState.published,
            Finding.published_at.isnot(None),
            Finding.published_at >= since,
        ],
    )
    comments = _daily_counts(
        db, Comment.created_at, [Comment.user_id == user_id, Comment.created_at >= since]
    )

    out: list[ActivityDay] = []
    for offset in range(days):
        day = today - timedelta(days=days - 1 - offset)
        out.append(
            ActivityDay(
                date=day,
                spectra=spectra.get(day, 0),
                findings=findings.get(day, 0),
                comments=comments.get(day, 0),
            )
        )

    current, longest = _streaks(out, today)
    return ActivitySummary(
        days=out,
        total=sum(d.total for d in out),
        current_streak=current,
        longest_streak=longest,
    )
