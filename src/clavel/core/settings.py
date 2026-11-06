"""Local settings; call load_settings at startup, never at import time."""

from pathlib import Path
from typing import Literal

from pydantic import PostgresDsn, SecretStr, TypeAdapter, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, SettingsError


class ConfigurationError(ValueError):
    """Invalid configuration, with field names and error codes only."""


class Settings(BaseSettings):
    """Environment overrides .env, which overrides optional .env.shared."""

    model_config = SettingsConfigDict(
        env_file=(".env.shared", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            TypeAdapter(PostgresDsn).validate_python(value.get_secret_value())
        except ValidationError:
            raise ValueError("must be a valid PostgreSQL URL") from None
        return value


def load_settings(
    *, env_file: str | Path | tuple[str | Path, ...] | None = (".env.shared", ".env")
) -> Settings:
    """Load validated settings; use env_file=None to read only the environment.

    ConfigurationError messages and displayed tracebacks omit input values.
    Access database_url.get_secret_value() only when opening a connection.
    """
    try:
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        errors = exc.errors(include_url=False, include_context=False, include_input=False)
        fields = "; ".join(f"{error['loc'][0]}: {error['type']}" for error in errors)
        raise ConfigurationError(f"Invalid settings: {fields}") from None
    except (SettingsError, OSError, UnicodeError):
        raise ConfigurationError("Unable to read settings sources") from None
