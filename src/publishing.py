"""Publishing.

Current phase: collect every per-network version and write READY_TO_PUBLISH.md
with its title, caption and hashtags, for a person to review and upload
manually. Versions that did not pass every check are listed separately with
what is missing.

Automatic publishing (later, only after checking each network's official
requirements — see docs/MULTIPLATAFORMA.md):
- TikTok: Content Posting API ("upload to inbox" with video.upload, or Direct
  Post with video.publish). Unaudited apps can only post privately.
- Instagram: Instagram Platform content publishing API (media_type=REELS) for
  professional accounts, with a daily limit of API-published posts.
- YouTube: Data API v3 videos.insert. Uploads from unverified API projects
  created after 28 July 2020 stay private until the project passes an audit.
Nothing here posts automatically.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import Settings


def collect_versions(settings: Settings) -> list[dict]:
    out = settings.path("output_dir")
    items = []
    for lang, lcfg in settings["languages"].items():
        for platform in settings.enabled_platforms():
            pcfg = settings.platform(platform)
            base = out / lcfg["output_folder"] / pcfg.get("folder", platform)
            for report_file in sorted(base.glob("*/qc_report.json")):
                report = json.loads(report_file.read_text(encoding="utf-8"))
                folder = report_file.parent
                meta_file = folder / "metadata.json"
                meta = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}
                items.append({
                    "topic": folder.name, "language": lang, "platform": platform,
                    "label": pcfg.get("label", platform), "folder": folder, "approved": report.get("approved"),
                    "status": report.get("status"), "metadata": meta,
                    "failed": [c["name"] for c in report.get("checks", []) if not c["passed"]],
                })
    return sorted(items, key=lambda i: (i["topic"], i["language"], i["platform"]))


def collect_approved(settings: Settings) -> list[dict]:
    return [i for i in collect_versions(settings) if i["approved"]]


def write_publish_index(settings: Settings) -> Path:
    items = collect_versions(settings)
    out = settings.path("output_dir") / "READY_TO_PUBLISH.md"
    lines = ["# Videos para revisión y publicación manual", "",
             "Revisa cada video completo antes de publicarlo. Nada se publica automáticamente.",
             "No añadas música de la biblioteca de la app: cada video ya lleva su música con licencia.", ""]
    ready = [i for i in items if i["approved"]]
    blocked = [i for i in items if not i["approved"]]
    lines += ["## Listos", ""]
    if not ready:
        lines.append("_No hay videos aprobados todavía._")
    for it in ready:
        rel = it["folder"].relative_to(settings.path("output_dir"))
        meta = it["metadata"]
        lines += [f"### {it['topic']} — {it['language']} — {it['label']}", "",
                  f"- Video: `{rel}/{meta.get('video_file', '')}`",
                  f"- Informe: `{rel}/qc_report.md`"]
        if meta.get("title"):
            lines.append(f"- Título: {meta['title']}")
        lines.append(f"- Portada: `{rel}/cover.jpg`" if meta.get("cover_file")
                     else f"- Portada: fotograma en t={meta.get('cover_frame_seconds')} s")
        lines += ["", "```", meta.get("caption", ""), "```", ""]
    lines += ["## Pendientes (no publicar)", ""]
    if not blocked:
        lines.append("_Ninguno._")
    for it in blocked:
        rel = it["folder"].relative_to(settings.path("output_dir"))
        lines.append(f"- `{rel}` ({it['status']}): falta {', '.join(it['failed'])}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


class TikTokPublisher:
    """Placeholder for the official Content Posting API (phase 2)."""

    def __init__(self, *_args, **_kwargs):
        raise NotImplementedError(
            "TikTok publishing is not implemented. It requires a registered TikTok developer app, "
            "user authorization (OAuth) and, for public posts, passing TikTok's audit. "
            "See docs/PUBLICACION_TIKTOK.md."
        )
