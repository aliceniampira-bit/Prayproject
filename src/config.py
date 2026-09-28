"""Configuration loading: JSON settings plus secrets from the environment (.env)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


class ConfigError(RuntimeError):
    """Raised when configuration or a required credential is missing."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"Missing configuration file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc


def load_dotenv_if_available() -> None:
    """Load .env from the project root. Secrets never live in source files."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv is optional for the offline prototype
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def get_secret(name: str, purpose: str) -> str:
    """Return a secret from the environment or fail with a clear message."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"{name} is not set. It is required for {purpose}. "
            f"Copy .env.example to .env and add the value (never commit .env)."
        )
    return value


@dataclass
class Settings:
    data: dict[str, Any]
    style: dict[str, Any]
    themes: dict[str, Any]
    root: Path = PROJECT_ROOT

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def path(self, key: str) -> Path:
        """Resolve a path from settings['paths'] relative to the project root."""
        return (self.root / self.data["paths"][key]).resolve()

    def language(self, lang: str) -> dict[str, Any]:
        try:
            return self.data["languages"][lang]
        except KeyError as exc:
            raise ConfigError(f"Unsupported language '{lang}'. Configure it in settings.json.") from exc


def load_settings(config_dir: Path | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    load_dotenv_if_available()
    cdir = config_dir or CONFIG_DIR
    data = _load_json(cdir / "settings.json")
    if overrides:
        _deep_update(data, overrides)
    return Settings(
        data=data,
        style=_load_json(cdir / "visual_style.json"),
        themes=_load_json(cdir / "themes.json"),
    )


def _deep_update(base: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
