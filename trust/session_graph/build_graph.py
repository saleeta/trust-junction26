"""
Build a knowledge graph from a Claude Code session transcript, fused with the
git history that session touched.

This is `trust.memory`'s temporal development graph (sprints.md #4, #5, #6, #28)
applied reflexively: the graph of the AI session that is building the AI
reviewer.

Design choice that matters: extraction is DETERMINISTIC. Every node and edge is
derived from transcript structure or from a real git object, so every element
carries provenance back to a `uuid`, a `file:line`, or a commit SHA. Nothing
here is an LLM's opinion. That is the trust contract from DESIGN.md section 1,
applied to our own tooling.

An optional LLM enrichment pass (--enrich, cookbook-style structured output)
adds semantic nodes (FINDING, REQUIREMENT, HYPOTHESIS). Those are tagged
`inferred: true` and rendered distinctly, never merged with observed facts.

Usage:
    python build_graph.py --session <session-id-or-path> --repo ../../repo
    python build_graph.py --latest --repo ../../repo --html graph.html
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Ontology
# ---------------------------------------------------------------------------
# Deliberately NOT the cookbook's PERSON/ORG/LOCATION/EVENT/ARTIFACT. The domain
# here is software provenance, so the types are the things a reviewer needs to
# trace a claim back to.

NODE_TYPES = [
    "PROMPT",      # a human turn
    "DECISION",    # an explicit user choice (AskUserQuestion)
    "TOOL_CALL",   # an action the agent took
    "FILE",        # a file read or written
    "ARTIFACT",    # a document this session produced
    "COMMIT",      # a real git commit, resolved against the repo
    "BRANCH",      # a git ref
    "SKILL",       # a skill invoked
    "AGENT",       # a subagent spawned
    "EXTERNAL",    # a URL consulted
    "FINDING",     # inferred: an evidence-backed claim
    "REQUIREMENT",  # inferred: a constraint the user stated
    "HYPOTHESIS",  # inferred: an unverified suspicion
]

EDGE_TYPES = [
    "follows",      # temporal succession between prompts
    "caused",       # prompt -> tool call it led to
    "invokes",      # tool call -> skill/agent
    "reads",        # tool call -> file
    "writes",       # tool call -> file/artifact
    "inspects",     # tool call -> commit/branch   <- fuses the two histories
    "fetches",      # tool call -> external url
    "answers",      # decision -> prompt it resolved
    "parent_of",    # commit -> parent commit      <- real git topology
    "tip_of",       # branch -> its head commit
    "cites",        # inferred node -> observed evidence
]


@dataclass
class Node:
    id: str
    type: str
    label: str
    detail: str = ""
    # provenance: how to check this node is real
    provenance: dict[str, Any] = field(default_factory=dict)
    ts: str | None = None
    inferred: bool = False
    mentions: int = 1


@dataclass
class Edge:
    source: str
    target: str
    type: str
    provenance: dict[str, Any] = field(default_factory=dict)


class Graph:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self._edge_keys: set[tuple[str, str, str]] = set()

    def add_node(self, node: Node) -> str:
        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
        else:
            existing.mentions += 1
            # keep the richest detail we have seen
            if len(node.detail) > len(existing.detail):
                existing.detail = node.detail
            if existing.ts is None:
                existing.ts = node.ts
        return node.id

    def add_edge(self, source: str, target: str, type_: str, **prov: Any) -> None:
        if source not in self.nodes or target not in self.nodes:
            return
        if source == target:
            return
        key = (source, target, type_)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self.edges.append(Edge(source, target, type_, prov))

    def to_dict(self, meta: dict[str, Any]) -> dict[str, Any]:
        return {
            "meta": meta,
            "node_types": NODE_TYPES,
            "edge_types": EDGE_TYPES,
            "nodes": [asdict(n) for n in self.nodes.values()],
            "edges": [asdict(e) for e in self.edges],
        }


# ---------------------------------------------------------------------------
# Transcript loading
# ---------------------------------------------------------------------------

def default_projects_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def find_transcript(session: str | None, latest: bool) -> Path:
    """Resolve a session id, a path, or --latest to a transcript file."""
    if session and Path(session).is_file():
        return Path(session)

    roots = [default_projects_dir()]
    candidates: list[Path] = []
    for root in roots:
        if root.is_dir():
            candidates.extend(root.glob("*/*.jsonl"))

    if session:
        for c in candidates:
            if c.stem == session:
                return c
        raise SystemExit(f"No transcript found for session id {session!r}")

    if not candidates:
        raise SystemExit(f"No transcripts found under {default_projects_dir()}")

    if latest:
        return max(candidates, key=lambda p: p.stat().st_mtime)

    raise SystemExit("Pass --session <id|path> or --latest")


def load_records(path: Path) -> list[dict]:
    recs = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return recs


def content_blocks(rec: dict) -> list[dict]:
    msg = rec.get("message")
    if isinstance(msg, dict):
        c = msg.get("content")
        if isinstance(c, list):
            return [b for b in c if isinstance(b, dict)]
        if isinstance(c, str):
            return [{"type": "text", "text": c}]
    return []


# ---------------------------------------------------------------------------
# Git resolution
# ---------------------------------------------------------------------------

class GitRepo:
    """Resolves SHAs and refs against a real repo. Unresolvable -> dropped.

    This is what keeps COMMIT nodes honest: a hex string in the conversation
    only becomes a node if git confirms it names an object.
    """

    SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b")
    REF_RE = re.compile(r"\b(?:origin/)?((?:ju26-issue-|ju26-re-|fix|v)[\w.\-/]+|master|develop|main)\b")

    def __init__(self, path: Path | None) -> None:
        self.path = path if path and (path / ".git").exists() else None
        self._commit_cache: dict[str, dict | None] = {}
        self._ref_cache: dict[str, str | None] = {}

    @property
    def available(self) -> bool:
        return self.path is not None

    def _git(self, *args: str) -> str | None:
        if not self.path:
            return None
        try:
            out = subprocess.run(
                ["git", *args],
                cwd=self.path,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if out.returncode != 0:
            return None
        return out.stdout.strip()

    def commit(self, rev: str) -> dict | None:
        if rev in self._commit_cache:
            return self._commit_cache[rev]
        result = None
        kind = self._git("cat-file", "-t", rev)
        if kind == "commit":
            raw = self._git(
                "show", "-s", "--format=%H%x1f%h%x1f%an%x1f%aI%x1f%s%x1f%P", rev
            )
            if raw and "\x1f" in raw:
                sha, short, author, date, subject, parents = (raw.split("\x1f") + [""] * 6)[:6]
                result = {
                    "sha": sha,
                    "short": short,
                    "author": author,
                    "date": date,
                    "subject": subject,
                    "parents": parents.split() if parents else [],
                }
        self._commit_cache[rev] = result
        return result

    def ref_tip(self, ref: str) -> str | None:
        if ref in self._ref_cache:
            return self._ref_cache[ref]
        sha = None
        for candidate in (ref, f"origin/{ref}"):
            got = self._git("rev-parse", "--verify", "--quiet", candidate)
            if got:
                sha = got
                break
        self._ref_cache[ref] = sha
        return sha

    def find_shas(self, text: str) -> list[dict]:
        """Return resolved commit records for every real SHA in `text`."""
        out: list[dict] = []
        seen: set[str] = set()
        for m in self.SHA_RE.finditer(text):
            tok = m.group(0)
            # Cheap guards before paying for a git call: pure-digit runs and
            # very long non-sha hex are almost never commits here.
            if tok.isdigit():
                continue
            c = self.commit(tok)
            if c and c["sha"] not in seen:
                seen.add(c["sha"])
                out.append(c)
        return out

    def find_refs(self, text: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        seen: set[str] = set()
        for m in self.REF_RE.finditer(text):
            name = m.group(1)
            if name in seen:
                continue
            seen.add(name)
            tip = self.ref_tip(name)
            if tip:
                out.append((name, tip))
        return out


# ---------------------------------------------------------------------------
# Path / URL extraction
# ---------------------------------------------------------------------------

CODE_EXT = (
    ".py", ".cs", ".md", ".json", ".yaml", ".yml", ".props", ".targets",
    ".csproj", ".sln", ".tt", ".jsonl", ".html", ".js", ".ts", ".txt", ".toml",
    ".cfg", ".ini", ".sh", ".ps1",
)

PATH_RE = re.compile(r"[A-Za-z0-9_./\\~$-]*[A-Za-z0-9_-]+(" + "|".join(re.escape(e) for e in CODE_EXT) + r")\b")
URL_RE = re.compile(r"https?://[^\s\"'`<>)\]]+")

NOISE_PATH_FRAGMENTS = ("*", "$", "node_modules")


def normalise_path(raw: str) -> str | None:
    p = raw.strip().strip("'\"`,;:")
    if not p or any(f in p for f in NOISE_PATH_FRAGMENTS):
        return None
    # reject bare extensions (".g.cs") and literals that are not paths ("null")
    base = re.split(r"[\\/]", p)[-1]
    if base.lower() in {"null", "none", "true", "false", "undefined"}:
        return None
    if not re.match(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*\.[A-Za-z0-9]+$", base):
        return None
    if not re.match(r"^[A-Za-z0-9_][A-Za-z0-9_-]*", base.split(".")[0] or ""):
        return None
    p = p.replace("\\", "/")
    # collapse the windows drive form so D:/x and /d/x unify
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    if m:
        p = f"/{m.group(1).lower()}/{m.group(2)}"
    if p.startswith("~"):
        p = "~" + p[1:]
    if len(p) < 4 or "/" not in p and not p.endswith(CODE_EXT):
        return None
    return p


def extract_paths(text: str, limit: int = 12) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for m in PATH_RE.finditer(text):
        p = normalise_path(m.group(0))
        if p and p not in seen:
            seen.add(p)
            out.append(p)
        if len(out) >= limit:
            break
    return out


def extract_urls(text: str, limit: int = 6) -> list[str]:
    out, seen = [], set()
    for m in URL_RE.finditer(text):
        u = m.group(0).rstrip(".,")
        if u not in seen:
            seen.add(u)
            out.append(u)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# Writing tools vs reading tools
# ---------------------------------------------------------------------------

WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}
READ_TOOLS = {"Read", "Grep", "Glob"}
WRITE_CMD_RE = re.compile(r"(?:>>?\s*|tee\s+|mkdir\s+-p\s+|cat\s*>\s*)([A-Za-z0-9_./\\~$-]+)")


def truncate(s: str, n: int = 400) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "\u2026"


# ---------------------------------------------------------------------------
# The builder
# ---------------------------------------------------------------------------

class SessionGraphBuilder:
    def __init__(self, records: list[dict], repo: GitRepo) -> None:
        self.records = records
        self.repo = repo
        self.g = Graph()
        self.by_uuid: dict[str, dict] = {
            r["uuid"]: r for r in records if isinstance(r.get("uuid"), str)
        }
        # tool_use_id -> result payload, for success/failure status
        self.results: dict[str, dict] = {}
        self.stats: Counter = Counter()

    # -- helpers ---------------------------------------------------------
    def nearest_prompt(self, rec: dict) -> str | None:
        """Walk parentUuid up to the human turn that caused this record."""
        seen = 0
        cur = rec
        while cur is not None and seen < 200:
            seen += 1
            pid = cur.get("parentUuid")
            if not pid:
                return None
            parent = self.by_uuid.get(pid)
            if parent is None:
                return None
            if is_human_prompt(parent):
                return f"prompt:{parent['uuid']}"
            cur = parent
        return None

    def index_results(self) -> None:
        for rec in self.records:
            for b in content_blocks(rec):
                if b.get("type") == "tool_result":
                    tid = b.get("tool_use_id")
                    if tid:
                        payload = {
                            "is_error": bool(b.get("is_error")),
                            "content": stringify(b.get("content")),
                        }
                        # a record-level toolUseResult carries stderr/stdout
                        tur = rec.get("toolUseResult")
                        if isinstance(tur, dict):
                            payload["stderr"] = truncate(tur.get("stderr") or "", 300)
                        self.results[tid] = payload

    # -- passes ----------------------------------------------------------
    def add_prompts(self) -> None:
        prompts: list[tuple[str, str]] = []  # (ts, node_id)
        for rec in self.records:
            if not is_human_prompt(rec):
                continue
            text = "\n".join(
                b.get("text", "") for b in content_blocks(rec) if b.get("type") == "text"
            ).strip()
            if not text:
                continue
            nid = f"prompt:{rec['uuid']}"
            self.g.add_node(Node(
                id=nid,
                type="PROMPT",
                label=truncate(text, 60),
                detail=truncate(text, 1500),
                ts=rec.get("timestamp"),
                provenance={
                    "transcript_uuid": rec["uuid"],
                    "source": rec.get("promptSource"),
                    "cwd": rec.get("cwd"),
                    "git_branch": rec.get("gitBranch"),
                },
            ))
            prompts.append((rec.get("timestamp") or "", nid))
            self.stats["prompts"] += 1

        prompts.sort()
        for (_, a), (_, b) in zip(prompts, prompts[1:]):
            self.g.add_edge(a, b, "follows")

    def add_tool_calls(self) -> None:
        seen_ids: set[str] = set()
        for rec in self.records:
            if rec.get("type") != "assistant":
                continue
            for b in content_blocks(rec):
                if b.get("type") != "tool_use":
                    continue
                tid = b.get("id")
                if not tid or tid in seen_ids:
                    continue  # transcript logs each block more than once
                seen_ids.add(tid)
                self._add_one_tool_call(rec, b, tid)

    def _add_one_tool_call(self, rec: dict, block: dict, tid: str) -> None:
        name = block.get("name") or "?"
        inp = block.get("input") if isinstance(block.get("input"), dict) else {}
        res = self.results.get(tid, {})
        failed = bool(res.get("is_error"))

        label = inp.get("description") or inp.get("skill") or name
        nid = f"tool:{tid}"
        self.g.add_node(Node(
            id=nid,
            type="TOOL_CALL",
            label=truncate(f"{name}: {label}", 60),
            detail=truncate(json.dumps(inp, ensure_ascii=False), 1200),
            ts=rec.get("timestamp"),
            provenance={
                "transcript_uuid": rec.get("uuid"),
                "tool": name,
                "tool_use_id": tid,
                "status": "error" if failed else "ok",
                "request_id": rec.get("requestId"),
            },
        ))
        self.stats[f"tool:{name}"] += 1

        prompt_id = self.nearest_prompt(rec)
        if prompt_id:
            self.g.add_edge(prompt_id, nid, "caused")

        # --- searchable text for this call: input + result
        blob = json.dumps(inp, ensure_ascii=False) + "\n" + stringify(res.get("content"))

        self._link_skills_and_agents(nid, name, inp)
        self._link_files(nid, name, inp, blob)
        self._link_git(nid, blob)
        self._link_urls(nid, blob)

    def _link_skills_and_agents(self, nid: str, name: str, inp: dict) -> None:
        if name == "Skill" and inp.get("skill"):
            skill = str(inp["skill"])
            sid = f"skill:{skill}"
            self.g.add_node(Node(
                id=sid, type="SKILL", label=skill,
                detail=truncate(str(inp.get("args") or ""), 400),
                provenance={"invoked_as": skill},
            ))
            self.g.add_edge(nid, sid, "invokes")
        if name == "Agent":
            sub = str(inp.get("subagent_type") or "general-purpose")
            aid = f"agent:{sub}"
            self.g.add_node(Node(
                id=aid, type="AGENT", label=sub,
                detail=truncate(str(inp.get("prompt") or ""), 600),
                provenance={"subagent_type": sub},
            ))
            self.g.add_edge(nid, aid, "invokes")

    def _link_files(self, nid: str, name: str, inp: dict, blob: str) -> None:
        written: set[str] = set()
        read: set[str] = set()

        if name in WRITE_TOOLS and inp.get("file_path"):
            p = normalise_path(str(inp["file_path"]))
            if p:
                written.add(p)
        if name in READ_TOOLS and inp.get("file_path"):
            p = normalise_path(str(inp["file_path"]))
            if p:
                read.add(p)

        cmd = str(inp.get("command") or "")
        if cmd:
            for m in WRITE_CMD_RE.finditer(cmd):
                p = normalise_path(m.group(1))
                if p:
                    written.add(p)
            for p in extract_paths(cmd):
                if p not in written:
                    read.add(p)

        for p in extract_paths(blob, limit=8):
            if p not in written:
                read.add(p)

        for p in sorted(written):
            self._add_file(p, is_artifact=True)
            self.g.add_edge(nid, f"file:{p}", "writes")
        for p in sorted(read - written):
            self._add_file(p)
            self.g.add_edge(nid, f"file:{p}", "reads")

    def _add_file(self, path: str, is_artifact: bool = False) -> None:
        existing = self.g.nodes.get(f"file:{path}")
        ntype = "ARTIFACT" if is_artifact else "FILE"
        if existing is not None:
            # once written by this session it is an artifact, permanently
            if is_artifact:
                existing.type = "ARTIFACT"
            existing.mentions += 1
            return
        self.g.add_node(Node(
            id=f"file:{path}",
            type=ntype,
            label=path.rsplit("/", 1)[-1],
            detail=path,
            provenance={"path": path},
        ))

    def _link_git(self, nid: str, blob: str) -> None:
        if not self.repo.available:
            return
        for c in self.repo.find_shas(blob)[:10]:
            cid = f"commit:{c['sha']}"
            self.g.add_node(Node(
                id=cid, type="COMMIT", label=f"{c['short']} {truncate(c['subject'], 40)}",
                detail=c["subject"], ts=c["date"],
                provenance={
                    "sha": c["sha"], "author": c["author"],
                    "date": c["date"], "subject": c["subject"],
                    "parents": c["parents"],
                    "verify": f"git show {c['short']}",
                },
            ))
            self.g.add_edge(nid, cid, "inspects")
        for name, tip in self.repo.find_refs(blob)[:12]:
            bid = f"branch:{name}"
            self.g.add_node(Node(
                id=bid, type="BRANCH", label=name,
                detail=f"tip {tip[:9]}",
                provenance={"ref": name, "tip": tip, "verify": f"git log -1 {name}"},
            ))
            self.g.add_edge(nid, bid, "inspects")

    def _link_urls(self, nid: str, blob: str) -> None:
        for u in extract_urls(blob):
            uid = f"url:{u}"
            host = re.sub(r"^https?://", "", u).split("/")[0]
            self.g.add_node(Node(
                id=uid, type="EXTERNAL", label=host,
                detail=u, provenance={"url": u},
            ))
            self.g.add_edge(nid, uid, "fetches")

    def add_decisions(self) -> None:
        """AskUserQuestion answers are the highest-value nodes in the graph:
        the points where a human actually steered the work."""
        seen: set[str] = set()
        for rec in self.records:
            if rec.get("type") != "assistant":
                continue
            for b in content_blocks(rec):
                if b.get("type") != "tool_use" or b.get("name") != "AskUserQuestion":
                    continue
                tid = b.get("id")
                if not tid or tid in seen:
                    continue
                seen.add(tid)
                inp = b.get("input") or {}
                res = self.results.get(tid, {})
                answers = parse_answers(stringify(res.get("content")))
                for q in (inp.get("questions") or []):
                    if not isinstance(q, dict):
                        continue
                    qtext = str(q.get("question") or "")
                    header = str(q.get("header") or "decision")
                    chosen = answers.get(qtext)
                    did = f"decision:{tid}:{header}"
                    options = [
                        str(o.get("label")) for o in (q.get("options") or [])
                        if isinstance(o, dict)
                    ]
                    self.g.add_node(Node(
                        id=did, type="DECISION",
                        label=f"{header}: {truncate(chosen or 'unanswered', 40)}",
                        detail=qtext,
                        ts=rec.get("timestamp"),
                        provenance={
                            "question": qtext,
                            "chosen": chosen,
                            "options": options,
                            "rejected": [o for o in options if o != chosen],
                            "tool_use_id": tid,
                            "transcript_uuid": rec.get("uuid"),
                        },
                    ))
                    self.stats["decisions"] += 1
                    self.g.add_edge(did, f"tool:{tid}", "answers")
                    prompt_id = self.nearest_prompt(rec)
                    if prompt_id:
                        self.g.add_edge(did, prompt_id, "answers")

    def add_git_topology(self) -> None:
        """Link the commits we collected to each other, and branches to tips.

        This is the join that makes it one graph instead of two: conversation
        nodes point at commits via `inspects`, and commits point at each other
        via real git parentage.
        """
        if not self.repo.available:
            return
        commit_ids = {
            n.provenance.get("sha"): nid
            for nid, n in self.g.nodes.items() if n.type == "COMMIT"
        }
        for nid, n in list(self.g.nodes.items()):
            if n.type != "COMMIT":
                continue
            for parent in n.provenance.get("parents", []) or []:
                pc = self.repo.commit(parent)
                if not pc:
                    continue
                pid = commit_ids.get(pc["sha"])
                if pid:
                    self.g.add_edge(nid, pid, "parent_of")

        for nid, n in list(self.g.nodes.items()):
            if n.type != "BRANCH":
                continue
            tip = n.provenance.get("tip")
            if not tip:
                continue
            tc = self.repo.commit(tip)
            if not tc:
                continue
            cid = commit_ids.get(tc["sha"])
            if cid is None:
                cid = f"commit:{tc['sha']}"
                self.g.add_node(Node(
                    id=cid, type="COMMIT",
                    label=f"{tc['short']} {truncate(tc['subject'], 40)}",
                    detail=tc["subject"], ts=tc["date"],
                    provenance={
                        "sha": tc["sha"], "author": tc["author"],
                        "date": tc["date"], "subject": tc["subject"],
                        "parents": tc["parents"],
                        "verify": f"git show {tc['short']}",
                    },
                ))
            self.g.add_edge(nid, cid, "tip_of")

    def build(self) -> Graph:
        self.index_results()
        self.add_prompts()
        self.add_tool_calls()
        self.add_decisions()
        self.add_git_topology()
        return self.g


def is_human_prompt(rec: dict) -> bool:
    if rec.get("type") != "user":
        return False
    if rec.get("isMeta") or rec.get("isSidechain"):
        return False
    if rec.get("turnOrigin") not in (None, "human"):
        return False
    blocks = content_blocks(rec)
    if not blocks:
        return False
    # a real human turn is text, not a tool result
    return all(b.get("type") == "text" for b in blocks)


def stringify(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        parts = []
        for b in x:
            if isinstance(b, dict):
                parts.append(b.get("text") or json.dumps(b, ensure_ascii=False))
            else:
                parts.append(str(b))
        return "\n".join(parts)
    if isinstance(x, dict):
        return json.dumps(x, ensure_ascii=False)
    return str(x)


ANSWER_RE = re.compile(r'"([^"]+)"="([^"]+)"')


def parse_answers(text: str) -> dict[str, str]:
    """AskUserQuestion results arrive as prose:  "question"="answer"."""
    return {m.group(1): m.group(2) for m in ANSWER_RE.finditer(text or "")}


# ---------------------------------------------------------------------------
# Optional LLM enrichment (cookbook-style structured extraction)
# ---------------------------------------------------------------------------

ENRICH_PROMPT = """Extract the substantive conclusions from this AI coding session.

<session>
{text}
</session>

Guidelines:
- A FINDING is a claim the session established with evidence (a file, a commit,
  a command's output). Record the evidence.
- A REQUIREMENT is a constraint or goal the human stated.
- A HYPOTHESIS is something suspected but not demonstrated.
- Extract only what the transcript supports. Do not add outside knowledge.
- `evidence` must quote an identifier that appears in the session: a path, a
  SHA, a branch name, or a command.
"""


def enrich_with_llm(graph: Graph, records: list[dict], model: str) -> int:
    """Add inferred semantic nodes. Requires `anthropic` and an API key."""
    try:
        from anthropic import Anthropic  # type: ignore
        from pydantic import BaseModel  # type: ignore
    except ImportError:
        print("  [enrich] skipped: pip install anthropic pydantic", file=sys.stderr)
        return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  [enrich] skipped: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 0

    from typing import Literal

    class Claim(BaseModel):
        kind: Literal["FINDING", "REQUIREMENT", "HYPOTHESIS"]
        statement: str
        evidence: list[str]

    class Claims(BaseModel):
        claims: list[Claim]

    # Feed only human turns and assistant prose: tool output is already in the
    # deterministic layer and would blow the context budget.
    chunks: list[str] = []
    for rec in records:
        if rec.get("type") == "user" and is_human_prompt(rec):
            t = stringify([b for b in content_blocks(rec) if b.get("type") == "text"])
            chunks.append(f"HUMAN: {t}")
        elif rec.get("type") == "assistant":
            t = "\n".join(
                b.get("text", "") for b in content_blocks(rec) if b.get("type") == "text"
            ).strip()
            if t:
                chunks.append(f"ASSISTANT: {t}")
    text = "\n\n".join(chunks)[:120_000]

    client = Anthropic()
    try:
        resp = client.messages.parse(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": ENRICH_PROMPT.format(text=text)}],
            output_format=Claims,
        )
        claims = resp.parsed_output.claims
    except Exception as exc:  # noqa: BLE001 - enrichment is best-effort
        print(f"  [enrich] failed: {exc}", file=sys.stderr)
        return 0

    # index observed nodes so `cites` edges land on real evidence
    index: list[tuple[str, str]] = []
    for nid, n in graph.nodes.items():
        for key in (n.label, n.detail, str(n.provenance.get("sha", "")),
                    str(n.provenance.get("path", "")), str(n.provenance.get("ref", ""))):
            if key and len(key) > 3:
                index.append((key.lower(), nid))

    added = 0
    for i, c in enumerate(claims):
        nid = f"claim:{i}"
        graph.add_node(Node(
            id=nid, type=c.kind, label=truncate(c.statement, 60),
            detail=c.statement, inferred=True,
            provenance={"evidence": c.evidence, "extracted_by": model},
        ))
        added += 1
        for ev in c.evidence:
            ev_l = ev.lower().strip()
            if len(ev_l) < 4:
                continue
            for key, target in index:
                if ev_l in key or key in ev_l:
                    graph.add_edge(nid, target, "cites", evidence=ev)
                    break
    return added


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", help="session id or path to a .jsonl transcript")
    ap.add_argument("--latest", action="store_true", help="use the most recent transcript")
    ap.add_argument("--repo", default=None, help="git repo to resolve SHAs/refs against")
    ap.add_argument("--out", default="session_graph.json", help="graph JSON output")
    ap.add_argument("--html", default=None, help="also render a standalone HTML viewer")
    ap.add_argument("--enrich", action="store_true", help="add LLM-inferred semantic nodes")
    ap.add_argument("--model", default="claude-sonnet-5-5", help="model for --enrich")
    args = ap.parse_args(argv)

    path = find_transcript(args.session, args.latest)
    records = load_records(path)
    print(f"transcript : {path}")
    print(f"records    : {len(records)}")

    repo_path = Path(args.repo).resolve() if args.repo else None
    repo = GitRepo(repo_path)
    print(f"repo       : {repo_path if repo.available else '(none - COMMIT/BRANCH nodes disabled)'}")

    builder = SessionGraphBuilder(records, repo)
    graph = builder.build()

    inferred = 0
    if args.enrich:
        inferred = enrich_with_llm(graph, records, args.model)

    session_id = next(
        (r.get("sessionId") for r in records if r.get("sessionId")), path.stem
    )
    cwd = next((r.get("cwd") for r in records if r.get("cwd")), None)
    times = sorted(t for t in (r.get("timestamp") for r in records) if t)

    type_counts = Counter(n.type for n in graph.nodes.values())
    edge_counts = Counter(e.type for e in graph.edges)

    meta = {
        "session_id": session_id,
        "transcript": str(path),
        "cwd": cwd,
        "repo": str(repo_path) if repo.available else None,
        "started": times[0] if times else None,
        "ended": times[-1] if times else None,
        "records": len(records),
        "node_counts": dict(type_counts),
        "edge_counts": dict(edge_counts),
        "inferred_nodes": inferred,
        "extraction": "deterministic" + (" + llm-enriched" if inferred else ""),
    }

    data = graph.to_dict(meta)
    out = Path(args.out)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nnodes      : {len(graph.nodes)}")
    for t, c in type_counts.most_common():
        print(f"  {t:12} {c}")
    print(f"edges      : {len(graph.edges)}")
    for t, c in edge_counts.most_common():
        print(f"  {t:12} {c}")
    print(f"\nwrote      : {out.resolve()}")

    if args.html:
        try:
            from render_html import render
        except ImportError:
            sys.path.insert(0, str(Path(__file__).parent))
            from render_html import render  # type: ignore
        html_path = Path(args.html)
        html_path.write_text(render(data), encoding="utf-8")
        print(f"wrote      : {html_path.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
