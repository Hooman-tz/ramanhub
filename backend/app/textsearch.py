"""Shared trigram search: the threshold, the predicate, and the ranking.

Four surfaces search text — the reference browse, the suggest palette, the
feed, and `/search/spectra`. They all want the same three things, and two of
them are easy to get subtly wrong, so they live here rather than being copied.

**The threshold is a GUC, not an argument.** Only the operator form
`search_text %> :q` can use a GIN trigram index; the function form
`word_similarity(:q, search_text) >= 0.35` cannot, and silently degrades to a
sequential scan. So the cutoff has to be set on the connection, per
transaction, before the query runs.

**`SET LOCAL`, never a bare `SET`.** Production points `DATABASE_URL` at a
pooled endpoint, so a bare `SET` would outlive the request and change the
cutoff for whoever got the connection next. `SET LOCAL` is transaction-scoped,
and `get_db` never commits, so it dies with the request.

**`word_similarity`, not `similarity`.** `similarity()` is normalized over the
whole string, so against a concatenated blob ("Calcite CaCO3 471-34-1 calcium
carbonate") it scores everything near zero. `word_similarity(q, blob)` scores
the query against the best matching *extent* of the blob, which is what a
typeahead means.
"""
from __future__ import annotations

from sqlalchemy import Float, case, func, or_, text
from sqlalchemy.orm import Session

# Measured against the local reference corpus:
#   word_similarity('calcyte', 'Calcite CaCO3 calcium carbonate') = 0.500
#   word_similarity('quarz',   'Quartz SiO2')                     = 0.667
#   word_similarity('cal',     'Calcite CaCO3')                   = 0.750
#   word_similarity('calcyte', 'Quartz SiO2')                     = 0.000
# Postgres' default of 0.6 rejects the first of those, i.e. it offers no typo
# tolerance at all. 0.35 clears every real typo above with margin while still
# leaving unrelated compounds at zero.
TRIGRAM_THRESHOLD = 0.35

# Below this, a query matches so much of the corpus that ranking is noise.
MIN_QUERY_LENGTH = 2


def apply_threshold(db: Session) -> None:
    """Set the trigram cutoff for this transaction. Call once per request,
    before any query using `text_predicate`.

    `set_config(..., is_local => true)` rather than the `SET LOCAL` statement:
    they mean the same thing, but `SET` will not accept a bind parameter, and
    interpolating the threshold into the SQL string to work around that is how
    you turn a tuning constant into an injection site.
    """
    db.execute(
        text("SELECT set_config('pg_trgm.word_similarity_threshold', :threshold, true)"),
        {"threshold": str(TRIGRAM_THRESHOLD)},
    )


def text_predicate(search_column, query: str):
    """Match `query` against a `search_text` column, using the index.

    The `ILIKE` arm is deliberately conditional. `gin_trgm_ops` can only
    accelerate `ILIKE '%x%'` when the pattern yields at least one trigram,
    which takes three non-wildcard characters. OR-ing an unindexable `ILIKE`
    against an indexable `%>` forces Postgres to sequential-scan the whole
    table — precisely the behaviour this module exists to remove. So below
    three characters we rely on `%>` alone, which still works at two because
    pg_trgm space-pads words ('fe' -> {"  f", " fe"}).
    """
    clauses = [search_column.op("%>")(query)]
    if len(query) >= 3:
        clauses.append(search_column.ilike(f"%{query}%"))
    return or_(*clauses)


def text_rank(primary_column, search_column, query: str):
    """Score a row 0..2.5, so exact beats prefix beats substring beats fuzzy.

    `primary_column` is the one field a person is most likely to have typed
    (a compound name, a title, a handle); `search_column` is the blob. The
    two `case` terms are what stop a 685-row corpus from answering "calcite"
    with "Sodium calcitrate" just because it sorted first.
    """
    lowered = func.lower(primary_column)
    needle = query.lower()
    return (
        case((lowered == needle, 1.0), else_=0.0)
        + case((lowered.like(needle + "%"), 0.5), else_=0.0)
        + func.word_similarity(query, search_column).cast(Float)
    )
