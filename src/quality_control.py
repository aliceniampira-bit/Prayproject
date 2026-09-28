"""Quality control: technical and publication checks before a video is approved.

``run_qc`` checks the master video once. ``run_platform_qc`` then checks every
per-network version (file, metadata, cover, SRT, interface safe zone, music
license for that network) and includes the master checks, so each folder has a
complete, self-contained report."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .ffmpeg_utils import duration_of, ffmpeg_bin, measure_loudness, probe
from .script_generator import PrayerScript, detect_language
from .subtitle_generator import Cue, SubtitleLayout, read_srt
from .video_editor import TextArea
from .voice_generator import NarrationResult

PLATFORM_DOMAINS = ("tiktok.com", "instagram.com", "youtube.com", "youtu.be", "facebook.com", "cdninstagram")


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    category: str = "technical"  # technical | publication
    fix: str = ""


@dataclass
class QCReport:
    production_id: str
    video: str
    checks: list[Check] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def add(self, name: str, passed: bool, detail: str, category: str = "technical", fix: str = "") -> None:
        self.checks.append(Check(name, bool(passed), detail, category, "" if passed else fix))

    @property
    def technical_ok(self) -> bool:
        return all(c.passed for c in self.checks if c.category == "technical")

    @property
    def approved(self) -> bool:
        return bool(self.checks) and all(c.passed for c in self.checks)

    @property
    def status(self) -> str:
        if self.approved:
            return "approved"
        return "rejected_technical" if not self.technical_ok else "blocked_for_publication"

    def to_dict(self) -> dict[str, Any]:
        return {"production_id": self.production_id, "video": self.video, "status": self.status,
                "approved": self.approved, "created_at": self.created_at, "metrics": self.metrics,
                "warnings": self.warnings, "checks": [asdict(c) for c in self.checks]}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "QCReport":
        rep = cls(d["production_id"], d["video"], [Check(**c) for c in d.get("checks", [])],
                  list(d.get("warnings", [])), dict(d.get("metrics", {})))
        rep.created_at = d.get("created_at", rep.created_at)
        return rep

    @classmethod
    def load(cls, path: Path) -> "QCReport":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def to_markdown(self) -> str:
        icon = {True: "✅", False: "❌"}
        lines = [f"# Informe de calidad — {self.production_id}", "",
                 f"**Estado:** `{self.status}`  ", f"**Fecha:** {self.created_at}", "",
                 "| Comprobación | Tipo | Resultado | Detalle |", "|---|---|---|---|"]
        for c in self.checks:
            lines.append(f"| {c.name} | {c.category} | {icon[c.passed]} | {c.detail} |")
        failed = [c for c in self.checks if not c.passed]
        if failed:
            lines += ["", "## Qué hay que corregir", ""]
            lines += [f"- **{c.name}**: {c.fix or c.detail}" for c in failed]
        if self.warnings:
            lines += ["", "## Avisos", ""] + [f"- {w}" for w in self.warnings]
        metrics = {k: v for k, v in self.metrics.items() if k != "text_area"}
        if "text_area" in self.metrics:
            metrics["text_area_bbox"] = self.metrics["text_area"].get("bbox")
        lines += ["", "## Métricas", "", "```json", json.dumps(metrics, indent=2, ensure_ascii=False), "```"]
        return "\n".join(lines) + "\n"

    def save(self, folder: Path) -> None:
        (folder / "qc_report.json").write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False) + "\n",
                                               encoding="utf-8")
        (folder / "qc_report.md").write_text(self.to_markdown(), encoding="utf-8")


def _decodes_cleanly(video: Path) -> tuple[bool, str]:
    proc = subprocess.run([ffmpeg_bin(), "-v", "error", "-i", str(video), "-f", "null", "-"],
                          capture_output=True, text=True)
    errors = proc.stderr.strip()
    return proc.returncode == 0 and not errors, errors[-300:] if errors else "decodificación completa sin errores"


def _fps(stream: dict[str, Any]) -> float:
    num, _, den = str(stream.get("r_frame_rate", "0/1")).partition("/")
    return float(num) / float(den or 1) if float(den or 1) else 0.0


_CODEC_NAMES = {"libx264": "h264", "libx265": "hevc", "aac": "aac", "libfdk_aac": "aac"}


def check_file_spec(rep: QCReport, info: dict[str, Any], video: Path, settings: Settings) -> None:
    """Container, codecs, resolution, orientation, frame rate and audio/video alignment."""
    v = settings["video"]
    vstreams = [s for s in info["streams"] if s["codec_type"] == "video"]
    astreams = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if not vstreams:
        rep.add("resolucion_9_16", False, "sin pista de video", fix="Vuelve a renderizar.")
        return
    vs = vstreams[0]
    w, h = int(vs["width"]), int(vs["height"])
    aw, ah = (int(x) for x in str(v.get("aspect_ratio", "9:16")).split(":"))
    rotation = any("rotation" in sd for sd in vs.get("side_data_list", []))
    good = (w, h) == (v["width"], v["height"]) and w * ah == h * aw and h > w and not rotation
    rep.add("resolucion_9_16", good, f"{w}x{h}, vertical={'sí' if h > w else 'no'}, rotación={'sí' if rotation else 'no'}",
            fix=f"Debe ser {v['width']}x{v['height']} ({v.get('aspect_ratio', '9:16')}), vertical y sin rotación.")
    container = v.get("container", "mp4")
    want_v = _CODEC_NAMES.get(v.get("video_codec", "libx264"), v.get("video_codec"))
    want_a = _CODEC_NAMES.get(v.get("audio_codec", "aac"), v.get("audio_codec"))
    a_codec = astreams[0]["codec_name"] if astreams else None
    fmt_ok = container in info["format"].get("format_name", "") and video.suffix.lower() == f".{container}"
    codec_ok = vs["codec_name"] == want_v and a_codec == want_a and vs.get("pix_fmt") == v.get("pixel_format", "yuv420p")
    rep.add("formato_y_codecs", fmt_ok and codec_ok,
            f"{container.upper()} · video {vs['codec_name']} ({vs.get('profile', '?')}, {vs.get('pix_fmt')}) · "
            f"audio {a_codec or 'ninguno'}"
            + (f" {astreams[0].get('sample_rate')} Hz" if astreams else ""),
            fix=f"Debe ser {container.upper()} con video {want_v} {v.get('pixel_format', 'yuv420p')} y audio {want_a}.")
    fps = _fps(vs)
    rep.add("fotogramas_por_segundo", abs(fps - v["fps"]) < 0.01, f"{fps:.2f} fps (objetivo {v['fps']})",
            fix="Revisa video.fps en settings.json.")
    if astreams:
        vd = float(vs.get("duration") or info["format"]["duration"])
        ad = float(astreams[0].get("duration") or info["format"]["duration"])
        rep.metrics["stream_durations"] = {"video": round(vd, 3), "audio": round(ad, 3)}
        rep.add("audio_y_video_alineados", abs(vd - ad) <= 0.1,
                f"video {vd:.2f}s, audio {ad:.2f}s (diferencia {abs(vd - ad):.2f}s)",
                fix="La pista de audio y la de video deben durar lo mismo; vuelve a renderizar.")


def check_text_area(rep: QCReport, text_area: TextArea, zone: dict[str, int], settings: Settings,
                    name: str, label: str) -> None:
    W, H = settings["video"]["width"], settings["video"]["height"]
    bad = text_area.outside(zone, W, H)
    margins = f"arriba {zone['top']}, abajo {zone['bottom']}, izquierda {zone['left']}, derecha {zone['right']} px"
    detail = (f"todo el texto queda dentro de la zona libre de {label} ({margins}); caja total {text_area.bbox}"
              if not bad else
              f"{len(bad)} fotogramas con texto bajo la interfaz de {label} ({margins}); "
              f"p. ej. t={bad[0][0]:.1f}s caja {bad[0][1]}")
    rep.add(name, not bad, detail,
            fix="Sube el texto o reduce su tamaño (layout y sizes en la plantilla), o ajusta ui_overlay si "
                "las medidas de la app han cambiado.")


def check_clean_file(rep: QCReport, info: dict[str, Any], provenance: dict[str, Any]) -> None:
    """No material taken from other apps (which would carry their watermark) and no app tags.

    The pipeline only overlays our own text and logo, so a watermark could only
    arrive through a source clip downloaded from a social network."""
    from_apps = [c["key"] for c in provenance.get("clips", [])
                 if any(d in (c.get("source_url") or "").lower() for d in PLATFORM_DOMAINS)]
    tags = {k: str(v) for k, v in (info.get("format", {}).get("tags") or {}).items()}
    tagged = [k for k, v in tags.items() if any(n in v.lower() for n in ("tiktok", "instagram", "youtube", "capcut"))]
    overlays = provenance.get("overlays", [])
    rep.add("sin_marcas_de_otras_apps", not from_apps and not tagged,
            f"clips de {sorted({c['source'] for c in provenance.get('clips', [])}) or '—'}; "
            f"superposiciones: {', '.join(overlays) or 'solo texto propio'}; metadatos del archivo: "
            f"{', '.join(f'{k}={v}' for k, v in tags.items()) or 'ninguno'}"
            + (f"; clips de redes sociales: {from_apps}" if from_apps else "")
            + (f"; etiquetas de apps: {tagged}" if tagged else ""),
            fix="No uses clips descargados de TikTok, Instagram o YouTube: llevan su marca de agua.")


def run_qc(*, production_id: str, video: Path, script: PrayerScript, narration: NarrationResult,
           cues: list[Cue], layout: SubtitleLayout, voice_stem: Path, music_bed: Path | None,
           provenance: dict[str, Any], settings: Settings, lead_in: float, outro_start: float,
           too_wide_cards: list[str] | None = None, warnings: list[str] | None = None,
           text_area: TextArea | None = None, expected_total: float | None = None) -> QCReport:
    v, a, q, sub = settings["video"], settings["audio"], settings["quality"], settings["subtitles"]
    rep = QCReport(production_id, str(video))
    rep.warnings.extend(warnings or [])

    # 1. File exists and plays -------------------------------------------------
    exists = video.exists() and video.stat().st_size > 0
    rep.add("archivo_existe", exists, str(video) if exists else "no se generó el MP4",
            fix="Revisa el log de FFmpeg en logs/.")
    if not exists:
        return rep
    ok, detail = _decodes_cleanly(video)
    rep.add("reproducible", ok, detail, fix="El archivo está dañado; vuelve a renderizar.")

    info = probe(video)
    astreams = [s for s in info["streams"] if s["codec_type"] == "audio"]
    duration = float(info["format"]["duration"])
    rep.metrics["duration_seconds"] = round(duration, 2)
    rep.metrics["file_size_mb"] = round(video.stat().st_size / 1e6, 2)

    # 2. Container, codecs, resolution, aspect ratio, frame rate --------------------
    check_file_spec(rep, info, video, settings)

    # 3. Audio present, not silent, not clipped ---------------------------------
    if astreams:
        loud = measure_loudness(video)
        rep.metrics["final_audio"] = loud
        tp_ok = loud["true_peak_db"] <= q["max_true_peak_db"]
        lufs_ok = abs(loud["integrated_lufs"] - a["target_lufs"]) <= q["loudness_tolerance_lu"]
        vol_ok = loud["mean_volume_db"] > q["min_mean_volume_db"]
        rep.add("audio_presente", vol_ok, f"volumen medio {loud['mean_volume_db']:.1f} dB",
                fix="El audio está vacío o casi en silencio.")
        rep.add("audio_sin_saturacion", tp_ok, f"pico real {loud['true_peak_db']:.1f} dBTP (máx {q['max_true_peak_db']})",
                fix="Baja el nivel o ajusta audio.true_peak_db.")
        rep.add("sonoridad_objetivo", lufs_ok,
                f"{loud['integrated_lufs']:.1f} LUFS (objetivo {a['target_lufs']} ± {q['loudness_tolerance_lu']})",
                fix="Revisa la normalización de audio.")
    else:
        rep.add("audio_presente", False, "sin pista de audio", fix="Vuelve a renderizar.")

    # 4. Narration present and music does not mask it ---------------------------
    voice = measure_loudness(voice_stem)
    rep.metrics["voice_stem"] = voice
    rep.add("narracion_presente", narration.duration > 1 and voice["mean_volume_db"] > q["min_mean_volume_db"],
            f"{narration.duration:.1f}s de narración, {len(narration.segments)} frases",
            fix="Regenera la voz.")
    if music_bed:
        music = measure_loudness(music_bed)
        rep.metrics["music_bed"] = music
        gap = voice["integrated_lufs"] - music["integrated_lufs"]
        rep.add("musica_no_tapa_voz", gap >= a["min_voice_over_music_db"],
                f"voz {gap:.1f} dB por encima de la música (mín {a['min_voice_over_music_db']}), con ducking={a['ducking']}",
                fix="Aumenta audio.music_below_voice_db.")
    # Voice, music and picture share one timeline: all three must span the whole video.
    stems = {"voz": duration_of(voice_stem)}
    if music_bed:
        stems["música"] = duration_of(music_bed)
    target = expected_total or duration
    off = {k: round(d - target, 3) for k, d in stems.items() if abs(d - target) > 0.1}
    rep.add("voz_musica_video_sincronizados", not off,
            ", ".join(f"{k} {d:.2f}s" for k, d in stems.items()) + f" · video {duration:.2f}s"
            + (f" · desfase {off}" if off else ""),
            fix="Las pistas de voz y música deben cubrir exactamente la duración del video.")

    # 5. Subtitles fit and are in sync ------------------------------------------
    too_wide = [c.text for c in cues for line in c.lines if not layout.fits(line, c.kind)]
    too_many = [c.text for c in cues if len(c.lines) > sub["max_lines"]]
    rep.add("subtitulos_dentro_de_pantalla", not too_wide and not too_many,
            f"{len(cues)} subtítulos; demasiado anchos: {len(too_wide)}; con demasiadas líneas: {len(too_many)}",
            fix="Reduce el tamaño de letra o max_words_per_cue.")
    rep.add("titulos_dentro_de_zona_segura", not too_wide_cards,
            "título y cierre caben en la zona segura" if not too_wide_cards
            else f"no caben: {', '.join(too_wide_cards)}",
            fix="Acorta el texto o reduce los tamaños en visual_style.json.")
    overlaps = [i for i in range(1, len(cues)) if cues[i].start < cues[i - 1].end - 1e-3]
    outside = [c.text for c in cues if c.start < 0 or c.end > duration + 0.05]
    in_span = all(lead_in - 0.01 <= c.start and c.end <= outro_start + 0.05 for c in cues)
    first_ok = bool(cues) and abs(cues[0].start - (lead_in + narration.segments[0].start)) < 0.05
    rep.add("subtitulos_sincronizados", not overlaps and not outside and in_span and first_ok,
            f"solapamientos: {len(overlaps)}; fuera del video: {len(outside)}; "
            f"primer subtítulo en {cues[0].start if cues else 0:.2f}s",
            fix="Regenera los subtítulos a partir de narration.json.")
    fast = [c.text for c in cues if len(c.text) / max(c.duration, 0.01) > sub["max_chars_per_second"]]
    if fast:
        rep.warnings.append(f"{len(fast)} subtítulos superan {sub['max_chars_per_second']} caracteres/s: "
                            + "; ".join(fast[:3]))

    if text_area is not None:
        rep.metrics["text_area"] = text_area.to_dict()
        check_text_area(rep, text_area, settings.style["safe_zone"], settings, "texto_en_zona_segura",
                        "todas las redes activadas")

    # 6. Duration for the prayer type ------------------------------------------------
    type_cfg = settings.prayer_type(script.type)
    lo, hi = type_cfg["min_seconds"], type_cfg["max_seconds"]
    rep.metrics["prayer_type"] = script.type
    rep.add("duracion_segun_tipo", lo <= duration <= hi,
            f"{duration:.1f}s para una oración '{script.type}' (rango {lo}-{hi}s)",
            fix="Ajusta la longitud del guion (sin relleno ni pausas artificiales) o cambia el tipo de oración.")

    # 7. Resources registered ---------------------------------------------------
    clips = provenance.get("clips", [])
    missing_meta = [c["key"] for c in clips if not c.get("license") or not (c.get("author") or c.get("source_url"))]
    rep.add("recursos_registrados", bool(clips) and not missing_meta and "voice" in provenance,
            f"{len(clips)} clips, música: {'sí' if provenance.get('music') else 'no'}, voz: {provenance.get('voice', {}).get('provider')}"
            + (f"; sin licencia/autor: {missing_meta}" if missing_meta else ""),
            fix="Completa la licencia y autoría de cada recurso.")

    check_clean_file(rep, info, provenance)

    # 8. Language consistency ---------------------------------------------------
    lang_desc = detect_language(script.description)
    lang_subs = detect_language(" ".join(c.text for c in cues))
    rep.add("idioma_coherente", lang_desc in (None, script.language) and lang_subs == script.language,
            f"guion={script.language}, descripción={lang_desc or 'indeterminado'}, subtítulos={lang_subs}",
            fix="La descripción o los subtítulos no están en el idioma del video.")

    # 9. Publication checks (licenses, verses, human review) --------------------
    music_meta = provenance.get("music")
    targets = settings.enabled_platforms()
    cleared = set(music_meta.get("cleared_platforms", [])) if music_meta else set()
    missing = [p for p in targets if p not in cleared]
    rep.add("musica_con_licencia_verificada", bool(music_meta) and not missing,
            (f"{music_meta['title']} — {music_meta['license']}; verificada para: "
             f"{', '.join(sorted(cleared)) or 'ninguna red'}") if music_meta else "sin música",
            category="publication",
            fix="Añade música instrumental con licencia comercial verificada para cada red (assets/music/"
                "music_library.json, platforms_verified).")
    rep.add("voz_con_uso_comercial", narration.commercial_use_cleared,
            f"{narration.provider} / {narration.voice_id}. {narration.license_note}".strip(),
            category="publication", fix="Usa un proveedor de voz IA con licencia comercial.")
    if script.bible_verse:
        bv = script.bible_verse
        rep.add("versiculo_verificado", bv.verification_status == "verified",
                f"{bv.reference} ({bv.translation}): {bv.verification_status}", category="publication",
                fix="Compara el texto con una edición fiable y marca verification.status='verified' en el guion.")
    rep.add("guion_revisado", script.review_status == "approved", f"revisión: {script.review_status}",
            category="publication", fix="Lee el guion y marca review.status='approved'.")
    return rep


# ---- per-platform versions ----------------------------------------------------------

def run_platform_qc(*, platform: str, production_id: str, video: Path, master_report: QCReport,
                    master_sha256: str, video_sha256: str, metadata: dict[str, Any], cover: Path | None,
                    srt: Path, master_srt: Path, provenance: dict[str, Any], script: PrayerScript,
                    settings: Settings) -> QCReport:
    cfg = settings.platform(platform)
    label = cfg.get("label", platform)
    rep = QCReport(f"{production_id}_{platform}", str(video))
    rep.metrics.update({k: v for k, v in master_report.metrics.items() if k != "text_area"})
    rep.metrics["platform"] = platform
    rep.warnings.extend(master_report.warnings)

    # Master checks (the music license is re-checked for this network below).
    for c in master_report.checks:
        if c.name != "musica_con_licencia_verificada":
            rep.checks.append(Check(c.name, c.passed, c.detail, c.category, c.fix))

    # 1. The file for this network --------------------------------------------------
    exists = video.exists() and video.stat().st_size > 0
    rep.add("archivo_plataforma", exists, video.name if exists else "falta el MP4", fix="Vuelve a exportar.")
    if not exists:
        return rep
    if video_sha256 == master_sha256:
        rep.add("copia_identica_del_maestro", True, "mismo contenido que el maestro (verificado por SHA-256)")
    else:
        ok, detail = _decodes_cleanly(video)
        rep.add("reproducible_plataforma", ok, detail, fix="La versión transcodificada está dañada.")
        info = probe(video)
        tmp = QCReport(rep.production_id, rep.video)
        check_file_spec(tmp, info, video, settings)
        for c in tmp.checks:
            rep.add(f"{c.name}_{platform}", c.passed, c.detail, c.category, c.fix)
    vcfg = cfg.get("video", {})
    duration = master_report.metrics.get("duration_seconds", 0)
    size_mb = video.stat().st_size / 1e6
    max_d, max_mb = vcfg.get("max_duration_seconds"), vcfg.get("max_file_size_mb")
    rep.add("limites_de_la_plataforma", (not max_d or duration <= max_d) and (not max_mb or size_mb <= max_mb),
            f"{duration:.1f}s (máx {max_d}s), {size_mb:.1f} MB (máx {max_mb} MB)",
            fix=f"Revisa los límites vigentes de {label} en platforms.json.")

    # 2. Text clear of this app's interface ------------------------------------------
    area = master_report.metrics.get("text_area")
    if area and cfg.get("ui_overlay"):
        check_text_area(rep, TextArea.from_dict(area), cfg["ui_overlay"], settings, "texto_libre_de_controles", label)
    else:
        rep.add("texto_libre_de_controles", False, "no hay medición del área de texto o falta ui_overlay",
                fix="Vuelve a producir el maestro.")

    # 3. Metadata ----------------------------------------------------------------------
    m = cfg.get("metadata", {})
    problems = []
    if m.get("has_title_field"):
        if not metadata.get("title"):
            problems.append("falta el título")
        elif len(metadata["title"]) > m.get("title_max_chars", 100):
            problems.append(f"título de {len(metadata['title'])} caracteres (máx {m.get('title_max_chars')})")
    caption = metadata.get("caption", "")
    if len(caption) > m.get("caption_max_chars", 2200):
        problems.append(f"texto de {len(caption)} caracteres (máx {m.get('caption_max_chars')})")
    tags = metadata.get("hashtags", [])
    if not tags:
        problems.append("sin hashtags")
    if len(tags) > m.get("max_hashtags", 30):
        problems.append(f"{len(tags)} hashtags (máx {m.get('max_hashtags')})")
    if len({t.lower() for t in tags}) != len(tags):
        problems.append("hashtags repetidos")
    lang = detect_language(" ".join([metadata.get("title") or "", metadata.get("description") or ""]))
    if lang not in (None, script.language):
        problems.append(f"los metadatos parecen estar en '{lang}'")
    rep.add("metadatos_adaptados", not problems,
            f"título: {metadata.get('title') or '—'}; {len(caption)} caracteres; {len(tags)} hashtags"
            + (f"; problemas: {'; '.join(problems)}" if problems else ""),
            fix=f"Ajusta el guion (platform_overrides.{platform}) o los límites de platforms.json.")

    # 4. Cover ---------------------------------------------------------------------------
    if cfg.get("cover", {}).get("upload_supported"):
        ok, detail = False, "falta cover.jpg"
        if cover and cover.exists():
            cs = next((s for s in probe(cover)["streams"] if s["codec_type"] == "video"), {})
            v = settings["video"]
            ok = (cs.get("width"), cs.get("height")) == (v["width"], v["height"])
            detail = f"{cover.name} {cs.get('width')}x{cs.get('height')}"
        rep.add("portada", ok, detail, fix="Vuelve a generar la portada (1080x1920).")
    else:
        frame = metadata.get("cover_frame_seconds")
        rep.add("portada", frame is not None,
                f"{label} usa un fotograma del video como portada: sugerido t={frame}s (tarjeta de título)",
                fix="Activa title_card_seconds para que haya un fotograma de portada con el título.")

    # 5. Subtitles file --------------------------------------------------------------------
    try:
        mine, ref = read_srt(srt), read_srt(master_srt)
        same = len(mine) == len(ref) and all(abs(a.start - b.start) < 0.01 and abs(a.end - b.end) < 0.01
                                             for a, b in zip(mine, ref))
        detail = f"{len(mine)} subtítulos, sincronizados con el maestro" if same else "no coincide con el maestro"
        in_video = all(c.end <= duration + 0.05 for c in mine)
        rep.add("archivo_srt", bool(mine) and same and in_video, detail,
                fix="Vuelve a exportar; el SRT debe coincidir con los subtítulos del video.")
    except (OSError, IndexError, ValueError) as exc:
        rep.add("archivo_srt", False, f"no se pudo leer: {exc}", fix="Vuelve a exportar.")

    # 6. Music licensed for this network (publication) -------------------------------------
    music = provenance.get("music")
    ok = bool(music and platform in music.get("cleared_platforms", []))
    rep.add("musica_con_licencia_para_la_red", ok,
            f"{music['title']} — {music['license']} ({'verificada' if ok else 'no verificada'} para {label})"
            if music else "sin música", category="publication",
            fix=f"Verifica que la licencia de la pista permita uso comercial en {label} "
                f"(platforms_verified.{platform} en music_library.json).")
    if music and platform == "youtube_shorts" and music.get("content_id_registered"):
        rep.warnings.append("La pista está registrada en Content ID: YouTube puede reclamar el video.")

    # 7. Recommendations (not blocking) ------------------------------------------------------
    rewards = cfg.get("creator_rewards")
    if rewards and script.type == "full":
        min_s = rewards.get("min_duration_seconds", 60)
        rep.metrics["creator_rewards_length_ok"] = duration > min_s
        if duration <= min_s:
            rep.warnings.append(f"Para Creator Rewards conviene que la oración completa dure más de {min_s}s "
                                f"(dura {duration:.1f}s). No la alargues con relleno: amplía el contenido del guion.")
    return rep
