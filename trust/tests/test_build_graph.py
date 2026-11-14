"""
Tests for trust.session_graph.build_graph.

Two of these are regressions for bugs shipped during this session:
  - junk FILE nodes ('null', bare '.g.cs') reached the graph
  - COMMIT nodes lacked `parents`, so `parent_of` edges never formed
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import build_graph as bg


# ---------------------------------------------------------------------------
# path normalisation - REGRESSION
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", [
    "null", "none", "true", "false", "undefined",
    ".g.cs", ".verified.txt",            # bare extensions, no stem
    "", "   ", "*.cs", "$VAR.cs",
    "node_modules/pkg/index.js",
])
def test_normalise_path_rejects_junk(raw):
    """REGRESSION: 'null' and '.g.cs' became FILE nodes in the first build."""
    assert bg.normalise_path(raw) is None


@pytest.mark.parametrize("raw,expected", [
    ("D:\\work\\big-hackathon\\DESIGN.md", "/d/work/big-hackathon/DESIGN.md"),
    ("d:/work/x/y.py", "/d/work/x/y.py"),
    ("src/MessagePack/Reader.cs", "src/MessagePack/Reader.cs"),
    ("Directory.Packages.props", "Directory.Packages.props"),
])
def test_normalise_path_normalises(raw, expected):
    assert bg.normalise_path(raw) == expected


def test_windows_and_posix_paths_unify():
    """The same file reached through both spellings must be ONE node."""
    assert bg.normalise_path("D:\\work\\a\\b.cs") == bg.normalise_path("d:/work/a/b.cs")


# ---------------------------------------------------------------------------
# human prompt detection
# ---------------------------------------------------------------------------

def test_is_human_prompt_accepts_typed_turn():
    rec = {"type": "user", "turnOrigin": "human",
           "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}}
    assert bg.is_human_prompt(rec) is True


@pytest.mark.parametrize("overrides", [
    {"isMeta": True},
    {"isSidechain": True},
    {"turnOrigin": "system"},
    {"type": "assistant"},
])
def test_is_human_prompt_rejects_non_human(overrides):
    rec = {"type": "user", "turnOrigin": "human",
           "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]}}
    rec.update(overrides)
    assert bg.is_human_prompt(rec) is False


def test_tool_result_is_not_a_prompt():
    """Tool results arrive as role=user and must never count as human turns."""
    rec = {"type": "user", "turnOrigin": "human", "message": {"role": "user",
           "content": [{"type": "tool_result", "tool_use_id": "t", "content": "x"}]}}
    assert bg.is_human_prompt(rec) is False


# ---------------------------------------------------------------------------
# AskUserQuestion answer parsing
# ---------------------------------------------------------------------------

def test_parse_answers_extracts_choice():
    text = ('Your questions have been answered: "Which engine?"="Hybrid". '
            'You can now continue.')
    assert bg.parse_answers(text) == {"Which engine?": "Hybrid"}


def test_parse_answers_handles_multiple_and_empty():
    text = '"A"="1", "B"="2"'
    assert bg.parse_answers(text) == {"A": "1", "B": "2"}
    assert bg.parse_answers("") == {}
    assert bg.parse_answers(None) == {}


# ---------------------------------------------------------------------------
# graph primitives
# ---------------------------------------------------------------------------

def test_graph_dedupes_edges_and_counts_mentions():
    g = bg.Graph()
    g.add_node(bg.Node(id="a", type="FILE", label="a"))
    g.add_node(bg.Node(id="a", type="FILE", label="a"))
    g.add_node(bg.Node(id="b", type="FILE", label="b"))
    g.add_edge("a", "b", "reads")
    g.add_edge("a", "b", "reads")
    g.add_edge("a", "b", "writes")

    assert g.nodes["a"].mentions == 2
    assert len(g.edges) == 2, "same (src,tgt,type) must collapse"


def test_graph_rejects_dangling_and_self_edges():
    g = bg.Graph()
    g.add_node(bg.Node(id="a", type="FILE", label="a"))
    g.add_edge("a", "missing", "reads")
    g.add_edge("a", "a", "reads")
    assert g.edges == []


# ---------------------------------------------------------------------------
# end-to-end over a synthetic transcript
# ---------------------------------------------------------------------------

def build(transcript, tmp_path, repo=None):
    t = transcript()
    t.prompt("please inspect the branch")
    t.assistant_text("Looking now.")
    tid = t.tool_use("Bash", {"command": "git log -1", "description": "Inspect log"},
                     duplicate=True)
    t.tool_result(tid, "deadbeef some subject")
    w = t.tool_use("Write", {"file_path": "D:\\proj\\out.py", "content": "x = 1\n"})
    t.tool_result(w, "written")
    path = t.save(tmp_path / "s.jsonl")
    records = bg.load_records(path)
    builder = bg.SessionGraphBuilder(records, bg.GitRepo(repo))
    return builder.build()


def test_duplicate_tool_use_blocks_make_one_node(transcript, tmp_path):
    """The transcript logs each tool_use twice; dedupe by id."""
    g = build(transcript, tmp_path)
    tool_nodes = [n for n in g.nodes.values() if n.type == "TOOL_CALL"]
    assert len(tool_nodes) == 2, "Bash + Write, each once"


def test_write_produces_artifact_and_prompt_causes_tools(transcript, tmp_path):
    g = build(transcript, tmp_path)
    artifacts = [n for n in g.nodes.values() if n.type == "ARTIFACT"]
    assert any(n.label == "out.py" for n in artifacts)
    assert any(e.type == "writes" for e in g.edges)
    assert any(e.type == "caused" for e in g.edges), "prompt -> tool call"


def test_no_commit_nodes_without_a_repo(transcript, tmp_path):
    """'deadbeef' looks like a SHA but must not become a node unresolved."""
    g = build(transcript, tmp_path, repo=None)
    assert not [n for n in g.nodes.values() if n.type == "COMMIT"]


# ---------------------------------------------------------------------------
# git fusion - REGRESSION
# ---------------------------------------------------------------------------

def test_commit_nodes_store_parents_so_parent_of_forms(transcript, divergent_repo,
                                                       tmp_path):
    """REGRESSION: _link_git omitted `parents`, so add_git_topology could never
    emit parent_of and the two histories stayed unjoined."""
    t = transcript()
    t.prompt("look at history")
    tid = t.tool_use("Bash", {
        "command": f"git log {divergent_repo['F']} {divergent_repo['Y']}",
        "description": "history"})
    t.tool_result(tid, f"{divergent_repo['F']}\n{divergent_repo['Y']}\n")
    path = t.save(tmp_path / "s2.jsonl")

    g = bg.SessionGraphBuilder(
        bg.load_records(path), bg.GitRepo(divergent_repo["path"])).build()

    commits = [n for n in g.nodes.values() if n.type == "COMMIT"]
    assert len(commits) >= 2
    assert all("parents" in n.provenance for n in commits)
    assert any(e.type == "parent_of" for e in g.edges), \
        "F -> Y parentage must appear as an edge"


def test_only_real_shas_become_commit_nodes(transcript, divergent_repo, tmp_path):
    t = transcript()
    t.prompt("mixed shas")
    tid = t.tool_use("Bash", {"command": "echo", "description": "d"})
    t.tool_result(tid, f"real={divergent_repo['Y']} fake=abcdef1234567890abcd")
    path = t.save(tmp_path / "s3.jsonl")

    g = bg.SessionGraphBuilder(
        bg.load_records(path), bg.GitRepo(divergent_repo["path"])).build()
    shas = {n.provenance["sha"] for n in g.nodes.values() if n.type == "COMMIT"}
    assert divergent_repo["Y"] in shas
    assert not any(s.startswith("abcdef1234") for s in shas)


def test_commit_nodes_carry_a_verify_command(transcript, divergent_repo, tmp_path):
    t = transcript()
    t.prompt("x")
    tid = t.tool_use("Bash", {"command": "echo", "description": "d"})
    t.tool_result(tid, divergent_repo["Y"])
    path = t.save(tmp_path / "s4.jsonl")
    g = bg.SessionGraphBuilder(
        bg.load_records(path), bg.GitRepo(divergent_repo["path"])).build()
    for n in g.nodes.values():
        if n.type == "COMMIT":
            assert n.provenance["verify"].startswith("git show")


# ---------------------------------------------------------------------------
# serialisation
# ---------------------------------------------------------------------------

def test_to_dict_is_json_serialisable(transcript, tmp_path):
    g = build(transcript, tmp_path)
    blob = json.dumps(g.to_dict({"session_id": "t"}))
    data = json.loads(blob)
    assert data["meta"]["session_id"] == "t"
    assert len(data["nodes"]) == len(g.nodes)
    for n in data["nodes"]:
        assert n["type"] in bg.NODE_TYPES
    for e in data["edges"]:
        assert e["type"] in bg.EDGE_TYPES


def test_every_node_has_provenance_or_is_inferred(transcript, tmp_path):
    """The trust contract: observed nodes must be traceable."""
    g = build(transcript, tmp_path)
    for n in g.nodes.values():
        if not n.inferred:
            assert n.provenance, f"{n.id} has no provenance"
