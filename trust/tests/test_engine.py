"""
Tests for the assumption blast-radius engine.

The engine's job is to multiply reach WITHOUT multiplying claims. So the tests
concentrate on: only `check` sets verdicts, hypotheses never become findings,
and `inflation_guard` refuses to let 200 impact sites become a crisis.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import engine as en
import tfm_guard_check as tg


def ctx_for(repo_fixture, **kw) -> en.Context:
    return en.Context(
        repo=repo_fixture["path"],
        base=repo_fixture["base"] if "base" in repo_fixture else repo_fixture["Y"],
        branch=repo_fixture["branch"],
        probe_dir=kw.pop("probe_dir", Path(".")),
        **kw)


def stub_probes(result: bool):
    return lambda api, tfms, wd: [tg.Probe(t, api, result, f"stub {t}")
                                  for t in tfms]


# ---------------------------------------------------------------------------
# harvest / check separation
# ---------------------------------------------------------------------------

def test_harvest_does_not_set_a_verdict(guard_repo, tmp_path):
    """Only check() may set a verdict, and only by running something."""
    cls = en.TfmGuardAssumption()
    found = cls.harvest(ctx_for(guard_repo, probe_dir=tmp_path))
    assert found
    assert all(a.verdict == "UNCHECKED" for a in found)


def test_check_falsifies_when_probe_compiles(guard_repo, monkeypatch, tmp_path):
    monkeypatch.setattr(tg, "compile_probe", stub_probes(True))
    c = ctx_for(guard_repo, probe_dir=tmp_path)
    cls = en.TfmGuardAssumption()
    a = cls.harvest(c)[0]
    cls.check(a, c)
    assert a.verdict == "FALSIFIED"
    assert any("premise is false" in e for e in a.evidence)


def test_check_supports_when_probe_fails(guard_repo, monkeypatch, tmp_path):
    monkeypatch.setattr(tg, "compile_probe", stub_probes(False))
    c = ctx_for(guard_repo, probe_dir=tmp_path)
    cls = en.TfmGuardAssumption()
    a = cls.harvest(c)[0]
    cls.check(a, c)
    assert a.verdict == "SUPPORTED"


def test_check_is_inconclusive_when_probe_cannot_run(guard_repo, monkeypatch,
                                                      tmp_path):
    monkeypatch.setattr(tg, "compile_probe", lambda api, tfms, wd: [
        tg.Probe(t, api, None, "dotnet unavailable", "SDK unavailable")
        for t in tfms])
    c = ctx_for(guard_repo, probe_dir=tmp_path)
    cls = en.TfmGuardAssumption()
    a = cls.harvest(c)[0]
    cls.check(a, c)
    assert a.verdict == "UNCHECKABLE"


def test_no_footprint_or_hypotheses_when_not_falsified(guard_repo, monkeypatch,
                                                       tmp_path):
    monkeypatch.setattr(tg, "compile_probe", stub_probes(False))
    c = ctx_for(guard_repo, probe_dir=tmp_path)
    cls = en.TfmGuardAssumption()
    a = cls.harvest(c)[0]
    cls.check(a, c)
    assert cls.hypotheses(a, cls.footprint(a, c), c) == []


# ---------------------------------------------------------------------------
# blast radius
# ---------------------------------------------------------------------------

def test_footprint_includes_shipped_excluded_framework(guard_repo, monkeypatch,
                                                       tmp_path):
    monkeypatch.setattr(tg, "compile_probe", stub_probes(True))
    c = ctx_for(guard_repo, probe_dir=tmp_path)
    cls = en.TfmGuardAssumption()
    a = cls.harvest(c)[0]
    cls.check(a, c)
    sites = cls.footprint(a, c)
    tfms = [s.ref for s in sites if s.kind == "target_framework"]
    assert "netstandard2.0" in tfms, "shipped AND excluded, so load-bearing"


def test_one_assumption_yields_a_family_of_hypotheses(guard_repo, monkeypatch,
                                                      tmp_path):
    """The differentiator: a falsified assumption is not one finding."""
    monkeypatch.setattr(tg, "compile_probe", stub_probes(True))
    c = ctx_for(guard_repo, probe_dir=tmp_path)
    cls = en.TfmGuardAssumption()
    a = cls.harvest(c)[0]
    cls.check(a, c)
    hyps = cls.hypotheses(a, cls.footprint(a, c), c)
    assert len(hyps) >= 1
    assert all(h.assumption_id == a.id for h in hyps)
    assert all(h.status == "untested" for h in hyps), \
        "hypotheses must never arrive pre-confirmed"


def test_hypotheses_are_ranked(guard_repo, monkeypatch, tmp_path):
    monkeypatch.setattr(tg, "compile_probe", stub_probes(True))
    c = ctx_for(guard_repo, probe_dir=tmp_path)
    results = en.run(c, classes=[en.TfmGuardAssumption])
    br = results[0]
    prios = [h.priority for h in br.hypotheses]
    assert prios == sorted(prios, reverse=True)


# ---------------------------------------------------------------------------
# inflation guard - the honesty mechanism
# ---------------------------------------------------------------------------

def test_inflation_guard_caps_severity_despite_huge_blast_radius():
    """222 impact sites must not become 'high'. Severity tracks what is
    DEMONSTRATED, not how many files are touched."""
    a = en.Assumption(id="x", cls="tfm-guard", statement="s",
                      source_kind="implicit_in_code", verdict="FALSIFIED")
    br = en.BlastRadius(
        assumption=a,
        sites=[en.ImpactSite("snapshot", "many", "why", count=5000),
               en.ImpactSite("target_framework", "netstandard2.0", "why")],
        hypotheses=[en.Hypothesis(id="h", assumption_id="x",
                                  failure_mode="feature_absent_on_target",
                                  rationale="r", site="s", strategy="static")])
    assert en.inflation_guard(br) == "moderate"
    assert br.site_count == 5001


def test_inflation_guard_returns_none_for_unfalsified():
    a = en.Assumption(id="x", cls="c", statement="s", source_kind="derived",
                      verdict="SUPPORTED")
    assert en.inflation_guard(en.BlastRadius(assumption=a)) == "none"


def test_inflation_guard_low_when_nothing_shipped_is_affected():
    a = en.Assumption(id="x", cls="tfm-guard", statement="s",
                      source_kind="implicit_in_code", verdict="FALSIFIED")
    br = en.BlastRadius(assumption=a,
                        sites=[en.ImpactSite("template", "t.tt", "why")])
    assert en.inflation_guard(br) == "low"


# ---------------------------------------------------------------------------
# documented claims
# ---------------------------------------------------------------------------

def test_documented_claim_harvested_and_falsified(tmp_path, monkeypatch):
    import subprocess

    repo = tmp_path / "doc"
    repo.mkdir()

    def g(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.t",
                        "-c", "commit.gpgsign=false", *a], cwd=repo,
                       capture_output=True, check=True)

    g("init", "-q", "-b", "master")
    (repo / "README.md").write_text("# Lib\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "a.csproj").write_text(
        "<Project><PropertyGroup><TargetFrameworks>netstandard2.0;net8.0"
        "</TargetFrameworks></PropertyGroup></Project>", encoding="utf-8")
    g("add", "-A"); g("commit", "-q", "-m", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    g("checkout", "-q", "-b", "feature")
    (repo / "README.md").write_text(
        "# Lib\nAll types get `[ExcludeFromCodeCoverage]`.\n"
        "The attribute is only emitted for targets where it is available "
        "(not `netstandard2.0`).\n", encoding="utf-8")
    (repo / "src" / "a.cs").write_text(
        "#if !NETSTANDARD2_0\n"
        "[global::System.Diagnostics.CodeAnalysis.ExcludeFromCodeCoverage]\n"
        "#endif\nclass A {}\n", encoding="utf-8")
    g("add", "-A"); g("commit", "-q", "-m", "feat")

    monkeypatch.setattr(tg, "compile_probe", stub_probes(True))
    c = en.Context(repo=repo, base=base, branch="feature", probe_dir=tmp_path)
    cls = en.DocumentedClaimAssumption()
    claims = cls.harvest(c)
    assert claims, "the availability sentence must be harvested"
    cls.check(claims[0], c)
    assert claims[0].verdict == "FALSIFIED"
    assert any("no test reads documentation" in e for e in claims[0].evidence)


def test_documented_claim_uncheckable_without_an_api(tmp_path, monkeypatch):
    """An un-resolvable claim is reported UNCHECKABLE, never dropped."""
    import subprocess
    repo = tmp_path / "doc2"
    repo.mkdir()

    def g(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.t",
                        "-c", "commit.gpgsign=false", *a], cwd=repo,
                       capture_output=True, check=True)
    g("init", "-q", "-b", "master")
    (repo / "README.md").write_text("# x\n", encoding="utf-8")
    g("add", "-A"); g("commit", "-q", "-m", "b")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    g("checkout", "-q", "-b", "feature")
    (repo / "README.md").write_text(
        "# x\nThis thing is not available on `netstandard2.0`.\n",
        encoding="utf-8")
    g("add", "-A"); g("commit", "-q", "-m", "c")

    c = en.Context(repo=repo, base=base, branch="feature", probe_dir=tmp_path)
    cls = en.DocumentedClaimAssumption()
    claims = cls.harvest(c)
    assert claims
    cls.check(claims[0], c)
    assert claims[0].verdict == "UNCHECKABLE"
    assert any("rather than dropped" in e for e in claims[0].evidence)


@pytest.mark.parametrize("raw,expected", [
    ("netstandard2.0", "netstandard2.0"),
    ("NetStandard 2.1", "netstandard2.1"),
    (".NET Framework", "net472"),
    ("net472", "net472"),
    ("net8.0", "net8.0"),
])
def test_norm_tfm(raw, expected):
    assert en._norm_tfm(raw) == expected


# ---------------------------------------------------------------------------
# rendering keeps facts and suspicions apart
# ---------------------------------------------------------------------------

def test_render_separates_facts_from_hypotheses(guard_repo, monkeypatch, tmp_path):
    monkeypatch.setattr(tg, "compile_probe", stub_probes(True))
    out = en.render(en.run(ctx_for(guard_repo, probe_dir=tmp_path),
                           classes=[en.TfmGuardAssumption]))
    assert "[facts, not claims]" in out
    assert "[UNVERIFIED - suspicions, not findings]" in out
    assert "never combined into one score" in out


def test_render_reports_uncheckable_rather_than_hiding(guard_repo):
    a = en.Assumption(id="u", cls="c", statement="unknowable",
                      source_kind="derived", verdict="UNCHECKABLE")
    out = en.render([en.BlastRadius(assumption=a)])
    assert "UNCHECKABLE (reported, not dropped)" in out
    assert "unknowable" in out


def test_render_labels_reconstructed_capsules():
    a = en.Assumption(id="r", cls="c", statement="s", source_kind="reconstructed",
                      verdict="FALSIFIED", reconstructed=True)
    out = en.render([en.BlastRadius(assumption=a, severity="low")])
    assert "[RECONSTRUCTED CAPSULE]" in out


def test_render_credits_supported_assumptions(guard_repo, monkeypatch, tmp_path):
    """The agent getting something right must be visible, or the report is a
    hit piece rather than a review."""
    monkeypatch.setattr(tg, "compile_probe", stub_probes(False))
    out = en.render(en.run(ctx_for(guard_repo, probe_dir=tmp_path),
                           classes=[en.TfmGuardAssumption]))
    assert "the agent got these right" in out


# ---------------------------------------------------------------------------
# engine ordering and serialisation
# ---------------------------------------------------------------------------

def test_run_sorts_severe_first(guard_repo, monkeypatch, tmp_path):
    monkeypatch.setattr(tg, "compile_probe", stub_probes(True))
    results = en.run(ctx_for(guard_repo, probe_dir=tmp_path))
    sev = [en.SEVERITY_ORDER.index(b.severity) for b in results]
    assert sev == sorted(sev, reverse=True)


def test_results_are_json_serialisable(guard_repo, monkeypatch, tmp_path):
    from dataclasses import asdict
    monkeypatch.setattr(tg, "compile_probe", stub_probes(True))
    results = en.run(ctx_for(guard_repo, probe_dir=tmp_path))
    blob = json.dumps([asdict(b) for b in results])
    assert json.loads(blob)
