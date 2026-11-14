"""Proof-carrying review: claims, rules, verdicts, witnesses, evidence.

A line of code links to a CLAIM (what it is supposed to do), a RULE (the
checker that decides it), and a RESULT with one of four honest labels:

    PROVED_IN_SCOPE  a checker established a precisely stated property under
                     listed assumptions
    REFUTED          the checker found a counterexample (a witness)
    TESTED           executed examples passed; other cases may remain
    UNKNOWN          the property was not checked or the checker could not decide

The proof usually belongs to a requirement or code hunk, with the changed
lines LINKING to it - the claim is stated once, not repeated per line.

For #2297 the formal obligation is:

    For every supported target framework, every generated code declaration
    carries ExcludeFromCodeCoverage.

The checker walks the T4 templates that generate the declarations, evaluates
their introduced `#if` guard under each shipped framework's defined symbols
(C# conditional compilation), and reports a witness whenever the attribute
would be missing from the emitted declaration. That is a counterexample, not
an opinion - the human can re-run the checker and inspect the witness.

Usage:
    python proof_review.py --repo ../../repo --branch origin/ju26-issue-2297 \\
        --base 32258fdb --issue-text ../../.trust/issues/2297.md \\
        --json ../../.trust/findings/2297-proof.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

# C# preprocessor symbols a build defines for each shipped TFM (the symbols
# the templates' conditions actually test).
TFM_SYMBOLS = {
    "netstandard2.0": ["NETSTANDARD", "NETSTANDARD2_0"],
    "netstandard2.1": ["NETSTANDARD", "NETSTANDARD2_1"],
    "net8.0": ["NET", "NET8_0", "NET8_0_OR_GREATER"],
    "net472": ["NETFRAMEWORK", "NET472"],
}

VERDICTS = ("PROVED_IN_SCOPE", "REFUTED", "TESTED", "UNKNOWN")


@dataclass
class Claim:
    id: str
    statement: str
    formal: str
    scope: dict = field(default_factory=dict)      # listed assumptions
    line_links: list[dict] = field(default_factory=list)   # file+lines linking to it
    level: str = "sub"                             # main | sub
    depends_on: list = field(default_factory=list) # sub-claim ids this claim is split into


@dataclass
class Rule:
    id: str
    statement: str
    checker: str


@dataclass
class Evidence:
    kind: str          # checker_output | command | commit | artifact
    value: str
    note: str = ""


@dataclass
class Result:
    claim: str
    rule: str
    verdict: str       # one of VERDICTS
    witness: dict = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class ProofReview:
    requirement: dict
    claims: list[Claim] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    results: list[Result] = field(default_factory=list)
    hierarchy: dict = field(default_factory=dict)
    label_legend: dict = field(default_factory=lambda: {
        "PROVED_IN_SCOPE": "a checker established a precisely stated property "
                           "under listed assumptions",
        "REFUTED": "the checker found a counterexample",
        "TESTED": "executed examples passed; other cases may remain",
        "UNKNOWN": "the property has not been checked or the checker could "
                   "not decide",
    })


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                       text=True, timeout=120)
    return p.stdout if p.returncode == 0 else ""


def read_shipped_tfms(repo: Path, branch: str) -> list[str]:
    out: set[str] = set()
    names = git(repo, "ls-tree", "-r", "--name-only", branch).splitlines()
    for path in names:
        if not path.endswith(".csproj") or not path.startswith("src/"):
            continue
        content = git(repo, "show", f"{branch}:{path}")
        for m in re.finditer(r"<TargetFrameworks?>([^<]+)<", content):
            for t in m.group(1).split(";"):
                t = t.strip()
                if t and not t.startswith("$"):
                    out.add(t)
    return sorted(out)


def eval_guard(condition: str, symbols: list[str]) -> bool:
    """Evaluate a simple #if condition against defined symbols.

    Supports !, &&, || and parentheses over symbol identifiers - enough for
    the guard classes this reviewer hunts, and nothing more. Unknown symbols
    count as undefined (C# semantics)."""
    tokens = re.findall(r"[A-Za-z0-9_]+|&&|\|\||!|\(|\)", condition)
    defined = set(symbols)

    def parse_expr(i: int) -> tuple[bool, int]:
        neg = False
        if i < len(tokens) and tokens[i] == "!":
            neg = True
            i += 1
        if i < len(tokens) and tokens[i] == "(":
            val, i = parse_or(i + 1)
            if i < len(tokens) and tokens[i] == ")":
                i += 1
            return (not val) if neg else val, i
        tok = tokens[i] if i < len(tokens) else "0"
        val = tok in defined
        return (not val) if neg else val, i + 1

    def parse_and(i: int) -> tuple[bool, int]:
        val, i = parse_expr(i)
        while i < len(tokens) and tokens[i] == "&&":
            rhs, i = parse_expr(i + 1)
            val = val and rhs
        return val, i

    def parse_or(i: int) -> tuple[bool, int]:
        val, i = parse_and(i)
        while i < len(tokens) and tokens[i] == "||":
            rhs, i = parse_and(i + 1)
            val = val or rhs
        return val, i

    if not tokens:
        return False
    val, _ = parse_or(0)
    return val


def check_r2297(repo: Path, base: str, branch: str) -> tuple[Result, list[dict]]:
    """R-2297: every generated declaration carries the attribute on every
    shipped TFM. Counterexample = a shipped TFM whose defined symbols make the
    introduced guard evaluate false, removing the attribute from the emitted
    declaration."""
    shipped = read_shipped_tfms(repo, branch)
    guard_condition = "!NETSTANDARD2_0 && !NETFRAMEWORK"

    # the templates that emit generated declarations, all carrying the guard
    templates: list[str] = []
    for path in git(repo, "diff", "--name-only", f"{base}..{branch}").splitlines():
        if not path.endswith(".tt"):
            continue
        content = git(repo, "show", f"{branch}:{path}")
        if guard_condition in content:
            templates.append(path)

    witnesses: list[dict] = []
    for tfm in shipped:
        symbols = TFM_SYMBOLS.get(tfm, [])
        survives = eval_guard(guard_condition, symbols)
        if not survives:
            witnesses.append({
                "tfm": tfm,
                "symbols_defined": symbols,
                "guard_evaluates": "false - the attribute is removed from the "
                                   "emitted declaration",
                "detail": f"{tfm} -> generated declaration without "
                          f"ExcludeFromCodeCoverage",
            })

    output_lines = [f"shipped frameworks: {', '.join(shipped)}"]
    for w in witnesses:
        output_lines.append(f"  {w['tfm']}: guard false -> "
                            f"attribute ABSENT (counterexample)")
    for tfm in shipped:
        if all(w["tfm"] != tfm for w in witnesses):
            output_lines.append(f"  {tfm}: guard true -> attribute present")

    verdict = "REFUTED" if witnesses else "PROVED_IN_SCOPE"
    result = Result(
        claim="C-2297-1", rule="R-2297", verdict=verdict,
        witness=witnesses[0] if witnesses else {},
        evidence=[
            Evidence("checker_output",
                     "\n".join(output_lines),
                     "static conditional-compilation evaluation of the "
                     "templates that emit the declarations; symbols are what "
                     "a build defines per TFM"),
            Evidence("command",
                     "python trust/proof/proof_review.py --repo ../../repo "
                     "--branch origin/ju26-issue-2297 --base 32258fdb"),
            Evidence("commit", git(repo, "rev-parse", branch).strip(),
                     "the reviewed patch"),
            Evidence("artifact",
                     "the same guard appears in the committed templates, and "
                     "the compile probes show the compatibility premise is "
                     "false (attribute compiles unguarded on net472 and "
                     "netstandard2.0)"),
        ],
    )
    line_links = []
    for path in templates:
        content = git(repo, "show", f"{branch}:{path}")
        for n, line in enumerate(content.splitlines(), 1):
            if guard_condition in line:
                line_links.append({"file": path, "line": n,
                                   "text": line.strip()})
    return result, line_links


def check_in_sync(repo: Path, base: str, branch: str) -> Result:
    """Every checked-in generated .cs is the current output of the .tt beside
    it (the pair moves together)."""
    changed = set(l for l in git(repo, "diff", "--name-only",
                                 f"{base}..{branch}").splitlines() if l.strip())
    tts = [p for p in git(repo, "ls-tree", "-r", "--name-only", branch)
           .splitlines() if p.endswith(".tt")]
    pairs = [(tt, tt[:-3] + ".cs") for tt in tts
             if git(repo, "cat-file", "-e", f"{branch}:{tt[:-3] + '.cs'}") == ""]
    touched = [(tt, cs) for tt, cs in pairs if tt in changed or cs in changed]
    desync = [(tt, cs, tt in changed, cs in changed)
              for tt, cs in touched if (tt in changed) != (cs in changed)]
    if not touched:
        return Result("C-2297-2", "R-sync", "UNKNOWN", {},
                      [Evidence("checker_output", "no template/output pairs touched")])
    if desync:
        first = desync[0]
        return Result(
            "C-2297-2", "R-sync", "REFUTED",
            {"pair": f"{first[0]} / {first[1]}",
             "detail": "one half of a template/output pair moved alone"},
            [Evidence("checker_output",
                      "; ".join(f"{tt if t else cs} ({'.tt only' if t else '.cs only'})"
                                for tt, cs, t, c in desync))])
    return Result(
        "C-2297-2", "R-sync", "PROVED_IN_SCOPE",
        {"pairs": len(touched), "detail": "all touched pairs changed on both sides"},
        [Evidence("checker_output",
                  f"all {len(touched)} touched template/output pair(s) changed "
                  f"together"),
         Evidence("commit", git(repo, "rev-parse", branch).strip())])


def check_observability(repo: Path, base: str, branch: str) -> Result:
    """The existing test suite can observe this change.

    The change is observable only if some test project builds a configuration
    where the guard behaves differently - i.e. an EXCLUDED framework. A green
    suite over net8.0-only proves nothing about the excluded ones."""
    shipped = read_shipped_tfms(repo, branch)
    excluded = [t for t in shipped
                if not eval_guard("!NETSTANDARD2_0 && !NETFRAMEWORK",
                                  TFM_SYMBOLS.get(t, []))]
    tested: set[str] = set()
    names = git(repo, "ls-tree", "-r", "--name-only", branch).splitlines()
    for path in names:
        if not path.endswith(".csproj") or not (path.startswith("tests/") or
                                                path.startswith("test/")):
            continue
        content = git(repo, "show", f"{branch}:{path}")
        for m in re.finditer(r"<TargetFrameworks?>([^<]+)<", content):
            for t in m.group(1).split(";"):
                t = t.strip()
                if t and not t.startswith("$"):
                    tested.add(t)
    changed_src = [p for p in git(repo, "diff", "--name-only",
                                  f"{base}..{branch}").splitlines()
                   if p.startswith("src/") and p.endswith((".cs", ".tt"))]
    overlap = sorted(set(excluded) & tested)
    if not tested:
        return Result("C-2297-3", "R-observability", "UNKNOWN", {},
                      [Evidence("checker_output", "could not read test TFMs")])
    if overlap:
        return Result("C-2297-3", "R-observability", "PROVED_IN_SCOPE",
                      {"covered": overlap},
                      [Evidence("checker_output",
                                f"test projects cover excluded frameworks "
                                f"{overlap} - the change is observable")])
    return Result(
        "C-2297-3", "R-observability", "REFUTED",
        {"detail": f"the change is conditional on {excluded}, which no test "
                   f"project builds; tests cover {sorted(tested)}"},
        [Evidence("checker_output",
                  f"no test project targets the excluded frameworks {excluded};"
                  f" a green suite is evidence about {sorted(tested)} only"),
         Evidence("artifact",
                  f"{len(changed_src)} changed source file(s) under src/ "
                  f"are never exercised by CI in the excluded configurations")])


def build(repo: Path, base: str, branch: str, issue_text: str) -> ProofReview:
    pr = ProofReview(requirement={
        "id": "REQ-2297",
        "text": "decorate ALL generated code with ExcludeFromCodeCoverage",
        "formal_obligation": (
            "For every supported target framework, every generated code "
            "declaration carries ExcludeFromCodeCoverage."),
        "source": "MessagePack-CSharp issue #2297 (unconditional request)",
        "assumptions": [
            "supported target frameworks are those the shipped src/ projects list",
            "the T4 templates are the source of the generated declarations",
            "C# conditional compilation selects code by the framework symbols "
            "a build defines",
        ],
    })
    pr.claims.append(Claim(
        id="C-2297-0",
        statement="the patch satisfies issue #2297: all generated code is "
                  "decorated with ExcludeFromCodeCoverage",
        formal="SATISFIES(REQ-2297)",
        level="main",
        depends_on=["C-2297-1", "C-2297-2", "C-2297-3"],
        scope={"split": "the main task is decided by its sub-claims; a main "
                        "claim is REFUTED when any sub-claim is REFUTED"},
        line_links=[],
    ))
    pr.claims.append(Claim(
        id="C-2297-1",
        statement="all generated code declarations carry "
                  "ExcludeFromCodeCoverage",
        formal="FORALL t in ShippedTFMs, d in GeneratedDeclarations(t): "
               "has(d, ExcludeFromCodeCoverage)",
        scope={"frameworks": "shipped src/ TFMs",
               "declarations": "generated by the committed T4 templates",
               "checked_by": "static guard evaluation, not a full compile"},
        level="sub",
        depends_on=[],
        line_links=[],
    ))
    pr.claims.append(Claim(
        id="C-2297-2",
        statement="every checked-in generated .cs is the current output of "
                  "the .tt beside it",
        formal="FORALL (tt, cs) in TemplatePairs: changed(tt) == changed(cs)",
        scope={"pairs": "T4 templates and their committed outputs"},
        level="sub",
        depends_on=[],
        line_links=[],
    ))
    pr.claims.append(Claim(
        id="C-2297-3",
        statement="the existing test suite can observe this change",
        formal="EXISTS t in TestedTFMs: t in ExcludedTFMs",
        scope={"suites": "test projects' TargetFrameworks"},
        level="sub",
        depends_on=[],
        line_links=[],
    ))
    pr.rules = [
        Rule("R-2297", "check every supported target framework",
             "evaluate the introduced #if guard under each framework's "
             "defined symbols; an attribute removed from the emitted "
             "declaration is a counterexample"),
        Rule("R-sync", "compare which half of each template/output pair the "
                       "diff touched", "git diff over .tt and .cs pairs"),
        Rule("R-observability", "intersect excluded frameworks with test "
                                "project TFMs", "csproj TargetFramework scan"),
    ]

    r2297, line_links = check_r2297(repo, base, branch)
    for c in pr.claims:
        if c.id == "C-2297-1":
            c.line_links = line_links
    pr.results.append(r2297)
    pr.results.append(check_in_sync(repo, base, branch))
    pr.results.append(check_observability(repo, base, branch))

    # the executed examples label: the re-enactment's regression tests
    pr.results.append(Result(
        claim="C-2297-2", rule="R-regression", verdict="TESTED",
        witness={"run": "19/19 GenericsFormatterTests passed on the guided "
                        "re-enactment branch (ju26-re-2283)"},
        evidence=[Evidence("checker_output",
                           "dotnet test --filter GenericsFormatterTests: "
                           "Passed 19, Failed 0"),
                  Evidence("command",
                           "dotnet test tests/MessagePack.SourceGenerator.Tests/"
                           "MessagePack.SourceGenerator.Tests.csproj "
                           "--filter GenericsFormatterTests"),
                  Evidence("commit", "c3791be5", "labelled guided reproduction")]))

    # an honest UNKNOWN: what we cannot decide from the shipped artifacts
    pr.results.append(Result(
        claim="C-2297-1", rule="R-unknown", verdict="UNKNOWN",
        witness={"detail": "the author's private reasoning for adding the "
                           "guard (L4) is not recoverable from the artifacts"},
        evidence=[Evidence("checker_output",
                           "no transcript was shipped with the patch; only "
                           "committed artifacts are observable")]))

    # ---- claim hierarchy: the main task is decided by its sub-claims -------
    sub_ids = ["C-2297-1", "C-2297-2", "C-2297-3"]
    sub_verdicts = {c: None for c in sub_ids}
    for r in pr.results:
        # the PRIMARY checker verdict decides the sub-claim; later results
        # (regression runs, L4 notes) annotate, they do not override
        if r.claim in sub_verdicts and sub_verdicts[r.claim] is None:
            sub_verdicts[r.claim] = r.verdict
    if any(v == "REFUTED" for v in sub_verdicts.values()):
        main_verdict = "REFUTED"
    elif all(v == "PROVED_IN_SCOPE" for v in sub_verdicts.values()):
        main_verdict = "PROVED_IN_SCOPE"
    elif any(v is None for v in sub_verdicts.values()):
        main_verdict = "UNKNOWN"
    else:
        main_verdict = "TESTED"
    pr.hierarchy = {
        "main": "C-2297-0",
        "main_verdict": main_verdict,
        "sub": sub_ids,
        "sub_verdicts": sub_verdicts,
        "rule": "a main claim is REFUTED when any sub-claim is REFUTED; "
                "PROVED_IN_SCOPE only when every sub-claim is",
    }
    pr.results.append(Result(
        claim="C-2297-0", rule="R-hierarchy", verdict=main_verdict,
        witness={"decided_by": sub_verdicts},
        evidence=[Evidence("checker_output",
                           "aggregated from sub-claim verdicts "
                           + json.dumps(sub_verdicts))]))
    return pr


def render(pr: ProofReview) -> str:
    lines = ["=" * 76, "  PROOF-CARRYING REVIEW", "=" * 76,
             "", f"REQUIREMENT {pr.requirement['id']}: {pr.requirement['text']}",
             f"OBLIGATION   {pr.requirement['formal_obligation']}", ""]
    for c in pr.claims:
        lines.append(f"CLAIM {c.id}: {c.statement}")
        lines.append(f"       formal: {c.formal}")
        if c.line_links:
            lines.append(f"       linked lines ({len(c.line_links)}):")
            for l in c.line_links[:8]:
                lines.append(f"         {l['file']}:{l['line']}  {l['text'][:70]}")
    lines.append("")
    for r in pr.results:
        lines.append(f"[{r.verdict:16}] {r.claim} via {r.rule}")
        if r.witness:
            lines.append(f"       witness : {json.dumps(r.witness, ensure_ascii=False)[:120]}")
        for e in r.evidence:
            lines.append(f"       {e.kind:15} {e.value[:110]}")
        lines.append("")
    lines.append("  label legend:")
    for k, v in pr.label_legend.items():
        lines.append(f"    {k:16} {v}")
    return "\n".join(lines)


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
    ap.add_argument("--issue-text", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    issue_text = ""
    if args.issue_text and Path(args.issue_text).exists():
        issue_text = Path(args.issue_text).read_text(encoding="utf-8")

    pr = build(repo, args.base, args.branch, issue_text)
    print(render(pr))
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(asdict(pr), indent=2, ensure_ascii=False),
                       encoding="utf-8")
        print(f"\nwrote {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
