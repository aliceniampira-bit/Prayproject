from src.style import resolve_font
from src.subtitle_generator import (build_cues, chunk_sentence, make_layout, read_srt, wrap_title,
                                    write_srt)
from src.voice_generator import NarrationSegment


def _layout(settings, lang="en"):
    fonts = {k: resolve_font(v, settings.path("fonts_dir")) for k, v in settings.style["fonts"].items()}
    return make_layout(settings, fonts, lang), fonts


def test_chunks_fit_width_and_line_limit(settings):
    layout, _ = _layout(settings, "es")
    sentence = ("Sé tú mi fortaleza cuando la mía se acaba, y dame luz para el siguiente paso, "
                "aunque todavía no vea todo el camino que tengo por delante.")
    chunks = chunk_sentence(sentence, layout)
    assert " ".join(" ".join(c) for c in chunks) == sentence
    for lines in chunks:
        assert len(lines) <= layout.max_lines
        assert all(layout.fits(line) for line in lines)


def test_no_line_ends_with_article_when_avoidable(settings):
    layout, _ = _layout(settings, "en")
    for lines in chunk_sentence("Forgive me for the days I rushed past your gifts and noticed only "
                                "what was missing.", layout):
        assert all(line.split()[-1].lower() not in {"the", "a", "and"} for line in lines)


def test_cues_are_ordered_and_synced(settings):
    layout, _ = _layout(settings)
    segments = [NarrationSegment("hook", "Before the day gets loud, take one breath and give thanks.", 0.0, 3.2),
                NarrationSegment("prayer", "Lord, thank you for this new morning.", 4.0, 6.1)]
    cues = build_cues(segments, layout, offset=1.5, min_cue=0.9)
    assert cues[0].start == 1.5
    assert abs(cues[-1].end - 7.6) < 0.01
    for a, b in zip(cues, cues[1:]):
        assert a.end <= b.start + 1e-6


def test_srt_roundtrip(settings, tmp_path):
    layout, _ = _layout(settings)
    cues = build_cues([NarrationSegment("prayer", "Quiet what is loud inside me. Amen.", 0.0, 2.5)], layout, 1.0)
    path = write_srt(cues, tmp_path / "x.srt")
    text = path.read_text(encoding="utf-8")
    assert text.startswith("1\n00:00:01,000 --> ")
    back = read_srt(path)
    assert [c.lines for c in back] == [c.lines for c in cues]


def test_long_title_is_wrapped(settings):
    _, fonts = _layout(settings)
    lines = wrap_title("Cuando ya no puedes más", fonts["title"], settings)
    assert 1 <= len(lines) <= 3
