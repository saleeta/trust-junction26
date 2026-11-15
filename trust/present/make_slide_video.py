"""Render the architecture deck slides and build a narrated slide video.

1. Writes one temp HTML per slide (controls hidden, show(i) forced).
2. Screenshots each with headless Chrome at 1440x900 (16:10 page, 16:9 stage).
3. Synthesizes a lively voiceover per slide with edge-tts (neural voice).
4. Composes segment videos + audio, concats into demo/videos/trust-pitch.mp4.

Usage: python trust/present/make_slide_video.py
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DECK = ROOT / "demo" / "architecture-presentation.html"
OUT = ROOT / "demo" / "videos" / "trust-pitch.mp4"

CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe"
VOICE = "en-US-JennyNeural"
RATE = "+10%"
PITCH = "+2Hz"

# Lively, conversational narration - one entry per slide, matching the deck.
SCRIPT = [
    "Here's the problem, in one picture. An AI was asked to shorten a function called average. "
    "It deleted one little line — the guard for an empty list. Every test stayed green, because "
    "no test ever tried an empty list. Then someone calls average on nothing — and it crashes. "
    "This is the everyday AI-coding accident. And this review catches it.",

    "So here's the idea. Same change, two reviews. One gives an opinion — 'looks fine to me'. "
    "The other runs a test that anyone can repeat. Don't take the AI's word for it: make it "
    "show proof. Every claim gets a sentence, a scope, and one command that re-runs the check.",

    "Step one: gather the evidence. What was promised, what the AI changed, and why it did it "
    "— from the AI's own chat log. Then we put them side by side. And when the chat log "
    "doesn't exist? We label the gap. No fake context, ever.",

    "Step two: turn the promise into a test. 'Never crashes' is vague — so we rewrite it so a "
    "computer can check it: for every list, including the empty one, average must not crash. "
    "One sentence, one scope, one command. That's an audit trail you can walk.",

    "Step three: run it — then look around. We try every list, including the empty one. It "
    "crashes — and one crash is enough to prove the claim wrong. Then we ask: what else uses "
    "average? Every caller gets re-checked. Leads — not guilt.",

    "Step four: only four honest answers. Refuted: we saw it fail. Proved in scope: we checked "
    "the whole stated domain. Tested: the examples passed. Unknown: reported, never dropped. "
    "An answer only counts if a real run produced it — the AI can suggest. It can't hand out answers.",

    "And this is how it grows: we check promises, not lines. One promise covers many lines of "
    "code. Each review reads only what changed — and every promise that's already checked "
    "becomes a test for the next change. The trust compounds.",

    "Does it work? We ran it on all five PRs of this project. Same checks on every change. "
    "Grey: how much text a basic AI must read — up to thirty-six thousand tokens. Purple: what "
    "our review actually needed — four hundred.",

    "And none of this floats in the air. The Entire Trail carries the agent context with the "
    "change — and the brain compare proves why that matters: with the session, the agent's own "
    "words refute its intent. MongoDB keeps the audit ledger — every visit, every token, "
    "re-walkable by anyone. They are not add-ons. They are essential parts.",

    "Finally — who decides? The AI finds the problem, but it is never allowed to approve its "
    "own work. It hands a person the evidence, and the person decides. In our repo, a named "
    "engineer — Saleeta Qadir — signed the corrected patch. The AI cannot sign. A human owns the trust.",
]

HIDE_CSS = "<style>.controls,.notes,#details{display:none!important}</style>"


def slides_html() -> list[str]:
    src = DECK.read_text(encoding="utf-8")
    n = len(re.findall(r"<section class=\"slide", src))
    out = []
    for i in range(n):
        # force the LAST show(0) (the boot call, not the one inside start())
        at = src.rfind("show(0);")
        html = src[:at] + f"show({i});" + src[at + len("show(0);"):]
        html = html.replace("</head>", HIDE_CSS + "</head>", 1)
        out.append(html)
    return out


def screenshot(html: str, png: Path) -> None:
    p = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=2", "--window-size=1440,900",
         f"--screenshot={png}", f"file:///{html}"],
        capture_output=True, text=True, timeout=180)
    if not png.exists():
        raise RuntimeError(p.stdout[-500:] + p.stderr[-500:])


def probe_duration(path: Path) -> float:
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "default=nw=1:nk=1",
                        str(path)], capture_output=True, text=True)
    return float(p.stdout.strip())


def compose(work: Path, slide_pngs: list[Path], voice_mp3s: list[Path]) -> None:
    segments = []
    for i, (png, mp3) in enumerate(zip(slide_pngs, voice_mp3s)):
        dur = probe_duration(mp3) + 0.9  # breath at the end of each slide
        seg = work / f"seg{i}.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-loop", "1", "-i", str(png), "-i", str(mp3),
             "-c:v", "libx264", "-tune", "stillimage", "-preset", "medium",
             "-crf", "20", "-pix_fmt", "yuv420p", "-r", "25",
             "-af", f"apad=pad_dur={dur - probe_duration(mp3):.2f}",
             "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.2f}", "-shortest",
             str(seg)],
            check=True, capture_output=True, text=True, timeout=600)
        segments.append(seg)
    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{s.as_posix()}'\n" for s in segments),
                      encoding="utf-8")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
         "-c", "copy", str(OUT)],
        check=True, capture_output=True, text=True, timeout=600)


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        print("ffmpeg not on PATH - it was installed via winget; restart the shell "
              "or set PATH manually", file=sys.stderr)
        return 1

    htmls = slides_html()
    print(f"{len(htmls)} slides, {len(SCRIPT)} voiceover segments")

    with tempfile.TemporaryDirectory(prefix="slidevideo-") as td:
        work = Path(td)
        pngs, mp3s = [], []
        for i, (html, text) in enumerate(zip(htmls, SCRIPT)):
            html_p = work / f"slide{i}.html"
            png = work / f"slide{i}.png"
            mp3 = work / f"voice{i}.mp3"
            html_p.write_text(html, encoding="utf-8")
            print(f"  screenshot slide {i + 1} ...")
            screenshot(html_p, png)
            print(f"  voiceover slide {i + 1} ...")
            p = subprocess.run(
                [sys.executable, "-m", "edge_tts", "--voice", VOICE,
                 "--rate", RATE, "--pitch", PITCH, "--text", text,
                 "--write-media", str(mp3)],
                capture_output=True, text=True, timeout=180)
            if p.returncode != 0 or not mp3.exists():
                print(p.stdout[-300:] + p.stderr[-300:], file=sys.stderr)
                return 1
            pngs.append(png)
            mp3s.append(mp3)
        print("  composing video ...")
        compose(work, pngs, mp3s)
    print(f"done: {OUT.resolve()} ({OUT.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
