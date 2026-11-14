#!/usr/bin/env python
"""
demo.py - the whole thing, one command.

    python demo.py                 # full run, ends with `dotnet test` failing
    python demo.py --quick         # skip the generated repro build and test
    python demo.py --branch origin/ju26-issue-2283

Runs every beat in order and prints the honesty rules at the end, because a
demo that oversells is the exact failure this project exists to attack.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRUST = ROOT / "trust"
REPO = ROOT / "repo"
OUT = ROOT / ".trust"

EXPECT_FILES = {"2283": 4, "2234": 4, "2129": 28, "2297": 237}


def hdr(n: str, title: str, why: str = "") -> None:
    print()
    print("#" * 78)
    print(f"#  BEAT {n}  {title}")
    if why:
        print(f"#  {why}")
    print("#" * 78)


def run(cmd: list[str], cwd: Path, tail: int | None = None,
        grep: tuple[str, ...] | None = None) -> int:
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, *cmd], cwd=cwd, capture_output=True,
                           text=True, timeout=1800, encoding="utf-8",
                           errors="replace")
    except subprocess.TimeoutExpired:
        print(f"   [timed out after {time.time() - t0:.1f}s]")
        return 2
    text = (p.stdout or "") + (p.stderr or "")
    lines = text.splitlines()
    if grep:
        lines = [l for l in lines if any(g in l for g in grep)]
    if tail:
        lines = lines[-tail:]
    for l in lines:
        print("   " + l)
    print(f"   [{time.time() - t0:.1f}s, exit {p.returncode}]")
    return p.returncode


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--branch", default="origin/ju26-issue-2297")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--session", default=None,
                    help="session id for the provenance beats")
    args = ap.parse_args()

    if not (REPO / ".git").exists():
        print(f"target repo not found at {REPO}")
        print("  git clone https://github.com/te-industry-tech-office/"
              "junction26-messagepack-csharp.git repo")
        return 1

    issue_num = "".join(c for c in args.branch if c.isdigit())[-4:]
    issue = OUT / "issues" / f"{issue_num}.md"
    expect = EXPECT_FILES.get(issue_num)
    base = subprocess.run(["git", "rev-parse", f"{args.branch}^"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()
    if not base:
        print(f"cannot resolve parent of {args.branch}; stopping review")
        return 1

    print("=" * 78)
    print("  HOW CAN AI REVIEW CODE MADE BY AI SO THAT HUMANS CAN TRUST IT?")
    print("=" * 78)
    print(f"  target   {args.branch}")
    print(f"  base     {base[:9]}")
    print(f"  repo     {REPO}")
    print("\n  The answer this demo defends: AI supplies checkable evidence;")
    print("  a named engineer owns the review decision.")
    print("  Two-minute stage card: demo/review-2297.html")

    # ---- BEAT 0 ---------------------------------------------------------
    hdr("0", "The reviewer that was confidently wrong",
        "an unrecorded assumption produced a false finding on these branches")
    print("   This project's own reviewer reported that all four agentic")
    print("   branches re-applied a dependency bump the maintainers had")
    print("   reverted. It cited a real commit. It was WRONG: origin/develop")
    print("   does not exist here, so a merge-base fallback silently used")
    print("   master and every diff started two commits too early.\n")
    for label, cmd in (
            ("real base (first parent) ", ["rev-parse", f"{args.branch}^"]),
            ("merge-base with master   ", ["merge-base", args.branch, "origin/master"]),
    ):
        got = subprocess.run(["git", *cmd], cwd=REPO, capture_output=True,
                             text=True).stdout.strip()
        print(f"   {label} {got[:9]}")
    miss = subprocess.run(["git", "rev-parse", "--verify", "origin/develop"],
                          cwd=REPO, capture_output=True, text=True)
    print(f"   origin/develop exists?     {'yes' if miss.returncode == 0 else 'NO'}")

    # ---- BEAT 1 ---------------------------------------------------------
    hdr("1", "Base resolution as a checked assumption",
        "cross-check several methods; refuse to pick silently; use an oracle")
    cmd = ["base_resolver.py", "--repo", str(REPO), "--branch", args.branch]
    if expect:
        cmd += ["--expect-files", f"{issue_num}={expect}"]
    cmd += ["--json", str(OUT / "bases.json")]
    if run(cmd, TRUST / "ingest"):
        return 1

    # ---- BEAT 2 ---------------------------------------------------------
    hdr("2", "Assumption ledger and blast radius",
        "one falsified assumption yields a family of pre-aimed hypotheses")
    ledger = OUT / "findings" / f"{issue_num}-blast.json"
    cmd = ["engine.py", "--repo", str(REPO), "--branch", args.branch,
           "--base", base, "--json", str(ledger)]
    if issue.exists():
        cmd += ["--issue-text", str(issue)]
    else:
        print(f"   (no issue text captured for #{issue_num}; intent checks "
              f"will be skipped)")
    if run(cmd, TRUST / "assumptions",
        grep=("ASSUMPTION LEDGER", "[FALSIFIED]", "[OK]", "[?]", "ASSUMPTION ",
              "BLAST RADIUS", "PRE-AIMED", "EVIDENCE", "  - ", "severity",
              "VERIFY", "separately")):
        return 1

    # ---- BEAT 3 ---------------------------------------------------------
    hdr("3", "Graph retrieval instead of a context dump",
        "cited snippets within a token budget, backed by SQLite")
    db = OUT / "memory.db"
    graph = TRUST / "session_graph" / "session_graph.json"
    cmd = ["recall.py", "--rebuild", "--db", str(db), "--repo", str(REPO),
           "--base", base, "--branch", args.branch, "--ledger", str(ledger),
           "--budget", "1200",
           "--query", "why is the attribute guarded by a target framework"]
    if graph.exists():
        cmd += ["--graph", str(graph)]
    if issue.exists():
        cmd += ["--issue", str(issue)]
    if run(cmd, TRUST / "memory", grep=("ingested", "store holds", "recall(",
                                        "assumption ::", "diff ::", "issue ::")):
        return 1

    # ---- BEAT 3b ---------------------------------------------------------
    hdr("3b", "The context tree: lookups, propagation, token ledger",
        "a falsified claim re-enters the tree; the walk is measured against "
        "a traditional agent reading the raw diff")
    tree_json = OUT / "tree" / f"{issue_num}-tree.json"
    tree_html = OUT / "tree" / f"{issue_num}-tree.html"
    cmd = ["context_tree.py", "--repo", str(REPO), "--branch", args.branch,
           "--base", base, "--json", str(tree_json), "--html", str(tree_html)]
    if issue.exists():
        cmd += ["--issue", str(issue)]
    if ledger.exists():
        cmd += ["--ledger", str(ledger)]
    if graph.exists():
        cmd += ["--graph", str(graph)]
    if run(cmd, TRUST / "tree",
           grep=("tree nodes", "full dump", "walk total", "lookup",
                 "propagate", "wrote", "REVISITS")):
        return 1

    # ---- BEAT 4 ---------------------------------------------------------
    hdr("4", "What context actually costs a model",
        "dump the diff vs. triage it vs. retrieve - measured, not asserted")
    cmd = ["llm_arm.py", "--repo", str(REPO), "--branch", args.branch,
           "--base", base, "--db", str(db), "--dry-run",
           "--json", str(OUT / "ab" / f"{issue_num}-llm.json")]
    if issue.exists():
        cmd += ["--issue", str(issue)]
    if run(cmd, TRUST / "ab"):
        return 1

    # ---- BEAT 5 ---------------------------------------------------------
    hdr("5", "Exploratory naive vs checked pipeline",
        "different checks; not a causal author-capsule experiment")
    cmd = ["run_ab.py", "--repo", str(REPO), "--branch", args.branch,
           "--json", str(OUT / "ab" / f"{issue_num}.json")]
    if issue.exists():
        cmd += ["--issue", str(issue)]
    if expect:
        cmd += ["--expect-files", str(expect)]
    if run(cmd, TRUST / "ab"):
        return 1

    # ---- BEAT 6 ---------------------------------------------------------
    hdr("6", "You run it, not us",
        "the finding ends as a test the audience executes")
    if args.quick:
        print("   skipped (--quick)")
    else:
        repro = OUT / "repro" / issue_num
        rc = run(["make_repro.py", "--repo", str(REPO), "--branch", args.branch,
                  "--ledger", str(ledger), "--out", str(repro), "--run"],
                 TRUST / "repro", tail=18)
        if rc:
            return rc
        if rc == 0:
            print(f"\n   Audience command:  cd {repro} && dotnet test")

    # ---- honesty --------------------------------------------------------
    print()
    print("=" * 78)
    print("  HONESTY RULES  (read these out)")
    print("=" * 78)
    print("""
  1. Beat 0's false finding is OURS, not Tieto's. We produced it, our own
     tooling caught it, and we lead with it.

  2. The #2297 agent did most of this job WELL: six templates updated, 222
     snapshots regenerated consistently, .tt and .cs kept in sync. Say so
     before the finding.

  3. The finding is a FEATURE GAP plus a false sentence in the README. Not a
     crash, not data corruption, not a security issue. Do not inflate it.

  4. Three of the four branches yield nothing real from either arm. That is an
     honest result, not four wins.

  5. Private agent reasoning is NOT recoverable. Claude Code stores thinking
     blocks empty (36 blocks, 0 chars). We recover what was RECORDED.

  6. We have NO transcript for Tieto's four branches, so there is no capsule
     of their agents' reasoning and we claim none. Every assumption checked
     here is read off what they COMMITTED - a guard in the code, a sentence in
     the README - which are observable facts. The session-provenance beats
     (why_lines, the graph) run on OUR session and are labelled as ours.

  7. Confirmed findings and unverified hypotheses are counted separately and
     never combined into one score.

  8. Token figures from --dry-run may use tiktoken or a rough fallback. The
     output states which. Cost is measured separately from review quality.
""")
    print(f"  Artifacts: {OUT}")
    print(f"  Tests:     python -m pytest   (from {ROOT})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
