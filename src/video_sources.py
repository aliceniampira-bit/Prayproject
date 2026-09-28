"""Background video sources. Every clip carries its provenance and license data."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .media_registry import MediaRegistry


class VideoSourceError(RuntimeError):
    pass


@dataclass
class Clip:
    path: Path
    key: str                 # unique id, e.g. "local:sunrise.mp4" or "pexels:123456"
    source: str              # "local", "pexels", ...
    title: str = ""
    author: str = ""
    author_url: str = ""
    source_url: str = ""
    license: str = ""
    license_url: str = ""
    focus_x: float = 0.5     # horizontal point to keep when cropping to 9:16 (0=left, 1=right)
    has_identifiable_people: bool = False
    themes: tuple[str, ...] = ()

    def provenance(self) -> dict[str, Any]:
        d = asdict(self)
        d["path"] = str(self.path)
        d["themes"] = list(self.themes)
        return d


class VideoSource:
    """Interface: return up to ``count`` clips suitable for ``theme``."""

    def select(self, theme: str, count: int, registry: MediaRegistry, today: str) -> list[Clip]:
        raise NotImplementedError


class LocalClipSource(VideoSource):
    """Clips on disk described by a ``clips.json`` catalog in the same folder.

    Catalog entries: {"file", "title", "author", "source_url", "license",
    "license_url", "focus_x", "themes": [...], "has_identifiable_people": false}
    """

    def __init__(self, folder: Path):
        self.folder = folder
        catalog = folder / "clips.json"
        if not catalog.exists():
            raise VideoSourceError(f"No clips.json catalog in {folder}. Every clip needs provenance data.")
        self.entries = json.loads(catalog.read_text(encoding="utf-8"))["clips"]

    def all_clips(self) -> list[Clip]:
        clips = []
        for e in self.entries:
            path = self.folder / e["file"]
            if not path.exists():
                continue
            clips.append(Clip(
                path=path, key=f"local:{e['file']}", source="local", title=e.get("title", ""),
                author=e.get("author", ""), author_url=e.get("author_url", ""),
                source_url=e.get("source_url", ""), license=e.get("license", ""),
                license_url=e.get("license_url", ""), focus_x=float(e.get("focus_x", 0.5)),
                has_identifiable_people=bool(e.get("has_identifiable_people", False)),
                themes=tuple(e.get("themes", [])),
            ))
        return clips

    def select(self, theme: str, count: int, registry: MediaRegistry, today: str) -> list[Clip]:
        clips = [c for c in self.all_clips() if not c.has_identifiable_people]
        if not clips:
            raise VideoSourceError(f"No usable clips in {self.folder}.")
        # Prefer clips tagged with the theme, then the least recently used.
        clips.sort(key=lambda c: (theme not in c.themes, registry.last_used("clips", c.key) or ""))
        return clips[:count]
