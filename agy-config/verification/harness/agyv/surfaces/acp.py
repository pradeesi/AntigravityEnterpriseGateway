#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: acp.py — JetBrains/Zed surface driver (Agent Client Protocol)
==============================================================================
Purpose:
    Drives the Antigravity ACP server (`agy_acp_server`, the binary JetBrains
    and Zed install from the ACP agent registry) exactly like an IDE does:
    JSON-RPC 2.0 over stdio with initialize → session/new → session/prompt,
    answering session/request_permission and serving the fs/* and terminal/*
    client methods, then normalizes the session into a SurfaceResult.

Architecture / Context:
    Surface driver used by runner.py for surface "acp". The client advertises
    the same capabilities Zed does (fs read/write + terminal), so file and
    command actions flow through the client; those requests are executed as
    the non-root test user, as an IDE running in the user's session would.
    Gateway auth uses the documented ACP setup: AGY_LLM_GATEWAY_* in the
    agent env plus ~/.gemini/antigravity-acp/settings.json {"auth": {"type": "gateway"}}.

Dependencies / Side Effects:
    Python 3.10+ standard library. Spawns the ACP server as the test user,
    may run commands/edit files on its behalf, and writes acp_transcript.jsonl.
==============================================================================
"""

from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from agyv import transcript as agy_transcript
from agyv.env import IS_WINDOWS, TEST_USER, GatewayConfig, redact
from agyv.probes import RoundPaths, SurfaceResult
from agyv.surfaces.cli import as_user, user_env

LOG = logging.getLogger("agyv.surfaces.acp")

ACP_BIN = (r"C:\ProgramData\agy-verify\acp\agy_acp_server.exe" if IS_WINDOWS
           else "/opt/agy-acp-server/agy_acp_server.par")
ACP_ARGS: list[str] = [] if IS_WINDOWS else ["--uid="]

# ACP tool kinds mapped to the canonical tool names the probes understand.
KIND_TO_TOOL = {"execute": "run_command", "read": "view_file", "edit": "write_to_file",
                "fetch": "read_url_content", "delete": "delete_file", "move": "move_file",
                "search": "grep_search"}


class _Rpc:
    """Line-delimited JSON-RPC peer over a subprocess's stdio.

    Attributes:
        proc (subprocess.Popen): ACP server process.
        log (list[dict]): Every message in either direction (for evidence).
    """

    def __init__(self, proc: subprocess.Popen) -> None:
        """Initialize the JSON-RPC stdio peer and start its background reader thread.

        Parameters:
            proc (subprocess.Popen): Running ACP server subprocess with piped stdin/stdout.
        Return Value:
            None.
        Exceptions/Errors:
            RuntimeError: If the reader thread cannot start.
        """
        self.proc = proc
        self.log: list[dict] = []
        self.inbox: "queue.Queue[dict]" = queue.Queue()
        self._next_id = 0
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        """Push every JSON message from the server's stdout into the inbox."""
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                self.log.append({"dir": "in-raw", "text": raw[:500]})
                continue
            self.log.append({"dir": "in", "ts": time.time(), "msg": msg})
            self.inbox.put(msg)

    def send(self, msg: dict) -> None:
        """Write one message to the server."""
        assert self.proc.stdin is not None
        self.log.append({"dir": "out", "ts": time.time(), "msg": msg})
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: dict) -> int:
        """Send a request and return its id (response handled by the caller's loop)."""
        self._next_id += 1
        self.send({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params})
        return self._next_id

    def respond(self, msg_id: Any, result: Any = None, error: dict | None = None) -> None:
        """Answer a server→client request."""
        body: dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id}
        if error is not None:
            body["error"] = error
        else:
            body["result"] = result
        self.send(body)


class _Terminals:
    """Executes terminal/* requests as the test user, like an IDE terminal would."""

    def __init__(self, env: dict[str, str]) -> None:
        """Create a terminal execution manager for one ACP round.

        Parameters:
            env (dict[str, str]): Base environment passed to spawned shell commands.
        Return Value:
            None.
        Exceptions/Errors:
            None.
        """
        self.env = env
        self.items: dict[str, dict[str, Any]] = {}

    def create(self, params: dict) -> dict:
        """terminal/create: start the command and return its terminal id."""
        command = params.get("command", "")
        args = params.get("args") or []
        cwd = params.get("cwd") or None
        env = dict(self.env)
        for item in params.get("env") or []:
            env[item.get("name", "")] = item.get("value", "")
        argv = [command, *args] if args else (["cmd", "/c", command] if IS_WINDOWS else ["sh", "-c", command])
        proc = subprocess.Popen(as_user(argv, env), cwd=cwd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        tid = f"term-{uuid.uuid4().hex[:8]}"
        self.items[tid] = {"proc": proc, "output": "", "argv": argv}
        return {"terminalId": tid}

    def _drain(self, tid: str, timeout: float | None) -> dict[str, Any]:
        """Collect available stdout/stderr output from a managed terminal up to `timeout` seconds.

        Parameters:
            tid (str): Terminal identifier returned by `create()`.
            timeout (float | None): Maximum seconds to wait for exit (`None` blocks indefinitely).
        Return Value:
            dict[str, Any]: Terminal state entry containing `proc`, `output`, and `argv`.
        Exceptions/Errors:
            KeyError: Unknown terminal identifier.
        """
        item = self.items[tid]
        try:
            out, _ = item["proc"].communicate(timeout=timeout)
            item["output"] += out or ""
        except subprocess.TimeoutExpired:
            pass
        return item

    def output(self, params: dict) -> dict:
        """terminal/output: current output and exit status if finished."""
        item = self._drain(params["terminalId"], 0.5)
        code = item["proc"].poll()
        result: dict[str, Any] = {"output": item["output"][-20000:], "truncated": False}
        if code is not None:
            result["exitStatus"] = {"exitCode": code, "signal": None}
        return result

    def wait(self, params: dict) -> dict:
        """terminal/wait_for_exit: block until the command exits."""
        item = self._drain(params["terminalId"], 300)
        return {"exitCode": item["proc"].poll(), "signal": None}

    def kill(self, params: dict) -> dict:
        """terminal/kill and terminal/release."""
        item = self.items.get(params.get("terminalId", ""))
        if item and item["proc"].poll() is None:
            item["proc"].kill()
        return {}


def run(prompt: str, rp: RoundPaths, gateway: GatewayConfig, skip_permissions: bool,
        extra_flags: list[str] | None = None, timeout_s: int = 300) -> SurfaceResult:
    """Run one prompt through the ACP server and normalize the session.

    Parameters:
        prompt (str): Probe prompt.
        rp (RoundPaths): Round directories.
        gateway (GatewayConfig): Gateway URL/key passed in the agent env (like acp.json).
        skip_permissions (bool): True → pick an allow option for every permission
            request; False → pick a reject option.
        extra_flags (list[str] | None): Unused (kept for the common driver signature).
        timeout_s (int): Overall timeout for the turn.
    Return Value:
        SurfaceResult: Normalized evidence (acp_transcript.jsonl in rp.evidence).
    Exceptions/Errors:
        None (failures are returned in SurfaceResult.error).
    """
    res = SurfaceResult()
    # Documented ACP gateway setup: env block + antigravity-acp/settings.json auth.type=gateway.
    acp_settings = rp.home / ".gemini" / "antigravity-acp" / "settings.json"
    if not acp_settings.exists():
        acp_settings.parent.mkdir(parents=True, exist_ok=True)
        acp_settings.write_text(json.dumps({"auth": {"type": "gateway"}}), encoding="utf-8")
        if not IS_WINDOWS:
            for path in (acp_settings, acp_settings.parent, acp_settings.parent.parent):
                os.chown(path, *_uid_gid())
    env = user_env(rp.home, {"AGY_LLM_GATEWAY_URL": gateway.url,
                             "AGY_LLM_GATEWAY_API_KEY": gateway.api_key,
                             "AGY_LLM_GATEWAY_WIRE_PROTOCOL": "genai",
                             "AGY_LLM_GATEWAY_MODELS": ",".join(gateway.models)})
    # Keep the handle so it can be closed: Windows refuses to delete a round folder with open files.
    stderr_handle = open(rp.evidence / "acp_stderr.txt", "w", encoding="utf-8")  # noqa: SIM115
    proc = subprocess.Popen(as_user([ACP_BIN, *ACP_ARGS], env), cwd=rp.workspace, env=env,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr_handle,
                            text=True, encoding="utf-8", errors="replace", bufsize=1)
    rpc, terms = _Rpc(proc), _Terminals(env)
    message_chunks: list[str] = []
    pending: dict[int, str] = {}
    session_id = ""
    deadline = time.time() + timeout_s
    state = "init"
    try:
        pending[rpc.request("initialize", {
            "protocolVersion": 1,
            "clientCapabilities": {"fs": {"readTextFile": True, "writeTextFile": True}, "terminal": True},
            "clientInfo": {"name": "agyv-acp-client", "version": "1.0.0"}})] = "initialize"
        while time.time() < deadline and state != "done":
            try:
                msg = rpc.inbox.get(timeout=1.0)
            except queue.Empty:
                if proc.poll() is not None:
                    res.error = f"ACP server exited with code {proc.returncode}"
                    break
                continue
            if "id" in msg and ("result" in msg or "error" in msg) and msg.get("id") in pending:
                what = pending.pop(msg["id"])
                if "error" in msg:
                    res.error = f"{what} failed: {json.dumps(msg['error'])[:400]}"
                    break
                result = msg.get("result") or {}
                if what == "initialize":
                    methods = [m.get("id") for m in result.get("authMethods", [])]
                    if "gateway" in methods:
                        pending[rpc.request("authenticate", {"methodId": "gateway"})] = "authenticate"
                    else:
                        pending[rpc.request("session/new", {"cwd": str(rp.workspace), "mcpServers": []})] = "session/new"
                elif what == "authenticate":
                    pending[rpc.request("session/new", {"cwd": str(rp.workspace), "mcpServers": []})] = "session/new"
                elif what == "session/new":
                    session_id = result.get("sessionId", "")
                    pending[rpc.request("session/prompt", {
                        "sessionId": session_id, "prompt": [{"type": "text", "text": prompt}]})] = "session/prompt"
                elif what == "session/prompt":
                    state = "done"
                continue
            method = msg.get("method")
            params = msg.get("params") or {}
            if method == "session/update":
                update = params.get("update", {})
                kind = update.get("sessionUpdate")
                if kind == "agent_message_chunk":
                    content = update.get("content", {})
                    if content.get("type") == "text":
                        message_chunks.append(content.get("text", ""))
                elif kind == "tool_call":
                    res.tool_calls.append({"name": KIND_TO_TOOL.get(update.get("kind", ""), update.get("kind", "")),
                                           "title": update.get("title", ""), "params": update.get("rawInput", {})})
            elif method == "session/request_permission":
                options = params.get("options", [])
                want = ("allow_once", "allow_always") if skip_permissions else ("reject_once", "reject_always")
                choice = next((o for o in options if o.get("kind") in want), None)
                res.prompts.append({"toolCall": params.get("toolCall", {}),
                                    "options": [o.get("kind") for o in options],
                                    "answered": choice.get("kind") if choice else "cancelled"})
                if choice:
                    rpc.respond(msg["id"], {"outcome": {"outcome": "selected", "optionId": choice["optionId"]}})
                else:
                    rpc.respond(msg["id"], {"outcome": {"outcome": "cancelled"}})
            elif method == "fs/read_text_file":
                path = Path(params.get("path", ""))
                try:
                    rpc.respond(msg["id"], {"content": path.read_text(encoding="utf-8")})
                except OSError as exc:
                    rpc.respond(msg["id"], error={"code": -32000, "message": str(exc)})
            elif method == "fs/write_text_file":
                path = Path(params.get("path", ""))
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(params.get("content", ""), encoding="utf-8")
                    if not IS_WINDOWS:
                        os.chown(path, *_uid_gid())
                    rpc.respond(msg["id"], None)
                except OSError as exc:
                    rpc.respond(msg["id"], error={"code": -32000, "message": str(exc)})
            elif method == "terminal/create":
                rpc.respond(msg["id"], terms.create(params))
            elif method == "terminal/output":
                rpc.respond(msg["id"], terms.output(params))
            elif method == "terminal/wait_for_exit":
                rpc.respond(msg["id"], terms.wait(params))
            elif method in ("terminal/kill", "terminal/release"):
                rpc.respond(msg["id"], terms.kill(params))
            elif "id" in msg and method:
                rpc.respond(msg["id"], error={"code": -32601, "message": f"client method not supported: {method}"})
        else:
            if state != "done" and not res.error:
                res.error = f"ACP turn did not finish within {timeout_s}s"
    finally:
        res.response = "".join(message_chunks)
        res.exit_code = proc.poll()
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        if IS_WINDOWS:
            # terminate() stops only agy_acp_server.exe; its localharness child would keep files open.
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
        stderr_handle.close()
        transcript = rp.evidence / "acp_transcript.jsonl"
        transcript.write_text("\n".join(redact(json.dumps(m), gateway) for m in rpc.log), encoding="utf-8")
        res.raw_paths += [str(transcript), str(rp.evidence / "acp_stderr.txt")]
        # The ACP server keeps its own transcript (~/.gemini/antigravity-acp/brain/...). It records
        # server-side denials (e.g. the built-in workspace boundary check) that never reach the
        # client as tool calls, so it is the oracle for steps just like on the CLI.
        server_transcript = agy_transcript.find_latest(rp.home)
        if server_transcript:
            res.steps, final_text = agy_transcript.parse(server_transcript)
            res.response = res.response or final_text
            copy = rp.evidence / "transcript.jsonl"
            copy.write_text(redact(server_transcript.read_text(encoding="utf-8"), gateway), encoding="utf-8")
            res.raw_paths.append(str(copy))
    return res


def _uid_gid() -> tuple[int, int]:
    """Return the test user's uid/gid (Linux only)."""
    import pwd  # noqa: PLC0415 — POSIX-only module
    entry = pwd.getpwnam(TEST_USER)
    return entry.pw_uid, entry.pw_gid
