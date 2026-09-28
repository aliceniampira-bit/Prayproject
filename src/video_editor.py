"""FFmpeg editing: the vertical master video (clips, transitions, text, mixed audio), its cover
image, and a text-only render used to verify that text stays clear of each app's interface."""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from .config import Settings
from .ffmpeg_utils import ffmpeg_bin, run_ffmpeg
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


def _even(x: float) -> int:
    return int(round(x / 2)) * 2


def _frame_chain(clip: Clip, settings: Settings, shot: int = 0, seg_len: float | None = None) -> str:
    """Scale/crop to the vertical canvas (with an optional slow pan) and apply the colour grade."""
    v, st = settings["video"], settings.style
    g = st["color_grade"]
    W, H, fps = v["width"], v["height"], v["fps"]
    warmth = g.get("warmth", 0.0)
    fx = min(max(clip.focus_x, 0.0), 1.0)
    motion = st.get("motion") or {}
    if motion.get("enabled") and seg_len:
        # Slow drift across a slightly larger frame: left, right, up or down, alternating by shot.
        k = 1 + float(motion.get("overscan", 0.08))
        amp_x, amp_y = W * (k - 1), H * (k - 1)
        prog = f"min(t/{seg_len:.3f},1)"
        dx, dy = {0: (amp_x, 0), 1: (-amp_x, 0), 2: (0, amp_y), 3: (0, -amp_y)}[shot % 4]
        x = f"'max(0,min(iw-{W},(iw-{W})*{fx}+{dx:.1f}*({prog}-0.5)))'"
        y = f"'max(0,min(ih-{H},(ih-{H})/2+{dy:.1f}*({prog}-0.5)))'"
        geom = (f"scale={_even(W * k)}:{_even(H * k)}:force_original_aspect_ratio=increase,"
                f"setpts=PTS-STARTPTS,crop={W}:{H}:x={x}:y={y}")
    else:
        geom = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:x=(iw-{W})*{fx}:y=(ih-{H})/2"
    return (f"{geom},setsar=1,fps={fps},"
            f"eq=brightness={g['brightness']}:contrast={g['contrast']}:saturation={g['saturation']}:gamma={g['gamma']},"
            f"colorbalance=rm={warmth}:bm={-warmth}")


def _clip_filter(i: int, clip: Clip, seg_len: float, settings: Settings) -> str:
    return (f"[{i}:v]{_frame_chain(clip, settings, i, seg_len)},"
            f"trim=0:{seg_len:.3f},setpts=PTS-STARTPTS,format=yuv420p[c{i}]")


def plan_shots(clips: list[Clip], total: float, settings: Settings) -> tuple[list[tuple[Clip, float]], float, float]:
    """Return (shots as (clip, source start), shot length, transition length)."""
    v = settings["video"]
    hard_cuts = v.get("transition", "crossfade") == "cut"
    target = v.get("target_clip_seconds")
    n = max(1, round(total / target)) if target else len(clips)
    xf = 0.0 if hard_cuts or n == 1 else min(v["crossfade_seconds"], total / (2 * n))
    seg_len = (total + (n - 1) * xf) / n
    # Reuse clips (from a later point) when there are fewer clips than shots.
    shots = [(clips[i % len(clips)], (i // len(clips)) * seg_len) for i in range(n)]
    return shots, seg_len, xf


def encoding_args(settings: Settings) -> list[str]:
    """Master encoding from settings.video (codec, profile, pixel format, audio)."""
    v = settings["video"]
    args = ["-r", str(v["fps"]), "-c:v", v.get("video_codec", "libx264"), "-preset", v["preset"],
            "-crf", str(v["crf"]), "-pix_fmt", v.get("pixel_format", "yuv420p")]
    if v.get("video_codec", "libx264") == "libx264":
        args += ["-profile:v", v.get("h264_profile", "high")]
        if v.get("h264_level"):
            args += ["-level:v", str(v["h264_level"])]
    args += ["-c:a", v.get("audio_codec", "aac"), "-b:a", v["audio_bitrate"],
             "-ar", str(v.get("audio_sample_rate", 48000)),
             # A clean file: no metadata carried over from the source clips.
             "-map_metadata", "-1", "-map_chapters", "-1"]
    if v.get("container", "mp4") == "mp4":
        args += ["-movflags", "+faststart"]
    return args


def render_video(clips: list[Clip], voice_stem: Path, music_bed: Path | None, ass_file: Path,
                 fonts: dict[str, ResolvedFont], timeline: Timeline, settings: Settings,
                 work_dir: Path, out_path: Path) -> Path:
    if not clips:
        raise ValueError("At least one clip is required.")
    v, st, a = settings["video"], settings.style, settings["audio"]
    T = timeline.total
    shots, seg_len, xf = plan_shots(clips, T, settings)
    n = len(shots)
    hard_cuts = xf == 0.0

    _stage_fonts(fonts, work_dir)
    local_ass = work_dir / "subtitles.ass"
    if ass_file.resolve() != local_ass.resolve():
        shutil.copy2(ass_file, local_ass)

    args: list[str] = []
    for clip, start in shots:
        args += ["-stream_loop", "-1", "-ss", f"{start:.3f}", "-t", f"{seg_len + 0.5:.3f}",
                 "-i", str(clip.path.resolve())]
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

    parts = [_clip_filter(i, c, seg_len, settings) for i, (c, _) in enumerate(shots)]
    if hard_cuts or n == 1:
        parts.append("".join(f"[c{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[joined]")
        last = "joined"
    else:
        last = "c0"
        for i in range(1, n):
            offset = i * (seg_len - xf)
            parts.append(f"[{last}][c{i}]xfade=transition=fade:duration={xf:.3f}:offset={offset:.3f}[x{i}]")
            last = f"x{i}"
    overlay_hex = st["colors"]["overlay"].lstrip("#")
    fade_in, fade_out = st["fade_in_seconds"], st["fade_out_seconds"]
    dim = float(st.get("card_dim", 0) or 0)
    dim_filter = ""
    if dim:
        # Darken the picture a little while the title and closing cards are on screen.
        ts, os_ = v.get("title_card_seconds", 0), timeline.outro_start
        env = (f"if(lt(t,{ts:.2f}),1,max(0,1-(t-{ts:.2f})/0.8))*gt({ts:.2f},0)" if ts else "0")
        if v.get("closing_card", True):
            env += f"+min(1,max(0,(t-{os_:.2f})/0.8))"
        dim_filter = f"eq=brightness='-{dim}*({env})':eval=frame,"
    parts.append(
        f"[{last}]trim=0:{T:.3f},{dim_filter}"
        f"drawbox=x=0:y=0:w=iw:h=ih:color=0x{overlay_hex}@{st['overlay_opacity']}:t=fill,"
        + ("vignette=angle=PI/4.5," if st.get("vignette") else "")
        + "subtitles=subtitles.ass:fontsdir=fonts,"
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

    args += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]", "-t", f"{T:.3f}",
             *encoding_args(settings), str(out_path.resolve())]
    log.info("Rendering %.1fs video: %d shots from %d clips (%s)", T, n, len(clips),
             "hard cuts" if hard_cuts else "crossfades")
    run_ffmpeg(args, cwd=work_dir)
    return out_path


def _stage_fonts(fonts: dict[str, ResolvedFont], work_dir: Path) -> None:
    # libass reads fonts from a folder next to the .ass file; paths stay relative
    # to the working directory, which avoids Windows drive-letter escaping issues.
    fonts_dir = work_dir / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    for f in fonts.values():
        shutil.copy2(f.path, fonts_dir / f.path.name)


def render_cover(clip: Clip, at_seconds: float, ass_file: Path, fonts: dict[str, ResolvedFont],
                 settings: Settings, work_dir: Path, out_path: Path) -> Path:
    """Cover image: a graded frame of a background clip with the title card on top."""
    st = settings.style
    _stage_fonts(fonts, work_dir)
    local_ass = work_dir / "cover.ass"
    if ass_file.resolve() != local_ass.resolve():
        shutil.copy2(ass_file, local_ass)
    overlay_hex = st["colors"]["overlay"].lstrip("#")
    vf = (f"{_frame_chain(clip, settings)},"
          f"drawbox=x=0:y=0:w=iw:h=ih:color=0x{overlay_hex}@{min(st['overlay_opacity'] + 0.1, 0.6)}:t=fill,"
          + ("vignette=angle=PI/4.5," if st.get("vignette") else "")
          + "setpts=PTS-STARTPTS+5/TB,subtitles=cover.ass:fontsdir=fonts")
    run_ffmpeg(["-ss", f"{max(at_seconds, 0):.3f}", "-i", str(clip.path.resolve()), "-vf", vf,
                "-frames:v", "1", "-q:v", "2", str(out_path.resolve())], cwd=work_dir)
    return out_path


@dataclass
class TextArea:
    """Where text appears on screen over the whole video (union of all frames)."""
    bbox: tuple[int, int, int, int] | None     # left, top, right, bottom in canvas pixels
    frames_with_text: int
    frames: int
    per_frame: list[tuple[float, tuple[int, int, int, int]]]

    def outside(self, zone: dict[str, int], width: int, height: int,
                tolerance: int = 6) -> list[tuple[float, tuple[int, int, int, int]]]:
        """Frames whose text box enters the given margins (top/bottom/left/right)."""
        left, top = zone.get("left", 0) - tolerance, zone.get("top", 0) - tolerance
        right, bottom = width - zone.get("right", 0) + tolerance, height - zone.get("bottom", 0) + tolerance
        return [(t, b) for t, b in self.per_frame
                if b[0] < left or b[1] < top or b[2] > right or b[3] > bottom]

    def to_dict(self) -> dict:
        return {"bbox": list(self.bbox) if self.bbox else None, "frames_with_text": self.frames_with_text,
                "frames_sampled": self.frames,
                "per_frame": [[round(t, 2), list(b)] for t, b in self.per_frame]}

    @classmethod
    def from_dict(cls, d: dict) -> "TextArea":
        return cls(tuple(d["bbox"]) if d.get("bbox") else None, d["frames_with_text"], d["frames_sampled"],
                   [(t, tuple(b)) for t, b in d.get("per_frame", [])])


def measure_text_area(ass_file: Path, fonts: dict[str, ResolvedFont], duration: float, settings: Settings,
                      work_dir: Path, fps: float = 6.0, scale: int = 4, threshold: int = 28,
                      extra_boxes: list[tuple[int, int, int, int]] | None = None) -> TextArea:
    """Render only the text layer on black and measure where lit pixels land.

    This checks what is really drawn (font metrics, line breaks, shadows) instead
    of trusting the layout maths, so QC can compare it with each app's interface.
    """
    v = settings["video"]
    W, H = v["width"], v["height"]
    w, h = W // scale, H // scale
    _stage_fonts(fonts, work_dir)
    local_ass = work_dir / "textarea.ass"
    shutil.copy2(ass_file, local_ass)
    cmd = [ffmpeg_bin(), "-v", "error", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={fps}:d={duration:.3f}",
           "-vf", f"subtitles=textarea.ass:fontsdir=fonts,scale={w}:{h}:flags=area,format=gray",
           "-f", "rawvideo", "-"]
    proc = subprocess.run(cmd, cwd=work_dir, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Text area render failed: {proc.stderr.decode(errors='replace')[-400:]}")
    frame_size = w * h
    per_frame = []
    frames = len(proc.stdout) // frame_size
    for i in range(frames):
        img = Image.frombytes("L", (w, h), proc.stdout[i * frame_size:(i + 1) * frame_size])
        box = img.point(lambda px: 255 if px > threshold else 0).getbbox()
        if box:
            per_frame.append((i / fps, (box[0] * scale, box[1] * scale, box[2] * scale, box[3] * scale)))
    boxes = [b for _, b in per_frame] + list(extra_boxes or [])
    union = None
    if boxes:
        union = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
    for b in extra_boxes or []:
        per_frame.append((-1.0, b))
    return TextArea(union, len(per_frame), frames, per_frame)
