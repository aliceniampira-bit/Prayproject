"""Subtitles: split narration into short cues, write SRT and styled ASS.

Timing comes from the sentence timestamps produced by voice_generator; each
sentence is split into cues proportionally to character count. If automatic
speech recognition is added later, its output must go through the same review
step (edit the SRT, then re-render).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .config import Settings
from .style import ResolvedFont, TextMeasurer, ass_color
from .voice_generator import NarrationSegment


@dataclass
class Cue:
    start: float
    end: float
    lines: list[str]
    kind: str = "prayer"
    reference: str | None = None

    @property
    def text(self) -> str:
        return " ".join(self.lines)

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class SubtitleLayout:
    max_width_px: float
    max_lines: int
    max_words: int
    measure: Callable[[str], float]
    verse_measure: Callable[[str], float] | None = None
    language: str = "en"

    def fits(self, line: str, kind: str = "prayer") -> bool:
        m = self.verse_measure if kind == "verse" and self.verse_measure else self.measure
        return m(line) <= self.max_width_px


# Words a line or cue should not end with (articles, prepositions, conjunctions,
# unstressed pronouns). Breaking after them reads unnaturally.
WEAK_ENDINGS = {
    "en": {"a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "at", "for", "with", "from", "by",
           "my", "your", "his", "her", "our", "their", "its", "i", "we", "you", "that", "which", "who",
           "is", "am", "are", "be", "not", "so", "as", "if", "when", "what", "this", "every"},
    "es": {"el", "la", "los", "las", "un", "una", "unos", "unas", "y", "e", "o", "u", "ni", "pero", "de",
           "del", "al", "en", "con", "por", "para", "sin", "sobre", "que", "mi", "mis", "tu", "tus", "su",
           "sus", "nuestro", "nuestra", "me", "te", "se", "nos", "lo", "le", "les", "no", "cuando", "si",
           "como", "a", "esta", "este", "cada", "todo"},
}


def is_weak_ending(word: str, language: str = "en") -> bool:
    if word[-1:] in ",.;:!?…":
        return False
    return word.lower().strip("¿¡\"'“”«»") in WEAK_ENDINGS.get(language, set())


def wrap_lines(words: list[str], layout: SubtitleLayout, kind: str = "prayer",
               strict: bool = False) -> list[str] | None:
    """Return balanced lines for ``words`` or None if they cannot fit.

    With ``strict`` a two-line split that ends a line on a weak word is rejected,
    so the caller starts a new cue instead of producing an awkward break.
    """
    one = " ".join(words)
    if layout.fits(one, kind) and len(words) <= 4:
        return [one]
    if layout.max_lines == 1 or len(words) == 1:
        return [one] if layout.fits(one, kind) else None
    m = layout.verse_measure if kind == "verse" and layout.verse_measure else layout.measure
    best: tuple[float, list[str]] | None = None
    for cut in range(1, len(words)):
        a, b = " ".join(words[:cut]), " ".join(words[cut:])
        if layout.fits(a, kind) and layout.fits(b, kind):
            score = max(m(a), m(b))
            if is_weak_ending(words[cut - 1], layout.language):
                if strict:
                    continue
                score += layout.max_width_px * 0.35
            if words[cut - 1][-1:] in ",;:":
                score -= layout.max_width_px * 0.1
            if best is None or score < best[0]:
                best = (score, [a, b])
    if best:
        return best[1]
    return [one] if layout.fits(one, kind) else None


_CLAUSE_RE = re.compile(r"(?<=[,;:—])\s+")


def chunk_sentence(sentence: str, layout: SubtitleLayout, kind: str = "prayer") -> list[list[str]]:
    """Split a sentence into cues (each a list of lines), breaking at clauses first."""
    clauses = [c.split() for c in _CLAUSE_RE.split(sentence.strip()) if c.strip()]
    chunks: list[list[str]] = []
    current: list[str] = []
    for clause in clauses:
        candidate = current + clause
        if current and len(candidate) <= layout.max_words and wrap_lines(candidate, layout, kind, strict=True):
            current = candidate
            continue
        if len(current) >= 3:
            chunks.append(current)
            current = []
        for word in clause:
            candidate = current + [word]
            if current and (len(candidate) > layout.max_words
                            or not wrap_lines(candidate, layout, kind, strict=True)):
                # Carry weak trailing words ("the", "de", "te"...) over to the next cue.
                carry: list[str] = []
                while len(current) > 2 and is_weak_ending(current[-1], layout.language):
                    carry.insert(0, current.pop())
                chunks.append(current)
                current = carry + [word]
            else:
                current = candidate
    if current:
        chunks.append(current)
    chunks = _absorb_orphans(chunks, layout, kind)
    result = []
    for words in chunks:
        lines = wrap_lines(words, layout, kind)
        if lines is None:
            raise ValueError(f"Word too wide for subtitle area: {' '.join(words)!r}")
        result.append(lines)
    return result


def _absorb_orphans(chunks: list[list[str]], layout: SubtitleLayout, kind: str) -> list[list[str]]:
    """Avoid one-word cues: merge them into a neighbour, or borrow a word from it."""
    i = 0
    while len(chunks) > 1 and i < len(chunks):
        if len(chunks[i]) > 1:
            i += 1
            continue
        prev_merge = chunks[i - 1] + chunks[i] if i > 0 else None
        next_merge = chunks[i] + chunks[i + 1] if i + 1 < len(chunks) else None
        if next_merge and len(next_merge) <= layout.max_words and wrap_lines(next_merge, layout, kind, strict=True):
            chunks[i:i + 2] = [next_merge]
        elif prev_merge and len(prev_merge) <= layout.max_words and wrap_lines(prev_merge, layout, kind, strict=True):
            chunks[i - 1:i + 1] = [prev_merge]
            i -= 1
        elif i > 0 and len(chunks[i - 1]) > 3:
            chunks[i].insert(0, chunks[i - 1].pop())
            if not wrap_lines(chunks[i], layout, kind):
                chunks[i - 1].append(chunks[i].pop(0))
            i += 1
        else:
            i += 1
    return chunks


def build_cues(segments: list[NarrationSegment], layout: SubtitleLayout, offset: float = 0.0,
               min_cue: float = 0.9) -> list[Cue]:
    cues: list[Cue] = []
    for seg in segments:
        chunks = chunk_sentence(seg.text, layout, seg.kind)
        weights = [len(" ".join(lines)) + 4 for lines in chunks]
        total = sum(weights)
        span = seg.end - seg.start
        t = seg.start
        for lines, w in zip(chunks, weights):
            dur = span * w / total
            cues.append(Cue(round(t + offset, 3), round(t + dur + offset, 3), lines, seg.kind, seg.reference))
            t += dur
    # Extend very short cues into the following silence when there is room.
    for i, cue in enumerate(cues):
        if cue.duration < min_cue:
            # Never run past the next cue, nor past the end of the narration.
            limit = cues[i + 1].start if i + 1 < len(cues) else cue.end
            cue.end = round(min(cue.start + min_cue, limit), 3)
    return cues


# ---- writers -------------------------------------------------------------

def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: list[Cue], path: Path) -> Path:
    blocks = []
    for i, cue in enumerate(cues, 1):
        blocks.append(f"{i}\n{_srt_time(cue.start)} --> {_srt_time(cue.end)}\n" + "\n".join(cue.lines))
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    return path


_SRT_RE = re.compile(r"(\d+):(\d+):(\d+),(\d+)\s*-->\s*(\d+):(\d+):(\d+),(\d+)")


def read_srt(path: Path) -> list[Cue]:
    """Parse an SRT file (e.g. after manual correction)."""
    cues = []
    for block in re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip()):
        rows = block.strip().splitlines()
        m = _SRT_RE.search(rows[1] if len(rows) > 1 else "")
        if not m:
            continue
        g = [int(x) for x in m.groups()]
        start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
        end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
        cues.append(Cue(start, end, rows[2:]))
    return cues


def _ass_time(t: float) -> str:
    cs = int(round(max(t, 0) * 100))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


@dataclass
class TitleCards:
    title: list[str]
    account_name: str
    tagline: str
    handle: str
    title_seconds: float
    outro_start: float
    total: float
    extra_styles: dict = field(default_factory=dict)


def write_ass(cues: list[Cue], cards: TitleCards, fonts: dict[str, ResolvedFont],
              settings: Settings, path: Path) -> Path:
    st = settings.style
    W, H = settings["video"]["width"], settings["video"]["height"]
    c, sz, safe, lay = st["colors"], st["sizes"], st["safe_zone"], st["layout"]
    outline, shadow = st["outline_px"], st["shadow_px"]

    def style(name: str, font: ResolvedFont, size: int, color: str, align: int, margin_v: int,
              italic: bool | None = None) -> str:
        italic = font.italic if italic is None else italic
        return (f"Style: {name},{font.family},{size},{ass_color(color)},{ass_color(color)},"
                f"{ass_color(c['outline'])},{ass_color(c['shadow'], 0.45)},{-1 if font.bold else 0},"
                f"{-1 if italic else 0},0,0,100,100,0,0,1,{outline},{shadow},{align},"
                f"{safe['left']},{safe['right']},{margin_v},1")

    sub_margin = lay["subtitle_bottom_margin"]
    styles = [
        style("Sub", fonts["body"], sz["subtitle"], c["text"], 2, sub_margin),
        style("Verse", fonts["verse"], sz["verse"], c["verse_text"], 2, sub_margin, italic=True),
        style("Ref", fonts["body"], sz["verse_reference"], c["accent"], 2, sub_margin),
        style("Title", fonts["title"], sz["title"], c["text"], 5, 0),
        style("Name", fonts["title"], sz["closing_name"], c["accent"], 5, 0),
        style("Tagline", fonts["body"], sz["closing_tagline"], c["text"], 5, 0),
    ]
    header = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        *styles, "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    cx = safe["left"] + (W - safe["left"] - safe["right"]) // 2
    events = []

    def ev(start: float, end: float, style_name: str, text: str, layer: int = 0) -> None:
        events.append(f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},{style_name},,0,0,0,,{text}")

    title_end = min(cards.title_seconds, cards.outro_start)
    ev(0.2, title_end, "Title", f"{{\\fad(500,600)\\pos({cx},{lay['title_center_y']})}}"
       + "\\N".join(_ass_escape(line) for line in cards.title))

    verse_lines_h = sz["verse"] * 1.25 * settings["subtitles"]["max_lines"]
    ref_y = H - sub_margin - verse_lines_h - 24
    verse_cues = [q for q in cues if q.kind == "verse"]
    for cue in cues:
        style_name = "Verse" if cue.kind == "verse" else "Sub"
        text = "\\N".join(_ass_escape(line) for line in cue.lines)
        ev(cue.start, cue.end, style_name, "{\\fad(120,120)}" + text)
    if verse_cues:
        ref = verse_cues[0].reference or ""
        ev(verse_cues[0].start, verse_cues[-1].end, "Ref",
           f"{{\\fad(250,250)\\pos({cx},{int(ref_y)})}}— {_ass_escape(ref)}")

    y = lay["closing_center_y"]
    ev(cards.outro_start, cards.total, "Name", f"{{\\fad(600,0)\\pos({W // 2},{y})}}{_ass_escape(cards.account_name)}")
    ev(cards.outro_start + 0.3, cards.total, "Tagline",
       f"{{\\fad(600,0)\\pos({W // 2},{y + sz['closing_name'] + 30})}}{_ass_escape(cards.tagline)}")
    if cards.handle:
        ev(cards.outro_start + 0.5, cards.total, "Tagline",
           f"{{\\fad(600,0)\\pos({W // 2},{y + sz['closing_name'] + sz['closing_tagline'] + 60})}}"
           f"{_ass_escape(cards.handle)}")

    path.write_text("\n".join(header + events) + "\n", encoding="utf-8")
    return path


def make_layout(settings: Settings, fonts: dict[str, ResolvedFont], language: str = "en") -> SubtitleLayout:
    st, sub = settings.style, settings["subtitles"]
    usable = settings["video"]["width"] - st["safe_zone"]["left"] - st["safe_zone"]["right"]
    body = TextMeasurer(fonts["body"].path, st["sizes"]["subtitle"], st["outline_px"])
    verse = TextMeasurer(fonts["verse"].path, st["sizes"]["verse"], st["outline_px"])
    return SubtitleLayout(usable * sub["width_safety_factor"], sub["max_lines"], sub["max_words_per_cue"],
                          body.width, verse.width, language)


def wrap_title(text: str, font: ResolvedFont, settings: Settings, max_lines: int = 3) -> list[str]:
    """Wrap a title into balanced lines that fit the safe area, or raise."""
    st = settings.style
    usable = (settings["video"]["width"] - st["safe_zone"]["left"] - st["safe_zone"]["right"]) \
        * settings["subtitles"]["width_safety_factor"]
    measure = TextMeasurer(font.path, st["sizes"]["title"], st["outline_px"]).width
    words = text.split()
    for n_lines in range(1, max_lines + 1):
        lines = _balanced_split(words, n_lines, measure)
        if lines and all(measure(line) <= usable for line in lines):
            return lines
    raise ValueError(f"Title too long for the safe area: {text!r}. Shorten it or reduce sizes.title.")


def _balanced_split(words: list[str], n: int, measure: Callable[[str], float]) -> list[str] | None:
    if n == 1:
        return [" ".join(words)]
    if len(words) < n:
        return None
    best = None
    for cut in range(1, len(words) - n + 2):
        rest = _balanced_split(words[cut:], n - 1, measure)
        if rest is None:
            continue
        lines = [" ".join(words[:cut]), *rest]
        score = max(measure(line) for line in lines)
        if best is None or score < best[0]:
            best = (score, lines)
    return best[1] if best else None
