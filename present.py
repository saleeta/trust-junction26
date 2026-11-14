#!/usr/bin/env python
"""present.py - the interactive stage deck, built from the real pipeline.

    python present.py            # run the pipeline (quick mode) if needed,
                                 # then build demo/presentation.html
    python present.py --no-run   # build from existing .trust artifacts only

The deck is a single self-contained HTML file: arrow keys to navigate, click
any assumption card to expand it, click a command line to copy it, and the
context-tree slide is interactive. Every number on a slide comes from the
artifacts the pipeline produced - nothing is hand-written into the deck.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def pipeline_needed() -> bool:
    required = [
        ROOT / ".trust" / "bases.json",
        ROOT / ".trust" / "findings" / "2297-blast.json",
        ROOT / ".trust" / "tree" / "2297-tree.json",
        ROOT / ".trust" / "ab" / "2297.json",
        ROOT / ".trust" / "ab" / "2297-llm.json",
        ROOT / ".trust" / "findings" / "2297-proof.json",
        ROOT / "toy" / "out" / "review.json",
    ]
    return not all(p.exists() for p in required)


def run_step(cmd: list[str], cwd: Path, label: str) -> int:
    p = subprocess.run([sys.executable, *cmd], cwd=cwd, capture_output=True,
                       text=True, timeout=1800, encoding="utf-8",
                       errors="replace")
    if p.returncode != 0:
        print(f"{label} failed:")
        print((p.stdout or "")[-800:])
        print((p.stderr or "")[-400:])
    return p.returncode


def main() -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-run", action="store_true",
                    help="skip the pipeline; build from existing artifacts")
    ap.add_argument("--out", default="demo/presentation.html")
    args = ap.parse_args()

    if not args.no_run and pipeline_needed():
        print("artifacts missing - running the pipeline (python demo.py --quick)")
        rc = run_step(["demo.py", "--quick"], ROOT, "pipeline")
        if rc != 0:
            print("pipeline failed; fix it or use --no-run to build from "
                  "existing artifacts")
            return rc
        if not (ROOT / "toy" / "out" / "review.json").exists():
            print("toy review missing - running python toy/review.py")
            rc = run_step(["toy/review.py"], ROOT, "toy review")
            if rc != 0:
                return rc

    sys.path.insert(0, str(ROOT / "trust" / "present"))
    import build_presentation as bp
    return bp.main(["--root", str(ROOT), "--out", str(args.out)])


if __name__ == "__main__":
    raise SystemExit(main())
