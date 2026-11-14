"""Sync the merged-PR snapshot the replay deck falls back to.

The deck's live mode calls the public GitHub API from the browser. Anonymous
API access is rate-limited per IP (60/hour), so at a venue the fetch can 403.
This script writes a committed snapshot of the repo's merged PRs
(`docs/prs.json`) and the deck falls back to it with an honest label:

    "GitHub API rate-limited - using the repo's committed PR snapshot."

Usage:
    python trust/present/sync_prs.py --repo saleeta/trust-junction26
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fetch_merged_prs(repo: str) -> list[dict]:
    out = subprocess.run(
        ["gh", "api",
         f"repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=100",
         "--jq",
         '[.[] | select(.merged_at != null) | {number: .number, title: .title, '
         'merged_at: .merged_at, html_url: .html_url}]'],
        capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        print(f"gh api failed: {out.stderr.strip()[:200]}", file=sys.stderr)
        return []
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return []
    data.sort(key=lambda p: p.get("merged_at") or "")
    return data[-4:]


def main(argv=None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default="saleeta/trust-junction26")
    args = ap.parse_args(argv)

    prs = fetch_merged_prs(args.repo)
    if not prs:
        print("no merged PRs found - snapshot not written")
        return 2
    payload = {"repo": args.repo, "source": "gh api (authenticated snapshot)",
               "generated": subprocess.run(
                   ["date", "+%Y-%m-%dT%H:%M:%SZ"], capture_output=True,
                   text=True).stdout.strip(),
               "prs": prs}
    for path in (ROOT / "docs" / "prs.json", ROOT / "demo" / "prs.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                        encoding="utf-8")
        print(f"wrote {path.resolve()} ({len(prs)} PRs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
