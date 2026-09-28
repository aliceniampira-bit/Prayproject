"""Visual template helpers: font resolution, colors and text measurement."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont


class StyleError(RuntimeError):
    pass


def _system_font_dirs() -> list[Path]:
    dirs: list[Path] = []
    system = platform.system()
    if system == "Windows":
        dirs.append(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif system == "Darwin":
        dirs += [Path("/System/Library/Fonts/Supplemental"), Path("/System/Library/Fonts"),
                 Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"]
    else:
        dirs += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".fonts",
                 Path.home() / ".local" / "share" / "fonts"]
    return [d for d in dirs if d.exists()]


@lru_cache(maxsize=None)
def _find_in(directory: Path, filename: str) -> Path | None:
    direct = directory / filename
    if direct.exists():
        return direct
    lower = filename.lower()
    for p in directory.rglob("*"):
        if p.name.lower() == lower:
            return p
    return None


@dataclass(frozen=True)
class ResolvedFont:
    path: Path
    family: str
    bold: bool
    italic: bool
    is_fallback: bool


def resolve_font(spec: dict, fonts_dir: Path) -> ResolvedFont:
    """Find the configured font in assets/fonts, else the first available fallback."""
    candidates = [spec["file"], *spec.get("fallbacks", [])]
    for i, name in enumerate(candidates):
        for directory in [fonts_dir, *_system_font_dirs()]:
            if not directory.exists():
                continue
            found = _find_in(directory, name)
            if found:
                family, style = _legacy_names(found)
                style_l = (style or "").lower()
                return ResolvedFont(found, family, "bold" in style_l,
                                    "italic" in style_l or "oblique" in style_l, i > 0)
    raise StyleError(f"No font found for {candidates}. Put the font file in {fonts_dir}.")


def _legacy_names(path: Path) -> tuple[str, str]:
    """Family and style as libass matches them (name table IDs 1 and 2).

    Static instances of variable fonts (e.g. "Lora Medium") use a different
    legacy family than the typographic family Pillow reports ("Lora"); libass
    only knows the legacy one, so using Pillow's name would silently fall back
    to another font."""
    try:
        from fontTools.ttLib import TTFont
        with TTFont(str(path), fontNumber=0, lazy=True) as font:
            names = font["name"]
            family, style = names.getDebugName(1), names.getDebugName(2)
            if family:
                return family, style or "Regular"
    except Exception:  # fontTools missing or unusual file: fall back to Pillow
        pass
    return ImageFont.truetype(str(path), 20).getname()


def ass_color(hex_color: str, alpha: float = 0.0) -> str:
    """#RRGGBB -> ASS &HAABBGGRR (alpha 0 = opaque)."""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    a = int(round(alpha * 255))
    return f"&H{a:02X}{b}{g}{r}".upper()


def libass_equivalent_size(font_path: Path, ass_size: int) -> int:
    """Pixel em-size that libass actually renders for an ASS ``Fontsize``.

    libass scales a font so that its ascent + descent equals the ASS font size,
    while Pillow's size is the em size, so measuring at the raw size would
    overestimate widths (by ~15-25 % for common fonts).
    """
    probe_size = 1000
    ascent, descent = ImageFont.truetype(str(font_path), probe_size).getmetrics()
    return max(1, round(ass_size * probe_size / (ascent + descent)))


class TextMeasurer:
    """Measures rendered line width in pixels with the real font file."""

    def __init__(self, font_path: Path, size: int, outline_px: int = 0):
        self.font = ImageFont.truetype(str(font_path), libass_equivalent_size(font_path, size))
        self.outline_px = outline_px

    def width(self, text: str) -> float:
        return self.font.getlength(text) + 2 * self.outline_px
