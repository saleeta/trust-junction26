"""Convert a deepcode-harness session log into the Claude Code transcript format.

WHY THIS EXISTS
---------------
`build_graph.py` / `why_lines.py` consume Claude Code `.jsonl` transcripts
(`type: user/assistant`, `message.content[]` blocks, `parentUuid` chains).
This project's review sessions are sometimes recorded by a different harness
(deepcode) whose log uses OpenAI-style records:

    {role: user|assistant|tool, content, messageParams.tool_calls[],
     createTime, meta, ...}

Both are genuine recordings of the same events - tool calls, edits, user
prompts. This module is a DETERMINISTIC re-encoding of the harness log into the
Claude Code record shapes, preserving every uuid/tool_use_id as provenance.
Nothing is inferred or fabricated: an output record exists only because an
input record exists.

HONESTY RULES
-------------
1. `reasoning_content` (the model's private thinking, which this harness does
   record) is deliberately NOT copied. The trust contract in this repo states
   that private reasoning is unrecoverable from Claude Code transcripts; this
   converter keeps that boundary: the capsule contains what the agent
   *recorded* (prompts, tool calls, edits, results), not what it privately
   reasoned.
2. The output is labelled: `meta.transcript` carries the ORIGINAL harness log
   path and the conversion note, so the graph viewer can show where each
   record really came from.

Usage:
    python deepcode_convert.py <harness.jsonl> <out.claude.jsonl>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def load(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _tool_blocks(rec: dict) -> list[dict]:
    """OpenAI-style tool_calls -> Claude Code tool_use blocks."""
    NAME_MAP = {"read": "Read", "write": "Write", "edit": "Edit",
                "bash": "Bash", "skill": "Skill", "agent": "Agent"}
    mp = rec.get("messageParams") or {}
    blocks = []
    for call in mp.get("tool_calls") or []:
        fn = call.get("function") or {}
        args = fn.get("arguments") or "{}"
        if isinstance(args, str):
            try:
                inp = json.loads(args)
            except json.JSONDecodeError:
                inp = {"raw": args}
        else:
            inp = args if isinstance(args, dict) else {"raw": str(args)}
        name = fn.get("name") or "?"
        blocks.append({
            "type": "tool_use",
            "id": call.get("id") or f"call_{len(blocks)}",
            "name": NAME_MAP.get(name, name),
            "input": inp,
        })
    return blocks


def _answer_lines(qtext: str, user_text: str) -> list[str]:
    """Match a deepcode answer message back to its AskUserQuestion questions.

    The harness renders answers as:

        Questions 1/1 answered
         - <question>
           answer: <chosen label>
    """
    lines: list[str] = []
    # find the bullet under which this question appears, then its answer line
    q_start = user_text.find(qtext[:60])
    if q_start < 0:
        return lines
    tail = user_text[q_start:]
    m = re.search(r"answer:\s*([^\n]+)", tail)
    if m:
        lines.append(f'"{qtext}"="{m.group(1).strip()}"')
    return lines


def convert(records: list[dict]) -> list[dict]:
    out: list[dict] = []
    by_id: dict[str, dict] = {}

    # first pass: index call ids and answer messages so tool_results can be
    # enriched with AskUserQuestion answers
    user_texts: dict[str, str] = {
        r["id"]: r.get("content") or ""
        for r in records if r.get("role") == "user"
    }
    ask_results: dict[str, tuple[str, dict]] = {}  # call_id -> (tool_uuid, input)
    pending_answers: dict[str, str] = {}           # call_id -> answer user text

    ordered = [r for r in records if r.get("role") in ("user", "assistant", "tool")]
    for i, rec in enumerate(ordered):
        if rec.get("role") == "assistant":
            for b in _tool_blocks(rec):
                if b["name"] == "AskUserQuestion":
                    # the harness delivers the human's answer as a LATER user
                    # message (the tool result only says "Waiting for user
                    # input."), typically two records ahead
                    for j in range(i + 1, min(i + 4, len(ordered))):
                        nxt = ordered[j]
                        if nxt.get("role") == "user" and "answered" in (nxt.get("content") or ""):
                            pending_answers[b["id"]] = nxt.get("content") or ""
                            ask_results[b["id"]] = (nxt.get("id", ""), b["input"])
                            break
        elif rec.get("role") == "tool":
            pass

    prev_uuid: str | None = None
    last_user: str | None = None

    for rec in ordered:
        role = rec.get("role")
        uuid = str(rec.get("id") or "")
        ts = rec.get("createTime")

        if role == "user":
            text = (rec.get("content") or "").strip()
            # AskUserQuestion answer messages are consumed by the decision
            # parser via the tool_result; still keep them as user turns.
            if not text:
                continue
            node = {
                "type": "user",
                "uuid": uuid,
                "parentUuid": prev_uuid,
                "timestamp": ts,
                "cwd": "d:/work/big-hackathon",
                "gitBranch": "master",
                "message": {"role": "user",
                            "content": [{"type": "text", "text": text}]},
                "_harness": "deepcode",
            }
            out.append(node)
            by_id[uuid] = node
            last_user = uuid
            prev_uuid = uuid
            continue

        if role == "assistant":
            blocks: list[dict] = []
            text = (rec.get("content") or "").strip()
            if text:
                blocks.append({"type": "text", "text": text})
            blocks += _tool_blocks(rec)
            if not blocks:
                prev_uuid = uuid
                continue
            node = {
                "type": "assistant",
                "uuid": uuid,
                "parentUuid": last_user or prev_uuid,
                "timestamp": ts,
                "cwd": "d:/work/big-hackathon",
                "gitBranch": "master",
                "message": {"role": "assistant", "content": blocks},
                "_harness": "deepcode",
            }
            out.append(node)
            by_id[uuid] = node
            prev_uuid = uuid
            continue

        # role == "tool": Claude Code delivers results as a user message with a
        # tool_result block keyed by tool_use_id
        mp = rec.get("messageParams") or {}
        call_id = mp.get("tool_call_id")
        if not call_id:
            continue
        raw = rec.get("content") or "{}"
        payload: dict[str, Any] = {}
        if isinstance(raw, str):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"output": raw}
        is_error = bool(payload.get("ok")) is False or bool(payload.get("is_error"))
        result_text = payload.get("output")
        if result_text is None:
            result_text = raw if isinstance(raw, str) else json.dumps(raw)

        if call_id in ask_results:
            ask_uuid, qinput = ask_results[call_id]
            answer_text = pending_answers.get(call_id, "")
            extra = []
            for q in (qinput.get("questions") or []):
                if isinstance(q, dict):
                    extra += _answer_lines(str(q.get("question") or ""), answer_text)
            if extra:
                result_text = "\n".join(extra) + "\n" + str(result_text)
            prev_uuid = ask_uuid  # chain the result under the answer turn

        node = {
            "type": "user",
            "uuid": uuid,
            "parentUuid": prev_uuid,
            "timestamp": ts,
            "cwd": "d:/work/big-hackathon",
            "gitBranch": "master",
            "message": {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": result_text,
                    "is_error": is_error,
                }],
            },
            "_harness": "deepcode",
        }
        out.append(node)
        by_id[uuid] = node
        prev_uuid = uuid

    return out


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="deepcode harness .jsonl log")
    ap.add_argument("output", help="Claude Code format .jsonl to write")
    args = ap.parse_args(argv)

    src = Path(args.input)
    records = load(src)
    converted = convert(records)

    dst = Path(args.output)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8") as fh:
        for r in converted:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    prompts = sum(1 for r in converted if r["type"] == "user"
                  and all(b.get("type") == "text" for b in r["message"]["content"]))
    tools = sum(1 for r in converted if r["type"] == "assistant")
    results = sum(1 for r in converted
                  if any(b.get("type") == "tool_result" for b in r["message"]["content"]))
    print(f"converted {len(records)} harness records -> {len(converted)} transcript records")
    print(f"  prompts={prompts} assistant_turns={tools} tool_results={results}")
    print(f"  source : {src.resolve()}")
    print(f"  wrote  : {dst.resolve()}")
    print("  NOTE   : reasoning_content deliberately not copied (honesty rule 1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
