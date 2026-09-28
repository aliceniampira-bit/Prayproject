"""Pexels video source, using only the official API (https://www.pexels.com/api/).

* Search: GET https://api.pexels.com/videos/search with header ``Authorization: <key>``.
* Portrait files around 1080 px wide are preferred; landscape files are accepted
  when their height allows a sharp 9:16 centre crop.
* Clips whose Pexels page slug suggests people are skipped, so nobody appears to
  endorse the account or the prayer.
* Search results are cached on disk (fewer requests), downloads are cached by
  video id, and clips used recently (media_registry.json) are avoided.
* Rate limits: the X-Ratelimit-* headers are read; on 429 the client stops with a
  clear message instead of retrying. Other transient errors get limited retries.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .config import Settings, get_secret
from .ffmpeg_utils import FFmpegError, duration_of
from .media_registry import MediaRegistry
from .video_sources import Clip, VideoSource, VideoSourceError

log = logging.getLogger(__name__)

API_URL = "https://api.pexels.com/videos/search"
LICENSE_NAME = "Pexels License"
LICENSE_URL = "https://www.pexels.com/license/"

# Words in a Pexels page slug that suggest identifiable people.
PEOPLE_WORDS = {
    "man", "men", "woman", "women", "girl", "girls", "boy", "boys", "person", "people", "couple",
    "family", "child", "children", "kid", "kids", "baby", "portrait", "face", "faces", "selfie",
    "crowd", "friends", "lady", "guy", "model", "bride", "groom", "worshipper", "pastor", "priest",
    "nun", "praying-woman", "praying-man", "silhouette-of-a-person",
}


class PexelsError(VideoSourceError):
    pass


@dataclass
class PexelsConfig:
    per_page: int = 15
    min_duration: int = 6
    max_duration: int = 60
    min_width_portrait: int = 1080
    min_height_landscape: int = 1080
    repeat_cooldown_days: int = 45
    search_cache_days: int = 7
    max_retries: int = 3
    timeout: int = 30


class PexelsVideoSource(VideoSource):
    def __init__(self, settings: Settings, api_key: str | None = None,
                 session: requests.Session | None = None, config: PexelsConfig | None = None):
        self.api_key = api_key or get_secret("PEXELS_API_KEY", "downloading background videos from Pexels")
        self.settings = settings
        self.session = session or requests.Session()
        self.cfg = config or PexelsConfig(**settings.data.get("pexels", {}))
        cache = settings.root / "data" / "cache" / "pexels"
        self.search_cache = cache / "search"
        self.download_dir = cache / "videos"
        self.search_cache.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.rate_limit: dict[str, str] = {}

    # ---- HTTP ------------------------------------------------------------------
    def _get(self, url: str, params: dict[str, Any] | None = None, stream: bool = False) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(self.cfg.max_retries):
            try:
                resp = self.session.get(url, params=params, stream=stream, timeout=self.cfg.timeout,
                                        headers={"Authorization": self.api_key})
            except requests.RequestException as exc:
                last_error = exc
            else:
                for h in ("X-Ratelimit-Limit", "X-Ratelimit-Remaining", "X-Ratelimit-Reset"):
                    if h in resp.headers:
                        self.rate_limit[h] = resp.headers[h]
                if resp.status_code == 200:
                    return resp
                if resp.status_code in (401, 403):
                    raise PexelsError("Pexels rejected the API key (HTTP %d). Check PEXELS_API_KEY in .env."
                                      % resp.status_code)
                if resp.status_code == 429:
                    reset = resp.headers.get("X-Ratelimit-Reset")
                    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(int(reset))) if reset else "later"
                    raise PexelsError(f"Pexels rate limit reached. Try again after {when}.")
                if resp.status_code < 500:
                    raise PexelsError(f"Pexels request failed: HTTP {resp.status_code} {resp.text[:200]}")
                last_error = PexelsError(f"Pexels server error HTTP {resp.status_code}")
            time.sleep(2 ** attempt)
        raise PexelsError(f"Pexels request failed after {self.cfg.max_retries} attempts: {last_error}")

    # ---- search ----------------------------------------------------------------
    def search(self, query: str, page: int = 1, orientation: str = "portrait") -> list[dict[str, Any]]:
        params = {"query": query, "orientation": orientation, "size": "medium",
                  "per_page": self.cfg.per_page, "page": page}
        key = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()[:20]
        cached = self.search_cache / f"{key}.json"
        if cached.exists() and time.time() - cached.stat().st_mtime < self.cfg.search_cache_days * 86400:
            return json.loads(cached.read_text(encoding="utf-8"))["videos"]
        data = self._get(API_URL, params).json()
        cached.write_text(json.dumps({"params": params, "videos": data.get("videos", [])}), encoding="utf-8")
        log.info("Pexels search %r page %d: %d results (remaining %s)", query, page,
                 len(data.get("videos", [])), self.rate_limit.get("X-Ratelimit-Remaining", "?"))
        return data.get("videos", [])

    # ---- filtering -------------------------------------------------------------
    @staticmethod
    def slug_words(video: dict[str, Any]) -> set[str]:
        slug = video.get("url", "").rstrip("/").rsplit("/", 1)[-1]
        return set(re.split(r"[-_]", slug.lower()))

    def looks_like_people(self, video: dict[str, Any]) -> bool:
        return bool(self.slug_words(video) & PEOPLE_WORDS)

    def pick_file(self, video: dict[str, Any]) -> dict[str, Any] | None:
        """Best MP4 rendition: portrait >= 1080 wide (smallest such), else sharp landscape."""
        files = [f for f in video.get("video_files", [])
                 if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height") and f.get("link")]
        portrait = [f for f in files if f["height"] > f["width"] and f["width"] >= self.cfg.min_width_portrait]
        if portrait:
            return min(portrait, key=lambda f: f["width"])
        landscape = [f for f in files if f["height"] >= self.cfg.min_height_landscape]
        if landscape:
            return min(landscape, key=lambda f: f["height"])
        return None

    def is_usable(self, video: dict[str, Any]) -> bool:
        duration = video.get("duration") or 0
        return (self.cfg.min_duration <= duration <= self.cfg.max_duration
                and not self.looks_like_people(video) and self.pick_file(video) is not None)

    # ---- download --------------------------------------------------------------
    def download(self, video: dict[str, Any]) -> Path:
        chosen = self.pick_file(video)
        if not chosen:
            raise PexelsError(f"No suitable file for Pexels video {video.get('id')}")
        path = self.download_dir / f"{video['id']}_{chosen['width']}x{chosen['height']}.mp4"
        if path.exists() and path.stat().st_size > 0:
            return path
        tmp = path.with_suffix(".part")
        resp = self._get(chosen["link"], stream=True)
        with tmp.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
        tmp.replace(path)
        try:
            if duration_of(path) <= 0:
                raise PexelsError("empty video")
        except (FFmpegError, PexelsError, KeyError, ValueError) as exc:
            path.unlink(missing_ok=True)
            raise PexelsError(f"Downloaded Pexels video {video['id']} is not playable: {exc}") from exc
        return path

    def to_clip(self, video: dict[str, Any], path: Path, theme: str) -> Clip:
        user = video.get("user") or {}
        slug = video.get("url", "").rstrip("/").rsplit("/", 1)[-1]
        title = " ".join(w for w in slug.split("-") if not w.isdigit()) or f"Pexels {video['id']}"
        return Clip(path=path, key=f"pexels:{video['id']}", source="pexels", title=title,
                    author=user.get("name", ""), author_url=user.get("url", ""),
                    source_url=video.get("url", ""), license=LICENSE_NAME, license_url=LICENSE_URL,
                    focus_x=0.5, has_identifiable_people=False, themes=(theme,))

    # ---- VideoSource -----------------------------------------------------------
    def queries_for(self, theme: str) -> list[str]:
        style = self.settings.data.get("visual_queries", [])
        themed = self.settings.themes.get(theme, {}).get("visual_queries", [])
        return list(dict.fromkeys([*style, *themed]))

    def select(self, theme: str, count: int, registry: MediaRegistry, today: str) -> list[Clip]:
        queries = self.queries_for(theme)
        if not queries:
            raise PexelsError(f"No visual queries configured for theme '{theme}'.")
        rng = random.Random(f"{today}:{theme}")  # varies by day, reproducible for re-runs
        rng.shuffle(queries)
        chosen: list[Clip] = []
        seen: set[int] = set()
        for page in (1, 2):
            for query in queries:
                if len(chosen) >= count:
                    break
                candidates = [v for v in self.search(query, page) if v.get("id") not in seen]
                rng.shuffle(candidates)
                for video in candidates:
                    seen.add(video["id"])
                    key = f"pexels:{video['id']}"
                    if not self.is_usable(video) or registry.used_within("clips", key,
                                                                          self.cfg.repeat_cooldown_days, today):
                        continue
                    try:
                        path = self.download(video)
                    except PexelsError as exc:
                        log.warning("%s", exc)
                        continue
                    chosen.append(self.to_clip(video, path, theme))
                    break  # one clip per query keeps the sequence varied
            if len(chosen) >= count:
                break
        if not chosen:
            raise PexelsError(f"Pexels returned no suitable clips for '{theme}' (queries: {queries}).")
        if len(chosen) < count:
            log.warning("Only %d of %d Pexels clips found; they will be reused.", len(chosen), count)
        return chosen
