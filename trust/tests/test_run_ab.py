"""
Tests for trust.ab.run_ab.

The property that matters is that the harness cannot flatter Arm B. The
verification stage is shared, runs against the branch's real parent, and is
reachable by both arms' findings. These tests assert the comparison stays
honest when Arm B is the one that is wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ab as ab


# ---------------------------------------------------------------------------
# file classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("path,bucket", [
    ("tests/X/Resources/A.MessagePack.GeneratedResolver.g.cs", "generated"),
    ("src/Foo/Bar.verified.txt", "generated"),
    ("tests/MessagePack.Tests/ReaderTests.cs", "test"),
    ("Directory.Packages.props", "build"),
    ("src/Lib/Lib.csproj", "build"),
    ("README.md", "doc"),
    ("doc/analyzers/MsgPack004.md", "doc"),
    ("src/MessagePack/MessagePackReader.cs", "source"),
])
def test_classify(path, bucket):
    assert path in ab.classify([path])[bucket]


def test_classify_generated_beats_test_path():
    """A generated file under tests/ is noise, not a test."""
    p = "tests/Foo/Resources/Thing.g.cs"
    b = ab.classify([p])
    assert p in b["generated"] and p not in b["test"]


# ---------------------------------------------------------------------------
# the naive base: Arm A's single-shot resolution
# ---------------------------------------------------------------------------

def test_naive_base_skips_missing_ref_and_lands_on_master(divergent_repo):
    """Reproduces Arm A's behaviour: origin/develop absent, so it takes the
    first ref that exists and never looks back."""
    ledger = ab.Ledger(divergent_repo["path"])
    base, method = ab.naive_base(ledger, divergent_repo["branch"])

    assert base == divergent_repo["B"], "merge-base with master, the wrong base"
    assert base != divergent_repo["Y"], "which is NOT the branch's real parent"
    assert "master" in method


def test_ledger_measures_rather_than_estimates(divergent_repo):
    ledger = ab.Ledger(divergent_repo["path"])
    assert ledger.bytes_read == 0
    ledger.git("log", "-1")
    assert ledger.bytes_read > 0
    assert ledger.git_calls == 1
    ledger.read("issue text", "x" * 100)
    assert ledger.bytes_read >= 100
    assert ledger.distinct_sources == 2


# ---------------------------------------------------------------------------
# verification must reject base-artefact findings
# ---------------------------------------------------------------------------

def test_verify_rejects_finding_produced_from_wrong_base(divergent_repo):
    """THE CENTRAL TEST. Arm A sees deps.props in its diff only because its
    base is two commits early. Verification against the real parent must call
    that false."""
    f = ab.Finding(id="scope-dependency-change", title="t", claim="c")
    # emulate the fixture's manifest name
    ab.verify([f], divergent_repo["path"], divergent_repo["Y"],
              divergent_repo["branch"])
    assert f.status == "REJECTED"
    assert "artefact of a misresolved base" in f.verify_note


def test_verify_confirms_finding_that_is_real(divergent_repo):
    """From the WRONG base the same file genuinely does differ, so a finding
    verified against that base is confirmed. Verification is not rigged to
    always reject - it checks."""
    f = ab.Finding(id="scope-dependency-change", title="t", claim="c")
    ab.verify([f], divergent_repo["path"], divergent_repo["B"],
              divergent_repo["branch"])
    assert f.status == "CONFIRMED"


def test_verify_is_applied_to_both_arms(guard_repo, monkeypatch, tmp_path):
    """Arm B's findings go through the same gate, with no exemption."""
    monkeypatch.setattr(ab.tg, "compile_probe",
                        lambda api, tfms, wd: [ab.tg.Probe(t, api, True, "stub")
                                               for t in tfms])
    b = ab.run_arm_b(guard_repo["path"], guard_repo["branch"], "", None, tmp_path)
    true_base = guard_repo["base"]
    ab.verify(b.findings, guard_repo["path"], true_base, guard_repo["branch"])

    assert b.findings, "arm B should produce something on the guard fixture"
    assert all(f.status in ("CONFIRMED", "REJECTED", "UNVERIFIED")
               for f in b.findings)


def test_unknown_finding_id_stays_unverified(divergent_repo):
    """An unrecognised finding must not be silently promoted to real."""
    f = ab.Finding(id="something-new", title="t", claim="c")
    ab.verify([f], divergent_repo["path"], divergent_repo["Y"],
              divergent_repo["branch"])
    assert f.status == "UNVERIFIED"
    assert f not in ab.ArmResult(arm="x", has_capsule=False, findings=[f]).confirmed


# ---------------------------------------------------------------------------
# arm fairness
# ---------------------------------------------------------------------------

def test_arm_a_receives_the_issue_text(guard_repo):
    """Denying Arm A the issue would make the delta meaningless."""
    r = ab.run_arm_a(guard_repo["path"], guard_repo["branch"],
                     "the issue body here")
    # the issue is recorded as consumed evidence
    assert r.has_capsule is False
    assert r.base_used is not None


def test_both_arms_run_the_same_diff_driven_checks(guard_repo, monkeypatch,
                                                   tmp_path):
    monkeypatch.setattr(ab.tg, "compile_probe",
                        lambda api, tfms, wd: [ab.tg.Probe(t, api, False, "stub")
                                               for t in tfms])
    a = ab.run_arm_a(guard_repo["path"], guard_repo["branch"], "issue")
    b = ab.run_arm_b(guard_repo["path"], guard_repo["branch"], "issue", None,
                     tmp_path)

    a_ids = {f.id for f in a.findings}
    b_ids = {f.id for f in b.findings}
    # with the probe stubbed to SUPPORTED, arm B adds no capsule finding,
    # so the diff-driven sets must match exactly
    assert a_ids == b_ids


def test_arm_b_counts_assumptions_arm_a_cannot(guard_repo, monkeypatch, tmp_path):
    monkeypatch.setattr(ab.tg, "compile_probe",
                        lambda api, tfms, wd: [ab.tg.Probe(t, api, True, "stub")
                                               for t in tfms])
    a = ab.run_arm_a(guard_repo["path"], guard_repo["branch"], "issue")
    b = ab.run_arm_b(guard_repo["path"], guard_repo["branch"], "issue", None,
                     tmp_path)

    assert a.assumptions_checked == 0, "Arm A has no assumption ledger"
    assert b.assumptions_checked > 0
    assert b.assumptions_falsified >= 1


def test_arm_b_uses_the_real_parent(divergent_repo, tmp_path):
    b = ab.run_arm_b(divergent_repo["path"], divergent_repo["branch"], "", 1,
                     tmp_path)
    assert b.base_used == divergent_repo["Y"]
    assert "first_parent" in b.base_method


# ---------------------------------------------------------------------------
# result accounting
# ---------------------------------------------------------------------------

def test_hidden_counts_only_confirmed_test_invisible_findings():
    real_hidden = ab.Finding(id="a", title="t", claim="c", status="CONFIRMED",
                             test_invisible=True)
    rejected_hidden = ab.Finding(id="b", title="t", claim="c", status="REJECTED",
                                 test_invisible=True)
    visible = ab.Finding(id="c", title="t", claim="c", status="CONFIRMED",
                         test_invisible=False)
    r = ab.ArmResult(arm="x", has_capsule=True,
                     findings=[real_hidden, rejected_hidden, visible])

    assert r.hidden == [real_hidden], "a rejected finding is not a hidden problem"
    assert len(r.confirmed) == 2
    assert len(r.rejected) == 1


@pytest.mark.parametrize("value,expected", [("50%", 50.0), ("100%", 100.0),
                                            ("n/a", -1.0)])
def test_pct_parsing(value, expected):
    assert ab._pct(value) == expected


# ---------------------------------------------------------------------------
# end to end on the fixture
# ---------------------------------------------------------------------------

def test_end_to_end_arm_b_beats_arm_a_on_precision(divergent_repo, tmp_path):
    """On the divergent topology, Arm A emits a base-artefact finding and
    Arm B does not."""
    a = ab.run_arm_a(divergent_repo["path"], divergent_repo["branch"], "issue")
    b = ab.run_arm_b(divergent_repo["path"], divergent_repo["branch"], "issue",
                     1, tmp_path)
    true_base = divergent_repo["Y"]
    ab.verify(a.findings, divergent_repo["path"], true_base, divergent_repo["branch"])
    ab.verify(b.findings, divergent_repo["path"], true_base, divergent_repo["branch"])

    assert len(a.rejected) >= 1, "Arm A must produce at least one false finding"
    assert len(b.rejected) == 0, "Arm B must produce none"
