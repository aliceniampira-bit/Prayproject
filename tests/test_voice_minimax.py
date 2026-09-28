"""MiniMax provider tests with a fake HTTP session (no network, no real key).

The last test makes a real API call and only runs with MINIMAX_LIVE_TEST=1.
"""

import os

import pytest

from src.voice_generator import (PROVIDERS, MiniMaxProvider, VoiceAuthError, VoiceError,
                                 VoiceRateLimitError, get_provider)

MP3_HEX = ("494433" + "00" * 20)  # a few bytes are enough: the fake response is not decoded by ffmpeg
CONFIG = {"model": "speech-02-hd", "voice_id": "ttv-voice-test", "language_boost": {"es": "Spanish"},
          "max_retries": 2}


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json, headers))
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def ok(audio=MP3_HEX):
    return FakeResponse(payload={"base_resp": {"status_code": 0, "status_msg": "success"},
                                 "data": {"audio": audio}})


def err(code, msg="x"):
    return FakeResponse(payload={"base_resp": {"status_code": code, "status_msg": msg}})


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("src.voice_generator.time.sleep", lambda s: None)


def test_registered_and_selected_by_config(settings):
    assert PROVIDERS["minimax"] is MiniMaxProvider and "espeak_local" in PROVIDERS
    settings.data["voice"]["provider"] = "minimax"
    provider = get_provider(settings)
    assert isinstance(provider, MiniMaxProvider) and provider.model == "speech-02-hd"
    assert provider.voice_id("es", "female").startswith("ttv-voice-")
    settings.data["voice"]["provider"] = "espeak_local"
    assert get_provider(settings).name == "espeak_local"


def test_request_payload_and_audio_file(tmp_path):
    s = FakeSession(ok())
    out = MiniMaxProvider(CONFIG, session=s, api_key="").synthesize("Hola.", "es", "female",
                                                                     tmp_path / "raw.wav")
    assert out.suffix == ".mp3" and out.read_bytes() == bytes.fromhex(MP3_HEX)
    url, body, headers = s.calls[0]
    assert url == "https://api.minimax.io/v1/t2a_v2"
    assert body["model"] == "speech-02-hd" and body["voice_setting"]["voice_id"] == "ttv-voice-test"
    assert body["language_boost"] == "Spanish" and body["stream"] is False


def test_no_key_means_no_authorization_header(tmp_path, monkeypatch):
    # In Claude Code the proxy injects the header; the code must not require or invent one.
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    s = FakeSession(ok())
    MiniMaxProvider(CONFIG, session=s).synthesize("Hola.", "es", "female", tmp_path / "raw.wav")
    assert "Authorization" not in s.calls[0][2]


def test_env_key_is_sent_but_never_in_errors(tmp_path):
    secret = "sk-SECRET-should-never-leak"
    s = FakeSession(err(1004, "login fail"))
    provider = MiniMaxProvider(CONFIG, session=s, api_key=secret)
    with pytest.raises(VoiceAuthError) as exc:
        provider.synthesize("Hola.", "es", "female", tmp_path / "raw.wav")
    assert s.calls[0][2]["Authorization"] == f"Bearer {secret}"
    assert secret not in str(exc.value) and "1004" in str(exc.value)
    assert len(s.calls) == 1  # auth errors are not retried


@pytest.mark.parametrize("response", [FakeResponse(401, {}), err(2049, "invalid api key")])
def test_auth_errors(tmp_path, response):
    with pytest.raises(VoiceAuthError, match="API credentials"):
        MiniMaxProvider(CONFIG, session=FakeSession(response), api_key="").synthesize(
            "Hola.", "es", "female", tmp_path / "raw.wav")


def test_quota_is_not_retried(tmp_path):
    s = FakeSession(err(1008, "insufficient balance"))
    with pytest.raises(VoiceRateLimitError, match="balance"):
        MiniMaxProvider(CONFIG, session=s, api_key="").synthesize("Hola.", "es", "female", tmp_path / "r.wav")
    assert len(s.calls) == 1


def test_rate_limit_retries_then_fails(tmp_path):
    s = FakeSession(err(1002, "rate limit"))
    with pytest.raises(VoiceRateLimitError):
        MiniMaxProvider(CONFIG, session=s, api_key="").synthesize("Hola.", "es", "female", tmp_path / "r.wav")
    assert len(s.calls) == 2


def test_rate_limit_then_success(tmp_path):
    s = FakeSession(FakeResponse(429, {}), ok())
    out = MiniMaxProvider(CONFIG, session=s, api_key="").synthesize("Hola.", "es", "female", tmp_path / "r.wav")
    assert out.exists() and len(s.calls) == 2


@pytest.mark.parametrize("response,match", [
    (FakeResponse(503, {}), "after 2 attempts"),
    (err(1026, "sensitive"), "refused the text"),
    (ok(audio=""), "no audio"),
    (ok(audio="zz"), "could not be decoded"),
    (FakeResponse(200, None), "not JSON"),
])
def test_generation_failures(tmp_path, response, match):
    with pytest.raises(VoiceError, match=match):
        MiniMaxProvider(CONFIG, session=FakeSession(response), api_key="").synthesize(
            "Hola.", "es", "female", tmp_path / "r.wav")


def test_missing_voice_id():
    with pytest.raises(VoiceError, match="voice_id"):
        MiniMaxProvider({}, session=FakeSession(ok()), api_key="").voice_id("es", "female")


@pytest.mark.skipif(os.environ.get("MINIMAX_LIVE_TEST") != "1",
                    reason="Real MiniMax API call (costs credits); run with MINIMAX_LIVE_TEST=1")
def test_live_minimax(settings, tmp_path):
    provider = MiniMaxProvider(settings["voice"]["voices"]["minimax"])
    provider.check_auth()
    out = provider.synthesize("Hola.", "es", "female", tmp_path / "raw.wav")
    assert out.stat().st_size > 1000 and out.read_bytes()[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3")
