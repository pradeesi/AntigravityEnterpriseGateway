#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: tui_probe.py — Drive the interactive Antigravity CLI (TUI) in tmux
==============================================================================
Purpose:
    Runs one prompt through the interactive `agy` terminal UI inside a private
    tmux server, records every distinct screen, and reports whether a
    permission or trust prompt appeared and whether the side effect happened.
    It checks behavior that print mode (`agy -p`) can't show, such as whether
    explicit ask rules prompt interactively or whether repository hooks
    trigger a trust prompt.

Architecture / Context:
    Diagnostic companion to run_matrix.py in the verification harness. Uses
    the same per-round layout (fresh HOME owned by the test user) and the same
    settings-file writers (agyv.files).

Dependencies / Side Effects:
    Linux only; Python 3.10+, tmux, runuser; must run as root. Rewrites the
    MDM admin_settings.json to the gateway-mode base (skipped when identical)
    and creates folders under <WORK_ROOT>/tui/<name>/.
==============================================================================
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agyv import files  # noqa: E402
from agyv.env import IS_WINDOWS, TEST_USER, WORK_ROOT, load_gateway, redact  # noqa: E402
from agyv.surfaces.cli import AGY_BIN, user_env  # noqa: E402
from agyv import transcript  # noqa: E402

LOG = logging.getLogger("agyv.tui")

# Words that show the TUI is asking the user something (permission card or trust dialog).
PROMPT_WORDS = ("allow", "deny", "reject", "approve", "permission", "trust", "do you want", "run this command")


def _tmux(sock: str, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    """Run a tmux command against the probe's private server as the test user.

    Parameters:
        sock (str): tmux -L socket name.
        *args (str): tmux arguments.
        env (dict[str, str]): Environment for the tmux client.
    Return Value:
        subprocess.CompletedProcess: Finished process (text mode).
    Exceptions/Errors:
        None (callers inspect returncode).
    """
    keep = [f"{k}={v}" for k, v in env.items()
            if k in ("HOME", "USER", "LOGNAME", "PATH", "LANG", "TERM", "XDG_CONFIG_HOME", "XDG_CACHE_HOME",
                     "XDG_DATA_HOME")]
    cmd = ["runuser", "-u", TEST_USER, "--", "env", "-i", *keep, "tmux", "-L", sock, *args]
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)


def _screen(sock: str, env: dict[str, str]) -> str:
    """Capture the visible pane text (empty string if the session is gone)."""
    res = _tmux(sock, "capture-pane", "-p", "-t", "main", env=env)
    return res.stdout if res.returncode == 0 else ""


def _wait_for_input(sock: str, env: dict[str, str], timeout_s: float = 30.0) -> bool:
    """Wait until the main chat view (input line + shortcut hint) is on screen.

    Parameters:
        sock (str): tmux socket name.
        env (dict[str, str]): tmux client environment.
        timeout_s (float): Maximum wait in seconds.
    Return Value:
        bool: True when the input view appeared, False on timeout.
    Exceptions/Errors:
        None.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if "for shortcuts" in _screen(sock, env):
            return True
        time.sleep(1)
    LOG.warning("main input view did not appear within %.0fs", timeout_s)
    return False


def run_probe(args: argparse.Namespace) -> dict:
    """Execute one TUI probe and return its summary.

    Parameters:
        args (argparse.Namespace): Parsed CLI options (see main()).
    Return Value:
        dict: {"name", "prompt_seen", "prompt_screens", "marker_exists", "screens", "transcript_steps",
               "response"}.
    Exceptions/Errors:
        ValueError: Invalid JSON in a settings option.
        OSError: Filesystem errors creating the round.
    """
    gateway = load_gateway()
    base = WORK_ROOT / "tui" / args.name
    if base.exists():
        shutil.rmtree(base)
    home, ws, out = base / "home", base / "home" / "ws", base / "screens"
    for path in (ws, out):
        path.mkdir(parents=True, exist_ok=True)
    for path in (base, home, ws):
        shutil.chown(path, user=TEST_USER, group=TEST_USER)

    files.write_admin_settings(gateway, None)
    values = {"{HOME}": str(home), "{WS}": str(ws)}

    def expand(text: str) -> str:
        """Substitute `{HOME}` and `{WS}` tokens inside a JSON flag string.

        Parameters:
            text (str): Raw argument text containing optional placeholders.
        Return Value:
            str: Expanded string with round paths substituted.
        Exceptions/Errors:
            None.
        """
        for key, value in values.items():
            text = text.replace(key, value)
        return text

    for kind, raw in (("cli_settings", args.cli_settings), ("shared_config", args.shared_config),
                      ("hooks", args.hooks)):
        if raw:
            files.write_user_file(home, kind, json.loads(expand(raw)))
    if args.workspace_hooks:
        files.write_workspace_file(ws, ".agents/hooks.json", json.loads(expand(args.workspace_hooks)), home)

    env = user_env(home, {"TERM": "xterm-256color"})
    sock = f"agyv-{args.name}"
    flags = [expand(f) for f in (args.flags or [])]
    start = _tmux(sock, "new-session", "-d", "-s", "main", "-x", "200", "-y", "50", "-c", str(ws),
                  AGY_BIN, *flags, env=env)
    if start.returncode != 0:
        raise OSError(f"tmux failed to start: {start.stderr.strip()}")

    screens: list[str] = []
    prompt_screens: list[int] = []

    def record(tag: str) -> str:
        """Capture the current tmux pane, write new redacted screens to disk, and track prompts.

        Parameters:
            tag (str): Stage label appended to the captured screen filename.
        Return Value:
            str: Current visible pane text.
        Exceptions/Errors:
            OSError: If writing the screen file fails.
        """
        text = _screen(sock, env)
        if text and (not screens or text != screens[-1]):
            screens.append(text)
            (out / f"{len(screens):02d}_{tag}.txt").write_text(redact(text, gateway), encoding="utf-8")
            if any(w in text.lower() for w in PROMPT_WORDS):
                prompt_screens.append(len(screens))
        return text

    time.sleep(args.startup)
    record("startup")
    # A fresh HOME starts with first-run onboarding (color scheme, Terms of Service, then the
    # folder-trust dialog "Do you trust the contents of this project?"); each advances with Enter
    # (the default choice is "Yes, I trust this folder"). Typing a prompt there would be swallowed.
    onboarding_words = ("choose your color scheme", "terms of service", "do you trust the contents")
    for _ in range(5):
        text = _screen(sock, env).lower()
        if not any(word in text for word in onboarding_words):
            break
        _tmux(sock, "send-keys", "-t", "main", "Enter", env=env)
        time.sleep(2.5)
        record("onboarding")
    prompt_screens.clear()  # onboarding text isn't a permission prompt
    if args.accept_startup_prompt and any(w in _screen(sock, env).lower() for w in PROMPT_WORDS):
        _tmux(sock, "send-keys", "-t", "main", "Enter", env=env)
        time.sleep(3)
        record("after_startup_enter")

    _wait_for_input(sock, env)
    typed = expand(args.prompt)
    for _ in range(2):
        _tmux(sock, "send-keys", "-t", "main", "-l", typed, env=env)
        time.sleep(1.0)
        # Keystrokes sent while the main view is still mounting are dropped; retype once if needed.
        if typed[:30] in _screen(sock, env).replace("\n", ""):
            break
    record("typed")
    _tmux(sock, "send-keys", "-t", "main", "Enter", env=env)
    deadline = time.time() + args.wait
    acted = False
    while time.time() < deadline:
        time.sleep(2)
        text = record("run")
        if not text:
            break
        if not acted and args.on_prompt != "none" and prompt_screens and prompt_screens[-1] == len(screens):
            # Keys are given explicitly: the TUI's card layout is version-specific.
            for key in (args.approve_keys if args.on_prompt == "approve" else args.reject_keys).split(","):
                _tmux(sock, "send-keys", "-t", "main", key, env=env)
                time.sleep(0.4)
            acted = True
            record("after_action")
    time.sleep(1)
    record("final")
    _tmux(sock, "kill-server", env=env)

    marker = ws / args.marker if args.marker else None
    steps, response = [], ""
    tpath = transcript.find_latest(home)
    if tpath:
        steps, response = transcript.parse(tpath)
        shutil.copy2(tpath, base / "transcript_full.jsonl")
    summary = {"name": args.name, "prompt_seen": bool(prompt_screens), "prompt_screens": prompt_screens,
               "acted": acted, "marker_exists": bool(marker and marker.exists()), "screens": len(screens),
               "transcript_steps": [{k: s.get(k) for k in ("tool", "status", "denied")} for s in steps],
               "response": response[-400:],
               "files_after": sorted(str(p.relative_to(home)) for p in (home / ".gemini").rglob("*")
                                     if p.is_file())[:80] if (home / ".gemini").exists() else []}
    (base / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv: list[str]) -> int:
    """CLI entry point.

    Parameters:
        argv (list[str]): Arguments without the program name.
    Return Value:
        int: 0 on success, 1 on errors.
    Exceptions/Errors:
        None (errors are logged).
    """
    parser = argparse.ArgumentParser(description="Drive the interactive agy TUI in tmux and record screens.")
    parser.add_argument("--name", required=True, help="probe name (folder under <WORK_ROOT>/tui)")
    parser.add_argument("--prompt", required=True, help="prompt text ({WS} and {HOME} are expanded)")
    parser.add_argument("--cli-settings", help="JSON for ~/.gemini/antigravity-cli/settings.json")
    parser.add_argument("--shared-config", help="JSON for ~/.gemini/config/config.json")
    parser.add_argument("--hooks", help="JSON for ~/.gemini/config/hooks.json")
    parser.add_argument("--workspace-hooks", help="JSON for <ws>/.agents/hooks.json")
    parser.add_argument("--flags", nargs="*", help="extra agy flags")
    parser.add_argument("--marker", help="file (relative to the workspace) whose existence means 'executed'")
    parser.add_argument("--on-prompt", choices=("none", "approve", "reject"), default="none")
    parser.add_argument("--approve-keys", default="Enter", help="comma-separated tmux keys to approve")
    parser.add_argument("--reject-keys", default="Escape", help="comma-separated tmux keys to reject")
    parser.add_argument("--accept-startup-prompt", action="store_true", help="press Enter on a startup dialog")
    parser.add_argument("--startup", type=float, default=8.0, help="seconds to wait for the TUI to start")
    parser.add_argument("--wait", type=float, default=60.0, help="seconds to watch after sending the prompt")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if IS_WINDOWS:
        LOG.error("tui_probe.py supports Linux only")
        return 1
    try:
        print(json.dumps(run_probe(args), indent=2))
    except (ValueError, OSError, RuntimeError) as exc:
        LOG.error("probe failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
