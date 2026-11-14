"""
Tests for trust.tree.mongo_tree - the MongoDB Atlas backend.

Offline tests cover the document construction contract: every tree node
becomes a node document, every parent-child link becomes an edge document
with the direction $graphLookup expects (from_id=parent, to_id=child).
Live tests run only when MONGO_TEST_URI points at a reachable deployment.
"""

from __future__ import annotations

import os

import pytest

import context_tree as ct
import mongo_tree as mt


def sample_tree_dict() -> dict:
    root = ct.TreeNode("review:x", "x", "review", tokens=10)
    a = ct.TreeNode("assumption:a1", "a1", "assumption",
                    detail="attr unavailable on net472", tokens=50,
                    falsified=True)
    a.children = [ct.TreeNode("assumption:a1:site", "site", "site",
                              detail="shipped but excluded", tokens=20)]
    root.children = [ct.TreeNode("issue", "issue", "issue", tokens=30), a]
    return root.to_dict()


# ---------------------------------------------------------------------------
# offline: document construction
# ---------------------------------------------------------------------------

def test_build_docs_flattens_tree_into_nodes_and_edges():
    nodes, edges = mt.build_docs(sample_tree_dict(), "t")
    ids = {n["_id"] for n in nodes}
    assert ids == {"review:x", "issue", "assumption:a1", "assumption:a1:site"}
    assert all(n["tree"] == "t" for n in nodes)

    edge_pairs = {(e["from_id"], e["to_id"]) for e in edges}
    assert edge_pairs == {
        ("review:x", "issue"),
        ("review:x", "assumption:a1"),
        ("assumption:a1", "assumption:a1:site"),
    }
    assert all(e["type"] == "contains" for e in edges)


def test_build_docs_preserves_falsified_and_tokens():
    nodes, _ = mt.build_docs(sample_tree_dict(), "t")
    a = next(n for n in nodes if n["_id"] == "assumption:a1")
    assert a["falsified"] is True and a["tokens"] == 50


def test_edge_direction_matches_graphlookup_contract():
    """from_id=parent, to_id=child: $graphLookup can climb child->parent via
    connectFromField=to_id / connectToField=from_id."""
    _, edges = mt.build_docs(sample_tree_dict(), "t")
    for e in edges:
        assert e["from_id"] != e["to_id"]
        assert e["from_id"] in {"review:x", "assumption:a1"}


# ---------------------------------------------------------------------------
# live (only with MONGO_TEST_URI)
# ---------------------------------------------------------------------------

URI = os.environ.get("MONGO_TEST_URI")


@pytest.mark.skipif(not URI, reason="set MONGO_TEST_URI to run Atlas tests")
def test_live_graphlookup_path_and_descendants():
    atlas = mt.AtlasTree(URI, "trust_demo_test")
    tree_name = "test_tree"
    atlas.ingest(sample_tree_dict(), tree_name)

    path = atlas.path_to_root("assumption:a1:site")
    assert [p["node_id"] for p in path] == ["review:x", "assumption:a1",
                                            "assumption:a1:site"], path
    assert path[0]["depth"] == 1, "root is one graphLookup hop from the site"
    assert path[2]["depth"] == 2, "the entry node carries the largest depth"

    sub = atlas.descendants("assumption:a1")
    assert [s["node_id"] for s in sub] == ["assumption:a1",
                                           "assumption:a1:site"]

    # token ledger via aggregation pipeline
    assert atlas.tokens_of(["assumption:a1", "assumption:a1:site"]) == 70

    passes = atlas.run_passes(["attr unavailable net472"], tree_name)
    kinds = [p["kind"] for p in passes]
    assert "lookup" in kinds and "propagation" in kinds
    assert atlas.traversals.count_documents({"tree": tree_name}) == len(passes)

    atlas.nodes.delete_many({"tree": tree_name})
    atlas.edges.delete_many({"tree": tree_name})
    atlas.traversals.delete_many({"tree": tree_name})
