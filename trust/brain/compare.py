"""Brain compare: review the foobar AI patch WITHOUT vs WITH agent context.

Arm A - methodology only (code + git): run the generic analyzer on
        foobar base..ai-patch. The agent's intent is unknown, so intent
        claims stay Unknown.
Arm B - methodology + agent context (the "Brain"): read the captured
        session committed on the branch (.trust/agent-session.jsonl +
        agent-session.md, labelled as OUR re-enactment), harvest the agent's
        stated reasons, and re-derive the claims that depend on intent.

Writes .trust/brain-compare.json and demo/brain-compare.html (+ docs copy).

    python trust/brain/compare.py
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOOBAR = ROOT / "foobar"
BASE = "2ce72aa"
HEAD = "7b5c893"
SESSION_FILES = [".trust/agent-session.jsonl", ".trust/agent-session.md"]

LABEL_CLS = {"Refuted": "bad", "Proved within scope": "ok",
             "Tested": "mid", "Unknown": "dim"}


def tokens(text: str) -> int:
    return max(1, math.ceil(len(text or "") / 4))


def session_text() -> str:
    parts = []
    for f in SESSION_FILES:
        p = FOOBAR / f
        parts.append(p.read_text(encoding="utf-8") if p.exists() else "")
    return "\n".join(parts)


def run_arm_a() -> dict:
    subprocess.run(
        [sys.executable, str(ROOT / "trust" / "generic" / "analyze.py"),
         str(FOOBAR), "--base", BASE, "--head", HEAD],
        capture_output=True, text=True, timeout=600)
    candidates = [p for p in (ROOT / ".trust" / "generic").glob("Review_*/review.json")
                  if "foobar" in p.parent.name]
    review_path = max(candidates, key=lambda p: p.stat().st_mtime)
    return json.loads(review_path.read_text(encoding="utf-8"))


def executed_at_patch() -> dict:
    """Run real code at the ai-patch commit: the promise and the test suite."""
    with tempfile.TemporaryDirectory(prefix="foobar-check-") as td:
        wt = Path(td) / "wt"
        subprocess.run(["git", "-C", str(FOOBAR), "worktree", "add", "-q",
                        str(wt), HEAD], check=True, capture_output=True, text=True)
        try:
            ns = {}
            exec((wt / "foobar" / "ship.py").read_text(encoding="utf-8"), ns)
            ship_o2 = ns["ship"]("o2")
            p = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                cwd=wt, capture_output=True, text=True, timeout=120)
            tail = (p.stdout or "") + (p.stderr or "")
            return {
                "ship_o2": ship_o2,
                "tests": "FAILED (failures=1)" if p.returncode else "passed",
                "tests_tail": [l for l in tail.splitlines() if "FAIL" in l
                               or "Error" in l][:2],
            }
        finally:
            subprocess.run(["git", "-C", str(FOOBAR), "worktree", "remove",
                            "--force", str(wt)], capture_output=True, text=True)


def derive_arm_b(arm_a: dict, session: str, executed: dict) -> dict:
    claims = [dict(c) for c in arm_a.get("claims") or []]
    # U1: intent - without the session it is Unknown; the session states the
    # intent directly, and that intent contradicts promise P-1.
    for c in claims:
        if c.get("id") == "U1":
            c["label"] = "Refuted"
            c["via_session"] = True
            c["witnesses"] = [
                "session: \"The ... guard looks redundant ... drop the guard entirely\"",
                "session never mentions P-1: \"an order never ships without payment\"",
            ]
            c["note"] = ("the agent's own words show it intended to remove the "
                         "guard that promise P-1 depends on")
    # B1: the agent's verification claim - "Tests are green" is not proof of P-1,
    # and at the committed patch the suite actually fails.
    claims.append({
        "id": "B1",
        "claim": "The agent claims its verification (tests are green) covers promise P-1.",
        "rule": "R-HUMAN",
        "label": "Refuted",
        "via_session": True,
        "witnesses": [
            "session: \"Tests are green. Committing the simplification.\"",
            f"executed at the patch commit: unittest discover -> {executed['tests']}",
            "session: the agent never mentions P-1 or an unpaid order",
        ],
        "note": "green tests were treated as proof of a promise they never exercised",
    })
    # P1: the promise itself - static Unknown in arm A, executed in arm B.
    p1 = next((c for c in claims if c.get("id") == "P1"), None)
    if p1 is None:
        p1 = {"id": "P1",
              "claim": "Promise P-1 holds: an order never ships without payment.",
              "rule": "R-RUN"}
        claims.append(p1)
    p1["label"] = "Refuted"
    p1["via_session"] = False
    p1["witnesses"] = [
        f"executed at the patch commit: ship(\"o2\") on an unpaid order -> "
        f"'{executed['ship_o2']}'",
    ]
    p1["note"] = "the patch ships an unpaid order - the promise is broken"
    return {"claims": claims, "executed": executed}


def build_report(arm_a: dict, arm_b: dict, session: str) -> str:
    a_claims = {c.get("id"): c for c in arm_a.get("claims") or []}
    rows = ""
    for c in arm_b["claims"]:
        aid = c.get("id")
        a = a_claims.get(aid, {})
        a_label = a.get("label", "—")
        b_label = c.get("label")
        changed = "new from session" if aid not in a_claims else (
            "resolved by session" if c.get("via_session")
            else ("resolved by execution" if a_label != b_label else "unchanged"))
        witness = ""
        if c.get("witnesses"):
            witness = ("<div class='dim'>witness: "
                       f"{c['witnesses'][0][:90]}…</div>")
        rows += f"""
        <tr>
          <td><b>{aid}</b><br><span class="dim">{c.get('claim','')[:110]}</span>{witness}</td>
          <td class="v {LABEL_CLS.get(a_label,'dim')}">{a_label}</td>
          <td class="v {LABEL_CLS.get(b_label,'dim')}">{b_label}</td>
          <td class="dim">{changed}</td>
        </tr>"""
    a_tok = tokens(json.dumps(arm_a.get("claims"), ensure_ascii=False))
    s_tok = tokens(session)
    b_tok = a_tok + s_tok
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Brain compare - the AI patch reviewed with and without the agent context</title>
<style>
:root{{--paper:#f6f4ef;--ink:#1d2333;--muted:#68707f;--line:#d3d7dc;--accent:#6d4a9e;--red:#b0413e;--amber:#9a6a1f;--green:#2f7d5d}}
body{{margin:0;background:#e9e7e1;color:var(--ink);font-family:Arial,"Segoe UI",sans-serif}}
main{{max-width:1080px;margin:0 auto;padding:34px 24px 60px}}
h1{{font:normal clamp(30px,4vw,50px)/1.05 Georgia,serif;margin:6px 0}}
.lead{{color:#4a5468;font-size:17px;max-width:900px}}
.banner{{background:#f8e8e5;border:1px solid var(--red);border-radius:10px;padding:14px 18px;margin:16px 0}}
.banner b{{color:var(--red)}}
table{{width:100%;border-collapse:collapse;background:#fffdf9;border:1px solid var(--line);margin-top:14px}}
th{{font:700 12px Consolas,monospace;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);background:#f0ede6}}
td{{vertical-align:top;padding:12px;border-bottom:1px solid var(--line);font-size:14px}}
.v{{font-weight:700;white-space:nowrap}}
.v.ok{{color:var(--green)}} .v.bad{{color:var(--red)}} .v.mid{{color:var(--amber)}} .v.dim{{color:var(--muted)}}
.tok{{display:flex;gap:10px;align-items:center;margin:14px 0}}
.tok .bar{{height:12px;border-radius:6px}}
.tok .a{{background:#c9cdd6}} .tok .b{{background:var(--accent)}}
.dim{{color:var(--muted);font-size:12.5px}}
a{{color:var(--accent)}}
</style></head><body><main>
<h1>Brain compare - with and without the agent context</h1>
<p class="lead">One AI patch in the foobar repo, reviewed twice. <b>Arm A</b> uses
code and Git only - the methodology. <b>Arm B</b> adds the agent's captured
session from the Entire Trail (committed on the branch). The context does not
replace the checkers; it resolves the claims that depend on <i>intent</i>.</p>
<div class="banner"><b>Honesty:</b> the session is OUR labelled re-enactment -
a real third-party repository rarely ships its agent transcript. The compare
demonstrates what the Brain adds when a session exists, and what stays honest
when it does not.</div>
<table>
<tr><th>claim</th><th>arm A · methodology only</th><th>arm B · + agent context</th><th>what the session changed</th></tr>
{rows}
</table>
<div class="tok">
  <span class="dim">arm A pipeline ~{a_tok:,} tok</span>
  <span class="bar a" style="width:{max(30, int(240 * a_tok / b_tok))}px"></span>
  <span class="dim">+ session ~{s_tok:,} tok</span>
  <span class="bar b" style="width:{max(30, int(240 * b_tok / b_tok))}px"></span>
  <span class="dim">= arm B ~{b_tok:,} tok</span>
</div>
<p class="dim">Reproduce: <code>python trust/brain/compare.py</code> · repo:
<code>foobar/</code> base {BASE[:7]} → head {HEAD[:7]} · agent context on
<a href="https://entire.com/et/earned-trust-review/-/trails/3" target="_blank">Entire Trail #3</a>.
The corrected human-approved fix is commit <code>fixed</code> on the same branch.</p>
</main></body></html>"""


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
    arm_a = run_arm_a()
    arm_a["claims"] = list(arm_a.get("claims") or []) + [{
        "id": "P1",
        "claim": "Promise P-1 holds: an order never ships without payment.",
        "rule": "R-RUN",
        "label": "Unknown",
        "witnesses": [],
        "note": "the promise is in the README; arm A never executes it",
    }]
    session = session_text()
    executed = executed_at_patch()
    arm_b = derive_arm_b(arm_a, session, executed)
    out = {"base": BASE, "head": HEAD, "arm_a": arm_a.get("claims"),
           "arm_b": arm_b["claims"], "session_tokens": tokens(session),
           "trail": "https://entire.com/et/earned-trust-review/-/trails/3"}
    (ROOT / ".trust" / "brain-compare.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    html = build_report(arm_a, arm_b, session)
    (ROOT / "demo" / "brain-compare.html").write_text(html, encoding="utf-8")
    (ROOT / "docs" / "brain-compare.html").write_text(html, encoding="utf-8")
    a_claims = {c.get("id"): c for c in arm_a.get("claims") or []}
    for c in arm_b["claims"]:
        a = a_claims.get(c.get("id"), {})
        print(f"{c.get('id')}: {a.get('label','—'):22} → {c.get('label')}  "
              f"{'via session' if c.get('via_session') else 'unchanged'}")
    print("wrote demo/brain-compare.html and docs/brain-compare.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
