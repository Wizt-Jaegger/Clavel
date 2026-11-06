"""Synthetic settings and credentials prove configuration mechanics only."""

import os
from pathlib import Path
import subprocess
import traceback

import pytest

from clavel.core.settings import ConfigurationError, load_settings


ROOT = Path(__file__).resolve().parents[1]
FAKE_URL = "postgresql://synthetic_user:synthetic_password@localhost:5432/synthetic_db"


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Read only synthetic configuration, never a developer's private files."""
    monkeypatch.chdir(tmp_path)
    for key in tuple(os.environ):
        if key.lower() in {"database_url", "app_env"}:
            monkeypatch.delenv(key)


def test_missing_database_url():
    with pytest.raises(ConfigurationError, match="database_url: missing"):
        load_settings(env_file=None)


@pytest.mark.parametrize("value", ["", "synthetic_password", "https://synthetic_password.invalid", "postgresql://"])
def test_malformed_database_url_is_redacted(monkeypatch, value):
    monkeypatch.setenv("DATABASE_URL", value)
    with pytest.raises(ConfigurationError, match="database_url: value_error") as caught:
        load_settings(env_file=None)
    displayed = "".join(traceback.format_exception(caught.value))
    assert "synthetic_password" not in displayed
    assert "input_value" not in displayed


def test_invalid_environment_is_redacted(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    monkeypatch.setenv("APP_ENV", "synthetic_sensitive_input")
    with pytest.raises(ConfigurationError, match="app_env: literal_error") as caught:
        load_settings(env_file=None)
    assert "synthetic_sensitive_input" not in "".join(traceback.format_exception(caught.value))
    assert "synthetic_password" not in str(caught.value)


def test_environment_only_and_secret_representation(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    settings = load_settings(env_file=None)
    assert settings.app_env == "development"
    assert settings.database_url.get_secret_value() == FAKE_URL
    assert "synthetic_password" not in repr(settings)
    assert "synthetic_password" not in settings.model_dump_json()


def test_dotenv_precedence(monkeypatch, tmp_path):
    (tmp_path / ".env.shared").write_text(f"APP_ENV=test\nDATABASE_URL={FAKE_URL}\n")
    (tmp_path / ".env").write_text("APP_ENV=development\n")
    assert load_settings().app_env == "development"
    assert load_settings().database_url.get_secret_value() == FAKE_URL
    monkeypatch.setenv("APP_ENV", "production")
    assert load_settings().app_env == "production"


def test_dotenv_can_be_disabled(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(f"DATABASE_URL={FAKE_URL}\n")
    with pytest.raises(ConfigurationError, match="database_url: missing"):
        load_settings(env_file=None)


def test_unreadable_settings_source_is_redacted(tmp_path):
    source = tmp_path / "synthetic_sensitive_filename.env"
    source.write_bytes(b"\xffsynthetic_password")
    with pytest.raises(ConfigurationError, match="Unable to read settings sources") as caught:
        load_settings(env_file=source)
    displayed = "".join(traceback.format_exception(caught.value))
    assert "synthetic_password" not in displayed
    assert "synthetic_sensitive_filename" not in displayed


def test_example_files_load():
    settings = load_settings(env_file=(ROOT / ".env.shared.example", ROOT / ".env.example"))
    assert settings.app_env == "development"
    assert settings.database_url.get_secret_value().startswith("postgresql://clavel_fake:")


def test_private_env_ignored_and_examples_trackable():
    paths = [".env", ".env.shared", ".env.production", "src/clavel/.env", ".env.example", ".env.shared.example"]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        input="\n".join(paths) + "\n", cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == paths[:4]
