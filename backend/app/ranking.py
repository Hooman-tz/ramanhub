"""Relevance scoring, defined once and shared by search and the feed.

## The policy change this file encodes

The architecture doc (Module 4) said social signals must NEVER influence
core scientific search: "Social features (upvote/comment) stay quarantined
to a separate Trending feed and never affect core search ranking."

That rule has been **deliberately reversed** by a product decision: the
platform is meant to work as a social network for scientists, and a
discovery surface where engagement counts for nothing does not behave like
one. This module is where that reversal lives.

The concern the original rule was protecting against is real and has not
gone away: popularity-weighted ranking can float a well-liked spectrum above
a better-matched one, and citation-style metrics are self-reinforcing —
things that rank highly get seen, get voted on, and rank higher still. Two
mitigations, both deliberate:

1. **It is explicit and switchable.** `sort=` is a first-class parameter
   with `newest`, `engagement` and `snr` alongside `relevance`, so a user
   who wants a popularity-free ordering can have one. It is not a hidden
   thumb on the scale.
2. **Engagement is capped and time-decayed, not linear.** A logarithmic
   transform means the 50th vote moves a result far less than the 5th, so a
   single viral item cannot bury an entire result set, and the decay means
   ranking reflects current interest rather than accumulated history.

Objective quality still dominates the blend by weight. Engagement breaks
ties between comparable results; it does not overrule a better match.

Trending remains a separate feed with different semantics (pure engagement
within a window). It is not merged into search.
"""
from __future__ import annotations

from sqlalchemy import case, func, literal, select
from sqlalchemy.sql.elements import ColumnElement

# Relative weights of the blended `relevance` score. Objective signals
# (recency, DOI verification) outweigh engagement on purpose — see above.
W_ENGAGEMENT = 1.0
W_RECENCY = 1.5
W_DOI_VERIFIED = 0.75

# Shares weigh more than votes, per share, and deliberately so. A vote is one
# click of approval; a share is someone putting the item in front of their own
# followers, which costs them a little reputation if it is bad. That makes it
# the more expensive signal to fake, and the more informative one.
#
# It is NOT weighted so much higher that a handful of shares can outrank
# recency — the same containment argument that keeps W_ENGAGEMENT below
# W_RECENCY applies here.
W_SHARES = 1.5

# Engagement half-life. 30 days is chosen to match how a paper's attention
# actually behaves: a preprint's discussion is largely over within a month,
# so a vote from last year should not still be steering today's front page.
ENGAGEMENT_HALFLIFE_DAYS = 30.0

# Recency half-life, deliberately longer than the engagement one. Spectral
# data does not go stale the way discussion does — a good reference spectrum
# from two years ago is still a good reference spectrum.
RECENCY_HALFLIFE_DAYS = 365.0


def _halflife_decay(age_days: ColumnElement, halflife: float) -> ColumnElement:
    """exp(-ln2 * age / halflife) — 1.0 when brand new, 0.5 at one
    half-life, asymptotically 0. Clamped at 0 so a future timestamp (clock
    skew, a backdated import) can't score above a fresh item."""
    return func.exp(-0.6931471805599453 * func.greatest(age_days, literal(0.0)) / halflife)


def age_in_days(timestamp_column: ColumnElement) -> ColumnElement:
    """Age of `timestamp_column` in fractional days, as SQL."""
    return func.extract("epoch", func.now() - timestamp_column) / 86400.0


def engagement_score(vote_count: ColumnElement, age_days: ColumnElement) -> ColumnElement:
    """Log-compressed, time-decayed engagement.

    `ln(1 + votes)` rather than raw votes: the difference between 0 and 5
    votes is meaningful signal, the difference between 100 and 200 is mostly
    noise about how long something has been visible. Without the compression
    one viral item outranks every well-matched result on the page.
    """
    return func.ln(1.0 + func.coalesce(vote_count, 0)) * _halflife_decay(
        age_days, ENGAGEMENT_HALFLIFE_DAYS
    )


def recency_score(age_days: ColumnElement) -> ColumnElement:
    return _halflife_decay(age_days, RECENCY_HALFLIFE_DAYS)


def relevance_score(
    vote_count: ColumnElement,
    timestamp_column: ColumnElement,
    doi_column: ColumnElement,
    share_count: ColumnElement | None = None,
) -> ColumnElement:
    """The blended default ordering.

    DOI-verified work gets a fixed bonus rather than a multiplier: it marks
    "this passed peer review", which is a one-time quality signal, not
    something that should compound with popularity.
    """
    age = age_in_days(timestamp_column)
    # A CASE, not cast(bool AS float): Postgres refuses to coerce boolean to
    # a numeric type directly ("cannot cast type boolean to double
    # precision").
    doi_bonus = case((doi_column.is_not(None), literal(W_DOI_VERIFIED)), else_=literal(0.0))
    score = (
        W_ENGAGEMENT * engagement_score(vote_count, age)
        + W_RECENCY * recency_score(age)
        + doi_bonus
    )
    if share_count is not None:
        # Same log compression and time decay as votes: one item going viral
        # must not permanently outrank the corpus, and an old well-shared item
        # decays back toward its objective standing.
        score = score + W_SHARES * engagement_score(share_count, age)
    return score


def vote_count_subquery(vote_model, vote_target_column, entity_id_column):
    """Correlated scalar subquery counting votes for each row of the outer
    query.

    A scalar subquery rather than a LEFT JOIN + GROUP BY, for two reasons.
    The join form forces every selected column into the GROUP BY, which
    breaks the moment someone adds a field to the result shape. And it must
    be a LEFT-equivalent: an INNER join would drop every zero-vote row,
    which on a search endpoint would silently hide most of the corpus —
    a mistake worth naming, because `app.routers.trending` uses an inner
    join *on purpose* (a zero-vote Trending page is uninformative) and
    copying that pattern here would be a bug.
    """
    return (
        select(func.count(vote_model.id))
        .where(vote_target_column == entity_id_column)
        .scalar_subquery()
    )
