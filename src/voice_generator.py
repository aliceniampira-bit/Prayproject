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
import os
import shutil
import subprocess
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests

from .config import Settings
from .ffmpeg_utils import duration_of, run_ffmpeg
from .script_generator import PrayerScript, split_sentences

log = logging.getLogger(__name__)


class VoiceError(RuntimeError):
    pass


class VoiceAuthError(VoiceError):
    """The provider rejected the credential (or none reached it)."""


class VoiceRateLimitError(VoiceError):
    """The provider's rate limit, quota or balance was exhausted."""


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


class MiniMaxProvider(VoiceProvider):
    """MiniMax text-to-speech (https://platform.minimax.io), endpoint ``/v1/t2a_v2``.

    Credentials: in Claude Code cloud sessions the egress proxy adds the
    ``Authorization: Bearer ...`` header for ``api.minimax.io``, so no key is
    needed in the environment or in any file. Only when running elsewhere is
    ``MINIMAX_API_KEY`` read from the environment (.env). The key and the header
    are never logged or included in error messages.
    """

    name = "minimax"
    license_note = ("MiniMax AI voice. Confirm that your MiniMax plan allows commercial use and set "
                    "voice.voices.minimax.commercial_use_confirmed=true.")

    # base_resp.status_code values documented by MiniMax.
    AUTH_CODES = {1004, 2049}
    RATE_CODES = {1002, 1039, 1041}       # per-minute limits: worth waiting and retrying
    QUOTA_CODES = {1008, 2056}            # balance or plan quota: retrying does not help
    TRANSIENT_CODES = {1000, 1001, 1013}  # unknown / timeout / internal error
    CONTENT_CODES = {1026, 1027, 1042}    # sensitive or invalid input text

    def __init__(self, config: dict[str, Any], session: requests.Session | None = None,
                 api_key: str | None = None):
        self.config = config
        self.session = session or requests.Session()
        self.base_url = config.get("base_url", "https://api.minimax.io").rstrip("/")
        self.model = config.get("model", "speech-02-hd")
        self.audio_format = config.get("format", "mp3")
        self.timeout = int(config.get("timeout", 60))
        self.max_retries = max(1, int(config.get("max_retries", 3)))
        self.commercial_use_cleared = bool(config.get("commercial_use_confirmed", False))
        # Optional: outside Claude Code the key may come from the environment.
        self._api_key = api_key if api_key is not None else os.environ.get("MINIMAX_API_KEY", "").strip()

    def voice_id(self, language: str, gender: str) -> str:
        per_language = self.config.get(language)
        voice = per_language.get(gender) if isinstance(per_language, dict) else None
        voice = voice or self.config.get("voice_id")
        if not voice:
            raise VoiceError(f"No MiniMax voice_id configured for {language}/{gender} "
                             "(voice.voices.minimax.voice_id in config/settings.json).")
        return voice

    def cache_key_extra(self) -> str:
        c = self.config
        return f"{self.model}:{c.get('speed', 1.0)}:{c.get('vol', 1.0)}:{c.get('pitch', 0)}:{c.get('emotion', '')}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    def _auth_error(self, detail: str) -> VoiceAuthError:
        source = ("MINIMAX_API_KEY from the environment" if self._api_key
                  else "the credential for api.minimax.io stored in the Claude environment (API credentials)")
        return VoiceAuthError(
            f"MiniMax rejected the authentication ({detail}). Check {source}: header 'Authorization', "
            "prefix 'Bearer', valid key. A credential saved after the session started only applies to a new session.")

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_error = "no response"
        for attempt in range(self.max_retries):
            if attempt:
                time.sleep(2 ** attempt)
            try:
                resp = self.session.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = f"network error: {type(exc).__name__}"
                continue
            if resp.status_code in (401, 403):
                raise self._auth_error(f"HTTP {resp.status_code}")
            if resp.status_code == 429:
                last_error = "HTTP 429"
                if attempt + 1 == self.max_retries:
                    raise VoiceRateLimitError("MiniMax rate limit reached (HTTP 429). Wait and try again.")
                continue
            if resp.status_code >= 500:
                last_error = f"HTTP {resp.status_code}"
                continue
            if resp.status_code != 200:
                raise VoiceError(f"MiniMax request failed: HTTP {resp.status_code}")
            try:
                data = resp.json()
            except ValueError:
                raise VoiceError("MiniMax returned a response that is not JSON.") from None
            base = data.get("base_resp") or {}
            code = int(base.get("status_code", 0) or 0)
            msg = str(base.get("status_msg", ""))[:200]
            if code == 0:
                return data
            if code in self.AUTH_CODES:
                raise self._auth_error(f"code {code}: {msg}")
            if code in self.QUOTA_CODES:
                raise VoiceRateLimitError(f"MiniMax usage limit or balance exhausted (code {code}: {msg}). "
                                          "Check your plan and balance on platform.minimax.io.")
            if code in self.RATE_CODES:
                last_error = f"code {code}: {msg}"
                if attempt + 1 == self.max_retries:
                    raise VoiceRateLimitError(f"MiniMax rate limit reached ({last_error}). Wait and try again.")
                continue
            if code in self.TRANSIENT_CODES:
                last_error = f"code {code}: {msg}"
                continue
            if code in self.CONTENT_CODES:
                raise VoiceError(f"MiniMax refused the text (code {code}: {msg}). Review the sentence.")
            raise VoiceError(f"MiniMax generation failed (code {code}: {msg}).")
        raise VoiceError(f"MiniMax request failed after {self.max_retries} attempts ({last_error}).")

    def check_auth(self) -> None:
        """Cheap authenticated call (lists voices); raises VoiceAuthError if rejected."""
        self._post("/v1/get_voice", {"voice_type": "system"})

    def synthesize(self, text: str, language: str, gender: str, out_path: Path) -> Path:
        c = self.config
        voice_setting: dict[str, Any] = {"voice_id": self.voice_id(language, gender),
                                         "speed": c.get("speed", 1.0), "vol": c.get("vol", 1.0),
                                         "pitch": c.get("pitch", 0)}
        if c.get("emotion"):
            voice_setting["emotion"] = c["emotion"]
        payload: dict[str, Any] = {
            "model": self.model, "text": text, "stream": False, "voice_setting": voice_setting,
            "audio_setting": {"sample_rate": int(c.get("sample_rate", 44100)), "bitrate": 128000,
                              "format": self.audio_format, "channel": 1},
        }
        boost = (c.get("language_boost") or {}).get(language)
        if boost:
            payload["language_boost"] = boost
        data = self._post("/v1/t2a_v2", payload)
        audio_hex = (data.get("data") or {}).get("audio")
        if not audio_hex:
            raise VoiceError("MiniMax returned no audio for: %r" % text[:80])
        try:
            audio = bytes.fromhex(audio_hex)
        except ValueError:
            raise VoiceError("MiniMax returned audio that could not be decoded.") from None
        path = out_path.with_suffix(f".{self.audio_format}")
        path.write_bytes(audio)
        return path


PROVIDERS: dict[str, type[VoiceProvider]] = {"espeak_local": EspeakProvider, "minimax": MiniMaxProvider}


def get_provider(settings: Settings) -> VoiceProvider:
    name = settings["voice"]["provider"]
    if name not in PROVIDERS:
        raise VoiceError(
            f"Voice provider '{name}' is not implemented. Available: {', '.join(PROVIDERS)}."
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
                raw = provider.synthesize(sentence, script.language, gender, out_dir / f"raw_{key}.wav")
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
