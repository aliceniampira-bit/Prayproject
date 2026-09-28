"""Quality control: technical and publication checks before a video is approved."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .ffmpeg_utils import ffmpeg_bin, measure_loudness, probe
from .script_generator import PrayerScript, detect_language
from .subtitle_generator import Cue, SubtitleLayout
from .voice_generator import NarrationResult


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
        lines += ["", "## Métricas", "", "```json", json.dumps(self.metrics, indent=2, ensure_ascii=False), "```"]
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


def run_qc(*, production_id: str, video: Path, script: PrayerScript, narration: NarrationResult,
           cues: list[Cue], layout: SubtitleLayout, voice_stem: Path, music_bed: Path | None,
           provenance: dict[str, Any], settings: Settings, lead_in: float, outro_start: float,
           too_wide_cards: list[str] | None = None, warnings: list[str] | None = None) -> QCReport:
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
    vstreams = [s for s in info["streams"] if s["codec_type"] == "video"]
    astreams = [s for s in info["streams"] if s["codec_type"] == "audio"]
    duration = float(info["format"]["duration"])
    rep.metrics["duration_seconds"] = round(duration, 2)

    # 2. Resolution and aspect ratio -------------------------------------------
    if vstreams:
        w, h = int(vstreams[0]["width"]), int(vstreams[0]["height"])
        good = (w, h) == (v["width"], v["height"]) and w * 16 == h * 9
        rep.add("resolucion_9_16", good, f"{w}x{h}, códec {vstreams[0]['codec_name']}",
                fix=f"Debe ser {v['width']}x{v['height']} (9:16).")
    else:
        rep.add("resolucion_9_16", False, "sin pista de video", fix="Vuelve a renderizar.")

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

    # 6. Duration ------------------------------------------------------------------
    lo, hi = v["min_duration_seconds"], v["max_duration_seconds"]
    rep.add("duracion_en_rango", lo <= duration <= hi, f"{duration:.1f}s (rango {lo}-{hi}s)",
            fix="Ajusta la longitud del guion (sin relleno artificial) o el rango configurado.")

    # 7. Resources registered ---------------------------------------------------
    clips = provenance.get("clips", [])
    missing_meta = [c["key"] for c in clips if not c.get("license") or not (c.get("author") or c.get("source_url"))]
    rep.add("recursos_registrados", bool(clips) and not missing_meta and "voice" in provenance,
            f"{len(clips)} clips, música: {'sí' if provenance.get('music') else 'no'}, voz: {provenance.get('voice', {}).get('provider')}"
            + (f"; sin licencia/autor: {missing_meta}" if missing_meta else ""),
            fix="Completa la licencia y autoría de cada recurso.")

    # 8. Language consistency ---------------------------------------------------
    lang_desc = detect_language(script.tiktok_description)
    lang_subs = detect_language(" ".join(c.text for c in cues))
    rep.add("idioma_coherente", lang_desc in (None, script.language) and lang_subs == script.language,
            f"guion={script.language}, descripción={lang_desc or 'indeterminado'}, subtítulos={lang_subs}",
            fix="La descripción o los subtítulos no están en el idioma del video.")

    # 9. Publication checks (licenses, verses, human review) --------------------
    music_meta = provenance.get("music")
    rep.add("musica_con_licencia_verificada", bool(music_meta and music_meta.get("cleared_for_publication")),
            f"{music_meta['title']} — {music_meta['license']}" if music_meta else "sin música",
            category="publication",
            fix="Añade música instrumental con licencia comercial verificada para TikTok (assets/music).")
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
