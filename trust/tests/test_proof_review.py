"""
Tests for trust.proof.proof_review - the proof-carrying review layer.

The properties that matter:
- the guard evaluator implements C# conditional-compilation semantics for
  the supported constructs (symbols, !, &&, ||, parentheses) and nothing more;
- the R-2297 checker produces a counterexample exactly when a shipped TFM's
  defined symbols make the guard false;
- the verdict vocabulary stays inside the four honest labels;
- line links point at the guard lines, not at a claim copy per line.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import proof_review as pr


# ---------------------------------------------------------------------------
# the C# conditional-compilation evaluator
# ---------------------------------------------------------------------------

def test_guard_evaluator_truth_table():
    assert pr.eval_guard("NETSTANDARD2_0", ["NETSTANDARD2_0"]) is True
    assert pr.eval_guard("NETSTANDARD2_0", []) is False
    assert pr.eval_guard("!NETSTANDARD2_0 && !NETFRAMEWORK",
                         ["NETSTANDARD2_0"]) is False
    assert pr.eval_guard("!NETSTANDARD2_0 && !NETFRAMEWORK",
                         ["NETFRAMEWORK"]) is False
    assert pr.eval_guard("!NETSTANDARD2_0 && !NETFRAMEWORK",
                         ["NET8_0"]) is True
    assert pr.eval_guard("A || B", ["B"]) is True
    assert pr.eval_guard("A || B", ["C"]) is False
    assert pr.eval_guard("!(A && B)", ["A"]) is True
    assert pr.eval_guard("!A && (B || C)", ["A", "B"]) is False
    assert pr.eval_guard("!A && (B || C)", ["B"]) is True


def test_unknown_symbols_count_as_undefined():
    assert pr.eval_guard("!SOMETHING_UNKNOWN", []) is True


# ---------------------------------------------------------------------------
# the R-2297 checker against a synthetic repository
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.t",
                        *args], cwd=repo, capture_output=True, text=True,
                       timeout=60)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def _commit(repo: Path, files: dict[str, str], msg: str) -> str:
    for rel, body in files.items():
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


GUARDED_TEMPLATE = (
    "line one\n"
    "#if !NETSTANDARD2_0 && !NETFRAMEWORK\n"
    "[global::System.Diagnostics.CodeAnalysis.ExcludeFromCodeCoverage]\n"
    "#endif\n"
    "partial class R { }\n"
)


def synthetic_repo(tmp_path: Path) -> dict:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")
    base = _commit(repo, {
        "src/Lib/Lib.csproj":
            "<Project><PropertyGroup><TargetFrameworks>netstandard2.0;"
            "net472;net8.0</TargetFrameworks></PropertyGroup></Project>\n",
        "src/Lib/Plain.tt": "partial class R { }\n",
        "src/Lib/Plain.cs": "partial class R { }\n",
        "tests/T/T.csproj":
            "<Project><PropertyGroup><TargetFramework>net8.0"
            "</TargetFramework></PropertyGroup></Project>\n",
    }, "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    tip = _commit(repo, {
        "src/Lib/Plain.tt": GUARDED_TEMPLATE,
        "src/Lib/Plain.cs": GUARDED_TEMPLATE,
    }, "add the guard")
    return {"path": repo, "base": base, "tip": tip, "branch": "feature"}


def test_r2297_refuted_with_witness_on_synthetic_repo(tmp_path):
    r = synthetic_repo(tmp_path)
    result, links = pr.check_r2297(r["path"], r["base"], r["branch"])
    assert result.verdict == "REFUTED"
    witnesses = result.witness
    assert witnesses["tfm"] in ("net472", "netstandard2.0")
    assert "ABSENT" in next(
        e.value for e in result.evidence if e.kind == "checker_output")
    assert any(l["line"] == 2 and l["file"].endswith("Plain.tt") for l in links)


def test_observability_refuted_when_tests_cover_only_net8(tmp_path):
    r = synthetic_repo(tmp_path)
    result = pr.check_observability(r["path"], r["base"], r["branch"])
    assert result.verdict == "REFUTED"
    assert "net8.0" in next(
        e.value for e in result.evidence if e.kind == "checker_output")


def test_verdicts_stay_inside_the_vocabulary(tmp_path):
    r = synthetic_repo(tmp_path)
    review = pr.build(r["path"], r["base"], r["branch"], "")
    assert review.requirement["formal_obligation"]
    assert all(res.verdict in pr.VERDICTS for res in review.results)
    # the four labels are all present somewhere in a full review
    assert {"REFUTED", "PROVED_IN_SCOPE", "TESTED", "UNKNOWN"} <= {
        res.verdict for res in review.results}


def test_claims_are_stated_once_and_lines_link_to_them(tmp_path):
    r = synthetic_repo(tmp_path)
    review = pr.build(r["path"], r["base"], r["branch"], "")
    c1 = next(c for c in review.claims if c.id == "C-2297-1")
    assert len(c1.line_links) == 1, "one guard line links to the claim"
    assert c1.line_links[0]["line"] == 2
