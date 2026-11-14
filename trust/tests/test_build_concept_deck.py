"""
Tests for trust.present.build_concept_deck - the backend-driven replay deck.

The deck's example must come from the backend review, not from hand-written
HTML: rows carry per-step statuses computed from claim verdicts, every row
has a token estimate, the VS comparison uses the real claim counts, and the
generated HTML keeps a well-formed single script block.
"""

from __future__ import annotations

import json

import build_concept_deck as bcd
import proof_review as pr


REVIEW = {
    "log": ["aa40be6|PR #4: cap discounts (AI patch)",
            "1e5307b|PR #3: bulk, member, checkout, ledger, tests",
            "570018d|PR #2: coupons",
            "dd84922|PR #1: final_price"],
    "claims": [
        {"id": "A1", "label": "Refuted",
         "formula": "FORALL b in BASKETS: total(b) >= 0",
         "example": "A shopper with a HALF coupon, 10 items, a member is "
                    "charged -100."},
        {"id": "A2", "label": "Refuted", "example": "README says never."},
        {"id": "P1", "label": "Proved within scope", "example": ""},
        {"id": "B1", "label": "Refuted", "example": ""},
        {"id": "B2", "label": "Refuted", "example": "VIP gets 50%, not 60%."},
        {"id": "T1", "label": "Tested", "example": ""},
        {"id": "T2", "label": "Refuted", "example": ""},
        {"id": "U1", "label": "Unknown", "example": ""},
        {"id": "D1", "label": "Refuted", "example": ""},
        {"id": "D2", "label": "Refuted", "example": ""},
    ],
}


def test_entries_built_from_backend_review():
    entries, comparison = bcd.build_entries(REVIEW)
    assert len(entries) == 4
    assert all("tokens" in e and e["tokens"] >= 1 for e in entries)
    # the backend refutation of A1 drives the row status at steps 3 and 4
    assert entries[0]["at"][2]["status"] == "BREACHED"
    assert entries[0]["at"][3]["status"] == "BREACHED"
    # the backend refutation of B2 drives row 2's final status
    assert entries[1]["at"][3]["status"] == "BREACHED"


def test_comparison_uses_real_claim_counts():
    _, comparison = bcd.build_entries(REVIEW)
    assert comparison["pipeline"]["beliefs"] == 10
    assert comparison["pipeline"]["refuted"] == 7
    assert comparison["pipeline"]["tokens"] > comparison["replay"]["tokens"]
    assert comparison["pipeline"]["agent_context"] is True
    assert comparison["replay"]["checked"] == 0


def test_entries_carry_drill_down_truths_from_claims():
    entries, _ = bcd.build_entries(REVIEW)
    t = entries[0]["truth"][0]
    assert t["id"] == "A1" and t["label"] == "Refuted"
    assert t["formula"] and t["command"].endswith("--check A1")
    # the final row drills into the refuted main claims of the story
    ids = [x["id"] for x in entries[3]["truth"]]
    assert "A1" in ids and "B2" in ids


def test_build_keeps_one_well_formed_script_block():
    template = ("<html><head><style>x{}</style></head><body>"
                "<script>\nconst S='x',by=id=>id,svg=null;\nrender();\n</script>"
                "</body></html>")
    html = bcd.build(REVIEW, template)
    assert html.count("<script>") == 1, "exactly one inline script"
    assert html.rstrip().endswith("</html>")
    assert "const example=" in html and "const comparison=" in html
    assert "vs-strip" in html and "vsbtn" in html


def test_proof_hierarchy_aggregates_sub_claims(tmp_path):
    import subprocess
    from pathlib import Path
    from test_proof_review import synthetic_repo  # shared fixture logic
    r = synthetic_repo(tmp_path)
    review = pr.build(r["path"], r["base"], r["branch"], "")
    h = review.hierarchy
    assert h["main"] == "C-2297-0"
    assert h["main_verdict"] == "REFUTED"
    assert h["sub_verdicts"]["C-2297-1"] == "REFUTED"
    assert h["sub_verdicts"]["C-2297-2"] == "PROVED_IN_SCOPE"
    # the main claim is stated once and depends on its sub-claims
    main = next(c for c in review.claims if c.id == "C-2297-0")
    assert main.level == "main" and main.depends_on == [
        "C-2297-1", "C-2297-2", "C-2297-3"]
