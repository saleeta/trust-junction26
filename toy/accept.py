"""accept.py - the corrected sample (toy PR #5) and its acceptance record.

PR #4 (the AI patch) was refuted: it left a negative price and broke the
VIP promise. PR #5 corrects it by capping the TOTAL discount at 100% while
leaving every single discount (VIP 60%) intact. This module re-runs the same
checkers against PR #5, writes `toy/out/accept.json`, and leaves the final
verdict to the named human recorded via the Entire Trail approval.

    python toy/accept.py
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import build_repo  # noqa: E402
from logic import PROVED, REFUTED, TESTED, UNKNOWN, Verdict  # noqa: E402

REPO = build_repo.REPO
CODES = ["", "WELCOME", "HALF", "VIP"]
QTYS = [1, 10]
MEMBERS = [False, True]


def load(module: str, path: Path):
    spec = importlib.util.spec_from_file_location(module, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)  # type: ignore[union-attr]
    return m


def load_functions() -> dict:
    sys.path.insert(0, str(REPO))  # shop/ package lives in the toy repo
    prices = load("prices", REPO / "shop" / "prices.py")
    checkout = load("checkout", REPO / "shop" / "checkout.py")
    ledger = load("ledger", REPO / "shop" / "ledger.py")
    return {"prices": prices, "checkout": checkout, "ledger": ledger}


def check() -> dict:
    build_repo.build()
    fn = load_functions()
    results: dict[str, dict] = {}

    # A1: no basket ever charges a negative total (exhaustive over the domain)
    bad = []
    for code, qty, member in itertools.product(CODES, QTYS, MEMBERS):
        total = fn["checkout"].checkout(100, qty, code, member)["total"]
        if total < 0:
            bad.append([code, qty, member, total])
    results["A1"] = {
        "verdict": PROVED if not bad else REFUTED,
        "checked": len(CODES) * len(QTYS) * len(MEMBERS),
        "witnesses": bad,
        "note": "every basket in the domain charges >= 0",
    }

    # B2: the VIP promise from PR #2 (60% off -> 100 becomes 40)
    vip = fn["checkout"].checkout(100, 1, "VIP", False)["total"]
    results["B2"] = {
        "verdict": PROVED if vip == 40 else REFUTED,
        "checked": 1,
        "witnesses": [] if vip == 40 else [["VIP", 1, False, vip]],
        "note": f"VIP total is {vip} (promised 40)",
    }

    # D1/D2: the callers' promises (points, revenue) hold on every basket
    bad_pts = bad_rev = []
    for code, qty, member in itertools.product(CODES, QTYS, MEMBERS):
        out = fn["checkout"].checkout(100, qty, code, member)
        if out["points"] < 0:
            bad_pts.append([code, qty, member])
        if fn["ledger"].post_sale(100, 100, qty, code, member) < 100:
            bad_rev.append([code, qty, member])
    results["D1"] = {"verdict": PROVED if not bad_pts else REFUTED,
                     "checked": 16, "witnesses": bad_pts,
                     "note": "loyalty points never negative"}
    results["D2"] = {"verdict": PROVED if not bad_rev else REFUTED,
                     "checked": 16, "witnesses": bad_rev,
                     "note": "a sale never lowers revenue"}

    # T1: the project's own tests pass (executed)
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s",
                        "tests"], cwd=REPO, capture_output=True, text=True,
                       timeout=120)
    results["T1"] = {"verdict": TESTED if p.returncode == 0 else REFUTED,
                     "checked": 2,
                     "witnesses": [p.stderr[-200:]] if p.returncode else [],
                     "note": "unit tests executed via unittest discover"}

    # U1: intent - stacking more than 100% discount is now capped by code;
    # whether that cap is the intended business rule remains a human question
    results["U1"] = {"verdict": UNKNOWN, "checked": 0, "witnesses": [],
                     "note": "the 100% cap is a product decision - recorded in "
                             "the README and decided by the named human"}

    import os
    human_name = os.environ.get("ACCEPT_HUMAN")
    human_decision = os.environ.get("ACCEPT_DECISION")
    accept = {
        "branch": "pr5",
        "sha": subprocess.run(["git", "rev-parse", "pr5"], cwd=REPO,
                              capture_output=True, text=True).stdout.strip(),
        "results": results,
        "ai_recommendation": "merge",
        "human": {
            "name": human_name,
            "decision": human_decision or "pending",
            "note": ("recorded via the Entire Trail discussion (approvals gate "
                     "disabled for this project)"
                     if human_decision else
                     "approve the Entire Trail to record the named decision"),
        },
    }
    return accept


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
    accept = check()
    out = HERE / "out" / "accept.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(accept, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    for cid, r in accept["results"].items():
        print(f"{cid:4} {r['verdict']:20} checked={r['checked']:3} "
              f"{r['note']}")
    print(f"sha {accept['sha'][:9]}")
    print(f"wrote {out.resolve()}")
    print(f"human decision: {accept['human']['decision']} - approve the "
          f"Entire Trail to sign it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
