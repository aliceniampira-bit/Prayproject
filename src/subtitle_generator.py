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
    show_closing: bool = True
    brand: str | None = None
    eyebrow: str | None = None
    show_handle: bool = True

    @property
    def show_title(self) -> bool:
        return self.title_seconds > 0 and bool(self.title)


def _ornament(cx: int, y: int, settings: Settings) -> str | None:
    """A thin accent rule (ASS vector drawing), part of the account's visual signature."""
    orn = settings.style.get("ornament") or {}
    if not orn.get("enabled"):
        return None
    w, h = int(orn.get("width", 180)), int(orn.get("height", 3))
    color = ass_color(settings.style["colors"]["accent"])[4:]  # override tags take &HBBGGRR&
    return (f"{{\\an5\\pos({cx},{y})\\bord0\\shad0\\blur0.6\\1c&H{color}&\\p1}}"
            f"m 0 0 l {w} 0 l {w} {h} l 0 {h}{{\\p0}}")


def _title_block(ev: Callable[..., None], start: float, end: float, lines: list[str], eyebrow: str | None,
                 cx: int, center_y: int, settings: Settings, fade: str) -> None:
    """Eyebrow label, title lines and ornament, vertically centred on ``center_y``."""
    st = settings.style
    size = st["sizes"]["title"]
    half = int(len(lines) * size * 1.02 / 2)
    ev(start, end, "Title", f"{{{fade}\\pos({cx},{center_y})}}" + "\\N".join(_ass_escape(x) for x in lines))
    gap = int((st.get("ornament") or {}).get("gap", 60))
    if eyebrow:
        ev(start, end, "Eyebrow", f"{{{fade}\\pos({cx},{center_y - half - gap})}}{_ass_escape(eyebrow)}")
    rule = _ornament(cx, center_y + half + gap - 20, settings)
    if rule:
        ev(start + 0.25, end, "Rule", "{" + fade + "}" + rule)


def write_ass(cues: list[Cue], cards: TitleCards, fonts: dict[str, ResolvedFont],
              settings: Settings, path: Path, title_center_y: int | None = None,
              title_fade: str = "\\fad(500,600)") -> Path:
    st = settings.style
    W, H = settings["video"]["width"], settings["video"]["height"]
    c, sz, safe, lay = st["colors"], st["sizes"], st["safe_zone"], st["layout"]
    outline, shadow = st["outline_px"], st["shadow_px"]
    spacing = st.get("text_spacing", 0)
    word_mode = settings["subtitles"].get("mode") == "word_groups"
    cue_fade = st.get("cue_fade_in_ms", 120)

    def style(name: str, font: ResolvedFont, size: int, color: str, align: int, margin_v: int,
              italic: bool | None = None, space: float = 0) -> str:
        italic = font.italic if italic is None else italic
        return (f"Style: {name},{font.family},{size},{ass_color(color)},{ass_color(color)},"
                f"{ass_color(c['outline'])},{ass_color(c['shadow'], 0.45)},{-1 if font.bold else 0},"
                f"{-1 if italic else 0},0,0,100,100,{space},0,1,{outline},{shadow},{align},"
                f"{safe['left']},{safe['right']},{margin_v},1")

    sub_margin = lay["subtitle_bottom_margin"]
    brand_font = fonts.get("brand", fonts["body"])
    blur = st.get("text_blur", 0)
    blur_tag = f"\\blur{blur}" if blur else ""
    styles = [
        style("Sub", fonts["body"], sz["subtitle"], c["text"], 2, sub_margin, space=spacing),
        style("Verse", fonts["verse"], sz["verse"], c["verse_text"], 2, sub_margin, italic=True, space=spacing),
        style("Ref", fonts["body"], sz["verse_reference"], c["accent"], 2, sub_margin),
        style("Title", fonts["title"], sz["title"], c["text"], 5, 0),
        style("Name", fonts["title"], sz["closing_name"], c["accent"], 5, 0),
        style("Tagline", fonts["body"], sz["closing_tagline"], c["text"], 5, 0),
        style("Brand", brand_font, sz.get("brand", 34), c["accent"], 5, 0, space=1),
        style("Eyebrow", brand_font, sz.get("eyebrow", 34), c["accent"], 5, 0, space=4),
        style("Rule", brand_font, 10, c["accent"], 5, 0),
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

    halo = st.get("text_halo") or {}

    def ev(start: float, end: float, style_name: str, text: str, layer: int = 1) -> None:
        if style_name == "Rule":
            events.append(f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},{style_name},,0,0,0,,{text}")
            return
        if halo.get("enabled"):
            # Soft dark glow under the text: keeps it legible over bright skies without a box.
            size = halo.get("size", 14)
            alpha = int(round((1 - halo.get("opacity", 0.45)) * 255))
            glow = (f"{{\\1a&HFF&\\3c&H{ass_color(c['shadow'])[4:]}&\\3a&H{alpha:02X}&"
                    f"\\bord{size}\\blur{size}\\shad0}}")
            events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style_name},,0,0,0,,{glow}{text}")
        if blur_tag:
            text = "{" + blur_tag + "}" + text
        events.append(f"Dialogue: {layer},{_ass_time(start)},{_ass_time(end)},{style_name},,0,0,0,,{text}")

    if cards.show_title:
        title_end = min(cards.title_seconds, cards.outro_start)
        _title_block(ev, 0.2 if title_fade else 0.0, title_end, cards.title, cards.eyebrow, cx,
                     title_center_y or lay["title_center_y"], settings, title_fade)

    words_y = lay.get("words_center_y", 960)
    placement = f"\\pos({cx},{words_y})\\an5" if word_mode else ""
    for cue in cues:
        style_name = "Verse" if cue.kind == "verse" else "Sub"
        text = "\\N".join(_ass_escape(line) for line in cue.lines)
        fade = f"\\fad({cue_fade},{80 if word_mode else 120})"
        ev(cue.start, cue.end, style_name, "{" + fade + placement + "}" + text)

    verse_cues = [q for q in cues if q.kind == "verse"]
    if verse_cues:
        if word_mode:
            ref_y = words_y + sz["verse"] + 40
        else:
            ref_y = H - sub_margin - sz["verse"] * 1.25 * settings["subtitles"]["max_lines"] - 44
        ev(verse_cues[0].start, verse_cues[-1].end, "Ref",
           f"{{\\fad(250,250)\\an5\\pos({cx},{int(ref_y)})}}— {_ass_escape(verse_cues[0].reference or '')}")

    if cards.brand:
        ev(0.0, cards.total, "Brand", f"{{\\fad(800,800)\\pos({cx},{lay.get('brand_center_y', 1330)})}}"
           + _ass_escape(cards.brand))

    if cards.show_closing:
        y = lay["closing_center_y"]
        rule = _ornament(cx, y + sz["closing_name"] // 2 + 30, settings)
        tagline_y = y + sz["closing_name"] + (60 if rule else 30)
        ev(cards.outro_start, cards.total, "Name",
           f"{{\\fad(600,0)\\pos({cx},{y})}}{_ass_escape(cards.account_name)}")
        if rule:
            ev(cards.outro_start + 0.2, cards.total, "Rule", "{\\fad(600,0)}" + rule)
        ev(cards.outro_start + 0.3, cards.total, "Tagline",
           f"{{\\fad(600,0)\\pos({cx},{tagline_y})}}{_ass_escape(cards.tagline)}")
        if cards.handle and cards.show_handle:
            ev(cards.outro_start + 0.5, cards.total, "Tagline",
               f"{{\\fad(600,0)\\pos({cx},{tagline_y + sz['closing_tagline'] + 30})}}"
               f"{_ass_escape(cards.handle)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(header + events) + "\n", encoding="utf-8")
    return path


def write_cover_ass(title_lines: list[str], eyebrow: str | None, brand: str | None,
                    fonts: dict[str, ResolvedFont], settings: Settings, path: Path) -> Path:
    """Static title card for the cover image (same look as the opening title of the video)."""
    cover = settings.style.get("cover", {})
    cards = TitleCards(title_lines, "", "", "", 10.0, 10.0, 10.0, show_closing=False, brand=brand,
                       eyebrow=eyebrow)
    return write_ass([], cards, fonts, settings, path,
                     title_center_y=cover.get("title_center_y", settings.style["layout"]["title_center_y"]),
                     title_fade="")


# ---- word-group captions (short centred phrases synced to the voice) ---------

def group_words(sentence: str, layout: SubtitleLayout, kind: str = "prayer") -> list[list[str]]:
    """Split a sentence into 1-3 word groups with the lowest total cost.

    Costs favour two-word groups, keep punctuation at group ends, and avoid
    ending a group on an article, preposition or unstressed pronoun.
    """
    words = sentence.split()
    n = len(words)
    inf = float("inf")
    best = [0.0] + [inf] * n
    back = [0] * (n + 1)
    for end in range(1, n + 1):
        for size in range(1, min(layout.max_words, end) + 1):
            start = end - size
            group = words[start:end]
            text = " ".join(group)
            if not layout.fits(text, kind):
                continue
            cost = {1: 1.0, 2: 0.0, 3: 0.5}.get(size, 2.0)
            if size == 1 and len(group[0]) >= 8:
                cost = 0.3
            if size == 3 and len(text) > 18:
                cost += 1.0
            if any(w[-1:] in ",;:.!?…" for w in group[:-1]):
                cost += 6.0  # punctuation inside a group reads badly
            if end < n and is_weak_ending(group[-1], layout.language):
                cost += 3.0
            if best[start] + cost < best[end]:
                best[end], back[end] = best[start] + cost, start
    if best[n] == inf:
        raise ValueError(f"Cannot fit caption words on screen: {sentence!r}")
    groups, end = [], n
    while end > 0:
        groups.insert(0, words[back[end]:end])
        end = back[end]
    return groups


def build_word_cues(segments: list[NarrationSegment], layout: SubtitleLayout, offset: float = 0.0,
                    uppercase: bool = False) -> list[Cue]:
    cues: list[Cue] = []
    for seg in segments:
        groups = group_words(seg.text, layout, seg.kind)
        # Weight by characters, plus a little for the micro-pause after punctuation.
        weights = [len(" ".join(g)) + 3 + (4 if g[-1][-1:] in ",;:" else 0) for g in groups]
        total = sum(weights)
        t = seg.start
        for g, w in zip(groups, weights):
            dur = (seg.end - seg.start) * w / total
            text = " ".join(g)
            cues.append(Cue(round(t + offset, 3), round(t + dur + offset, 3),
                            [text.upper() if uppercase else text], seg.kind, seg.reference))
            t += dur
    return cues


def make_layout(settings: Settings, fonts: dict[str, ResolvedFont], language: str = "en") -> SubtitleLayout:
    st, sub = settings.style, settings["subtitles"]
    usable = settings["video"]["width"] - st["safe_zone"]["left"] - st["safe_zone"]["right"]
    spacing = st.get("text_spacing", 0)
    upper = sub.get("uppercase", False)
    body = TextMeasurer(fonts["body"].path, st["sizes"]["subtitle"], st["outline_px"])
    verse = TextMeasurer(fonts["verse"].path, st["sizes"]["verse"], st["outline_px"])

    def measure_with(m: TextMeasurer) -> Callable[[str], float]:
        return lambda text: m.width(text.upper() if upper else text) + spacing * len(text)

    return SubtitleLayout(usable * sub["width_safety_factor"], sub["max_lines"], sub["max_words_per_cue"],
                          measure_with(body), measure_with(verse), language)


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
