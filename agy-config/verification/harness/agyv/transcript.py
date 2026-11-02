#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: transcript.py — Parser for Antigravity conversation transcripts
==============================================================================
Purpose:
    Finds the newest conversation transcript an Antigravity surface wrote
    under the round HOME (<home>/.gemini/<app-data>/brain/<id>/.system_generated/
    logs/transcript_full.jsonl) and turns it into a flat list of tool steps
    with their status, error text and output, so oracles can tell a
    permission denial ("Permission denied for read_url(...)") from a tool
    that ran or a model that answered from memory.

Architecture / Context:
    Used by the surface drivers (cli, hub, acp) after a round. The CLI, the
    App, VS Code and the web UI share the language server that writes these
    files; the folder name differs per surface (antigravity-cli, antigravity).

Dependencies / Side Effects:
    Python 3.10+ standard library. Read-only.
==============================================================================
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

LOG = logging.getLogger("agyv.transcript")

# Substrings that mark a tool result as a policy denial rather than a tool failure.
DENIAL_MARKERS = ("permission denied", "permission check failed", "denied by", "blocked by",
                  "is blocked by policy", "not allowed", "hook denied", "pretooluse",
                  "user rejected", "rejected by user", "declined")


def find_latest(home: Path) -> Optional[Path]:
    """Return the most recently modified transcript under any app-data folder.

    Parameters:
        home (Path): Round HOME.
    Return Value:
        Optional[Path]: transcript_full.jsonl (or transcript.jsonl) path, or None.
    Exceptions/Errors:
        None.
    """
    candidates = list(home.glob(".gemini/*/brain/*/.system_generated/logs/transcript_full.jsonl"))
    if not candidates:
        candidates = list(home.glob(".gemini/*/brain/*/.system_generated/logs/transcript.jsonl"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _decode_args(args: dict[str, Any]) -> dict[str, Any]:
    """Transcript args are JSON-encoded strings; decode each value when possible."""
    out: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if isinstance(value, str):
            try:
                out[key] = json.loads(value)
                continue
            except json.JSONDecodeError:
                pass
        out[key] = value
    return out


def parse(path: Path) -> tuple[list[dict[str, Any]], str]:
    """Parse a transcript into tool steps and the final agent text.

    Parameters:
        path (Path): Transcript file.
    Return Value:
        tuple: (steps, final_text). Each step: {tool, args, status, error, output, denied}.
    Exceptions/Errors:
        None (unreadable lines are skipped).
    """
    steps: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    final_text = ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        LOG.warning("cannot read transcript %s: %s", path, exc)
        return steps, final_text
    items: list[dict[str, Any]] = []
    for line in lines:
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    # Steps can be appended out of order (the ACP server writes a tool's ERROR_MESSAGE before the
    # PLANNER_RESPONSE that issued the call), so pair calls and results in step_index order.
    items.sort(key=lambda it: it.get("step_index", 0) if isinstance(it.get("step_index"), int) else 0)
    for item in items:
        kind = item.get("type")
        if kind == "PLANNER_RESPONSE":
            for call in item.get("tool_calls") or []:
                pending.append({"tool": call.get("name", ""), "args": _decode_args(call.get("args", {}))})
            if not item.get("tool_calls") and item.get("content"):
                final_text = item.get("content", "")
        elif kind not in ("USER_INPUT",) and item.get("source") in ("MODEL", "SYSTEM"):
            step = pending.pop(0) if pending else {"tool": item.get("type", "?"), "args": {}}
            error = item.get("error", "") or ""
            content = item.get("content", "") or ""
            step.update({"status": item.get("status", ""), "error": error[:1500],
                         "output": content[:3000],
                         "denied": item.get("status") == "ERROR"
                         and any(m in (error + content).lower() for m in DENIAL_MARKERS)})
            steps.append(step)
    # Calls that never got a result still count as attempts (e.g. the turn was cut short).
    for call in pending:
        steps.append({**call, "status": "PENDING", "error": "", "output": "", "denied": False})
    return steps, final_text
