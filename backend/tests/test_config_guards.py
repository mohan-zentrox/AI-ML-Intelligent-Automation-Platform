"""Regression tests for startup-safety guards and import hygiene.

Each test here corresponds to a defect that shipped once:

  * `app.main` could not be imported at all (circular import) even though the
    whole suite passed, because conftest.py happens to import `app.db.base`
    first and that ordering hides the cycle.
  * the demo roster from docs/TEAM.md was seeded unconditionally on startup,
    so any deployment got an admin account whose password is in the README.
  * SECRET_KEY defaulted to a placeholder that is published in this repo, and
    nothing refused to boot with it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import DEV_SECRET_KEY, Settings

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _settings(**overrides) -> Settings:
    """Build Settings from explicit values only.

    `_env_file=None` stops a developer's real backend/.env from leaking in and
    making these assertions depend on an untracked file.
    """
    return Settings(_env_file=None, **overrides)


# --------------------------------------------------------------------------
# Circular-import regression (app/db/base.py <-> app/models/*)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "module",
    [
        "app.main",  # what uvicorn imports
        "app.core.deps",  # the module whose import order originally triggered it
        "app.models.api_key",  # the model that lost the race
    ],
)
def test_module_imports_in_a_clean_interpreter(module: str) -> None:
    """Import each module as the *first* app import in a fresh interpreter.

    This has to be a subprocess: once pytest has imported conftest, the
    modules are already in sys.modules in a working order, so an in-process
    import can never reproduce the cycle.
    """
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"`import {module}` failed as a first import - likely a circular import:\n"
        f"{result.stderr}"
    )


def test_base_metadata_has_every_table() -> None:
    """`app.db.base` must still register all models after the Base split."""
    from app.db.base import Base

    assert {
        "users",
        "api_keys",
        "documents",
        "chunks",
        "query_logs",
        "review_items",
        "feedback",
        "usage_logs",
    } <= set(Base.metadata.tables)


def test_models_do_not_import_the_registry_hub() -> None:
    """Models must import Base from `base_class`, never from the hub.

    Importing the hub from a model is precisely what reintroduces the cycle,
    and it would pass the suite while breaking `uvicorn app.main:app`.
    """
    offenders = [
        path.name
        for path in (BACKEND_ROOT / "app" / "models").glob("*.py")
        if "from app.db.base import" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"these models import the registry hub: {offenders}"


# --------------------------------------------------------------------------
# Demo-user seeding
# --------------------------------------------------------------------------


def test_demo_seeding_defaults_on_for_local() -> None:
    assert _settings(ENVIRONMENT="local").should_seed_demo_users is True


@pytest.mark.parametrize("environment", ["production", "staging", "prod", "Production"])
def test_demo_seeding_defaults_off_outside_local(environment: str) -> None:
    settings = _settings(ENVIRONMENT=environment, SECRET_KEY="a-real-secret")
    assert settings.should_seed_demo_users is False


def test_explicit_opt_out_is_honoured_locally() -> None:
    assert _settings(ENVIRONMENT="local", SEED_DEMO_USERS=False).should_seed_demo_users is False


def test_seeding_demo_users_outside_local_is_rejected() -> None:
    with pytest.raises(ValidationError, match="SEED_DEMO_USERS"):
        _settings(ENVIRONMENT="production", SECRET_KEY="a-real-secret", SEED_DEMO_USERS=True)


# --------------------------------------------------------------------------
# SECRET_KEY
# --------------------------------------------------------------------------


def test_placeholder_secret_key_is_allowed_locally() -> None:
    """The placeholder must not block local dev - only deployed environments.

    Passed explicitly rather than relying on the field default, because
    conftest.py exports SECRET_KEY into os.environ and pydantic-settings reads
    the environment whether or not an _env_file is in play.
    """
    settings = _settings(ENVIRONMENT="local", SECRET_KEY=DEV_SECRET_KEY)
    assert settings.SECRET_KEY == DEV_SECRET_KEY
    assert settings.is_local is True


@pytest.mark.parametrize("environment", ["production", "staging", "dev"])
def test_placeholder_secret_key_is_rejected_outside_local(environment: str) -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _settings(ENVIRONMENT=environment, SECRET_KEY=DEV_SECRET_KEY)


def test_real_secret_key_boots_outside_local() -> None:
    settings = _settings(ENVIRONMENT="production", SECRET_KEY="x" * 48)
    assert settings.is_local is False


# --------------------------------------------------------------------------
# CORS_ORIGINS parsing
#
# These go through a real environment variable in a subprocess, not just a
# Settings(...) kwarg. That distinction matters: pydantic-settings decodes
# complex fields inside EnvSettingsSource, so a `list[str]` annotation blows up
# on a comma-separated env var *before* any validator runs, while the exact
# same value passed as a kwarg sails through. Asserting only on kwargs is how
# this bug hid the first time.
# --------------------------------------------------------------------------


def _cors_via_env(value: str) -> list[str]:
    """Read CORS_ORIGINS=<value> from the environment in a fresh interpreter."""
    code = (
        "from app.core.config import Settings;"
        "import json;"
        "print(json.dumps(Settings().cors_origins))"
    )
    env = {
        **os.environ,
        "CORS_ORIGINS": value,
        "ENVIRONMENT": "local",
        "SECRET_KEY": "test-secret-key",
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        "CORS_ORIGINS=" + repr(value)
        + " failed to load from the environment: "
        + result.stderr
    )
    return json.loads(result.stdout)


def test_cors_origins_comma_separated_from_env() -> None:
    assert _cors_via_env("https://a.example, https://b.example") == [
        "https://a.example",
        "https://b.example",
    ]


def test_cors_origins_single_value_from_env() -> None:
    assert _cors_via_env("https://only.example") == ["https://only.example"]


def test_cors_origins_json_array_from_env() -> None:
    assert _cors_via_env('["https://a.example", "https://b.example"]') == [
        "https://a.example",
        "https://b.example",
    ]


def test_cors_origins_empty_from_env() -> None:
    assert _cors_via_env("") == []


def test_cors_origins_default_covers_the_vite_dev_server() -> None:
    assert "http://localhost:5173" in _settings(ENVIRONMENT="local").cors_origins


def test_cors_origins_ignores_blank_entries() -> None:
    settings = _settings(
        ENVIRONMENT="local",
        CORS_ORIGINS="https://a.example,,  ,https://b.example",
    )
    assert settings.cors_origins == ["https://a.example", "https://b.example"]


def test_cors_origins_rejects_malformed_json() -> None:
    settings = _settings(ENVIRONMENT="local", CORS_ORIGINS='["unterminated')
    with pytest.raises(ValueError, match="does not parse"):
        _ = settings.cors_origins
