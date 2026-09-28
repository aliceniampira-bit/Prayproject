"""Configuration loading: JSON settings plus secrets from the environment (.env)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
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
    platforms: dict[str, Any] = field(default_factory=dict)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def path(self, key: str) -> Path:
        """Resolve a path from settings['paths'] relative to the project root."""
        return (self.root / self.data["paths"][key]).resolve()

    def language(self, lang: str) -> dict[str, Any]:
        try:
            return self.data["languages"][lang]
        except KeyError as exc:
            raise ConfigError(f"Unsupported language '{lang}'. Configure it in settings.json.") from exc

    def prayer_type(self, name: str | None) -> dict[str, Any]:
        """Duration range and structure rules for a prayer type ('short' or 'full')."""
        name = name or self.data.get("default_prayer_type", "full")
        types = {k: v for k, v in self.data.get("prayer_types", {}).items() if not k.startswith("_")}
        if name not in types:
            raise ConfigError(f"Unknown prayer type '{name}'. Valid: {', '.join(types)} (settings.json prayer_types).")
        return types[name]

    def platform(self, name: str) -> dict[str, Any]:
        try:
            return self.platforms["platforms"][name]
        except KeyError as exc:
            raise ConfigError(f"Unknown platform '{name}'. Configure it in platforms.json.") from exc

    def enabled_platforms(self) -> list[str]:
        return list(self.platforms.get("enabled", []))


def load_settings(config_dir: Path | None = None, overrides: dict[str, Any] | None = None) -> Settings:
    load_dotenv_if_available()
    cdir = config_dir or CONFIG_DIR
    data = _load_json(cdir / "settings.json")
    style = _load_json(cdir / "visual_style.json")
    preset_name = (overrides or {}).get("preset", data.get("preset"))
    if preset_name:
        # A preset is a named format: it overrides parts of settings.json and visual_style.json.
        preset = _load_json(cdir / "presets" / f"{preset_name}.json")
        _deep_update(data, preset.get("settings", {}))
        _deep_update(style, preset.get("style", {}))
    if overrides:
        _deep_update(data, overrides)
    platforms_file = cdir / Path(data.get("paths", {}).get("platforms_file", "platforms.json")).name
    platforms = _load_json(platforms_file) if platforms_file.exists() else {"enabled": [], "platforms": {}}
    if "platforms" in (overrides or {}):
        _deep_update(platforms, overrides["platforms"])
    _widen_safe_zone(style, platforms)
    return Settings(data=data, style=style, themes=_load_json(cdir / "themes.json"), platforms=platforms)


def _widen_safe_zone(style: dict[str, Any], platforms: dict[str, Any]) -> None:
    """One master video serves every network, so text must avoid the UI of all of them."""
    zone = style.setdefault("safe_zone", {})
    for name in platforms.get("enabled", []):
        overlay = platforms.get("platforms", {}).get(name, {}).get("ui_overlay", {})
        for side in ("top", "bottom", "left", "right"):
            if side in overlay:
                zone[side] = max(int(zone.get(side, 0)), int(overlay[side]))


def _deep_update(base: dict[str, Any], extra: dict[str, Any]) -> None:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
