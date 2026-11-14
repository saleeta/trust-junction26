"""Generate a compact, evidence-linked review receipt for the stage demo.

The human decision is deliberately left pending. This tool cannot approve code.
"""

from __future__ import annotations

import argparse
import html
import json
import subprocess
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parents[2]


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True,
                       text=True, timeout=30, check=True)
    return p.stdout.strip()


def build_card(repo: Path, branch: str, finding_path: Path) -> dict:
    findings = json.loads(finding_path.read_text(encoding="utf-8"))
    finding = next((f for f in findings if f.get("verdict") == "FALSIFIED"
                    and f.get("affected_tfms")), None)
    if finding is None:
        raise ValueError("no verified affected-framework finding; cannot build card")
    if not finding.get("probes") or not all(
            p.get("compiles") is True for p in finding["probes"]):
        raise ValueError("compile evidence is incomplete; cannot build card")
    commit = git(repo, "rev-parse", "--verify", f"{branch}^{{commit}}")
    base = git(repo, "rev-parse", "--verify", f"{branch}^")
    guard = finding["guards"][0]
    source = git(repo, "show", f"{commit}:{guard['file']}")
    if f"#if {guard['condition']}" not in source:
        raise ValueError("finding guard does not match the selected commit")
    return {
        "requirement_id": "MessagePack-CSharp#2297",
        "requirement": "Decorate all generated code with ExcludeFromCodeCoverage.",
        "branch": branch, "commit": commit, "base": base,
        "source_type": "Tieto AI-made patch; author session unavailable",
        "risk": "moderate",
        "finding": "The new guard omits the attribute on two shipped target frameworks.",
        "affected_frameworks": finding["affected_tfms"],
        "evidence": [
            {"claim": "The requirement says all generated code.",
             "source": "Issue #2297", "check": "Read .trust/issues/2297.md"},
            {"claim": "The patch adds #if !NETSTANDARD2_0 && !NETFRAMEWORK.",
             "source": guard["file"],
             "check": f"git -C repo diff {base}..{commit} -- {guard['file']}"},
            {"claim": "The attribute compiles unguarded on both excluded targets.",
             "source": "Executed compile probes",
             "check": ("python trust/assumptions/tfm_guard_check.py --repo repo "
                       f"--branch {branch} --base {base} "
                       "--issue-text .trust/issues/2297.md")},
        ],
        "not_checked": [
            "The full emitted output was not built for every consumer configuration.",
            "No original Tieto author transcript was supplied.",
            "A security review of the entire 237-file patch was not performed.",
        ],
        "ai_recommendation": "Request changes",
        "ai_refusal": "AI cannot waive the 'all generated code' requirement or approve this patch.",
        "human_owner": None, "human_decision": "pending",
        "accepted_residual_risk": None,
        "next_action": "A named engineer checks the evidence and requests a fix or records an authorized scope change.",
        "decision_log": [
            {"observation": "Base candidates disagreed", "decision": "Used the branch parent; matched the brief's 237-file count."},
            {"observation": "Guard excludes shipped targets", "decision": "Compiled the attribute unguarded on both targets."},
            {"observation": "Requirement and implementation differ", "decision": "AI recommends changes; human decision remains pending."},
        ],
    }


def render(card: dict, template: Path) -> str:
    esc = lambda s: html.escape(str(s), quote=True)
    evidence = "".join(
        f'<li><strong>{esc(e["claim"])}</strong><span>{esc(e["source"])}</span>'
        f'<code>{esc(e["check"])}</code></li>' for e in card["evidence"])
    gaps = "".join(f"<li>{esc(v)}</li>" for v in card["not_checked"])
    log = "".join(
        f'<li><span>{esc(d["observation"])}</span><strong>{esc(d["decision"])}</strong></li>'
        for d in card["decision_log"])
    return Template(template.read_text(encoding="utf-8")).substitute(
        requirement_id=esc(card["requirement_id"]),
        requirement=esc(card["requirement"]),
        commit=esc(card["commit"][:12]),
        branch=esc(card["branch"]), risk=esc(card["risk"]),
        finding=esc(card["finding"]),
        affected=esc(", ".join(card["affected_frameworks"])),
        recommendation=esc(card["ai_recommendation"]),
        refusal=esc(card["ai_refusal"]), next_action=esc(card["next_action"]),
        evidence=evidence, gaps=gaps, log=log,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, default=ROOT / "repo")
    p.add_argument("--branch", default="origin/ju26-issue-2297")
    p.add_argument("--finding", type=Path,
                   default=ROOT / ".trust/findings/2297-tfm-guard.json")
    p.add_argument("--out", type=Path, default=ROOT / "demo/review-2297")
    a = p.parse_args(argv)
    try:
        card = build_card(a.repo.resolve(), a.branch, a.finding)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f"card not generated: {exc}")
        return 1
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.with_suffix(".json").write_text(json.dumps(card, indent=2), encoding="utf-8")
    a.out.with_suffix(".html").write_text(
        render(card, Path(__file__).with_name("card_template.html")), encoding="utf-8")
    print(f"wrote {a.out.with_suffix('.html')} and {a.out.with_suffix('.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
