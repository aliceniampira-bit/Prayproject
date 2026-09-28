import json

from src.media_registry import MediaRegistry
from src.music_manager import load_library, select_track


def _lib(tmp_path, verified):
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "b.wav").write_bytes(b"x")
    tracks = [
        {"id": "a", "file": "a.wav", "title": "A", "artist": "x", "source_url": "u", "license": "L",
         "commercial_use_verified": verified, "tiktok_use_verified": verified},
        {"id": "b", "file": "b.wav", "title": "B", "artist": "x", "source_url": "u", "license": "L",
         "commercial_use_verified": False, "tiktok_use_verified": False},
    ]
    path = tmp_path / "music_library.json"
    path.write_text(json.dumps({"tracks": tracks}))
    return path


def test_verified_tracks_are_preferred(tmp_path):
    reg = MediaRegistry(tmp_path / "reg.json")
    track = select_track(load_library(_lib(tmp_path, True)), reg, allow_unverified=True)
    assert track.id == "a" and track.cleared_for_publication


def test_unverified_only_when_allowed(tmp_path):
    reg = MediaRegistry(tmp_path / "reg.json")
    tracks = load_library(_lib(tmp_path, False))
    assert select_track(tracks, reg, allow_unverified=False) is None
    assert not select_track(tracks, reg, allow_unverified=True).cleared_for_publication


def test_registry_tracks_recent_use(tmp_path):
    reg = MediaRegistry(tmp_path / "reg.json")
    reg.record("clips", "local:x.mp4", "2026-10-01", "2026-10-01_en", {})
    reg.record("clips", "local:x.mp4", "2026-10-01", "2026-10-01_en", {})  # idempotent
    reg.save()
    again = MediaRegistry(tmp_path / "reg.json")
    assert again.uses("clips", "local:x.mp4") == ["2026-10-01"]
    assert again.used_within("clips", "local:x.mp4", 7, "2026-10-05")
    assert not again.used_within("clips", "local:x.mp4", 3, "2026-10-05")
