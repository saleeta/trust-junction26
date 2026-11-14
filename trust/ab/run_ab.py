"""
run_ab - an exploratory naive-baseline vs checked-pipeline comparison.

The arms deliberately differ in base resolution and available checks. This
illustrates a failure mode; it does not measure the causal value of an author
capsule. Tieto did not provide author sessions for these branches.

  Arm A  "before"  diff + issue text + unrestricted repo reads.
                   This is a genuine PR review as practised today. It is
                   deliberately NOT a strawman: it may read anything.
                   What it lacks is a capsule - no recorded base assumption,
                   no enumerated assumption ledger, no session provenance.

  Arm B  "after"   everything Arm A has, PLUS the capsule:
                   a cross-checked base record, and the assumptions the
                   implementation rests on, each compiled to a command.

FAIRNESS
--------
Arm A gets the issue text. Denying it would make the delta "did you bother to
read the issue", which proves nothing. The delta we want to measure is "did you
capture what the author assumed".

Both arms are DETERMINISTIC analyzers, not LLM calls. That is on purpose: the
measured difference is then attributable to evidence availability rather than to
model luck, and the demo reproduces identically on stage.

Every finding from either arm goes through the same verification stage. A
finding whose check does not confirm is counted as a FALSE finding against the
arm that produced it. Neither arm grades itself.

Usage:
    python run_ab.py --repo ../../repo --branch origin/ju26-issue-2297 \
        --issue ../../.trust/issues/2297.md --json ../../.trust/ab/2297.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "assumptions"))

import base_resolver as br          # noqa: E402
import tfm_guard_check as tg        # noqa: E402

GENERATED_RE = re.compile(r"(\.g\.cs$|\.verified\.|/Resources/|\.generated\.)")
TEST_RE = re.compile(r"(^|/)(tests?|spec)/", re.I)
BUILD_RE = re.compile(r"(Directory\.(Packages|Build)\.props|\.csproj$|\.sln$|"
                      r"global\.json$|nuget\.config$)", re.I)
DOC_RE = re.compile(r"(\.md$|^doc/|/doc/)", re.I)


# ---------------------------------------------------------------------------
# instrumentation: every read is measured, so cost is counted not estimated
# ---------------------------------------------------------------------------

class Ledger:
    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self.reads: list[tuple[str, int]] = []
        self.git_calls = 0

    def git(self, *args: str) -> str:
        self.git_calls += 1
        p = subprocess.run(["git", *args], cwd=self.repo,
                           capture_output=True, text=True, timeout=120)
        out = p.stdout if p.returncode == 0 else ""
        self.reads.append((f"git {' '.join(args[:3])}", len(out)))
        return out

    def show(self, rev: str, path: str) -> str:
        return self.git("show", f"{rev}:{path}")

    def read(self, label: str, text: str) -> str:
        """Record consuming an already-materialised piece of evidence."""
        self.reads.append((label, len(text)))
        return text

    @property
    def bytes_read(self) -> int:
        return sum(n for _, n in self.reads)

    @property
    def distinct_sources(self) -> int:
        return len({label for label, _ in self.reads})


# ---------------------------------------------------------------------------
# findings
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    id: str
    title: str
    claim: str
    severity: str = "unknown"
    evidence: list[str] = field(default_factory=list)
    verify: str = ""
    # filled by the verification stage
    status: str = "UNVERIFIED"       # CONFIRMED | REJECTED | UNVERIFIED
    verify_note: str = ""
    test_invisible: bool | None = None
    from_capsule: bool = False


@dataclass
class ArmResult:
    arm: str
    has_capsule: bool
    findings: list[Finding] = field(default_factory=list)
    assumptions_checked: int = 0
    assumptions_falsified: int = 0
    base_used: str | None = None
    base_method: str = ""
    bytes_read: int = 0
    sources_read: int = 0
    git_calls: int = 0

    @property
    def confirmed(self) -> list[Finding]:
        return [f for f in self.findings if f.status == "CONFIRMED"]

    @property
    def rejected(self) -> list[Finding]:
        return [f for f in self.findings if f.status == "REJECTED"]

    @property
    def hidden(self) -> list[Finding]:
        return [f for f in self.confirmed if f.test_invisible]


# ---------------------------------------------------------------------------
# base resolution: the one input the capsule changes
# ---------------------------------------------------------------------------

def naive_base(ledger: Ledger, branch: str) -> tuple[str | None, str]:
    """What a reviewer does without a recorded base assumption: ask once,
    take the answer. This is the real-world default, and it is how this
    project's own reviewer went wrong."""
    for cand in ("origin/develop", "origin/master", "master"):
        if not ledger.git("rev-parse", "--verify", "--quiet", cand).strip():
            continue
        mb = ledger.git("merge-base", branch, cand).strip()
        if mb:
            return mb, f"merge-base with {cand} (first ref that existed)"
    return None, "unresolved"


def capsule_base(repo: Path, branch: str, expect_files: int | None):
    git = br.Git(repo)
    return br.resolve(git, branch, expect_files)


# ---------------------------------------------------------------------------
# checks available to BOTH arms (diff-driven)
# ---------------------------------------------------------------------------

def classify(paths: list[str]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {
        "generated": [], "test": [], "build": [], "doc": [], "source": []}
    for p in paths:
        if GENERATED_RE.search(p):
            buckets["generated"].append(p)
        elif TEST_RE.search(p):
            buckets["test"].append(p)
        elif BUILD_RE.search(p):
            buckets["build"].append(p)
        elif DOC_RE.search(p):
            buckets["doc"].append(p)
        else:
            buckets["source"].append(p)
    return buckets


def diff_driven_checks(ledger: Ledger, base: str, branch: str,
                       issue_text: str) -> list[Finding]:
    """Checks that need only the diff, the issue and the repo."""
    findings: list[Finding] = []
    names = [l for l in ledger.git("diff", "--name-only",
                                   f"{base}..{branch}").splitlines() if l.strip()]
    buckets = classify(names)
    ledger.read("issue text", issue_text)

    # 1. unrequested build/dependency changes - scope creep
    if buckets["build"]:
        manifests = [p for p in buckets["build"]
                     if re.search(r"Directory\.Packages\.props|nuget\.config", p, re.I)]
        if manifests:
            findings.append(Finding(
                id="scope-dependency-change",
                title="dependency manifest changed, not requested by the issue",
                claim=(f"the diff modifies {', '.join(manifests)}, which the "
                       "issue does not ask for; dependency changes in a feature "
                       "branch alter every consumer's resolved graph"),
                severity="moderate",
                evidence=[f"base used: {base[:9]}",
                          f"changed manifests: {manifests}",
                          "issue text contains no dependency request"],
                verify=f"git diff {base[:9]}..{branch} -- {manifests[0]}",
            ))

    # 2. noise ratio - reviewer drowning
    if len(names) > 50 and buckets["generated"]:
        ratio = len(buckets["generated"]) / len(names)
        if ratio > 0.5:
            findings.append(Finding(
                id="review-noise-ratio",
                title="diff dominated by generated files",
                claim=(f"{len(buckets['generated'])} of {len(names)} changed "
                       f"files are generated ({ratio:.0%}); only "
                       f"{len(buckets['source'])} are source"),
                severity="low",
                evidence=[f"generated: {len(buckets['generated'])}",
                          f"source: {len(buckets['source'])}",
                          f"test: {len(buckets['test'])}"],
                verify=f"git diff --name-only {base[:9]}..{branch} | wc -l",
            ))

    # 3. no tests added alongside a source change
    if buckets["source"] and not buckets["test"]:
        findings.append(Finding(
            id="no-test-added",
            title="source changed with no test change",
            claim=f"{len(buckets['source'])} source files changed, no test files",
            severity="low",
            evidence=[f"source: {buckets['source'][:4]}"],
            verify=f"git diff --name-only {base[:9]}..{branch}",
        ))

    return findings


# ---------------------------------------------------------------------------
# checks available ONLY to Arm B (capsule-driven)
# ---------------------------------------------------------------------------

def capsule_driven_checks(repo: Path, ledger: Ledger, base: str, branch: str,
                          issue_text: str, probe_dir: Path) -> list[Finding]:
    findings: list[Finding] = []
    for f in tg.analyse(repo, base, branch, issue_text, probe_dir):
        ledger.read(f"assumption {f.id}", json.dumps(asdict(f)))
        if f.verdict != "FALSIFIED":
            continue
        g = f.guards[0]
        findings.append(Finding(
            id=f"assumption-{f.id}",
            title=f"compatibility premise falsified: {g.guarded_api} guarded by #if {g.condition}",
            claim=(f"{g.guarded_api} compiles on at least one excluded target; "
                   "whether narrowing the requirement is acceptable is a "
                   "human decision"),
            severity=f.severity,
            evidence=f.evidence,
            verify=f.verify[0] if f.verify else "",
            test_invisible=not f.test_observable,
            from_capsule=False,  # derived from committed code, not author context
        ))
    return findings


# ---------------------------------------------------------------------------
# verification: neither arm grades itself
# ---------------------------------------------------------------------------

def verify(findings: list[Finding], repo: Path, true_base: str,
           branch: str) -> None:
    """Confirm or reject each finding against the repo.

    The decisive test for a diff-scope claim is whether the change is real
    relative to the branch's ACTUAL parent. A claim produced from a
    misresolved base evaporates here.
    """
    def git(*a: str) -> str:
        p = subprocess.run(["git", *a], cwd=repo, capture_output=True,
                           text=True, timeout=120)
        return p.stdout if p.returncode == 0 else ""

    for f in findings:
        if f.id == "scope-dependency-change":
            real = [l for l in git("diff", "--name-only", f"{true_base}..{branch}",
                                   "--", "Directory.Packages.props",
                                   "nuget.config").splitlines() if l.strip()]
            if real:
                f.status = "CONFIRMED"
                f.verify_note = f"manifest genuinely changed vs {true_base[:9]}"
            else:
                f.status = "REJECTED"
                f.verify_note = (
                    f"the manifest is IDENTICAL between {true_base[:9]} (the "
                    f"branch's real parent) and {branch}. The claim is an "
                    "artefact of a misresolved base - a false finding.")
        elif f.id.startswith("assumption-"):
            # The checker supplied the probe result. This is corroboration,
            # not an independent second verifier or a test of emitted output.
            f.status = "CONFIRMED" if f.evidence and f.verify else "UNVERIFIED"
            f.verify_note = ("compile probe confirmed API availability; "
                             "requirement impact still needs human assessment"
                             if f.status == "CONFIRMED" else
                             "probe evidence missing; finding remains unverified")
        elif f.id == "review-noise-ratio":
            n = len([l for l in git("diff", "--name-only",
                                    f"{true_base}..{branch}").splitlines() if l.strip()])
            f.status = "CONFIRMED" if n > 50 else "REJECTED"
            f.verify_note = f"{n} files changed vs real base"
            f.test_invisible = False
        elif f.id == "no-test-added":
            names = [l for l in git("diff", "--name-only",
                                    f"{true_base}..{branch}").splitlines() if l.strip()]
            b = classify(names)
            if b["test"]:
                f.status = "REJECTED"
                f.verify_note = (f"{len(b['test'])} test files DO change vs the "
                                 "real base; claim is a base artefact")
            else:
                f.status = "CONFIRMED"
                f.verify_note = "no test files change vs real base"
            f.test_invisible = False
        else:
            f.status = "UNVERIFIED"


# ---------------------------------------------------------------------------
# the arms
# ---------------------------------------------------------------------------

def run_arm_a(repo: Path, branch: str, issue_text: str) -> ArmResult:
    ledger = Ledger(repo)
    r = ArmResult(arm="A (naive baseline)", has_capsule=False)
    base, method = naive_base(ledger, branch)
    r.base_used, r.base_method = base, method
    if base:
        r.findings = diff_driven_checks(ledger, base, branch, issue_text)
    r.bytes_read = ledger.bytes_read
    r.sources_read = ledger.distinct_sources
    r.git_calls = ledger.git_calls
    return r


def run_arm_b(repo: Path, branch: str, issue_text: str, expect_files: int | None,
              probe_dir: Path) -> ArmResult:
    ledger = Ledger(repo)
    r = ArmResult(arm="B (checked pipeline)", has_capsule=False)

    rec = capsule_base(repo, branch, expect_files)
    ledger.read("base assumption record", json.dumps(rec.as_assumption()))
    r.base_used = rec.base
    r.base_method = f"{rec.method} ({rec.verdict.lower()}, oracle-checked)"
    r.assumptions_checked += 1
    if rec.as_assumption()["verdict"] == "FALSIFIED":
        r.assumptions_falsified += 1

    if rec.base:
        r.findings = diff_driven_checks(ledger, rec.base, branch, issue_text)
        cap = capsule_driven_checks(repo, ledger, rec.base, branch,
                                    issue_text, probe_dir)
        r.findings += cap
        guards = tg.find_introduced_guards(repo, rec.base, branch)
        r.assumptions_checked += len(guards)
        r.assumptions_falsified += len(cap)

    r.bytes_read = ledger.bytes_read
    r.sources_read = ledger.distinct_sources
    r.git_calls = ledger.git_calls
    return r


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def report(a: ArmResult, b: ArmResult, branch: str, true_base: str) -> None:
    print(f"\n{'=' * 74}")
    print(f"  A/B REVIEW  {branch}")
    print(f"  true base (branch's first parent): {true_base[:9]}")
    print("=" * 74)
    print("  EXPLORATORY: the arms use different checks; this is not a capsule A/B test.")

    for r in (a, b):
        print(f"\n--- Arm {r.arm}")
        print(f"    base used : {(r.base_used or 'unresolved')[:9]}  via {r.base_method}")
        if not r.findings:
            print("    findings  : none")
        for f in r.findings:
            flag = {"CONFIRMED": "[REAL ]", "REJECTED": "[FALSE]",
                    "UNVERIFIED": "[?    ]"}[f.status]
            extra = " test-invisible" if f.test_invisible else ""
            print(f"    {flag} {f.title}{extra}")
            print(f"            {f.verify_note}")

    def precision(r: ArmResult) -> str:
        n = len(r.confirmed) + len(r.rejected)
        return "n/a" if not n else f"{len(r.confirmed) / n:.0%}"

    rows = [
        ("real findings", len(a.confirmed), len(b.confirmed), "higher"),
        ("FALSE findings", len(a.rejected), len(b.rejected), "lower"),
        ("finding precision", precision(a), precision(b), "higher"),
        ("hidden problems (test-invisible)", len(a.hidden), len(b.hidden), "higher"),
        ("assumptions checked", a.assumptions_checked, b.assumptions_checked, "higher"),
        ("assumptions falsified", a.assumptions_falsified, b.assumptions_falsified, "higher"),
        ("evidence bytes loaded", a.bytes_read, b.bytes_read, "lower"),
        ("distinct sources read", a.sources_read, b.sources_read, "lower"),
        ("git calls", a.git_calls, b.git_calls, "lower"),
    ]
    w = max(len(k) for k, *_ in rows)
    print(f"\n{'=' * 74}\n  MEASURED\n{'=' * 74}")
    print(f"  {'metric'.ljust(w)}  {'Arm A':>10}  {'Arm B':>10}   better")
    print(f"  {'-' * w}  {'-' * 10}  {'-' * 10}   ------")
    for k, av, bv, better in rows:
        win = ""
        if av != bv:
            if isinstance(av, str):          # percentages
                b_wins = _pct(bv) > _pct(av)
            else:
                b_wins = (bv > av) if better == "higher" else (bv < av)
            win = "  B" if b_wins else "  A"
        print(f"  {k.ljust(w)}  {str(av):>10}  {str(bv):>10} {win}")

    # The tool reports its own losses. DESIGN.md section 5.2 predicted Arm B
    # would consume LESS context despite knowing more. On this corpus that
    # prediction is wrong, and saying so is cheaper than being caught.
    if b.bytes_read > a.bytes_read:
        print(f"\n  NOTE  Arm B loaded {b.bytes_read - a.bytes_read} more bytes "
              f"({b.bytes_read / max(a.bytes_read, 1):.2f}x).")
        print("        The checked pipeline adds probe evidence; it does not "
              "replace prior reading.\n        This result cannot measure "
              "author-context value or model token cost.")
    print()


def _pct(s) -> float:
    try:
        return float(str(s).rstrip("%"))
    except ValueError:
        return -1.0


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
    ap.add_argument("--issue", help="path to the issue text")
    ap.add_argument("--expect-files", type=int, default=None,
                    help="oracle: changed-file count from the brief")
    ap.add_argument("--json", help="write the comparison here")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    issue_text = ""
    if args.issue and Path(args.issue).exists():
        issue_text = Path(args.issue).read_text(encoding="utf-8")

    probe_dir = Path(__file__).resolve().parents[2] / ".trust" / "probes" / \
        re.sub(r"[^A-Za-z0-9._-]", "_", args.branch)
    probe_dir.mkdir(parents=True, exist_ok=True)

    # ground truth for verification, independent of either arm
    true_base = br.Git(repo).ok("rev-parse", f"{args.branch}^") or ""

    a = run_arm_a(repo, args.branch, issue_text)
    b = run_arm_b(repo, args.branch, issue_text, args.expect_files, probe_dir)

    verify(a.findings, repo, true_base, args.branch)
    verify(b.findings, repo, true_base, args.branch)

    report(a, b, args.branch, true_base)

    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "branch": args.branch, "true_base": true_base,
            "arm_a": asdict(a), "arm_b": asdict(b),
        }, indent=2), encoding="utf-8")
        print(f"wrote {p.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
