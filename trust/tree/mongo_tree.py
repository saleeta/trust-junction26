"""MongoDB Atlas backend for the context tree.

This is the challenge-track integration: the context tree lives in Atlas, and
the demo's two traversal questions are answered with real Mongo features.

    question -> entry node          $graphLookup (path to root, depthField)
    falsified claim -> blast radius $graphLookup (subtree from the node)
    token ledger per pass           aggregation pipeline ($match/$group/$sum)
    audit trail                     a `traversals` collection (one doc per pass)

COLLECTIONS (db: trust_demo)
----------------------------
    nodes        one document per tree node; heterogeneous kinds, embedded
                 provenance, token cost. `_id` = the tree node id.
    edges        {from_id: parent, to_id: child, type: "contains"} - the tree
                 structure as references, so $graphLookup does the walking.
    traversals   one document per pass: query, visited ids, tokens, revisits.

The same JSON the offline `context_tree.py` emits comes back out, so the HTML
renderer works identically whether the walk ran in-process or on Atlas.

Usage:
    MONGO_URI="mongodb+srv://..." python mongo_tree.py --repo ../../repo \
        --branch origin/ju26-issue-2297 --base 32258fdb \
        --issue ../../.trust/issues/2297.md \
        --ledger ../../.trust/findings/2297-blast.json \
        --json ../../.trust/tree/2297-tree.mongo.json

No MONGO_URI -> exit 2 with a clear message; the demo falls back to
context_tree.py, and the output says which backend ran.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "memory"))

import context_tree as ct   # noqa: E402
import recall as rc         # noqa: E402

KIND_WEIGHT = ct.KIND_WEIGHT


# ---------------------------------------------------------------------------
# pure doc construction (testable offline)
# ---------------------------------------------------------------------------

def build_docs(tree: dict, tree_name: str) -> tuple[list[dict], list[dict]]:
    """Flatten the nested tree into nodes + edges documents."""
    nodes: list[dict] = []
    edges: list[dict] = []

    def walk(node: dict, parent: str | None) -> None:
        nodes.append({
            "_id": node["id"],
            "tree": tree_name,
            "kind": node.get("kind"),
            "label": node.get("label"),
            "detail": (node.get("detail") or "")[:1600],
            "tokens": node.get("tokens", 0),
            "falsified": node.get("falsified", False),
            "provenance": node.get("provenance", {}),
        })
        if parent is not None:
            edges.append({
                "_id": f"{parent}->{node['id']}",
                "tree": tree_name,
                "from_id": parent,       # parent
                "to_id": node["id"],     # child
                "type": "contains",
            })
        for c in node.get("children", []):
            walk(c, node["id"])

    walk(tree, None)
    return nodes, edges


# ---------------------------------------------------------------------------
# the Atlas store
# ---------------------------------------------------------------------------

class AtlasTree:
    def __init__(self, uri: str, db_name: str = "trust_demo"):
        import pymongo  # deferred: the offline path must not require it
        self.client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=8000)
        self.db = self.client[db_name]
        self.nodes = self.db.nodes
        self.edges = self.db.edges
        self.traversals = self.db.traversals
        # the graph lookups need an index on the joined fields
        self.edges.create_index([("from_id", 1)])
        self.edges.create_index([("to_id", 1)])
        self.traversals.create_index([("tree", 1), ("ts", -1)])

    def ping(self) -> dict:
        return self.client.admin.command("ping")

    # -- ingest -------------------------------------------------------------
    def ingest(self, tree: dict, tree_name: str) -> tuple[int, int]:
        nodes, edges = build_docs(tree, tree_name)
        if nodes:
            self.nodes.delete_many({"tree": tree_name})
        if edges:
            self.edges.delete_many({"tree": tree_name})
        if nodes:
            self.nodes.insert_many(nodes, ordered=False)
        if edges:
            self.edges.insert_many(edges, ordered=False)
        return len(nodes), len(edges)

    # -- the two traversal primitives ---------------------------------------
    def path_to_root(self, node_id: str) -> list[dict]:
        """$graphLookup walking child->parent along the `contains` edges.

        The result is the actual lookup path, with `depth` attached by Mongo.
        """
        pipeline = [
            {"$match": {"_id": node_id}},
            {"$graphLookup": {
                "from": "edges",
                "startWith": "$_id",
                "connectFromField": "to_id",     # current node is the child
                "connectToField": "from_id",     # jump to its parent
                "as": "ancestors",
                "depthField": "depth",
                "maxDepth": 50,
            }},
        ]
        rows = list(self.nodes.aggregate(pipeline))
        if not rows:
            return []
        row = rows[0]
        path = [{"node_id": node_id, "depth": 0,
                 "label": row.get("label"), "kind": row.get("kind"),
                 "tokens": row.get("tokens", 0)}]
        for a in sorted(row.get("ancestors", []),
                        key=lambda x: x.get("depth", 0)):
            path.append({"node_id": a["_id"], "depth": a.get("depth", 0),
                         "label": a.get("label"), "kind": a.get("kind"),
                         "tokens": a.get("tokens", 0)})
        path.sort(key=lambda p: p["depth"], reverse=True)   # root first
        return path

    def descendants(self, node_id: str) -> list[dict]:
        """$graphLookup walking parent->child: the blast radius as traversal."""
        pipeline = [
            {"$match": {"_id": node_id}},
            {"$graphLookup": {
                "from": "edges",
                "startWith": "$_id",
                "connectFromField": "from_id",     # current node is the parent
                "connectToField": "to_id",         # jump to its children
                "as": "subtree",
                "depthField": "depth",
                "maxDepth": 50,
            }},
        ]
        rows = list(self.nodes.aggregate(pipeline))
        if not rows:
            return []
        row = rows[0]
        out = [{"node_id": node_id, "depth": 0, "label": row.get("label"),
                "kind": row.get("kind"), "tokens": row.get("tokens", 0)}]
        for a in sorted(row.get("subtree", []),
                        key=lambda x: x.get("depth", 0)):
            out.append({"node_id": a["_id"], "depth": a.get("depth", 0),
                        "label": a.get("label"), "kind": a.get("kind"),
                        "tokens": a.get("tokens", 0)})
        return out

    # -- entry point ---------------------------------------------------------
    def find_entry(self, query: str) -> str | None:
        """Regex over label+detail, ranked by the tree's kind weights.

        On Atlas this is the place an Atlas Search index would live; the
        fallback regex keeps the same contract on any deployment.
        """
        terms = [t for t in re.findall(r"\w{3,}", query.lower())]
        pats = [re.compile(re.escape(t), re.I) for t in terms]
        best, best_score = None, 0.0
        for doc in self.nodes.find({}, {"_id": 1, "kind": 1, "label": 1,
                                        "detail": 1, "tokens": 1}):
            text = f"{doc.get('label', '')} {doc.get('detail', '')}".lower()
            hits = sum(1 for p in pats if p.search(text))
            score = hits * KIND_WEIGHT.get(doc.get("kind"), 1.0)
            if score > best_score:
                best, best_score = doc["_id"], score
        return best

    # -- token ledger: aggregation, not arithmetic ----------------------------
    def tokens_of(self, node_ids: list[str]) -> int:
        if not node_ids:
            return 0
        rows = list(self.nodes.aggregate([
            {"$match": {"_id": {"$in": node_ids}}},
            {"$group": {"_id": None, "tokens": {"$sum": "$tokens"}}},
        ]))
        return int(rows[0]["tokens"]) if rows else 0

    # -- the review passes -----------------------------------------------------
    def run_passes(self, queries: list[str], tree_name: str) -> list[dict]:
        """The same two pass kinds as context_tree.py, executed on Atlas."""
        passes: list[dict] = []
        seen: set[str] = set()
        for q in queries:
            entry = self.find_entry(q)
            path = self.path_to_root(entry) if entry else []
            visits = []
            for i, p in enumerate(path):
                visits.append({
                    "node_id": p["node_id"], "label": p["label"],
                    "kind": p["kind"], "tokens": p["tokens"],
                    "revisit": p["node_id"] in seen,
                    "why": ("entry point" if p["depth"] == 0 else
                            "context root" if i == 0 else "opened on the path"),
                })
            passes.append({"name": f"lookup: {q}", "kind": "lookup",
                           "visits": visits,
                           "tokens": self.tokens_of([v["node_id"] for v in visits])})
            seen.update(v["node_id"] for v in visits)

        for doc in self.nodes.find({"falsified": True, "tree": tree_name},
                                   {"_id": 1}):
            sub = self.descendants(doc["_id"])
            visits = [{
                "node_id": s["node_id"], "label": s["label"], "kind": s["kind"],
                "tokens": s["tokens"], "revisit": s["node_id"] in seen,
                "why": ("falsified claim - re-enter the tree" if s["depth"] == 0
                        else "blast-radius footprint"),
            } for s in sub]
            passes.append({"name": f"propagate: {doc['_id']}",
                           "kind": "propagation", "visits": visits,
                           "tokens": self.tokens_of([v["node_id"] for v in visits])})
            seen.update(v["node_id"] for v in visits)

        # audit trail: every pass is a document
        self.traversals.delete_many({"tree": tree_name})
        self.traversals.insert_many([{
            "tree": tree_name, "ts": datetime.now(timezone.utc),
            "pass": p["name"], "kind": p["kind"], "tokens": p["tokens"],
            "visited_ids": [v["node_id"] for v in p["visits"]],
            "revisits": sum(1 for v in p["visits"] if v["revisit"]),
        } for p in passes])
        return passes


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
    ap.add_argument("--uri", default=os.environ.get("MONGO_URI"),
                    help="MongoDB Atlas connection string (default: $MONGO_URI)")
    ap.add_argument("--db", default="trust_demo")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--branch", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--issue")
    ap.add_argument("--ledger")
    ap.add_argument("--query", action="append", default=[])
    ap.add_argument("--json", help="output in the same schema as context_tree.py")
    args = ap.parse_args(argv)

    if not args.uri:
        print("no MONGO_URI: Atlas backend not configured", file=sys.stderr)
        print("fall back to context_tree.py, or set MONGO_URI to your Atlas "
              "connection string", file=sys.stderr)
        return 2

    issue_text = ""
    if args.issue and Path(args.issue).exists():
        issue_text = Path(args.issue).read_text(encoding="utf-8")
    ledger = None
    if args.ledger and Path(args.ledger).exists():
        ledger = json.loads(Path(args.ledger).read_text(encoding="utf-8"))

    root = ct.build_tree(Path(args.repo).resolve(), args.base, args.branch,
                         issue_text, ledger, None)
    tree_name = re.sub(r"[^A-Za-z0-9_-]", "_", args.branch)

    atlas = AtlasTree(args.uri, args.db)
    print(f"atlas ping : {atlas.ping().get('ok') == 1.0 and 'ok' or 'FAILED'}")

    n_nodes, n_edges = atlas.ingest(root.to_dict(), tree_name)
    print(f"ingested   : {n_nodes} node documents, {n_edges} edge documents "
          f"(db {args.db})")

    queries = args.query or [
        "why is the attribute guarded by a target framework",
        "which target frameworks do the tests cover versus the library ships",
    ]
    passes = atlas.run_passes(queries, tree_name)

    totals = {
        "lookup_tokens": sum(p["tokens"] for p in passes if p["kind"] == "lookup"),
        "propagation_tokens": sum(p["tokens"] for p in passes if p["kind"] == "propagation"),
        "total_tokens": sum(p["tokens"] for p in passes),
        "nodes_visited": len({v["node_id"] for p in passes for v in p["visits"]}),
        "revisits": sum(1 for p in passes for v in p["visits"] if v["revisit"]),
        "falsified_assumptions": atlas.nodes.count_documents(
            {"tree": tree_name, "falsified": True}),
    }

    for p in passes:
        rev = sum(1 for v in p["visits"] if v["revisit"])
        print(f"  [{p['kind']:11}] {p['name'][:70]:70} {p['tokens']:>7} tokens"
              + (f"  REVISITS {rev}" if rev else ""))
    t = totals
    print(f"walk total : {t['total_tokens']} tokens over {t['nodes_visited']} "
          f"nodes, {t['revisits']} revisits (computed by Mongo aggregation)")

    data = {
        "branch": args.branch, "base": args.base,
        "backend": f"mongodb-atlas::{args.db}",
        "tree": root.to_dict(), "passes": passes, "totals": totals,
        "baselines": ct.baselines(Path(args.repo).resolve(), args.base,
                                  args.branch, issue_text, root),
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        print(f"wrote {out.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
