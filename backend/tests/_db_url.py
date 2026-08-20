"""Shared helper for resolving a *test* Postgres database URL.

The full test suite creates and drops every table (`Base.metadata.create_all`
/ `drop_all`) once per session. Running that directly against the app's dev
`DATABASE_URL` would silently wipe local dev data every time `make test`
runs. Instead, every test module that needs a live DB should call
`get_test_database_url()`, which derives a sibling database named
`<dbname>_test` from the configured `DATABASE_URL`, creates it if it doesn't
exist yet, and returns a connectable URL to *that* database — leaving the
real dev database untouched.

Returns None (never raises) if no Postgres is reachable at all, so callers
can skip DB-backed tests gracefully.
"""
from __future__ import annotations

import contextlib
import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import settings


def _test_db_name(dbname: str) -> str:
    return dbname if dbname.endswith("_test") else f"{dbname}_test"


def get_test_database_url() -> str | None:
    base_url = os.environ.get("DATABASE_URL", settings.DATABASE_URL)
    if not base_url:
        return None

    url = make_url(base_url)
    test_dbname = _test_db_name(url.database)
    test_url = url.set(database=test_dbname)

    # Connect to the *maintenance* DB (the original, non-"_test" one) to
    # create the test database if it's missing — CREATE DATABASE can't run
    # inside a transaction block, so use autocommit isolation. Any failure
    # here (e.g. no Postgres at all) just falls through to the reachability
    # check below, which returns None.
    with contextlib.suppress(Exception):
        admin_engine = create_engine(url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": test_dbname},
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{test_dbname}"'))
        admin_engine.dispose()

    try:
        engine = create_engine(test_url)
        with engine.connect():
            pass
        engine.dispose()
        # NOT str(test_url): SQLAlchemy's URL.__str__ hides the password as a
        # literal "***", so the returned string would carry "***" as the
        # actual password. That works against a trust-auth local Postgres
        # (password ignored) and then fails against any password-checking
        # server — exactly the local-pass/CI-fail split that found this.
        return test_url.render_as_string(hide_password=False)
    except Exception:  # noqa: BLE001 - any failure just means "no usable test DB"
        return None
