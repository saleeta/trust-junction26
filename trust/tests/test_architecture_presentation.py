"""The stage deck keeps the technical story accurate and within two minutes."""

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_timed_architecture_deck_and_published_copy():
    source = (ROOT / "demo/architecture-presentation.html").read_text(encoding="utf-8")
    published = (ROOT / "docs/architecture-presentation.html").read_text(encoding="utf-8")
    assert source == published
    durations = [int(n) for n in re.findall(r'data-duration="(\d+)"', source)]
    assert len(durations) == 10 and sum(durations) == 120
    for fact in ("Requirements", "Current code", "Entire", "MongoDB Atlas",
                 "$graphLookup", "CANDIDATE CLAIM", "source_kind: implicit_in_code",
                 "check_cmd:", "parent SHA", "Run check",
                 "unconfirmed → check", "Scoped formal verification",
                 "Human decision", "Revocable",
                 "Five PRs", "review-all-prs.html", "12.7k", "36.6k",
                 "basic AI: whole diff",
                 "not add-ons", "context + ledger", "foobar", "Trail #3",
                 "brain-compare.html", "audit ledger"):
        assert fact.lower() in source.lower()
    assert 'href="review-2297.html"' in source
    assert 'href="claim-tableau.html"' in source
    assert (ROOT / "demo/claim-tableau.html").read_text(encoding="utf-8") == (
        ROOT / "docs/claim-tableau.html").read_text(encoding="utf-8")
    # the deep-dive layer: formal logic, node joins, verdict rules,
    # codebase-wide re-checking, and the named acceptance
    for fact in ("detailsBtn", "∀ xs ∈ LISTS", "harvested-from",
                 "R-RUN", "R-CALL", "R-HIST", "one witness refutes",
                 "PROVED IN SCOPE", "Saleeta Qadir", "empty list",
                 "average([])", "ZeroDivisionError", "never crash", "counterexample"):
        assert fact.lower() in source.lower()
    # the old target-framework example is gone from the stage story
    for gone in ("netstandard2.0", "net472", "ExcludeFromCodeCoverage"):
        assert gone.lower() not in source.lower()
    script = ("new Function(require('fs').readFileSync(process.argv[1],'utf8')"
              ".split('<script>')[1].split('</script>')[0])")
    subprocess.run(["node", "-e", script, str(ROOT / "demo/architecture-presentation.html")],
                   check=True, capture_output=True, text=True)
