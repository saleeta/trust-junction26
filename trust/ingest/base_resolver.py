"""
base_resolver - resolve a branch's true base commit, and record it as a
*checked assumption* rather than a silent default.

WHY THIS EXISTS
---------------
This module encodes a real failure that happened during this project. Reviewing
the four agentic branches, the resolution used was:

    git merge-base <branch> origin/develop  ||  git merge-base <branch> master

`origin/develop` does not exist in that fork, so the fallback fired silently and
returned 524fd55e - two commits earlier than the branch's actual parent,
32258fdb. Every diff taken from there included two pre-existing dependency
commits, which were then attributed to the AI agents. The resulting finding was
confident, cited a real commit, and was false.

The lesson is not "use first-parent". It is that **base resolution is an
assumption, and an unrecorded assumption is where hallucinations come from.**
So this resolver:

  1. computes the base several independent ways,
  2. reports when they disagree instead of picking a winner quietly,
  3. validates against an external oracle when one is available,
  4. returns a record with a verdict that downstream stages must carry.

Usage:
    python base_resolver.py --repo ../../repo --branch origin/ju26-issue-2283
    python base_resolver.py --repo ../../repo --all-ju26 --expect-files 2283=4,2234=4,2129=28,2297=237
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

DEFAULT_BRANCH_CANDIDATES = ("origin/develop", "origin/master", "origin/main",
                             "develop", "master", "main")


class Git:
    def __init__(self, repo: Path) -> None:
        self.repo = repo
        if not (repo / ".git").exists():
            raise SystemExit(f"not a git repository: {repo}")

    def run(self, *args: str) -> tuple[int, str]:
        p = subprocess.run(["git", *args], cwd=self.repo,
                           capture_output=True, text=True, timeout=60)
        return p.returncode, p.stdout.strip()

    def ok(self, *args: str) -> str | None:
        code, out = self.run(*args)
        return out if code == 0 and out else None

    def exists(self, ref: str) -> bool:
        return self.ok("rev-parse", "--verify", "--quiet", ref) is not None

    def subject(self, rev: str) -> str:
        return self.ok("show", "-s", "--format=%s", rev) or "?"

    def changed_files(self, a: str, b: str) -> int:
        out = self.ok("diff", "--name-only", f"{a}..{b}")
        return len([l for l in (out or "").splitlines() if l.strip()])


@dataclass
class Candidate:
    method: str
    sha: str | None
    note: str = ""


@dataclass
class BaseRecord:
    """A base resolution, carrying its own evidence and verdict."""
    branch: str
    base: str | None
    base_subject: str = ""
    method: str = ""
    verdict: str = "UNRESOLVED"      # CONFIRMED | DISPUTED | UNRESOLVED
    candidates: list[Candidate] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    oracle: dict = field(default_factory=dict)
    verify: str = ""

    def as_assumption(self) -> dict:
        """The form trust.assumptions consumes (DESIGN.md section 4)."""
        return {
            "id": f"base::{self.branch}",
            "statement": f"the base of {self.branch} is {(self.base or 'unknown')[:9]}",
            "source": {"kind": "derived", "module": "trust.ingest.base_resolver"},
            "check": self.verify,
            "verdict": {"CONFIRMED": "SUPPORTED", "DISPUTED": "FALSIFIED",
                        "UNRESOLVED": "UNCHECKABLE"}[self.verdict],
            "evidence": "; ".join(
                f"{c.method}={(c.sha or 'none')[:9]}" for c in self.candidates
            ),
            "consequence": (
                "diffs, fingerprints and every downstream finding are computed "
                "from this commit; an error here silently misattributes "
                "pre-existing changes to the agent"
            ),
        }


def resolve(git: Git, branch: str, expect_files: int | None = None) -> BaseRecord:
    rec = BaseRecord(branch=branch, base=None)

    if not git.exists(branch):
        rec.warnings.append(f"branch {branch!r} does not exist")
        return rec

    # --- method 1: first parent. What the branch was actually built on.
    first_parent = git.ok("rev-parse", "--verify", "--quiet", f"{branch}^")
    rec.candidates.append(Candidate("first_parent", first_parent))

    # --- method 2: merge-base against each default-branch candidate that EXISTS.
    # The original bug was treating a missing ref as a reason to fall through
    # silently. Here a missing ref is recorded, not skipped.
    for cand in DEFAULT_BRANCH_CANDIDATES:
        if not git.exists(cand):
            rec.candidates.append(Candidate(f"merge_base[{cand}]", None, "ref does not exist"))
            continue
        mb = git.ok("merge-base", branch, cand)
        rec.candidates.append(Candidate(f"merge_base[{cand}]", mb))

    # --- method 3: fork-point, when the reflog supports it
    for cand in DEFAULT_BRANCH_CANDIDATES:
        if git.exists(cand):
            fp = git.ok("merge-base", "--fork-point", cand, branch)
            if fp:
                rec.candidates.append(Candidate(f"fork_point[{cand}]", fp))
            break

    # A base equal to the branch tip yields an empty diff, which downstream
    # reads as "no changes to review" - a silent failure worse than an error.
    # A base that is not an ancestor of the tip is meaningless too.
    tip = git.ok("rev-parse", branch)
    rejected: list[Candidate] = []
    for c in rec.candidates:
        if not c.sha:
            continue
        if tip and c.sha == tip:
            c.note = "equals the branch tip - would produce an empty diff"
            rejected.append(c)
        elif git.ok("merge-base", "--is-ancestor", c.sha, branch) is None and \
                subprocess.run(["git", "merge-base", "--is-ancestor", c.sha, branch],
                               cwd=git.repo, capture_output=True).returncode != 0:
            c.note = "not an ancestor of the branch"
            rejected.append(c)

    real = [c for c in rec.candidates if c.sha and c not in rejected]
    if not real:
        rec.warnings.append(
            "no method produced a usable base commit"
            + (f" ({len(rejected)} candidate(s) rejected: "
               + "; ".join(f"{c.method} {c.note}" for c in rejected) + ")"
               if rejected else ""))
        return rec

    # first_parent is authoritative for "what did the agent branch from",
    # because it is the commit the agent's own commit points at.
    chosen = next((c for c in real if c.method == "first_parent"), real[0])
    rec.base = chosen.sha
    rec.method = chosen.method
    rec.base_subject = git.subject(chosen.sha)
    rec.verify = f"git rev-parse {branch}^"

    distinct = {c.sha for c in real}
    if len(distinct) > 1:
        rec.verdict = "DISPUTED"
        disagreeing = sorted(
            f"{c.method}={c.sha[:9]}" for c in real if c.sha != rec.base
        )
        rec.warnings.append(
            "methods disagree - this is the condition that produced a false "
            "finding in this project. Disagreeing: " + ", ".join(disagreeing)
        )
    else:
        rec.verdict = "CONFIRMED"

    # --- external oracle: the challenge brief states the file count per branch.
    if expect_files is not None:
        actual = git.changed_files(rec.base, branch)
        rec.oracle = {
            "expected_changed_files": expect_files,
            "actual_changed_files": actual,
            "agrees": actual == expect_files,
            "source": "challenge brief",
        }
        if actual == expect_files:
            # An independent oracle outranks internal disagreement.
            rec.verdict = "CONFIRMED"
            rec.warnings.append(
                f"oracle confirms base: {actual} changed files matches the brief"
            )
        else:
            rec.verdict = "DISPUTED"
            rec.warnings.append(
                f"oracle REJECTS base: brief says {expect_files} files, "
                f"this base yields {actual}"
            )
    return rec


def parse_expect(spec: str | None) -> dict[str, int]:
    if not spec:
        return {}
    out: dict[str, int] = {}
    for part in spec.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = int(v)
    return out


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--branch", action="append", default=[])
    ap.add_argument("--all-ju26", action="store_true",
                    help="resolve every origin/ju26-issue-* branch")
    ap.add_argument("--expect-files", help="e.g. 2283=4,2234=4,2129=28,2297=237")
    ap.add_argument("--json", help="write records to this path")
    args = ap.parse_args(argv)

    git = Git(Path(args.repo).resolve())
    expect = parse_expect(args.expect_files)

    branches = list(args.branch)
    if args.all_ju26:
        _, out = git.run("for-each-ref", "--format=%(refname:short)",
                         "refs/remotes/origin/ju26-issue-*")
        branches += [b for b in out.splitlines() if b.strip()]
    if not branches:
        raise SystemExit("pass --branch or --all-ju26")

    records: list[BaseRecord] = []
    for b in branches:
        key = next((k for k in expect if k in b), None)
        rec = resolve(git, b, expect.get(key) if key else None)
        records.append(rec)

        mark = {"CONFIRMED": "OK", "DISPUTED": "DISPUTED", "UNRESOLVED": "FAIL"}[rec.verdict]
        print(f"\n{b}")
        print(f"  base     {(rec.base or 'unknown')[:9]}  {rec.base_subject[:58]}")
        print(f"  method   {rec.method}")
        print(f"  verdict  [{mark}]")
        if rec.oracle:
            o = rec.oracle
            print(f"  oracle   brief={o['expected_changed_files']} "
                  f"actual={o['actual_changed_files']} "
                  f"{'agrees' if o['agrees'] else 'REJECTS'}")
        for w in rec.warnings:
            print(f"  ! {w}")
        print(f"  verify   {rec.verify}")
        shown = {c.sha for c in rec.candidates if c.sha}
        if len(shown) > 1:
            for c in rec.candidates:
                if c.sha and c.sha != rec.base:
                    print(f"    alt    {c.method:28} {c.sha[:9]}  {git.subject(c.sha)[:40]}")

    disputed = [r for r in records if r.verdict != "CONFIRMED"]
    print(f"\n{len(records)} branch(es): {len(records)-len(disputed)} confirmed, "
          f"{len(disputed)} needing a human")

    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(
            {"records": [asdict(r) for r in records],
             "assumptions": [r.as_assumption() for r in records]},
            indent=2), encoding="utf-8")
        print(f"wrote {p.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
