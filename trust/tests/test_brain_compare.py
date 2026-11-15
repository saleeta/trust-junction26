"""Brain compare: the foobar repo and its with/without-context arms."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "trust" / "brain"))

import compare  # noqa: E402


@pytest.mark.skipif(not (ROOT / "foobar" / ".git").exists(),
                    reason="foobar demo repo not built")
def test_foobar_repo_and_session_exist():
    for f in compare.SESSION_FILES:
        assert (ROOT / "foobar" / f).exists(), f
    assert compare.BASE and compare.HEAD


def test_derive_arm_b_resolves_intent_and_adds_verification_claim():
    arm_a = {"claims": [
        {"id": "G1", "label": "Unknown"},
        {"id": "U1", "label": "Unknown", "claim": "intent"},
    ]}
    session = "The guard looks redundant - drop the guard entirely. Tests are green."
    executed = {"ship_o2": "shipped", "tests": "FAILED (failures=1)"}
    out = compare.derive_arm_b(arm_a, session, executed)
    by_id = {c["id"]: c for c in out["claims"]}
    assert by_id["U1"]["label"] == "Refuted"
    assert by_id["B1"]["label"] == "Refuted"
    assert "Tests are green" in by_id["B1"]["witnesses"][0]
    # the executed promise check refutes P1 without the session
    p1 = next(c for c in out["claims"] if c["id"] == "P1")
    assert p1["label"] == "Refuted"
    assert "shipped" in p1["witnesses"][0]


def test_report_renders_and_labels_the_arms():
    arm_a = {"claims": [{"id": "U1", "label": "Unknown", "claim": "intent"}]}
    arm_b = {"claims": [{"id": "U1", "label": "Refuted", "claim": "intent",
                         "via_session": True,
                         "witnesses": ["session quote"]}]}
    html = compare.build_report(arm_a, arm_b, "session text")
    assert "arm A · methodology only" in html
    assert "arm B · + agent context" in html
    assert "resolved by session" in html
