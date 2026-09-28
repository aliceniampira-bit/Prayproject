"""Prayer scripts: data model, validation, similarity detection and providers.

Scripts are written natively for each language (never literal translations) and
stored as JSON. Generation is pluggable through ``ScriptProvider``: the first
version uses curated scripts written and reviewed ahead of time
(``CuratedScriptProvider``). An LLM-backed provider can be added later without
changing the rest of the pipeline.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date as date_cls
from pathlib import Path
from typing import Any, Iterable

SUPPORTED_LANGUAGES = ("en", "es")
REQUIRED_FIELDS = ("date", "language", "theme", "title", "hook", "prayer", "closing",
                   "description", "hashtags")
PRAYER_TYPES = ("short", "full")
PLATFORM_OVERRIDE_FIELDS = ("title", "description", "hashtags")
VERSE_STATUSES = ("pending", "verified", "rejected")

# Very small stopword lists: enough to tell English from Spanish in a QC check.
_STOPWORDS = {
    "en": {"the", "and", "you", "your", "of", "to", "in", "is", "my", "me", "for", "with", "that",
           "this", "we", "our", "lord", "god", "be", "are", "it", "on", "have", "all", "who"},
    "es": {"el", "la", "los", "las", "y", "de", "que", "en", "tu", "mi", "me", "por", "con", "para",
           "un", "una", "es", "nos", "nuestro", "señor", "dios", "se", "del", "al", "lo", "te"},
}


class ScriptValidationError(ValueError):
    pass


@dataclass
class BibleVerse:
    reference: str
    translation: str
    text: str
    spoken_intro: str = ""
    verification_status: str = "pending"
    verified_by: str | None = None
    verification_source: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BibleVerse":
        ver = d.get("verification", {}) or {}
        return cls(
            reference=d["reference"], translation=d["translation"], text=d["text"],
            spoken_intro=d.get("spoken_intro", ""),
            verification_status=ver.get("status", "pending"),
            verified_by=ver.get("verified_by"), verification_source=ver.get("source"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference": self.reference, "translation": self.translation, "text": self.text,
            "spoken_intro": self.spoken_intro,
            "verification": {"status": self.verification_status, "verified_by": self.verified_by,
                             "source": self.verification_source},
        }


@dataclass
class NarrationSection:
    """One block of narration. ``kind`` controls pauses and on-screen styling."""
    kind: str  # hook | verse_intro | verse | prayer | closing
    text: str
    reference: str | None = None


@dataclass
class PrayerScript:
    date: str
    language: str
    theme: str
    title: str
    hook: str
    prayer: list[str]
    closing: str
    description: str
    hashtags: list[str]
    bible_verse: BibleVerse | None = None
    review_status: str = "pending"
    generator: str = "curated"
    type: str = "full"
    platform_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    # ---- serialization -------------------------------------------------
    @classmethod
    def from_dict(cls, d: dict[str, Any], default_type: str = "full") -> "PrayerScript":
        d = dict(d)
        if "description" not in d and "tiktok_description" in d:  # older scripts
            d["description"] = d.pop("tiktok_description")
        missing = [k for k in REQUIRED_FIELDS if k not in d]
        if missing:
            raise ScriptValidationError(f"Script is missing fields: {', '.join(missing)}")
        known = set(REQUIRED_FIELDS) | {"bible_verse", "review", "generator", "type", "platform_overrides",
                                         "estimated_duration_seconds", "subtitle_text", "id"}
        return cls(
            date=d["date"], language=d["language"], theme=d["theme"], title=d["title"],
            hook=d["hook"], prayer=list(d["prayer"]), closing=d["closing"],
            description=d["description"], hashtags=list(d["hashtags"]),
            bible_verse=BibleVerse.from_dict(d["bible_verse"]) if d.get("bible_verse") else None,
            review_status=(d.get("review") or {}).get("status", "pending"),
            generator=d.get("generator", "curated"),
            type=d.get("type") or default_type,
            platform_overrides=dict(d.get("platform_overrides") or {}),
            extra={k: v for k, v in d.items() if k not in known},
        )

    @classmethod
    def load(cls, path: Path) -> "PrayerScript":
        with Path(path).open(encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def to_dict(self, words_per_minute: int | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "date": self.date, "language": self.language, "type": self.type, "theme": self.theme,
            "title": self.title, "hook": self.hook,
            "bible_verse": self.bible_verse.to_dict() if self.bible_verse else None,
            "prayer": self.prayer, "closing": self.closing,
            "description": self.description, "hashtags": self.hashtags,
            "platform_overrides": self.platform_overrides,
            "subtitle_text": self.subtitle_text,
            "review": {"status": self.review_status},
            "generator": self.generator,
        }
        if words_per_minute:
            d["estimated_duration_seconds"] = round(self.estimated_narration_seconds(words_per_minute), 1)
        d.update(self.extra)
        return d

    def save(self, path: Path, words_per_minute: int | None = None) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(self.to_dict(words_per_minute), fh, ensure_ascii=False, indent=2)
            fh.write("\n")

    # ---- derived data --------------------------------------------------
    @property
    def id(self) -> str:
        return f"{self.date}_{self.language}_{self.type}_{self.theme}"

    @property
    def topic_key(self) -> str:
        """Same value for the English and Spanish versions of one topic."""
        return f"{self.date}_{self.type}_{self.theme}"

    def sections(self) -> list[NarrationSection]:
        """Narration order: hook, (verse intro + verse), prayer paragraphs, closing."""
        out = [NarrationSection("hook", self.hook)]
        if self.bible_verse:
            if self.bible_verse.spoken_intro:
                out.append(NarrationSection("verse_intro", self.bible_verse.spoken_intro))
            out.append(NarrationSection("verse", self.bible_verse.text,
                                        reference=f"{self.bible_verse.reference} ({self.bible_verse.translation})"))
        out.extend(NarrationSection("prayer", p) for p in self.prayer)
        out.append(NarrationSection("closing", self.closing))
        return out

    @property
    def narration_text(self) -> str:
        return "\n\n".join(s.text for s in self.sections())

    @property
    def subtitle_text(self) -> str:
        return self.narration_text

    def word_count(self) -> int:
        return len(re.findall(r"\w+", self.narration_text))

    def estimated_narration_seconds(self, words_per_minute: int, pause_sentence: float = 0.55,
                                    pause_section: float = 1.1) -> float:
        sentences = sum(len(split_sentences(s.text)) for s in self.sections())
        sections = len(self.sections())
        return self.word_count() / words_per_minute * 60 + sentences * pause_sentence + sections * pause_section


# ---- text helpers -------------------------------------------------------

_SENTENCE_RE = re.compile(r"(?<=[.!?…»”\"])\s+(?=[A-ZÁÉÍÓÚÑ¿¡“«\"])")


def split_sentences(text: str) -> list[str]:
    parts = _SENTENCE_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]", " ", text)


def shingles(text: str, n: int = 3) -> set[tuple[str, ...]]:
    words = normalize(text).split()
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def detect_language(text: str) -> str | None:
    """Return 'en' or 'es' based on stopword hits, or None if unclear."""
    words = normalize(text).split()
    scores = {lang: sum(w in sw for w in words) for lang, sw in _STOPWORDS.items()}
    best = max(scores, key=scores.get)
    other = min(scores, key=scores.get)
    if scores[best] < 3 or scores[best] < 1.5 * max(scores[other], 1):
        return None
    return best


# ---- validation ---------------------------------------------------------

@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_script(script: PrayerScript, themes: dict[str, Any], words_per_minute: int = 130,
                    min_seconds: float | None = None, max_seconds: float | None = None, *,
                    type_cfg: dict[str, Any] | None = None, fixed_seconds: float = 0.0,
                    pauses: tuple[float, float] = (0.55, 1.1),
                    platforms: Iterable[str] | None = None) -> ValidationResult:
    """Check a script. Durations compare the whole video: narration estimate + ``fixed_seconds``
    (lead-in and closing card). ``type_cfg`` is the prayer type from settings.prayer_types."""
    res = ValidationResult()
    try:
        date_cls.fromisoformat(script.date)
    except ValueError:
        res.errors.append(f"Invalid date '{script.date}' (expected YYYY-MM-DD).")
    if script.language not in SUPPORTED_LANGUAGES:
        res.errors.append(f"Unsupported language '{script.language}'.")
    if script.type not in PRAYER_TYPES:
        res.errors.append(f"Unknown prayer type '{script.type}'. Valid: {', '.join(PRAYER_TYPES)}.")
    if script.theme not in themes:
        res.errors.append(f"Unknown theme '{script.theme}'. Valid: {', '.join(themes)}.")
    for name in ("title", "hook", "closing", "description"):
        if not getattr(script, name).strip():
            res.errors.append(f"Field '{name}' is empty.")
    if not script.prayer or not all(p.strip() for p in script.prayer):
        res.errors.append("The prayer must contain at least one non-empty paragraph.")
    if not script.hashtags:
        res.errors.append("At least one hashtag is required.")
    bad_tags = [h for h in script.hashtags if not re.fullmatch(r"#\w+", h)]
    if bad_tags:
        res.errors.append(f"Invalid hashtags: {bad_tags}")

    detected = detect_language(script.narration_text)
    if detected and detected != script.language:
        res.errors.append(f"Narration looks like '{detected}' but script language is '{script.language}'.")
    detected_desc = detect_language(script.description)
    if detected_desc and detected_desc != script.language:
        res.errors.append(f"The description looks like '{detected_desc}', expected '{script.language}'.")

    # No padding: duration must come from real content, not repetition or artificial pauses.
    res.errors.extend(padding_problems(script))

    known_platforms = set(platforms) if platforms is not None else None
    for platform, override in script.platform_overrides.items():
        if known_platforms is not None and platform not in known_platforms:
            res.errors.append(f"platform_overrides: unknown platform '{platform}'.")
        unknown = set(override) - set(PLATFORM_OVERRIDE_FIELDS)
        if unknown:
            res.errors.append(f"platform_overrides.{platform}: unknown fields {sorted(unknown)} "
                              f"(allowed: {', '.join(PLATFORM_OVERRIDE_FIELDS)}).")
        tags = override.get("hashtags", [])
        if any(not re.fullmatch(r"#\w+", h) for h in tags):
            res.errors.append(f"platform_overrides.{platform}: invalid hashtags {tags}.")
        for key in ("title", "description"):
            lang = detect_language(override.get(key, ""))
            if lang and lang != script.language:
                res.errors.append(f"platform_overrides.{platform}.{key} looks like '{lang}', "
                                  f"expected '{script.language}'.")

    verse = script.bible_verse
    if verse:
        if not re.search(r"\d+:\d+", verse.reference):
            res.errors.append(f"Bible reference '{verse.reference}' has no chapter:verse.")
        if verse.verification_status not in VERSE_STATUSES:
            res.errors.append(f"Unknown verse verification status '{verse.verification_status}'.")
        elif verse.verification_status == "rejected":
            res.errors.append("Bible verse was rejected in review; fix or remove it.")
        elif verse.verification_status == "pending":
            res.warnings.append(f"Bible verse {verse.reference} ({verse.translation}) is pending human "
                                "verification against a trusted edition.")

    if type_cfg:
        min_seconds = type_cfg.get("min_seconds", min_seconds)
        max_seconds = type_cfg.get("max_seconds", max_seconds)
        max_par = type_cfg.get("max_prayer_paragraphs")
        if max_par and len(script.prayer) > max_par:
            res.warnings.append(f"A '{script.type}' prayer should have at most {max_par} paragraphs "
                                f"(has {len(script.prayer)}).")
        if verse and not type_cfg.get("allow_bible_verse", True):
            res.errors.append(f"'{script.type}' prayers do not include a Bible verse (settings.prayer_types).")
        recommended = type_cfg.get("recommended_themes")
        if recommended and script.theme not in recommended:
            res.warnings.append(f"Theme '{script.theme}' is not among the recommended themes for "
                                f"'{script.type}' prayers: {', '.join(recommended)}.")

    est = script.estimated_narration_seconds(words_per_minute, *pauses) + fixed_seconds
    if min_seconds and est < min_seconds:
        res.warnings.append(f"Estimated video length {est:.0f}s is below the {min_seconds:.0f}s minimum for "
                            f"'{script.type}'. Do not pad: write more content or change the type.")
    if max_seconds and est > max_seconds:
        res.warnings.append(f"Estimated video length {est:.0f}s exceeds the {max_seconds:.0f}s maximum for "
                            f"'{script.type}'. Shorten the script or change the type.")
    if script.review_status != "approved":
        res.warnings.append("Script has not been approved by a human reviewer yet.")
    return res


_PAUSE_MARKERS = re.compile(r"\.{4,}|…{2,}|\[\s*pause\s*\]|\[\s*pausa\s*\]|<\s*break", re.IGNORECASE)


def padding_problems(script: PrayerScript) -> list[str]:
    """Repeated sentences or artificial pause markers used to stretch a video."""
    problems = []
    seen: dict[str, str] = {}
    for section in script.sections():
        if _PAUSE_MARKERS.search(section.text):
            problems.append(f"Artificial pause marker in {section.kind}: {section.text[:60]!r}. "
                            "Pauses come from the narration pacing, not from the text.")
        for sentence in split_sentences(section.text):
            key = normalize(sentence).strip()
            if len(key.split()) < 3:
                continue  # "Amen." or "Thank you." may legitimately repeat
            if key in seen:
                problems.append(f"Repeated sentence ({seen[key]} and {section.kind}): {sentence!r}. "
                                "Do not repeat text to reach a duration.")
            seen.setdefault(key, section.kind)
    return problems


def validate_with_settings(script: PrayerScript, settings: Any) -> ValidationResult:
    """validate_script with the type, pacing and platforms from the loaded settings."""
    v, voice = settings["video"], settings["voice"]
    type_cfg = settings.prayer_type(script.type) if script.type in PRAYER_TYPES else None
    fixed = v["lead_in_seconds"] + v["outro_seconds"]
    return validate_script(script, settings.themes, settings.language(script.language)["words_per_minute"],
                           type_cfg=type_cfg, fixed_seconds=fixed,
                           pauses=(voice["pause_between_sentences_seconds"],
                                   voice["pause_between_sections_seconds"]),
                           platforms=settings.platforms.get("platforms", {}).keys())


def estimated_video_seconds(script: PrayerScript, settings: Any) -> float:
    v, voice = settings["video"], settings["voice"]
    return (script.estimated_narration_seconds(settings.language(script.language)["words_per_minute"],
                                               voice["pause_between_sentences_seconds"],
                                               voice["pause_between_sections_seconds"])
            + v["lead_in_seconds"] + v["outro_seconds"])


def iter_history(dirs: Iterable[Path], language: str) -> Iterable[tuple[Path, PrayerScript]]:
    for d in dirs:
        if not d.exists():
            continue
        for path in sorted(d.rglob("*.json")):
            try:
                s = PrayerScript.load(path)
            except (ScriptValidationError, json.JSONDecodeError, KeyError, TypeError):
                continue
            if s.language == language:
                yield path, s


def find_similar(script: PrayerScript, history: Iterable[tuple[Path, PrayerScript]],
                 threshold: float) -> list[dict[str, Any]]:
    """Return earlier scripts whose prayer, hook or title is too similar."""
    mine_body = shingles(" ".join(script.prayer))
    mine_hook = shingles(script.hook, n=2)
    hits = []
    for path, other in history:
        if other.id == script.id:
            continue
        body = jaccard(mine_body, shingles(" ".join(other.prayer)))
        hook = jaccard(mine_hook, shingles(other.hook, n=2))
        same_title = normalize(other.title).strip() == normalize(script.title).strip()
        if body >= threshold or hook >= max(threshold * 1.5, 0.5) or same_title:
            hits.append({"path": str(path), "id": other.id, "prayer_similarity": round(body, 3),
                         "hook_similarity": round(hook, 3), "same_title": same_title})
    return hits


# ---- providers ----------------------------------------------------------

class ScriptProvider:
    """Interface for anything that produces a PrayerScript for a date/language/theme."""

    def get_script(self, date: str, language: str, theme: str | None = None) -> PrayerScript:
        raise NotImplementedError


def pair_by_topic(scripts: Iterable[tuple[Path, PrayerScript]]) -> dict[str, dict[str, Path]]:
    """Group scripts so one topic (date + type + theme) maps to its language versions."""
    topics: dict[str, dict[str, Path]] = {}
    for path, script in scripts:
        topics.setdefault(script.topic_key, {})[script.language] = path
    return topics


def literal_translation_suspects(a: PrayerScript, b: PrayerScript) -> list[str]:
    """Cheap signals that one language version was translated line by line from the other."""
    notes = []
    if len(a.prayer) == len(b.prayer) and len(a.prayer) > 2:
        ratios = [len(x.split()) / max(len(y.split()), 1) for x, y in zip(a.prayer, b.prayer)]
        if all(0.85 <= r <= 1.2 for r in ratios):
            notes.append("Same number of paragraphs with nearly identical lengths; make sure each version "
                         "was written for its own audience, not translated line by line.")
    return notes


class CuratedScriptProvider(ScriptProvider):
    """Uses scripts written and reviewed in advance, stored in a queue folder.

    Files are named ``<date>_<lang>_<theme>.json`` (the prayer type is read from the file). This keeps a human in the loop
    and needs no paid API. An LLM provider can be added later.
    """

    def __init__(self, queue_dir: Path):
        self.queue_dir = queue_dir

    def get_script(self, date: str, language: str, theme: str | None = None) -> PrayerScript:
        pattern = f"{date}_{language}_{theme or '*'}.json"
        matches = sorted(self.queue_dir.glob(pattern))
        if not matches:
            raise FileNotFoundError(f"No curated script for {date}/{language} in {self.queue_dir} ({pattern}).")
        return PrayerScript.load(matches[0])
