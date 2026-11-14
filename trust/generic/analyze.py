"""
analyze.py - proof-carrying review for ANY git repository, in ANY language.

    python trust/generic/analyze.py https://github.com/OWNER/REPO --pr 123
    python trust/generic/analyze.py https://github.com/OWNER/REPO/pull/123
    python trust/generic/analyze.py /path/to/local/repo --base main --head my-branch
    python trust/generic/analyze.py <repo> --pr 123 --run            # also run the project's own tests
    python trust/generic/analyze.py <repo> --pr 123 --run --spec claims.json
    python trust/generic/analyze.py <repo> --pr 123 --check G1       # re-run ONE claim

WHY THIS IS LANGUAGE-INDEPENDENT
--------------------------------
Nothing here needs a compiler. It uses only things every repository has: git
history, file text, and a test suite (if any). Three tiers, each labelled:

  static    read from the text. (changed symbols, who mentions them, which tests
            mention them). Assumptions are listed on every verdict.
  induced   a pattern seen in past commits ("these two files usually change
            together"). ALWAYS reported as Unknown: a deviation is a lead for a
            human, never a proof of a defect.
  executed  only with --run: the project's own test command, plus any
            `--spec` command oracles you write. Exit code decides the verdict.

Only `executed` claims can be Tested, and only a counterexample can be Refuted.
Everything that cannot be decided stays Unknown and is handed to a person.

SAFETY: without --run nothing from the target repository is ever executed.
--run executes the repository's own test command on this machine.
Use it only on code you would run anyway, or inside a container.
"""
from __future__ import annotations
import argparse, io, json, os, re, shutil, subprocess, sys, tarfile, tempfile, urllib.request
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
from logic import *      # noqa

CLONES = ROOT / ".trust" / "_clones"
GH = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/pull/(\d+).*|/)?$")

RULES = {
    "R-RUN": "A claim is only Tested or Refuted because something was executed.",
    "R-STATIC": "A claim about the code text can be refuted by a counterexample found in the text, under listed assumptions.",
    "R-HIST": "Earlier changes to the same files are evidence about what this change should also touch.",
    "R-CALL": "If a function changes, every function that mentions it is a place to look; they are listed, not assumed broken.",
    "R-DOC": "A sentence in the docs makes a claim that no test reads.",
    "R-HUMAN": "Questions of intent cannot be decided by code. They go to a person.",
}
STOP = {"main", "init", "test", "tests", "setup", "teardown", "get", "set", "run", "new", "name", "value", "data", "index",
        "item", "list", "add", "close", "open", "read", "write", "load", "save", "parse", "build", "create", "update",
        "delete", "call", "apply", "handle", "start", "stop", "next", "self", "this", "args", "result", "error"}
SKIP_FILE = re.compile(r"(^|/)(node_modules|vendor|dist|build|\.git|third_party)/|\.(lock|min\.js|map|svg|png|jpe?g|gif|pdf|zip|snap|ico)$|"
                       r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|go\.sum|Cargo\.lock)$")
TEST_FILE = re.compile(r"(^|/)(tests?|spec|specs|__tests__|e2e|testing)(/|$)|(_test|\.test|\.spec|Tests?|Spec)\.\w+$|(^|/)test_\w+")
DOC_FILE = re.compile(r"\.(md|rst|txt|adoc)$", re.I)
ABSOLUTE = re.compile(r"\b(never|always|only|must|every|all|guarantee[sd]?|cannot|exactly|at most|at least|no longer|is safe|thread[- ]safe)\b", re.I)
IMPORT = re.compile(r"^\s*(from\s+\S+\s+import\b|import\b|using\b|use\b|#\s*include\b|require\b|export\s*\{|.*=\s*require\()")
DEF = [re.compile(p) for p in (
    r"^\s*(?:async\s+)?def\s+(\w+)",                                                        # python, ruby
    r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\*?\s+(\w+)",                   # js, ts, php
    r"^\s*(?:export\s+)?(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>",
    r"^\s*func\s+(?:\([^)]*\)\s*)?(\w+)",                                                   # go
    r"^\s*(?:pub(?:\([\w:]+\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+(\w+)",                 # rust
    r"^\s*fun\s+(\w+)",                                                                      # kotlin
    r"^\s*(?:(?:public|private|protected|internal|static|final|override|virtual|async|abstract|sealed|extern)\s+)+[\w<>\[\]?,.\s]+?\s+(\w+)\s*\(",  # java, c#
    r"^\s*(?:class|struct|interface|trait|enum)\s+(\w+)",
    r"^[A-Za-z_][\w\s\*&:<>,]*[\s\*&](\w+)\s*\([^;]*\)\s*\{?\s*$",                          # c, c++
)]


# ------------------------------------------------------------------ git plumbing
def sh(args, cwd, timeout=300, check=False):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(args[:4])}...: {r.stderr.strip()[:300]}")
    return r


def git(repo, *a, check=False, timeout=300):
    return sh(["git", *a], repo, timeout, check).stdout


def resolve_repo(spec: str, pr: int | None):
    """-> (local path, display name, pr number or None). Refuses anything that is not a github https URL or a local dir."""
    m = GH.match(spec)
    if m:
        owner, name, urlpr = m.group(1), m.group(2), m.group(3)
        pr = pr or (int(urlpr) if urlpr else None)
        dest = CLONES / f"{owner}__{name}"
        CLONES.mkdir(parents=True, exist_ok=True)
        url = f"https://github.com/{owner}/{name}.git"
        if not dest.exists():
            print(f"cloning {url} (depth 300) ...", file=sys.stderr)
            sh(["git", "clone", "--quiet", "--no-tags", "--depth", "300", url, str(dest)], CLONES, 900, True)
        return dest, f"{owner}/{name}", pr
    p = Path(spec)
    if p.is_dir() and (p / ".git").exists():
        return p.resolve(), p.resolve().name, pr
    sys.exit(f"not a github.com https URL or a local git repository: {spec!r}")


def sha(repo, ref):
    r = sh(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], repo)
    return r.stdout.strip() or None


def github_pr_meta(owner_repo: str, pr: int) -> dict:
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{owner_repo}/pulls/{pr}",
                                     headers={"User-Agent": "trust-review", "Accept": "application/vnd.github+json"})
        return json.load(urllib.request.urlopen(req, timeout=20))
    except Exception as e:
        print(f"(could not read PR metadata from the GitHub API: {e})", file=sys.stderr)
        return {}


def find_base(repo, head, base_sha):
    """True merge-base, or refuse. A wrong base silently blames the PR for other people's changes."""
    for _ in range(4):
        mb = git(repo, "merge-base", base_sha, head).strip()
        if mb:
            return mb, ""
        sh(["git", "fetch", "--quiet", "--deepen", "400", "origin"], repo, 600)
    sys.exit("could not find a true merge-base within the fetched history; refusing to guess (a wrong base misattributes changes)")


# ------------------------------------------------------------------ code reading
def enclosing(lines, lineno):
    for i in range(min(lineno, len(lines)) - 1, max(-1, lineno - 450), -1):
        for rx in DEF:
            m = rx.match(lines[i])
            if m and m.group(1) not in {"if", "for", "while", "switch", "return", "catch", "else"}:
                return m.group(1), i + 1
    return None, None


def parse_diff(repo, base, head):
    out, cur = {}, None
    for line in git(repo, "diff", "-U0", "--no-color", "--no-ext-diff", base, head).splitlines():
        if line.startswith("+++ "):
            path = line[4:]
            cur = None if path == "/dev/null" else path[2:]
            if cur and not SKIP_FILE.search(cur):
                out[cur] = {"added": {}, "removed": 0}
            else:
                cur = None
        elif line.startswith("--- ") or not cur:
            continue
        elif (m := re.match(r"@@ -\S+ \+(\d+)(?:,(\d+))? @@", line)):
            nl = int(m.group(1))
        elif line.startswith("+"):
            out[cur]["added"][nl] = line[1:]; nl += 1
        elif line.startswith("-"):
            out[cur]["removed"] += 1
    return out


class Ctx:
    def __init__(self, repo, base, head):
        self.repo, self.base, self.head = repo, base, head
        self._txt = {}

    def text(self, path, rev=None):
        k = (path, rev or self.head)
        if k not in self._txt:
            self._txt[k] = git(self.repo, "show", f"{rev or self.head}:{path}").splitlines()
        return self._txt[k]

    def refs(self, sym):
        """Whole-word text matches of `sym` at head: [(path, lineno, text)]."""
        r = sh(["git", "grep", "-n", "-w", "-F", "-I", "--no-color", "-e", sym, self.head, "--"], self.repo, 120)
        out = []
        for l in r.stdout.splitlines()[:600]:
            m = re.match(r"^[0-9a-f]{40}:(.+?):(\d+):(.*)$", l)
            if m and not SKIP_FILE.search(m.group(1)):
                out.append((m.group(1), int(m.group(2)), m.group(3)))
        return out


def is_def_of(text, sym):
    return any((m := rx.match(text)) and m.group(1) == sym for rx in DEF)


# ------------------------------------------------------------------ analysis
def run_project_tests(root: Path, timeout=600):
    """-> (cmd, returncode, output) or None if no runner is recognised."""
    f = lambda n: (root / n).exists()
    pj = (root / "package.json").read_text(encoding="utf-8", errors="replace") if f("package.json") else ""
    if f("go.mod"): cmd = ["go", "test", "./..."]
    elif f("Cargo.toml"): cmd = ["cargo", "test", "--quiet"]
    elif any(root.glob("*.sln")) or any(root.glob("**/*.csproj")): cmd = ["dotnet", "test", "--nologo", "-v", "q"]
    elif f("pom.xml"): cmd = ["mvn", "-q", "test"]
    elif f("package.json") and '"test"' in pj: cmd = ["npm", "test", "--silent"]
    elif f("pytest.ini") or f("pyproject.toml") or f("setup.cfg") or f("tox.ini") or (root / "tests").is_dir():
        cmd = [sys.executable, "-m", "pytest", "-x", "-q"]
    else:
        return None
    cmd[0] = shutil.which(cmd[0]) or cmd[0]
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return cmd, r.returncode, (r.stdout + r.stderr)
    except FileNotFoundError:
        return cmd, 127, f"{cmd[0]}: command not found"
    except subprocess.TimeoutExpired:
        return cmd, 124, f"timed out after {timeout}s"


def export(repo, rev) -> Path:
    raw = subprocess.run(["git", "archive", rev], cwd=repo, capture_output=True).stdout
    d = Path(tempfile.mkdtemp(prefix="trust_run_"))
    tarfile.open(fileobj=io.BytesIO(raw)).extractall(d)
    return d


def analyze(spec, pr=None, base=None, head=None, run=False, specfile=None, label=None) -> dict:
    repo, name, pr = resolve_repo(spec, pr)
    meta, base_note = {}, ""
    if pr and GH.match(spec):
        sh(["git", "fetch", "--quiet", "--depth", "300", "origin", f"pull/{pr}/head:refs/trust/pr-{pr}"], repo, 600, True)
        head_sha = sha(repo, f"refs/trust/pr-{pr}")
        meta = github_pr_meta(name, pr)
        bsha = (meta.get("base") or {}).get("sha")
        if bsha:
            sh(["git", "fetch", "--quiet", "--depth", "300", "origin", bsha], repo, 600)
        base_sha, base_note = find_base(repo, head_sha, bsha or "origin/HEAD")
    else:
        head_sha = sha(repo, head or "HEAD")
        base_sha = sha(repo, base) if base else sha(repo, f"{head_sha}~1")
        if not (head_sha and base_sha):
            sys.exit("could not resolve --base/--head to commits")
        if base:
            base_sha = git(repo, "merge-base", base_sha, head_sha).strip() or base_sha
    ctx = Ctx(repo, base_sha, head_sha)
    title = meta.get("title") or git(repo, "log", "-1", "--format=%s", head_sha).strip()
    diff = parse_diff(repo, base_sha, head_sha)
    if not diff:
        sys.exit("the change touches no analysable files")
    files = sorted(diff, key=lambda p: -len(diff[p]["added"]))[:8]
    langs = Counter(Path(p).suffix or "(none)" for p in diff)

    # ---- symbols changed (per file, by pattern; language-agnostic heuristic)
    sym_of_line, symbols = {}, {}
    for p in files:
        lines = ctx.text(p)
        for ln, txt in diff[p]["added"].items():
            s, dl = (txt and next(((m.group(1), ln) for rx in DEF if (m := rx.match(txt))), (None, None))) or (None, None)
            if not s:
                s, dl = enclosing(lines, ln)
            if s:
                sym_of_line[(p, ln)] = s
                symbols.setdefault(s, (p, dl or ln))
    traceable, too_common = [], []
    refs_of = {}
    for s in symbols:
        if len(s) < 4 or s.lower() in STOP:
            continue
        refs_of[s] = ctx.refs(s)
        (too_common if len({r[0] for r in refs_of[s]}) > 60 else traceable).append(s)
    traceable = traceable[:12]

    # ---- tests that mention each changed symbol
    test_refs = {s: sorted({r[0] for r in refs_of[s] if TEST_FILE.search(r[0])}) for s in traceable}

    # ---- callers (textual), hop 1 and hop 2
    hop1, hop2 = {}, {}
    def scan(sym, into, exclude):
        for p, ln, txt in refs_of.get(sym) or ctx.refs(sym):
            if TEST_FILE.search(p) or is_def_of(txt, sym) or IMPORT.match(txt):
                continue
            cs, _ = enclosing(ctx.text(p), ln)
            key = (p, cs or "<module>")
            if key in exclude or (cs == sym):
                continue
            into.setdefault(key, (sym, ln))
    for s in traceable:
        scan(s, hop1, set())
    hop1 = dict(list(sorted(hop1.items()))[:6])
    for (p, cs), _ in list(hop1.items()):
        if cs != "<module>" and len(cs) >= 4 and cs.lower() not in STOP and len(hop2) < 6:
            refs_of[cs] = refs_of.get(cs) or ctx.refs(cs)
            if len({r[0] for r in refs_of[cs]}) <= 60:
                scan(cs, hop2, set(hop1))
    hop2 = dict(list(sorted(hop2.items()))[:4])

    # ---- history: earlier commits and co-change (induced)
    earlier, cochange = {}, []
    for p in files[:6]:
        out = git(repo, "log", "--name-only", "--no-merges", "-n", "30", "--format=@%H|%s", base_sha, "--", p)
        commits = [c for c in out.split("@") if c.strip()]
        sets = []
        for c in commits:
            head_line, *fl = c.strip().splitlines()
            h, subj = head_line.split("|", 1)
            fl = [x for x in fl if x.strip()]
            earlier.setdefault(h[:8], (subj, set()))[1].add(p)
            if len(fl) <= 25:
                sets.append(set(fl))
        if len(sets) >= 4:
            cnt = Counter(g for s in sets for g in s if g != p)
            for g, n in cnt.items():
                if n / len(sets) >= 0.6 and g not in diff and not SKIP_FILE.search(g) and sha(repo, f"{head_sha}:{g}") is not None \
                        or (n / len(sets) >= 0.6 and g not in diff and not SKIP_FILE.search(g) and sh(["git", "cat-file", "-e", f"{head_sha}:{g}"], repo).returncode == 0):
                    cochange.append((p, g, n, len(sets)))
    cochange = sorted(set(cochange), key=lambda x: -x[2] / x[3])[:4]
    earlier_items = sorted(earlier.items(), key=lambda kv: -len(kv[1][1]))[:5]

    # ---- claims
    C = []   # dict(id, short, rule, claim, origin, plain, formula|None, label, ..., tier, stage, chain)
    def claim(**k):
        k.setdefault("witnesses", []); k.setdefault("assumptions", []); k.setdefault("note", ""); k.setdefault("checked", 0)
        k.setdefault("chain", []); k.setdefault("example", ""); k.setdefault("scope_note", "")
        C.append(k); return k

    if traceable:
        dom = Domain("CHANGED_SYMBOLS", traceable, True,
                     "symbols are extracted by pattern (not a parser); 'mentions' means a whole-word text match in a test file")
        v = check(Forall("s", dom, Pred("a test file mentions s", lambda e: bool(test_refs[e["s"]]))))
        ex = f"No test file mentions `{v.witnesses[0]['s']}`, so a green build says nothing about it." if v.witnesses else ""
        claim(id="G1", short="tests mention what changed", rule="R-STATIC", tier="static", stage=1,
              claim="Every symbol this change touches is mentioned by at least one test file.",
              origin="derived from the diff and a text search of the repository",
              plain="Does anything in the test suite even mention the code this change touches?", example=ex,
              formula=v.formula, label=v.label, witnesses=v.witnesses, assumptions=v.assumptions, checked=v.checked)
    else:
        claim(id="G1", short="tests mention what changed", rule="R-STATIC", tier="static", stage=1,
              claim="Every symbol this change touches is mentioned by at least one test file.",
              origin="derived from the diff", plain="Does anything in the test suite mention the changed code?",
              formula="∀ s ∈ CHANGED_SYMBOLS. a test file mentions s", label=UNKNOWN,
              note="no changed symbol could be extracted by pattern (config/data/doc files, or an unfamiliar syntax)")
    if cochange:
        rows = [f"{p} changed; {g} changed alongside it in {n} of the last {m} commits" for p, g, n, m in cochange]
        claim(id="G2", short="usual companions also changed", rule="R-HIST", tier="induced", stage=2,
              claim="Files that usually change together with these files were also considered.",
              origin="co-change rate over the last 30 commits touching each file (before the PR's base)",
              plain="In the past, certain files nearly always changed together with these. This change left them out.",
              formula="∀ (f,g) ∈ HABITUAL_PAIRS. g ∈ CHANGED", label=UNKNOWN,
              note="induced from history: " + "; ".join(rows) + ". A deviation, not a defect: ask the author.",
              witnesses=[{"file": p, "usually_with": g, "rate": f"{n}/{m}"} for p, g, n, m in cochange])
    docs = [(p, ln, t.strip()) for p in diff if DOC_FILE.search(p) for ln, t in diff[p]["added"].items() if ABSOLUTE.search(t)][:3]
    for i, (p, ln, t) in enumerate(docs, 1):
        claim(id=f"H{i}", short=f"doc: {t[:28]}…", rule="R-DOC", tier="static", stage=1,
              claim=f'{p}:{ln} says: "{t[:140]}"', origin=f"sentence added in {p}",
              plain="A sentence with an absolute word (never/always/only/…) was added. No test reads documentation.",
              formula="doc_claim ⇒ code_behaviour", label=UNKNOWN,
              note="no automatic checker can verify a prose claim; a person (or a --spec command) must.")
    ci = 0
    for (p, cs), (sym, ln) in list(hop1.items()) + list(hop2.items()):
        ci += 1
        hops = 1 if (p, cs) in hop1 else 2
        root = sym if hops == 1 else hop1_of(sym, hop1)   # the changed symbol this chain starts from
        claim(id=f"K{ci}", short=f"{cs}() still correct", rule="R-CALL", tier="static", stage=3,
              claim=f"{cs}() in {p} keeps behaving correctly after {root}() changed.",
              origin=f"{cs}() mentions `{sym}` at {p}:{ln} (text match, {hops} hop{'s' if hops > 1 else ''} from the change)",
              plain=f"{cs}() uses code this change touches. It is a place to look, not a proven problem.",
              formula=f"behaviour({cs}) preserved", label=UNKNOWN, chain=([root, cs] if hops == 1 else [root, sym, cs]),
              note="no checker available: listed because it mentions the changed code. Add a --spec command to test it.")

    run_info = {"ran": False}
    if run:
        wt_head = export(repo, head_sha)
        res = run_project_tests(wt_head)
        if res is None:
            claim(id="T1", short="project tests pass", rule="R-RUN", tier="executed", stage=2,
                  claim="The project's own tests pass on the changed code.", origin="project test runner",
                  plain="Run the repository's own tests.", formula="tests(head) pass", label=UNKNOWN,
                  note="no recognised test runner (looked for go, cargo, dotnet, maven, npm, pytest)")
        else:
            cmd, rc, out = res
            run_info = {"ran": True, "cmd": " ".join(cmd), "rc": rc}
            tail = "\n".join(out.strip().splitlines()[-25:])
            if rc == 0:
                label, note, wit = TESTED, "", []
            elif rc in (124, 127) or "No module named" in out or "Cannot find module" in out or "not recognized" in out:
                label, note, wit = UNKNOWN, f"could not run (environment): {tail[-300:]}", []
            else:
                wb = run_project_tests(export(repo, base_sha))
                if wb and wb[1] != 0:
                    label, note, wit = UNKNOWN, "tests also fail on the PR's base, so the failure is not attributable to this change", []
                else:
                    label, note, wit = REFUTED, "", [{"command": " ".join(cmd), "exit": rc, "output_tail": tail}]
            claim(id="T1", short="project tests pass", rule="R-RUN", tier="executed", stage=2,
                  claim="The project's own tests pass on the changed code.", origin=f"`{' '.join(cmd)}` at {head_sha[:8]}",
                  plain="Run the repository's own tests.", formula="tests(head) pass", label=label, note=note, witnesses=wit,
                  scope_note="A pass means these tests passed once, on this machine. Other inputs may still fail.")
        if specfile:
            for sp in json.loads(Path(specfile).read_text(encoding="utf-8")):
                r = subprocess.run(sp["command"], shell=True, cwd=wt_head / sp.get("cwd", "."), capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=sp.get("timeout", 300))
                ok = r.returncode == sp.get("expect", 0)
                claim(id=sp["id"], short=sp.get("short", sp["claim"][:34]), rule="R-RUN", tier="executed", stage=2,
                      claim=sp["claim"], origin=f"your spec: `{sp['command']}`", plain=sp.get("plain", sp["claim"]),
                      formula=f"exit({sp['command']}) = {sp.get('expect', 0)}", label=TESTED if ok else REFUTED,
                      witnesses=[] if ok else [{"exit": r.returncode, "output_tail": "\n".join((r.stdout + r.stderr).strip().splitlines()[-15:])}],
                      scope_note="The command passed on this checkout once; other inputs may still fail.")
    claim(id="U1", short="the change is what was intended", rule="R-HUMAN", tier="human", stage=2,
          claim="This change does what its author and the requirement intended.", origin=f'PR title: "{title[:80]}"',
          plain="Whether the change matches the intent behind it is a human judgement.",
          formula="intended(change)", label=UNKNOWN, note="a question of intent; code cannot decide it.")

    for c in C:
        c["n_witnesses"] = len(c["witnesses"])
        c["command"] = f"python trust/generic/analyze.py {spec} " + (f"--pr {pr} " if pr else f"--base {base or ''} --head {head or ''} ") + f"--check {c['id']}"

    # ---- viewer data
    nodes, edges = [], []
    pr_label = f"PR #{pr}" if pr else head_sha[:8]
    nodes.append(("HEAD", pr_label, title[:30], "cur", 0, 0))
    short = lambda p: p if len(p) <= 30 else "…" + p[-29:]
    for p in files[:6]:
        sy = sorted({s for (f, _), s in sym_of_line.items() if f == p})[:3]
        nodes.append((f"f:{p}", short(p), ", ".join(sy)[:30] or "changed", "code", 1, 0)); edges.append(("HEAD", f"f:{p}", "touch", 0))
    for h, (subj, fs) in earlier_items:
        nodes.append((f"c:{h}", h, subj[:26], "pr", 0, 2))
        for p in fs:
            if f"f:{p}" in {n[0] for n in nodes}:
                edges.append((f"c:{h}", f"f:{p}", "hist", 2))
    tests_seen = sorted({t for s in traceable for t in test_refs[s]})[:3]
    for t in tests_seen:
        nodes.append((f"t:{t}", short(t), "mentions changed code", "code", 1, 2))
    for p, g, n, m in cochange[:2]:
        nid = f"s:{g}"
        if nid not in {x[0] for x in nodes}:
            nodes.append((nid, short(g), "usual companion", "code", 1, 2))
    for (p, cs), _ in list(hop1.items()) + list(hop2.items()):
        nodes.append((f"k:{p}:{cs}", f"{cs}()", short(p), "code", 1, 3))
    for c in C:
        nodes.append((c["id"], f"{c['id']} {c['short']}", "", "claim", 2, c["stage"]))
    for c in C:
        nodes.append(("V" + c["id"], c["label"], c["id"], "ver", 3, 4))
        edges.append((c["id"], "V" + c["id"], "verdict", 4))
    ids = {n[0] for n in nodes}
    def edge(a, b, t, s):
        if a in ids and b in ids: edges.append((a, b, t, s))
    for p in files[:6]:
        if any(c["id"] == "G1" for c in C):
            edge(f"f:{p}", "G1", "claim", 1)
        for c in C:
            if c["id"].startswith("H") and c["claim"].startswith(p):
                edge(f"f:{p}", c["id"], "claim", 1)
    for t in tests_seen:
        edge(f"t:{t}", "G1", "claim", 2)
    for p, g, n, m in cochange[:2]:
        edge(f"s:{g}", "G2", "domain", 2)
        for h, (_, fs) in earlier_items:
            edge(f"c:{h}", "G2", "hist", 2)
    for (p, cs), (sym, ln) in hop1.items():
        src = symbols.get(sym, (None,))[0]
        edge(f"f:{src}", f"k:{p}:{cs}", "calls", 3)
    for (p, cs), (sym, ln) in hop2.items():
        for (p1, c1) in hop1:
            if c1 == sym:
                edge(f"k:{p1}:{c1}", f"k:{p}:{cs}", "calls", 3)
    for i, ((p, cs), _) in enumerate(list(hop1.items()) + list(hop2.items()), 1):
        edge(f"k:{p}:{cs}", f"K{i}", "claim", 3)

    # ---- code view: changed lines with 1 line of context, first three files
    fv = {}
    for p in files[:3]:
        lines = ctx.text(p)
        want = set()
        for ln in diff[p]["added"]:
            want |= {ln - 1, ln, ln + 1}
        rows = []
        for ln in sorted(x for x in want if 1 <= x <= len(lines))[:90]:
            sym = sym_of_line.get((p, ln))
            cl = []
            if ln in diff[p]["added"]:
                if sym in traceable and any(c["id"] == "G1" for c in C): cl.append("G1")
                cl += [c["id"] for c in C if c["id"].startswith("K") and c["chain"] and c["chain"][0] == sym][:2]
                cl += [c["id"] for c in C if c["id"].startswith("H") and c["claim"].startswith(f"{p}:{ln}")]
            rows.append({"n": ln, "text": lines[ln - 1], "changed": ln in diff[p]["added"], "claims": cl})
        fv[p] = rows

    n_ref = sum(1 for c in C if c["label"] == REFUTED)
    story = (f"<h1>Proof-carrying review — {name}{f' · PR #{pr}' if pr else ''}</h1><p><b>{title}</b><br>"
             f"{len(diff)} files analysed ({', '.join(f'{k}×{v}' for k, v in langs.most_common(5))}). "
             f"Nothing from the repository was executed{'' if not run_info['ran'] else ' except its own test command'}. "
             f"Step through to see how the review grows from the diff to its history and to the code that mentions it.</p>")
    caps = [
        ["1. Just the diff", f"<b>What a reviewer sees:</b> {len(diff)} changed files. <span class=q>Question: what does this change quietly rely on?</span> With the diff alone there is nothing to label: <b>0 findings</b>."],
        ["2. Claims in the diff", "The change <b>makes claims</b> (amber): that its symbols are tested, and any absolute sentence it adds to the docs. Not checked yet, so unlabeled."],
        ["3. Look back at history", f"<b>History is evidence.</b> {len(earlier_items)} earlier commits touched these files, and {len(cochange)} file(s) habitually change with them. The graph pulls them in (<span style='color:#7b8fe0'>dashed</span>). Habits are <b>induced</b>, so they stay Unknown: leads, not proof."],
        ["4. Look deeper: who mentions it?", f"A text search finds <b>{len(hop1)}</b> place(s) that mention the changed code and <b>{len(hop2)}</b> that mention <i>those</i> (<span style='color:#e879f9'>pink</span>). These are listed to look at, not assumed broken."],
        ["5. Labels", f"Each claim ends <b>Refuted</b> (counterexample in the text or a failing run), <b>Tested</b>, <b>Proved within scope</b>, or <b>Unknown</b>. Here: <b>{n_ref}</b> refuted. The human decision stays <b>pending</b>."]]
    return dict(title=f"Review — {name}", story=story, captions=caps, head=head_sha[:8], base=base_sha[:8], pr3=base_sha[:8], pr4=head_sha[:8],
                pend="The AI lists evidence and leads. It cannot approve this change, and most of what it lists is Unknown by design.",
                claims=[{k: v for k, v in c.items() if k != "stage" or True} for c in C], files=fv, nodes=nodes, edges=edges, rules=RULES,
                info={}, base_note=base_note, run=run_info, languages=dict(langs), too_common=too_common,
                capabilities=dict(static=True, induced=bool(earlier_items), executed=run_info["ran"]),
                log=[f"{h}|{s}" for h, (s, _) in earlier_items])


def hop1_of(sym, hop1):
    for (p, cs), (s, _) in hop1.items():
        if cs == sym:
            return s
    return sym



def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("repo"); ap.add_argument("--pr", type=int); ap.add_argument("--base"); ap.add_argument("--head")
    ap.add_argument("--run", action="store_true", help="execute the repo's own test command (runs its code!)")
    ap.add_argument("--spec", help="JSON list of {id, claim, command, expect?, cwd?}; requires --run")
    ap.add_argument("--check"); ap.add_argument("--out")
    a = ap.parse_args()
    if a.spec and not a.run:
        sys.exit("--spec commands execute code; add --run to confirm")
    d = analyze(a.repo, a.pr, a.base, a.head, a.run, a.spec)
    if a.check:
        c = next(c for c in d["claims"] if c["id"] == a.check)
        print(f"{c['id']}  {c['label'].upper()}  [{c['tier']}]\n  claim:   {c['claim']}\n  formula: {c['formula']}\n  commit:  {d['head']} (base {d['base']})")
        for w in c["witnesses"][:6]: print("  witness:", w)
        if c["note"]: print("  note:   ", c["note"])
        return
    slug = re.sub(r"[^\w.-]+", "_", d["title"])[:40]
    out = Path(a.out) if a.out else ROOT / ".trust" / "generic" / slug
    out.mkdir(parents=True, exist_ok=True)
    (out / "review.json").write_text(json.dumps(d, indent=2, default=list), encoding="utf-8")
    html = (HERE / "viewer.html").read_text(encoding="utf-8").replace("__DATA__", json.dumps(d, default=list))
    (out / "review.html").write_text(html, encoding="utf-8")
    print(f"{d['title']}   base {d['base']} → head {d['head']}   languages: {d['languages']}")
    for c in d["claims"]:
        print(f"  {c['id']:<3} {c['label']:<20} [{c['tier']:<8}] {c['short']}")
    print("wrote", out / "review.html")


if __name__ == "__main__":
    main()
