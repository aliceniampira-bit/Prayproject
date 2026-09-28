import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SAMPLES = ROOT / "data" / "scripts" / "samples"


@pytest.fixture
def settings():
    from src.config import load_settings
    return load_settings()


@pytest.fixture
def sample_paths():
    return sorted(SAMPLES.glob("*.json"))


needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                                  reason="FFmpeg not installed")
needs_espeak = pytest.mark.skipif(not (shutil.which("espeak-ng") or shutil.which("espeak")),
                                  reason="espeak-ng not installed")
