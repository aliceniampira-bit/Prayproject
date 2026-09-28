"""Publishing.

Phase 1 (current): collect approved videos and write READY_TO_PUBLISH.md with
their descriptions and hashtags, for a person to review and upload manually.

Phase 2 (later, needs an approved TikTok developer app): TikTok Content Posting
API. Two official options exist — "upload to inbox/drafts" (scope video.upload;
the creator finishes the post inside the app) and "Direct Post" (scope
video.publish). Unaudited apps can only post privately (SELF_ONLY) and to a
limited number of users; public posting requires TikTok's audit. See
docs/PUBLICACION_TIKTOK.md. Nothing here posts automatically.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import Settings


def collect_approved(settings: Settings) -> list[dict]:
    out = settings.path("output_dir")
    items = []
    for lang, cfg in settings["languages"].items():
        for report_file in sorted((out / cfg["output_folder"]).glob("*/qc_report.json")):
            report = json.loads(report_file.read_text(encoding="utf-8"))
            if not report.get("approved"):
                continue
            folder = report_file.parent
            items.append({
                "date": folder.name, "language": lang, "folder": folder,
                "description": (folder / "description.txt").read_text(encoding="utf-8").strip(),
            })
    return sorted(items, key=lambda i: (i["date"], i["language"]))


def write_publish_index(settings: Settings) -> Path:
    items = collect_approved(settings)
    out = settings.path("output_dir") / "READY_TO_PUBLISH.md"
    lines = ["# Videos listos para revisión y publicación manual", "",
             "Revisa cada video completo antes de publicarlo. Nada se publica automáticamente.", ""]
    if not items:
        lines.append("_No hay videos aprobados todavía._")
    for it in items:
        rel = it["folder"].relative_to(settings.path("output_dir"))
        lines += [f"## {it['date']} — {it['language']}", "", f"- Video: `{rel}/video.mp4`",
                  f"- Informe: `{rel}/qc_report.md`", "", "```", it["description"], "```", ""]
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
