"""The generic analyzer: works on any git repo, refuses unsafe inputs, keeps labels honest."""
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "trust" / "generic")); sys.path.insert(0, str(ROOT / "toy"))
import analyze as A          # noqa: E402
import build_repo            # noqa: E402


@pytest.fixture(scope="module")
def data():
    build_repo.build()
    return A.analyze(str(build_repo.REPO), base="pr3", head="pr4")


def test_refuses_non_github_and_non_repo(tmp_path):
    for bad in ("https://evil.example.com/a/b", "--upload-pack=x", "git@github.com:a/b.git", str(tmp_path)):
        with pytest.raises(SystemExit):
            A.resolve_repo(bad, None)


def test_github_url_forms_parse():
    assert A.GH.match("https://github.com/o/r").groups() == ("o", "r", None)
    assert A.GH.match("https://github.com/o/r.git").group(2) == "r"
    assert A.GH.match("https://github.com/o/r/pull/12/files").group(3) == "12"


def test_static_claim_is_refuted_with_a_witness(data):
    g1 = next(c for c in data["claims"] if c["id"] == "G1")
    assert g1["label"] == "Refuted" and g1["tier"] == "static" and g1["witnesses"]


def test_callers_found_by_text_search_and_never_overclaimed(data):
    ks = [c for c in data["claims"] if c["id"].startswith("K")]
    assert [c["chain"] for c in ks] == [["final_price", "checkout"], ["final_price", "checkout", "post_sale"]]
    assert all(c["label"] == "Unknown" for c in ks)          # listed, not assumed broken


def test_intent_and_induced_are_never_decided_by_code(data):
    assert next(c for c in data["claims"] if c["id"] == "U1")["label"] == "Unknown"
    assert all(c["label"] == "Unknown" for c in data["claims"] if c["tier"] == "induced")


def test_nothing_executed_without_run(data):
    assert data["run"]["ran"] is False and not any(c["tier"] == "executed" for c in data["claims"])
