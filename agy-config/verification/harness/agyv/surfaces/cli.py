#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: cli.py — Antigravity CLI (`agy -p`) surface driver
==============================================================================
Purpose:
    Runs one probe prompt through the Antigravity CLI in headless print mode
    with `--output-format stream-json`, as the non-root test user with the
    round HOME, and normalizes the event stream into a SurfaceResult.

Architecture / Context:
    One of the surface drivers used by runner.py. Print mode can't show
    permission prompts: an action that needs one is auto-denied and listed in
    the final `result.denied_actions`. Deny-rule tests therefore pass
    `--dangerously-skip-permissions` (deny rules still apply in every mode);
    ask-rule tests run without it so an ask shows up as an auto-denial.

Dependencies / Side Effects:
    Python 3.10+ standard library; `agy` on PATH (Linux /usr/local/bin/agy,
    Windows C:\\Program Files\\Antigravity\\bin\\agy.exe). Spawns the CLI as
    the test user (Linux: runuser) and writes stream/stderr evidence files.
==============================================================================
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from agyv import transcript
from agyv.env import IS_WINDOWS, TEST_USER, GatewayConfig, redact
from agyv.probes import RoundPaths, SurfaceResult

LOG = logging.getLogger("agyv.surfaces.cli")

AGY_BIN = r"C:\Program Files\Antigravity\bin\agy.exe" if IS_WINDOWS else "/usr/local/bin/agy"


def user_env(home: Path, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build the environment for a surface process running with the round HOME.

    Parameters:
        home (Path): Round HOME.
        extra (dict[str, str] | None): Additional variables.
    Return Value:
        dict[str, str]: Environment mapping.
    Exceptions/Errors:
        None.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGY_LLM_GATEWAY", "AGYV_"))}
    env["HOME"] = str(home)
    if IS_WINDOWS:
        # Antigravity resolves the home folder from USERPROFILE on Windows.
        env["USERPROFILE"] = str(home)
        env["APPDATA"] = str(home / "AppData" / "Roaming")
        env["LOCALAPPDATA"] = str(home / "AppData" / "Local")
    else:
        env["USER"] = TEST_USER
        env["LOGNAME"] = TEST_USER
        env["XDG_CONFIG_HOME"] = str(home / ".config")
        env["XDG_CACHE_HOME"] = str(home / ".cache")
        env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env.update(extra or {})
    return env


def as_user(cmd: list[str], env: dict[str, str]) -> list[str]:
    """Wrap a command so it runs as the test user (Linux) with `env`.

    Parameters:
        cmd (list[str]): Command and arguments.
        env (dict[str, str]): Environment to pass explicitly.
    Return Value:
        list[str]: Wrapped command (unchanged on Windows).
    Exceptions/Errors:
        None.
    """
    if IS_WINDOWS:
        return cmd
    keep = [f"{k}={v}" for k, v in env.items()
            if k in ("HOME", "USER", "LOGNAME", "PATH", "LANG", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                     "XDG_DATA_HOME", "DISPLAY", "TERM") or k.startswith("AGY")]
    return ["runuser", "-u", TEST_USER, "--", "env", "-i", *keep, *cmd]


def run(prompt: str, rp: RoundPaths, gateway: GatewayConfig, skip_permissions: bool,
        extra_flags: list[str] | None = None, timeout_s: int = 240) -> SurfaceResult:
    """Run one prompt in print mode and normalize the stream-json events.

    Parameters:
        prompt (str): Probe prompt.
        rp (RoundPaths): Round directories (HOME, workspace, evidence).
        gateway (GatewayConfig): Used only to redact evidence.
        skip_permissions (bool): Pass --dangerously-skip-permissions.
        extra_flags (list[str] | None): Extra CLI flags (e.g. --mode plan, --settings ...).
        timeout_s (int): Hard timeout for the CLI process.
    Return Value:
        SurfaceResult: Normalized evidence.
    Exceptions/Errors:
        None (failures are returned in SurfaceResult.error).
    """
    res = SurfaceResult()
    flags = ["-p", prompt, "--output-format", "stream-json"]
    if skip_permissions:
        flags.append("--dangerously-skip-permissions")
    flags += extra_flags or []
    env = user_env(rp.home)
    cmd = as_user([AGY_BIN, *flags], env)
    try:
        # Explicit UTF-8: Windows would otherwise decode the CLI's UTF-8 stream
        # with the ANSI code page (cp1252) and crash on the first non-Latin byte.
        proc = subprocess.run(cmd, cwd=rp.workspace, env=env, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        res.error = f"CLI timed out after {timeout_s}s"
        (rp.evidence / "cli_stream.jsonl").write_text(redact(str(exc.stdout or ""), gateway), encoding="utf-8")
        return res
    res.exit_code = proc.returncode
    stream_path = rp.evidence / "cli_stream.jsonl"
    err_path = rp.evidence / "cli_stderr.txt"
    stream_path.write_text(redact(proc.stdout, gateway), encoding="utf-8")
    err_path.write_text(redact(proc.stderr, gateway), encoding="utf-8")
    res.raw_paths += [str(stream_path), str(err_path)]

    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("event")
        if kind == "init":
            res.tools_offered = list(event.get("init", {}).get("tools", []))
        elif kind == "step_update":
            step = event.get("step_update", {})
            if step.get("step_type") == "tool" and step.get("state") == "ACTIVE":
                info = step.get("tool_info", {})
                res.tool_calls.append({"name": info.get("name") or step.get("tool_name"),
                                       "params": info.get("parameters", {})})
        elif kind == "result":
            result = event.get("result", {})
            res.response = result.get("response", "") or ""
            res.denied = list(result.get("denied_actions", []) or [])
    # The transcript carries tool results and denial messages that stream-json omits.
    transcript_path = transcript.find_latest(rp.home)
    if transcript_path:
        res.steps, final_text = transcript.parse(transcript_path)
        res.response = res.response or final_text
        copy = rp.evidence / "transcript.jsonl"
        copy.write_text(redact(transcript_path.read_text(encoding="utf-8"), gateway), encoding="utf-8")
        res.raw_paths.append(str(copy))
    if not res.tool_calls and not res.steps and proc.returncode != 0:
        res.error = redact(proc.stderr.strip()[-600:], gateway) or f"CLI exited {proc.returncode}"
    return res
