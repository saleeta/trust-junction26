"""
llm_arm - the LLM reviewer arms, with honest token telemetry.

The deterministic arms in `run_ab.py` stay, because they reproduce identically
on stage. This module adds the arms that actually answer the context-cost
question, because token cost only means something when a model is consuming the
context.

THREE STRATEGIES, SAME QUESTION
-------------------------------
  full           dump the entire diff + issue into the prompt
  full-triaged   dump the diff MINUS generated files + issue
                 (a competent reviewer's first move - not a strawman)
  recall         ask the graph store for cited snippets within a budget

WHY THIS IS THE HONEST TEST
---------------------------
`run_ab.py` measured Arm B loading MORE bytes than Arm A and said so. That
result stands for deterministic analyzers, where the capsule adds records and
replaces no reading. The claim worth testing is different: when a MODEL must be
given context, does targeted retrieval cost less than dumping the diff? Prompt
tokens are countable locally, so that comparison needs no API key and no
sampling luck - `--dry-run` measures it exactly.

The API key is needed only to judge finding QUALITY. Cost and quality are
reported separately and never conflated: a cheap arm that finds nothing is not
winning.

Usage:
    python llm_arm.py --repo ../../repo --branch origin/ju26-issue-2297 \\
        --base 32258fdb --db ../../.trust/memory.db --dry-run
    python llm_arm.py ... --live --model claude-sonnet-5-5
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "memory"))

import recall as rc   # noqa: E402

GENERATED_RE = re.compile(r"(\.g\.cs$|\.verified\.|/Resources/)")

REVIEW_PROMPT = """You are reviewing a change made by an AI coding agent.

The change implements this issue:
<issue>
{issue}
</issue>

Here is the evidence available to you:
<evidence>
{evidence}
</evidence>

Report defects that a human should act on. For each one state:
  - the claim, in one sentence
  - the concrete evidence from the material above that supports it
  - a command or test that would confirm it

Rules:
  - Only claim what the evidence above supports. If you are uncertain, label it
    a hypothesis rather than a finding.
  - Prefer defects that existing tests would NOT catch.
  - If you find nothing worth a human's time, say so plainly.
"""


@dataclass
class ArmCost:
    strategy: str
    prompt_tokens: int
    evidence_tokens: int
    hits: int = 0
    dropped: int = 0
    citations: bool = False
    estimated: bool = True
    # live only
    completion_tokens: int = 0
    api_prompt_tokens: int = 0
    response: str = ""
    error: str = ""

    @property
    def total_tokens(self) -> int:
        return (self.api_prompt_tokens or self.prompt_tokens) + self.completion_tokens


# ---------------------------------------------------------------------------
# evidence assembly
# ---------------------------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                       text=True, timeout=600)
    return p.stdout if p.returncode == 0 else ""


def evidence_full(repo: Path, base: str, branch: str,
                  triaged: bool = False) -> tuple[str, int]:
    names = [l for l in git(repo, "diff", "--name-only",
                            f"{base}..{branch}").splitlines() if l.strip()]
    kept = [p for p in names if not (triaged and GENERATED_RE.search(p))]
    chunks = []
    for p in kept:
        chunks.append(git(repo, "diff", f"{base}..{branch}", "--", p))
    if triaged:
        skipped = len(names) - len(kept)
        if skipped:
            chunks.append(f"\n[{skipped} generated/snapshot files omitted by "
                          f"triage]\n")
    return "\n".join(chunks), len(kept)


def evidence_recall(store: rc.Store, questions: list[str],
                    budget: int) -> tuple[str, rc.Recall, int]:
    """Spend the budget across several questions, de-duplicating hits."""
    per = max(1, budget // max(1, len(questions)))
    seen: set[str] = set()
    blocks: list[str] = []
    total_used = 0
    dropped = 0
    last: rc.Recall | None = None
    for q in questions:
        r = store.recall(q, mode="question", budget_tokens=per)
        last = r
        dropped += r.hits_dropped_for_budget
        for h in r.hits:
            key = f"{h.kind}:{h.ref}"
            if key in seen:
                continue
            seen.add(key)
            blocks.append(h.render())
            total_used += h.tokens
    merged = "\n\n".join(blocks)
    assert last is not None
    last.tokens_used = total_used
    last.hits = last.hits        # keep shape
    return merged, last, len(seen)


# ---------------------------------------------------------------------------
# the arms
# ---------------------------------------------------------------------------

QUESTIONS = [
    "falsified assumption about target framework availability or guards",
    "documented claim added to the README about availability or support",
    "which target frameworks do the tests cover versus the library ships",
    "template and generated output changed together or separately",
]


def build_arms(repo: Path, base: str, branch: str, issue: str,
               db: Path | None, budget: int) -> list[ArmCost]:
    arms: list[ArmCost] = []

    for name, triaged in (("full", False), ("full-triaged", True)):
        ev, nfiles = evidence_full(repo, base, branch, triaged)
        prompt = REVIEW_PROMPT.format(issue=issue, evidence=ev)
        arms.append(ArmCost(
            strategy=name,
            prompt_tokens=rc.count_tokens(prompt),
            evidence_tokens=rc.count_tokens(ev),
            hits=nfiles, citations=False, estimated=rc._ESTIMATED))

    if db and Path(db).exists():
        store = rc.Store(db)
        ev, last, nhits = evidence_recall(store, QUESTIONS, budget)
        prompt = REVIEW_PROMPT.format(issue=issue, evidence=ev)
        arms.append(ArmCost(
            strategy="recall",
            prompt_tokens=rc.count_tokens(prompt),
            evidence_tokens=rc.count_tokens(ev),
            hits=nhits, dropped=last.hits_dropped_for_budget,
            citations=True, estimated=rc._ESTIMATED))
        store.close()
    return arms


def run_live(arms: list[ArmCost], repo: Path, base: str, branch: str,
             issue: str, db: Path | None, budget: int, model: str) -> None:
    try:
        from anthropic import Anthropic  # type: ignore
    except ImportError:
        for a in arms:
            a.error = "anthropic package not installed"
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        for a in arms:
            a.error = "ANTHROPIC_API_KEY not set"
        return

    client = Anthropic()
    for a in arms:
        if a.strategy == "recall":
            if not (db and Path(db).exists()):
                a.error = "no store"
                continue
            store = rc.Store(db)
            ev, _, _ = evidence_recall(store, QUESTIONS, budget)
            store.close()
        else:
            ev, _ = evidence_full(repo, base, branch,
                                  a.strategy == "full-triaged")
        prompt = REVIEW_PROMPT.format(issue=issue, evidence=ev)
        try:
            resp = client.messages.create(
                model=model, max_tokens=2000,
                messages=[{"role": "user", "content": prompt}])
            a.response = "".join(
                b.text for b in resp.content if getattr(b, "type", "") == "text")
            a.api_prompt_tokens = resp.usage.input_tokens
            a.completion_tokens = resp.usage.output_tokens
            a.estimated = False
        except Exception as exc:          # noqa: BLE001
            a.error = f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def report(arms: list[ArmCost], branch: str, live: bool) -> None:
    print("=" * 78)
    print(f"  LLM CONTEXT COST   {branch}")
    print("=" * 78)
    # Be precise about where the numbers come from. tiktoken is exact for its
    # own tokenizer but only an APPROXIMATION for Claude, and saying otherwise
    # would overstate the measurement.
    if live and any(a.api_prompt_tokens for a in arms):
        note = "token counts are EXACT - reported by the Anthropic API"
    elif rc._ESTIMATED:
        note = ("token counts are ROUGH ESTIMATES (ceil(chars/4)); "
                "install tiktoken or use --live for better numbers")
    else:
        note = ("token counts come from tiktoken cl100k_base: exact for that "
                "tokenizer, APPROXIMATE for Claude. Use --live for exact "
                "Anthropic counts. Ratios between strategies are reliable; "
                "absolute values are not.")
    print(f"  {note}\n")

    w = 14
    print(f"  {'strategy'.ljust(w)} {'prompt tok':>11} {'evidence tok':>13} "
          f"{'items':>7} {'cited':>6}")
    print(f"  {'-' * w} {'-' * 11} {'-' * 13} {'-' * 7} {'-' * 6}")
    for a in arms:
        print(f"  {a.strategy.ljust(w)} {a.prompt_tokens:>11} "
              f"{a.evidence_tokens:>13} {a.hits:>7} "
              f"{('yes' if a.citations else 'no'):>6}")

    base_arm = next((a for a in arms if a.strategy == "full"), None)
    triaged = next((a for a in arms if a.strategy == "full-triaged"), None)
    recall_arm = next((a for a in arms if a.strategy == "recall"), None)

    if base_arm and recall_arm and base_arm.prompt_tokens:
        print(f"\n  recall vs full         "
              f"{1 - recall_arm.prompt_tokens / base_arm.prompt_tokens:.1%} fewer "
              f"prompt tokens "
              f"({base_arm.prompt_tokens / max(recall_arm.prompt_tokens, 1):.0f}x)")
    if triaged and recall_arm and triaged.prompt_tokens:
        delta = 1 - recall_arm.prompt_tokens / triaged.prompt_tokens
        verdict = "fewer" if delta > 0 else "MORE"
        print(f"  recall vs full-triaged {abs(delta):.1%} {verdict} prompt tokens")
        print("  (full-triaged is the fair baseline: a competent reviewer drops\n"
              "   generated files before reading anything)")

    if live:
        print(f"\n{'=' * 78}\n  LIVE FINDINGS\n{'=' * 78}")
        for a in arms:
            print(f"\n--- {a.strategy}")
            if a.error:
                print(f"    skipped: {a.error}")
                continue
            print(f"    tokens: {a.api_prompt_tokens} in / "
                  f"{a.completion_tokens} out")
            print("    " + (a.response or "").strip()[:1500].replace("\n", "\n    "))
    else:
        print("\n  Cost measured; finding QUALITY not measured in --dry-run.")
        print("  A cheap arm that finds nothing is not winning. Use --live to")
        print("  compare what each strategy actually reports.")
    print()


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--branch", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--issue")
    ap.add_argument("--db", default=None)
    ap.add_argument("--budget", type=int, default=2500)
    ap.add_argument("--live", action="store_true",
                    help="actually call the model (needs ANTHROPIC_API_KEY)")
    ap.add_argument("--dry-run", action="store_true", default=False)
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    issue = ""
    if args.issue and Path(args.issue).exists():
        issue = Path(args.issue).read_text(encoding="utf-8")

    repo = Path(args.repo).resolve()
    db = Path(args.db) if args.db else None
    arms = build_arms(repo, args.base, args.branch, issue, db, args.budget)

    live = args.live and not args.dry_run
    if live:
        run_live(arms, repo, args.base, args.branch, issue, db, args.budget,
                 args.model)

    report(arms, args.branch, live)

    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([asdict(a) for a in arms], indent=2),
                     encoding="utf-8")
        print(f"wrote {p.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
