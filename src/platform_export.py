"""Per-network versions of a master video: file, metadata, cover, SRT and QC report.

One master video (9:16, 1080x1920, H.264/AAC, 30 fps, text inside the shared
safe zone) is valid for TikTok, Instagram Reels and YouTube Shorts, so it is
reused as is. A network gets a re-encoded file only if ``platforms.json`` asks
for it (``video.transcode``). What changes per network is the text around the
video: title, caption, hashtags, cover and publishing notes.

Nothing is published from here: each folder is left ready for manual review.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .ffmpeg_utils import run_ffmpeg
from .quality_control import QCReport, run_platform_qc
from .script_generator import PrayerScript

log = logging.getLogger(__name__)

_LABELS = {
    "en": {"footage": "Footage", "music": "Music", "by": "by", "voice": "AI voice"},
    "es": {"footage": "Imágenes", "music": "Música", "by": "de", "voice": "Voz IA"},
}


@dataclass
class ExportResult:
    platform: str
    folder: Path
    report: QCReport


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def credits_line(provenance: dict[str, Any], language: str) -> str:
    """Short credit text for descriptions (Pexels authors, music attribution when required)."""
    lab = _LABELS.get(language, _LABELS["en"])
    parts = []
    clips = provenance.get("clips", [])
    by_source: dict[str, list[str]] = {}
    for c in clips:
        name = "Pexels" if c.get("source") == "pexels" else (c.get("license") if c.get("source") != "local" else "")
        if name:
            by_source.setdefault(name, [])
            if c.get("author") and c["author"] not in by_source[name]:
                by_source[name].append(c["author"])
    for source, authors in by_source.items():
        parts.append(f"{lab['footage']}: {source}" + (f" ({', '.join(authors[:4])})" if authors else ""))
    music = provenance.get("music")
    if music and music.get("attribution"):
        parts.append(f"{lab['music']}: {music['attribution']}")
    return " · ".join(parts)


def _merge_hashtags(*groups: list[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for tag in group:
            key = tag.lower()
            if key not in seen:
                seen.add(key)
                out.append(tag)
    return out[:limit]


def build_metadata(script: PrayerScript, platform: str, settings: Settings, provenance: dict[str, Any],
                   cover_frame_seconds: float | None) -> dict[str, Any]:
    """Title, caption and hashtags adapted to one network, from the script (plus its overrides)."""
    cfg = settings.platform(platform)
    m = cfg.get("metadata", {})
    lang = script.language
    override = script.platform_overrides.get(platform, {})
    type_label = settings.prayer_type(script.type)["label"].get(lang, script.type)
    hashtags = _merge_hashtags(m.get("fixed_hashtags", []), override.get("hashtags") or script.hashtags,
                               limit=int(m.get("max_hashtags", 30)))
    description = (override.get("description") or script.description).strip()
    fields = {"title": script.title, "description": description, "hashtags": " ".join(hashtags),
              "credits": credits_line(provenance, lang), "type_label": type_label}

    title = None
    if m.get("has_title_field"):
        template = (m.get("title_template") or {}).get(lang, "{title}")
        title = override.get("title") or template.format(**fields)
        max_len = int(m.get("title_max_chars", 100))
        if len(title) > max_len:  # drop the suffix before cutting the prayer title itself
            title = script.title if len(script.title) <= max_len else script.title[:max_len - 1].rstrip() + "…"
    caption = m.get("caption_template", "{description}\n\n{hashtags}").format(**fields)
    caption = re.sub(r"\n{3,}", "\n\n", caption).strip()

    cover_cfg = cfg.get("cover", {})
    return {
        "platform": platform,
        "label": cfg.get("label", platform),
        "language": lang,
        "prayer_type": script.type,
        "theme": script.theme,
        "date": script.date,
        "title": title,
        "opening_text": script.title,
        "description": description,
        "caption": caption,
        "hashtags": hashtags,
        "credits": fields["credits"],
        "cover_file": "cover.jpg" if cover_cfg.get("upload_supported") else None,
        "cover_frame_seconds": cover_frame_seconds,
        "cover_note": cover_cfg.get("note", ""),
        "captions_file_upload": bool(cfg.get("captions_file_upload")),
        "platform_music": "none — the video already contains licensed music; do not add in-app sounds",
        "publishing": "manual",
        "publishing_note": cfg.get("publishing_note", ""),
        "rules_last_reviewed": cfg.get("last_reviewed"),
        "official_sources": cfg.get("official_sources", []),
    }


def _link_or_copy(src: Path, dst: Path) -> None:
    dst.unlink(missing_ok=True)
    try:
        os.link(src, dst)  # same bytes, no extra disk space
    except OSError:
        shutil.copy2(src, dst)


def _platform_video(master: Path, dst: Path, cfg: dict[str, Any], settings: Settings) -> None:
    transcode = (cfg.get("video") or {}).get("transcode")
    if not transcode:
        _link_or_copy(master, dst)
        return
    # Only when a network needs different encoding: re-encode from the master.
    from .video_editor import encoding_args
    local = Settings({**settings.data, "video": {**settings["video"], **transcode}}, settings.style,
                     settings.themes, settings.root, settings.platforms)
    run_ffmpeg(["-i", str(master), "-map", "0:v:0", "-map", "0:a:0", *encoding_args(local), str(dst)])


def export_platform(master_dir: Path, platform: str, settings: Settings) -> ExportResult:
    script = PrayerScript.from_dict(json.loads((master_dir / "script.json").read_text(encoding="utf-8")))
    provenance = json.loads((master_dir / "provenance.json").read_text(encoding="utf-8"))
    master_report = QCReport.load(master_dir / "qc_report.json")
    master = master_dir / "master.mp4"
    cfg = settings.platform(platform)
    folder = master_dir.parent.parent / cfg.get("folder", platform) / master_dir.name
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    base = f"{master_dir.name}_{script.language}_{platform}"
    video = folder / f"{base}.mp4"
    _platform_video(master, video, cfg, settings)
    title_seconds = settings["video"].get("title_card_seconds", 0)
    frame = round(min(title_seconds * 0.55, 2.5), 2) if title_seconds else None
    meta = build_metadata(script, platform, settings, provenance, frame)
    meta["video_file"] = video.name

    (folder / "title.txt").write_text((meta["title"] or meta["opening_text"]) + "\n", encoding="utf-8")
    (folder / "description.txt").write_text(meta["caption"] + "\n", encoding="utf-8")
    (folder / "hashtags.txt").write_text("\n".join(meta["hashtags"]) + "\n", encoding="utf-8")
    shutil.copy2(master_dir / "subtitles.srt", folder / "subtitles.srt")
    cover = None
    if meta["cover_file"] and (master_dir / "cover.jpg").exists():
        cover = folder / "cover.jpg"
        shutil.copy2(master_dir / "cover.jpg", cover)
    for name in ("credits.txt", "provenance.json"):
        if (master_dir / name).exists():
            shutil.copy2(master_dir / name, folder / name)

    report = run_platform_qc(
        platform=platform, production_id=master_report.production_id, video=video, master_report=master_report,
        master_sha256=sha256_of(master), video_sha256=sha256_of(video), metadata=meta, cover=cover,
        srt=folder / "subtitles.srt", master_srt=master_dir / "subtitles.srt", provenance=provenance,
        script=script, settings=settings)
    meta["qc_status"] = report.status
    (folder / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report.save(folder)
    blocked = [c for c in report.checks if not c.passed]
    if blocked:
        lines = [f"NO PUBLICAR TODAVÍA — {cfg.get('label', platform)} ({report.status})", ""]
        lines += [f"- {c.name}: {c.fix or c.detail}" for c in blocked]
        (folder / "NO_PUBLICAR.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("%s -> %s (%s)", platform, folder, report.status)
    return ExportResult(platform, folder, report)


def export_all(master_dir: Path, settings: Settings, platforms: list[str] | None = None) -> list[ExportResult]:
    return [export_platform(master_dir, p, settings) for p in (platforms or settings.enabled_platforms())]
