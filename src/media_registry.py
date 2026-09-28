"""Registry of media already used, to avoid frequent repetition and keep provenance."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any


class MediaRegistry:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {"clips": {}, "music": {}}
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
            self.data.setdefault("clips", {})
            self.data.setdefault("music", {})

    def uses(self, kind: str, key: str) -> list[str]:
        return [u["date"] for u in self.data[kind].get(key, {}).get("uses", [])]

    def last_used(self, kind: str, key: str) -> str | None:
        uses = self.uses(kind, key)
        return max(uses) if uses else None

    def used_within(self, kind: str, key: str, days: int, today: str) -> bool:
        last = self.last_used(kind, key)
        if not last:
            return False
        return date.fromisoformat(today) - date.fromisoformat(last) < timedelta(days=days)

    def record(self, kind: str, key: str, on_date: str, production_id: str, meta: dict[str, Any]) -> None:
        entry = self.data[kind].setdefault(key, {"meta": meta, "uses": []})
        entry["meta"] = meta
        if not any(u["production"] == production_id for u in entry["uses"]):
            entry["uses"].append({"date": on_date, "production": production_id})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
