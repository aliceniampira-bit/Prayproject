"""Pexels video source (phase 2 — not active yet).

Planned behaviour, using only the official API (no scraping):
  * GET https://api.pexels.com/videos/search with header ``Authorization: <PEXELS_API_KEY>``
    and params ``query``, ``orientation=portrait``, ``size``, ``per_page``, ``page``.
  * Prefer portrait files >= 1080 px wide; accept landscape only when a centred
    9:16 crop keeps the subject (``focus_x``).
  * Queries come from ``config/themes.json`` (landscapes, sunrises, skies...).
  * Skip clips whose metadata suggests identifiable people, so nobody appears to
    endorse the account.
  * Save id, page URL, author name/URL and the Pexels license reference for each
    clip into the production's provenance file and data/media_registry.json.
  * Respect rate limits (read ``X-Ratelimit-Remaining`` / ``X-Ratelimit-Reset``),
    cache search results locally, limited retries with backoff on 429/5xx.

It is left unimplemented until you create a Pexels account and API key, so the
prototype does not pretend to call an API it cannot reach.
"""

from __future__ import annotations

from .config import get_secret
from .media_registry import MediaRegistry
from .video_sources import Clip, VideoSource, VideoSourceError


class PexelsVideoSource(VideoSource):
    def __init__(self) -> None:
        self.api_key = get_secret("PEXELS_API_KEY", "downloading background videos from Pexels")

    def select(self, theme: str, count: int, registry: MediaRegistry, today: str) -> list[Clip]:
        raise VideoSourceError("The Pexels integration is planned for phase 2 and is not implemented yet. "
                               "Use local clips (assets/clips) for now.")
