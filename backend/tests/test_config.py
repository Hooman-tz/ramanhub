"""Regression test for the `.env` resolution bug: `Settings.model_config`'s
`env_file` must be resolved to an absolute path anchored at the repo root,
not a bare relative string. A bare ".env" resolves against the process's
CWD at import time — the README's documented fast-iteration workflow (`cd
backend && uv run uvicorn app.main:app --reload`) runs with `backend/` as
CWD while `.env` lives at the repo root, so a bare relative path there
silently loads zero secrets in exactly the setup most local dev uses.
"""
from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic_settings import SettingsConfigDict

from app.config import Settings


def test_env_file_is_an_absolute_path():
    """A relative env_file is resolved against CWD by pydantic-settings, not
    against this file's location — which is exactly the footgun being
    guarded against here."""
    env_file = Settings.model_config["env_file"]
    assert Path(env_file).is_absolute()


def test_env_file_points_at_the_repo_root_env():
    env_file = Path(Settings.model_config["env_file"])
    repo_root = Path(__file__).resolve().parent.parent.parent
    assert env_file == repo_root / ".env"


def test_database_url_scheme_is_normalized_to_psycopg3():
    """Render/Railway/Heroku-style managed Postgres hands out postgres:// or
    postgresql:// URLs; bare postgresql:// selects the (uninstalled) psycopg2
    driver in SQLAlchemy, so both must normalize to postgresql+psycopg://."""
    for given in ("postgres://u:p@h:5432/db", "postgresql://u:p@h:5432/db"):
        assert (
            Settings(DATABASE_URL=given).DATABASE_URL == "postgresql+psycopg://u:p@h:5432/db"
        )
    already = "postgresql+psycopg://u:p@h:5432/db"
    assert Settings(DATABASE_URL=already).DATABASE_URL == already


def test_an_absolute_env_file_loads_regardless_of_cwd(tmp_path, monkeypatch):
    """The actual bug, reproduced without touching the real `.env` (which
    may hold real secrets): a Settings subclass pointed at a scratch env
    file via an absolute path must still find it after `cd`ing elsewhere —
    exactly what `cd backend && uv run ...` does relative to the repo-root
    `.env`. A bare relative env_file would fail this same test once CWD is
    no longer the file's own directory."""
    scratch_env = tmp_path / ".env"
    marker = "test-marker-value-not-a-real-secret"
    scratch_env.write_text(f"GOOGLE_CLIENT_ID={marker}\n")

    class ScratchSettings(Settings):
        model_config: ClassVar[SettingsConfigDict] = {
            **Settings.model_config,
            "env_file": str(scratch_env),
        }

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    assert ScratchSettings().GOOGLE_CLIENT_ID == marker
