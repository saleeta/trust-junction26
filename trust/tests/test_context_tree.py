"""
Tests for trust.tree.context_tree - the offline traversal engine.

The properties that matter:
- a lookup visits only the path from the root to the entry node;
- a falsified assumption triggers a propagation pass over its subtree;
- revisits are counted as revisits (the recurring-traversal signal);
- token accounting sums what was actually visited, not the whole tree.
"""

from __future__ import annotations

import context_tree as ct


def sample_tree() -> ct.TreeNode:
    root = ct.TreeNode("review:x", "x", "review", tokens=10)
    issue = ct.TreeNode("issue", "issue text", "issue", tokens=100)
    abr = ct.TreeNode("assumptions", "ledger", "assumption-branch", tokens=5)
    a1 = ct.TreeNode("assumption:a1", "a1", "assumption",
                     detail="the attribute is unavailable on net472",
                     tokens=50, falsified=True)
    a1.children = [
        ct.TreeNode("assumption:a1:site", "site net472", "site",
                    detail="shipped but excluded", tokens=20),
        ct.TreeNode("assumption:a1:hyp", "feature_absent", "hypothesis",
                    detail="feature absent on target", tokens=30),
    ]
    a2 = ct.TreeNode("assumption:a2", "a2", "assumption",
                     detail="tests observe the change", tokens=40,
                     falsified=False)
    abr.children = [a1, a2]
    root.children = [issue, abr]
    return root


def test_lookup_visits_only_the_path_to_the_entry():
    root = sample_tree()
    p = ct.lookup_pass(root, "attribute unavailable net472", set())
    ids = [v.node_id for v in p.visits]
    assert ids == ["review:x", "assumptions", "assumption:a1"], ids
    assert p.tokens == 10 + 5 + 50


def test_lookup_with_no_match_is_an_empty_pass():
    root = sample_tree()
    p = ct.lookup_pass(root, "zzzqqq", set())
    assert p.visits == [] and p.tokens == 0


def test_falsified_assumption_triggers_propagation_over_subtree():
    root = sample_tree()
    passes = ct.propagation_pass(root, set())
    assert len(passes) == 1, "only the falsified assumption propagates"
    p = passes[0]
    kinds = [v.node_id for v in p.visits]
    assert kinds == ["assumption:a1", "assumption:a1:site",
                     "assumption:a1:hyp"], kinds
    assert p.tokens == 50 + 20 + 30


def test_revisit_is_marked_when_propagation_touches_a_visited_node():
    root = sample_tree()
    seen = set()
    lp = ct.lookup_pass(root, "attribute unavailable", seen)
    seen.update(v.node_id for v in lp.visits)
    prop = ct.propagation_pass(root, seen)
    assert any(v.revisit for p in prop for v in p.visits), \
        "the propagation pass re-enters nodes the lookup already saw"


def test_totals_are_measured_not_estimated():
    root = sample_tree()
    passes, totals = ct.build_traversal(root, ["attribute unavailable"], None)
    assert totals["total_tokens"] == sum(p.tokens for p in passes)
    assert totals["falsified_assumptions"] == 1
    assert totals["nodes_visited"] == len(
        {v.node_id for p in passes for v in p.visits})


def test_tree_token_total_covers_every_node():
    root = sample_tree()
    assert ct.baselines(None, "", "", "", root)["full_tree_dump_tokens"] \
        == sum(n.tokens for n in ct._walk(root))
