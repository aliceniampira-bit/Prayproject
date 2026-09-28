from pathlib import Path

from src.config import load_settings
from src.script_generator import PrayerScript, validate_script
from src.style import resolve_font
from src.subtitle_generator import build_word_cues, group_words, is_weak_ending, make_layout
from src.voice_generator import NarrationSegment

TWILIGHT = Path(__file__).resolve().parent.parent / "data" / "scripts" / "twilight"


def _layout(settings, lang):
    fonts = {k: resolve_font(v, settings.path("fonts_dir")) for k, v in settings.style["fonts"].items()}
    return make_layout(settings, fonts, lang)


def test_preset_overrides_settings_and_style():
    s = load_settings()
    assert s["preset"] == "twilight_words"
    assert s["video"]["transition"] == "cut" and s["subtitles"]["mode"] == "word_groups"
    assert s.style["fonts"]["body"]["file"] == "Cinzel-Regular.ttf"
    base = load_settings(overrides={"preset": None})
    assert base["video"].get("transition") is None


def test_word_groups_are_short_and_natural():
    s = load_settings()
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
    s = load_settings()
    layout = _layout(s, "en")
    seg = NarrationSegment("prayer", "My future is safe in your hands.", 2.0, 4.0)
    cues = build_word_cues([seg], layout, offset=0.8, uppercase=True)
    assert cues[0].start == 2.8 and abs(cues[-1].end - 4.8) < 1e-6
    assert " ".join(c.text for c in cues) == seg.text.upper()


def test_twilight_scripts_fit_the_format():
    s = load_settings()
    paths = sorted(TWILIGHT.glob("*.json"))
    assert len(paths) == 6
    for path in paths:
        script = PrayerScript.load(path)
        res = validate_script(script, s.themes, s.language(script.language)["words_per_minute"],
                              s["video"]["min_duration_seconds"], s["video"]["max_duration_seconds"])
        assert res.ok, (path, res.errors)
        assert not any("short" in w or "exceeds" in w for w in res.warnings), (path, res.warnings)
