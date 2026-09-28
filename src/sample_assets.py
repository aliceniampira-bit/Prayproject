"""Generate synthetic, locally-made test media so the prototype runs offline.

These are NOT meant for publication: the clips are animated gradients and the
music is a simple generated pad. They are marked as test-only in their metadata,
so quality control blocks any video that uses them.
"""

from __future__ import annotations

import json
from pathlib import Path

from .ffmpeg_utils import run_ffmpeg

# Twilight palettes (sky -> horizon glow -> dark land), in the spirit of dusk landscapes.
PALETTES = {
    "dusk_orange": ("0x1a1f33", "0x4a3550", "0xd9772b", "0x120d0c"),
    "night_blue": ("0x070b18", "0x1b2a4a", "0x3d5a80", "0x0b0f12"),
    "ember_sky": ("0x2b1a2f", "0x8a3b2e", "0xf2a14a", "0x16110d"),
    "misty_green": ("0x5f6b6d", "0x2f4a3f", "0x1d2e27", "0x0d1411"),
    "violet_hour": ("0x1c1433", "0x5b3a6b", "0xe08a5a", "0x0f0c14"),
    "storm_grey": ("0x3b4046", "0x6c737a", "0x23282c", "0x0e1012"),
}

# Chord progression Am - F - C - G (4 s per chord); four arpeggio notes per chord.
_CHORDS = [
    (220.00, 261.63, 329.63, 440.00),
    (174.61, 220.00, 261.63, 349.23),
    (261.63, 329.63, 392.00, 523.25),
    (196.00, 246.94, 293.66, 392.00),
]


def _ambient_piano_expr() -> str:
    """aevalsrc expression: soft piano-like arpeggio over a low pad."""
    def pick(var: int, values) -> str:
        expr = str(values[-1])
        for i in range(len(values) - 2, -1, -1):
            expr = f"if(eq(ld({var}),{i}),{values[i]},{expr})"
        return expr
    note = "if(eq(ld(0),0),{a},if(eq(ld(0),1),{b},if(eq(ld(0),2),{c},{d})))".format(
        a=pick(1, _CHORDS[0]), b=pick(1, _CHORDS[1]), c=pick(1, _CHORDS[2]), d=pick(1, _CHORDS[3]))
    root = pick(0, [c[0] for c in _CHORDS])
    return ("st(0,floor(mod(t,16)/4));st(1,mod(floor(t*1.5),4));"
            f"st(2,{note});st(3,{root});"
            "0.22*sin(2*PI*ld(2)*t)*exp(-2.2*mod(t,1/1.5))"
            "+0.06*sin(2*PI*ld(2)*2*t)*exp(-4*mod(t,1/1.5))"
            "+0.07*sin(2*PI*ld(3)/2*t)+0.04*sin(2*PI*ld(3)*0.75*t)")


def make_sample_assets(folder: Path, clip_seconds: int = 12, music_seconds: int = 40) -> Path:
    clips_dir = folder / "clips"
    music_dir = folder / "music"
    clips_dir.mkdir(parents=True, exist_ok=True)
    music_dir.mkdir(parents=True, exist_ok=True)

    entries = []
    for name, (c0, c1, c2, c3) in PALETTES.items():
        out = clips_dir / f"{name}.mp4"
        if not out.exists():
            src = (f"gradients=s=1080x1920:r=30:d={clip_seconds}:c0={c0}:c1={c1}:c2={c2}:c3={c3}"
                   f":nb_colors=4:x0=540:y0=0:x1=540:y1=1920:speed=0.003:seed=7")
            run_ffmpeg(["-f", "lavfi", "-i", src, "-vf", "noise=alls=5:allf=t,format=yuv420p",
                        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", str(out)])
        entries.append({"file": out.name, "title": f"Synthetic gradient ({name})", "author": "Daily Prayer Studio",
                        "source_url": "", "license": "Generated locally — test only", "license_url": "",
                        "focus_x": 0.5, "themes": [], "has_identifiable_people": False})
    (clips_dir / "clips.json").write_text(json.dumps({"clips": entries}, indent=2) + "\n", encoding="utf-8")

    pad = music_dir / "test-ambient-piano.wav"
    if not pad.exists():
        run_ffmpeg(["-f", "lavfi", "-i", f"aevalsrc='{_ambient_piano_expr()}':s=48000:d={music_seconds}",
                    "-af", "lowpass=f=2500,aecho=0.8:0.6:180|360|540:0.4|0.25|0.15,"
                           f"afade=t=in:d=2,afade=t=out:st={music_seconds - 3}:d=3",
                    "-ac", "2", str(pad)])
    library = {"tracks": [{
        "id": "test-ambient-piano", "file": pad.name, "title": "Generated ambient piano (test)", "artist": "Daily Prayer Studio",
        "source_url": "", "license": "Generated locally — test only", "license_url": "", "instrumental": True,
        "commercial_use_verified": False,
        "platforms_verified": {"tiktok": False, "instagram_reels": False, "youtube_shorts": False},
        "restrictions": "Test tone for pipeline development. Do not publish.",
        "verified_by": None, "verified_on": None}]}
    (music_dir / "music_library.json").write_text(json.dumps(library, indent=2) + "\n", encoding="utf-8")
    return folder
