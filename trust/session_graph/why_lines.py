"""
why_lines - per-line provenance for code written by an AI agent.

Answers "why does this line exist?" for any file an instrumented agent touched,
by replaying the session's edit operations and attaching, to each surviving
line, the operation that introduced it and the context around that operation.

WHAT THIS CAN AND CANNOT TELL YOU
---------------------------------
The answer is layered, and each layer has a different reliability. The tool
labels every layer rather than blending them into one confident story.

  L0  COMMIT    git blame: line -> commit -> message -> issue
                always available once committed; coarse (whole commit)
  L1  EDIT      the exact tool call that wrote the line
                EXACT, when a transcript exists
  L2  STATED    the agent's own narration around that call
                the author's CLAIM about its reasoning - not ground truth,
                and scoped to a BATCH of edits when one narration covers
                several, which the tool marks explicitly
  L3  TRIGGER   what caused the edit: the human prompt, a decision, or the
                tool result that preceded it
                structural, derived from parentUuid - verifiable
  L4  PRIVATE   the agent's internal reasoning
                NOT AVAILABLE. Claude Code stores `thinking` blocks with
                empty text and a signature only. Do not claim otherwise.

So the question this tool actually answers is:

    "What reason was recorded for this line, and does that reason hold up
     against the code?"

not

    "What truly caused this line?"

The first is auditable and falsifiable. The second is unknowable. That is not a
weakness: a recorded reason the code contradicts is exactly the hidden-defect
signal we are hunting (see DESIGN.md, trust.assumptions).

Usage:
    python why_lines.py --file build_graph.py --line 300
    python why_lines.py --file ../../DESIGN.md --all
    python why_lines.py --list
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from build_graph import (  # reuse the loader/ontology so both tools agree
    content_blocks,
    find_transcript,
    is_human_prompt,
    load_records,
    stringify,
    truncate,
)

WRITE_KINDS = ("Write", "Edit", "NotebookEdit")


@dataclass
class Op:
    """One file-mutating tool call."""
    seq: int
    kind: str                 # Write | Edit
    path: str
    uuid: str
    tool_use_id: str
    ts: str | None
    old: str = ""
    new: str = ""
    content: str = ""
    replace_all: bool = False
    narration: str = ""       # L2
    narration_shared_with: int = 1   # how many ops share this narration
    trigger: dict[str, Any] = field(default_factory=dict)  # L3
    failed: bool = False

    @property
    def label(self) -> str:
        return f"{self.kind}#{self.seq}"


def norm_path(p: str) -> str:
    return str(p).replace("\\", "/").lower()


# ---------------------------------------------------------------------------
# Build the operation timeline
# ---------------------------------------------------------------------------

def collect_ops(records: list[dict]) -> tuple[list[Op], dict[str, dict]]:
    by_uuid = {r["uuid"]: r for r in records if isinstance(r.get("uuid"), str)}

    # tool_use_id -> error flag
    errors: dict[str, bool] = {}
    for rec in records:
        for b in content_blocks(rec):
            if b.get("type") == "tool_result" and b.get("tool_use_id"):
                errors[b["tool_use_id"]] = bool(b.get("is_error"))

    # tool_use_id -> the tool result text, for L3 triggers
    results: dict[str, str] = {}
    for rec in records:
        for b in content_blocks(rec):
            if b.get("type") == "tool_result" and b.get("tool_use_id"):
                results[b["tool_use_id"]] = stringify(b.get("content"))

    def nearest_prompt(rec: dict) -> dict | None:
        cur, hops = rec, 0
        while cur is not None and hops < 300:
            hops += 1
            pid = cur.get("parentUuid")
            if not pid:
                return None
            parent = by_uuid.get(pid)
            if parent is None:
                return None
            if is_human_prompt(parent):
                return parent
            cur = parent
        return None

    def preceding_tool_result(rec: dict) -> tuple[str, str] | None:
        """The tool call whose result immediately preceded this edit (L3)."""
        cur, hops = rec, 0
        while cur is not None and hops < 40:
            hops += 1
            pid = cur.get("parentUuid")
            if not pid:
                return None
            parent = by_uuid.get(pid)
            if parent is None:
                return None
            for b in content_blocks(parent):
                if b.get("type") == "tool_result" and b.get("tool_use_id") in results:
                    tid = b["tool_use_id"]
                    desc = tool_descriptions.get(tid, "")
                    return desc, truncate(results[tid], 300)
            cur = parent
        return None

    # index tool descriptions so a trigger can be named
    tool_descriptions: dict[str, str] = {}
    for rec in records:
        for b in content_blocks(rec):
            if b.get("type") == "tool_use":
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                tool_descriptions[b.get("id", "")] = str(
                    inp.get("description") or b.get("name") or ""
                )

    ops: list[Op] = []
    seen: set[str] = set()
    last_text = ""
    narration_owners: dict[str, list[int]] = {}

    for rec in records:
        if rec.get("type") != "assistant":
            continue
        txt = " ".join(
            b.get("text", "") for b in content_blocks(rec) if b.get("type") == "text"
        ).strip()
        if txt:
            last_text = txt
        for b in content_blocks(rec):
            if b.get("type") != "tool_use":
                continue
            tid = b.get("id")
            if not tid or tid in seen:
                continue
            seen.add(tid)
            if b.get("name") not in WRITE_KINDS:
                continue
            inp = b.get("input") if isinstance(b.get("input"), dict) else {}
            path = str(inp.get("file_path") or "")
            if not path:
                continue
            prompt = nearest_prompt(rec)
            trig = preceding_tool_result(rec)
            op = Op(
                seq=len(ops),
                kind="Write" if b.get("name") == "Write" else "Edit",
                path=path,
                uuid=str(rec.get("uuid")),
                tool_use_id=tid,
                ts=rec.get("timestamp"),
                old=str(inp.get("old_string") or ""),
                new=str(inp.get("new_string") or ""),
                content=str(inp.get("content") or ""),
                replace_all=bool(inp.get("replace_all")),
                narration=last_text,
                failed=errors.get(tid, False),
                trigger={
                    "prompt_uuid": prompt.get("uuid") if prompt else None,
                    "prompt_text": truncate(
                        stringify([
                            x for x in content_blocks(prompt) if x.get("type") == "text"
                        ]), 240) if prompt else None,
                    "after_tool": trig[0] if trig else None,
                    "after_tool_output": trig[1] if trig else None,
                },
            )
            ops.append(op)
            narration_owners.setdefault(last_text, []).append(op.seq)

    for text, owners in narration_owners.items():
        for s in owners:
            ops[s].narration_shared_with = len(owners)

    return ops, by_uuid


# ---------------------------------------------------------------------------
# Replay + attribution
# ---------------------------------------------------------------------------

@dataclass
class LineAttr:
    lineno: int
    text: str
    op: Op | None


def apply_op(cur: str, op: Op) -> tuple[str, str | None]:
    """Return (new_content, error)."""
    if op.kind == "Write":
        return op.content, None
    if not op.old:
        return cur, "Edit with empty old_string"
    if op.old not in cur:
        return cur, "old_string not found in replayed content"
    if op.replace_all:
        return cur.replace(op.old, op.new), None
    if cur.count(op.old) > 1:
        return cur.replace(op.old, op.new, 1), "old_string was not unique"
    return cur.replace(op.old, op.new, 1), None


def replay(ops: list[Op], target: str, seed: str | None = None) -> tuple[list[LineAttr], list[str], str]:
    """Replay ops for one file; attribute each final line to the op that wrote it.

    `seed` is the file content BEFORE the session's first tracked edit (e.g.
    `git show <rev>:<path>`). Without it, replay starts empty and only works
    for files the session created with a Write. Lines that come from the seed
    are attributed to no op - the L0 commit layer covers them.
    """
    rel = [o for o in ops if norm_path(o.path).endswith(norm_path(target).lstrip("./"))]
    if not rel:
        return [], [f"no tracked edit operations for {target!r}"], ""

    warnings: list[str] = []
    if seed is None:
        content = ""
        owners: list[Op | None] = []
    else:
        content = seed
        owners = [None] * len(seed.splitlines())

    for op in rel:
        if op.failed:
            warnings.append(f"{op.label}: tool call failed; skipped")
            continue
        new_content, err = apply_op(content, op)
        if err:
            warnings.append(f"{op.label}: {err}")
            if new_content == content:
                continue

        old_lines = content.splitlines()
        new_lines = new_content.splitlines()
        new_owners: list[Op | None] = [None] * len(new_lines)

        sm = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                for k in range(j2 - j1):
                    idx = i1 + k
                    new_owners[j1 + k] = owners[idx] if idx < len(owners) else op
            else:
                for j in range(j1, j2):
                    new_owners[j] = op

        content, owners = new_content, new_owners

    attrs = [
        LineAttr(i + 1, line, owners[i] if i < len(owners) else None)
        for i, line in enumerate(content.splitlines())
    ]
    return attrs, warnings, content


# ---------------------------------------------------------------------------
# L0: git blame
# ---------------------------------------------------------------------------

def _repo_root(path: Path) -> Path | None:
    repo = path.resolve().parent
    while repo != repo.parent and not (repo / ".git").exists():
        repo = repo.parent
    return repo if (repo / ".git").exists() else None


def git_show_at(path: Path, rev: str) -> str | None:
    """The file's content at `rev`, to seed a replay for pre-existing files."""
    repo = _repo_root(path)
    if not repo:
        return None
    try:
        rel = str(path.resolve().relative_to(repo)).replace("\\", "/")
    except ValueError:
        return None
    try:
        out = subprocess.run(
            ["git", "show", f"{rev}:{rel}"],
            cwd=repo, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def git_blame(path: Path) -> dict[int, dict[str, str]] | None:
    repo = _repo_root(path)
    if not repo:
        return None
    try:
        out = subprocess.run(
            ["git", "blame", "--line-porcelain", "--", str(path.resolve())],
            cwd=repo, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    blame: dict[int, dict[str, str]] = {}
    sha = author = summary = ""
    for line in out.stdout.splitlines():
        m = re.match(r"^([0-9a-f]{40}) \d+ (\d+)", line)
        if m:
            sha, lineno = m.group(1), int(m.group(2))
            blame[lineno] = {"sha": sha[:9]}
        elif line.startswith("author "):
            author = line[7:]
        elif line.startswith("summary "):
            summary = line[8:]
        elif line.startswith("\t") and blame:
            last = max(blame)
            blame[last].update(author=author, summary=summary)
    return blame or None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

C = {
    "dim": "\033[2m", "b": "\033[1m", "r": "\033[0m",
    "cy": "\033[36m", "ye": "\033[33m", "gr": "\033[32m", "re": "\033[31m",
}


def no_color() -> None:
    for k in C:
        C[k] = ""


def explain(attr: LineAttr, blame: dict | None, verbose: bool = True) -> str:
    op = attr.op
    out = [f"{C['b']}line {attr.lineno}{C['r']}  {C['dim']}|{C['r']} {attr.text.strip()[:100]}"]
    if op is None:
        out.append(f"  {C['re']}L1 EDIT    no tracked operation wrote this line{C['r']}")
        out.append(f"  {C['dim']}           (shell redirect, external editor, or pre-existing){C['r']}")
    else:
        out.append(f"  {C['cy']}L1 EDIT   {C['r']} {op.kind} at {op.ts or '?'}")
        out.append(f"  {C['dim']}           transcript_uuid={op.uuid[:8]}  tool_use_id={op.tool_use_id[:14]}{C['r']}")
        scope = ("this edit only" if op.narration_shared_with == 1
                 else f"{C['ye']}BATCH of {op.narration_shared_with} edits - not line-specific{C['r']}")
        out.append(f"  {C['cy']}L2 STATED {C['r']} ({scope})")
        if verbose and op.narration:
            for ln in wrap(op.narration, 92):
                out.append(f"  {C['dim']}           {C['r']}{ln}")
        t = op.trigger
        if t.get("after_tool"):
            out.append(f"  {C['cy']}L3 TRIGGER{C['r']} followed: {t['after_tool']}")
        if t.get("prompt_text"):
            out.append(f"  {C['dim']}           human ask: {truncate(t['prompt_text'], 150)}{C['r']}")
    if blame and attr.lineno in blame:
        b = blame[attr.lineno]
        out.append(f"  {C['cy']}L0 COMMIT {C['r']} {b.get('sha','')} {b.get('summary','')} ({b.get('author','')})")
    else:
        out.append(f"  {C['dim']}L0 COMMIT  not committed{C['r']}")
    out.append(f"  {C['dim']}L4 PRIVATE unavailable - thinking blocks are stored empty{C['r']}")
    return "\n".join(out)


def wrap(s: str, w: int) -> list[str]:
    words, lines, cur = s.split(), [], ""
    for word in words:
        if len(cur) + len(word) + 1 > w:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return lines[:6]


def main(argv: list[str] | None = None) -> int:
    # Windows consoles default to cp1252 and mangle em-dashes in narration.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--session", help="session id or transcript path")
    ap.add_argument("--latest", action="store_true", default=True)
    ap.add_argument("--seed-rev", help=(
        "git revision holding the file content BEFORE this session's edits; "
        "pre-existing lines are then attributed to the L0 commit layer only"))
    ap.add_argument("--file", help="file to explain")
    ap.add_argument("--line", type=int, help="single line number")
    ap.add_argument("--range", help="line range, e.g. 100-140")
    ap.add_argument("--all", action="store_true", help="summarise every line")
    ap.add_argument("--list", action="store_true", help="list files this session wrote")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args(argv)

    if args.no_color or args.json:
        no_color()

    path = find_transcript(args.session, args.latest)
    records = load_records(path)
    ops, _ = collect_ops(records)

    if args.list or not args.file:
        files: dict[str, list[Op]] = {}
        for op in ops:
            files.setdefault(op.path, []).append(op)
        print(f"{C['b']}files mutated by tracked tool calls in this session{C['r']}")
        print(f"{C['dim']}(shell redirects are NOT tracked and will show as gaps){C['r']}\n")
        for f, fops in files.items():
            kinds = ", ".join(f"{o.kind}#{o.seq}" + ("(failed)" if o.failed else "") for o in fops)
            print(f"  {f}\n    {C['dim']}{kinds}{C['r']}")
        if not args.file:
            print(f"\nrun: python why_lines.py --file <path> --line <n>")
        return 0

    attrs, warnings, replayed = replay(
        ops, args.file,
        seed=git_show_at(Path(args.file).resolve(), args.seed_rev)
        if args.seed_rev else None)
    if not attrs:
        for w in warnings:
            print(f"{C['re']}{w}{C['r']}")
        return 1

    target = Path(args.file)
    disk = target.read_text(encoding="utf-8") if target.exists() else None
    diverged = disk is not None and disk != replayed
    blame = git_blame(target) if target.exists() else None

    if args.json:
        print(json.dumps({
            "file": str(target),
            "replay_matches_disk": not diverged,
            "seed_rev": args.seed_rev,
            "warnings": warnings,
            "layers_available": {
                "L0_commit": blame is not None, "L1_edit": True,
                "L2_stated": True, "L3_trigger": True, "L4_private": False,
            },
            "lines": [
                {
                    "lineno": a.lineno, "text": a.text,
                    "op": None if a.op is None else {
                        "kind": a.op.kind, "seq": a.op.seq, "ts": a.op.ts,
                        "transcript_uuid": a.op.uuid,
                        "tool_use_id": a.op.tool_use_id,
                        "stated_reason": a.op.narration,
                        "stated_reason_scope": (
                            "edit" if a.op.narration_shared_with == 1
                            else f"batch_of_{a.op.narration_shared_with}"),
                        "trigger": a.op.trigger,
                    },
                    "blame": (blame or {}).get(a.lineno),
                }
                for a in attrs
                if args.all or (args.line and a.lineno == args.line)
                or (args.range and in_range(a.lineno, args.range))
            ],
        }, indent=2, ensure_ascii=False))
        return 0

    print(f"{C['b']}{target}{C['r']}")
    print(f"{C['dim']}transcript {path.name}  |  {len(attrs)} lines replayed from "
          f"{len([o for o in ops if norm_path(o.path).endswith(norm_path(args.file).lstrip('./'))])} tracked ops{C['r']}")
    if diverged:
        print(f"{C['ye']}WARNING replayed content != file on disk.{C['r']}")
        print(f"{C['dim']}        The file was also changed outside tracked tool calls "
              f"(shell redirect / external editor). Attribution below covers only "
              f"tracked operations.{C['r']}")
    else:
        print(f"{C['gr']}replay matches disk exactly - attribution is complete{C['r']}")
    if args.seed_rev:
        print(f"{C['dim']}replay seeded from git rev {args.seed_rev}: pre-existing "
              f"lines are attributed to the L0 commit layer only{C['r']}")
    for w in warnings:
        print(f"{C['ye']}  note: {w}{C['r']}")
    print()

    if args.line:
        match = next((a for a in attrs if a.lineno == args.line), None)
        if match is None:
            print(f"{C['re']}line {args.line} out of range (1..{len(attrs)}){C['r']}")
            return 1
        print(explain(match, blame))
        return 0

    if args.range:
        for a in attrs:
            if in_range(a.lineno, args.range):
                print(explain(a, blame, verbose=False))
                print()
        return 0

    # --all : group contiguous lines by op
    groups: list[tuple[Op | None, int, int]] = []
    for a in attrs:
        if groups and groups[-1][0] is a.op:
            groups[-1] = (groups[-1][0], groups[-1][1], a.lineno)
        else:
            groups.append((a.op, a.lineno, a.lineno))
    print(f"{C['b']}attribution by region{C['r']}\n")
    for op, lo, hi in groups:
        span = f"{lo}" if lo == hi else f"{lo}-{hi}"
        if op is None:
            print(f"  {C['re']}{span:>12}{C['r']}  untracked (shell write or external edit)")
        else:
            scope = "" if op.narration_shared_with == 1 else f" {C['ye']}[batch]{C['r']}"
            print(f"  {C['cy']}{span:>12}{C['r']}  {op.kind}#{op.seq} {op.uuid[:8]}{scope}"
                  f"  {C['dim']}{truncate(op.narration, 70)}{C['r']}")
    return 0


def in_range(n: int, spec: str) -> bool:
    try:
        lo, hi = spec.split("-")
        return int(lo) <= n <= int(hi)
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
