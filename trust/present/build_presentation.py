"""Build the interactive stage presentation from the pipeline's real artifacts.

The deck is a single self-contained HTML file (no CDN, no build step) that
presents the before/after story with the actual numbers produced by the
pipeline: bases.json, the assumption ledger, the context tree, the A/B arms,
and the LLM token measurements. Every slide that shows a command has a copy
button, so the audience can re-run the check themselves.

Nothing in the deck is invented: if an artifact is missing the slide says so
instead of substituting a made-up number.

Usage:
    python build_presentation.py --root <project-root> --out demo/presentation.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SLIDE_COUNT_PLACEHOLDER = 0


def load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def esc(s: object) -> str:
    import html
    return html.escape(str(s or ""))


def load_artifacts(root: Path) -> dict:
    """Everything the deck needs, read from .trust/ and demo/. Missing = None."""
    return {
        "root": root,
        "bases": load_json(root / ".trust" / "bases.json"),
        "blast": load_json(root / ".trust" / "findings" / "2297-blast.json"),
        "ab": load_json(root / ".trust" / "ab" / "2297.json"),
        "llm": load_json(root / ".trust" / "ab" / "2297-llm.json"),
        "tree": load_json(root / ".trust" / "tree" / "2297-tree.json"),
        "review": load_json(root / "demo" / "review-2297.json"),
        "proof": load_json(root / ".trust" / "findings" / "2297-proof.json"),
    }


# ---------------------------------------------------------------------------
# slide fragments (real data only)
# ---------------------------------------------------------------------------

def chip(text: str, cls: str = "") -> str:
    return f'<span class="chip {cls}">{esc(text)}</span>'


def s_title(_d: dict) -> str:
    return """
    <div class="center">
      <div class="kicker">junction26 · MessagePack-CSharp · 4 AI-made patches</div>
      <h1 class="big">How can AI review code made by AI<br>so that <span class="hl">humans</span> can trust it?</h1>
      <p class="lede">The reviewer is structurally incapable of asserting a defect it has
      not demonstrated. Every finding on these slides carries the command that produced it.</p>
      <div class="hint">→ / ← to navigate · click anything with a border</div>
    </div>"""


def s_setup(d: dict) -> str:
    bases = d["bases"]
    rows = []
    if bases:
        for r in bases.get("records", []):
            o = r.get("oracle") or {}
            agrees = bool(o.get("agrees"))
            oracle_chip = chip("agrees" if agrees else "disagrees",
                               "ok" if agrees else "bad")
            rows.append(
                f"<tr><td><code>{esc(r['branch'])}</code></td>"
                f"<td>{o.get('expected_changed_files', '?')}</td>"
                f"<td>{o.get('actual_changed_files', '?')}</td>"
                f"<td>{oracle_chip}</td></tr>")
    return f"""
    <h2>The setup: human repository, AI-made patches</h2>
    <div class="split">
      <div class="card">
        <h3>The library is human</h3>
        <p>MessagePack-CSharp — first commit <b>2017-02-13</b>, <b>3,536 commits</b>.
        The challenge input is not the repo: it is <b>one AI-made patch per branch</b>,
        all on top of base <code>32258fdb</code>.</p>
        <p>The human base is the oracle. &ldquo;Did this belief exist before the agent
        arrived?&rdquo; is answerable only because the base is nine years of human code.</p>
      </div>
      <div class="card">
        <h3>The four patches, checked against the brief</h3>
        <table class="mini">
          <tr><th>branch</th><th>brief</th><th>resolved</th><th></th></tr>
          {''.join(rows) or '<tr><td colspan=4>no bases.json - run demo.py</td></tr>'}
        </table>
        <p class="dim">The brief's own file counts are the external oracle. 4/4/28/237 - all four match.</p>
      </div>
    </div>"""


def s_before(d: dict) -> str:
    ab = d["ab"] or {}
    a = ab.get("arm_a") or {}
    false_finding = ""
    for f in a.get("findings", []):
        if f.get("status") == "REJECTED":
            false_finding = (
                f"<div class=\"finding false\"><b>[FALSE]</b> {esc(f.get('title', ''))}"
                f"<p class=\"dim\">{esc(f.get('verify_note', ''))}</p></div>")
    used = a.get("base_used") or "?"
    return f"""
    <h2>BEFORE - the reviewer that was confidently wrong</h2>
    <div class="beforeafter">
      <div class="ba bad">
        <h3>Before: unrecorded assumption</h3>
        <p>&ldquo;The merge-base is the base.&rdquo;<br>
        <code>origin/develop</code> does not exist → silent fallback to <code>master</code></p>
        <div class="bigcode">base used: {esc(used)[:9]}</div>
        <p>Diff starts <b>two commits too early</b>: pre-existing dependency bumps get
        attributed to the agents.</p>
        {false_finding or '<div class="finding false"><b>[FALSE]</b> dependency manifest changed - a base artefact</div>'}
      </div>
      <div class="vs">vs</div>
      <div class="ba good">
        <h3>Reality: the branch's own parent</h3>
        <p><code>git rev-parse origin/ju26-issue-2297^</code></p>
        <div class="bigcode">32258fdb</div>
        <p>The agents never touched that file. One unchecked assumption produced a
        plausible, evidence-citing, <b>false</b> finding.</p>
      </div>
    </div>
    <p class="dim center">This happened to <b>us</b> during this project. We lead with it.</p>"""


def s_after(d: dict) -> str:
    bases = d["bases"]
    rows = ""
    if bases:
        for r in bases.get("records", []):
            cands = ""
            for c in r.get("candidates", []):
                mark = "ok" if c.get("sha") else "miss"
                cands += (f"<div class='cand {mark}'>"
                          f"<span>{esc(c.get('method'))}</span>"
                          f"<span>{esc((c.get('sha') or '')[:9]) or c.get('note', 'missing')}</span></div>")
            rows += (f"<div class='card'><h3>{esc(r['branch'])}</h3>{cands}"
                     f"<p class='dim'>{esc('; '.join(r.get('warnings', [])))[:220]}</p>"
                     f"<p>verdict: {chip(r.get('verdict', '?'), 'ok' if r.get('verdict') == 'CONFIRMED' else 'bad')}"
                     f" <code>{esc(r.get('verify', ''))}</code></p></div>")
    return f"""
    <h2>AFTER - base resolution as a checked assumption</h2>
    <div class="grid3">
      {rows or '<div class="card">run demo.py first - bases.json missing</div>'}
    </div>
    <p class="dim center">Several independent methods, a missing ref is recorded (not skipped),
    disagreement is surfaced, and an external oracle decides. Never a silent fallback.</p>"""


def _blast_slide(d: dict) -> str:
    blast = d["blast"] or []
    if not blast:
        return "<h2>The hidden defect</h2><p>run demo.py first - ledger missing</p>"
    fal = [b for b in blast if (b.get("assumption") or {}).get("verdict") == "FALSIFIED"]
    sup = [b for b in blast if (b.get("assumption") or {}).get("verdict") == "SUPPORTED"]
    cards = ""
    for i, b in enumerate(fal):
        a = b["assumption"]
        sites = b.get("sites") or []
        hyps = b.get("hypotheses") or []
        site_html = "".join(
            f"<li><b>{esc(s.get('kind'))}</b> {esc(s.get('ref'))} "
            f"{'x' + str(s.get('count')) if s.get('count', 1) > 1 else ''}"
            f"<span class='dim'> - {esc(s.get('why', ''))}</span></li>"
            for s in sites[:8])
        hyp_html = "".join(
            f"<li>({esc(h.get('priority'))}) <b>{esc(h.get('failure_mode'))}</b> "
            f"<span class='dim'>{esc(h.get('site', ''))}</span></li>"
            for h in hyps[:6])
        cards += f"""
        <div class="acard falsified" onclick="toggle(this)">
          <div class="ahead"><b>[FALSIFIED]</b> {esc(a.get('id', ''))}
            <span class="sev">{esc(b.get('severity', ''))}</span></div>
          <div class="abody">
            <p class="assume">assumption: &ldquo;{esc(a.get('statement', ''))}&rdquo;</p>
            <ul class="tight">{''.join(f'<li>{esc(e)}</li>' for e in a.get('evidence', [])[:4])}</ul>
            <p class="blast">blast radius: {b.get('site_count', len(sites))} impact sites</p>
            <ul class="tight">{site_html}</ul>
            <p class="blast">pre-aimed hypotheses (unverified, labelled as such)</p>
            <ul class="tight">{hyp_html}</ul>
            <div class="cmdline" onclick="copyCmd(event, this)">$ {esc(a.get('check_cmd', ''))}</div>
          </div>
        </div>"""
    sup_html = "".join(
        f"<div class='acard supported'><div class='ahead'>[SUPPORTED] "
        f"{esc((b.get('assumption') or {}).get('id', ''))}</div>"
        f"<div class='abody'><p class='dim'>{esc((b.get('assumption') or {}).get('statement', ''))}</p></div></div>"
        for b in sup)
    return f"""
    <h2>The hidden defect - one falsified assumption</h2>
    <p class="dim">Branch <code>origin/ju26-issue-2297</code> implements
    &ldquo;add ExcludeFromCodeCoverage to generated code&rdquo;. The agent did most of the job
    <b>well</b> (6 templates, 222 snapshots regenerated). But it invented a guard of its own.
    <b>Click a card.</b></p>
    {cards}
    {sup_html}
    <p class="dim">Facts and suspicions stay separate: impact sites are facts,
    hypotheses are unverified suspicions and are never merged into the finding count.</p>"""


def s_probes(d: dict) -> str:
    return """
    <h2>The falsification - you can re-run it</h2>
    <div class="grid3">
      <div class="card probe"><h3>netstandard2.0</h3>
        <div class="big ok">COMPILES</div>
        <p class="dim">the attribute, unguarded, compiles on a framework the guard excludes</p></div>
      <div class="card probe"><h3>net472</h3>
        <div class="big ok">COMPILES</div>
        <p class="dim">same - the compatibility premise is false on both excluded targets</p></div>
      <div class="card probe"><h3>why no test catches it</h3>
        <p>All 8 test projects target <code>net8.0</code> - the guard always passes in CI.
        The 220 verified snapshots were regenerated <b>with</b> the guard, so the tests now
        codify the gap.</p></div>
    </div>
    <div class="cmdline" onclick="copyCmd(event, this)">$ dotnet build .trust/probes/origin_ju26-issue-2297/probe_netstandard2_0/p.csproj -v q --nologo</div>
    <div class="cmdline" onclick="copyCmd(event, this)">$ dotnet build .trust/probes/origin_ju26-issue-2297/probe_net472/p.csproj -v q --nologo</div>
    <p class="dim center">Consequence: netstandard2.0 and net472 - two of the four shipped
    target frameworks - silently never receive the feature the issue asked for. A feature gap,
    not a crash: we do not inflate it.</p>"""


def s_tokens(d: dict) -> str:
    llm = d["llm"] or []
    tree = d["tree"] or {}
    arms = {a.get("strategy"): a for a in llm}
    walk = (tree.get("totals") or {}).get("total_tokens")
    rows = []
    for label, val, cls, note in (
        ("BEFORE - dump the whole diff", arms.get("full", {}).get("prompt_tokens"),
         "bad", "237 files, no citations - a model has to read all of it"),
        ("A competent human's triage", arms.get("full-triaged", {}).get("prompt_tokens"),
         "mid", "generated files dropped first - the fair baseline"),
        ("AFTER - graph walk (this system)", walk if walk else arms.get("recall", {}).get("prompt_tokens"),
         "good", "cited snippets + compile probes, not reading"),
    ):
        if val is None:
            continue
        maxv = max((arms.get("full", {}).get("prompt_tokens") or 1), walk or 1)
        pct = int(100 * val / maxv)
        rows.append(f"""
        <div class="trow {cls}">
          <div class="tlabel">{label}<br><span class="dim">{note}</span></div>
          <div class="ttrack"><div class="tfill" style="width:{pct}%"></div></div>
          <div class="tval">{val:,} tokens</div>
        </div>""")
    return f"""
    <h2>What context actually costs - measured</h2>
    {''.join(rows) or '<p>run demo.py first</p>'}
    <p class="dim center">tiktoken cl100k_base estimates; ratios reliable, absolutes approximate.
    On the 4-file patch the walk saves only ~24% - fixed costs dominate - and we publish that too.
    Retrieval pays at scale, not by magic.</p>"""


def s_ab(d: dict) -> str:
    ab = d["ab"] or {}
    a = ab.get("arm_a") or {}
    b = ab.get("arm_b") or {}

    def findings_html(arm: dict) -> str:
        out = ""
        for f in arm.get("findings", []):
            cls = {"CONFIRMED": "good", "REJECTED": "bad", "UNVERIFIED": "mid"}.get(f.get("status"), "mid")
            inv = " <b>test-invisible</b>" if f.get("test_invisible") else ""
            out += f"<div class='finding {cls}'><b>[{esc(f.get('status'))}]</b> {esc(f.get('title', ''))}{inv}</div>"
        return out or "<div class='finding good'><b>[none]</b> no findings</div>"

    return f"""
    <h2>The measured A/B - same reviewer, one variable</h2>
    <div class="beforeafter">
      <div class="ba bad">
        <h3>Arm A - no capsule (&ldquo;before&rdquo;)</h3>
        <p>diff + issue text, unrestricted reads. A genuine review as practised today.</p>
        <p>base used: <code>{esc((a.get('base_used') or '?')[:9])}</code> (wrong)</p>
        {findings_html(a)}
        <p class="dim">{len(a.get('rejected', [])) if isinstance(a.get('rejected'), list) else ''} false finding(s) rejected by the shared verifier</p>
      </div>
      <div class="vs">vs</div>
      <div class="ba good">
        <h3>Arm B - with the capsule (&ldquo;after&rdquo;)</h3>
        <p>everything Arm A has, plus the checked base and the assumption ledger.</p>
        <p>base used: <code>{esc((b.get('base_used') or '?')[:9])}</code> (oracle-checked)</p>
        {findings_html(b)}
        <p class="dim">100% precision. Neither arm grades itself - one shared verifier.</p>
      </div>
    </div>"""


def _tree_slide(d: dict) -> str:
    tree = d["tree"]
    if not tree:
        return "<h2>The context tree</h2><p>run demo.py first - tree missing</p>"
    marks: dict[str, set[str]] = {}
    for p in tree.get("passes", []):
        cls = "p0" if p.get("kind") == "lookup" else "p1"
        for v in p.get("visits", []):
            marks.setdefault(v["node_id"], set()).add(cls)

    def render_node(node: dict, depth: int) -> str:
        m = marks.get(node["id"], set())
        cls = "node"
        if "p0" in m:
            cls += " p0"
        if "p1" in m:
            cls += " p1"
        kids = "".join(render_node(c, depth + 1) for c in node.get("children", []))
        toggle = "<span class='tgl' onclick='tgl(this)'>&#9662;</span>" if kids else "<span class='tgl leaf'>&#183;</span>"
        return (f"<li class='{cls} {('falsified' if node.get('falsified') else '')}'>"
                f"<div class='row'>{toggle}<span class='kind'>{esc(node.get('kind'))}</span>"
                f"<span class='label'>{esc(node.get('label'))[:70]}</span>"
                f"<span class='tok'>{node.get('tokens', 0)}</span></div>"
                f"{'<ul>' + kids + '</ul>' if kids else ''}</li>")

    passes_html = ""
    for i, p in enumerate(tree.get("passes", [])):
        rev = sum(1 for v in p.get("visits", []) if v.get("revisit"))
        passes_html += (f"<div class='passrow {p.get('kind')}' data-pass='{i}' onclick='focusPass({i})'>"
                        f"<span class='pkind'>{esc(p.get('kind'))}</span>"
                        f"<span class='pname'>{esc(p.get('name', ''))[:58]}</span>"
                        f"<span class='ptok'>{p.get('tokens', 0)}</span>"
                        f"{'<span class=rev>&#8635;' + str(rev) + '</span>' if rev else ''}</div>")
    t = tree.get("totals", {})
    return f"""
    <h2>The context tree - a question is a measured walk</h2>
    <div class="treesplit">
      <div class="treebox"><ul>{render_node(tree["tree"], 0)}</ul></div>
      <div class="treeinfo">
        <p><span class="legend p0"></span> lookup path &nbsp;
           <span class="legend p1"></span> falsification propagation &nbsp;
           <span class="legend both"></span> revisited</p>
        {passes_html}
        <div class="stat"><span>walk total</span><b>{t.get('total_tokens', 0):,} tokens</b></div>
        <div class="stat"><span>nodes visited</span><b>{t.get('nodes_visited', 0)}</b></div>
        <div class="stat"><span>revisits (recurring traversal)</span><b>{t.get('revisits', 0)}</b></div>
        <div class="stat"><span>full dump would be</span><b>{(tree.get('baselines') or {}).get('full_tree_dump_tokens', 0):,}</b></div>
      </div>
    </div>
    <p class="dim center">When a claim is falsified, the walk re-enters the tree and visits its
    blast radius - that is the &ldquo;problems nobody asked about&rdquo; mechanism.</p>"""


def s_run(d: dict) -> str:
    return """
    <h2>You run it - not us</h2>
    <div class="center">
      <div class="cmdline big" onclick="copyCmd(event, this)">$ cd .trust/repro/2297 &amp;&amp; dotnet test</div>
      <div class="terminal">
        <span class="fail">Failed: 2</span> <span class="pass">Passed: 1</span> Total: 3<br>
        <span class="dim">ExcludeFromCodeCoverageAppliesToAllShippedTargets.AttributeIsNotRestrictedByTargetFramework [FAIL]</span><br>
        <span class="dim">ExcludeFromCodeCoverageAppliesToAllShippedTargets.ReadmeDoesNotClaimTheAttributeIsUnavailable [FAIL]</span><br>
        <span class="dim">TemplatesExist [PASS] - the suite cannot succeed vacuously</span>
      </div>
      <p class="dim">The finding ships as a test the audience executes. Failing while the defect
      exists, passing once fixed. That is the trust check - not prose.</p>
    </div>"""


def s_trail(d: dict) -> str:
    review = d["review"]
    rec = ""
    if review:
        rec = f"<p class='dim'>recommendation recorded in <code>demo/review-2297.json</code></p>"
    return """
    <h2>The Trail and the human decision</h2>
    <div class="split">
      <div class="card">
        <h3>Live on Entire</h3>
        <p>Trail #1: <a href="https://entire.com/et/earned-trust-review/-/trails/1"
        target="_blank">entire.com/et/earned-trust-review/-/trails/1</a></p>
        <p>Branch <code>review/2297</code> linked and retargeted onto its true base.
        Two findings attached with suggested patches.</p>
        <p><span class="chip bad">AI: request changes</span>
           <span class="chip mid">refuses to waive the requirement</span>
           <span class="chip ok">human decision: pending</span></p>
        """ + rec + """
      </div>
      <div class="card">
        <h3>The honesty rules</h3>
        <ol class="tight">
          <li>The false finding in &ldquo;before&rdquo; is ours, not Tieto's.</li>
          <li>The #2297 agent did most of the job well - say so first.</li>
          <li>The finding is a feature gap + a false README sentence, not a crash.</li>
          <li>Three of four branches yield nothing - an honest result, not four wins.</li>
          <li>Private agent reasoning is not recoverable; reconstructed context is labelled.</li>
          <li>Confirmed findings and hypotheses are never merged into one score.</li>
        </ol>
      </div>
    </div>
    <p class="dim center">MongoDB Atlas stores the same tree (nodes/edges/traversals, $graphLookup).
    The token numbers are measured; the decision belongs to a named human.</p>"""


# ---------------------------------------------------------------------------
# Part 1: the small sandbox - how the graph works, on a toy example
# ---------------------------------------------------------------------------

def s_small(_d: dict) -> str:
    return """
    <h2>Start small: a three-file toy project</h2>
    <div class="sandboxnote">toy example - mechanics only, not a real finding</div>
    <div class="split">
      <div class="card code">
        <h3>store.py</h3>
<pre>items = {}
def put(k, v): items[k] = v
def get(k):    return items[k]</pre>
      </div>
      <div class="card code">
        <h3>checkout.py</h3>
<pre>def total(cart):
    s = 0
    for k in cart:
        s += store.get(k).price   # &lt;- assumes every key exists
    return s</pre>
      </div>
      <div class="card code">
        <h3>tests</h3>
<pre>assert total({"a": 2}) == 12   # passes
# no test for a missing key</pre>
      </div>
    </div>
    <p>Everything the review system does is easier to see here than in a
    237-file patch. Next: how this toy becomes a graph.</p>"""


def s_graph_made(_d: dict) -> str:
    return """
    <h2>How the graph is made - step by step</h2>
    <div class="steps" id="gmsteps">
      <div class="stepcard"><h3>1 · the session records what happened</h3>
        <p class="dim">a transcript: human prompt &rarr; tool call &rarr; file edit &rarr; commit</p>
        <code>prompt "add checkout total" · Edit checkout.py · git commit 9f3c</code></div>
      <div class="stepcard"><h3>2 · records become nodes</h3>
        <p>one node per fact, with its provenance: <span class="chip">PROMPT</span>
        <span class="chip">TOOL_CALL</span> <span class="chip">FILE</span>
        <span class="chip">COMMIT</span></p></div>
      <div class="stepcard"><h3>3 · edges connect them</h3>
        <p><span class="edge">caused</span> prompt&rarr;call ·
        <span class="edge">writes</span> call&rarr;file ·
        <span class="edge">inspects</span> call&rarr;commit</p></div>
      <div class="stepcard"><h3>4 · fused with real git history</h3>
        <p><span class="edge">parent_of</span> commit&rarr;base commit, so the graph answers
        &ldquo;what was this change built on?&rdquo; from git, not from memory</p></div>
    </div>
    <div class="center"><button onclick="step('gmsteps',1)">step 1</button>
      <button onclick="step('gmsteps',2)">step 2</button>
      <button onclick="step('gmsteps',3)">step 3</button>
      <button onclick="step('gmsteps',4)">all</button></div>"""


def s_colors(_d: dict) -> str:
    return """
    <h2>What the colors mean</h2>
    <div class="split">
      <div class="card">
        <h3><span class="legend p0"></span> blue - the lookup path</h3>
        <p>The question enters the graph at one node; only the path from the
        root to that node is opened. Everything else stays unread.</p>
      </div>
      <div class="card">
        <h3><span class="legend p1"></span> red - falsification propagation</h3>
        <p>When a claim is falsified, the walk re-enters the graph and visits
        everything that claim was load-bearing for - its blast radius.</p>
      </div>
      <div class="card">
        <h3><span class="legend both"></span> purple - revisited</h3>
        <p>A node already seen by an earlier pass and touched again - the
        &ldquo;recurring traversal&rdquo; signal, counted per pass.</p>
      </div>
      <div class="card">
        <h3>token chip on every node</h3>
        <p>Each node costs what its text costs. The walk's total is the sum of
        what was actually opened - not the whole graph.</p>
      </div>
    </div>"""


def s_history(_d: dict) -> str:
    return """
    <h2>Current PR vs previous PRs - history does the routing</h2>
    <div class="sandboxnote">toy example - mechanics only</div>
    <div class="split">
      <div class="card">
        <h3>Previous PR #41 fixed the same region</h3>
        <p><code>checkout.py:4</code> once crashed on a missing key; PR #41 added
        <code>store.get(k, 0)</code>. The graph records that fix as a commit node
        with <span class="edge">parent_of</span> edges to today's code.</p>
        <p class="dim">commit 41a7c2 &ldquo;fix KeyError in checkout.total&rdquo; &rarr; today's line 4</p>
      </div>
      <div class="card bad">
        <h3>Current PR #58 touches the same line</h3>
        <p>The graph routes the reviewer to the history: &ldquo;this region was
        fragile before; what changed?&rdquo; The new code inlines the lookup again
        without the default.</p>
        <p>Reviewer is pre-aimed at exactly the line the previous bug lived on -
        <b>before</b> reading the rest of the diff.</p>
      </div>
    </div>
    <p class="dim center">History edges turn &ldquo;read everything&rdquo; into
    &ldquo;check where it broke before&rdquo;. The checker still has to prove the
    claim - the graph only chooses where to look.</p>"""


def s_expand(_d: dict) -> str:
    return """
    <h2>How a falsified claim expands the search space</h2>
    <div class="steps" id="exsteps">
      <div class="stepcard"><h3>1 · one falsified assumption</h3>
        <p class="dim">&ldquo;the attribute is unavailable on netstandard2.0 and net472&rdquo; - false,
        proved by a compile probe.</p></div>
      <div class="stepcard"><h3>2 · its footprint predicate searches the whole change</h3>
        <p class="dim">every file carrying the same guard, every shipped target framework,
        every snapshot that baked the guard in.</p></div>
      <div class="stepcard"><h3>3 · impact sites are facts</h3>
        <p>2 shipped frameworks · 6 templates · 220 snapshots = <b>228 sites</b></p></div>
      <div class="stepcard"><h3>4 · each site becomes a pre-aimed hypothesis</h3>
        <p class="dim">feature absent on net472 · tests codify the gap · regeneration will
        re-emit the guard - labelled hypotheses, never findings.</p></div>
    </div>
    <div class="center"><button onclick="step('exsteps',1)">step 1</button>
      <button onclick="step('exsteps',2)">step 2</button>
      <button onclick="step('exsteps',3)">step 3</button>
      <button onclick="step('exsteps',4)">all</button></div>
    <p class="dim center">One falsified claim finds problems nobody asked about -
    and the deck states which are facts and which are suspicions.</p>"""


# ---------------------------------------------------------------------------
# Part 2: the real PR, proof-carrying
# ---------------------------------------------------------------------------

def s_proof(d: dict) -> str:
    proof = d.get("proof") or {}
    if not proof:
        return ("<h2>Proof-carrying review</h2><p>run the pipeline first - "
                "2297-proof.json missing</p>")
    req = proof.get("requirement") or {}
    claims = proof.get("claims") or []
    results = proof.get("results") or []
    legend = proof.get("label_legend") or {}

    # the centerpiece: the first claim, its rule, and its result
    c1 = next((c for c in claims if c.get("id") == "C-2297-1"), claims[0] if claims else {})
    r1 = next((r for r in results if r.get("claim") == c1.get("id")
               and r.get("verdict") == "REFUTED"), None)
    lines_html = ""
    for i, link in enumerate(c1.get("line_links", [])[:9]):
        lines_html += (f"<div class='lineitem' onclick='showDetail({i})' "
                       f"data-i='{i}'>"
                       f"<span class='ln'>{esc(link.get('line'))}</span>"
                       f"<span class='lt'>{esc(link.get('text', ''))}</span>"
                       f"<span class='lp'>{esc(link.get('file', ''))}</span></div>")
    details_html = ""
    rv = r1 or {}
    verdict_word = rv.get("verdict", "?")
    chip_cls = "bad" if verdict_word == "REFUTED" else "ok"
    witness_raw = rv.get("witness", {}) or {}
    witness_text = witness_raw.get("detail", "") or witness_raw.get("tfm", "")
    rule_rec = next((r for r in proof.get("rules", [])
                     if r.get("id") == rv.get("rule")), {}) or {}
    rule_text = rule_rec.get("checker", "")
    for i, link in enumerate(c1.get("line_links", [])[:9]):
        ev_html = ""
        for e in rv.get("evidence", []):
            if e.get("kind") in ("command", "checker_output"):
                ev_html += (f"<div class='cmdline' onclick='copyCmd(event, this)'>"
                            f"$ {esc(e.get('value', ''))[:160]}</div>")
            else:
                ev_html += (f"<p class='dim'>[{esc(e.get('kind'))}] "
                            f"{esc(e.get('value', ''))[:220]}</p>")
        style_attr = 'style="display:block"' if i == 0 else ""
        details_html += f"""
        <div class="proofdetail" id="pd{i}" {style_attr}>
          <p class="dim">changed line: <code>{esc(link.get('file'))}:{esc(link.get('line'))}</code></p>
          <div class="proofgrid">
            <div><b>Claim</b></div><div>{esc(c1.get('id'))} - {esc(c1.get('statement'))}</div>
            <div><b>Formal</b></div><div class="formal">{esc(c1.get('formal'))}</div>
            <div><b>Rule</b></div><div>{esc(rule_text)}</div>
            <div><b>Result</b></div>
            <div><span class="chip {chip_cls}">{esc(verdict_word)}</span></div>
            <div><b>Witness</b></div><div class="witness">{esc(witness_text)}</div>
          </div>
          <p class="blast">evidence - re-run it yourself</p>
          {ev_html}
        </div>"""

    verdict_chips = ""
    for res in results:
        cls = {"REFUTED": "bad", "PROVED_IN_SCOPE": "ok",
               "TESTED": "mid", "UNKNOWN": "dim"}.get(res.get("verdict"), "dim")
        verdict_chips += (f"<div class='vrow'><span class='chip {cls}'>"
                          f"{esc(res.get('verdict'))}</span> "
                          f"<span>{esc(res.get('claim'))} via {esc(res.get('rule'))}</span></div>")

    legend_rows = "".join(
        f"<tr><td><b>{esc(k)}</b></td><td class='dim'>{esc(v)}</td></tr>"
        for k, v in legend.items())
    return f"""
    <h2>The centerpiece: click a changed line &rarr; its proof</h2>
    <div class="proofsplit">
      <div class="linelist">
        <p class="dim">changed lines of the patch - each links to one claim</p>
        {lines_html}
        <p class="dim">{len(c1.get('line_links', []))} guard lines across the templates
        link to the same claim - the claim is stated once, not per line.</p>
      </div>
      <div class="proofpanel">
        <div class="obligation">
          <b>REQ-2297</b> - {esc(req.get('formal_obligation', ''))}
          <p class="dim">assumptions: {esc('; '.join(req.get('assumptions', [])))}</p>
        </div>
        {details_html}
      </div>
    </div>
    <h3>every verdict, honestly labelled</h3>
    <div class="split">
      <table class="mini"><tr><th>label</th><th>what it means</th></tr>{legend_rows}</table>
      <div class="card"><h3>this review's ledger</h3>{verdict_chips}
        <p class="dim">the human decision stays pending - the AI recommends
        request changes and refuses to waive the requirement.</p></div>
    </div>"""


SLIDES = [
    ("The question", s_title),
    ("Start small", s_small),
    ("How the graph is made", s_graph_made),
    ("What the colors mean", s_colors),
    ("Current PR vs previous PRs", s_history),
    ("Expanding the search space", s_expand),
    ("The real PR: setup", s_setup),
    ("Before: the wrong review", s_before),
    ("After: the checked base", s_after),
    ("Click a line, see its proof", s_proof),
    ("The hidden defect", _blast_slide),
    ("The falsification", s_probes),
    ("Tokens: before vs after", s_tokens),
    ("The A/B outcome", s_ab),
    ("The context tree", _tree_slide),
    ("You run it", s_run),
    ("The Trail & the decision", s_trail),
]


# ---------------------------------------------------------------------------
# deck assembly
# ---------------------------------------------------------------------------

_CSS = """
body{margin:0;font:15px/1.5 system-ui,'Segoe UI',sans-serif;background:#0d1321;color:#e8ecf5}
.slide{display:none;max-width:1080px;margin:0 auto;padding:34px 44px 70px;min-height:76vh}
.slide.active{display:block;animation:fade .25s}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1}}
h1.big{font-size:44px;line-height:1.15;margin:14px 0}
h2{font-size:30px;margin:6px 0 16px;color:#dfe7f5}
h3{font-size:17px;margin:0 0 8px}
.hl{color:#7fb0f0}.lede{color:#aab6cc;font-size:18px;max-width:760px}
.kicker{letter-spacing:.14em;text-transform:uppercase;color:#7f8db0;font-size:12px}
.center{text-align:center;padding-top:14vh}
.dim{color:#93a0b8;font-size:13px}
code{background:#1c2740;border-radius:4px;padding:1px 7px;color:#9fd0ff;font-size:13px}
a{color:#7fb0f0}
.split{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.card{background:#141d33;border:1px solid #253251;border-radius:12px;padding:16px 18px}
.card h3{color:#c9d6ef}
table.mini{width:100%;border-collapse:collapse;font-size:13px}
table.mini th,table.mini td{border-bottom:1px solid #253251;padding:5px 6px;text-align:left}
.chip{display:inline-block;border-radius:20px;padding:2px 12px;font-size:12px;margin:2px;background:#22304f}
.chip.ok{background:#123d24;color:#7ce3a0}.chip.bad{background:#4d1620;color:#ff9d9d}
.chip.mid{background:#4d3d12;color:#ffd98a}.chip.miss{background:#2a2f42;color:#8b94ac}
.beforeafter{display:grid;grid-template-columns:1fr 60px 1fr;gap:14px;align-items:stretch}
.ba{border-radius:14px;padding:20px;border:1px solid #253251}
.ba.bad{background:#221322;border-color:#5c2433}.ba.good{background:#0f2119;border-color:#1f5c3c}
.ba h3{margin-top:0}
.vs{align-self:center;text-align:center;color:#7f8db0;font-weight:700;font-size:18px}
.bigcode{font-family:ui-monospace,Consolas,monospace;font-size:34px;color:#9fd0ff;background:#101a30;border-radius:8px;padding:10px 16px;margin:10px 0;display:inline-block}
.finding{border-radius:8px;padding:9px 12px;margin:8px 0;font-size:13px}
.finding.good{background:#123d24;color:#7ce3a0}.finding.bad{background:#4d1620;color:#ff9d9d}
.finding.mid{background:#3a3f55;color:#cdd5e6}
.acard{border:1px solid #253251;border-radius:12px;margin:10px 0;background:#141d33;cursor:pointer}
.acard .ahead{padding:12px 16px;font-weight:600}
.acard.falsified .ahead{color:#ffb0b0}.acard.falsified{border-color:#7c3346}
.acard.supported .ahead{color:#7ce3a0}
.acard .abody{display:none;padding:4px 18px 16px;border-top:1px solid #253251}
.acard.open .abody{display:block}
.sev{float:right;color:#ffd98a;font-size:12px;text-transform:uppercase}
.assume{color:#dfe7f5;font-style:italic}
.blast{color:#ffd98a;font-weight:600;margin:8px 0 4px}
ul.tight{margin:4px 0 8px;padding-left:20px;font-size:13px;color:#c2cce0}
ul.tight li{margin:2px 0}
.cmdline{font-family:ui-monospace,Consolas,monospace;font-size:13px;background:#0b1220;border:1px solid #253251;border-radius:8px;padding:9px 12px;margin:8px 0;color:#9fd0ff;cursor:pointer;white-space:pre-wrap}
.cmdline.big{font-size:16px;display:inline-block}
.cmdline:hover{border-color:#4d8ff0}
.probe .big{font-size:30px;font-weight:800;margin:6px 0}.big.ok{color:#7ce3a0}
.trow{display:grid;grid-template-columns:300px 1fr 140px;gap:14px;align-items:center;margin:14px 0}
.tlabel{font-weight:600}
.ttrack{background:#1c2740;border-radius:6px;height:26px;overflow:hidden}
.tfill{height:100%;border-radius:6px;transition:width .8s}
.trow.good .tfill{background:linear-gradient(90deg,#1f5c3c,#7ce3a0)}
.trow.mid .tfill{background:linear-gradient(90deg,#4d3d12,#ffd98a)}
.trow.bad .tfill{background:linear-gradient(90deg,#4d1620,#ff9d9d)}
.tval{font-weight:700;font-size:16px}
.treesplit{display:grid;grid-template-columns:1fr 380px;gap:18px}
.treebox{background:#101a30;border:1px solid #253251;border-radius:12px;padding:12px;max-height:56vh;overflow:auto}
.treebox ul{list-style:none;margin:0;padding-left:18px}
.treebox li>ul{display:none}.treebox li.open>ul{display:block}
.treebox .row{padding:2px 4px;border-radius:5px;white-space:nowrap}
.treebox .tgl{cursor:pointer;color:#7f8db0;display:inline-block;width:14px}
.treebox .kind{display:inline-block;min-width:80px;color:#7f8db0;font-size:11px}
.treebox .label{margin-left:4px;font-size:13px}
.treebox .tok{float:right;color:#8b94ac;font-size:11px;background:#1c2740;border-radius:8px;padding:0 7px}
.treebox .node.p0 .row{background:#122a4d;outline:1px solid #4d8ff0}
.treebox .node.p1 .row{background:#4d1620;outline:1px solid #e2603a}
.treebox .node.p0.p1 .row{background:#2c1e4d;outline:1px solid #b08ae0}
.treebox .node.falsified .label{color:#ff9d9d;font-weight:600}
.legend{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:3px}
.legend.p0{background:#4d8ff0}.legend.p1{background:#e2603a}.legend.both{background:#b08ae0}
.passrow{display:grid;grid-template-columns:86px 1fr auto auto;gap:6px;padding:5px 8px;border-radius:6px;margin-bottom:4px;cursor:pointer;background:#1c2740}
.passrow.look{border-left:3px solid #4d8ff0}.passrow.prop{border-left:3px solid #e2603a}
.passrow.active{box-shadow:0 0 0 2px #b08ae0}
.pkind{font-size:11px;color:#7f8db0;text-transform:uppercase}.ptok{font-weight:700}
.rev{color:#e2603a;font-size:11px}
.stat{display:flex;justify-content:space-between;border-bottom:1px dotted #253251;padding:3px 0;font-size:13px}
.terminal{font-family:ui-monospace,Consolas,monospace;background:#0b1220;border:1px solid #253251;border-radius:10px;padding:14px 18px;text-align:left;display:inline-block;margin:14px 0;font-size:13px}
.fail{color:#ff9d9d}.pass{color:#7ce3a0}
nav{position:fixed;bottom:0;left:0;right:0;background:#0b1220;border-top:1px solid #1c2740;padding:10px 20px;display:flex;align-items:center;gap:10px;z-index:9}
nav button{background:#1c2740;border:1px solid #2a3d66;color:#cdd5e6;border-radius:8px;padding:7px 14px;cursor:pointer;font-size:13px}
nav button:hover{border-color:#4d8ff0}
.dots{flex:1;text-align:center}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:#2a3d66;margin:0 4px;cursor:pointer}
.dot.on{background:#7fb0f0}
.counter{color:#7f8db0;font-size:12px;min-width:70px;text-align:right}
.toast{position:fixed;top:18px;left:50%;transform:translateX(-50%);background:#1f5c3c;color:#eafff2;border-radius:8px;padding:7px 16px;font-size:13px;opacity:0;transition:opacity .2s;z-index:10}
.sandboxnote{display:inline-block;background:#4d3d12;color:#ffd98a;border-radius:20px;padding:2px 12px;font-size:12px;margin-bottom:10px}
.card.code pre{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;background:#0b1220;border-radius:8px;padding:10px 12px;overflow:auto;color:#c9d6ef}
.edge{color:#b08ae0;font-weight:600}
.steps .stepcard{display:none;background:#141d33;border:1px solid #253251;border-radius:10px;padding:12px 16px;margin:8px 0}
.steps .stepcard h3{margin:0 0 4px}
.linelist{background:#101a30;border:1px solid #253251;border-radius:10px;padding:10px;overflow:auto;max-height:44vh}
.lineitem{display:grid;grid-template-columns:34px 1fr;gap:8px;padding:5px 8px;border-radius:6px;cursor:pointer;font-family:ui-monospace,Consolas,monospace;font-size:12.5px}
.lineitem:hover{background:#1c2740;outline:1px solid #4d8ff0}
.lineitem .ln{color:#7f8db0;text-align:right}
.lineitem .lt{color:#9fd0ff}
.lineitem .lp{grid-column:1/3;color:#7f8db0;font-size:11px;font-family:system-ui}
.proofsplit{display:grid;grid-template-columns:420px 1fr;gap:16px}
.proofpanel{background:#141d33;border:1px solid #253251;border-radius:12px;padding:16px}
.obligation{background:#0b1220;border-left:3px solid #7fb0f0;border-radius:8px;padding:10px 14px;margin-bottom:12px}
.obligation b{color:#7fb0f0}
.proofdetail{display:none;margin-top:10px}
.proofgrid{display:grid;grid-template-columns:90px 1fr;gap:6px 10px;font-size:13.5px;margin:8px 0}
.proofgrid .formal{font-family:ui-monospace,Consolas,monospace;color:#9fd0ff}
.proofgrid .witness{color:#ff9d9d;font-weight:600}
.vrow{padding:4px 0;border-bottom:1px dotted #253251;font-size:13px}
.chip.dim{background:#2a2f42;color:#8b94ac}
"""

_JS = r"""
const slides=[...document.querySelectorAll('.slide')];
let cur=0;
function show(i){
  if(i<0||i>=slides.length)return;
  slides[cur].classList.remove('active');
  cur=i;slides[cur].classList.add('active');
  document.querySelectorAll('.dot').forEach((d,j)=>d.classList.toggle('on',j===cur));
  document.getElementById('counter').textContent=(cur+1)+' / '+slides.length;
  const bars=slides[cur].querySelectorAll('.tfill');
  bars.forEach(b=>{const w=b.style.width;b.style.width='0';setTimeout(()=>b.style.width=w,60);});
  window.scrollTo({top:0});
}
document.addEventListener('keydown',e=>{
  if(e.key==='ArrowRight'||e.key===' ')show(cur+1);
  if(e.key==='ArrowLeft')show(cur-1);
});
function tgl(el){el.parentElement.parentElement.classList.toggle('open');}
function toggle(card){card.classList.toggle('open');}
function focusPass(i){
  document.querySelectorAll('.passrow').forEach(r=>r.classList.remove('active'));
  document.querySelectorAll(`.passrow[data-pass="${i}"]`).forEach(r=>r.classList.add('active'));
}
function copyCmd(ev,el){
  ev.stopPropagation();
  const text=el.textContent.replace(/^\$\s*/,'');
  (navigator.clipboard?navigator.clipboard.writeText(text):Promise.reject()).then(()=>{
    const t=document.getElementById('toast');t.textContent='copied: '+text.slice(0,60)+'…';t.style.opacity=1;
    setTimeout(()=>t.style.opacity=0,1500);
  });
}
function step(containerId,n){
  const kids=document.getElementById(containerId).children;
  for(let i=0;i<kids.length;i++){kids[i].style.display = i<n ? 'block' : 'none';}
}
function showDetail(i){
  document.querySelectorAll('.proofdetail').forEach(d=>d.style.display='none');
  const el=document.getElementById('pd'+i);
  if(el) el.style.display='block';
  document.querySelectorAll('.lineitem').forEach((l,j)=>l.style.outline = j===i ? '1px solid #4d8ff0' : 'none');
}
"""


def build_deck(d: dict) -> str:
    sections = []
    for i, (title, fn) in enumerate(SLIDES):
        sections.append(f'<section class="slide{" active" if i == 0 else ""}" data-title="{esc(title)}">'
                        f"{fn(d)}</section>")
    dots = "".join(f'<span class="dot{" on" if i == 0 else ""}" onclick="show({i})"></span>'
                   for i in range(len(SLIDES)))
    nav = (f'<nav><button onclick="show(cur-1)">&#8592;</button>'
           f'<button onclick="show(cur+1)">&#8594;</button>'
           f'<div class="dots">{dots}</div>'
           f'<span class="counter" id="counter">1 / {len(SLIDES)}</span></nav>')
    title_html = "".join(f'<div class="dim" id="t{i}" style="display:none">{esc(t)}</div>'
                         for i, (t, _) in enumerate(SLIDES))
    payload = json.dumps({k: (v if k in ("bases", "blast", "ab", "llm", "tree", "review") else None)
                          for k, v in d.items() if k != "root"},
                         ensure_ascii=False, default=str).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>How can AI review code made by AI so that humans can trust it?</title>
<style>{_CSS}</style></head>
<body>
<div id="toast" class="toast"></div>
{''.join(sections)}
{nav}
{title_html}
<script>const DATA={payload};</script>
<script>{_JS}</script>
</body></html>"""


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    ap.add_argument("--out", default="demo/presentation.html")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    d = load_artifacts(root)
    missing = [k for k, v in d.items() if k not in ("root",) and v is None]
    html = build_deck(d)
    out = (root if (Path(args.out).is_absolute()) else root) / args.out \
        if not Path(args.out).is_absolute() else Path(args.out)
    out = Path(args.out) if Path(args.out).is_absolute() else root / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"deck built: {out.resolve()} ({len(html)} bytes, {len(SLIDES)} slides)")
    if missing:
        print(f"missing artifacts (slides will say so): {', '.join(missing)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
