"""Context tree: the reviewer's evidence as a tree, with traversal accounting.

WHY A TREE
----------
A reviewer should not be handed a pile of evidence. This module arranges
everything the review can know about a branch into a TREE:

    review
    ├── issue            (what was asked)
    ├── diff             (files -> hunks, generated bulk summarised)
    ├── assumptions      (each harvested assumption -> evidence/sites/hypotheses)
    └── capsule          (session provenance, when a transcript exists)

Then it MEASURES how questions travel through the tree:

    pass 1  lookup        question -> entry node -> path from the root.
                          Only nodes on the path are counted.
    pass 2  propagation   a FALSIFIED assumption re-enters the tree and
                          recursively visits its impact sites and hypotheses -
                          the mechanism by which one falsified claim becomes a
                          family of pre-aimed hypotheses.

Every visited node contributes its token cost. The JSON output therefore
answers three questions at once: what did the review know, how did it get to
each answer, and what did that cost - against the baseline of a traditional
agent dumping the whole diff.

BACKEND
-------
The traversal is computed here deterministically (no Mongo required). With
MONGO_URI set, `mongo_tree.py` performs the SAME passes as MongoDB Atlas
$graphLookup queries and writes each pass to a `traversals` collection; both
paths emit the same JSON schema, and the HTML renderer cannot tell them apart.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "memory"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ab"))

import recall as rc                 # noqa: E402
from llm_arm import evidence_full   # noqa: E402

GENERATED_RE = re.compile(r"(\.g\.cs$|\.verified\.|/Resources/)")

# how attractive each node kind is when a question looks for an entry point
KIND_WEIGHT = {
    "assumption": 4.0, "hypothesis": 2.5, "site": 2.0, "evidence": 1.8,
    "hunk": 2.0, "file": 1.2, "issue": 3.0, "decision": 3.0,
    "prompt": 2.0, "tool_call": 1.5, "commit": 1.5, "branch": 1.0,
}


@dataclass
class TreeNode:
    id: str
    label: str
    kind: str
    detail: str = ""
    tokens: int = 0
    children: list["TreeNode"] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    falsified: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "kind": self.kind,
            "detail": self.detail[:1600], "tokens": self.tokens,
            "falsified": self.falsified, "provenance": self.provenance,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class Visit:
    node_id: str
    label: str
    kind: str
    tokens: int
    revisit: bool = False
    why: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Pass:
    name: str
    kind: str            # lookup | propagation
    visits: list[Visit] = field(default_factory=list)

    @property
    def tokens(self) -> int:
        return sum(v.tokens for v in self.visits)

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind,
                "tokens": self.tokens,
                "visits": [v.to_dict() for v in self.visits]}


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                       text=True, timeout=300)
    return p.stdout if p.returncode == 0 else ""


def _walk(node: TreeNode):
    yield node
    for c in node.children:
        yield from _walk(c)


def build_tree(repo: Path, base: str, branch: str, issue_text: str,
               ledger: list[dict] | None,
               graph: dict | None) -> TreeNode:
    root = TreeNode(f"review:{branch}", branch, "review", tokens=0)

    if issue_text:
        root.children.append(TreeNode(
            "issue", f"issue text ({len(issue_text)} chars)", "issue",
            detail=issue_text, tokens=rc.count_tokens(issue_text),
            provenance={"source": "issue tracker"}))

    # --- diff branch: files -> hunks; generated bulk summarised -----------
    names = [l for l in git(repo, "diff", "--name-only",
                            f"{base}..{branch}").splitlines() if l.strip()]
    diff_branch = TreeNode("diff", f"diff {base[:9]}..{branch} "
                                   f"({len(names)} files)", "diff-branch")
    generated: list[str] = []
    for path in names:
        if GENERATED_RE.search(path):
            generated.append(path)
            continue
        hunk = git(repo, "diff", f"{base}..{branch}", "--", path)
        if not hunk:
            continue
        fnode = TreeNode(f"file:{path}", path, "file", tokens=0,
                         provenance={"path": path,
                                     "verify": f"git diff {base[:9]}..{branch} -- {path}"})
        fnode.children.append(TreeNode(
            f"hunk:{path}", "diff hunk", "hunk", detail=hunk[:20000],
            tokens=rc.count_tokens(hunk[:20000])))
        diff_branch.children.append(fnode)
    if generated:
        summary = (f"{len(generated)} generated/snapshot files changed, e.g. "
                   + ", ".join(generated[:5]))
        diff_branch.children.append(TreeNode(
            "generated", f"generated bulk ({len(generated)})", "generated",
            detail=summary, tokens=rc.count_tokens(summary),
            provenance={"count": len(generated),
                        "verify": f"git diff --name-only {base[:9]}..{branch}"}))
    if diff_branch.children:
        root.children.append(diff_branch)

    # --- assumptions branch ------------------------------------------------
    if ledger:
        abr = TreeNode("assumptions", f"assumption ledger ({len(ledger)} "
                       "harvested)", "assumption-branch")
        for b in ledger:
            a = b.get("assumption", {})
            node = TreeNode(
                f"assumption:{a.get('id')}", str(a.get("id")), "assumption",
                detail=a.get("statement", ""), falsified=a.get("verdict") == "FALSIFIED",
                tokens=rc.count_tokens(a.get("statement", "")),
                provenance={"verdict": a.get("verdict"),
                            "source_kind": a.get("source_kind"),
                            "source_ref": a.get("source_ref", ""),
                            "severity": b.get("severity"),
                            "verify": a.get("check_cmd", "")})
            for ev in a.get("evidence") or []:
                node.children.append(TreeNode(
                    f"{node.id}:ev", "evidence", "evidence", detail=ev,
                    tokens=rc.count_tokens(ev)))
            for s in b.get("sites") or []:
                node.children.append(TreeNode(
                    f"{node.id}:site:{s.get('kind')}:{s.get('ref')}",
                    f"site: {s.get('kind')} {s.get('ref')}", "site",
                    detail=s.get("why", ""), tokens=rc.count_tokens(s.get("why", "")),
                    provenance={"kind": s.get("kind"), "ref": s.get("ref"),
                                "count": s.get("count", 1)}))
            for h in b.get("hypotheses") or []:
                node.children.append(TreeNode(
                    f"{node.id}:hyp:{h.get('id')}", h.get("failure_mode", "?"),
                    "hypothesis",
                    detail=f"{h.get('rationale', '')} expected: {h.get('expected_observation', '')}",
                    tokens=rc.count_tokens(str(h)),
                    provenance={"strategy": h.get("strategy"),
                                "priority": h.get("priority"),
                                "status": h.get("status")}))
            abr.children.append(node)
        root.children.append(abr)

    # --- capsule branch ----------------------------------------------------
    if graph:
        cap = TreeNode("capsule", "session capsule", "capsule-branch")
        for n in graph.get("nodes", []):
            t = n.get("type")
            if t not in ("PROMPT", "DECISION", "TOOL_CALL", "COMMIT", "BRANCH"):
                continue
            prov = n.get("provenance") or {}
            body = n.get("detail") or n.get("label") or ""
            if t == "DECISION":
                body = (f"question: {prov.get('question', '')} | chosen: "
                        f"{prov.get('chosen')} | rejected: "
                        f"{', '.join(prov.get('rejected') or [])}")
            cap.children.append(TreeNode(
                f"capsule:{n.get('id')}", n.get("label", ""), t.lower(),
                detail=body, tokens=rc.count_tokens(body),
                provenance={k: v for k, v in prov.items()
                            if k in ("transcript_uuid", "tool_use_id", "sha",
                                     "ref", "path", "verify")}))
        if cap.children:
            root.children.append(cap)

    # token totals: a node costs its own text; parents add context overhead
    # (labels) so the ledger reflects "what the model saw", not just hits
    for node in _walk(root):
        node.tokens += rc.count_tokens(node.label)
    return root


# ---------------------------------------------------------------------------
# traversal
# ---------------------------------------------------------------------------

def _terms(q: str) -> list[str]:
    return [t for t in re.findall(r"\w{3,}", q.lower())]


def _score(node: TreeNode, terms: list[str]) -> float:
    text = f"{node.label} {node.detail}".lower()
    hits = sum(1 for t in terms if t in text)
    return hits * KIND_WEIGHT.get(node.kind, 1.0)


def _path_from_root(root: TreeNode, target: TreeNode) -> list[TreeNode]:
    """DFS from the root to `target`; ids are unique per tree."""
    stack: list[TreeNode] = [root]
    parent: dict[int, TreeNode | None] = {id(root): None}
    found: TreeNode | None = None
    while stack:
        node = stack.pop()
        if node is target:
            found = node
            break
        for c in node.children:
            parent[id(c)] = node
            stack.append(c)
    path: list[TreeNode] = []
    cur: TreeNode | None = found
    while cur is not None:
        path.append(cur)
        cur = parent.get(id(cur))
    return path


def lookup_pass(root: TreeNode, query: str, visit_seen: set[str]) -> Pass:
    terms = _terms(query)
    # find the best entry node anywhere in the tree
    best, best_score = None, 0.0
    for node in _walk(root):
        s = _score(node, terms)
        if s > best_score:
            best, best_score = node, s
    if best is None:
        return Pass(f"lookup: {query}", "lookup")

    # the path from root to the entry node is what the review had to open
    path = _path_from_root(root, best)

    p = Pass(f"lookup: {query}", "lookup")
    for node in reversed(path):
        revisit = node.id in visit_seen
        p.visits.append(Visit(
            node.id, node.label, node.kind, node.tokens,
            revisit=revisit,
            why=("entry point" if node is best else
                 "opened on the path" if node.kind != "review" else "context root")))
    return p


def propagation_pass(root: TreeNode, visit_seen: set[str]) -> list[Pass]:
    """Recurring traversal: every FALSIFIED assumption re-enters the tree and
    its whole subtree (evidence, impact sites, pre-aimed hypotheses) is
    revisited. This is the blast radius, expressed as tree traversal."""
    passes: list[Pass] = []
    for node in _walk(root):
        if not node.falsified:
            continue
        p = Pass(f"propagate: {node.id}", "propagation")
        p.visits.append(Visit(node.id, node.label, node.kind, node.tokens,
                              revisit=node.id in visit_seen,
                              why="falsified claim - re-enter the tree"))
        for child in node.children:
            p.visits.append(Visit(child.id, child.label, child.kind,
                                  child.tokens, revisit=child.id in visit_seen,
                                  why="blast-radius footprint"))
        passes.append(p)
    return passes


def build_traversal(root: TreeNode, queries: list[str],
                    ledger: list[dict] | None) -> tuple[list[Pass], dict]:
    seen: set[str] = set()
    passes: list[Pass] = []
    for q in queries:
        p = lookup_pass(root, q, seen)
        passes.append(p)
        for v in p.visits:
            seen.add(v.node_id)

    prop = propagation_pass(root, seen)
    passes += prop
    for p in prop:
        for v in p.visits:
            seen.add(v.node_id)

    falsified = [n.id for n in _walk(root) if n.falsified]
    totals = {
        "lookup_tokens": sum(p.tokens for p in passes if p.kind == "lookup"),
        "propagation_tokens": sum(p.tokens for p in passes if p.kind == "propagation"),
        "total_tokens": sum(p.tokens for p in passes),
        "nodes_visited": len(seen),
        "revisits": sum(1 for p in passes for v in p.visits if v.revisit),
        "falsified_assumptions": len(falsified),
    }
    return passes, totals


# ---------------------------------------------------------------------------
# baselines: a traditional agent that reads the raw diff
# ---------------------------------------------------------------------------

def baselines(repo: Path, base: str, branch: str, issue_text: str,
              root: TreeNode) -> dict:
    full_ev, nfiles = evidence_full(repo, base, branch, triaged=False)
    triaged_ev, kept = evidence_full(repo, base, branch, triaged=True)
    full_dump = sum(n.tokens for n in _walk(root))
    return {
        "tree_nodes": len(list(_walk(root))),
        "full_tree_dump_tokens": full_dump,
        "traditional_full_prompt_tokens":
            rc.count_tokens(full_ev) + rc.count_tokens(issue_text),
        "traditional_triaged_prompt_tokens":
            rc.count_tokens(triaged_ev) + rc.count_tokens(issue_text),
        "traditional_full_files": nfiles,
        "traditional_triaged_files": kept,
        "note": "traditional arms are prompt-token estimates (tiktoken "
                "cl100k_base); finding QUALITY for a live agent is not "
                "measured in dry-run mode",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

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
    ap.add_argument("--ledger", help="engine.py output JSON")
    ap.add_argument("--graph", help="capsule graph JSON")
    ap.add_argument("--query", action="append", default=[],
                    help="a reviewer question; repeatable")
    ap.add_argument("--json", help="write the tree + traversal here")
    ap.add_argument("--html", help="also render a standalone HTML viewer")
    args = ap.parse_args(argv)

    issue_text = ""
    if args.issue and Path(args.issue).exists():
        issue_text = Path(args.issue).read_text(encoding="utf-8")

    ledger = None
    if args.ledger and Path(args.ledger).exists():
        ledger = json.loads(Path(args.ledger).read_text(encoding="utf-8"))

    graph = None
    if args.graph and Path(args.graph).exists():
        graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))

    root = build_tree(Path(args.repo).resolve(), args.base, args.branch,
                      issue_text, ledger, graph)
    queries = args.query or [
        "why is the attribute guarded by a target framework",
        "which target frameworks do the tests cover versus the library ships",
    ]
    passes, totals = build_traversal(root, queries, ledger)

    data = {
        "branch": args.branch, "base": args.base,
        "tree": root.to_dict(),
        "passes": [p.to_dict() for p in passes],
        "totals": totals,
        "baselines": baselines(Path(args.repo).resolve(), args.base,
                               args.branch, issue_text, root),
    }

    print(f"tree nodes  : {data['baselines']['tree_nodes']}")
    print(f"full dump   : {data['baselines']['full_tree_dump_tokens']} tokens")
    for p in passes:
        mark = "REVISITS" if any(v.revisit for v in p.visits) else ""
        print(f"  [{p.kind:11}] {p.name[:70]:70} {p.tokens:>7} tokens {mark}")
    t = totals
    print(f"walk total  : {t['total_tokens']} tokens over {t['nodes_visited']} "
          f"nodes, {t['revisits']} revisits, {t['falsified_assumptions']} "
          f"falsified assumption(s)")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        print(f"wrote {out.resolve()}")

    if args.html:
        from render_tree import render
        out = Path(args.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render(data), encoding="utf-8")
        print(f"wrote {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
