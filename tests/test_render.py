"""Integration test: short end-to-end render with synthetic media and the local voice,
exported to every network."""

import json

from conftest import needs_espeak, needs_ffmpeg
from src.config import load_settings
from src.ffmpeg_utils import probe
from src.pipeline import produce
from src.sample_assets import make_sample_assets
from src.video_sources import LocalClipSource


@needs_ffmpeg
@needs_espeak
def test_prototype_render(tmp_path, sample_paths):
    script = json.loads(sample_paths[0].read_text(encoding="utf-8"))
    script["prayer"] = script["prayer"][:1]
    script["bible_verse"] = None
    script["type"] = "short"
    script_path = tmp_path / "script.json"
    script_path.write_text(json.dumps(script), encoding="utf-8")

    settings = load_settings(overrides={
        "video": {"preset": "ultrafast", "clips_per_video": 2},
        "prayer_types": {"short": {"min_seconds": 5}},
        "script": {"history_dirs": []},
        "paths": {"output_dir": str(tmp_path / "out"), "errors_dir": str(tmp_path / "out" / "errors"),
                  "work_dir": str(tmp_path / "work"), "media_registry": str(tmp_path / "registry.json")},
    })
    assets = make_sample_assets(tmp_path / "assets", clip_seconds=4, music_seconds=8)
    result = produce(script_path, settings, LocalClipSource(assets / "clips"),
                     music_library=assets / "music" / "music_library.json")

    report = result.report
    assert report.technical_ok, [c for c in report.checks if not c.passed]
    # Test voice and test music can never be approved for publication.
    assert not report.approved and report.status == "blocked_for_publication"
    master = result.folder
    assert master.parent.name == "_master" and master.name == "2026-10-01_short_gratitude"
    for name in ("master.mp4", "cover.jpg", "script.json", "subtitles.srt", "provenance.json",
                 "qc_report.json", "qc_report.md"):
        assert (master / name).exists(), name
    v = next(s for s in probe(master / "master.mp4")["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"], v["codec_name"], v["r_frame_rate"]) == (1080, 1920, "h264", "30/1")
    names = {c.name for c in report.checks}
    assert {"formato_y_codecs", "texto_en_zona_segura", "portada_generada", "duracion_segun_tipo",
            "voz_musica_video_sincronizados", "sin_marcas_de_otras_apps"} <= names

    assert [e.platform for e in result.exports] == ["tiktok", "instagram_reels", "youtube_shorts"]
    for ex in result.exports:
        assert ex.folder == tmp_path / "out" / "english" / ex.platform / master.name
        files = {p.name for p in ex.folder.iterdir()}
        assert f"{master.name}_en_{ex.platform}.mp4" in files
        assert {"title.txt", "description.txt", "hashtags.txt", "subtitles.srt", "metadata.json",
                "qc_report.json", "qc_report.md", "NO_PUBLICAR.txt"} <= files
        assert ("cover.jpg" in files) == (ex.platform != "youtube_shorts")
        failed = {c.name for c in ex.report.checks if not c.passed}
        assert failed <= {"voz_con_uso_comercial", "guion_revisado", "musica_con_licencia_para_la_red"}, failed
        assert ex.report.status == "blocked_for_publication"
