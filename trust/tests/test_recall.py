"""
Tests for the graph retrieval API.

Two properties are non-negotiable: every hit carries a citation, and the token
budget is actually enforced. A retrieval layer that silently exceeds its budget
or returns uncited text defeats the purpose of having one.
"""

from __future__ import annotations

import json

import pytest

import recall as rc


@pytest.fixture
def store():
    s = rc.Store(":memory:")
    yield s
    s.close()


@pytest.fixture
def filled(store):
    store.ingest_text("issue", "Add ExcludeFromCodeCoverage to all generated "
                               "code. I do not feel a setting is needed.",
                      ref="2297.md", provenance={"source": "issue tracker"})
    store.add("assumption", "tfm-guard-0",
              "ASSUMPTION: the attribute is unavailable on netstandard2.0\n"
              "VERDICT: FALSIFIED",
              {"verdict": "FALSIFIED", "verify": "dotnet build probe.csproj"},
              weight=3.0)
    store.add("diff", "src/Templates/EnumTemplate.tt",
              "+#if !NETSTANDARD2_0\n+[ExcludeFromCodeCoverage]\n+#endif",
              {"path": "src/Templates/EnumTemplate.tt",
               "verify": "git diff -- src/Templates/EnumTemplate.tt"},
              path="src/Templates/EnumTemplate.tt", symbol="EnumTemplate")
    store.add("graph:DECISION", "decision:1",
              "QUESTION: which engine?\nCHOSEN: hybrid\nREJECTED: differential",
              {"question": "which engine?", "chosen": "hybrid",
               "transcript_uuid": "abcdef1234"}, weight=3.0)
    store.db.commit()
    return store


# ---------------------------------------------------------------------------
# citations
# ---------------------------------------------------------------------------

def test_every_hit_carries_a_citation(filled):
    r = filled.recall("netstandard2.0 attribute", budget_tokens=5000)
    assert r.hits
    for h in r.hits:
        assert h.citation
        assert h.kind in h.citation


def test_citation_surfaces_a_verify_command(filled):
    r = filled.recall("unavailable netstandard2.0", budget_tokens=5000)
    cited = [h for h in r.hits if "verify:" in h.citation]
    assert cited, "evidence with a verify command must advertise it"


def test_citation_marks_reconstructed_evidence(store):
    store.add("assumption", "recon-1", "some reconstructed claim",
              {"reconstructed": True})
    store.db.commit()
    r = store.recall("reconstructed claim", budget_tokens=5000)
    assert any("RECONSTRUCTED" in h.citation for h in r.hits)


def test_as_context_includes_citations(filled):
    r = filled.recall("attribute", budget_tokens=5000)
    ctx = r.as_context()
    assert ctx
    for h in r.hits:
        assert h.citation in ctx


# ---------------------------------------------------------------------------
# budget enforcement
# ---------------------------------------------------------------------------

def test_budget_is_enforced(filled):
    r = filled.recall("attribute generated code netstandard", budget_tokens=30)
    assert r.tokens_used <= 30
    assert r.hits_dropped_for_budget > 0


def test_zero_budget_returns_nothing_but_reports_drops(filled):
    r = filled.recall("attribute", budget_tokens=0)
    assert r.hits == []
    assert r.hits_dropped_for_budget > 0


def test_tokens_used_matches_sum_of_hits(filled):
    r = filled.recall("attribute netstandard", budget_tokens=5000)
    assert r.tokens_used == sum(h.tokens for h in r.hits)


def test_full_dump_tokens_exceeds_recall(filled):
    r = filled.recall("netstandard2.0", budget_tokens=200)
    assert r.full_dump_tokens > r.tokens_used
    assert 0 < r.saving_ratio <= 1


def test_saving_ratio_is_zero_without_a_dump_baseline():
    r = rc.Recall(query="q", mode="question")
    assert r.saving_ratio == 0.0


# ---------------------------------------------------------------------------
# retrieval modes
# ---------------------------------------------------------------------------

def test_path_mode(filled):
    r = filled.recall("EnumTemplate.tt", mode="path", budget_tokens=5000)
    assert r.hits
    assert all("EnumTemplate" in h.ref for h in r.hits)


def test_symbol_mode(filled):
    r = filled.recall("EnumTemplate", mode="symbol", budget_tokens=5000)
    assert r.hits


def test_question_mode_ranks_assumption_above_raw_diff(filled):
    """Weighting must put the assumption ledger ahead of a diff hunk."""
    r = filled.recall("is the attribute unavailable on netstandard2.0",
                      budget_tokens=5000)
    assert r.hits
    assert r.hits[0].kind in ("assumption", "issue")


def test_miss_is_not_silent(filled):
    """An FTS miss falls back to LIKE rather than returning nothing."""
    r = filled.recall("ExcludeFromCodeCoverage", budget_tokens=5000)
    assert r.candidates_considered > 0


def test_unmatched_query_returns_empty_not_error(filled):
    r = filled.recall("zzzzz nonexistent token qqqq", budget_tokens=500)
    assert r.hits == [] or all(h.score >= 0 for h in r.hits)


# ---------------------------------------------------------------------------
# ingestion
# ---------------------------------------------------------------------------

def test_ingest_graph_keeps_decision_alternatives(store):
    graph = {"nodes": [{
        "id": "decision:1", "type": "DECISION", "label": "l", "detail": "d",
        "provenance": {"question": "A or B?", "chosen": "A",
                       "rejected": ["B", "C"]}}]}
    assert store.ingest_graph(graph) == 1
    r = store.recall("A or B", budget_tokens=5000)
    assert any("REJECTED: B, C" in h.snippet for h in r.hits)


def test_ingest_graph_skips_uninteresting_node_types(store):
    graph = {"nodes": [
        {"id": "f", "type": "FILE", "label": "x.cs", "detail": "x.cs",
         "provenance": {}},
        {"id": "p", "type": "PROMPT", "label": "hi", "detail": "hi there",
         "provenance": {}}]}
    assert store.ingest_graph(graph) == 1, "FILE nodes are not evidence rows"


def test_empty_text_is_not_stored(store):
    assert store.add("k", "r", "   ", {}) == -1
    assert store.size == 0


def test_ingest_diff_summarises_generated_bulk(divergent_repo, store):
    n = store.ingest_diff(divergent_repo["path"], divergent_repo["B"],
                          divergent_repo["branch"])
    assert n >= 1
    r = store.recall("Thing", mode="path", budget_tokens=5000)
    assert r.hits


def test_store_persists_to_disk(tmp_path):
    db = tmp_path / "m.db"
    s1 = rc.Store(db)
    s1.ingest_text("issue", "persisted body text", ref="i")
    s1.close()

    s2 = rc.Store(db)
    assert s2.size == 1
    assert s2.recall("persisted", budget_tokens=500).hits
    s2.close()


# ---------------------------------------------------------------------------
# token accounting honesty
# ---------------------------------------------------------------------------

def test_estimated_flag_is_reported(filled):
    r = filled.recall("attribute", budget_tokens=500)
    assert isinstance(r.estimated, bool)
    assert ("estimated" in r.summary()) == r.estimated


def test_count_tokens_is_monotonic():
    assert rc.count_tokens("") == 0
    assert rc.count_tokens("a" * 400) > rc.count_tokens("a" * 40)


# ---------------------------------------------------------------------------
# snippet focusing
# ---------------------------------------------------------------------------

def test_focus_centres_on_the_query_not_the_prefix():
    text = ("A" * 3000) + " NEEDLE_TOKEN here " + ("B" * 3000)
    out = rc._focus(text, "NEEDLE_TOKEN", 300)
    assert "NEEDLE_TOKEN" in out
    assert len(out) <= 320


def test_focus_returns_short_text_untouched():
    assert rc._focus("short", "q", 100) == "short"


@pytest.mark.parametrize("q", ["", "   ", "a", "!!!"])
def test_fts_query_never_crashes(filled, q):
    filled.recall(q, budget_tokens=100)
