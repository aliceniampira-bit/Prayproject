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
                   "tiktok_description", "hashtags")
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
    tiktok_description: str
    hashtags: list[str]
    bible_verse: BibleVerse | None = None
    review_status: str = "pending"
    generator: str = "curated"
    extra: dict[str, Any] = field(default_factory=dict)

    # ---- serialization -------------------------------------------------
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PrayerScript":
        missing = [k for k in REQUIRED_FIELDS if k not in d]
        if missing:
            raise ScriptValidationError(f"Script is missing fields: {', '.join(missing)}")
        known = set(REQUIRED_FIELDS) | {"bible_verse", "review", "generator",
                                         "estimated_duration_seconds", "subtitle_text", "id"}
        return cls(
            date=d["date"], language=d["language"], theme=d["theme"], title=d["title"],
            hook=d["hook"], prayer=list(d["prayer"]), closing=d["closing"],
            tiktok_description=d["tiktok_description"], hashtags=list(d["hashtags"]),
            bible_verse=BibleVerse.from_dict(d["bible_verse"]) if d.get("bible_verse") else None,
            review_status=(d.get("review") or {}).get("status", "pending"),
            generator=d.get("generator", "curated"),
            extra={k: v for k, v in d.items() if k not in known},
        )

    @classmethod
    def load(cls, path: Path) -> "PrayerScript":
        with Path(path).open(encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def to_dict(self, words_per_minute: int | None = None) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "date": self.date, "language": self.language, "theme": self.theme,
            "title": self.title, "hook": self.hook,
            "bible_verse": self.bible_verse.to_dict() if self.bible_verse else None,
            "prayer": self.prayer, "closing": self.closing,
            "tiktok_description": self.tiktok_description, "hashtags": self.hashtags,
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
        return f"{self.date}_{self.language}_{self.theme}"

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
                    min_seconds: float | None = None, max_seconds: float | None = None) -> ValidationResult:
    res = ValidationResult()
    try:
        date_cls.fromisoformat(script.date)
    except ValueError:
        res.errors.append(f"Invalid date '{script.date}' (expected YYYY-MM-DD).")
    if script.language not in SUPPORTED_LANGUAGES:
        res.errors.append(f"Unsupported language '{script.language}'.")
    if script.theme not in themes:
        res.errors.append(f"Unknown theme '{script.theme}'. Valid: {', '.join(themes)}.")
    for name in ("title", "hook", "closing", "tiktok_description"):
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
    detected_desc = detect_language(script.tiktok_description)
    if detected_desc and detected_desc != script.language:
        res.errors.append(f"TikTok description looks like '{detected_desc}', expected '{script.language}'.")

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

    est = script.estimated_narration_seconds(words_per_minute)
    if min_seconds and est < min_seconds * 0.85:
        res.warnings.append(f"Estimated narration {est:.0f}s is short for the {min_seconds:.0f}s minimum. "
                            "Do not pad: write more content or accept a shorter video.")
    if max_seconds and est > max_seconds:
        res.warnings.append(f"Estimated narration {est:.0f}s exceeds the {max_seconds:.0f}s maximum.")
    if script.review_status != "approved":
        res.warnings.append("Script has not been approved by a human reviewer yet.")
    return res


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


class CuratedScriptProvider(ScriptProvider):
    """Uses scripts written and reviewed in advance, stored in a queue folder.

    Files are named ``<date>_<lang>_<theme>.json``. This keeps a human in the loop
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
