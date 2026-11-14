"""
Tests for trust.session_graph.why_lines.

The integrity properties matter more than the happy path. A per-line provenance
tool that silently mis-attributes is worse than no tool, so most of these
assert that it refuses to answer when it cannot.
"""

from __future__ import annotations

import pytest

import why_lines as wl


def ops_for(transcript, tmp_path, name="s.jsonl"):
    path = transcript.save(tmp_path / name)
    records = wl.load_records(path)
    return wl.collect_ops(records)[0], records


# ---------------------------------------------------------------------------
# attribution across a Write then Edits
# ---------------------------------------------------------------------------

@pytest.fixture
def edited_session(transcript, tmp_path):
    t = transcript()
    t.prompt("write a module")
    t.assistant_text("Creating the module.")
    w = t.tool_use("Write", {"file_path": "D:\\proj\\m.py",
                             "content": "a = 1\nb = 2\nc = 3\n"})
    t.tool_result(w, "ok")
    t.assistant_text("b was wrong, fixing it.")
    e = t.tool_use("Edit", {"file_path": "D:\\proj\\m.py",
                            "old_string": "b = 2", "new_string": "b = 22"})
    t.tool_result(e, "ok")
    ops, records = ops_for(t, tmp_path)
    return ops


def test_each_line_attributed_to_the_op_that_wrote_it(edited_session):
    attrs, warnings, content = wl.replay(edited_session, "m.py")

    assert content == "a = 1\nb = 22\nc = 3\n"
    assert warnings == []
    assert attrs[0].op.kind == "Write", "untouched line keeps the Write"
    assert attrs[1].op.kind == "Edit", "changed line moves to the Edit"
    assert attrs[2].op.kind == "Write"


def test_stated_reason_follows_the_right_op(edited_session):
    attrs, _, _ = wl.replay(edited_session, "m.py")
    assert "b was wrong" in attrs[1].op.narration
    assert "Creating the module" in attrs[0].op.narration


def test_trigger_links_back_to_the_human_prompt(edited_session):
    attrs, _, _ = wl.replay(edited_session, "m.py")
    assert "write a module" in attrs[1].op.trigger["prompt_text"]


# ---------------------------------------------------------------------------
# narration scope - must not over-attribute
# ---------------------------------------------------------------------------

def test_batch_narration_is_flagged(transcript, tmp_path):
    """One narration covering several edits is NOT a per-line reason."""
    t = transcript()
    t.prompt("fix both")
    t.assistant_text("Applying two unrelated fixes.")
    a = t.tool_use("Write", {"file_path": "D:\\p\\x.py", "content": "p\nq\n"})
    t.tool_result(a, "ok")
    b = t.tool_use("Edit", {"file_path": "D:\\p\\x.py",
                            "old_string": "p", "new_string": "P"})
    t.tool_result(b, "ok")
    c = t.tool_use("Edit", {"file_path": "D:\\p\\x.py",
                            "old_string": "q", "new_string": "Q"})
    t.tool_result(c, "ok")
    ops, _ = ops_for(t, tmp_path)

    attrs, _, _ = wl.replay(ops, "x.py")
    assert all(a.op.narration_shared_with == 3 for a in attrs), \
        "all three ops share one narration and must say so"


def test_single_narration_not_flagged_as_batch(edited_session):
    attrs, _, _ = wl.replay(edited_session, "m.py")
    assert attrs[1].op.narration_shared_with == 1


# ---------------------------------------------------------------------------
# seeded replay: files the session edited but did not create
# ---------------------------------------------------------------------------

def test_replay_with_git_seed_attributes_only_session_edits(transcript, tmp_path):
    """Pre-existing lines come from the seed and belong to no op; the edited
    line belongs to the Edit. Without the seed the same ops fail to replay."""
    t = transcript()
    t.prompt("fix a pre-existing file")
    e = t.tool_use("Edit", {"file_path": "D:\\p\\z.py",
                             "old_string": "x = 1", "new_string": "x = 11"})
    t.tool_result(e, "ok")
    ops, _ = ops_for(t, tmp_path)

    # no seed: the edit cannot apply to empty content
    attrs, warnings, _ = wl.replay(ops, "z.py")
    assert warnings and any("not found" in w for w in warnings)

    # with the pre-edit content from git, replay succeeds and is honest:
    # untouched lines are unattributed (L0 territory), the changed line is the Edit's
    seed = "x = 1\ny = 2\n"
    attrs, warnings, content = wl.replay(ops, "z.py", seed=seed)
    assert warnings == []
    assert content == "x = 11\ny = 2\n"
    assert attrs[0].op is not None and attrs[0].op.kind == "Edit"
    assert attrs[1].op is None, "a line the session did not write has no op"


def test_replay_seed_survives_multiple_edits(transcript, tmp_path):
    t = transcript()
    t.prompt("two edits on a pre-existing file")
    a = t.tool_use("Edit", {"file_path": "D:\\p\\w.py",
                             "old_string": "a", "new_string": "A"})
    t.tool_result(a, "ok")
    b = t.tool_use("Edit", {"file_path": "D:\\p\\w.py",
                             "old_string": "c", "new_string": "C"})
    t.tool_result(b, "ok")
    ops, _ = ops_for(t, tmp_path)

    attrs, warnings, content = wl.replay(ops, "w.py", seed="a\nb\nc\n")
    assert warnings == []
    assert content == "A\nb\nC\n"
    assert attrs[0].op is not None and attrs[2].op is not None
    assert attrs[1].op is None


# ---------------------------------------------------------------------------
# failure handling - must warn, never guess
# ---------------------------------------------------------------------------

def test_missing_old_string_warns_and_does_not_corrupt(transcript, tmp_path):
    t = transcript()
    t.prompt("edit")
    w = t.tool_use("Write", {"file_path": "D:\\p\\y.py", "content": "keep\n"})
    t.tool_result(w, "ok")
    e = t.tool_use("Edit", {"file_path": "D:\\p\\y.py",
                            "old_string": "absent", "new_string": "new"})
    t.tool_result(e, "ok")
    ops, _ = ops_for(t, tmp_path)

    attrs, warnings, content = wl.replay(ops, "y.py")
    assert content == "keep\n", "content must be unchanged"
    assert any("not found" in w for w in warnings)


def test_failed_tool_call_is_skipped(transcript, tmp_path):
    t = transcript()
    t.prompt("edit")
    w = t.tool_use("Write", {"file_path": "D:\\p\\z.py", "content": "one\n"})
    t.tool_result(w, "ok")
    e = t.tool_use("Edit", {"file_path": "D:\\p\\z.py",
                            "old_string": "one", "new_string": "two"})
    t.tool_result(e, "Error: permission denied", is_error=True)
    ops, _ = ops_for(t, tmp_path)

    attrs, warnings, content = wl.replay(ops, "z.py")
    assert content == "one\n", "a failed edit must not be replayed"
    assert any("failed" in w for w in warnings)


def test_non_unique_old_string_is_reported(transcript, tmp_path):
    t = transcript()
    t.prompt("edit")
    w = t.tool_use("Write", {"file_path": "D:\\p\\d.py", "content": "x\nx\n"})
    t.tool_result(w, "ok")
    e = t.tool_use("Edit", {"file_path": "D:\\p\\d.py",
                            "old_string": "x", "new_string": "y"})
    t.tool_result(e, "ok")
    ops, _ = ops_for(t, tmp_path)

    attrs, warnings, content = wl.replay(ops, "d.py")
    assert any("not unique" in w for w in warnings)


def test_untracked_file_returns_no_attribution(edited_session):
    attrs, warnings, _ = wl.replay(edited_session, "never_touched.py")
    assert attrs == []
    assert any("no tracked edit operations" in w for w in warnings)


def test_replace_all_is_honoured(transcript, tmp_path):
    t = transcript()
    t.prompt("edit")
    w = t.tool_use("Write", {"file_path": "D:\\p\\r.py", "content": "x\nx\n"})
    t.tool_result(w, "ok")
    e = t.tool_use("Edit", {"file_path": "D:\\p\\r.py", "old_string": "x",
                            "new_string": "y", "replace_all": True})
    t.tool_result(e, "ok")
    ops, _ = ops_for(t, tmp_path)

    _, warnings, content = wl.replay(ops, "r.py")
    assert content == "y\ny\n"
    assert not any("not unique" in w for w in warnings)


# ---------------------------------------------------------------------------
# the L4 honesty claim
# ---------------------------------------------------------------------------

def test_thinking_blocks_are_empty_in_the_transcript(transcript, tmp_path):
    """The basis for refusing to claim L4. If this ever fails, the README and
    DEMO.md claims about private reasoning must be revisited."""
    t = transcript()
    t.prompt("x")
    t.assistant_text("some narration")
    path = t.save(tmp_path / "think.jsonl")
    recs = wl.load_records(path)

    thinking = [b for r in recs for b in wl.content_blocks(r)
                if b.get("type") == "thinking"]
    assert thinking, "fixture should contain thinking blocks"
    assert all(b.get("thinking") == "" for b in thinking)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n,spec,expected", [
    (5, "1-10", True), (1, "1-10", True), (10, "1-10", True),
    (11, "1-10", False), (0, "1-10", False), (5, "bad", False),
])
def test_in_range(n, spec, expected):
    assert wl.in_range(n, spec) is expected


def test_apply_op_write_replaces_whole_file():
    op = wl.Op(seq=0, kind="Write", path="p", uuid="u", tool_use_id="t",
               ts=None, content="fresh\n")
    assert wl.apply_op("old\n", op) == ("fresh\n", None)
