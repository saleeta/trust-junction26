"""Package only cleared public-sample material for the presentation.

The raw re-enactment transcript and capsule graph are intentionally excluded.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = (
    "CONCEPT_CARD.md", "TWO_MINUTE_DEMO.md",
    "demo/review-2297.html", "demo/review-2297.json",
)
PRIVATE_PATTERN = re.compile(
    rb"C:[\\/]+Users[\\/]+|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|"
    rb"sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}", re.I)


def package(out: Path) -> None:
    payload: list[tuple[str, bytes]] = []
    for name in ALLOWLIST:
        data = (ROOT / name).read_bytes()
        if PRIVATE_PATTERN.search(data):
            raise ValueError(f"personal path, email, or token pattern in {name}")
        payload.append((name, data))
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in payload:
            z.writestr(name, data)


if __name__ == "__main__":
    target = ROOT / "demo/stage-package.zip"
    package(target)
    print(f"wrote {target}; {len(ALLOWLIST)} cleared public-sample files")
