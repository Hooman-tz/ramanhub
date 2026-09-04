"""The SQL behind every `search_text` column, in one place.

Each searchable table carries a STORED generated column that concatenates the
handful of fields a person might actually type, and a single GIN trigram index
over it. One blob per table rather than one index per column: the alternative
needed ~9 GIN indexes and *still* could not reach the JSONB columns
(`common_names`, `tags`, `research_interests`), because a plain trigram index
cannot be built over `jsonb_array_elements_text()` — set-returning functions are
forbidden in both index expressions and generated columns.

These constants are imported by the models AND copied into the Alembic revision
that first creates the columns. Postgres stores the expression it was given, so
editing a string here does NOT alter an existing column: a change to any
expression below needs its own migration that drops and re-adds the column.

Two deliberate restrictions, both load-bearing:

- `left(..., 600)` on the long prose fields. Trigram-indexing a full abstract is
  the one genuinely expensive option here, and typeahead does not need it.
- `users.search_text` excludes `bio` (public, but long-tail noise that makes
  people-search imprecise) and `email` (must never be searchable).

Because these are `Computed`, SQLAlchemy leaves them out of INSERT/UPDATE, so no
construction site anywhere in the app needs to know they exist.
"""
from __future__ import annotations


def _json_words(column: str) -> str:
    """Flatten a JSONB array of strings into space-separated words.

    `#>>` is `jsonb_extract_path_text`, which `pg_proc` declares IMMUTABLE — the
    requirement for a generated column. An empty path returns the whole
    document's text serialization, identical to `::text` but without relying on
    an I/O-cast immutability inference.

    The character class `[][",]` is the literal set `]`, `[`, `"`, `,` (the `]`
    must come first to be read as a literal). Stripping it leaves the trigram
    set as words rather than JSON punctuation:
    `["calcite","calcium carbonate"]` -> `  calcite    calcium carbonate  `.

    NULL in, NULL out — every caller wraps this in `coalesce(..., '')`.
    """
    return f"regexp_replace({column} #>> '{{}}'::text[], '[][\",]', ' ', 'g')"


REFERENCE_SEARCH_SQL = (
    "coalesce(compound_name, '') || ' ' || "
    "coalesce(mineral_name, '') || ' ' || "
    "coalesce(chemical_formula, '') || ' ' || "
    "coalesce(cas_number, '') || ' ' || "
    f"coalesce({_json_words('common_names')}, '')"
)

# `accession` is folded in so typing `RH-S-000042` hits the same index as a
# title search, with no special-case query path.
SPECTRUM_SEARCH_SQL = (
    "coalesce(title, '') || ' ' || "
    "coalesce(material_type, '') || ' ' || "
    "coalesce(accession, '') || ' ' || "
    "left(coalesce(description, ''), 600)"
)

FINDING_SEARCH_SQL = (
    "coalesce(title, '') || ' ' || "
    "coalesce(accession, '') || ' ' || "
    f"coalesce({_json_words('tags')}, '') || ' ' || "
    "left(coalesce(abstract_md, ''), 600)"
)

USER_SEARCH_SQL = (
    "coalesce(display_name, '') || ' ' || "
    "coalesce(profile_handle, '') || ' ' || "
    "coalesce(orcid_name, '') || ' ' || "
    "coalesce(affiliation, '') || ' ' || "
    f"coalesce({_json_words('research_interests')}, '')"
)
