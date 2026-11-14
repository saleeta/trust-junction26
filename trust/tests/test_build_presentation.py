"""
Tests for trust.present.build_presentation.

The deck must stay honest: built from real artifacts, never invented numbers,
and it must be a valid single file that carries the before/after story.
"""

from __future__ import annotations

import build_presentation as bp


def test_deck_contains_all_slides():
    import html as _html
    d = {k: None for k in
         ("bases", "blast", "ab", "llm", "tree", "review")}
    html = bp.build_deck(d)
    assert html.count('<section class="slide') == len(bp.SLIDES)
    for title, _ in bp.SLIDES:
        assert _html.escape(title) in html


def test_deck_is_standalone_and_closed():
    d = {k: None for k in ("bases", "blast", "ab", "llm", "tree", "review")}
    html = bp.build_deck(d)
    assert html.strip().startswith("<!DOCTYPE html>")
    assert html.rstrip().endswith("</html>")
    assert "https://" not in html.split("<style>")[1].split("</style>")[0], \
        "no CDN inside the stylesheet"


def test_missing_artifacts_are_reported_not_invented():
    d = {k: None for k in ("bases", "blast", "ab", "llm", "tree", "review")}
    html = bp.build_deck(d)
    assert "run demo.py first" in html or "missing" in html.lower()


def test_real_artifacts_feed_real_numbers(tmp_path):
    root = tmp_path
    (root / ".trust").mkdir()
    (root / ".trust" / "ab").mkdir(parents=True)
    import json
    (root / ".trust" / "ab" / "2297-llm.json").write_text(json.dumps([
        {"strategy": "full", "prompt_tokens": 79250},
        {"strategy": "full-triaged", "prompt_tokens": 5644},
        {"strategy": "recall", "prompt_tokens": 2511},
    ]), encoding="utf-8")
    d = bp.load_artifacts(root)
    assert d["llm"] is not None and len(d["llm"]) == 3
    html = bp.build_deck(d)
    assert "79,250" in html and "5,644" in html


def test_payload_is_escaped_for_script_injection():
    d = {k: None for k in ("bases", "blast", "ab", "llm", "tree", "review")}
    d["review"] = {"title": "</script><script>alert(1)</script>"}
    html = bp.build_deck(d)
    assert "<script>alert(1)</script>" not in html
