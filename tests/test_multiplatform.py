"""Prayer types, anti-padding rules, bilingual topics, per-network metadata and safe zones."""

import json
from pathlib import Path

import pytest

from src.config import ConfigError, load_settings
from src.platform_export import build_metadata, credits_line
from src.script_generator import (PrayerScript, estimated_video_seconds, pair_by_topic, padding_problems,
                                  validate_with_settings)
from src.video_editor import TextArea

QUEUE = Path(__file__).resolve().parent.parent / "data" / "scripts" / "queue"


def load(name):
    return PrayerScript.load(QUEUE / name)


def test_master_spec_is_configurable():
    s = load_settings()
    v = s["video"]
    assert (v["width"], v["height"], v["fps"], v["aspect_ratio"]) == (1080, 1920, 30, "9:16")
    assert (v["container"], v["video_codec"], v["audio_codec"]) == ("mp4", "libx264", "aac")
    s2 = load_settings(overrides={"video": {"fps": 25}})
    assert s2["video"]["fps"] == 25


def test_prayer_type_ranges():
    s = load_settings()
    assert (s.prayer_type("short")["min_seconds"], s.prayer_type("short")["max_seconds"]) == (30, 60)
    assert (s.prayer_type("full")["min_seconds"], s.prayer_type("full")["max_seconds"]) == (60, 90)
    with pytest.raises(ConfigError):
        s.prayer_type("medium")


def test_queue_topics_have_both_languages_and_fit_their_type():
    s = load_settings()
    scripts = [(p, PrayerScript.load(p)) for p in sorted(QUEUE.glob("*.json"))]
    topics = pair_by_topic(scripts)
    assert set(topics) == {"2026-10-07_short_hope", "2026-10-07_full_faith"}
    assert all(set(v) == {"en", "es"} for v in topics.values())
    for path, script in scripts:
        res = validate_with_settings(script, s)
        assert res.ok, (path, res.errors)
        t = s.prayer_type(script.type)
        assert t["min_seconds"] <= estimated_video_seconds(script, s) <= t["max_seconds"], path


def test_language_versions_are_written_separately():
    en, es = load("2026-10-07_en_faith.json"), load("2026-10-07_es_faith.json")
    assert en.title != es.title and len(en.prayer) != len(es.prayer)


def test_short_prayers_do_not_take_a_verse():
    s = load_settings()
    script = load("2026-10-07_en_hope.json")
    script.bible_verse = load("2026-10-07_en_faith.json").bible_verse
    assert any("Bible verse" in e for e in validate_with_settings(script, s).errors)


def test_padding_is_rejected():
    script = load("2026-10-07_en_hope.json")
    assert padding_problems(script) == []
    script.prayer.append(script.prayer[0])
    assert any("Repeated sentence" in p for p in padding_problems(script))
    script = load("2026-10-07_en_hope.json")
    script.prayer[0] += " ....."
    assert any("pause" in p for p in padding_problems(script))
    script = load("2026-10-07_en_hope.json")
    script.prayer[1] += " Amen."  # short liturgical words may repeat
    assert padding_problems(script) == []


def test_unknown_platform_override_is_an_error():
    s = load_settings()
    script = load("2026-10-07_en_faith.json")
    script.platform_overrides["myspace"] = {"title": "x"}
    assert any("myspace" in e for e in validate_with_settings(script, s).errors)


def test_safe_zone_covers_every_enabled_platform():
    s = load_settings()
    zone = s.style["safe_zone"]
    for name in s.enabled_platforms():
        for side, px in s.platform(name)["ui_overlay"].items():
            assert zone[side] >= px, (name, side)
    only_tiktok = load_settings(overrides={"platforms": {"enabled": ["tiktok"]}})
    assert only_tiktok.enabled_platforms() == ["tiktok"]


PROVENANCE = {"clips": [{"source": "pexels", "author": "Ana", "license": "Pexels License"},
                        {"source": "pexels", "author": "Ana", "license": "Pexels License"},
                        {"source": "pexels", "author": "Luis", "license": "Pexels License"}],
              "music": {"attribution": "Calm Piano by Someone (CC BY 4.0)"}}


def test_metadata_is_adapted_per_platform():
    s = load_settings()
    script = load("2026-10-07_es_hope.json")
    tt = build_metadata(script, "tiktok", s, PROVENANCE, 1.6)
    ig = build_metadata(script, "instagram_reels", s, PROVENANCE, 1.6)
    yt = build_metadata(script, "youtube_shorts", s, PROVENANCE, 1.6)
    assert tt["title"] is None and ig["title"] is None
    assert yt["title"] == "Cuando la esperanza se apaga | Oración corta"
    assert ig["caption"].startswith(script.title)
    assert "Imágenes: Pexels (Ana, Luis)" in yt["caption"] and "Música: Calm Piano" in yt["caption"]
    assert tt["cover_file"] == "cover.jpg" and yt["cover_file"] is None and yt["cover_frame_seconds"] == 1.6
    for meta in (tt, ig, yt):
        assert meta["hashtags"] == script.hashtags[:5] and meta["language"] == "es"
        assert meta["publishing"] == "manual"


def test_overrides_and_limits():
    s = load_settings()
    script = load("2026-10-07_en_faith.json")
    yt = build_metadata(script, "youtube_shorts", s, {}, None)
    assert yt["title"] == "A Prayer for Faith When You Can't See the Way"
    tt = build_metadata(script, "tiktok", s, {}, None)
    assert len(tt["hashtags"]) == s.platform("tiktok")["metadata"]["max_hashtags"]
    script.platform_overrides = {"youtube_shorts": {"hashtags": ["#Prayer", "#prayer", "#Shorts"]}}
    script.title = "A" * 120
    yt = build_metadata(script, "youtube_shorts", s, {}, None)
    assert yt["hashtags"] == ["#Prayer", "#Shorts"]
    assert len(yt["title"]) <= 100


def test_credits_line_lists_each_author_once():
    assert credits_line(PROVENANCE, "en").startswith("Footage: Pexels (Ana, Luis)")


def test_text_area_detects_platform_interface():
    area = TextArea((200, 700, 900, 1300), 2, 10, [(1.0, (200, 700, 900, 1300)), (2.0, (100, 1500, 950, 1700))])
    tiktok = {"top": 200, "bottom": 480, "left": 60, "right": 170}
    bad = area.outside(tiktok, 1080, 1920)
    assert [t for t, _ in bad] == [2.0]  # the right edge (950 > 910) and bottom (1700 > 1440)
    again = TextArea.from_dict(json.loads(json.dumps(area.to_dict())))
    assert again.outside(tiktok, 1080, 1920) == bad
