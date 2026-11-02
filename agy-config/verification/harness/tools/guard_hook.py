#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: guard_hook.py — Cross-surface PreToolUse guard and PostToolUse audit
==============================================================================
Purpose:
    Minimal Antigravity lifecycle hook used by the verification matrix:
    PreToolUse denies any tool call whose arguments contain a blocked token
    (default "hookblock"), and PostToolUse appends an audit line, so the same
    hooks.json can prove whether a surface loads hooks at all.

Architecture / Context:
    Referenced from hooks.json written by cases.py:
      PreToolUse  -> python3 guard_hook.py pre  <audit_log> [token ...]
      PostToolUse -> python3 guard_hook.py post <audit_log>
    Input is the documented hook stdin JSON ({"toolCall": {"name", "args"}, ...});
    output is the documented decision JSON ({"decision": "deny", "reason": ...}).

Dependencies / Side Effects:
    Python 3.8+ standard library. Appends JSON lines to the audit log (the
    directory must be writable by the test user). Never blocks on errors:
    failures are logged to stderr and the hook returns "allow" so a broken
    harness can't be mistaken for an enforcing hook.
==============================================================================
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def _audit(log_path: Path, record: dict) -> None:
    """Append one JSON line to the audit log.

    Parameters:
        log_path (Path): Audit file.
        record (dict): Event to record.
    Return Value:
        None.
    Exceptions/Errors:
        None (errors go to stderr).
    """
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
    except OSError as exc:
        print(f"guard_hook: audit write failed: {exc}", file=sys.stderr)


def main(argv: list[str]) -> int:
    """Entry point for both hook phases.

    Parameters:
        argv (list[str]): [phase, audit_log, *blocked_tokens].
    Return Value:
        int: Always 0 (decisions are returned on stdout).
    Exceptions/Errors:
        None.
    """
    if len(argv) < 2 or argv[0] not in ("pre", "post"):
        print("usage: guard_hook.py pre|post <audit_log> [token ...]", file=sys.stderr)
        print(json.dumps({"decision": "allow"}))
        return 0
    phase, log_path, tokens = argv[0], Path(argv[1]), argv[2:] or ["hookblock"]
    try:
        # Read bytes: Windows would decode stdin with the ANSI code page otherwise.
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError as exc:
        print(f"guard_hook: bad stdin JSON: {exc}", file=sys.stderr)
        payload = {}
    call = payload.get("toolCall") or {}
    name = call.get("name", "")
    args_text = json.dumps(call.get("args", {}), sort_keys=True)
    record = {"ts": time.time(), "phase": phase, "tool": name, "args": args_text[:500],
              "conversationId": payload.get("conversationId", "")}

    if phase == "post":
        record["error"] = payload.get("error", "")
        _audit(log_path, record)
        print(json.dumps({}))
        return 0

    hit = next((t for t in tokens if t and t in args_text), None)
    record["decision"] = "deny" if hit else "allow"
    _audit(log_path, record)
    if hit:
        print(json.dumps({"decision": "deny",
                          "reason": f"agy-verify guard: token '{hit}' is blocked by policy"}))
    else:
        print(json.dumps({"decision": "allow"}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
