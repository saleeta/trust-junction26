"""
Tests for trust.ingest.base_resolver.

The first test is the one that matters: it reproduces the topology that made
this project's own reviewer produce a false finding, and asserts the resolver
now refuses to resolve it silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import base_resolver as br


# ---------------------------------------------------------------------------
# the regression that motivated the module
# ---------------------------------------------------------------------------

def test_prefers_first_parent_over_merge_base(divergent_repo):
    """REGRESSION: merge-base returned a commit two steps too early.

    The agent's branch was built on Y, but merge-base with master returns B.
    Diffing from B attributes X and Y - two pre-existing dependency commits -
    to the agent. The resolver must pick Y.
    """
    git = br.Git(divergent_repo["path"])
    rec = br.resolve(git, divergent_repo["branch"])

    assert rec.base == divergent_repo["Y"], "must use the branch's real parent"
    assert rec.base != divergent_repo["B"], "must not use the merge-base"
    assert rec.method == "first_parent"


def test_reports_disagreement_instead_of_choosing_silently(divergent_repo):
    """The failure mode was silence, not the wrong answer per se."""
    git = br.Git(divergent_repo["path"])
    rec = br.resolve(git, divergent_repo["branch"])

    assert rec.verdict == "DISPUTED"
    assert any("disagree" in w for w in rec.warnings)
    # the competing answer must be visible to a human, not swallowed
    methods = {c.method: c.sha for c in rec.candidates}
    assert methods["merge_base[origin/master]"] is None  # no remote in fixture
    assert methods["merge_base[master]"] == divergent_repo["B"]


def test_missing_ref_is_recorded_not_skipped(divergent_repo):
    """`origin/develop` did not exist; a silent fall-through caused the bug."""
    git = br.Git(divergent_repo["path"])
    rec = br.resolve(git, divergent_repo["branch"])

    missing = [c for c in rec.candidates if c.method == "merge_base[origin/develop]"]
    assert len(missing) == 1
    assert missing[0].sha is None
    assert "does not exist" in missing[0].note


# ---------------------------------------------------------------------------
# the external oracle
# ---------------------------------------------------------------------------

def test_oracle_confirms_correct_base(divergent_repo):
    """Y..F touches exactly one file; the oracle should confirm."""
    git = br.Git(divergent_repo["path"])
    rec = br.resolve(git, divergent_repo["branch"], expect_files=1)

    assert rec.oracle["actual_changed_files"] == 1
    assert rec.oracle["agrees"] is True
    assert rec.verdict == "CONFIRMED", "an agreeing oracle outranks internal dispute"


def test_oracle_rejects_wrong_expectation(divergent_repo):
    """If the brief says 3 files and this base yields 1, say so loudly."""
    git = br.Git(divergent_repo["path"])
    rec = br.resolve(git, divergent_repo["branch"], expect_files=3)

    assert rec.oracle["agrees"] is False
    assert rec.verdict == "DISPUTED"
    assert any("REJECTS" in w for w in rec.warnings)


def test_oracle_would_have_caught_the_original_error(divergent_repo):
    """From the WRONG base, the file count differs - which is why the brief's
    counts were a usable oracle for the real branches."""
    git = br.Git(divergent_repo["path"])
    from_right = git.changed_files(divergent_repo["Y"], divergent_repo["branch"])
    from_wrong = git.changed_files(divergent_repo["B"], divergent_repo["branch"])

    assert from_right == 1
    assert from_wrong == 2, "the wrong base drags in deps.props"
    assert from_right != from_wrong


# ---------------------------------------------------------------------------
# degenerate inputs
# ---------------------------------------------------------------------------

def test_unknown_branch_is_unresolved_not_crash(divergent_repo):
    git = br.Git(divergent_repo["path"])
    rec = br.resolve(git, "no/such/branch")

    assert rec.verdict == "UNRESOLVED"
    assert rec.base is None
    assert any("does not exist" in w for w in rec.warnings)


def test_root_commit_has_no_base(divergent_repo):
    """REGRESSION: a root commit has no first parent, and merge-base then
    returns the commit itself. Reporting that as the base yields an empty diff,
    which downstream reads as "no changes to review" - a silent failure."""
    git = br.Git(divergent_repo["path"])
    git.run("branch", "rooty", divergent_repo["A"])
    rec = br.resolve(git, "rooty")

    assert rec.base is None, "must not report the branch tip as its own base"
    assert rec.verdict == "UNRESOLVED"
    assert any("empty diff" in (c.note or "") for c in rec.candidates)


def test_non_repo_path_raises(tmp_path):
    with pytest.raises(SystemExit):
        br.Git(tmp_path / "definitely-not-a-repo")


# ---------------------------------------------------------------------------
# the assumption record consumed downstream
# ---------------------------------------------------------------------------

def test_assumption_record_maps_verdicts(divergent_repo):
    git = br.Git(divergent_repo["path"])

    disputed = br.resolve(git, divergent_repo["branch"]).as_assumption()
    assert disputed["verdict"] == "FALSIFIED"
    assert disputed["check"].startswith("git rev-parse")

    confirmed = br.resolve(
        git, divergent_repo["branch"], expect_files=1).as_assumption()
    assert confirmed["verdict"] == "SUPPORTED"

    unresolved = br.resolve(git, "nope").as_assumption()
    assert unresolved["verdict"] == "UNCHECKABLE"


def test_assumption_record_carries_consequence(divergent_repo):
    git = br.Git(divergent_repo["path"])
    a = br.resolve(git, divergent_repo["branch"]).as_assumption()
    assert "misattribut" in a["consequence"]
    assert divergent_repo["Y"][:9] in a["statement"]


# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("spec,expected", [
    (None, {}),
    ("", {}),
    ("2283=4", {"2283": 4}),
    ("2283=4,2234=4,2129=28,2297=237",
     {"2283": 4, "2234": 4, "2129": 28, "2297": 237}),
    ("  2283 = 4 , 2297=237 ", {"2283": 4, "2297": 237}),
    ("garbage", {}),
])
def test_parse_expect(spec, expected):
    assert br.parse_expect(spec) == expected
