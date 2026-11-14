"""
Tests for the LLM cost arms and the generated repro.

For `llm_arm` the thing worth testing is that the baselines are FAIR: the
triaged dump must really drop generated files, and recall must really carry
citations, or the comparison is theatre.

For `make_repro` the thing worth testing is that the generated test fails for
the right reason and cannot pass vacuously.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import llm_arm as la
import make_repro as mr
import recall as rc
import tfm_guard_check as tg


# ---------------------------------------------------------------------------
# evidence assembly
# ---------------------------------------------------------------------------

def test_full_dump_includes_everything(guard_repo):
    ev, n = la.evidence_full(guard_repo["path"], guard_repo["base"],
                             guard_repo["branch"], triaged=False)
    assert "NETSTANDARD2_0" in ev
    assert n >= 1


def test_triaged_dump_drops_generated_files(tmp_path):
    """The fair baseline must genuinely exclude generated noise."""
    repo = tmp_path / "gen"
    repo.mkdir()

    def g(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.t",
                        "-c", "commit.gpgsign=false", *a], cwd=repo,
                       capture_output=True, check=True)
    g("init", "-q", "-b", "master")
    (repo / "a.cs").write_text("class A{}\n", encoding="utf-8")
    g("add", "-A"); g("commit", "-q", "-m", "b")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    g("checkout", "-q", "-b", "feature")
    (repo / "a.cs").write_text("class A{int x;}\n", encoding="utf-8")
    (repo / "big.g.cs").write_text("// GENERATED\n" * 500, encoding="utf-8")
    g("add", "-A"); g("commit", "-q", "-m", "f")

    full, nf = la.evidence_full(repo, base, "feature", triaged=False)
    triaged, nt = la.evidence_full(repo, base, "feature", triaged=True)

    assert nf == 2 and nt == 1
    assert "big.g.cs" in full
    assert "omitted by triage" in triaged
    assert la.rc.count_tokens(triaged) < la.rc.count_tokens(full)


def test_recall_arm_carries_citations_and_costs_less(tmp_path, guard_repo):
    db = tmp_path / "m.db"
    store = rc.Store(db)
    store.ingest_diff(guard_repo["path"], guard_repo["base"],
                      guard_repo["branch"])
    store.ingest_text("issue", "add the attribute to all generated code")
    store.close()

    arms = la.build_arms(guard_repo["path"], guard_repo["base"],
                         guard_repo["branch"], "add the attribute", db, 800)
    by = {a.strategy: a for a in arms}
    assert set(by) == {"full", "full-triaged", "recall"}
    assert by["recall"].citations is True
    assert by["full"].citations is False
    assert by["recall"].prompt_tokens <= by["full"].prompt_tokens


def test_arms_built_without_a_store_omit_recall(guard_repo):
    arms = la.build_arms(guard_repo["path"], guard_repo["base"],
                         guard_repo["branch"], "", None, 500)
    assert {a.strategy for a in arms} == {"full", "full-triaged"}


def test_live_arms_report_missing_key_rather_than_crashing(guard_repo,
                                                          monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    arms = la.build_arms(guard_repo["path"], guard_repo["base"],
                         guard_repo["branch"], "", None, 500)
    la.run_live(arms, guard_repo["path"], guard_repo["base"],
                guard_repo["branch"], "", None, 500, "claude-sonnet-5-5")
    assert all(a.error for a in arms)
    assert all(a.completion_tokens == 0 for a in arms)


def test_total_tokens_prefers_api_counts():
    a = la.ArmCost(strategy="x", prompt_tokens=100, evidence_tokens=90,
                   api_prompt_tokens=123, completion_tokens=7)
    assert a.total_tokens == 130
    b = la.ArmCost(strategy="y", prompt_tokens=100, evidence_tokens=90)
    assert b.total_tokens == 100


# ---------------------------------------------------------------------------
# repro generation
# ---------------------------------------------------------------------------

def ledger_entry(verdict="FALSIFIED", cls="tfm-guard"):
    return {
        "assumption": {
            "id": "tfm-guard-0", "cls": cls, "verdict": verdict,
            "statement": "the attribute is unavailable on netstandard2.0",
            "source_kind": "implicit_in_code",
            "source_ref": "src/T.cs  #if !NETSTANDARD2_0",
            "check_cmd": "dotnet build probe.csproj",
        },
        "severity": "moderate", "test_invisible": True,
        "sites": [{"kind": "target_framework", "ref": "netstandard2.0",
                   "why": "shipped"}],
        "hypotheses": [],
    }


def test_pick_finding_selects_falsified_guard():
    assert mr.pick_finding([ledger_entry()]) is not None


def test_pick_finding_ignores_supported_and_other_classes():
    assert mr.pick_finding([ledger_entry(verdict="SUPPORTED")]) is None
    assert mr.pick_finding([ledger_entry(cls="documented-claim")]) is None
    assert mr.pick_finding([]) is None


def test_generated_repro_has_the_expected_shape(guard_repo, tmp_path):
    ledger = tmp_path / "l.json"
    ledger.write_text(json.dumps([ledger_entry()]), encoding="utf-8")
    out = tmp_path / "repro"

    rc_code = mr.main(["--repo", str(guard_repo["path"]),
                       "--branch", guard_repo["branch"],
                       "--ledger", str(ledger), "--out", str(out)])
    assert rc_code == 0
    assert (out / "TrustRepro.csproj").exists()
    assert (out / "README.md").exists()
    commit = guard_repo["tip"]
    assert (out / "source_snapshot" / commit).is_dir()
    assert commit in (out / "README.md").read_text(encoding="utf-8")
    test_src = (out / "ExcludeFromCodeCoverageTests.cs").read_text(encoding="utf-8")

    # the guard under test is embedded verbatim
    assert "#if !NETSTANDARD2_0" in test_src
    assert str(out / "source_snapshot" / commit) in test_src
    # a sanity test exists so the suite cannot pass vacuously
    assert "TemplatesExist" in test_src
    # it states what it is NOT, so severity cannot be inflated on stage
    readme = (out / "README.md").read_text(encoding="utf-8")
    assert "Not a crash" in readme
    assert "did most of this job" in readme or "updated all six" in readme \
        or "regenerated 222" in readme


def test_repro_refuses_when_nothing_was_falsified(guard_repo, tmp_path):
    ledger = tmp_path / "l.json"
    ledger.write_text(json.dumps([ledger_entry(verdict="SUPPORTED")]),
                      encoding="utf-8")
    code = mr.main(["--repo", str(guard_repo["path"]),
                    "--branch", guard_repo["branch"],
                    "--ledger", str(ledger), "--out", str(tmp_path / "r2")])
    assert code == 1, "no finding means no repro, not an empty passing test"


def test_repro_refuses_without_a_recoverable_guard(guard_repo, tmp_path):
    entry = ledger_entry()
    entry["assumption"]["source_ref"] = "src/T.cs  (no guard text here)"
    ledger = tmp_path / "l.json"
    ledger.write_text(json.dumps([entry]), encoding="utf-8")
    code = mr.main(["--repo", str(guard_repo["path"]),
                    "--branch", guard_repo["branch"],
                    "--ledger", str(ledger), "--out", str(tmp_path / "r3")])
    assert code == 1


@pytest.mark.slow
def test_generated_repro_compiles_and_fails_for_the_right_reason(tmp_path):
    """End to end against the REAL repo: the test must fail, and the sanity
    test must pass, proving it read the repository rather than succeeding
    vacuously."""
    repo = Path(__file__).resolve().parents[2] / "repo"
    ledger = Path(__file__).resolve().parents[2] / ".trust" / "findings" / \
        "2297-blast.json"
    if not (repo / ".git").exists() or not ledger.exists():
        pytest.skip("target repo or ledger not available")
    if tg.dotnet_exe() is None:
        pytest.skip("no .NET SDK")

    out = tmp_path / "repro2297"
    assert mr.main(["--repo", str(repo), "--branch", "origin/ju26-issue-2297",
                    "--ledger", str(ledger), "--out", str(out)]) == 0

    p = subprocess.run([tg.dotnet_exe(), "test", str(out / "TrustRepro.csproj"),
                        "--nologo", "-v", "q"], capture_output=True, text=True,
                       timeout=900)
    text = p.stdout + p.stderr
    assert p.returncode != 0, "the repro must FAIL while the defect exists"
    assert "Passed:     1" in text or "Passed: 1" in text, \
        "the sanity test must still pass, proving the repro is not vacuous"
    assert "AttributeIsNotRestrictedByTargetFramework" in text
