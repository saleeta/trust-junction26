"""
Tests for trust.assumptions.tfm_guard_check.

The compile probe is the slow part, so verdict logic is tested with the probe
stubbed, and one test exercises the real toolchain (marked `slow`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import tfm_guard_check as tg


# ---------------------------------------------------------------------------
# guard discovery
# ---------------------------------------------------------------------------

def test_finds_introduced_guard(guard_repo):
    guards = tg.find_introduced_guards(
        guard_repo["path"], guard_repo["base"], guard_repo["branch"])

    assert len(guards) == 1
    g = guards[0]
    assert g.condition == "!NETSTANDARD2_0"
    assert g.excluded_symbols == ["NETSTANDARD2_0"]
    assert g.guarded_api == "System.Diagnostics.CodeAnalysis.ExcludeFromCodeCoverage"
    assert g.preexisting is False, "the guard did not exist at base"


def test_no_guards_when_diff_adds_none(guard_repo):
    """Comparing a commit to itself introduces nothing."""
    guards = tg.find_introduced_guards(
        guard_repo["path"], guard_repo["tip"], guard_repo["branch"])
    assert guards == []


def test_preexisting_guard_is_marked(tmp_path):
    """A guard that already followed a repo convention is lower suspicion."""
    import subprocess

    repo = tmp_path / "conv"
    repo.mkdir()

    def git(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.t",
                        "-c", "commit.gpgsign=false", *a],
                       cwd=repo, capture_output=True, check=True)

    git("init", "-q", "-b", "master")
    (repo / "a.cs").write_text("#if !NETSTANDARD2_0\nint x;\n#endif\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-q", "-m", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    git("checkout", "-q", "-b", "feature")
    (repo / "b.cs").write_text(
        "#if !NETSTANDARD2_0\n[global::Some.Attr]\n#endif\nint y;\n", encoding="utf-8")
    git("add", "-A"); git("commit", "-q", "-m", "more")

    guards = tg.find_introduced_guards(repo, base, "feature")
    assert len(guards) == 1
    assert guards[0].preexisting is True


@pytest.mark.parametrize("cond,expected", [
    ("!NETSTANDARD2_0 && !NETFRAMEWORK", ["NETSTANDARD2_0", "NETFRAMEWORK"]),
    ("!NETSTANDARD2_0", ["NETSTANDARD2_0"]),
    ("! NETFRAMEWORK", ["NETFRAMEWORK"]),
])
def test_negated_symbol_extraction(cond, expected):
    assert tg.NEG_SYMBOL_RE.findall(cond) == expected


def test_positive_only_condition_is_ignored():
    """`#if NET8_0` narrows nothing by negation; not this check's business."""
    assert tg.NEG_SYMBOL_RE.findall("NET8_0 || NET6_0") == []


# ---------------------------------------------------------------------------
# TFM reading
# ---------------------------------------------------------------------------

def test_reads_shipped_and_tested_tfms(guard_repo):
    shipped = tg.read_tfms(guard_repo["path"], guard_repo["branch"], ["src/"])
    tested = tg.read_tfms(guard_repo["path"], guard_repo["branch"], ["tests/"])

    assert shipped == ["net8.0", "netstandard2.0"]
    assert tested == ["net8.0"]


# ---------------------------------------------------------------------------
# verdict logic, probe stubbed
# ---------------------------------------------------------------------------

def stub_probe(result: bool):
    def _probe(api, tfms, workdir):
        return [tg.Probe(t, api, result, f"stub build {t}") for t in tfms]
    return _probe


def test_falsified_when_api_compiles_on_excluded_tfm(guard_repo, monkeypatch, tmp_path):
    monkeypatch.setattr(tg, "compile_probe", stub_probe(True))
    findings = tg.analyse(guard_repo["path"], guard_repo["base"],
                          guard_repo["branch"], None, tmp_path)

    assert len(findings) == 1
    f = findings[0]
    assert f.verdict == "FALSIFIED"
    assert f.affected_tfms == ["netstandard2.0"]
    assert f.test_observable is False
    assert f.severity == "moderate"
    assert "silently does not apply" in f.consequence


def test_supported_when_api_really_is_unavailable(guard_repo, monkeypatch, tmp_path):
    monkeypatch.setattr(tg, "compile_probe", stub_probe(False))
    findings = tg.analyse(guard_repo["path"], guard_repo["base"],
                          guard_repo["branch"], None, tmp_path)

    assert findings[0].verdict == "SUPPORTED"
    assert any("warranted" in e for e in findings[0].evidence)


def test_issue_text_without_tfms_is_noted(guard_repo, monkeypatch, tmp_path):
    monkeypatch.setattr(tg, "compile_probe", stub_probe(True))
    findings = tg.analyse(
        guard_repo["path"], guard_repo["base"], guard_repo["branch"],
        "I would like all generated code decorated with the attribute.", tmp_path)

    assert any("does not mention target frameworks" in e
               for e in findings[0].evidence)


def test_issue_text_mentioning_tfms_suppresses_that_note(guard_repo, monkeypatch,
                                                         tmp_path):
    monkeypatch.setattr(tg, "compile_probe", stub_probe(True))
    findings = tg.analyse(
        guard_repo["path"], guard_repo["base"], guard_repo["branch"],
        "Please skip netstandard2.0, it is not supported there.", tmp_path)

    assert not any("does not mention target frameworks" in e
                   for e in findings[0].evidence)


def test_evidence_records_whether_guard_was_a_convention(guard_repo, monkeypatch,
                                                        tmp_path):
    monkeypatch.setattr(tg, "compile_probe", stub_probe(True))
    f = tg.analyse(guard_repo["path"], guard_repo["base"],
                   guard_repo["branch"], None, tmp_path)[0]
    assert any("did NOT exist" in e for e in f.evidence)


def test_test_observability_is_detected(guard_repo, monkeypatch, tmp_path):
    """If a test project DID target the excluded TFM, severity drops."""
    monkeypatch.setattr(tg, "compile_probe", stub_probe(True))
    monkeypatch.setattr(tg, "read_tfms", lambda repo, branch, globs:
                        ["net8.0", "netstandard2.0"])
    f = tg.analyse(guard_repo["path"], guard_repo["base"],
                   guard_repo["branch"], None, tmp_path)[0]

    assert f.test_observable is True
    assert f.severity == "low"


# ---------------------------------------------------------------------------
# the real toolchain
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_real_probe_proves_attribute_available_on_netstandard20(tmp_path):
    """The finding rests on this: the attribute DOES compile where the guard
    claims it cannot."""
    if tg.dotnet_exe() is None:
        pytest.skip("no .NET SDK")

    probes = tg.compile_probe(
        "System.Diagnostics.CodeAnalysis.ExcludeFromCodeCoverage",
        ["netstandard2.0"], tmp_path)

    assert len(probes) == 1
    assert probes[0].compiles is True, probes[0].output_tail


@pytest.mark.slow
def test_probe_projects_persist_for_human_verification(tmp_path):
    """A 'verify yourself' command pointing into a deleted directory is worse
    than no command. REGRESSION: probes were built in a TemporaryDirectory."""
    if tg.dotnet_exe() is None:
        pytest.skip("no .NET SDK")

    probes = tg.compile_probe(
        "System.Diagnostics.CodeAnalysis.ExcludeFromCodeCoverage",
        ["netstandard2.0"], tmp_path)

    proj = tmp_path / "probe_netstandard2_0" / "p.csproj"
    assert proj.exists(), "the probe project must remain on disk"
    assert str(proj) in probes[0].command or "p.csproj" in probes[0].command


def test_probe_reports_cleanly_without_sdk(monkeypatch, tmp_path):
    monkeypatch.setattr(tg, "dotnet_exe", lambda: None)
    probes = tg.compile_probe("Some.Attr", ["netstandard2.0"], tmp_path)
    assert probes[0].compiles is None
    assert "unavailable" in probes[0].output_tail


def test_missing_sdk_cannot_support_guard(guard_repo, monkeypatch, tmp_path):
    monkeypatch.setattr(tg, "dotnet_exe", lambda: None)
    finding = tg.analyse(guard_repo["path"], guard_repo["base"],
                         guard_repo["branch"], None, tmp_path)[0]
    assert finding.verdict == "UNCHECKABLE"
