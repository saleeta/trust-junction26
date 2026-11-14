"""
Tests for trust.session_graph.deepcode_convert.

The converter's contract: a DETERMINISTIC re-encoding of a genuine harness log
into Claude Code transcript shapes. Nothing is inferred or fabricated, tool
names map to canonical casing, human answers to AskUserQuestion land in the
tool_result where the decision parser can read them, and the model's private
reasoning is never copied.
"""

from __future__ import annotations

import json

import build_graph as bg
import deepcode_convert as dc


def harness_record(role: str, *, rid: str, content: str = "",
                   message_params: dict | None = None, ts: str | None = None) -> dict:
    return {
        "id": rid, "role": role, "sessionId": "s", "content": content,
        "messageParams": message_params or {},
        "createTime": ts or "2026-11-14T10:00:00.000Z",
        "compacted": False, "visible": True,
    }


def tool_call(name: str, args: dict, cid: str) -> dict:
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


# ---------------------------------------------------------------------------
# tool names map to Claude Code casing (why_lines / build_graph are case-aware)
# ---------------------------------------------------------------------------

def test_lowercase_harness_tool_names_map_to_canonical_casing():
    records = [
        harness_record("user", rid="u1", content="go"),
        harness_record("assistant", rid="a1",
                       message_params={"tool_calls": [
                           tool_call("edit", {"file_path": "D:\\x\\f.cs",
                                              "old_string": "a", "new_string": "b"},
                                     "call_1"),
                           tool_call("read", {"file_path": "D:\\x\\f.cs"}, "call_2"),
                       ]}),
    ]
    out = dc.convert(records)
    asst = [r for r in out if r["type"] == "assistant"]
    blocks = asst[0]["message"]["content"]
    names = {b["name"] for b in blocks if b["type"] == "tool_use"}
    assert names == {"Edit", "Read"}


# ---------------------------------------------------------------------------
# AskUserQuestion answers: the harness delivers them as a later user message
# ---------------------------------------------------------------------------

def test_ask_answer_lands_in_tool_result_and_parses():
    q = "Which direction?"
    records = [
        harness_record("user", rid="u1", content="decide"),
        harness_record("assistant", rid="a1",
                       message_params={"tool_calls": [
                           tool_call("AskUserQuestion",
                                     {"questions": [{
                                         "question": q,
                                         "options": [{"label": "A"}, {"label": "B"}],
                                     }]}, "call_ask")]}),
        harness_record("tool", rid="t1",
                       content=json.dumps({"ok": True, "name": "AskUserQuestion",
                                           "output": "Waiting for user input."}),
                       message_params={"tool_call_id": "call_ask"}),
        harness_record("user", rid="u2",
                       content=f"Questions 1/1 answered\n - {q}\n   answer: A"),
    ]
    out = dc.convert(records)
    results = [r for r in out
               if any(b.get("type") == "tool_result" for b in r["message"]["content"])]
    assert results, "the tool result must exist"
    content = results[0]["message"]["content"][0]["content"]
    answers = bg.parse_answers(content)
    assert answers == {q: "A"}


def test_unanswered_question_stays_unanswered():
    records = [
        harness_record("user", rid="u1", content="decide"),
        harness_record("assistant", rid="a1",
                       message_params={"tool_calls": [
                           tool_call("AskUserQuestion",
                                     {"questions": [{"question": "Q?",
                                                     "options": [{"label": "A"}]}]},
                                     "call_ask")]}),
        harness_record("tool", rid="t1",
                       content=json.dumps({"ok": True, "name": "AskUserQuestion",
                                           "output": "Waiting for user input."}),
                       message_params={"tool_call_id": "call_ask"}),
        # the human typed something new instead of answering
        harness_record("user", rid="u2", content="actually, do the other thing"),
    ]
    out = dc.convert(records)
    results = [r for r in out
               if any(b.get("type") == "tool_result" for b in r["message"]["content"])]
    assert bg.parse_answers(results[0]["message"]["content"][0]["content"]) == {}


# ---------------------------------------------------------------------------
# honesty boundary: private reasoning is not copied
# ---------------------------------------------------------------------------

def test_reasoning_content_is_not_copied():
    records = [
        harness_record("user", rid="u1", content="go"),
        harness_record("assistant", rid="a1",
                       message_params={
                           "tool_calls": [tool_call("bash",
                                                    {"command": "pwd"}, "call_1")],
                           "reasoning_content": "secret private thinking",
                       }),
        harness_record("tool", rid="t1",
                       content=json.dumps({"ok": True, "name": "bash",
                                           "output": "/tmp"}),
                       message_params={"tool_call_id": "call_1"}),
    ]
    out = dc.convert(records)
    text = json.dumps(out)
    assert "secret private thinking" not in text


def test_tool_results_preserve_error_status():
    records = [
        harness_record("user", rid="u1", content="go"),
        harness_record("assistant", rid="a1",
                       message_params={"tool_calls": [
                           tool_call("bash", {"command": "false"}, "call_1")]}),
        harness_record("tool", rid="t1",
                       content=json.dumps({"ok": False, "name": "bash",
                                           "output": "boom"}),
                       message_params={"tool_call_id": "call_1"}),
    ]
    out = dc.convert(records)
    result = [r for r in out
              if any(b.get("type") == "tool_result" for b in r["message"]["content"])][0]
    block = result["message"]["content"][0]
    assert block["is_error"] is True
    assert "boom" in block["content"]
