"""Background music: licensed library, selection and the processed music bed.

Every track must be described in ``assets/music/music_library.json`` with its
origin, license and restrictions, and whether its license was checked for each
network (``platforms_verified``). Tracks not verified for commercial use on a
network can be used for local previews only; quality control never approves them
for that network. Platform-native music (TikTok sounds, Instagram audio, YouTube
audio library inside the apps) is never added to the file.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .ffmpeg_utils import run_ffmpeg
from .media_registry import MediaRegistry

REQUIRED_TRACK_FIELDS = ("id", "file", "title", "artist", "source_url", "license", "commercial_use_verified")


class MusicError(RuntimeError):
    pass


@dataclass
class Track:
    id: str
    path: Path
    title: str
    artist: str
    source_url: str
    license: str
    license_url: str
    commercial_use_verified: bool
    platforms_verified: dict[str, bool]
    instrumental: bool
    restrictions: str
    verified_by: str | None
    verified_on: str | None
    content_id_registered: bool | None = None
    attribution: str = ""

    def cleared_for(self, platform: str) -> bool:
        return self.commercial_use_verified and self.instrumental and bool(self.platforms_verified.get(platform))

    def cleared_for_all(self, platforms: list[str]) -> bool:
        return bool(platforms) and all(self.cleared_for(p) for p in platforms)

    @property
    def cleared_for_publication(self) -> bool:
        """Cleared for at least one network (see cleared_for for a specific one)."""
        return any(self.cleared_for(p) for p in self.platforms_verified)

    def provenance(self) -> dict[str, Any]:
        d = asdict(self)
        d["path"] = str(self.path)
        d["cleared_for_publication"] = self.cleared_for_publication
        d["cleared_platforms"] = sorted(p for p in self.platforms_verified if self.cleared_for(p))
        return d


def load_library(library_file: Path) -> list[Track]:
    if not library_file.exists():
        raise MusicError(f"Music library not found: {library_file}")
    raw = json.loads(library_file.read_text(encoding="utf-8"))
    tracks = []
    for entry in raw.get("tracks", []):
        missing = [f for f in REQUIRED_TRACK_FIELDS if f not in entry]
        if missing:
            raise MusicError(f"Track {entry.get('id', '?')} is missing: {', '.join(missing)}")
        platforms = {k: bool(v) for k, v in (entry.get("platforms_verified") or {}).items()}
        if "tiktok_use_verified" in entry:  # older library files
            platforms.setdefault("tiktok", bool(entry["tiktok_use_verified"]))
        tracks.append(Track(
            id=entry["id"], path=(library_file.parent / entry["file"]).resolve(), title=entry["title"],
            artist=entry["artist"], source_url=entry["source_url"], license=entry["license"],
            license_url=entry.get("license_url", ""),
            commercial_use_verified=bool(entry["commercial_use_verified"]),
            platforms_verified=platforms,
            instrumental=bool(entry.get("instrumental", True)), restrictions=entry.get("restrictions", ""),
            verified_by=entry.get("verified_by"), verified_on=entry.get("verified_on"),
            content_id_registered=entry.get("content_id_registered"),
            attribution=entry.get("attribution", ""),
        ))
    return tracks


def select_track(tracks: list[Track], registry: MediaRegistry, allow_unverified: bool,
                 track_id: str | None = None, platforms: list[str] | None = None) -> Track | None:
    """Least recently used track, preferring one cleared for every target network."""
    available = [t for t in tracks if t.path.exists()]
    if track_id:
        match = [t for t in available if t.id == track_id]
        if not match:
            raise MusicError(f"Track '{track_id}' not found or its file is missing.")
        return match[0]
    cleared = ([t for t in available if t.cleared_for_all(platforms)] if platforms
               else [t for t in available if t.cleared_for_publication])
    if platforms and not cleared:
        cleared = [t for t in available if t.cleared_for_publication]
    pool = cleared or (available if allow_unverified else [])
    if not pool:
        return None
    return sorted(pool, key=lambda t: registry.last_used("music", t.id) or "")[0]


def build_music_bed(track: Track, duration: float, settings: Settings, out_path: Path) -> Path:
    """Loop/trim the track to ``duration``, normalize it below the voice and fade it."""
    a = settings["audio"]
    level = a["voice_stem_lufs"] - a["music_below_voice_db"]
    fade_out = min(a["music_fade_out_seconds"], duration / 3)
    af = (f"loudnorm=I={level}:TP=-6:LRA=7,"
          f"afade=t=in:st=0:d={a['music_fade_in_seconds']},"
          f"afade=t=out:st={duration - fade_out:.3f}:d={fade_out:.3f}")
    run_ffmpeg(["-stream_loop", "-1", "-i", str(track.path), "-t", f"{duration:.3f}", "-af", af,
                "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(out_path)])
    return out_path
