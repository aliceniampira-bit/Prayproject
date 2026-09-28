"""Narration: pluggable TTS providers plus sentence-level assembly.

Each sentence is synthesized separately, trimmed, and joined with controlled
pauses. Because we know where every sentence starts and ends, subtitles are
synchronized without speech recognition. Sentence audio is cached by content
hash, so re-running a production never pays twice for the same text.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import subprocess
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .ffmpeg_utils import duration_of, run_ffmpeg
from .script_generator import PrayerScript, split_sentences

log = logging.getLogger(__name__)


class VoiceError(RuntimeError):
    pass


class VoiceProvider:
    """Interface for text-to-speech providers."""

    name = "base"
    #: True only when the provider's terms allow commercial use of the audio.
    commercial_use_cleared = False
    license_note = ""

    def voice_id(self, language: str, gender: str) -> str:
        raise NotImplementedError

    def synthesize(self, text: str, language: str, gender: str, out_path: Path) -> Path:
        """Write audio for ``text`` to ``out_path`` (any format ffmpeg reads)."""
        raise NotImplementedError

    def cache_key_extra(self) -> str:
        return ""


class EspeakProvider(VoiceProvider):
    """Local, offline, robotic voice. ONLY for prototyping the pipeline.

    It is not natural enough for publication, so productions that use it are
    never approved by quality control.
    """

    name = "espeak_local"
    commercial_use_cleared = False
    license_note = "Placeholder voice for testing only. Not for publication."

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.binary = shutil.which("espeak-ng") or shutil.which("espeak")

    def voice_id(self, language: str, gender: str) -> str:
        try:
            return self.config[language][gender]
        except KeyError as exc:
            raise VoiceError(f"No espeak voice configured for {language}/{gender}.") from exc

    def cache_key_extra(self) -> str:
        return f"{self.config.get('speed_wpm')}:{self.config.get('pitch')}"

    def synthesize(self, text: str, language: str, gender: str, out_path: Path) -> Path:
        if not self.binary:
            raise VoiceError("espeak-ng is not installed. It is only needed for the offline prototype "
                             "(see README), or configure another voice provider.")
        text_file = out_path.with_suffix(".txt")
        text_file.write_text(text, encoding="utf-8")
        cmd = [self.binary, "-v", self.voice_id(language, gender), "-s", str(self.config.get("speed_wpm", 125)),
               "-p", str(self.config.get("pitch", 45)), "-g", "2", "-w", str(out_path), "-f", str(text_file)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        text_file.unlink(missing_ok=True)
        if proc.returncode != 0 or not out_path.exists():
            raise VoiceError(f"espeak failed: {proc.stderr.strip()}")
        return out_path


PROVIDERS = {"espeak_local": EspeakProvider}


def get_provider(settings: Settings) -> VoiceProvider:
    name = settings["voice"]["provider"]
    if name not in PROVIDERS:
        raise VoiceError(
            f"Voice provider '{name}' is not implemented yet. Available: {', '.join(PROVIDERS)}. "
            "Commercial providers are added once one is chosen (see README, 'Decisiones')."
        )
    return PROVIDERS[name](settings["voice"]["voices"].get(name, {}))


@dataclass
class NarrationSegment:
    kind: str
    text: str
    start: float
    end: float
    reference: str | None = None


@dataclass
class NarrationResult:
    audio_path: Path
    duration: float
    segments: list[NarrationSegment]
    provider: str
    voice_id: str
    commercial_use_cleared: bool
    license_note: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["audio_path"] = str(self.audio_path)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NarrationResult":
        d = dict(d)
        d["audio_path"] = Path(d["audio_path"])
        d["segments"] = [NarrationSegment(**s) for s in d["segments"]]
        return cls(**d)


def _normalize_segment(src: Path, dst: Path, sample_rate: int) -> None:
    """Convert to mono 16-bit WAV and trim leading/trailing silence."""
    trim = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,"
            "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse")
    run_ffmpeg(["-i", str(src), "-af", trim, "-ac", "1", "-ar", str(sample_rate),
                "-c:a", "pcm_s16le", str(dst)])


def generate_narration(script: PrayerScript, settings: Settings, out_dir: Path,
                       gender: str | None = None, provider: VoiceProvider | None = None) -> NarrationResult:
    vcfg = settings["voice"]
    provider = provider or get_provider(settings)
    gender = gender or vcfg["selected_gender"][script.language]
    if gender not in ("female", "male"):
        raise VoiceError(f"Voice gender must be 'female' or 'male', got '{gender}'.")
    voice_id = provider.voice_id(script.language, gender)
    sr = int(vcfg["sample_rate"])
    cache_dir = settings.root / "data" / "cache" / "tts"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    pause_sentence = int(vcfg["pause_between_sentences_seconds"] * sr)
    pause_section = int(vcfg["pause_between_sections_seconds"] * sr)
    frames = bytearray()
    segments: list[NarrationSegment] = []

    for s_idx, section in enumerate(script.sections()):
        if s_idx > 0:
            frames += b"\x00\x00" * pause_section
        for i, sentence in enumerate(split_sentences(section.text)):
            if i > 0:
                frames += b"\x00\x00" * pause_sentence
            key = hashlib.sha256(
                f"{provider.name}|{voice_id}|{provider.cache_key_extra()}|{sr}|{sentence}".encode()
            ).hexdigest()[:24]
            cached = cache_dir / f"{key}.wav"
            if not cached.exists():
                raw = out_dir / f"raw_{key}.wav"
                provider.synthesize(sentence, script.language, gender, raw)
                _normalize_segment(raw, cached, sr)
                raw.unlink(missing_ok=True)
            with wave.open(str(cached), "rb") as wf:
                if wf.getframerate() != sr or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                    raise VoiceError(f"Unexpected audio format in {cached}")
                data = wf.readframes(wf.getnframes())
            seg_seconds = len(data) / 2 / sr
            if seg_seconds < vcfg["min_segment_seconds"]:
                raise VoiceError(f"Generated audio too short ({seg_seconds:.2f}s) for: {sentence!r}")
            start = len(frames) / 2 / sr
            frames += data
            segments.append(NarrationSegment(section.kind, sentence, round(start, 3),
                                             round(start + seg_seconds, 3), section.reference))

    audio_path = out_dir / "narration.wav"
    with wave.open(str(audio_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(bytes(frames))

    duration = duration_of(audio_path)
    if duration <= 1.0:
        raise VoiceError(f"Narration is unexpectedly short ({duration:.2f}s).")
    result = NarrationResult(audio_path, duration, segments, provider.name, voice_id,
                             provider.commercial_use_cleared, provider.license_note)
    (out_dir / "narration.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                                            encoding="utf-8")
    log.info("Narration %.1fs, %d sentences (%s/%s)", duration, len(segments), provider.name, voice_id)
    return result
