from pathlib import Path

from src.config import load_settings
from src.script_generator import PrayerScript, estimated_video_seconds, validate_script
from src.style import resolve_font
from src.subtitle_generator import build_word_cues, group_words, is_weak_ending, make_layout
from src.voice_generator import NarrationSegment

TWILIGHT = Path(__file__).resolve().parent.parent / "data" / "scripts" / "twilight"


def _layout(settings, lang):
    fonts = {k: resolve_font(v, settings.path("fonts_dir")) for k, v in settings.style["fonts"].items()}
    return make_layout(settings, fonts, lang)


def twilight():
    return load_settings(overrides={"preset": "twilight_words"})


def test_preset_overrides_settings_and_style():
    s = twilight()
    assert s["preset"] == "twilight_words"
    assert s["video"]["transition"] == "cut" and s["subtitles"]["mode"] == "word_groups"
    assert s.style["fonts"]["body"]["file"] == "APompadourText.otf"
    assert "Jost-Regular.ttf" in s.style["fonts"]["body"]["fallbacks"]
    base = load_settings(overrides={"preset": None})
    assert base["video"].get("transition") is None


def test_word_groups_are_short_and_natural():
    s = twilight()
    for lang, sentence in [
        ("es", "Pongo en tus manos mis planes, mis pendientes y también mis miedos."),
        ("en", "Guide my choices, guard my words, and give me patience with every person I meet today."),
    ]:
        layout = _layout(s, lang)
        groups = group_words(sentence, layout)
        assert " ".join(" ".join(g) for g in groups) == sentence
        assert all(1 <= len(g) <= 3 for g in groups)
        assert all(layout.fits(" ".join(g)) for g in groups)
        # Punctuation only at the end of a group, and no dangling articles/prepositions.
        assert all(not any(w[-1] in ",.;:" for w in g[:-1]) for g in groups)
        assert not any(is_weak_ending(g[-1], lang) for g in groups[:-1])


def test_word_cues_cover_the_sentence_in_order():
    s = twilight()
    layout = _layout(s, "en")
    seg = NarrationSegment("prayer", "My future is safe in your hands.", 2.0, 4.0)
    cues = build_word_cues([seg], layout, offset=0.8, uppercase=True)
    assert cues[0].start == 2.8 and abs(cues[-1].end - 4.8) < 1e-6
    assert " ".join(c.text for c in cues) == seg.text.upper()


def test_twilight_scripts_fit_the_format():
    s = twilight()
    paths = sorted(TWILIGHT.glob("*.json"))
    assert len(paths) == 6
    for path in paths:
        script = PrayerScript.load(path)
        res = validate_script(script, s.themes, s.language(script.language)["words_per_minute"])
        assert res.ok, (path, res.errors)
        # The format's documented length (45-70 s, see docs/FORMATO_TWILIGHT_WORDS.md).
        assert 45 <= estimated_video_seconds(script, s) <= 70, path
