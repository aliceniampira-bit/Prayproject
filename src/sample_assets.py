"""Generate synthetic, locally-made test media so the prototype runs offline.

These are NOT meant for publication: the clips are animated gradients and the
music is a simple generated pad. They are marked as test-only in their metadata,
so quality control blocks any video that uses them.
"""

from __future__ import annotations

import json
from pathlib import Path

from .ffmpeg_utils import run_ffmpeg

PALETTES = {
    "dawn": ("0x1b2a4a", "0x6b4c7a", "0xe89a5c", "0xf6d59a"),
    "sea": ("0x0b2233", "0x1f5f7a", "0x7fb7c9", "0xe9e2c9"),
    "forest": ("0x0f1f14", "0x2e5638", "0x8fa86b", "0xf0dfa8"),
}


def make_sample_assets(folder: Path, clip_seconds: int = 12, music_seconds: int = 40) -> Path:
    clips_dir = folder / "clips"
    music_dir = folder / "music"
    clips_dir.mkdir(parents=True, exist_ok=True)
    music_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for name, (c0, c1, c2, c3) in PALETTES.items():
        out = clips_dir / f"{name}.mp4"
        if not out.exists():
            src = (f"gradients=s=1920x1080:r=30:d={clip_seconds}:c0={c0}:c1={c1}:c2={c2}:c3={c3}"
                   f":nb_colors=4:speed=0.004:seed=7")
            run_ffmpeg(["-f", "lavfi", "-i", src, "-vf", "noise=alls=5:allf=t,format=yuv420p",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", str(out)])
        entries.append({"file": out.name, "title": f"Synthetic gradient ({name})", "author": "Daily Prayer Studio",
                        "source_url": "", "license": "Generated locally — test only", "license_url": "",
                        "focus_x": 0.5, "themes": [], "has_identifiable_people": False})
    (clips_dir / "clips.json").write_text(json.dumps({"clips": entries}, indent=2) + "\n", encoding="utf-8")

    pad = music_dir / "test-pad.wav"
    if not pad.exists():
        expr = ("0.10*sin(2*PI*220*t)*(0.7+0.3*sin(2*PI*0.13*t))"
                "+0.07*sin(2*PI*277.18*t)*(0.7+0.3*sin(2*PI*0.09*t))"
                "+0.07*sin(2*PI*329.63*t)*(0.7+0.3*sin(2*PI*0.11*t))"
                "+0.04*sin(2*PI*440*t)")
        run_ffmpeg(["-f", "lavfi", "-i", f"aevalsrc={expr}:s=48000:d={music_seconds}",
                    "-af", "lowpass=f=1800,aecho=0.8:0.7:120|240:0.35|0.2,afade=t=in:d=2,"
                           f"afade=t=out:st={music_seconds - 3}:d=3",
                    "-ac", "2", str(pad)])
    library = {"tracks": [{
        "id": "test-pad", "file": pad.name, "title": "Generated test pad", "artist": "Daily Prayer Studio",
        "source_url": "", "license": "Generated locally — test only", "license_url": "", "instrumental": True,
        "commercial_use_verified": False, "tiktok_use_verified": False,
        "restrictions": "Test tone for pipeline development. Do not publish.",
        "verified_by": None, "verified_on": None}]}
    (music_dir / "music_library.json").write_text(json.dumps(library, indent=2) + "\n", encoding="utf-8")
    return folder
