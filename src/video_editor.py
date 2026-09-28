"""FFmpeg editing: vertical 1080x1920 video with clips, crossfades, text and mixed audio."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .ffmpeg_utils import run_ffmpeg
from .style import ResolvedFont
from .video_sources import Clip

log = logging.getLogger(__name__)


@dataclass
class Timeline:
    lead_in: float
    narration: float
    outro: float

    @property
    def total(self) -> float:
        return self.lead_in + self.narration + self.outro

    @property
    def outro_start(self) -> float:
        return self.lead_in + self.narration


def build_voice_stem(narration_wav: Path, timeline: Timeline, settings: Settings, out_path: Path) -> Path:
    """Delay the narration by the lead-in, pad to full length and normalize loudness."""
    a = settings["audio"]
    delay_ms = int(timeline.lead_in * 1000)
    af = (f"adelay={delay_ms}:all=1,apad,atrim=0:{timeline.total:.3f},"
          f"loudnorm=I={a['voice_stem_lufs']}:TP=-3:LRA=11")
    run_ffmpeg(["-i", str(narration_wav), "-af", af, "-ac", "2", "-ar", "48000",
                "-c:a", "pcm_s16le", str(out_path)])
    return out_path


def _clip_filter(i: int, clip: Clip, seg_len: float, settings: Settings) -> str:
    v, g = settings["video"], settings.style["color_grade"]
    W, H, fps = v["width"], v["height"], v["fps"]
    warmth = g.get("warmth", 0.0)
    fx = min(max(clip.focus_x, 0.0), 1.0)
    return (
        f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H}:x=(iw-{W})*{fx}:y=(ih-{H})/2,setsar=1,fps={fps},"
        f"eq=brightness={g['brightness']}:contrast={g['contrast']}:saturation={g['saturation']}:gamma={g['gamma']},"
        f"colorbalance=rm={warmth}:bm={-warmth},"
        f"trim=0:{seg_len:.3f},setpts=PTS-STARTPTS,format=yuv420p[c{i}]"
    )


def render_video(clips: list[Clip], voice_stem: Path, music_bed: Path | None, ass_file: Path,
                 fonts: dict[str, ResolvedFont], timeline: Timeline, settings: Settings,
                 work_dir: Path, out_path: Path) -> Path:
    if not clips:
        raise ValueError("At least one clip is required.")
    v, st, a = settings["video"], settings.style, settings["audio"]
    T = timeline.total
    n = len(clips)
    xf = min(v["crossfade_seconds"], T / (2 * n)) if n > 1 else 0.0
    seg_len = (T + (n - 1) * xf) / n

    # libass reads fonts from a folder next to the .ass file; paths stay relative
    # to the working directory, which avoids Windows drive-letter escaping issues.
    fonts_dir = work_dir / "fonts"
    fonts_dir.mkdir(exist_ok=True)
    for f in fonts.values():
        shutil.copy2(f.path, fonts_dir / f.path.name)
    local_ass = work_dir / "subtitles.ass"
    if ass_file.resolve() != local_ass.resolve():
        shutil.copy2(ass_file, local_ass)

    args: list[str] = []
    for clip in clips:
        args += ["-stream_loop", "-1", "-t", f"{seg_len + 0.5:.3f}", "-i", str(clip.path.resolve())]
    voice_idx = n
    args += ["-i", str(voice_stem.resolve())]
    music_idx = None
    if music_bed:
        music_idx = n + 1
        args += ["-i", str(music_bed.resolve())]
    logo_path = settings.path("branding_dir") / st["logo"]["file"]
    logo_idx = None
    if logo_path.exists():
        logo_idx = n + (2 if music_bed else 1)
        args += ["-i", str(logo_path.resolve())]

    parts = [_clip_filter(i, c, seg_len, settings) for i, c in enumerate(clips)]
    last = "c0"
    for i in range(1, n):
        offset = i * (seg_len - xf)
        parts.append(f"[{last}][c{i}]xfade=transition=fade:duration={xf:.3f}:offset={offset:.3f}[x{i}]")
        last = f"x{i}"
    overlay_hex = st["colors"]["overlay"].lstrip("#")
    fade_in, fade_out = st["fade_in_seconds"], st["fade_out_seconds"]
    parts.append(
        f"[{last}]trim=0:{T:.3f},drawbox=x=0:y=0:w=iw:h=ih:color=0x{overlay_hex}@{st['overlay_opacity']}:t=fill,"
        f"subtitles=subtitles.ass:fontsdir=fonts,"
        f"fade=t=in:st=0:d={fade_in},fade=t=out:st={T - fade_out:.3f}:d={fade_out}[vtxt]"
    )
    vout = "vtxt"
    if logo_idx is not None:
        lg = st["logo"]
        parts.append(f"[{logo_idx}:v]scale={lg['width']}:-1,format=rgba,"
                     f"colorchannelmixer=aa={lg['opacity']}[logo]")
        parts.append(f"[vtxt][logo]overlay=x={st['safe_zone']['left']}:y={st['safe_zone']['top']}[vlogo]")
        vout = "vlogo"
    parts.append(f"[{vout}]format=yuv420p[vout]")

    if music_idx is not None:
        if a["ducking"]:
            parts.append(f"[{voice_idx}:a]asplit=2[vmix][vkey]")
            parts.append(f"[{music_idx}:a][vkey]sidechaincompress=threshold=0.03:ratio=4:attack=30:release=600[mduck]")
            parts.append("[vmix][mduck]amix=inputs=2:normalize=0:duration=first[amixed]")
        else:
            parts.append(f"[{voice_idx}:a][{music_idx}:a]amix=inputs=2:normalize=0:duration=first[amixed]")
        audio_in = "amixed"
    else:
        audio_in = f"{voice_idx}:a"
    parts.append(f"[{audio_in}]loudnorm=I={a['target_lufs']}:TP={a['true_peak_db']}:LRA=11,"
                 f"aresample=48000,afade=t=out:st={T - fade_out:.3f}:d={fade_out}[aout]")

    args += [
        "-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]",
        "-t", f"{T:.3f}", "-r", str(v["fps"]),
        "-c:v", "libx264", "-preset", v["preset"], "-crf", str(v["crf"]),
        "-profile:v", "high", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", v["audio_bitrate"], "-ar", "48000",
        "-movflags", "+faststart", str(out_path.resolve()),
    ]
    log.info("Rendering %.1fs video from %d clips", T, n)
    run_ffmpeg(args, cwd=work_dir)
    return out_path
