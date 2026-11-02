#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: probe_mcp_server.py — Dependency-free stdio MCP server for tests
==============================================================================
Purpose:
    Exposes two harmless MCP tools, `probe_echo` and `probe_extra`, over the
    MCP stdio transport and logs every call, so the matrix can prove whether
    a surface loaded an MCP server, honored enabledTools/disabledTools, and
    applied mcp(server/tool) permission rules.

Architecture / Context:
    Registered as server "agyprobe" in the mcp_config.json that cases.py
    writes: {"command": "python3", "args": [this file, <call_log>]}.
    Implements only the methods clients use: initialize, tools/list,
    tools/call, ping; notifications are ignored.

Dependencies / Side Effects:
    Python 3.8+ standard library. Appends one line per tool call to the call
    log given as argv[1]; reads newline-delimited JSON-RPC on stdin.
==============================================================================
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

TOOLS = [
    {"name": "probe_echo", "description": "Echo back the given text (verification probe).",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}}},
    # Named neutrally on purpose: a tool called "secret" trips Model Armor at the gateway.
    {"name": "probe_extra", "description": "Return a fixed probe string (verification probe).",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _reply(msg_id, result=None, error=None) -> None:
    """Write one JSON-RPC response line to stdout.

    Parameters:
        msg_id: Request id.
        result: Result object (when no error).
        error: Error object.
    Return Value:
        None.
    Exceptions/Errors:
        None.
    """
    body = {"jsonrpc": "2.0", "id": msg_id}
    body["error" if error is not None else "result"] = error if error is not None else result
    sys.stdout.buffer.write((json.dumps(body) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def main(argv: list[str]) -> int:
    """Serve MCP over stdio until EOF.

    Parameters:
        argv (list[str]): [call_log_path].
    Return Value:
        int: 0 at EOF.
    Exceptions/Errors:
        None (malformed lines are skipped).
    """
    log_path = Path(argv[0]) if argv else Path("/tmp/agyv_mcp_calls.log")
    # Byte-level reads keep the JSON-RPC stream UTF-8 on Windows too.
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", "replace")
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method, msg_id = msg.get("method"), msg.get("id")
        if msg_id is None:
            continue  # notification
        if method == "initialize":
            version = msg.get("params", {}).get("protocolVersion", "2025-06-18")
            _reply(msg_id, {"protocolVersion": version, "capabilities": {"tools": {}},
                            "serverInfo": {"name": "agyprobe", "version": "1.0.0"}})
        elif method == "tools/list":
            _reply(msg_id, {"tools": TOOLS})
        elif method == "tools/call":
            params = msg.get("params", {})
            name = params.get("name", "")
            try:
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(f"{time.time():.3f} {name} {json.dumps(params.get('arguments', {}))}\n")
            except OSError as exc:
                print(f"probe_mcp_server: log write failed: {exc}", file=sys.stderr)
            text = f"probe_echo:{params.get('arguments', {}).get('text', '')}" if name == "probe_echo" \
                else "probe_extra:AGYV-MCP-EXTRA-OK"
            _reply(msg_id, {"content": [{"type": "text", "text": text}], "isError": False})
        elif method == "ping":
            _reply(msg_id, {})
        else:
            _reply(msg_id, error={"code": -32601, "message": f"method not found: {method}"})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
