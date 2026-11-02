#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: runner.py — Executes one test case on one surface with evidence
==============================================================================
Purpose:
    Creates a clean per-round HOME/workspace, writes exactly the settings
    files the case specifies (plus the gateway-mode admin_settings.json),
    prepares canaries, runs the probe through the chosen surface driver,
    classifies the outcome, and stores redacted evidence.

Architecture / Context:
    Called by run_matrix.py. Surface drivers live in agyv/surfaces/ and all
    return a probes.SurfaceResult. One round = one fresh HOME, so no state
    (approvals, caches, rewritten settings) leaks between cases.

Dependencies / Side Effects:
    Python 3.10+ standard library. Must run as root (Linux) or an
    administrator (Windows) because it rewrites the MDM admin_settings.json.
    Creates round folders under env.WORK_ROOT/rounds/<run_id>/.
==============================================================================
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import os
import shutil
import subprocess
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable

from agyv import files
from agyv.cases import Case, all_cases
from agyv.env import IS_WINDOWS, TEST_USER, WORK_ROOT, GatewayConfig, redact
from agyv.probes import EXECUTED, NOT_ATTEMPTED, PROBES, TOUCH_CMD, RoundPaths, SurfaceResult, classify

LOG = logging.getLogger("agyv.runner")

HARNESS_ROOT = Path(r"C:\ProgramData\agy-verify\harness") if IS_WINDOWS else Path("/opt/agy-verify/harness")
PYTHON_EXE = r"C:\Windows\py.exe" if IS_WINDOWS else "/usr/bin/python3"
# Baseline guard as hooks.json must invoke it on each OS (Windows: no inner quotes).
# Forward slashes on Windows: the ACP server splits hook commands POSIX-style (shlex), which eats
# backslashes ("External hook ... failed to execute"); PowerShell and the CLI accept "/" paths.
GUARD_CMD = ("powershell.exe -NoProfile -ExecutionPolicy Bypass -File "
             "C:/ProgramData/agy-verify/minimal-baseline/guard/agy_guard.ps1" if IS_WINDOWS
             else "/opt/agy-verify/minimal-baseline/guard/agy_guard.sh")


def _substitute(obj: Any, values: dict[str, str]) -> Any:
    """Replace {PLACEHOLDER} tokens inside every string of a JSON-like object.

    Parameters:
        obj (Any): dict / list / str / scalar.
        values (dict[str, str]): Placeholder -> value.
    Return Value:
        Any: New object with substitutions applied.
    Exceptions/Errors:
        None.
    """
    if isinstance(obj, str):
        for key, value in values.items():
            obj = obj.replace("{" + key + "}", value)
        return obj
    if isinstance(obj, dict):
        return {_substitute(k, values): _substitute(v, values) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute(v, values) for v in obj]
    return obj


# Stable 1-based position of each case in the full catalog (used for neutral round folders).
_CASE_INDEX = {c.id: i for i, c in enumerate(all_cases(), start=1)}

_PATH_RULE = re.compile(r"^(read_file|write_file)\((.+)\)$")


def _native_rule_paths(obj: Any) -> Any:
    """Normalize the path inside read_file(...)/write_file(...) rules to the OS separator.

    Parameters:
        obj (Any): dict / list / str / scalar (a settings document after substitution).
    Return Value:
        Any: New object; on Linux it is returned unchanged.
    Exceptions/Errors:
        None.
    """
    # Placeholders expand to native Windows paths while cases append "/sub", giving mixed
    # separators that a fair Windows rule test must not depend on.
    if not IS_WINDOWS:
        return obj
    if isinstance(obj, str):
        match = _PATH_RULE.match(obj)
        return f"{match.group(1)}({os.path.normpath(match.group(2))})" if match else obj
    if isinstance(obj, dict):
        return {k: _native_rule_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_native_rule_paths(v) for v in obj]
    return obj


def _set_locks(paths: list[Path], on: bool) -> None:
    """Make files immutable (or writable again) the way the baseline deploy scripts do.

    Parameters:
        paths (list[Path]): Files to lock or unlock.
        on (bool): True = lock, False = unlock.
    Return Value:
        None.
    Exceptions/Errors:
        None (failures are logged; an unlocked file would show up as a test failure, not a crash).
    """
    for path in paths:
        if IS_WINDOWS:
            user = os.environ.get("USERNAME", "")
            cmds = ([["attrib", "+R", str(path)], ["icacls", str(path), "/deny", f"{user}:(WD,AD,WEA,WA,DE,WDAC,WO)"]]
                    if on else [["icacls", str(path), "/remove:d", user], ["attrib", "-R", str(path)]])
        else:
            cmds = [["chattr", "+i" if on else "-i", str(path)]]
        for cmd in cmds:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if res.returncode != 0:
                LOG.warning("lock command %s failed: %s", cmd, res.stderr.strip()[:200])


def _remove_round(base: Path) -> None:
    """Delete a previous round folder, tolerating files still held open on Windows.

    Parameters:
        base (Path): Round folder.
    Return Value:
        None.
    Exceptions/Errors:
        OSError: Only if the folder can be neither deleted nor renamed aside.
    """
    for _ in range(5):
        try:
            shutil.rmtree(base)
            return
        except OSError:
            # A surface child process may still be exiting and holding a log file open.
            time.sleep(2)
    aside = base.with_name(f"{base.name}.stale-{int(time.time())}")
    LOG.warning("could not delete %s; moving it to %s", base, aside)
    base.rename(aside)


def _make_round(run_id: str, case: Case, surface: str, attempt: int = 1) -> RoundPaths:
    """Create clean round directories owned appropriately.

    Parameters:
        run_id (str): Matrix run id.
        case (Case): Case being run.
        surface (str): Surface name.
        attempt (int): 1-based attempt number; retries get a suffixed folder (r017-2).
    Return Value:
        RoundPaths: Round paths.
    Exceptions/Errors:
        OSError: Filesystem errors.
    """
    # Neutral folder names: the shared gateway's Model Armor rated prompts whose paths held case
    # ids ("D3.cmd.control"), run ids with words like "smoke", or hex hashes as dangerous / prompt
    # injection. "r017"-style names passed screening; case.txt maps the folder back to the case.
    suffix = "" if attempt <= 1 else f"-{attempt}"
    # Retries get their own folder: on Windows, Defender or a lingering child can keep the previous
    # attempt's files locked, so deleting it in place is not reliable.
    base = WORK_ROOT / "rounds" / run_id / surface / f"r{_CASE_INDEX.get(case.id, 0):03d}{suffix}"
    if base.exists():
        _remove_round(base)
    rp = RoundPaths(home=base / "home", workspace=base / "home" / "ws", outside=base / "out",
                    evidence=base / "evidence")
    for path in (rp.workspace, rp.outside, rp.evidence):
        path.mkdir(parents=True, exist_ok=True)
    (base / "case.txt").write_text(f"{case.id}\n{surface}\n", encoding="utf-8")
    if not IS_WINDOWS:
        for path in (WORK_ROOT, WORK_ROOT / "rounds", WORK_ROOT / "rounds" / run_id, base.parent, base):
            os.chmod(path, 0o755)
        for path in (rp.home, rp.workspace, rp.outside):
            shutil.chown(path, user=TEST_USER, group=TEST_USER)
        os.chmod(rp.home, 0o700)
    return rp


def _snapshot_tree(root: Path, limit: int = 400) -> list[str]:
    """List files under `root` (relative paths) for after-run evidence."""
    out: list[str] = []
    if not root.exists():
        return out
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out.append(str(path.relative_to(root)))
            if len(out) >= limit:
                break
    return out


def _driver(surface: str) -> Callable[..., SurfaceResult]:
    """Return the run function of a surface driver (imported lazily)."""
    if surface == "cli":
        from agyv.surfaces import cli
        return cli.run
    if surface == "acp":
        from agyv.surfaces import acp
        return acp.run
    if surface in ("app", "web", "vscode"):
        from agyv.surfaces import hub
        return lambda prompt, rp, gateway, skip_permissions, extra_flags=None: hub.run(
            surface, prompt, rp, gateway, skip_permissions)
    raise KeyError(f"unknown surface {surface}")


def run_case(run_id: str, case: Case, surface: str, gateway: GatewayConfig,
             retries: int = 1) -> dict[str, Any]:
    """Run one case on one surface and return the result record.

    Parameters:
        run_id (str): Matrix run id.
        case (Case): Case definition.
        surface (str): One of cases.ALL_SURFACES.
        gateway (GatewayConfig): Gateway settings.
        retries (int): Extra attempts when the agent didn't attempt the action.
    Return Value:
        dict: Result record (written to results.jsonl by the caller).
    Exceptions/Errors:
        None (errors are captured in the record).
    """
    probe = PROBES[case.probe]
    attempt, record = 0, {}
    while attempt <= retries:
        attempt += 1
        rp = _make_round(run_id, case, surface, attempt)
        # PY/HARNESS/OUT end up inside hook and MCP command lines: render them with "/" (see GUARD_CMD).
        values = {"HOME": str(rp.home), "WS": str(rp.workspace), "OUT": rp.outside.as_posix(),
                  "HARNESS": HARNESS_ROOT.as_posix(), "PY": PYTHON_EXE.replace("\\", "/"),
                  "TOUCH": TOUCH_CMD, "GUARD": GUARD_CMD}
        started = time.time()
        written: dict[str, str] = {}
        locked: list[Path] = []
        try:
            files.write_admin_settings(gateway, _substitute(case.admin_extra, values))
            for kind, content in case.files.items():
                path = files.write_user_file(rp.home, kind, _native_rule_paths(_substitute(content, values)))
                if case.lock:
                    locked.append(path)
                written[kind] = redact(path.read_text(encoding="utf-8"), gateway)
            for rel, content in case.workspace_files.items():
                path = files.write_workspace_file(rp.workspace, rel, _substitute(content, values), rp.home)
                written[f"workspace:{rel}"] = path.read_text(encoding="utf-8")
            _set_locks(locked, True)
            probe.prepare(rp)
            prompt = probe.prompt(rp)
            res = _driver(surface)(prompt, rp, gateway, case.approvals,
                                   extra_flags=_substitute(case.cli_flags, values))
        except Exception as exc:  # noqa: BLE001 — every failure must land in the record
            LOG.exception("case %s on %s failed", case.id, surface)
            res, prompt = SurfaceResult(error=f"harness: {exc!r}"), ""
        finally:
            _set_locks(locked, False)
        outcome, reason = classify(probe, rp, res, case.approvals)
        if case.placement == "control":
            verdict = "BASELINE_OK" if outcome == case.expect_if_honored else "BASELINE_UNEXPECTED"
        elif outcome == case.expect_if_honored:
            verdict = "HONORED"
        elif outcome == case.expect_if_ignored:
            verdict = "IGNORED"
        else:
            verdict = "OTHER"
        cli_after = rp.home / files.USER_FILE_PATHS["cli_settings"]
        record = {
            "run_id": run_id, "case": case.id, "domain": case.domain, "probe": case.probe,
            "placement": case.placement, "surface": surface, "attempt": attempt,
            "approvals": case.approvals, "outcome": outcome, "reason": reason, "verdict": verdict,
            "expect_if_honored": case.expect_if_honored, "expect_if_ignored": case.expect_if_ignored,
            "duration_s": round(time.time() - started, 1), "note": case.note,
            "prompt": prompt, "files_written": written,
            "cli_settings_after": redact(cli_after.read_text(encoding="utf-8"), gateway) if cli_after.exists() else None,
            "evidence": {**{k: v for k, v in asdict(res).items() if k != "raw_paths"},
                         "raw_paths": res.raw_paths,
                         "home_tree": _snapshot_tree(rp.home / ".gemini"),
                         "hook_audit": _read_text(rp.outside / "hook_audit.jsonl"),
                         "mcp_calls": _read_text(rp.outside / "mcp_calls.log")},
        }
        # Pass the entire serialized record through redact() so nested tool arguments,
        # stderr snippets, or hook payloads can never leak the gateway URL or API key.
        redacted_json = redact(json.dumps(record, indent=2), gateway)
        record = json.loads(redacted_json)
        (rp.evidence / "record.json").write_text(redacted_json, encoding="utf-8")
        if outcome not in (NOT_ATTEMPTED,) or case.expect_if_honored == NOT_ATTEMPTED:
            break
        LOG.info("case %s on %s: agent did not attempt the action; retrying", case.id, surface)
    return record


def _read_text(path: Path) -> str:
    """Read a small evidence file if present."""
    try:
        return path.read_text(encoding="utf-8")[-4000:] if path.exists() else ""
    except OSError:
        return ""
