"""
Assumption blast-radius engine.

The differentiator. `tfm_guard_check` falsifies ONE assumption and reports ONE
finding. That undersells what a falsified assumption is worth: an assumption is
load-bearing, so when it falls, everything standing on it is suspect.

    assumption  ->  footprint predicate  ->  impact sites  ->  ranked hypotheses

A single falsified assumption therefore produces a *family* of pre-aimed
hypotheses, each anchored to a concrete site, rather than one prose paragraph.
That is the mechanism by which capturing the author's context multiplies a
reviewer's reach instead of merely adding a note.

ARCHITECTURE
------------
An `AssumptionClass` is a plugin with four responsibilities:

    harvest(ctx)                 -> find instances of this assumption in the diff
    check(assumption, ctx)       -> EXECUTE a falsification attempt
    footprint(assumption, ctx)   -> every site the assumption is load-bearing for
    hypotheses(a, sites, ctx)    -> ranked, pre-aimed, each citing its evidence

Only `check` may set a verdict, and it must do so by running something. The
engine never promotes a hypothesis to a finding: hypotheses stay labelled
hypotheses until an experiment confirms them (DESIGN.md section 1).

HONESTY
-------
Impact sites are *facts* (a path, a line, a target framework). Hypotheses are
*suspicions* and are rendered separately, never merged into the finding count.
`inflation_guard()` caps claimed severity at what the evidence supports.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ingest"))

import tfm_guard_check as tg   # noqa: E402

SEVERITY_ORDER = ["none", "low", "moderate", "high"]


# ---------------------------------------------------------------------------
# data model
# ---------------------------------------------------------------------------

@dataclass
class Assumption:
    id: str
    cls: str
    statement: str
    source_kind: str           # implicit_in_code | derived | stated | reconstructed
    source_ref: str = ""
    check_cmd: str = ""
    verdict: str = "UNCHECKED"  # SUPPORTED | FALSIFIED | UNCHECKABLE | UNCHECKED
    evidence: list[str] = field(default_factory=list)
    reconstructed: bool = False


@dataclass
class ImpactSite:
    """A place the assumption is load-bearing. A FACT, not a suspicion."""
    kind: str                  # file | template | snapshot | target_framework | finding
    ref: str
    why: str
    count: int = 1


@dataclass
class Hypothesis:
    """A SUSPICION, pre-aimed by a falsified assumption. Never a finding."""
    id: str
    assumption_id: str
    failure_mode: str
    rationale: str
    site: str
    strategy: str              # differential | property | boundary | stateful | static
    priority: float = 0.0
    expected_observation: str = ""
    status: str = "untested"   # untested | confirmed | refuted | inconclusive


@dataclass
class BlastRadius:
    assumption: Assumption
    sites: list[ImpactSite] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    severity: str = "none"
    test_invisible: bool = False

    @property
    def site_count(self) -> int:
        return sum(s.count for s in self.sites)


@dataclass
class Context:
    repo: Path
    base: str
    branch: str
    issue_text: str = ""
    probe_dir: Path = Path(".")
    reconstructed_capsule: bool = False

    def git(self, *args: str) -> str:
        p = subprocess.run(["git", *args], cwd=self.repo, capture_output=True,
                           text=True, timeout=180)
        return p.stdout if p.returncode == 0 else ""

    def changed(self, *pathspec: str) -> list[str]:
        args = ["diff", "--name-only", f"{self.base}..{self.branch}"]
        if pathspec:
            args += ["--", *pathspec]
        return [l for l in self.git(*args).splitlines() if l.strip()]


class AssumptionClass(Protocol):
    id: str

    def harvest(self, ctx: Context) -> list[Assumption]: ...
    def check(self, a: Assumption, ctx: Context) -> None: ...
    def footprint(self, a: Assumption, ctx: Context) -> list[ImpactSite]: ...
    def hypotheses(self, a: Assumption, sites: list[ImpactSite],
                   ctx: Context) -> list[Hypothesis]: ...


# ---------------------------------------------------------------------------
# class 1: target-framework guards
# ---------------------------------------------------------------------------

class TfmGuardAssumption:
    """'This API is unavailable on the excluded frameworks, and narrowing the
    feature to exclude them is acceptable.'"""

    id = "tfm-guard"

    def __init__(self) -> None:
        self._guards: dict[str, tg.Guard] = {}
        self._probes: dict[str, list[tg.Probe]] = {}

    def harvest(self, ctx: Context) -> list[Assumption]:
        out = []
        for i, g in enumerate(tg.find_introduced_guards(ctx.repo, ctx.base,
                                                        ctx.branch)):
            aid = f"{self.id}-{i}"
            self._guards[aid] = g
            excluded = sorted({tg.SYMBOL_TO_TFM[s] for s in g.excluded_symbols
                               if s in tg.SYMBOL_TO_TFM})
            out.append(Assumption(
                id=aid, cls=self.id,
                statement=(f"{g.guarded_api or 'the guarded API'} is unavailable "
                           f"on {', '.join(excluded) or 'the excluded frameworks'}"
                           ", and excluding them is acceptable"),
                source_kind="implicit_in_code",
                source_ref=f"{g.file}  #if {g.condition}",
                check_cmd=f"compile {g.guarded_api} unguarded on {excluded}",
                reconstructed=ctx.reconstructed_capsule,
            ))
        return out

    def check(self, a: Assumption, ctx: Context) -> None:
        g = self._guards[a.id]
        excluded = sorted({tg.SYMBOL_TO_TFM[s] for s in g.excluded_symbols
                           if s in tg.SYMBOL_TO_TFM})
        if not g.guarded_api or not excluded:
            a.verdict = "UNCHECKABLE"
            a.evidence.append("could not identify the guarded API or the "
                              "excluded frameworks")
            return

        probes = tg.compile_probe(g.guarded_api, excluded, ctx.probe_dir)
        self._probes[a.id] = probes
        ok = [p.tfm for p in probes if p.compiles]

        if g.preexisting:
            a.evidence.append(f"'#if {g.condition}' already existed at "
                              f"{ctx.base[:9]} - follows repo convention")
        else:
            a.evidence.append(f"'#if {g.condition}' did NOT exist at "
                              f"{ctx.base[:9]} - introduced by this change")

        if ok:
            a.verdict = "FALSIFIED"
            a.evidence.append(f"{g.guarded_api} compiles unguarded on "
                              f"{', '.join(ok)} - the premise is false")
            a.check_cmd = probes[0].command
        else:
            a.verdict = "SUPPORTED"
            a.evidence.append(f"{g.guarded_api} does not compile on {excluded} "
                              "- the guard is warranted")

        if ctx.issue_text and not _mentions_tfms(ctx.issue_text):
            a.evidence.append("the originating issue does not mention target "
                              "frameworks - the conditionality was not requested")

    def footprint(self, a: Assumption, ctx: Context) -> list[ImpactSite]:
        """The blast radius: everything the guard narrows."""
        g = self._guards[a.id]
        sites: list[ImpactSite] = []

        excluded = sorted({tg.SYMBOL_TO_TFM[s] for s in g.excluded_symbols
                           if s in tg.SYMBOL_TO_TFM})
        shipped = tg.read_tfms(ctx.repo, ctx.branch, ["src/"])
        for t in excluded:
            if t in shipped:
                sites.append(ImpactSite(
                    "target_framework", t,
                    "shipped by the library but excluded by the guard"))

        # every template carrying the guard
        templates = [p for p in ctx.changed("*.tt") if _has(ctx, p, g.condition)]
        for p in templates:
            sites.append(ImpactSite("template", p,
                                    "emits the guarded code into consumers"))

        # every committed snapshot that bakes the guard in
        snaps = [p for p in ctx.changed("*.g.cs") if _has(ctx, p, g.condition)]
        if snaps:
            sites.append(ImpactSite(
                "snapshot", f"{len(snaps)} verified snapshots",
                "regenerated WITH the guard, so the tests now assert the "
                "guarded output is correct", count=len(snaps)))
        return sites

    def hypotheses(self, a: Assumption, sites: list[ImpactSite],
                   ctx: Context) -> list[Hypothesis]:
        if a.verdict != "FALSIFIED":
            return []
        g = self._guards[a.id]
        tfms = [s.ref for s in sites if s.kind == "target_framework"]
        templates = [s for s in sites if s.kind == "template"]
        snaps = [s for s in sites if s.kind == "snapshot"]
        hyps: list[Hypothesis] = []

        for t in tfms:
            hyps.append(Hypothesis(
                id=f"{a.id}-h-tfm-{t}", assumption_id=a.id,
                failure_mode="feature_absent_on_target",
                rationale=(f"the guard removes {g.guarded_api} for {t}, which the "
                           f"library ships; the issue asked for it unconditionally"),
                site=t, strategy="differential", priority=3.0,
                expected_observation=(f"code generated for {t} contains no "
                                      f"{g.guarded_api}"),
            ))
        for s in snaps:
            hyps.append(Hypothesis(
                id=f"{a.id}-h-snapshot", assumption_id=a.id,
                failure_mode="test_codifies_the_gap",
                rationale=("the verified snapshots were regenerated with the "
                           "guard, so snapshot tests assert the narrowed output "
                           "is correct and can never fail on it"),
                site=s.ref, strategy="static", priority=2.5,
                expected_observation=("removing the guard makes snapshot tests "
                                      "fail, proving they pin the gap"),
            ))
        for s in templates:
            hyps.append(Hypothesis(
                id=f"{a.id}-h-tmpl-{Path(s.ref).name}", assumption_id=a.id,
                failure_mode="regeneration_drift",
                rationale=("a future regeneration propagates the guard to every "
                           "consumer of this template"),
                site=s.ref, strategy="static", priority=1.0,
                expected_observation="regenerated output still carries the guard",
            ))
        return hyps


# ---------------------------------------------------------------------------
# class 2: generated output in sync with its template
# ---------------------------------------------------------------------------

class GeneratedInSyncAssumption:
    """'The committed generated file is the output of the template beside it.'

    A T4 .tt and its checked-in .cs must move together. If only one moved, the
    next regeneration silently reverts the change - a defect no test sees,
    because the committed .cs is what gets compiled today.
    """

    id = "generated-in-sync"

    def __init__(self) -> None:
        self._pairs: dict[str, list[tuple[str, str, bool, bool]]] = {}

    def harvest(self, ctx: Context) -> list[Assumption]:
        tts = ctx.changed("*.tt")
        all_tt = [p for p in ctx.git("ls-tree", "-r", "--name-only",
                                     ctx.branch).splitlines() if p.endswith(".tt")]
        changed = set(ctx.changed())
        pairs: list[tuple[str, str, bool, bool]] = []
        for tt in all_tt:
            cs = tt[:-3] + ".cs"
            exists = bool(ctx.git("cat-file", "-e", f"{ctx.branch}:{cs}") == "") and \
                _path_exists(ctx, cs)
            if not exists:
                continue
            pairs.append((tt, cs, tt in changed, cs in changed))
        if not pairs or not tts:
            return []
        self._pairs[f"{self.id}-0"] = pairs
        return [Assumption(
            id=f"{self.id}-0", cls=self.id,
            statement=("every checked-in generated .cs is the current output of "
                       "the .tt template beside it"),
            source_kind="implicit_in_code",
            source_ref=f"{len(pairs)} template/output pairs",
            check_cmd="compare which half of each pair the diff touched",
            reconstructed=ctx.reconstructed_capsule,
        )]

    def check(self, a: Assumption, ctx: Context) -> None:
        pairs = self._pairs.get(a.id, [])
        desync = [(tt, cs, t, c) for tt, cs, t, c in pairs if t != c]
        if not pairs:
            a.verdict = "UNCHECKABLE"
            return
        if desync:
            a.verdict = "FALSIFIED"
            for tt, cs, t, c in desync:
                side = ".tt only" if t else ".cs only"
                a.evidence.append(f"{side}: {tt if t else cs}")
        else:
            a.verdict = "SUPPORTED"
            touched = [p for p in pairs if p[2] or p[3]]
            a.evidence.append(
                f"all {len(touched)} touched pair(s) changed on both sides")

    def footprint(self, a: Assumption, ctx: Context) -> list[ImpactSite]:
        if a.verdict != "FALSIFIED":
            return []
        pairs = self._pairs.get(a.id, [])
        return [ImpactSite("file", cs if t else tt,
                           "one half of a template/output pair moved alone")
                for tt, cs, t, c in pairs if t != c]

    def hypotheses(self, a: Assumption, sites: list[ImpactSite],
                   ctx: Context) -> list[Hypothesis]:
        return [Hypothesis(
            id=f"{a.id}-h-{i}", assumption_id=a.id,
            failure_mode="change_lost_on_regeneration",
            rationale=("template and committed output disagree; regenerating "
                       "overwrites the hand-side and silently drops the change"),
            site=s.ref, strategy="differential", priority=3.0,
            expected_observation="re-running the generator changes this file",
        ) for i, s in enumerate(sites)]


# ---------------------------------------------------------------------------
# class 3: existing tests can observe the change
# ---------------------------------------------------------------------------

class TestObservabilityAssumption:
    """'The existing test suite can observe this change.'

    Falsified when the changed code is only active under a configuration no
    test project builds. Every changed source file then becomes an impact site:
    a green suite says nothing about any of them.
    """

    id = "test-observability"

    def __init__(self) -> None:
        self._excluded: dict[str, list[str]] = {}

    def harvest(self, ctx: Context) -> list[Assumption]:
        guards = tg.find_introduced_guards(ctx.repo, ctx.base, ctx.branch)
        if not guards:
            return []
        excluded = sorted({tg.SYMBOL_TO_TFM[s] for g in guards
                           for s in g.excluded_symbols if s in tg.SYMBOL_TO_TFM})
        if not excluded:
            return []
        self._excluded[f"{self.id}-0"] = excluded
        return [Assumption(
            id=f"{self.id}-0", cls=self.id,
            statement="the existing test suite can observe this change",
            source_kind="derived",
            source_ref=f"change is conditional on {excluded}",
            check_cmd="intersect excluded frameworks with test project TFMs",
            reconstructed=ctx.reconstructed_capsule,
        )]

    def check(self, a: Assumption, ctx: Context) -> None:
        excluded = self._excluded.get(a.id, [])
        tested = tg.read_tfms(ctx.repo, ctx.branch, ["tests/", "test/"])
        overlap = sorted(set(excluded) & set(tested))
        if not tested:
            a.verdict = "UNCHECKABLE"
            a.evidence.append("could not read test project target frameworks")
            return
        if overlap:
            a.verdict = "SUPPORTED"
            a.evidence.append(f"test projects cover {overlap}")
        else:
            a.verdict = "FALSIFIED"
            a.evidence.append(
                f"no test project targets {excluded}; tests cover {tested}. "
                "A green suite is evidence about one configuration only.")

    def footprint(self, a: Assumption, ctx: Context) -> list[ImpactSite]:
        if a.verdict != "FALSIFIED":
            return []
        src = [p for p in ctx.changed()
               if p.endswith((".cs", ".tt")) and not p.endswith(".g.cs")
               and p.startswith("src/")]
        return [ImpactSite("file", p, "changed source under an untested "
                                      "configuration") for p in src]

    def hypotheses(self, a: Assumption, sites: list[ImpactSite],
                   ctx: Context) -> list[Hypothesis]:
        if not sites:
            return []
        return [Hypothesis(
            id=f"{a.id}-h-suite", assumption_id=a.id,
            failure_mode="green_suite_proves_nothing",
            rationale=(f"{len(sites)} changed source file(s) are only exercised "
                       "under configurations the suite does not build"),
            site=f"{len(sites)} files under src/", strategy="differential",
            priority=2.0,
            expected_observation=("building the excluded configuration reveals "
                                  "behaviour the suite never checks"),
        )]


# ---------------------------------------------------------------------------
# class 4: claims the change wrote into documentation
# ---------------------------------------------------------------------------

class DocumentedClaimAssumption:
    """A STATED assumption: a factual claim the agent added to the docs.

    This is the purest form of the hallucination problem. An implicit guard is
    at least silent; a documented claim actively tells future readers something
    the code cannot support. No test in any repository reads a README, so a
    false sentence here survives indefinitely and is cited by humans as truth.

    Harvests sentences added to docs that assert an availability or support
    constraint, then falsifies them with the same compile probe used for guards.
    """

    id = "documented-claim"

    AVAILABILITY_RE = re.compile(
        r"(only (?:emitted|applied|available|added|generated)|not available|"
        r"unavailable|unsupported|does not support|where it is available|"
        r"not supported (?:on|in|for))", re.I)
    TFM_RE = re.compile(
        r"(netstandard\s*2\.\d|net\s*framework|netframework|net4\d\d|"
        r"net\s*8\.0|net\s*6\.0)", re.I)

    def __init__(self) -> None:
        self._claims: dict[str, tuple[str, str, list[str], str]] = {}

    def harvest(self, ctx: Context) -> list[Assumption]:
        out: list[Assumption] = []
        docs = [p for p in ctx.changed() if p.lower().endswith((".md", ".txt"))
                or "/doc/" in p.lower() or p.lower().startswith("doc/")]
        n = 0
        for path in docs:
            diff = ctx.git("diff", f"{ctx.base}..{ctx.branch}", "--", path)
            added = [l[1:].strip() for l in diff.splitlines()
                     if l.startswith("+") and not l.startswith("+++")]
            block = chr(10).join(added)
            for body in added:
                if not body or not self.AVAILABILITY_RE.search(body):
                    continue
                tfms = sorted({_norm_tfm(m) for m in self.TFM_RE.findall(body)})
                tfms = [t for t in tfms if t]
                if not tfms:
                    continue
                aid = f"{self.id}-{n}"
                n += 1
                api = _guess_api(body, ctx) or _guess_api(block, ctx)
                self._claims[aid] = (path, body, tfms, block)
                out.append(Assumption(
                    id=aid, cls=self.id,
                    statement=f'documentation asserts: "{body[:160]}"',
                    source_kind="stated",
                    source_ref=f"{path} (added by this change)",
                    check_cmd=f"compile {api or 'the API'} on {tfms}",
                    reconstructed=ctx.reconstructed_capsule,
                ))
        return out

    def check(self, a: Assumption, ctx: Context) -> None:
        path, body, tfms, block = self._claims[a.id]
        api = _guess_api(body, ctx) or _guess_api(block, ctx)
        if not api:
            a.verdict = "UNCHECKABLE"
            a.evidence.append("could not identify which API the sentence is "
                              "about; reported rather than dropped")
            return
        probes = tg.compile_probe(api, tfms, ctx.probe_dir)
        ok = [p.tfm for p in probes if p.compiles]
        a.evidence.append(f'the sentence was ADDED to {path} by this change')
        if ok:
            a.verdict = "FALSIFIED"
            a.evidence.append(
                f"{api} compiles on {', '.join(ok)}, so the documented "
                "availability constraint is factually wrong")
            a.evidence.append("no test reads documentation, so this claim "
                              "cannot be caught by the suite")
            a.check_cmd = probes[0].command
        else:
            a.verdict = "SUPPORTED"
            a.evidence.append(f"{api} genuinely does not compile on {tfms}")

    def footprint(self, a: Assumption, ctx: Context) -> list[ImpactSite]:
        if a.verdict != "FALSIFIED":
            return []
        path, body, tfms, _ = self._claims[a.id]
        sites = [ImpactSite("documentation", path,
                            "ships a factually false statement to readers")]
        for t in tfms:
            sites.append(ImpactSite("target_framework", t,
                                    "named in the false claim"))
        return sites

    def hypotheses(self, a: Assumption, sites: list[ImpactSite],
                   ctx: Context) -> list[Hypothesis]:
        if a.verdict != "FALSIFIED":
            return []
        path, body, tfms, _ = self._claims[a.id]
        return [Hypothesis(
            id=f"{a.id}-h-doc", assumption_id=a.id,
            failure_mode="false_documented_constraint",
            rationale=("the change documents an availability limit that does "
                       "not exist, which will be read as justification for the "
                       "feature gap and repeated by maintainers"),
            site=path, strategy="static", priority=3.5,
            expected_observation=("the named API compiles on the frameworks the "
                                  "sentence excludes"),
        )]


def _norm_tfm(raw: str) -> str:
    t = re.sub(r"\s+", "", raw).lower()
    if t.startswith("netstandard2."):
        return f"netstandard{t[len('netstandard'):]}"
    if t in ("netframework", "net.netframework") or "framework" in t:
        return "net472"
    if re.fullmatch(r"net4\d\d", t):
        return "net472"
    if re.fullmatch(r"net\d\.\d", t):
        return t
    return ""


def _guess_api(sentence: str, ctx: Context) -> str | None:
    """Pull the API the sentence is about: a backticked/bracketed attribute."""
    for m in re.finditer(r"[`\[]+\s*(?:global::)?([\w.]*[A-Z]\w+)\s*[`\]]+",
                         sentence):
        name = m.group(1)
        if "." in name:
            return name
        for g in tg.find_introduced_guards(ctx.repo, ctx.base, ctx.branch):
            if g.guarded_api and name.removesuffix("Attribute") in g.guarded_api:
                return g.guarded_api
    return None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _mentions_tfms(text: str) -> bool:
    t = text.lower()
    words = ("netstandard", "netframework", ".net framework", "net framework",
             "net472", "net48", "net8.0", "net6.0", "tfm", "target framework")
    return any(w in t for w in words)


def _has(ctx: Context, path: str, needle: str) -> bool:
    return needle in ctx.git("show", f"{ctx.branch}:{path}")


def _path_exists(ctx: Context, path: str) -> bool:
    return bool(ctx.git("ls-tree", "--name-only", f"{ctx.branch}", path).strip())


def inflation_guard(br: BlastRadius) -> str:
    """Cap severity at what the evidence actually supports.

    Blast radius is seductive: 222 impact sites feels like a catastrophe. It is
    not. Severity is driven by what is DEMONSTRATED, and site count only
    modulates within that ceiling.
    """
    a = br.assumption
    if a.verdict != "FALSIFIED":
        return "none"

    shipped_hit = any(s.kind == "target_framework" for s in br.sites)
    lost_change = any(h.failure_mode == "change_lost_on_regeneration"
                      for h in br.hypotheses)

    false_doc = any(h.failure_mode == "false_documented_constraint"
                    for h in br.hypotheses)
    if false_doc:
        ceiling = "moderate"       # a false sentence shipped to readers
    elif lost_change:
        ceiling = "moderate"       # a silently reverted fix, still not a crash
    elif shipped_hit:
        ceiling = "moderate"       # a real feature gap on shipped targets
    else:
        ceiling = "low"            # unnecessary, but nothing shipped is affected

    # test-invisibility raises confidence that it will survive, not the harm
    if br.test_invisible and ceiling == "low" and br.site_count > 50:
        ceiling = "low"
    return ceiling


# ---------------------------------------------------------------------------
# the engine
# ---------------------------------------------------------------------------

DEFAULT_CLASSES: list = [TfmGuardAssumption, DocumentedClaimAssumption,
                         GeneratedInSyncAssumption, TestObservabilityAssumption]


def run(ctx: Context, classes: Iterable | None = None) -> list[BlastRadius]:
    out: list[BlastRadius] = []
    for cls in (classes if classes is not None else DEFAULT_CLASSES):
        inst = cls() if isinstance(cls, type) else cls
        for a in inst.harvest(ctx):
            inst.check(a, ctx)
            sites = inst.footprint(a, ctx)
            hyps = inst.hypotheses(a, sites, ctx)
            br = BlastRadius(assumption=a, sites=sites, hypotheses=hyps)
            tested = tg.read_tfms(ctx.repo, ctx.branch, ["tests/", "test/"])
            excluded = [s.ref for s in sites if s.kind == "target_framework"]
            br.test_invisible = bool(excluded) and not (set(excluded) & set(tested))
            br.severity = inflation_guard(br)
            br.hypotheses.sort(key=lambda h: -h.priority)
            out.append(br)
    out.sort(key=lambda b: (-SEVERITY_ORDER.index(b.severity), -b.site_count))
    return out


def render(results: list[BlastRadius], show_supported: bool = True) -> str:
    L: list[str] = []
    fal = [b for b in results if b.assumption.verdict == "FALSIFIED"]
    sup = [b for b in results if b.assumption.verdict == "SUPPORTED"]
    unk = [b for b in results if b.assumption.verdict in ("UNCHECKABLE", "UNCHECKED")]

    L.append("=" * 76)
    L.append(f"  ASSUMPTION LEDGER   {len(results)} harvested   "
             f"{len(fal)} falsified   {len(sup)} supported   "
             f"{len(unk)} uncheckable")
    L.append("=" * 76)

    for b in fal:
        a = b.assumption
        tag = " [RECONSTRUCTED CAPSULE]" if a.reconstructed else ""
        L.append("")
        L.append(f"[FALSIFIED] {a.id}   severity={b.severity}{tag}")
        L.append(f"  ASSUMPTION  {a.statement}")
        L.append(f"  SOURCE      {a.source_kind}: {a.source_ref}")
        L.append("  EVIDENCE (established facts)")
        for e in a.evidence:
            L.append(f"    - {e}")
        if b.sites:
            L.append(f"  BLAST RADIUS  {b.site_count} impact site(s) "
                     f"[facts, not claims]")
            for s in b.sites:
                n = f" x{s.count}" if s.count > 1 else ""
                L.append(f"    {s.kind:17} {s.ref}{n}")
                L.append(f"    {'':17} {s.why}")
        if b.hypotheses:
            L.append(f"  PRE-AIMED HYPOTHESES  {len(b.hypotheses)} "
                     f"[UNVERIFIED - suspicions, not findings]")
            for h in b.hypotheses:
                L.append(f"    ({h.priority:.1f}) {h.failure_mode}  "
                         f"<{h.strategy}>  status={h.status}")
                L.append(f"          site: {h.site}")
                L.append(f"          why : {h.rationale}")
                L.append(f"          expect: {h.expected_observation}")
        if a.check_cmd:
            L.append(f"  VERIFY      {a.check_cmd}")

    if show_supported and sup:
        L.append("")
        L.append("-" * 76)
        L.append("  SUPPORTED assumptions (checked, held up - the agent got these right)")
        for b in sup:
            L.append(f"    [OK] {b.assumption.id}: {b.assumption.statement}")
            for e in b.assumption.evidence[-1:]:
                L.append(f"         {e}")

    if unk:
        L.append("")
        L.append("  UNCHECKABLE (reported, not dropped)")
        for b in unk:
            L.append(f"    [?] {b.assumption.id}: {b.assumption.statement}")

    L.append("")
    L.append("  Confirmed findings and unverified hypotheses are listed")
    L.append("  separately above and are never combined into one score.")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    import argparse
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
    ap.add_argument("--issue-text")
    ap.add_argument("--reconstructed", action="store_true",
                    help="mark the capsule as reconstructed, not authentic")
    ap.add_argument("--json")
    args = ap.parse_args(argv)

    issue = ""
    if args.issue_text and Path(args.issue_text).exists():
        issue = Path(args.issue_text).read_text(encoding="utf-8")

    probe_dir = Path(__file__).resolve().parents[2] / ".trust" / "probes" / \
        re.sub(r"[^A-Za-z0-9._-]", "_", args.branch)
    probe_dir.mkdir(parents=True, exist_ok=True)

    ctx = Context(repo=Path(args.repo).resolve(), base=args.base,
                  branch=args.branch, issue_text=issue, probe_dir=probe_dir,
                  reconstructed_capsule=args.reconstructed)
    results = run(ctx)
    print(render(results))

    if args.json:
        p = Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([asdict(b) for b in results], indent=2),
                     encoding="utf-8")
        print(f"\nwrote {p.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
