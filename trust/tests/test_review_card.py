"""The demo receipt must never turn AI advice into a human approval."""

import json
from pathlib import Path

import pytest

from trust.review import review_card as card


def test_receipt_requires_probe_evidence_and_stays_pending(tmp_path, monkeypatch):
    finding = [{
        "verdict": "FALSIFIED", "affected_tfms": ["net472"],
        "guards": [{"file": "src/Template.tt", "condition": "!NETFRAMEWORK"}],
        "probes": [{"compiles": True, "command": "dotnet build probe.csproj"}],
    }]
    source = tmp_path / "finding.json"
    source.write_text(json.dumps(finding), encoding="utf-8")
    monkeypatch.setattr(card, "git", lambda repo, *args:
                        "#if !NETFRAMEWORK" if args[0] == "show" else "a" * 40)
    receipt = card.build_card(tmp_path, "feature", source)
    assert receipt["human_decision"] == "pending"
    assert receipt["human_owner"] is None
    assert "cannot" in receipt["ai_refusal"].lower()
    page = card.render(receipt, Path(card.__file__).with_name("card_template.html"))
    assert "Human decision pending" in page
    assert "tfm_guard_check.py" in page


def test_receipt_refuses_inconclusive_probe(tmp_path, monkeypatch):
    source = tmp_path / "finding.json"
    source.write_text(json.dumps([{
        "verdict": "FALSIFIED", "affected_tfms": ["net472"],
        "probes": [{"compiles": None}],
    }]), encoding="utf-8")
    monkeypatch.setattr(card, "git", lambda repo, *args: "a" * 40)
    with pytest.raises(ValueError, match="incomplete"):
        card.build_card(tmp_path, "feature", source)
