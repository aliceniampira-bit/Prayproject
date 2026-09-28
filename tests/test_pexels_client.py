"""Pexels client tests with a fake HTTP session (no network, no real key)."""

import shutil
import subprocess

import pytest

from conftest import needs_ffmpeg
from src.config import load_settings
from src.media_registry import MediaRegistry
from src.pexels_client import PexelsConfig, PexelsError, PexelsVideoSource


class FakeResponse:
    def __init__(self, status=200, payload=None, content=b"", headers=None):
        self.status_code = status
        self._payload = payload or {}
        self._content = content
        self.headers = headers or {"X-Ratelimit-Remaining": "19999"}
        self.text = str(payload)

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=1):
        yield self._content


class FakeSession:
    def __init__(self, search_payload, video_bytes=b"", status=200):
        self.search_payload = search_payload
        self.video_bytes = video_bytes
        self.status = status
        self.calls = []

    def get(self, url, params=None, stream=False, timeout=None, headers=None):
        self.calls.append((url, params, headers))
        if self.status != 200:
            return FakeResponse(self.status, {"error": "x"}, headers={"X-Ratelimit-Reset": "1900000000"})
        if "api.pexels.com" in url:
            return FakeResponse(payload=self.search_payload)
        return FakeResponse(content=self.video_bytes)


def video(vid, slug, files, duration=12):
    return {"id": vid, "url": f"https://www.pexels.com/video/{slug}-{vid}/", "duration": duration,
            "user": {"name": "Ana Photographer", "url": "https://www.pexels.com/@ana"},
            "video_files": files}


PORTRAIT = [{"file_type": "video/mp4", "width": 720, "height": 1280, "link": "https://videos.pexels.com/a.mp4"},
            {"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "https://videos.pexels.com/b.mp4"},
            {"file_type": "video/mp4", "width": 2160, "height": 3840, "link": "https://videos.pexels.com/c.mp4"}]
LANDSCAPE = [{"file_type": "video/mp4", "width": 1920, "height": 1080, "link": "https://videos.pexels.com/d.mp4"}]
LOW_RES = [{"file_type": "video/mp4", "width": 640, "height": 360, "link": "https://videos.pexels.com/e.mp4"}]


@pytest.fixture
def source(tmp_path):
    settings = load_settings()
    settings.root = tmp_path  # keep caches inside the test folder
    return settings


def make(settings, session):
    return PexelsVideoSource(settings, api_key="test-key", session=session,
                             config=PexelsConfig(max_retries=1))


def test_sends_key_in_authorization_header(source):
    s = FakeSession({"videos": []})
    make(source, s).search("sunset road")
    url, params, headers = s.calls[0]
    assert headers == {"Authorization": "test-key"}
    assert params["orientation"] == "portrait" and params["query"] == "sunset road"


def test_search_results_are_cached(source):
    s = FakeSession({"videos": [video(1, "sunset-over-hills", PORTRAIT)]})
    px = make(source, s)
    px.search("sunset")
    px.search("sunset")
    assert len(s.calls) == 1


def test_picks_smallest_portrait_file_at_least_1080(source):
    px = make(source, FakeSession({}))
    assert px.pick_file(video(1, "road", PORTRAIT))["width"] == 1080
    assert px.pick_file(video(2, "road", LANDSCAPE))["height"] == 1080
    assert px.pick_file(video(3, "road", LOW_RES)) is None


def test_skips_people_short_clips_and_low_resolution(source):
    px = make(source, FakeSession({}))
    assert not px.is_usable(video(1, "woman-walking-on-road-at-sunset", PORTRAIT))
    assert not px.is_usable(video(2, "couple-watching-sunset", PORTRAIT))
    assert not px.is_usable(video(3, "sunset-sky", PORTRAIT, duration=3))
    assert not px.is_usable(video(4, "sunset-sky", LOW_RES))
    assert px.is_usable(video(5, "aerial-view-of-highway-at-sunset", PORTRAIT))


def test_clear_errors_for_bad_key_and_rate_limit(source):
    with pytest.raises(PexelsError, match="API key"):
        make(source, FakeSession({}, status=401)).search("x")
    with pytest.raises(PexelsError, match="rate limit"):
        make(source, FakeSession({}, status=429)).search("x")


def test_missing_key_gives_clear_message(source, monkeypatch):
    from src.config import ConfigError
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="PEXELS_API_KEY"):
        PexelsVideoSource(source, session=FakeSession({}))


@needs_ffmpeg
def test_select_downloads_and_records_provenance(source, tmp_path):
    sample = tmp_path / "sample.mp4"
    subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=c=orange:s=1080x1920:d=1",
                    "-c:v", "libx264", str(sample)], check=True)
    payload = {"videos": [video(10, "woman-at-sunset", PORTRAIT),
                          video(11, "aerial-view-of-highway-at-sunset", PORTRAIT),
                          video(12, "misty-forest-valley", PORTRAIT)]}
    px = make(source, FakeSession(payload, video_bytes=sample.read_bytes()))
    registry = MediaRegistry(tmp_path / "registry.json")
    registry.record("clips", "pexels:12", "2026-10-01", "old", {})  # used recently -> skipped
    clips = px.select("gratitude", 3, registry, "2026-10-04")
    keys = {c.key for c in clips}
    assert keys == {"pexels:11"}
    clip = clips[0]
    assert clip.author == "Ana Photographer" and clip.license == "Pexels License"
    assert clip.source_url.endswith("-11/") and clip.path.exists()
