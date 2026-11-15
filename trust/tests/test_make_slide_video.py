"""The slide video's narration must cover every slide of the current deck."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "trust" / "present"))

import make_slide_video  # noqa: E402


def test_narration_covers_every_slide():
    deck = (ROOT / "demo" / "architecture-presentation.html").read_text(
        encoding="utf-8")
    slides = len(re.findall(r'<section class="slide', deck))
    assert slides == len(make_slide_video.SCRIPT), (
        f"deck has {slides} slides but the video script has "
        f"{len(make_slide_video.SCRIPT)} narration segments")
    # every segment is speakable and non-trivial
    for i, text in enumerate(make_slide_video.SCRIPT):
        assert len(text) > 120, f"narration {i} is too short: {text[:60]!r}"
    # no silent empty slide: each segment maps to the same order
    assert make_slide_video.SCRIPT[0].startswith("Here's the problem")
    assert make_slide_video.SCRIPT[-1].endswith("owns the trust.")
