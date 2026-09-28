import json

import pytest

from src.script_generator import (PrayerScript, ScriptValidationError, detect_language, find_similar,
                                  split_sentences, validate_script)


def test_samples_are_valid(settings, sample_paths):
    assert len(sample_paths) == 6
    themes = {PrayerScript.load(p).theme for p in sample_paths}
    assert len(themes) == 3
    for path in sample_paths:
        script = PrayerScript.load(path)
        wpm = settings.language(script.language)["words_per_minute"]
        res = validate_script(script, settings.themes, wpm, 60, 90)
        assert res.ok, (path, res.errors)


def test_missing_field_is_rejected():
    with pytest.raises(ScriptValidationError):
        PrayerScript.from_dict({"date": "2026-01-01", "language": "en"})


def test_language_mismatch_is_detected(settings, sample_paths):
    en = PrayerScript.load(next(p for p in sample_paths if "_en_" in p.name))
    es = PrayerScript.load(next(p for p in sample_paths if "_es_" in p.name))
    en.tiktok_description = es.tiktok_description
    res = validate_script(en, settings.themes)
    assert any("description" in e for e in res.errors)


def test_detect_language():
    assert detect_language("Lord, thank you for the light of this day and for all you give me") == "en"
    assert detect_language("Señor, gracias por la luz de este día y por todo lo que me das") == "es"


def test_unverified_verse_produces_warning(settings, sample_paths):
    script = PrayerScript.load(sample_paths[0])
    res = validate_script(script, settings.themes)
    assert any("pending" in w for w in res.warnings)
    script.bible_verse.verification_status = "rejected"
    assert not validate_script(script, settings.themes).ok


def test_similarity_flags_near_duplicates(sample_paths, tmp_path):
    original = PrayerScript.load(sample_paths[0])
    copy = PrayerScript.from_dict(json.loads(sample_paths[0].read_text(encoding="utf-8")))
    copy.date = "2027-01-01"
    copy.prayer[0] = copy.prayer[0].replace("morning", "evening")
    hits = find_similar(copy, [(sample_paths[0], original)], threshold=0.35)
    assert hits and hits[0]["prayer_similarity"] > 0.35


def test_samples_are_not_similar_to_each_other(sample_paths):
    scripts = [(p, PrayerScript.load(p)) for p in sample_paths]
    for path, script in scripts:
        others = [(p, s) for p, s in scripts if p != path and s.language == script.language]
        assert find_similar(script, others, threshold=0.35) == []


def test_sections_order_and_verse_reference(sample_paths):
    script = PrayerScript.load(sample_paths[0])
    kinds = [s.kind for s in script.sections()]
    assert kinds[0] == "hook" and kinds[-1] == "closing" and "verse" in kinds
    verse = next(s for s in script.sections() if s.kind == "verse")
    assert script.bible_verse.reference in verse.reference


def test_split_sentences_spanish_punctuation():
    parts = split_sentences("Señor, gracias. ¿Qué me pides hoy? Aquí estoy. Amén.")
    assert parts == ["Señor, gracias.", "¿Qué me pides hoy?", "Aquí estoy.", "Amén."]
