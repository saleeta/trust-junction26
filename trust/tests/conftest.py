"""Shared fixtures: synthetic transcripts and throwaway git repositories."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for sub in ("session_graph", "ingest", "assumptions", "ab", "memory", "repro",
            "tree", "present", "proof"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------------------------------------------------------------------
# transcript building
# ---------------------------------------------------------------------------

class TranscriptBuilder:
    """Builds a JSONL transcript shaped like a real Claude Code session.

    Keeps the parent chain honest so `caused` / nearest-prompt logic is
    exercised the same way it is in production.
    """

    def __init__(self) -> None:
        self.recs: list[dict] = []
        self._n = 0
        self._last_uuid: str | None = None

    def _uuid(self, tag: str) -> str:
        self._n += 1
        return f"{tag}-{self._n:04d}-0000-0000-000000000000"

    def _ts(self) -> str:
        return f"2026-11-14T10:{self._n:02d}:00.000Z"

    def prompt(self, text: str) -> str:
        u = self._uuid("prmt")
        self.recs.append({
            "type": "user", "uuid": u, "parentUuid": self._last_uuid,
            "timestamp": self._ts(), "turnOrigin": "human",
            "promptSource": "typed", "cwd": "D:\\work\\demo",
            "sessionId": "test-session", "gitBranch": "main",
            "message": {"role": "user", "content": [{"type": "text", "text": text}]},
        })
        self._last_uuid = u
        return u

    def assistant_text(self, text: str) -> str:
        u = self._uuid("asst")
        self.recs.append({
            "type": "assistant", "uuid": u, "parentUuid": self._last_uuid,
            "timestamp": self._ts(), "sessionId": "test-session",
            "message": {"role": "assistant",
                        "content": [{"type": "thinking", "thinking": "", "signature": "x"},
                                    {"type": "text", "text": text}]},
        })
        self._last_uuid = u
        return u

    def tool_use(self, name: str, inp: dict, *, tool_id: str | None = None,
                 duplicate: bool = False) -> str:
        """Add a tool_use. `duplicate` re-logs the same block, as the real
        transcript does, so de-duplication by id gets exercised."""
        tid = tool_id or f"toolu_{self._n:04d}"
        u = self._uuid("asst")
        block = {"type": "tool_use", "id": tid, "name": name, "input": inp}
        self.recs.append({
            "type": "assistant", "uuid": u, "parentUuid": self._last_uuid,
            "timestamp": self._ts(), "sessionId": "test-session",
            "message": {"role": "assistant", "content": [block]},
        })
        self._last_uuid = u
        if duplicate:
            self.recs.append({
                "type": "assistant", "uuid": self._uuid("asst"),
                "parentUuid": self._last_uuid, "timestamp": self._ts(),
                "sessionId": "test-session",
                "message": {"role": "assistant", "content": [block]},
            })
        return tid

    def tool_result(self, tool_id: str, content: str, is_error: bool = False) -> None:
        u = self._uuid("tres")
        self.recs.append({
            "type": "user", "uuid": u, "parentUuid": self._last_uuid,
            "timestamp": self._ts(), "sessionId": "test-session",
            "toolUseResult": {"stdout": content, "stderr": ""},
            "message": {"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": tool_id,
                "content": content, "is_error": is_error}]},
        })
        self._last_uuid = u

    def write(self, path: str) -> str:
        """A non-human 'user' record that must NOT count as a prompt."""
        u = self._uuid("meta")
        self.recs.append({
            "type": "user", "uuid": u, "parentUuid": self._last_uuid,
            "timestamp": self._ts(), "isMeta": True, "sessionId": "test-session",
            "message": {"role": "user", "content": [{"type": "text", "text": path}]},
        })
        self._last_uuid = u
        return u

    def save(self, path: Path) -> Path:
        path.write_text(
            "\n".join(json.dumps(r) for r in self.recs), encoding="utf-8")
        return path


@pytest.fixture
def transcript(tmp_path):
    def _make() -> TranscriptBuilder:
        return TranscriptBuilder()
    _make.dir = tmp_path  # type: ignore[attr-defined]
    return _make


# ---------------------------------------------------------------------------
# git repositories
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t.t",
         "-c", "commit.gpgsign=false", *args],
        cwd=repo, capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {p.stderr}")
    return p.stdout.strip()


def _commit(repo: Path, files: dict[str, str], msg: str) -> str:
    for rel, body in files.items():
        f = repo / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def divergent_repo(tmp_path):
    """Reproduces the topology that produced a false finding in this project.

        master:   A --- B
                         \\
        (no ref):         X --- Y
                                 \\
        feature:                  F

    `origin/develop` does not exist, so a merge-base fallback to master returns
    B, while the branch was actually built on Y. first-parent and merge-base
    therefore disagree, exactly as they did for the ju26-* branches.
    """
    repo = tmp_path / "divergent"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")

    a = _commit(repo, {"README.md": "a\n"}, "A: root")
    b = _commit(repo, {"README.md": "b\n"}, "B: master tip")

    _git(repo, "checkout", "-q", "-b", "staging")
    x = _commit(repo, {"Directory.Packages.props": "v1\n"}, "X: bump dependency one")
    y = _commit(repo, {"Directory.Packages.props": "v2\n"}, "Y: bump dependency two")

    _git(repo, "checkout", "-q", "-b", "feature")
    f = _commit(repo, {"src/Thing.cs": "class Thing {}\n"}, "F: the agent's work")

    # the intermediate line has no surviving ref, as in the real fork
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "branch", "-q", "-D", "staging")

    return {"path": repo, "A": a, "B": b, "X": x, "Y": y, "F": f,
            "branch": "feature"}


@pytest.fixture
def guard_repo(tmp_path):
    """A repo whose feature branch introduces a TFM guard."""
    repo = tmp_path / "guarded"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "master")

    base = _commit(repo, {
        "src/Lib/Lib.csproj":
            "<Project><PropertyGroup><TargetFrameworks>"
            "netstandard2.0;net8.0</TargetFrameworks></PropertyGroup></Project>\n",
        "tests/LibTests/LibTests.csproj":
            "<Project><PropertyGroup><TargetFramework>net8.0"
            "</TargetFramework></PropertyGroup></Project>\n",
        "src/Lib/Thing.cs": "internal sealed class Thing { }\n",
    }, "base")

    _git(repo, "checkout", "-q", "-b", "feature")
    tip = _commit(repo, {
        "src/Lib/Thing.cs":
            "#if !NETSTANDARD2_0\n"
            "[global::System.Diagnostics.CodeAnalysis.ExcludeFromCodeCoverage]\n"
            "#endif\n"
            "internal sealed class Thing { }\n",
    }, "add guarded attribute")

    return {"path": repo, "base": base, "tip": tip, "branch": "feature"}
