"""
tfm_guard_check - falsify implementer-introduced target-framework guards.

THE ASSUMPTION CLASS
--------------------
When an agent wraps new code in a target-framework guard:

    #if !NETSTANDARD2_0 && !NETFRAMEWORK
        [SomeAttribute]
    #endif

it has asserted something it usually never says out loud:

    "this API is unavailable on the excluded target frameworks,
     and narrowing the feature to exclude them is acceptable."

Both halves are checkable, and both are frequently wrong. This is a high-yield
class because a TFM guard is **invisible to tests whenever the test projects all
target a framework where the guard passes.** The build is green, the snapshots
match, and a reviewer reading the diff sees a plausible compatibility shim.

THE CHECK
---------
  1. Find `#if` guards the diff INTRODUCED (not pre-existing convention).
  2. Extract the excluded TFM symbols from the condition.
  3. Read which TFMs the library actually SHIPS, and which the TESTS cover.
  4. Compile-probe the guarded API against the excluded TFMs. This is the
     falsification step: if it compiles, the compatibility premise is false.
  5. Report whether any existing test could observe the guard at all.

Verdicts: SUPPORTED | FALSIFIED | UNCHECKABLE.

Nothing here is an opinion. The probe either compiles or it does not, and the
command is printed so a human can re-run it.

Usage:
    python tfm_guard_check.py --repo ../../repo --branch origin/ju26-issue-2297 \
        --base 32258fdb --json ../../.trust/findings/2297-tfm-guard.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

# TFM preprocessor symbol -> a concrete TFM the SDK can build
SYMBOL_TO_TFM = {
    "NETSTANDARD2_0": "netstandard2.0",
    "NETSTANDARD2_1": "netstandard2.1",
    "NETFRAMEWORK": "net472",
    "NET472": "net472",
    "NET48": "net48",
    "NETCOREAPP": "net8.0",
    "NET8_0": "net8.0",
    "NET6_0": "net6.0",
}

GUARD_RE = re.compile(r"^\+\s*#if\s+(?P<cond>.+?)\s*$")
# a negated symbol in the condition means "excluded when that symbol is defined"
NEG_SYMBOL_RE = re.compile(r"!\s*([A-Z0-9_]+)")
ATTR_RE = re.compile(r"^\+\s*\[\s*(?P<attr>(?:global::)?[\w.]+)")


@dataclass
class Guard:
    file: str
    condition: str
    excluded_symbols: list[str]
    guarded_api: str | None
    preexisting: bool = False


@dataclass
class Probe:
    tfm: str
    api: str
    compiles: bool | None  # None means the probe did not establish availability.
    command: str
    output_tail: str = ""


@dataclass
class Finding:
    id: str
    assumption: str
    verdict: str
    severity: str = "unknown"
    guards: list[Guard] = field(default_factory=list)
    probes: list[Probe] = field(default_factory=list)
    shipped_tfms: list[str] = field(default_factory=list)
    test_tfms: list[str] = field(default_factory=list)
    affected_tfms: list[str] = field(default_factory=list)
    test_observable: bool = True
    evidence: list[str] = field(default_factory=list)
    consequence: str = ""
    verify: list[str] = field(default_factory=list)


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                       text=True, timeout=120)
    return p.stdout if p.returncode == 0 else ""


# ---------------------------------------------------------------------------
# 1-2. find introduced guards
# ---------------------------------------------------------------------------

def find_introduced_guards(repo: Path, base: str, branch: str) -> list[Guard]:
    diff = git(repo, "diff", "-U3", f"{base}..{branch}", "--", "*.cs", "*.tt")
    guards: list[Guard] = []
    cur_file = ""
    pending: Guard | None = None

    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            cur_file = line[6:]
            pending = None
            continue
        m = GUARD_RE.match(line)
        if m:
            cond = m.group("cond")
            excluded = NEG_SYMBOL_RE.findall(cond)
            if excluded:
                pending = Guard(cur_file, cond, excluded, None)
                guards.append(pending)
            continue
        if pending is not None:
            a = ATTR_RE.match(line)
            if a:
                pending.guarded_api = a.group("attr").replace("global::", "")
                pending = None
            elif line.startswith("+") and line.strip() not in ("+", "+#endif"):
                pending = None

    # dedupe by (condition, api); keep one representative file list
    seen: dict[tuple, Guard] = {}
    for g in guards:
        key = (g.condition, g.guarded_api)
        if key not in seen:
            seen[key] = g
    uniq = list(seen.values())

    # convention check: did this exact condition already exist at base?
    for g in uniq:
        hits = git(repo, "grep", "-l", "-F", f"#if {g.condition}", base)
        g.preexisting = bool(hits.strip())
    return uniq


# ---------------------------------------------------------------------------
# 3. shipped and tested TFMs
# ---------------------------------------------------------------------------

def read_tfms(repo: Path, branch: str, globs: list[str]) -> list[str]:
    out: set[str] = set()
    names = git(repo, "ls-tree", "-r", "--name-only", branch).splitlines()
    for path in names:
        if not path.endswith(".csproj"):
            continue
        if not any(path.startswith(g) for g in globs):
            continue
        content = git(repo, "show", f"{branch}:{path}")
        for m in re.finditer(r"<TargetFrameworks?>([^<]+)<", content):
            for t in m.group(1).split(";"):
                t = t.strip()
                if t and not t.startswith("$"):
                    out.add(t)
    return sorted(out)


# ---------------------------------------------------------------------------
# 4. the falsification step: compile probe
# ---------------------------------------------------------------------------

def dotnet_exe() -> str | None:
    for cand in ("dotnet", r"C:\Program Files\dotnet\dotnet.exe"):
        if shutil.which(cand) or Path(cand).exists():
            return cand
    return None


def compile_probe(api: str, tfms: list[str], workdir: Path) -> list[Probe]:
    """Does `api` resolve on each TFM with NO guard? If yes, the premise is false."""
    exe = dotnet_exe()
    probes: list[Probe] = []
    if exe is None:
        return [Probe(t, api, None, "dotnet not found", "SDK unavailable") for t in tfms]

    for tfm in tfms:
        d = workdir / f"probe_{tfm.replace('.', '_')}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "p.csproj").write_text(
            "<Project Sdk=\"Microsoft.NET.Sdk\">\n"
            f"  <PropertyGroup><TargetFramework>{tfm}</TargetFramework>\n"
            "    <Nullable>disable</Nullable><LangVersion>latest</LangVersion>\n"
            "    <EnableNETAnalyzers>false</EnableNETAnalyzers></PropertyGroup>\n"
            "</Project>\n", encoding="utf-8")
        # the attribute applied with no #if at all
        (d / "C.cs").write_text(
            f"[global::{api}]\ninternal sealed class ProbeTarget {{ }}\n", encoding="utf-8")
        cmd = f"dotnet build \"{d / 'p.csproj'}\" -v q --nologo"
        try:
            p = subprocess.run([exe, "build", str(d / "p.csproj"), "-v", "q", "--nologo"],
                               capture_output=True, text=True, timeout=300)
            output = p.stdout + p.stderr
            tail = "\n".join(output.strip().splitlines()[-8:])
            # Only a compiler diagnostic about the missing API establishes
            # unavailability. Restore, SDK and test-host errors are unknown.
            ok = (True if p.returncode == 0 else False if re.search(
                r"\berror CS(?:0234|0246|0616)\b", output) else None)
        except (OSError, subprocess.TimeoutExpired) as exc:
            ok, tail = None, f"probe failed to run: {exc}"
        probes.append(Probe(tfm, api, ok, cmd, tail))
    return probes


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------

def analyse(repo: Path, base: str, branch: str, issue_text: str | None,
            workdir: Path) -> list[Finding]:
    guards = find_introduced_guards(repo, base, branch)
    if not guards:
        return []

    shipped = read_tfms(repo, branch, ["src/"])
    tested = read_tfms(repo, branch, ["tests/", "test/"])
    findings: list[Finding] = []

    for i, g in enumerate(guards):
        excluded_tfms = sorted({
            SYMBOL_TO_TFM[s] for s in g.excluded_symbols if s in SYMBOL_TO_TFM
        })
        affected = [t for t in excluded_tfms if t in shipped]

        f = Finding(
            id=f"tfm-guard-{i}",
            assumption=(
                f"{g.guarded_api or 'the guarded API'} is unavailable on "
                f"{', '.join(excluded_tfms) or 'the excluded frameworks'}, and "
                f"narrowing the feature to exclude them is acceptable"
            ),
            verdict="UNCHECKABLE",
            guards=[g],
            shipped_tfms=shipped,
            test_tfms=tested,
            affected_tfms=affected,
        )

        if g.preexisting:
            f.evidence.append(
                f"condition '#if {g.condition}' already existed at {base[:9]} - "
                "follows a repo convention, lower suspicion")
        else:
            f.evidence.append(
                f"condition '#if {g.condition}' did NOT exist at {base[:9]} - "
                "introduced by this change, not a repo convention")

        # test observability: can any test project see the guarded-out path?
        f.test_observable = bool(set(excluded_tfms) & set(tested))
        if not f.test_observable and tested:
            f.evidence.append(
                f"no test project targets {excluded_tfms}; tests cover {tested} "
                "- the guard is always satisfied in CI, so no test can observe "
                "the excluded path")

        # the falsification
        if g.guarded_api and excluded_tfms:
            f.probes = compile_probe(g.guarded_api, excluded_tfms, workdir)
            compiles_everywhere = all(p.compiles is True for p in f.probes)
            if compiles_everywhere:
                f.verdict = "FALSIFIED"
                f.evidence.append(
                    f"{g.guarded_api} compiles unguarded on "
                    f"{', '.join(p.tfm for p in f.probes)} - the compatibility "
                    "premise for the guard is false")
            elif any(p.compiles is True for p in f.probes):
                f.verdict = "FALSIFIED"
                ok = [p.tfm for p in f.probes if p.compiles]
                f.evidence.append(
                    f"{g.guarded_api} compiles unguarded on {ok} - the guard is "
                    "broader than any real incompatibility")
            elif f.probes and all(p.compiles is False for p in f.probes):
                f.verdict = "SUPPORTED"
                f.evidence.append(
                    f"{g.guarded_api} does not compile on {excluded_tfms} - "
                    "the guard is warranted")
            else:
                f.verdict = "UNCHECKABLE"
                f.evidence.append("the compile probe did not establish API "
                                  "availability on every excluded framework")
            f.verify = [p.command for p in f.probes]

        if issue_text is not None:
            mentions = [s for s in SYMBOL_TO_TFM
                        if s.lower().replace("_", ".") in issue_text.lower()
                        or s.lower() in issue_text.lower()]
            tfm_words = ("netstandard", "net framework", ".net framework",
                         "net472", "net8.0", "tfm", "target framework")
            if not mentions and not any(w in issue_text.lower() for w in tfm_words):
                f.evidence.append(
                    "the originating issue does not mention target frameworks at "
                    "all - the conditionality was introduced by the implementer, "
                    "not requested")

        if f.verdict == "FALSIFIED" and affected:
            f.severity = "moderate" if not f.test_observable else "low"
            f.consequence = (
                f"the feature silently does not apply to {', '.join(affected)}, "
                f"which the library ships. "
                + ("No existing test can detect this: all test projects target "
                   f"{', '.join(tested)}, where the guard always passes."
                   if not f.test_observable else "")
            )
        elif f.verdict == "FALSIFIED":
            f.severity = "low"
            f.consequence = ("the guard is unnecessary but excludes no shipped "
                             "target framework")
        findings.append(f)
    return findings


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
    ap.add_argument("--issue-text", help="path to a file with the issue body")
    ap.add_argument("--probe-dir", default=None,
                    help="where to keep probe projects so --verify commands stay "
                         "runnable (default .trust/probes/<branch>)")
    ap.add_argument("--json", help="write findings here")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    issue_text = None
    if args.issue_text and Path(args.issue_text).exists():
        issue_text = Path(args.issue_text).read_text(encoding="utf-8")

    # Probe projects MUST outlive this process: a "verify yourself" command
    # pointing into a deleted temp dir is worse than no command at all.
    if args.probe_dir:
        probe_dir = Path(args.probe_dir)
    else:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", args.branch)
        probe_dir = Path(__file__).resolve().parents[2] / ".trust" / "probes" / safe
    probe_dir.mkdir(parents=True, exist_ok=True)
    findings = analyse(repo, args.base, args.branch, issue_text, probe_dir)

    if not findings:
        print("no introduced target-framework guards in this diff")
        return 0

    print(f"branch {args.branch}  base {args.base[:9]}")
    print(f"{len(findings)} introduced TFM guard(s) analysed\n")

    for f in findings:
        print("=" * 72)
        print(f"[{f.verdict}] {f.id}   severity={f.severity}")
        print(f"\n  ASSUMPTION\n    {f.assumption}")
        g = f.guards[0]
        print(f"\n  GUARD\n    #if {g.condition}")
        print(f"    api: {g.guarded_api}")
        print(f"    e.g. {g.file}")
        print(f"\n  SHIPPED tfms  {', '.join(f.shipped_tfms) or '?'}")
        print(f"  TESTED  tfms  {', '.join(f.test_tfms) or '?'}")
        print(f"  AFFECTED tfms {', '.join(f.affected_tfms) or 'none'}")
        print(f"  test-observable: {f.test_observable}")
        if f.probes:
            print("\n  COMPILE PROBE (attribute applied with no guard)")
            for p in f.probes:
                print(f"    {p.tfm:16} "
                      f"{'COMPILES' if p.compiles is True else 'API MISSING' if p.compiles is False else 'INCONCLUSIVE'}")
        print("\n  EVIDENCE")
        for e in f.evidence:
            print(f"    - {e}")
        if f.consequence:
            print(f"\n  CONSEQUENCE\n    {f.consequence}")
        if f.verify:
            print("\n  VERIFY YOURSELF")
            for v in f.verify:
                print(f"    {v}")
        print()

    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([asdict(f) for f in findings], indent=2),
                     encoding="utf-8")
        print(f"wrote {p.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
