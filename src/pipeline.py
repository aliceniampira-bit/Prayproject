"""End-to-end production of one video (one date, one language)."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .media_registry import MediaRegistry
from .music_manager import build_music_bed, load_library, select_track
from .quality_control import QCReport, run_qc
from .script_generator import PrayerScript, find_similar, iter_history, validate_script
from .style import TextMeasurer, resolve_font
from .subtitle_generator import (TitleCards, build_cues, make_layout, read_srt, wrap_title, write_ass,
                                 write_srt)
from .video_editor import Timeline, build_voice_stem, render_video
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


def final_folder(settings: Settings, script: PrayerScript) -> Path:
    lang_folder = settings.language(script.language)["output_folder"]
    return settings.path("output_dir") / lang_folder / script.date


def produce(script_path: Path, settings: Settings, clip_source: VideoSource, *,
            music_library: Path | None = None, music_id: str | None = None, gender: str | None = None,
            srt_override: Path | None = None, force: bool = False, allow_similar: bool = False) -> ProductionResult:
    script = PrayerScript.load(script_path)
    pid = f"{script.date}_{script.language}"
    dest = final_folder(settings, script)

    # Idempotency: never produce the same date/language twice unless forced.
    if (dest / "qc_report.json").exists() and not force:
        report = json.loads((dest / "qc_report.json").read_text(encoding="utf-8"))
        if report.get("approved"):
            log.info("%s already approved in %s — skipping (use --force to redo).", pid, dest)
            return ProductionResult(pid, dest, None, skipped=True)

    lang_cfg = settings.language(script.language)
    v = settings["video"]
    validation = validate_script(script, settings.themes, lang_cfg["words_per_minute"],
                                 v["min_duration_seconds"], v["max_duration_seconds"])
    if not validation.ok:
        raise ProductionError("Script validation failed:\n- " + "\n- ".join(validation.errors))
    history_dirs = [settings.root / d for d in settings["script"]["history_dirs"]]
    similar = [h for h in find_similar(script, iter_history(history_dirs, script.language),
                                       settings["script"]["similarity_threshold"])
               if Path(h["path"]).resolve() != script_path.resolve()]
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
    else:
        cues = build_cues(narration.segments, layout, offset=timeline.lead_in,
                          min_cue=settings["subtitles"]["min_cue_seconds"])
    write_srt(cues, work / "subtitles.srt")
    title_lines = wrap_title(script.title, fonts["title"], settings)
    cards = TitleCards(title_lines, settings["project"]["account_name"], lang_cfg["closing_tagline"],
                       settings["project"].get("handle", ""), v["title_card_seconds"],
                       timeline.outro_start, timeline.total)
    ass = write_ass(cues, cards, fonts, settings, work / "subtitles.ass")
    card_texts = [("título", fonts["title"], "title", line) for line in title_lines] + [
        ("nombre de la cuenta", fonts["title"], "closing_name", cards.account_name),
        ("lema de cierre", fonts["body"], "closing_tagline", cards.tagline),
        ("usuario", fonts["body"], "closing_tagline", cards.handle)]
    usable = v["width"] - settings.style["safe_zone"]["left"] - settings.style["safe_zone"]["right"]
    too_wide_cards = [label for label, font, size_key, text in card_texts
                      if TextMeasurer(font.path, settings.style["sizes"][size_key],
                                      settings.style["outline_px"]).width(text) > usable]

    # 3. Media: clips and music ----------------------------------------------------
    registry = MediaRegistry(settings.path("media_registry"))
    clips = clip_source.select(script.theme, v["clips_per_video"], registry, script.date)
    tracks = load_library(music_library or settings.root / settings["music"]["library_file"])
    track = select_track(tracks, registry, settings["music"]["allow_unverified_for_preview"], music_id)
    music_bed = None
    if track:
        music_bed = build_music_bed(track, timeline.total, settings, work / "music_bed.wav")
        if not track.cleared_for_publication:
            warnings.append(f"La pista '{track.title}' no está verificada: solo sirve para vista previa.")
    else:
        warnings.append("No hay música disponible; el video se genera solo con voz.")
    voice_stem = build_voice_stem(narration.audio_path, timeline, settings, work / "voice_stem.wav")

    # 4. Render --------------------------------------------------------------------
    video = render_video(clips, voice_stem, music_bed, ass, fonts, timeline, settings, work, work / "video.mp4")

    provenance = {
        "production_id": pid,
        "script": {"id": script.id, "generator": script.generator, "review_status": script.review_status,
                   "bible_verse": script.bible_verse.to_dict() if script.bible_verse else None},
        "clips": [c.provenance() for c in clips],
        "music": track.provenance() if track else None,
        "voice": {"provider": narration.provider, "voice_id": narration.voice_id,
                  "commercial_use_cleared": narration.commercial_use_cleared,
                  "license_note": narration.license_note},
        "fonts": {k: {"file": f.path.name, "family": f.family} for k, f in fonts.items()},
    }

    # 5. Quality control -------------------------------------------------------------
    report = run_qc(production_id=pid, video=video, script=script, narration=narration, cues=cues,
                    layout=layout, voice_stem=voice_stem, music_bed=music_bed, provenance=provenance,
                    settings=settings, lead_in=timeline.lead_in, outro_start=timeline.outro_start,
                    too_wide_cards=too_wide_cards, warnings=warnings)

    # 6. Deliverables: approved -> output/<lang>/<date>, otherwise -> output/errors --------
    target = dest if report.approved else settings.path("errors_dir") / pid
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    shutil.copy2(video, target / "video.mp4")
    shutil.copy2(work / "subtitles.srt", target / "subtitles.srt")
    script.save(target / "script.json", lang_cfg["words_per_minute"])
    (target / "description.txt").write_text(script.tiktok_description.strip() + "\n\n"
                                            + " ".join(script.hashtags) + "\n", encoding="utf-8")
    (target / "hashtags.txt").write_text("\n".join(script.hashtags) + "\n", encoding="utf-8")
    (target / "provenance.json").write_text(json.dumps(provenance, indent=2, ensure_ascii=False) + "\n",
                                            encoding="utf-8")
    report.video = str(target / "video.mp4")
    report.save(target)
    if report.approved:
        for c in clips:
            registry.record("clips", c.key, script.date, pid, c.provenance())
        if track:
            registry.record("music", track.id, script.date, pid, track.provenance())
        registry.save()
        errors_copy = settings.path("errors_dir") / pid
        if errors_copy.exists():
            shutil.rmtree(errors_copy)
    log.info("%s -> %s (%s)", pid, target, report.status)
    return ProductionResult(pid, target, report)
