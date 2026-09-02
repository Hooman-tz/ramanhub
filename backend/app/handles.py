"""Public URL handles for user profiles (`/u/<handle>`).

A profile that lives at a UUID is not a profile anyone links to. Handles are
what make a contributor citable and followable — the "user profile ID" half
of tying data to the person who produced it, alongside their ORCID.

The stored column is `User.profile_handle`; this module is where the naming
rules live so they are testable without Postgres.

Rules, and why:

- Lowercase `[a-z0-9-]`, 3-30 chars, no leading/trailing/doubled dashes.
  Narrow on purpose: handles appear in URLs and in citation strings, so
  anything needing escaping in either is excluded outright.
- Reserved words are refused so a handle can never shadow an application
  route (`/u/settings` is fine, but `/api`, `/login` and friends would be
  ambiguous if handles were ever hoisted to the URL root, which is the
  usual next step).
- Derived handles get a numeric suffix on collision rather than failing.
  Sign-in must never dead-end because someone else already took your email's
  local part.
"""

from __future__ import annotations

import re

# Lowercase letters/digits, plus `.` `_` `-` as internal separators. Must
# start and end alphanumeric; no two separators in a row (blocks `..`, `__`,
# `._`, `--`, …). Length is enforced separately (MIN/MAX_LENGTH).
HANDLE_REGEX = re.compile(r"^[a-z0-9](?:[a-z0-9]|[._-](?![._-])){1,28}[a-z0-9]$")
_SEPARATOR_RUN_RE = re.compile(r"[._-]{2}")
MIN_LENGTH = 3
MAX_LENGTH = 30

# Route names and platform terms a user handle must not occupy.
#
# Only entries that would otherwise PASS format validation belong here.
# The short URL prefixes (/s/, /f/, /u/) and "me" are already unreachable
# as handles because of the 3-character minimum, so listing them would be
# dead weight that hides typos — a test asserts this list stays live.
RESERVED_HANDLES = frozenset(
    {
        "about",
        "admin",
        "api",
        "auth",
        "callback",
        "comments",
        "compare",
        "contact",
        "dashboard",
        "docs",
        "explore",
        "export",
        "feed",
        "findings",
        "health",
        "help",
        "home",
        "library",
        "license",
        "licenses",
        "login",
        "logout",
        "new",
        "null",
        "privacy",
        "profile",
        "processing",
        "ramanhub",
        "routines",
        "search",
        "settings",
        "signin",
        "signout",
        "signup",
        "spectra",
        "spectrum",
        "static",
        "support",
        "terms",
        "trending",
        "undefined",
        "upload",
        "user",
        "users",
        "v1",
    }
)


class InvalidHandleError(ValueError):
    """Raised for a handle that fails validation or is reserved."""


def normalize_handle(raw: str) -> str:
    """Lowercase and trim. Does not validate — pair with `validate_handle`."""
    return raw.strip().lower()


def validate_handle(raw: str) -> str:
    """Return the normalized handle, or raise `InvalidHandleError`."""
    handle = normalize_handle(raw)
    if len(handle) < MIN_LENGTH or len(handle) > MAX_LENGTH:
        raise InvalidHandleError(f"Handles must be {MIN_LENGTH}-{MAX_LENGTH} characters long.")
    if not HANDLE_REGEX.match(handle):
        raise InvalidHandleError(
            "Handles may use lowercase letters, numbers, dots, underscores and "
            "dashes, and must start and end with a letter or number."
        )
    if _SEPARATOR_RUN_RE.search(handle):
        raise InvalidHandleError("Handles may not contain two dots/underscores/dashes in a row.")
    if handle in RESERVED_HANDLES:
        raise InvalidHandleError(f"'{handle}' is reserved and can't be used as a handle.")
    return handle


def suggest_handle(email: str, display_name: str | None = None) -> str:
    """Build a plausible base handle from what an OAuth provider gives us.

    Never raises: falls back to a generic base if neither the email local
    part nor the display name survives sanitizing (e.g. a name written
    entirely in a non-Latin script). Uniqueness is the caller's job — see
    `uniquify_handle`.
    """
    for candidate in (email.split("@", 1)[0], display_name or ""):
        cleaned = re.sub(r"[^a-z0-9]+", "-", candidate.lower()).strip("-")
        cleaned = re.sub(r"-{2,}", "-", cleaned)[:MAX_LENGTH].rstrip("-")
        if len(cleaned) >= MIN_LENGTH and cleaned not in RESERVED_HANDLES:
            return cleaned
    return "researcher"


def assign_handle(db, email: str, display_name: str | None = None) -> str:
    """Pick a free handle for a new (or handle-less) account.

    The only database-aware function here; everything above stays pure so
    the naming rules are testable without Postgres.

    Note the uniqueness check is advisory, not a lock: two simultaneous
    sign-ups deriving the same base could both see it free. The unique index
    on `users.profile_handle` is the real guarantee — the loser gets an
    IntegrityError and retries sign-in, which is rare enough to be the right
    trade against serializing every account creation.
    """
    from app.models.user import User

    def exists(candidate: str) -> bool:
        return db.query(User.id).filter(User.profile_handle == candidate).first() is not None

    return uniquify_handle(suggest_handle(email, display_name), exists)


def uniquify_handle(base: str, exists: object) -> str:
    """Append `-2`, `-3`, ... until `exists(handle)` is False.

    `exists` is a callable taking a handle and returning bool, so this stays
    a pure function testable without a database.
    """
    if not exists(base):
        return base
    suffix = 2
    while True:
        # Truncate the base so base+suffix still fits the length cap.
        candidate = f"{base[: MAX_LENGTH - len(str(suffix)) - 1].rstrip('-')}-{suffix}"
        if not exists(candidate):
            return candidate
        suffix += 1
