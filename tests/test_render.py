"""Integration test: short end-to-end render with synthetic media and the local voice."""

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
    script_path = tmp_path / "script.json"
    script_path.write_text(json.dumps(script), encoding="utf-8")

    settings = load_settings(overrides={
        "video": {"min_duration_seconds": 5, "max_duration_seconds": 60, "preset": "ultrafast",
                  "clips_per_video": 2},
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
    assert (result.folder / "video.mp4").exists()
    for name in ("script.json", "subtitles.srt", "description.txt", "hashtags.txt", "provenance.json",
                 "qc_report.json", "qc_report.md"):
        assert (result.folder / name).exists(), name
    v = next(s for s in probe(result.folder / "video.mp4")["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == (1080, 1920)
