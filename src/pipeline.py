"""End-to-end production of one topic in one language: master video + per-network versions.

Output layout::

    output/<language>/_master/<date>_<type>_<theme>/    master.mp4, script, SRT, cover, QC
    output/<language>/<network>/<date>_<type>_<theme>/  video, title, description, hashtags,
                                                         cover, SRT, metadata, QC report
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .config import Settings
from .ffmpeg_utils import duration_of, probe
from .media_registry import MediaRegistry
from .music_manager import build_music_bed, load_library, select_track
from .platform_export import ExportResult, export_all
from .quality_control import QCReport, run_qc
from .script_generator import PrayerScript, find_similar, iter_history, validate_with_settings
from .style import TextMeasurer, resolve_font
from .subtitle_generator import (TitleCards, build_cues, build_word_cues, make_layout, read_srt, wrap_title,
                                 write_ass, write_cover_ass, write_srt)
from .video_editor import (Timeline, build_voice_stem, measure_text_area, plan_shots, render_cover,
                           render_video)
from .video_sources import VideoSource
from .voice_generator import NarrationResult, generate_narration

log = logging.getLogger(__name__)


class ProductionError(RuntimeError):
    pass


@dataclass
class ProductionResult:
    production_id: str
    folder: Path
    report: QCReport | None
    skipped: bool = False
    exports: list[ExportResult] = field(default_factory=list)


def topic_folder_name(script: PrayerScript) -> str:
    return script.topic_key


def master_folder(settings: Settings, script: PrayerScript) -> Path:
    lang_folder = settings.language(script.language)["output_folder"]
    return (settings.path("output_dir") / lang_folder / settings["paths"].get("masters_folder", "_master")
            / topic_folder_name(script))


def _already_done(dest: Path, settings: Settings, platforms: list[str]) -> bool:
    report = dest / "qc_report.json"
    if not report.exists() or not json.loads(report.read_text(encoding="utf-8")).get("approved"):
        return False
    for p in platforms:
        folder = dest.parent.parent / settings.platform(p).get("folder", p) / dest.name
        if not (folder / "qc_report.json").exists():
            return False
    return True


def produce(script_path: Path, settings: Settings, clip_source: VideoSource, *,
            music_library: Path | None = None, music_id: str | None = None, gender: str | None = None,
            srt_override: Path | None = None, force: bool = False, allow_similar: bool = False,
            platforms: list[str] | None = None) -> ProductionResult:
    script = PrayerScript.from_dict(json.loads(Path(script_path).read_text(encoding="utf-8")),
                                    default_type=settings.get("default_prayer_type", "full"))
    pid = script.id
    dest = master_folder(settings, script)
    platforms = platforms or settings.enabled_platforms()

    # Idempotency: never produce the same topic/language twice unless forced.
    if not force and _already_done(dest, settings, platforms):
        log.info("%s already approved in %s — skipping (use --force to redo).", pid, dest)
        return ProductionResult(pid, dest, None, skipped=True)

    lang_cfg = settings.language(script.language)
    v = settings["video"]
    validation = validate_with_settings(script, settings)
    if not validation.ok:
        raise ProductionError("Script validation failed:\n- " + "\n- ".join(validation.errors))
    history_dirs = [settings.root / d for d in settings["script"]["history_dirs"]]
    similar = [h for h in find_similar(script, iter_history(history_dirs, script.language),
                                       settings["script"]["similarity_threshold"])
               if Path(h["path"]).resolve() != Path(script_path).resolve()]
    if similar and not allow_similar:
        raise ProductionError(f"Script is too similar to earlier scripts: {similar}")
    warnings = list(validation.warnings)

    work = settings.path("work_dir") / pid
    work.mkdir(parents=True, exist_ok=True)

    # 1. Narration (sentence audio is cached, so re-runs cost nothing) ----------
    narration: NarrationResult = generate_narration(script, settings, work / "voice", gender=gender)

    # 2. Timeline, fonts, subtitles ------------------------------------------------
    timeline = Timeline(v["lead_in_seconds"], narration.duration, v["outro_seconds"])
    fonts_dir = settings.path("fonts_dir")
    fonts = {k: resolve_font(spec, fonts_dir) for k, spec in settings.style["fonts"].items()}
    for key, font in fonts.items():
        if font.is_fallback:
            warnings.append(f"Fuente '{key}': no se encontró {settings.style['fonts'][key]['file']} en assets/fonts; "
                            f"se usa {font.path.name}.")
    layout = make_layout(settings, fonts, script.language)
    if srt_override:
        cues = read_srt(srt_override)
        warnings.append(f"Subtítulos tomados de un SRT corregido manualmente: {srt_override}")
    elif settings["subtitles"].get("mode") == "word_groups":
        cues = build_word_cues(narration.segments, layout, offset=timeline.lead_in,
                               uppercase=settings["subtitles"].get("uppercase", False))
    else:
        cues = build_cues(narration.segments, layout, offset=timeline.lead_in,
                          min_cue=settings["subtitles"]["min_cue_seconds"])
    write_srt(cues, work / "subtitles.srt")
    show_title = v["title_card_seconds"] > 0
    title_lines = wrap_title(script.title, fonts["title"], settings) if show_title else []
    eyebrow = (lang_cfg.get("opening_label") or {}).get(script.type)
    cards = TitleCards(title_lines, settings["project"]["account_name"], lang_cfg["closing_tagline"],
                       settings["project"].get("handle", ""), v["title_card_seconds"],
                       timeline.outro_start, timeline.total, show_closing=v.get("closing_card", True),
                       brand=settings.style.get("brand_text"), eyebrow=eyebrow if show_title else None,
                       show_handle=v.get("closing_show_handle", True))
    ass = write_ass(cues, cards, fonts, settings, work / "subtitles.ass")
    brand_font = fonts.get("brand", fonts["body"])
    card_texts = [("título", fonts["title"], "title", line) for line in title_lines]
    if cards.eyebrow:
        card_texts.append(("texto de apertura", brand_font, "eyebrow", cards.eyebrow))
    if cards.show_closing:
        card_texts += [("nombre de la cuenta", fonts["title"], "closing_name", cards.account_name),
                       ("lema de cierre", fonts["body"], "closing_tagline", cards.tagline)]
        if cards.show_handle:
            card_texts.append(("usuario", fonts["body"], "closing_tagline", cards.handle))
    if cards.brand:
        card_texts.append(("marca", brand_font, "brand", cards.brand))
    usable = v["width"] - settings.style["safe_zone"]["left"] - settings.style["safe_zone"]["right"]
    too_wide_cards = [label for label, font, size_key, text in card_texts
                      if TextMeasurer(font.path, settings.style["sizes"].get(size_key, 34),
                                      settings.style["outline_px"]).width(text) > usable]

    # 3. Media: clips and music ----------------------------------------------------
    registry = MediaRegistry(settings.path("media_registry"))
    clips = clip_source.select(script.theme, v["clips_per_video"], registry, script.date)
    tracks = load_library(music_library or settings.root / settings["music"]["library_file"])
    track = select_track(tracks, registry, settings["music"]["allow_unverified_for_preview"], music_id,
                         platforms=platforms)
    music_bed = None
    if track:
        music_bed = build_music_bed(track, timeline.total, settings, work / "music_bed.wav")
        not_cleared = [p for p in platforms if not track.cleared_for(p)]
        if not_cleared:
            warnings.append(f"La pista '{track.title}' no está verificada para {', '.join(not_cleared)}: "
                            "solo sirve para vista previa en esas redes.")
    else:
        warnings.append("No hay música disponible; el video se genera solo con voz.")
    voice_stem = build_voice_stem(narration.audio_path, timeline, settings, work / "voice_stem.wav")

    # 4. Render the master, measure where text lands, make the cover ----------------------
    video = render_video(clips, voice_stem, music_bed, ass, fonts, timeline, settings, work, work / "master.mp4")
    logo = settings.path("branding_dir") / settings.style["logo"]["file"]
    extra = []
    if logo.exists():
        from PIL import Image
        lw = settings.style["logo"]["width"]
        with Image.open(logo) as im:
            lh = round(im.height * lw / im.width)
        safe = settings.style["safe_zone"]
        extra.append((safe["left"], safe["top"], safe["left"] + lw, safe["top"] + lh))
    text_area = measure_text_area(ass, fonts, timeline.total, settings, work / "textarea", extra_boxes=extra)

    shots, seg_len, _ = plan_shots(clips, timeline.total, settings)
    cover_title = title_lines or wrap_title(script.title, fonts["title"], settings)
    cover_ass = write_cover_ass(cover_title, eyebrow, settings["project"]["account_name"], fonts, settings,
                                work / "cover" / "cover.ass")
    cover_clip, cover_start = shots[0]
    at = cover_start + seg_len * settings.style.get("cover", {}).get("frame_fraction", 0.5)
    at = min(at, max(duration_of(cover_clip.path) - 0.5, 0.0))  # stay inside the clip
    cover = render_cover(cover_clip, at, cover_ass, fonts, settings, work / "cover", work / "cover.jpg")
    cover_area = measure_text_area(cover_ass, fonts, 6.0, settings, work / "cover_area", fps=1)

    provenance = {
        "production_id": pid,
        "topic": script.topic_key,
        "language": script.language,
        "prayer_type": script.type,
        "script": {"id": script.id, "source": str(script_path), "generator": script.generator,
                   "review_status": script.review_status,
                   "bible_verse": script.bible_verse.to_dict() if script.bible_verse else None},
        "clips": [c.provenance() for c in clips],
        "music": track.provenance() if track else None,
        "voice": {"provider": narration.provider, "voice_id": narration.voice_id,
                  "commercial_use_cleared": narration.commercial_use_cleared,
                  "license_note": narration.license_note},
        "fonts": {k: {"file": f.path.name, "family": f.family} for k, f in fonts.items()},
        "overlays": ["texto propio (ASS)"] + (["logo.png"] if logo.exists() else []),
        "platform_native_music": None,
        "master_spec": {k: v[k] for k in ("width", "height", "aspect_ratio", "fps", "container", "video_codec",
                                          "audio_codec", "pixel_format") if k in v},
        "preset": settings.get("preset"),
    }

    # 5. Quality control -------------------------------------------------------------
    report = run_qc(production_id=pid, video=video, script=script, narration=narration, cues=cues,
                    layout=layout, voice_stem=voice_stem, music_bed=music_bed, provenance=provenance,
                    settings=settings, lead_in=timeline.lead_in, outro_start=timeline.outro_start,
                    too_wide_cards=too_wide_cards, warnings=warnings, text_area=text_area,
                    expected_total=timeline.total)
    _check_cover(report, cover, cover_area, settings)

    # 6. Deliverables: master folder + one folder per network ---------------------------
    #    A technical failure goes to output/errors and produces no network versions.
    target = dest if report.technical_ok else settings.path("errors_dir") / pid
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copy2(video, target / "master.mp4")
    shutil.copy2(cover, target / "cover.jpg")
    shutil.copy2(work / "subtitles.srt", target / "subtitles.srt")
    shutil.copy2(work / "subtitles.ass", target / "subtitles.ass")
    shutil.copy2(work / "voice" / "narration.json", target / "narration.json")
    script.save(target / "script.json", lang_cfg["words_per_minute"])
    credits = [f"- {c.title or c.key} — {c.author or 'autor desconocido'} ({c.source_url or c.source}) · {c.license}"
               for c in clips]
    if track:
        credits.append(f"- Música: {track.title} — {track.artist} · {track.license}")
    credits.append(f"- Voz: {narration.provider} / {narration.voice_id}")
    (target / "credits.txt").write_text("Créditos de los recursos\n\n" + "\n".join(credits) + "\n",
                                        encoding="utf-8")
    (target / "provenance.json").write_text(json.dumps(provenance, indent=2, ensure_ascii=False) + "\n",
                                            encoding="utf-8")
    report.video = str(target / "master.mp4")
    report.save(target)

    exports: list[ExportResult] = []
    if report.technical_ok:
        exports = export_all(target, settings, platforms)
        errors_copy = settings.path("errors_dir") / pid
        if errors_copy.exists():
            shutil.rmtree(errors_copy)
    if report.approved:
        for c in clips:
            registry.record("clips", c.key, script.date, pid, c.provenance())
        if track:
            registry.record("music", track.id, script.date, pid, track.provenance())
        registry.save()
    log.info("%s -> %s (%s)", pid, target, report.status)
    return ProductionResult(pid, target, report, exports=exports)


def _check_cover(report: QCReport, cover: Path, area, settings: Settings) -> None:
    """Cover exists, has the master size, and its title survives the profile-grid crops."""
    v = settings["video"]
    W, H = v["width"], v["height"]
    ok_file = cover.exists() and cover.stat().st_size > 0
    size = None
    if ok_file:
        s = next(s for s in probe(cover)["streams"] if s["codec_type"] == "video")
        size = (s["width"], s["height"])
    # Central 3:4 (Instagram grid) and 1:1 crops of a 9:16 frame.
    crop_34 = (H - W * 4 // 3) // 2
    crop_11 = (H - W) // 2
    box = area.bbox
    safe = settings.style["safe_zone"]
    inside = bool(box) and box[1] >= crop_11 and box[3] <= H - crop_11 and not area.outside(safe, W, H)
    report.metrics["cover"] = {"size": size, "text_bbox": list(box) if box else None,
                               "grid_crop_3_4_y": [crop_34, H - crop_34], "grid_crop_1_1_y": [crop_11, H - crop_11]}
    report.add("portada_generada", ok_file and size == (W, H) and inside,
               f"cover.jpg {size}; título en y={box[1]}-{box[3]} (recorte 1:1 y={crop_11}-{H - crop_11})"
               if box else "cover.jpg sin texto de título",
               fix="Ajusta cover.title_center_y o el tamaño del título en la plantilla.")
