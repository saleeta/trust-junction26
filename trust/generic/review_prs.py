"""Review every demo PR, compare token costs, and write one report page.

For each PR this runs the generic proof-carrying analyzer over its base..head
pair, records the claims and verdicts, and measures two token costs:

    basic AI     the full base..head diff dumped into a prompt (what a
                 plain coding agent would read to "fix" the PR)
    pipeline     the evidence the review actually carried (claims, witnesses,
                 check commands) - what this system needed to decide

Every number is an estimate (chars/4) and is labelled as such. The output is
a self-contained HTML report plus JSON, synced to docs/ for GitHub Pages.

    python trust/generic/review_prs.py
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTDIR = ROOT / ".trust" / "pr-reviews"

# (github PR number, base, head, repo, direction note)
PRS = [
    (1, "504da84", "ff46d84", ROOT, "Foundation - base resolution becomes a checked assumption; the TFM-guard checker ships."),
    (2, "ff46d84", "12150ee", ROOT, "Hardening - the regression test suite for already-shipped bugs."),
    (3, "12150ee", "64e9721", ROOT, "Honesty pivot - the A/B arms are automated and a design claim the measurement disproved is withdrawn."),
    (4, "64e9721", "4088340", ROOT, "The differentiator - blast-radius engine, graph retrieval, LLM cost arms and the one-command demo."),
    (5, "pr4", "pr5", ROOT / "toy" / "_repo", "Completed outcome - the corrected sample that re-ran the checkers and was accepted by the named engineer."),
]


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                       text=True, timeout=300)
    return p.stdout if p.returncode == 0 else ""


def tokens(text: str) -> int:
    return max(1, math.ceil(len(text or "") / 4))


def run_analyzer(repo: Path, base: str, head: str) -> dict:
    out = subprocess.run(
        [sys.executable, str(ROOT / "trust" / "generic" / "analyze.py"),
         str(repo), "--base", base, "--head", head],
        capture_output=True, text=True, timeout=600)
    # the analyzer names the output dir after the repo basename with some
    # characters rewritten (e.g. big-hackathon -> Review_big-hackathon);
    # take the freshest matching review.json written by this run
    candidates = [p for p in (ROOT / ".trust" / "generic").glob("Review_*/review.json")
                  if repo.name in p.parent.name]
    if not candidates:
        return {"error": (out.stdout or "")[-200:] + (out.stderr or "")[-200:]}
    review_path = max(candidates, key=lambda p: p.stat().st_mtime)
    data = json.loads(review_path.read_text(encoding="utf-8"))
    data["_stdout"] = out.stdout[-600:]
    return data


def review_pr(number: int, base: str, head: str, repo: Path,
              direction: str) -> dict:
    full_diff = git(repo, "diff", f"{base}..{head}")
    basic_tokens = tokens(full_diff) + tokens(git(repo, "log", "-1",
                                                  "--format=%B", head))
    data = run_analyzer(repo, base, head)
    claims = data.get("claims") or []
    pipeline_tokens = tokens(json.dumps(
        [{"id": c.get("id"), "label": c.get("label"), "claim": c.get("claim"),
          "witnesses": c.get("witnesses")} for c in claims], ensure_ascii=False))
    record = {
        "pr": number,
        "base": base,
        "head": head,
        "title": git(repo, "log", "-1", "--format=%s", head),
        "direction": direction,
        "claims": [{"id": c.get("id"), "label": c.get("label"),
                    "claim": (c.get("claim") or c.get("short") or "")[:200],
                    "witnesses": (c.get("witnesses") or [])[:4]}
                   for c in claims],
        "tokens": {"basic_ai": basic_tokens,
                   "pipeline": pipeline_tokens},
        "error": data.get("error"),
    }
    return record


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(ROOT / "demo" / "review-all-prs.html"))
    args = ap.parse_args(argv)

    OUTDIR.mkdir(parents=True, exist_ok=True)
    records = []
    for number, base, head, repo, direction in PRS:
        rec = review_pr(number, base, head, repo, direction)
        records.append(rec)
        (OUTDIR / f"pr{number}.json").write_text(
            json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"PR #{number}: {rec['title'][:50]}")
        for c in rec["claims"]:
            print(f"    {c['label'][:22]:22} {c['id']}: {c['claim'][:60]}")
        if rec.get("error"):
            print(f"    ERROR {rec['error'][:120]}")
        print(f"    tokens: basic AI {rec['tokens']['basic_ai']} vs pipeline "
              f"{rec['tokens']['pipeline']}")

    html = build_report(records)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    docs = ROOT / "docs" / out.name
    docs.write_text(html, encoding="utf-8")
    print(f"wrote {out.resolve()} and {docs.resolve()}")
    return 0


_LABEL_CLS = {"Refuted": "bad", "Proved within scope": "ok",
              "Tested": "mid", "Unknown": "dim"}


def build_report(records: list[dict]) -> str:
    rows = ""
    max_tok = max((r["tokens"]["basic_ai"] for r in records), default=1)
    for r in records:
        claims = ""
        for c in r.get("claims") or []:
            cls = _LABEL_CLS.get(c.get("label"), "dim")
            wit = ""
            if c.get("witnesses"):
                wit = (f"<span class='dim'> witness: "
                       f"{json.dumps(c['witnesses'][0])[:60]}</span>")
            claims += (f"<div class='claim'><span class='tag {cls}'>"
                       f"{c.get('label', '?')}</span> <b>{c.get('id')}</b> "
                       f"{c.get('claim', '')} {wit}</div>")
        b = r["tokens"]["basic_ai"]
        p = r["tokens"]["pipeline"]
        bp = int(100 * b / max_tok)
        pp = int(100 * p / max_tok)
        rows += f"""
        <tr>
          <td class="pr"><b>#{r['pr']}</b><br><span class="dim">{r['head'][:9]}</span></td>
          <td class="title">{r['title']}<br><span class="dim">{r['direction']}</span></td>
          <td class="claims">{claims or f"<span class='dim'>{r.get('error','no claims')[:120]}</span>"}</td>
          <td class="tok">
            <div class="bar basic" style="width:{bp}%"></div>
            <span>basic AI ~{b:,} tok</span>
            <div class="bar pipe" style="width:{pp}%"></div>
            <span>pipeline ~{p:,} tok</span>
          </td>
        </tr>"""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Review of every demo PR - verdicts, direction, token costs</title>
<style>
:root{{--paper:#f6f4ef;--ink:#1d2333;--muted:#68707f;--line:#d3d7dc;--accent:#6d4a9e;--red:#b0413e;--amber:#9a6a1f;--green:#2f7d5d}}
body{{margin:0;background:#e9e7e1;color:var(--ink);font-family:Arial,"Segoe UI",sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:34px 24px 60px}}
h1{{font:normal clamp(30px,4vw,52px)/1.05 Georgia,serif;letter-spacing:-.03em;margin:6px 0}}
.lead{{color:#4a5468;font-size:17px;max-width:900px}}
table{{width:100%;border-collapse:collapse;background:#fffdf9;border:1px solid var(--line);margin-top:18px}}
th{{font:700 12px Consolas,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);background:#f0ede6}}
td{{vertical-align:top;padding:12px;border-bottom:1px solid var(--line);font-size:14px}}
td.pr{{width:64px}} td.title{{width:300px}} td.claims{{min-width:340px}} td.tok{{width:200px}}
.dim{{color:var(--muted);font-size:12.5px}}
.claim{{padding:3px 0;font-size:13.5px}}
.tag{{display:inline-block;font:700 10px Consolas,monospace;border-radius:9px;padding:1px 8px;margin-right:4px;letter-spacing:.04em}}
.tag.bad{{background:#f8e8e5;color:var(--red)}} .tag.ok{{background:#e2efe9;color:var(--green)}}
.tag.mid{{background:#f8eedd;color:var(--amber)}} .tag.dim{{background:#e9e7e1;color:var(--muted)}}
.tok span{{font:12px Consolas,monospace;color:var(--muted);display:block;margin:2px 0}}
.bar{{height:10px;border-radius:5px;margin-top:2px}}
.bar.basic{{background:#c9cdd6}} .bar.pipe{{background:var(--accent)}}
.foot{{color:var(--muted);font-size:12.5px;margin-top:12px}}
a{{color:var(--accent)}}
</style></head><body><main>
<h1>Every demo PR, reviewed</h1>
<p class="lead">The same proof-carrying analyzer ran on each PR's base..head pair.
Verdicts use the four honest labels. "Direction" states what the PR means for
where the project is going. Token figures compare a basic AI reading the whole
diff against this pipeline carrying only the evidence it needs - estimates
(chars/4), labelled as such.</p>
<table>
<tr><th>PR</th><th>what it is · direction</th><th>verdicts from the checker</th><th>tokens</th></tr>
{rows}
</table>
<p class="foot">Reviewer: trust/generic/analyze.py (static + executed tiers). Evidence per PR in
<a href="../.trust/pr-reviews/">.trust/pr-reviews/</a>. The known-gap sample stays pending on
<a href="https://entire.com/et/earned-trust-review/-/trails/1">Entire Trail #1</a>; the corrected
sample was accepted on <a href="https://entire.com/et/earned-trust-review/-/trails/2">Trail #2</a>.</p>
</main></body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
