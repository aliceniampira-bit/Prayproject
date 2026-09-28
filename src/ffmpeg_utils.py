"""Thin wrappers around the ffmpeg / ffprobe command line tools."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class FFmpegError(RuntimeError):
    pass


def ffmpeg_bin() -> str:
    return os.environ.get("FFMPEG_BIN", "ffmpeg")


def ffprobe_bin() -> str:
    return os.environ.get("FFPROBE_BIN", "ffprobe")


def check_tools() -> dict[str, str | None]:
    """Return the version line of ffmpeg/ffprobe, or None if not installed."""
    result: dict[str, str | None] = {}
    for name, binary in (("ffmpeg", ffmpeg_bin()), ("ffprobe", ffprobe_bin())):
        if not shutil.which(binary):
            result[name] = None
            continue
        out = subprocess.run([binary, "-version"], capture_output=True, text=True)
        result[name] = out.stdout.splitlines()[0] if out.stdout else "unknown version"
    return result


def require_ffmpeg() -> None:
    missing = [k for k, v in check_tools().items() if v is None]
    if missing:
        raise FFmpegError(
            f"Not found on PATH: {', '.join(missing)}. Install FFmpeg (see README) "
            "or set FFMPEG_BIN / FFPROBE_BIN in .env."
        )


def run_ffmpeg(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [ffmpeg_bin(), "-hide_banner", "-y", *args]
    log.debug("ffmpeg %s", " ".join(args))
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
        raise FFmpegError(f"ffmpeg failed (exit {proc.returncode}):\n{tail}")
    return proc


def probe(path: Path) -> dict:
    cmd = [ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe could not read {path}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def duration_of(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def measure_loudness(path: Path, stream_filter: str = "") -> dict[str, float]:
    """Integrated loudness (LUFS), true peak (dBTP) and mean volume (dB) of the audio."""
    chain = f"{stream_filter}," if stream_filter else ""
    proc = run_ffmpeg(["-nostats", "-i", str(path), "-map", "0:a:0",
                       "-af", f"{chain}ebur128=peak=true,volumedetect", "-f", "null", "-"])
    err = proc.stderr
    summary = err[err.rfind("Summary:"):] if "Summary:" in err else err

    def grab(pattern: str, text: str) -> float:
        m = re.search(pattern, text)
        return float(m.group(1)) if m else float("-inf")

    return {
        "integrated_lufs": grab(r"I:\s+(-?[\d.]+|-inf) LUFS", summary),
        "true_peak_db": grab(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summary),
        "mean_volume_db": grab(r"mean_volume:\s+(-?[\d.]+) dB", err),
        "max_volume_db": grab(r"max_volume:\s+(-?[\d.]+) dB", err),
    }


def escape_filter_path(path: str) -> str:
    """Escape a path for use inside an ffmpeg filter argument."""
    return path.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
