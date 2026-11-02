#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: hub.py — Desktop App, `agy --hub` web UI and VS Code driver
==============================================================================
Purpose:
    Runs one probe prompt through one of the three GUI surfaces that share the
    Antigravity Hub backend — the desktop App (Electron), the self-hosted web
    UI served by `agy --hub` (opened in headless Chrome) and the VS Code
    extension (webview) — by driving the real UI over the Chrome DevTools
    Protocol: type the prompt, answer every permission card (approve once or
    reject), wait for the agent to finish, then normalize the surface's own
    conversation transcript into a SurfaceResult.

Architecture / Context:
    Surface driver used by runner.py for surfaces "app", "web" and "vscode"
    (runner._driver calls run(surface, prompt, rp, gateway, skip_permissions)).
    tools/explore_ui.py reuses launch() / connect() / dump_ui() / stop() to
    inspect the UI. Each surface owns a fixed resource slot (Xvfb display, CDP
    port, hub port) inside the ranges reserved for this work (:110-:119,
    9310-9319, 4410-4419) so it can run next to other harness processes.
    Workspace wiring (verified on the VM): web passes `--add-dir=<ws>` to
    `agy --hub`, VS Code's extension passes the opened folder the same way,
    and the App gets a pre-seeded project file whose folder is <ws> (its only
    other way to add a folder is a native file dialog that CDP cannot drive).

Dependencies / Side Effects:
    Linux only (runuser, Xvfb, /proc). Python 3.10+, websocket-client (via
    agyv.cdp). Spawns Xvfb (root) plus the surface processes as the test user
    with the round HOME, writes screenshots / UI dumps / logs into
    rp.evidence, and kills every process whose environment HOME is the round
    HOME when the round ends (never other users' processes).
==============================================================================
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import signal
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from agyv import cdp, transcript
from agyv.env import ADMIN_SETTINGS, IS_WINDOWS, TEST_USER, GatewayConfig, redact
from agyv.probes import RoundPaths, SurfaceResult
from agyv.surfaces.cli import AGY_BIN, user_env

LOG = logging.getLogger("agyv.surfaces.hub")

SURFACES = ("app", "web", "vscode")

APP_BIN = "/opt/antigravity-app/antigravity"          # target of /usr/local/bin/antigravity-desktop
CHROME_BIN = "/usr/bin/google-chrome"
VSCODE_BIN = "/usr/share/code/code"                   # Electron binary (the `code` wrapper forks and exits)
VSCODE_CLI = "/usr/bin/code"
VSIX_PATH = Path("/opt/agy-verify/vsix/google-antigravity.vsix")
XVFB_BIN = "/usr/bin/Xvfb"

# Name/id of the project seeded for the App so its conversations use <ws> as the workspace.
APP_PROJECT_ID = "agyv-workspace"

TURN_TIMEOUT_S = 240
READY_TIMEOUT_S = 150
# No UI or transcript change for this long (and no card pending) means the turn is stuck.
STALL_TIMEOUT_S = 75
# A Google sign-in screen must persist this long before the round counts as "gateway lost".
SIGNIN_GRACE_S = 25

# Text that means the surface fell back to Google sign-in instead of gateway mode.
SIGNIN_MARKERS = ("sign in with google", "continue with google", "accounts.google.com", "sign in to antigravity",
                  "log in with google", "waiting for authentication")


@dataclass(frozen=True)
class Slot:
    """Fixed per-surface resources inside the ranges reserved for this work.

    Attributes:
        display (int): Xvfb display number (:110-:119).
        cdp_port (int): Chrome DevTools port (9310-9319).
        hub_port (int): Hub HTTP port for `agy --hub` / the VS Code backend (4410-4419).
    """

    display: int
    cdp_port: int
    hub_port: int


SLOTS: dict[str, Slot] = {
    "web": Slot(110, 9310, 4410),
    "app": Slot(111, 9311, 4411),
    "vscode": Slot(112, 9312, 4412),
    "q4": Slot(118, 9318, 4418),
    "explore": Slot(119, 9319, 4419),
}
# Second slot set so a second matrix process (AGYV_HUB_SLOT_SET=alt) can run beside the first.
ALT_SLOTS: dict[str, Slot] = {
    "web": Slot(113, 9313, 4413),
    "app": Slot(114, 9314, 4414),
    "vscode": Slot(115, 9315, 4415),
}


def matrix_slot(surface: str) -> Slot:
    """Return the slot a matrix round of `surface` uses (main set, or alt via AGYV_HUB_SLOT_SET=alt).

    Parameters:
        surface (str): "app", "web" or "vscode".
    Return Value:
        Slot: Resources for the round.
    Exceptions/Errors:
        KeyError: Unknown surface.
    """
    return (ALT_SLOTS if os.environ.get("AGYV_HUB_SLOT_SET", "") == "alt" else SLOTS)[surface]


@dataclass
class Handle:
    """A launched surface and everything needed to drive and tear it down.

    Attributes:
        surface (str): "app", "web" or "vscode".
        rp (RoundPaths): Round directories.
        slot (Slot): Ports/display in use.
        procs (list[subprocess.Popen]): Wrapper processes started for the round.
        xvfb (Optional[subprocess.Popen]): Xvfb started for the round (root-owned).
        logs (dict[str, Path]): Named log files in rp.evidence.
        notes (list[str]): Observations worth keeping in the evidence (launch quirks).
    """

    surface: str
    rp: RoundPaths
    slot: Slot
    procs: list[subprocess.Popen] = field(default_factory=list)
    xvfb: Optional[subprocess.Popen] = None
    logs: dict[str, Path] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------------------------
# Process management
# ------------------------------------------------------------------------------

def _user_cmd(cmd: list[str], env: dict[str, str]) -> list[str]:
    """Wrap a command so it runs as the test user with exactly `env`.

    Parameters:
        cmd (list[str]): Command and arguments.
        env (dict[str, str]): Complete environment for the child (passed via `env -i`).
    Return Value:
        list[str]: runuser-wrapped command.
    Exceptions/Errors:
        None.
    """
    # cli.as_user keeps a fixed allow-list; GUI processes also need DISPLAY-adjacent
    # variables (e.g. SSH_CONNECTION for VS Code), so the full env is passed here.
    return ["runuser", "-u", TEST_USER, "--", "env", "-i", *[f"{k}={v}" for k, v in env.items()], *cmd]


def _gui_env(home: Path, display: Optional[int], extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Build a minimal environment for a GUI process of the round.

    Parameters:
        home (Path): Round HOME.
        display (Optional[int]): Xvfb display number, or None for headless processes.
        extra (Optional[dict[str, str]]): Additional variables.
    Return Value:
        dict[str, str]: Environment (HOME/XDG dirs point into the round).
    Exceptions/Errors:
        None.
    """
    base = user_env(home)
    keep = ("HOME", "USER", "LOGNAME", "LANG", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME")
    env = {k: base[k] for k in keep if k in base}
    env["PATH"] = "/usr/local/bin:/usr/bin:/bin"
    env.setdefault("LANG", "C.UTF-8")
    if display is not None:
        env["DISPLAY"] = f":{display}"
    env.update(extra or {})
    return env


def _spawn(cmd: list[str], env: dict[str, str], cwd: Path, log_path: Path) -> subprocess.Popen:
    """Start a test-user process in its own session with output captured to a log.

    Parameters:
        cmd (list[str]): Command to run as the test user.
        env (dict[str, str]): Environment for the child.
        cwd (Path): Working directory.
        log_path (Path): File receiving stdout+stderr.
    Return Value:
        subprocess.Popen: The runuser wrapper process.
    Exceptions/Errors:
        OSError: If the process can't be started.
    """
    log = open(log_path, "ab")  # noqa: SIM115 — the child owns the handle for its lifetime
    LOG.debug("spawn %s", " ".join(cmd)[:300])
    return subprocess.Popen(_user_cmd(cmd, env), cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, start_new_session=True)


def _ancestors() -> set[int]:
    """Return this process and its ancestors (never signalled by the cleanup)."""
    out, pid = set(), os.getpid()
    while pid > 1:
        out.add(pid)
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as handle:
                pid = int(handle.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return out


def _home_pids(home: Path) -> list[int]:
    """List processes whose environment HOME is exactly the round HOME.

    Parameters:
        home (Path): Round HOME.
    Return Value:
        list[int]: Matching PIDs (excluding this process and its ancestors).
    Exceptions/Errors:
        None (unreadable /proc entries are skipped).
    """
    # Matching the environment (not the command line) avoids killing the shell or sudo
    # that merely mentions the path, and every surface child inherits HOME.
    needle = f"HOME={home}".encode()
    skip = _ancestors()
    pids: list[int] = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) in skip:
            continue
        try:
            with open(f"/proc/{entry}/environ", "rb") as handle:
                if needle in handle.read().split(b"\0"):
                    pids.append(int(entry))
        except OSError:
            continue
    return pids


def _kill_home(home: Path, grace_s: float = 4.0) -> list[int]:
    """Terminate every process of the round (SIGTERM, then SIGKILL survivors).

    Parameters:
        home (Path): Round HOME.
        grace_s (float): Seconds between SIGTERM and SIGKILL.
    Return Value:
        list[int]: PIDs that received a signal.
    Exceptions/Errors:
        None.
    """
    signalled: list[int] = []
    for sig in (signal.SIGTERM, signal.SIGKILL):
        pids = _home_pids(home)
        if not pids:
            break
        for pid in pids:
            try:
                os.kill(pid, sig)
                signalled.append(pid)
            except OSError:
                continue
        deadline = time.time() + (grace_s if sig == signal.SIGTERM else 1.0)
        while time.time() < deadline and _home_pids(home):
            time.sleep(0.3)
    return sorted(set(signalled))


def _kill_stale_xvfb(display: int) -> None:
    """Kill an Xvfb left on one of our reserved displays by a crashed round.

    Parameters:
        display (int): Display number (inside the reserved range only).
    Return Value:
        None.
    Exceptions/Errors:
        None.
    """
    # Match on the exact argv (comm "Xvfb" + first argument ":<display>") rather than pkill -f,
    # which would also hit any shell whose command line merely mentions the display.
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as handle:
                argv = handle.read().split(b"\0")
        except OSError:
            continue
        if len(argv) > 1 and argv[0].endswith(b"Xvfb") and argv[1] == f":{display}".encode():
            try:
                os.kill(int(entry), signal.SIGKILL)
            except OSError:
                continue
    time.sleep(0.5)
    for stale in (Path(f"/tmp/.X11-unix/X{display}"), Path(f"/tmp/.X{display}-lock")):
        try:
            stale.unlink(missing_ok=True)
        except OSError:
            continue


def _start_xvfb(display: int, log_path: Path) -> subprocess.Popen:
    """Start a private Xvfb server for the round.

    Parameters:
        display (int): Display number inside the reserved range.
        log_path (Path): Log file.
    Return Value:
        subprocess.Popen: The Xvfb process (root-owned; stopped by stop()).
    Exceptions/Errors:
        RuntimeError: If the display socket never appears.
    """
    socket_path = Path(f"/tmp/.X11-unix/X{display}")
    if socket_path.exists() or Path(f"/tmp/.X{display}-lock").exists():
        _kill_stale_xvfb(display)
    log = open(log_path, "ab")  # noqa: SIM115
    # -ac: the GUI runs as the test user while Xvfb runs as root; the display is local-only.
    proc = subprocess.Popen([XVFB_BIN, f":{display}", "-screen", "0", "1600x1000x24", "-nolisten", "tcp", "-ac"],
                            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + 10
    while time.time() < deadline:
        if socket_path.exists():
            return proc
        time.sleep(0.2)
    proc.kill()
    raise RuntimeError(f"Xvfb :{display} did not start")


def _wait_http(url: str, timeout_s: float) -> bool:
    """Poll until an HTTP(S) URL answers (any status) or the timeout expires.

    Parameters:
        url (str): URL to probe.
        timeout_s (float): Seconds to wait.
    Return Value:
        bool: True when the server answered.
    Exceptions/Errors:
        None.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3):
                return True
        except urllib.error.HTTPError:
            return True
        except (OSError, ValueError):
            time.sleep(0.5)
    return False


def _chown_user(path: Path, stop_at: Path) -> None:
    """chown a path and its parents up to `stop_at` to the test user."""
    current = path
    while True:
        shutil.chown(current, user=TEST_USER, group=TEST_USER)
        if current == stop_at or current.parent == current:
            break
        current = current.parent


def _write_user_json(home: Path, rel: str, content: Any) -> Path:
    """Write a JSON file under the round HOME owned by the test user.

    Parameters:
        home (Path): Round HOME.
        rel (str): Path relative to HOME.
        content (Any): JSON-serializable content.
    Return Value:
        Path: Written file.
    Exceptions/Errors:
        OSError: Filesystem errors.
    """
    target = home / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(content, indent=2), encoding="utf-8")
    _chown_user(target, home)
    return target


def _admin_settings_ok(gateway: GatewayConfig) -> bool:
    """Return True when the machine-wide admin_settings.json is in gateway mode for our gateway.

    Parameters:
        gateway (GatewayConfig): Expected gateway URL.
    Return Value:
        bool: gateway.enabled is true and the URL matches.
    Exceptions/Errors:
        None (unreadable or malformed files return False).
    """
    try:
        doc = json.loads(ADMIN_SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    gw = doc.get("gateway") if isinstance(doc, dict) else None
    return isinstance(gw, dict) and gw.get("enabled") is True and str(gw.get("url", "")).rstrip("/") == gateway.url


# ------------------------------------------------------------------------------
# Surface launchers
# ------------------------------------------------------------------------------

def _launch_web(h: Handle, extra_args: list[str]) -> None:
    """Start `agy --hub` for the round and open its UI in headless Chrome.

    Parameters:
        h (Handle): Handle being filled.
        extra_args (list[str]): Extra `agy` flags (Q4 experiments).
    Return Value:
        None.
    Exceptions/Errors:
        RuntimeError: If the hub never serves its UI.
    """
    rp, slot = h.rp, h.slot
    env = _gui_env(rp.home, None, {"AGY_ENABLE_HUB": "1"})
    h.logs["hub"] = rp.evidence / "hub_stdout.txt"
    h.procs.append(_spawn([AGY_BIN, "--hub", f"--hub-port={slot.hub_port}", f"--add-dir={rp.workspace}",
                           *extra_args], env, rp.workspace, h.logs["hub"]))
    if not _wait_http(f"http://127.0.0.1:{slot.hub_port}/", 60):
        raise RuntimeError(f"agy --hub did not serve http://127.0.0.1:{slot.hub_port}/ within 60s")
    h.logs["chrome"] = rp.evidence / "chrome_stderr.txt"
    chrome_env = _gui_env(rp.home, None)
    # useWebSocket=true multiplexes the UI's streaming RPCs over one socket; without it the
    # UI opens 6 streams and exhausts Chrome's 6-connections-per-origin HTTP/1.1 limit.
    h.procs.append(_spawn([CHROME_BIN, "--headless=new", f"--remote-debugging-port={slot.cdp_port}",
                           f"--user-data-dir={rp.home / '.chrome-hub'}", "--no-first-run",
                           "--no-default-browser-check", "--disable-gpu", "--window-size=1600,1000",
                           f"http://127.0.0.1:{slot.hub_port}/?useWebSocket=true"],
                          chrome_env, rp.workspace, h.logs["chrome"]))


def _seed_app_project(rp: RoundPaths) -> Path:
    """Write the project file that makes <ws> the App conversation's workspace folder.

    Parameters:
        rp (RoundPaths): Round directories.
    Return Value:
        Path: The project JSON (~/.gemini/config/projects/agyv-workspace.json).
    Exceptions/Errors:
        OSError: Filesystem errors.
    """
    # Same protojson shape the projects store reads (project_pb.Project); no settings or
    # grants, so the global settings under test stay the only source of policy.
    doc = {"id": APP_PROJECT_ID, "name": APP_PROJECT_ID,
           "projectResources": {"resources": [{"folderUri": rp.workspace.as_uri()}]}}
    return _write_user_json(rp.home, f".gemini/config/projects/{APP_PROJECT_ID}.json", doc)


def _launch_app(h: Handle, extra_args: list[str]) -> None:
    """Start the desktop App under a private Xvfb with CDP enabled.

    Parameters:
        h (Handle): Handle being filled.
        extra_args (list[str]): Extra Electron flags.
    Return Value:
        None.
    Exceptions/Errors:
        RuntimeError: If Xvfb fails.
    """
    rp, slot = h.rp, h.slot
    seeded = _seed_app_project(rp)
    h.notes.append(f"seeded App project {seeded}")
    h.logs["xvfb"] = rp.evidence / "xvfb.txt"
    h.xvfb = _start_xvfb(slot.display, h.logs["xvfb"])
    env = _gui_env(rp.home, slot.display)
    h.logs["app"] = rp.evidence / "app_stdout.txt"
    h.procs.append(_spawn([APP_BIN, "--no-sandbox", "--disable-gpu", "--password-store=basic",
                           f"--remote-debugging-port={slot.cdp_port}", *extra_args, str(rp.workspace)],
                          env, rp.workspace, h.logs["app"]))


VSCODE_USER_SETTINGS: dict[str, Any] = {
    # A dead loopback release server keeps the extension on the agy we copy in (no download/update).
    "antigravity.releaseBaseUrl": "http://127.0.0.1:9",
    "workbench.startupEditor": "none",
    "workbench.tips.enabled": False,
    "workbench.secondarySideBar.defaultVisibility": "hidden",
    "chat.commandCenter.enabled": False,
    "chat.disableAIFeatures": True,
    "telemetry.telemetryLevel": "off",
    "update.mode": "none",
    "extensions.autoUpdate": False,
    "extensions.ignoreRecommendations": True,
    "window.titleBarStyle": "custom",
    "window.restoreWindows": "none",
    "files.hotExit": "off",
    "security.workspace.trust.enabled": False,
}


def _install_vsix(home: Path, user_data: Path, ext_dir: Path, log_path: Path) -> None:
    """Install the Antigravity VSIX into the round's own extensions dir.

    Parameters:
        home (Path): Round HOME (the installer runs as the test user with this HOME).
        user_data (Path): VS Code --user-data-dir of the round.
        ext_dir (Path): VS Code --extensions-dir of the round.
        log_path (Path): Install log.
    Return Value:
        None.
    Exceptions/Errors:
        RuntimeError: If the install produced no extension directory.
    """
    env = _gui_env(home, None)
    # DISPLAY must be unset: with a display the Electron binary activates the extension host and never exits.
    cmd = _user_cmd([VSCODE_CLI, "--user-data-dir", str(user_data), "--extensions-dir", str(ext_dir),
                     "--install-extension", str(VSIX_PATH), "--force"], env)
    with open(log_path, "ab") as log:
        subprocess.run(cmd, cwd="/tmp", stdout=log, stderr=subprocess.STDOUT, timeout=180, check=False)
    if not any(ext_dir.glob("google.google-antigravity-*/package.json")):
        raise RuntimeError(f"VSIX install produced no extension under {ext_dir} (see {log_path})")


def _prepare_vscode(rp: RoundPaths, slot: Slot, log_path: Path, trust_enabled: bool = False) -> tuple[Path, Path]:
    """Lay out the round's VS Code profile: agy binary, user settings, extension.

    Parameters:
        rp (RoundPaths): Round directories.
        slot (Slot): Ports in use (the extension's backend port is pinned to slot.hub_port).
        log_path (Path): Install log.
        trust_enabled (bool): Keep VS Code workspace trust on (Q4 experiment); off by default.
    Return Value:
        tuple[Path, Path]: (user-data-dir, extensions-dir).
    Exceptions/Errors:
        RuntimeError / OSError: Install or filesystem failures.
    """
    # The extension always runs ~/.gemini/bin/agy; copying the bench CLI there (plus the dead
    # releaseBaseUrl) pins the version under test instead of a fresh download.
    agy_target = rp.home / ".gemini" / "bin" / "agy"
    agy_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(AGY_BIN, agy_target)
    os.chmod(agy_target, 0o755)
    _chown_user(agy_target, rp.home)
    user_data = rp.home / ".vscode-data"
    _write_user_json(rp.home, ".vscode-data/User/settings.json",
                     {**VSCODE_USER_SETTINGS, "antigravity.serverPort": slot.hub_port,
                      "security.workspace.trust.enabled": trust_enabled})
    ext_dir = rp.home / ".vscode" / "extensions"
    ext_dir.mkdir(parents=True, exist_ok=True)
    _chown_user(ext_dir, rp.home)
    _install_vsix(rp.home, user_data, ext_dir, log_path)
    return user_data, ext_dir


def _launch_vscode(h: Handle, extra_args: list[str]) -> None:
    """Start VS Code with the Antigravity extension under a private Xvfb.

    Parameters:
        h (Handle): Handle being filled.
        extra_args (list[str]): Extra VS Code flags (e.g. trust experiments).
    Return Value:
        None.
    Exceptions/Errors:
        RuntimeError / OSError: Install or launch failures.
    """
    rp, slot = h.rp, h.slot
    trust_enabled = "--enable-workspace-trust" in extra_args
    h.logs["vsix_install"] = rp.evidence / "vsix_install.txt"
    user_data, ext_dir = _prepare_vscode(rp, slot, h.logs["vsix_install"], trust_enabled)
    h.logs["xvfb"] = rp.evidence / "xvfb.txt"
    h.xvfb = _start_xvfb(slot.display, h.logs["xvfb"])
    # SSH_CONNECTION mirrors the glinux_agy_capture sandbox (keeps the extension off desktop keyring paths).
    env = _gui_env(rp.home, slot.display, {"SSH_CONNECTION": "agyv-sandbox"})
    h.logs["vscode"] = rp.evidence / "vscode_stdout.txt"
    # The matrix disables workspace trust (noted in the report); "--enable-workspace-trust" is a
    # harness-only marker for the Q4 experiment, never passed to VS Code itself.
    trust_flags = [] if trust_enabled else ["--disable-workspace-trust"]
    flags = [a for a in extra_args if a != "--enable-workspace-trust"]
    h.notes.append(f"vscode workspace trust {'enabled' if trust_enabled else 'disabled (--disable-workspace-trust)'}")
    h.procs.append(_spawn([VSCODE_BIN, "--no-sandbox", "--ozone-platform=x11", "--disable-gpu",
                           "--user-data-dir", str(user_data), "--extensions-dir", str(ext_dir),
                           f"--remote-debugging-port={slot.cdp_port}", *trust_flags, "--new-window", "--wait",
                           *flags, str(rp.workspace)], env, rp.workspace, h.logs["vscode"]))


def launch(surface: str, rp: RoundPaths, slot: Optional[Slot] = None,
           extra_args: Optional[list[str]] = None) -> Handle:
    """Launch one GUI surface for the round.

    Parameters:
        surface (str): "app", "web" or "vscode".
        rp (RoundPaths): Round directories (settings files already written).
        slot (Optional[Slot]): Resource slot; defaults to matrix_slot(surface).
        extra_args (Optional[list[str]]): Extra surface flags (experiments only).
    Return Value:
        Handle: Launched surface.
    Exceptions/Errors:
        ValueError: Unknown surface or non-Linux host.
        RuntimeError / OSError: Launch failures (the caller must still call stop()).
    """
    if surface not in SURFACES:
        raise ValueError(f"unknown hub surface {surface!r}")
    if IS_WINDOWS:
        raise ValueError("hub.py drives the Linux GUI surfaces only")
    h = Handle(surface=surface, rp=rp, slot=slot or matrix_slot(surface))
    launcher: dict[str, Callable[[Handle, list[str]], None]] = {
        "web": _launch_web, "app": _launch_app, "vscode": _launch_vscode}
    launcher[surface](h, list(extra_args or []))
    return h


def stop(h: Handle) -> None:
    """Tear down every process of the round and the round's Xvfb.

    Parameters:
        h (Handle): Launched surface.
    Return Value:
        None.
    Exceptions/Errors:
        None.
    """
    killed = _kill_home(h.rp.home)
    for proc in h.procs:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
    if h.xvfb and h.xvfb.poll() is None:
        h.xvfb.terminate()
        try:
            h.xvfb.wait(timeout=5)
        except subprocess.TimeoutExpired:
            h.xvfb.kill()
    LOG.debug("stopped %s (signalled %d processes)", h.surface, len(killed))


# ------------------------------------------------------------------------------
# UI access over CDP
# ------------------------------------------------------------------------------

# Every UI snippet evaluates inside the document that hosts the Hub UI; VS Code nests it
# one level deeper (#active-frame) in some versions, so resolve that first.
_DOC = ("(() => { const af = document.getElementById('active-frame'); "
        "return (af && af.contentDocument) ? af.contentDocument : document; })()")

# Snapshot of the chat UI used by the turn loop (JSON string to survive returnByValue).
STATE_JS = """
(() => {
  const doc = %s;
  const vis = (e) => { if (!e) return false; const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const q = (s) => [...doc.querySelectorAll(s)];
  const responses = q('[role="article"][aria-label="Agent response"]');
  const last = responses.length ? responses[responses.length - 1] : null;
  const lastText = last ? (last.innerText || '') : '';
  const project = q('[aria-label^="Select project"]').find(vis);
  return JSON.stringify({
    url: location.href,
    hasInput: !!q('[aria-label="Message input"]').find(vis),
    users: q('[role="article"][aria-label="User message"]').length,
    responses: responses.length,
    lastText: lastText.slice(-2500),
    worked: /Worked for \\d/.test(lastText),
    waitingInput: /Waiting for user input/i.test(lastText),
    radios: q('input[id^="ask-opt-"]').length,
    project: project ? (project.getAttribute('aria-label') || '') : '',
    body: (doc.body ? doc.body.innerText || '' : '').slice(0, 8000),
  });
})()
""" % _DOC

# Answers the Hub permission card (radio options + Skip/Submit). mode: approve | reject.
# Approve = the one-time "Yes, allow this time" option (never an "always allow" option);
# reject = "Skip", which the backend records as "user denied permission".
CARD_JS = """
((mode) => {
  const doc = %s;
  const radios = [...doc.querySelectorAll('input[id^="ask-opt-"]')];
  if (!radios.length) return JSON.stringify({found: false});
  let form = radios[0];
  while (form && !(form.querySelectorAll && [...form.querySelectorAll('button')].some(b => /^(submit|skip)/i.test((b.innerText || '').trim())))) form = form.parentElement;
  // Climb from the options form to the card whose first line is its "Allow ...?" title, so the
  // evidence names the action (command, path, tool) and not just the generic options.
  let card = form || radios[0].parentElement;
  for (let i = 0; i < 6 && card && card.parentElement; i++) {
    const first = ((card.innerText || '').trim().split('\\n')[0] || '');
    if (/\\?\\s*$/.test(first)) break;
    card = card.parentElement;
  }
  const opts = radios.map(r => {
    const lab = doc.querySelector('label[for="' + r.id + '"]') || r.closest('label') || r.parentElement;
    return {id: r.id, text: (lab ? lab.innerText : '').replace(/\\s+/g, ' ').trim()};
  });
  const text = (card ? card.innerText : '').replace(/\\s+/g, ' ').trim().slice(0, 900);
  const buttons = form ? [...form.querySelectorAll('button')] : [];
  if (mode === 'reject') {
    const skip = buttons.find(b => /^skip$/i.test((b.innerText || '').trim()));
    if (skip) { skip.click(); return JSON.stringify({found: true, text, opts, choice: 'Skip'}); }
    return JSON.stringify({found: true, text, opts, choice: null, why: 'no Skip button'});
  }
  const pick = opts.find(o => /allow this time|allow once|just this once/i.test(o.text) && !/always/i.test(o.text))
    || opts.find(o => /^\\d*\\s*yes\\b/i.test(o.text) && !/always/i.test(o.text));
  if (!pick) return JSON.stringify({found: true, text, opts, choice: null, why: 'no one-time allow option'});
  const input = doc.getElementById(pick.id);
  const lab = doc.querySelector('label[for="' + pick.id + '"]') || input.closest('label');
  (lab || input).click();
  return JSON.stringify({found: true, text, opts, choice: pick.text, needsSubmit: true});
})
""" % _DOC

SUBMIT_JS = """
(() => {
  const doc = %s;
  const b = [...doc.querySelectorAll('button')].find(x => /^submit/i.test((x.innerText || '').trim()));
  if (!b) return 'no-submit';
  if (b.disabled || b.getAttribute('aria-disabled') === 'true') return 'submit-disabled';
  b.click();
  return 'submitted';
})()
""" % _DOC

# Older approval UIs render plain approve/reject button pairs instead of the radio card.
BUTTON_CARD_JS = """
((mode) => {
  const doc = %s;
  const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const label = (b) => ((b.innerText || b.getAttribute('aria-label') || '').replace(/\\s+/g, ' ').trim());
  const yes = /^(run|allow|allow once|accept|approve|run command|yes)$/i;
  const no = /^(reject|deny|cancel|decline|no|skip)$/i;
  const all = [...doc.querySelectorAll('button')].filter(vis);
  for (const b of all.filter(x => yes.test(label(x)))) {
    let box = b.parentElement;
    for (let i = 0; i < 5 && box; i++, box = box.parentElement) {
      const txt = box.innerText || '';
      if (/Enable Notifications|Get notified/i.test(txt)) break;
      const partner = [...box.querySelectorAll('button')].filter(vis).find(x => no.test(label(x)));
      if (partner) {
        const target = mode === 'approve' ? b : partner;
        target.click();
        return JSON.stringify({found: true, text: txt.replace(/\\s+/g, ' ').trim().slice(0, 900), choice: label(target)});
      }
    }
  }
  return JSON.stringify({found: false});
})
""" % _DOC

# Clicks the next onboarding button (never a sign-in button); returns the label or ''.
ONBOARD_JS = """
(() => {
  const doc = %s;
  const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const order = [/^get started$/i, /^next$/i, /^continue$/i, /^accept$/i, /^i agree$/i, /^agree$/i, /^done$/i, /^skip$/i];
  const buttons = [...doc.querySelectorAll('button, [role="button"]')].filter(vis);
  for (const re of order) {
    const b = buttons.find(x => re.test((x.innerText || '').trim()) && !/sign in|log in|google/i.test(x.innerText || ''));
    if (b) { b.click(); return (b.innerText || '').trim(); }
  }
  return '';
})()
""" % _DOC

# Selects a project by name in the composer's project picker (App only).
OPEN_PROJECT_MENU_JS = """
(() => {
  const doc = %s;
  const b = [...doc.querySelectorAll('[aria-label^="Select project"]')].find(e => e.getBoundingClientRect().width > 0);
  if (!b) return 'no-picker';
  b.click();
  return b.getAttribute('aria-label');
})()
""" % _DOC

PICK_PROJECT_JS = """
((name) => {
  const doc = %s;
  const items = [...doc.querySelectorAll('[role="menuitem"], [role="option"]')].filter(e => e.getBoundingClientRect().width > 0);
  const hit = items.find(e => (e.innerText || '').trim() === name);
  if (!hit) return 'missing: ' + items.map(e => (e.innerText || '').trim()).join(' | ');
  hit.click();
  return 'picked';
})
""" % _DOC

FOCUS_INPUT_JS = """
(() => {
  const doc = %s;
  const el = [...doc.querySelectorAll('[aria-label="Message input"]')].find(e => e.getBoundingClientRect().width > 0);
  if (!el) return 'no-input';
  el.focus();
  return 'focused';
})()
""" % _DOC

CLICK_SEND_JS = """
(() => {
  const doc = %s;
  const b = [...doc.querySelectorAll('[aria-label="Send message"]')].find(e => e.getBoundingClientRect().width > 0);
  if (!b) return 'no-send';
  if (b.disabled || b.getAttribute('aria-disabled') === 'true') return 'send-disabled';
  b.click();
  return 'sent';
})()
""" % _DOC

# Opens the Antigravity view from VS Code's activity bar (the palette chord proved unreliable).
VSCODE_OPEN_VIEW_JS = """
(() => {
  const a = [...document.querySelectorAll('.activitybar [aria-label]')].find(e => /^antigravity$/i.test((e.getAttribute('aria-label') || '').trim()));
  if (!a) return 'no-activity-item';
  const item = a.closest('.action-item');
  if (item && item.classList.contains('checked')) return 'already-open';
  a.click();
  return 'clicked';
})()
"""

# Interactive elements with labels, for explore dumps and failure evidence.
ELEMENTS_JS = """
(() => {
  const doc = %s;
  const out = [];
  const sel = 'button, a, [role="button"], [role="menuitem"], [role="option"], [role="tab"], [role="switch"], [role="checkbox"], [role="combobox"], [role="article"], textarea, input, select, [contenteditable="true"], [aria-label]';
  for (const e of doc.querySelectorAll(sel)) {
    const r = e.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    out.push({tag: e.tagName.toLowerCase(), id: e.id || '', role: e.getAttribute('role') || '',
              label: (e.getAttribute('aria-label') || e.getAttribute('title') || e.getAttribute('placeholder') || '').slice(0, 120),
              text: (e.innerText || e.value || '').replace(/\\s+/g, ' ').trim().slice(0, 160),
              disabled: !!(e.disabled || e.getAttribute('aria-disabled') === 'true'),
              x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)});
  }
  return JSON.stringify(out);
})()
""" % _DOC


@dataclass
class Ui:
    """CDP sessions for a launched surface.

    Attributes:
        chat (cdp.Session): Session on the target whose document hosts the Hub UI.
        shot (cdp.Session): Session used for screenshots (VS Code: the workbench window).
        chat_target (dict): CDP target descriptor of the chat UI.
    """

    chat: cdp.Session
    shot: cdp.Session
    chat_target: dict[str, Any]

    def close(self) -> None:
        """Close both sessions (they may be the same object)."""
        self.chat.close()
        if self.shot is not self.chat:
            self.shot.close()


def _targets(port: int) -> list[dict[str, Any]]:
    """Return CDP targets that accept a debugger connection."""
    return [t for t in cdp.list_targets(port) if t.get("webSocketDebuggerUrl")]


def _chat_target(h: Handle) -> Optional[dict[str, Any]]:
    """Find the CDP target that hosts the Hub chat UI for the surface.

    Parameters:
        h (Handle): Launched surface.
    Return Value:
        Optional[dict]: Target descriptor, or None when it isn't there (yet).
    Exceptions/Errors:
        None.
    """
    targets = _targets(h.slot.cdp_port)
    if h.surface == "web":
        prefix = f"http://127.0.0.1:{h.slot.hub_port}"
        return next((t for t in targets if t.get("type") == "page" and t.get("url", "").startswith(prefix)), None)
    if h.surface == "app":
        # The App serves the UI from its embedded language server on a random https port;
        # a data: URL page is its splash/helper window.
        return next((t for t in targets if t.get("type") == "page"
                     and t.get("url", "").startswith("https://127.0.0.1:")), None)
    prefix = f"http://127.0.0.1:{h.slot.hub_port}/"
    return next((t for t in targets if t.get("url", "").startswith(prefix) and "extensionView=true" in t.get("url", "")),
                None)


def _workbench_target(h: Handle) -> Optional[dict[str, Any]]:
    """Return VS Code's workbench page target (None for other surfaces or before it exists)."""
    return next((t for t in _targets(h.slot.cdp_port)
                 if t.get("type") == "page" and "workbench" in t.get("url", "")), None)


def backend_argv(home: Path) -> list[str]:
    """Return the command lines of the round's agent backends (agy / language_server).

    Parameters:
        home (Path): Round HOME.
    Return Value:
        list[str]: One string per backend process, with token values masked.
    Exceptions/Errors:
        None.
    """
    out: list[str] = []
    for pid in _home_pids(home):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                argv = [a.decode("utf-8", "replace") for a in handle.read().split(b"\0") if a]
        except OSError:
            continue
        if argv and os.path.basename(argv[0]) in ("agy", "language_server"):
            # CSRF / host-bridge tokens are per-run secrets of the local server; keep them out of evidence.
            masked = [a.split("=", 1)[0] + "=<masked>" if a.startswith(("--csrf_token=", "--host_bridge_token="))
                      else a for a in argv]
            for i, arg in enumerate(masked[:-1]):
                if arg in ("--csrf_token", "--host_bridge_token"):
                    masked[i + 1] = "<masked>"
            out.append(" ".join(masked))
    return sorted(set(out))


# Text of VS Code's workspace-trust dialog / banner, for Q4 evidence.
TRUST_STATE_JS = """
(() => {
  const dlg = document.querySelector('.monaco-dialog-box, .dialog-shadow, [role="dialog"]');
  const banner = document.querySelector('.monaco-workbench .banner, .workspace-trust-banner');
  return JSON.stringify({dialog: dlg ? (dlg.innerText || '').trim().slice(0, 1500) : '',
                         banner: banner ? (banner.innerText || '').trim().slice(0, 500) : '',
                         title: document.title});
})()
"""

# Grants workspace trust the way a user would: the startup dialog's "trust" choice when VS Code
# shows one, otherwise the Restricted Mode banner's "Manage" link and then the trust editor's
# "Trust" button (VS Code 1.144 opens untrusted folders in Restricted Mode without a dialog).
TRUST_CLICK_JS = """
(() => {
  const vis = (e) => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const label = (e) => (e.innerText || e.getAttribute('title') || e.getAttribute('aria-label') || '').trim();
  const dialog = [...document.querySelectorAll('.monaco-dialog-box a.monaco-button, .monaco-dialog-box button')].filter(vis);
  const yes = dialog.find(b => /yes, i trust|trust folder|trust workspace|^trust$/i.test(label(b)));
  if (yes) { yes.click(); return 'clicked dialog: ' + label(yes); }
  const editor = [...document.querySelectorAll('.workspace-trust-editor a.monaco-button, .workspace-trust-editor button')].filter(vis);
  const trust = editor.find(b => /^trust( folder| workspace)?$/i.test(label(b)));
  if (trust) { trust.click(); return 'clicked editor: ' + label(trust); }
  const manage = [...document.querySelectorAll('.monaco-workbench .banner a, .monaco-workbench .banner [role="button"], .monaco-workbench .banner .monaco-link')]
    .filter(vis).find(b => /^manage$/i.test(label(b)));
  if (manage) { manage.click(); return 'opened-manage'; }
  return 'no-trust-control: ' + editor.map(label).concat(dialog.map(label)).join(' | ');
})()
"""


def workbench_dump(h: Handle, prefix: Path) -> dict[str, Any]:
    """Screenshot VS Code's workbench window and record its trust dialog/banner text.

    Parameters:
        h (Handle): Launched VS Code surface.
        prefix (Path): Output prefix (.png / .json are added).
    Return Value:
        dict: {"dialog", "banner", "title"} (empty dict when the workbench isn't reachable).
    Exceptions/Errors:
        None (failures are logged).
    """
    target = _workbench_target(h)
    if not target:
        return {}
    session = cdp.Session(target)
    try:
        info = json.loads(session.eval(TRUST_STATE_JS) or "{}")
        session.screenshot(str(prefix.with_suffix(".png")))
        prefix.with_suffix(".json").write_text(json.dumps(info, indent=2), encoding="utf-8")
        return info
    except (RuntimeError, OSError, ValueError) as exc:
        LOG.warning("workbench dump failed: %s", exc)
        return {}
    finally:
        session.close()


def trust_workspace(h: Handle, timeout_s: float = 60) -> str:
    """Grant VS Code workspace trust like a user would (Q4 experiment).

    Parameters:
        h (Handle): Launched VS Code surface (started with --enable-workspace-trust).
        timeout_s (float): Seconds to keep trying.
    Return Value:
        str: Click result ("clicked ...") or the reason nothing was clicked.
    Exceptions/Errors:
        None.
    """
    deadline = time.time() + timeout_s
    result = "no workbench"
    steps: list[str] = []
    while time.time() < deadline:
        target = _workbench_target(h)
        if target:
            session = cdp.Session(target)
            try:
                result = session.eval(TRUST_CLICK_JS) or ""
            except RuntimeError as exc:
                result = f"error: {exc}"
            finally:
                session.close()
            if not steps or steps[-1] != result:
                steps.append(result)
            if result.startswith("clicked"):
                return " -> ".join(steps)
        time.sleep(2)
    return " -> ".join(steps) or result


def connect(h: Handle, timeout_s: float = READY_TIMEOUT_S) -> Ui:
    """Attach CDP sessions to the surface's chat UI (opening VS Code's view if needed).

    Parameters:
        h (Handle): Launched surface.
        timeout_s (float): Seconds to wait for the UI target.
    Return Value:
        Ui: Connected sessions.
    Exceptions/Errors:
        RuntimeError: If the UI target never appears.
    """
    deadline = time.time() + timeout_s
    workbench: Optional[cdp.Session] = None
    last_view_click = 0.0
    while time.time() < deadline:
        if h.surface == "vscode":
            if workbench is None:
                target = _workbench_target(h)
                if target:
                    workbench = cdp.Session(target)
            if workbench is not None and time.time() - last_view_click > 15:
                try:
                    result = workbench.eval(VSCODE_OPEN_VIEW_JS)
                    last_view_click = time.time()
                    LOG.debug("vscode open view: %s", result)
                except RuntimeError as exc:
                    LOG.debug("vscode open view failed: %s", exc)
        target = _chat_target(h)
        if target:
            chat = cdp.Session(target)
            return Ui(chat=chat, shot=workbench or chat, chat_target=target)
        time.sleep(1.0)
    if workbench is not None:
        workbench.close()
    raise RuntimeError(f"{h.surface}: chat UI target did not appear within {int(timeout_s)}s")


def _state(ui: Ui) -> dict[str, Any]:
    """Return the parsed STATE_JS snapshot (empty dict if the page is navigating)."""
    try:
        raw = ui.chat.eval(STATE_JS)
        return json.loads(raw) if raw else {}
    except (RuntimeError, ValueError, OSError) as exc:
        LOG.debug("state read failed: %s", exc)
        return {}


def _shot(ui: Ui, path: Path, res: Optional[SurfaceResult] = None) -> None:
    """Save a screenshot (best effort) and register it as evidence.

    Parameters:
        ui (Ui): Sessions.
        path (Path): PNG path.
        res (Optional[SurfaceResult]): Result whose raw_paths gets the file.
    Return Value:
        None.
    Exceptions/Errors:
        None (failures are logged).
    """
    try:
        ui.shot.screenshot(str(path))
        if res is not None:
            res.raw_paths.append(str(path))
    except (RuntimeError, OSError, ValueError) as exc:
        LOG.warning("screenshot %s failed: %s", path.name, exc)


def dump_ui(ui: Ui, prefix: Path) -> dict[str, Any]:
    """Write the UI text, labeled elements and a screenshot for exploration/evidence.

    Parameters:
        ui (Ui): Sessions.
        prefix (Path): Output path prefix (suffixes .txt / .json / .png are added).
    Return Value:
        dict: The STATE_JS snapshot plus the element count.
    Exceptions/Errors:
        None (individual failures are logged).
    """
    state = _state(ui)
    prefix.with_suffix(".txt").write_text(state.get("body", ""), encoding="utf-8")
    try:
        elements = json.loads(ui.chat.eval(ELEMENTS_JS) or "[]")
    except (RuntimeError, ValueError, OSError) as exc:
        LOG.warning("element dump failed: %s", exc)
        elements = []
    prefix.with_suffix(".json").write_text(json.dumps({"state": {k: v for k, v in state.items() if k != "body"},
                                                       "elements": elements}, indent=2), encoding="utf-8")
    _shot(ui, prefix.with_suffix(".png"))
    state["element_count"] = len(elements)
    return state


def _signin_text(state: dict[str, Any]) -> str:
    """Return the visible UI text when it shows a Google sign-in screen, else ''."""
    body = state.get("body", "")
    return body[:600] if any(m in body.lower() for m in SIGNIN_MARKERS) else ""


def wait_ready(h: Handle, ui: Ui, res: Optional[SurfaceResult] = None, timeout_s: float = READY_TIMEOUT_S) -> str:
    """Click through onboarding until the chat input is usable.

    Parameters:
        h (Handle): Launched surface.
        ui (Ui): Sessions.
        res (Optional[SurfaceResult]): Gets onboarding screenshots as evidence.
        timeout_s (float): Seconds to wait.
    Return Value:
        str: "" when ready, otherwise an error text (sign-in screens include their visible text).
    Exceptions/Errors:
        None.
    """
    deadline = time.time() + timeout_s
    clicks = 0
    signin_since: Optional[float] = None
    while time.time() < deadline:
        state = _state(ui)
        signin = _signin_text(state)
        if signin and not state.get("hasInput"):
            # The App renders "Welcome to Antigravity / Continue with Google" for a second or two
            # before gateway auth completes; only a sign-in screen that stays is a failure.
            signin_since = signin_since or time.time()
            if time.time() - signin_since > SIGNIN_GRACE_S:
                _shot(ui, h.rp.evidence / "signin.png", res)
                # "sign in with google" is the phrase probes.classify() maps to GATEWAY_LOST.
                return ("surface dropped gateway mode and shows a Google sign-in screen (sign in with Google "
                        f"required); visible text: {signin}")
            if "transient sign-in screen" not in " ".join(h.notes):
                h.notes.append(f"transient sign-in screen at startup: {signin[:200]}")
            time.sleep(1.0)
            continue
        signin_since = None
        if state.get("hasInput") and "/onboarding" not in state.get("url", ""):
            return ""
        if state:
            clicked = ""
            try:
                clicked = ui.chat.eval(ONBOARD_JS) or ""
            except RuntimeError as exc:
                LOG.debug("onboarding click failed: %s", exc)
            if clicked:
                clicks += 1
                h.notes.append(f"onboarding: clicked '{clicked}'")
                _shot(ui, h.rp.evidence / f"onboarding_{clicks}.png", res)
        time.sleep(1.5)
    state = _state(ui)
    return f"{h.surface}: chat input not ready after {int(timeout_s)}s; UI text: {state.get('body', '')[:400]}"


def select_app_project(h: Handle, ui: Ui) -> str:
    """Select the seeded workspace project in the App's composer.

    Parameters:
        h (Handle): Launched surface (App).
        ui (Ui): Sessions.
    Return Value:
        str: "" on success, otherwise an error text.
    Exceptions/Errors:
        None.
    """
    for _ in range(10):
        state = _state(ui)
        if APP_PROJECT_ID in state.get("project", ""):
            return ""
        try:
            opened = ui.chat.eval(OPEN_PROJECT_MENU_JS)
            time.sleep(0.8)
            picked = ui.chat.eval(f"({PICK_PROJECT_JS})({json.dumps(APP_PROJECT_ID)})")
            LOG.debug("project picker: %s / %s", opened, picked)
        except RuntimeError as exc:
            LOG.debug("project selection failed: %s", exc)
        time.sleep(1.5)
    return f"App: could not select project {APP_PROJECT_ID!r}; picker shows {_state(ui).get('project', '')!r}"


def send_prompt(ui: Ui, prompt: str) -> str:
    """Type the prompt into the chat input and send it.

    Parameters:
        ui (Ui): Sessions.
        prompt (str): Probe prompt.
    Return Value:
        str: "" when the user message appeared in the conversation, else an error text.
    Exceptions/Errors:
        None.
    """
    before = _state(ui).get("users", 0)
    for attempt in range(3):
        try:
            if ui.chat.eval(FOCUS_INPUT_JS) != "focused":
                time.sleep(1.0)
                continue
            ui.chat.insert_text(prompt)
            time.sleep(0.6)
            sent = ui.chat.eval(CLICK_SEND_JS)
            if sent != "sent":
                ui.chat.key("Enter", "Enter", 13)
        except RuntimeError as exc:
            LOG.debug("send attempt %d failed: %s", attempt, exc)
        deadline = time.time() + 15
        while time.time() < deadline:
            if _state(ui).get("users", 0) > before:
                return ""
            time.sleep(0.5)
    return "prompt was not accepted by the chat input (no user message appeared)"


def _transcript_final(home: Path, since: float) -> bool:
    """True when the newest transcript (written after `since`) ends with a final agent answer.

    Parameters:
        home (Path): Round HOME.
        since (float): Epoch seconds; older transcripts are ignored.
    Return Value:
        bool: Last PLANNER_RESPONSE has text and no tool calls, after the last USER_INPUT.
    Exceptions/Errors:
        None.
    """
    path = transcript.find_latest(home)
    if not path or path.stat().st_mtime < since:
        return False
    final = False
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if item.get("type") == "USER_INPUT":
                final = False
            elif item.get("type") == "PLANNER_RESPONSE":
                final = not item.get("tool_calls") and bool(item.get("content"))
            elif item.get("source") in ("MODEL", "SYSTEM"):
                final = False
    except OSError:
        return False
    return final


def _answer_card(ui: Ui, approve: bool) -> Optional[dict[str, Any]]:
    """Answer one pending permission card, if any.

    Parameters:
        ui (Ui): Sessions.
        approve (bool): True → one-time allow; False → reject (Skip).
    Return Value:
        Optional[dict]: {"text", "options", "choice", "action", "kind"} when a card was handled, else None.
    Exceptions/Errors:
        None.
    """
    mode = "approve" if approve else "reject"
    try:
        card = json.loads(ui.chat.eval(f"({CARD_JS})({json.dumps(mode)})") or "{}")
    except (RuntimeError, ValueError) as exc:
        LOG.debug("card read failed: %s", exc)
        return None
    if card.get("found"):
        if card.get("needsSubmit"):
            time.sleep(0.5)
            submit = ""
            for _ in range(6):
                submit = ui.chat.eval(SUBMIT_JS)
                if submit == "submitted":
                    break
                time.sleep(0.5)
            card["submit"] = submit
        action = ("approved" if approve else "rejected") if card.get("choice") else "unanswered"
        return {"text": card.get("text", ""), "options": [o.get("text") for o in card.get("opts", [])],
                "choice": card.get("choice"), "action": action, "kind": "radio-card",
                "detail": card.get("why") or card.get("submit", "")}
    try:
        legacy = json.loads(ui.chat.eval(f"({BUTTON_CARD_JS})({json.dumps(mode)})") or "{}")
    except (RuntimeError, ValueError) as exc:
        LOG.debug("button card read failed: %s", exc)
        return None
    if legacy.get("found"):
        return {"text": legacy.get("text", ""), "options": [], "choice": legacy.get("choice"),
                "action": "approved" if approve else "rejected", "kind": "button-card", "detail": ""}
    return None


def drive_turn(h: Handle, ui: Ui, res: SurfaceResult, approve: bool, started: float,
               timeout_s: float = TURN_TIMEOUT_S) -> None:
    """Answer permission cards until the agent finishes (or the timeout hits).

    Parameters:
        h (Handle): Launched surface.
        ui (Ui): Sessions.
        res (SurfaceResult): Receives prompts, screenshots and errors.
        approve (bool): Approve (True) or reject (False) every card.
        started (float): Epoch seconds when the prompt was sent.
        timeout_s (float): Turn timeout.
    Return Value:
        None.
    Exceptions/Errors:
        None (a timeout is recorded in res.error only when nothing finished).
    """
    deadline = started + timeout_s
    done_polls = 0
    last_card: tuple[str, float] = ("", 0.0)
    last_change, last_fingerprint = time.time(), ""
    while time.time() < deadline:
        state = _state(ui)
        if state.get("radios") or state.get("waitingInput"):
            card_text = state.get("lastText", "")[-400:]
            # A just-answered card can linger for a moment; don't record it twice.
            if card_text == last_card[0] and time.time() - last_card[1] < 6:
                time.sleep(1.0)
                continue
            index = len(res.prompts) + 1
            _shot(ui, h.rp.evidence / f"card_{index}.png", res)
            card = _answer_card(ui, approve)
            if card:
                res.prompts.append(card)
                last_card = (card_text, time.time())
                LOG.info("%s: permission card %d %s (%s)", h.surface, index, card["action"], card["text"][:120])
                time.sleep(2.0)
                last_change = time.time()
                continue
        finished_ui = bool(state.get("worked")) and not state.get("radios")
        finished_transcript = _transcript_final(h.rp.home, started)
        # The UI's "Worked for Ns" footer and the transcript's final answer normally agree;
        # requiring both (or one of them for several polls) avoids stopping mid-turn.
        if finished_ui and finished_transcript:
            done_polls += 2
        elif finished_ui or finished_transcript:
            done_polls += 1
        else:
            done_polls = 0
        if done_polls >= 4:
            return
        path = transcript.find_latest(h.rp.home)
        fingerprint = f"{state.get('lastText', '')}|{path.stat().st_size if path else 0}"
        if fingerprint != last_fingerprint:
            last_change, last_fingerprint = time.time(), fingerprint
        elif time.time() - last_change > STALL_TIMEOUT_S:
            res.error = res.error or (f"{h.surface}: agent stalled (no UI/transcript change for {STALL_TIMEOUT_S}s); "
                                      f"last UI text: {state.get('lastText', '')[-300:]}")
            return
        time.sleep(1.5)
    res.error = res.error or f"{h.surface}: agent did not finish within {int(timeout_s)}s"


# ------------------------------------------------------------------------------
# Evidence and transcript
# ------------------------------------------------------------------------------

def _copy_logs(h: Handle, gateway: GatewayConfig, res: SurfaceResult) -> None:
    """Copy (redacted) surface logs that live outside rp.evidence into it.

    Parameters:
        h (Handle): Launched surface.
        gateway (GatewayConfig): Used to redact secrets.
        res (SurfaceResult): Gets the file paths.
    Return Value:
        None.
    Exceptions/Errors:
        None.
    """
    sources = {
        "app_main.log": h.rp.home / ".config" / "Antigravity" / "logs" / "main.log",
        "app_language_server.log": h.rp.home / ".config" / "Antigravity" / "logs" / "language_server.log",
    }
    for cli_log in sorted((h.rp.home / ".gemini").glob("*/log/cli-*.log"))[-2:]:
        sources[f"{cli_log.parent.parent.name}_{cli_log.name}"] = cli_log
    for name, src in sources.items():
        try:
            if src.exists():
                text = src.read_text(encoding="utf-8", errors="replace")[-200_000:]
                dest = h.rp.evidence / name
                dest.write_text(redact(text, gateway), encoding="utf-8")
                res.raw_paths.append(str(dest))
        except OSError as exc:
            LOG.debug("log copy %s failed: %s", src, exc)
    for path in h.logs.values():
        if path.exists():
            try:
                path.write_text(redact(path.read_text(encoding="utf-8", errors="replace"), gateway), encoding="utf-8")
                res.raw_paths.append(str(path))
            except OSError as exc:
                LOG.debug("log redaction %s failed: %s", path, exc)


def _gemini_snapshot(home: Path) -> dict[str, Any]:
    """Return the file list of ~/.gemini plus the shared config.json content (for Q2 evidence)."""
    root = home / ".gemini"
    files = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) if root.exists() else []
    config = root / "config" / "config.json"
    try:
        config_text = config.read_text(encoding="utf-8") if config.exists() else None
    except OSError:
        config_text = None
    return {"files": [f for f in files if "/brain/" not in f and "/conversations/" not in f][:400],
            "config_json": config_text}


def _collect_transcript(h: Handle, res: SurfaceResult, gateway: GatewayConfig, since: float) -> None:
    """Fill res.steps / res.response from the newest transcript written during the round.

    Parameters:
        h (Handle): Launched surface.
        res (SurfaceResult): Result to fill.
        gateway (GatewayConfig): Used to redact the evidence copy.
        since (float): Epoch seconds the prompt was sent.
    Return Value:
        None.
    Exceptions/Errors:
        None.
    """
    path = transcript.find_latest(h.rp.home)
    if not path or path.stat().st_mtime < since:
        return
    res.steps, final_text = transcript.parse(path)
    res.response = final_text or res.response
    copy = h.rp.evidence / "transcript.jsonl"
    try:
        copy.write_text(redact(path.read_text(encoding="utf-8"), gateway), encoding="utf-8")
        res.raw_paths.append(str(copy))
        (h.rp.evidence / "transcript_source.txt").write_text(str(path), encoding="utf-8")
    except OSError as exc:
        LOG.warning("transcript copy failed: %s", exc)


# ------------------------------------------------------------------------------
# Driver entry point
# ------------------------------------------------------------------------------

def run(surface: str, prompt: str, rp: RoundPaths, gateway: GatewayConfig, skip_permissions: bool,
        extra_args: Optional[list[str]] = None) -> SurfaceResult:
    """Run one probe prompt on a GUI surface and normalize the evidence.

    Parameters:
        surface (str): "app", "web" or "vscode".
        prompt (str): Probe prompt.
        rp (RoundPaths): Round directories (settings files already written by the runner).
        gateway (GatewayConfig): Used to verify gateway mode and to redact evidence.
        skip_permissions (bool): True → approve every permission card once (deny tests);
            False → reject every card (ask tests).
        extra_args (Optional[list[str]]): Extra surface flags (experiments only; the matrix passes none).
    Return Value:
        SurfaceResult: tool steps from the surface transcript, cards in `prompts`, final response,
        screenshots/logs in raw_paths, and `error` for driver failures.
    Exceptions/Errors:
        None (failures are returned in SurfaceResult.error).
    """
    res = SurfaceResult()
    if surface not in SURFACES:
        res.error = f"hub driver: unknown surface {surface!r}"
        return res
    if not prompt.strip():
        res.error = "hub driver: empty prompt"
        return res
    # Concurrent admin cases elsewhere rewrite the shared admin_settings.json; wait (bounded)
    # for gateway mode so a round never starts on a broken file and falls back to sign-in.
    # AGYV_HUB_SKIP_ADMIN_GUARD=1 is for the serial admin cases, which break the file on purpose.
    if os.environ.get("AGYV_HUB_SKIP_ADMIN_GUARD", "") != "1":
        waited = time.time()
        while not _admin_settings_ok(gateway) and time.time() - waited < 180:
            time.sleep(3)
        if not _admin_settings_ok(gateway):
            res.error = f"admin_settings.json is not in gateway mode for {gateway.url}; round not started"
            return res
    before = _gemini_snapshot(rp.home)
    h: Optional[Handle] = None
    ui: Optional[Ui] = None
    started = time.time()
    try:
        h = launch(surface, rp, extra_args=extra_args)
        ui = connect(h)
        error = wait_ready(h, ui, res)
        if not error and surface == "app":
            error = select_app_project(h, ui)
        if error:
            res.error = error
            return res
        _shot(ui, rp.evidence / "ready.png", res)
        h.notes.extend(f"backend: {argv}" for argv in backend_argv(rp.home))
        started = time.time()
        error = send_prompt(ui, prompt)
        if error:
            res.error = error
            return res
        drive_turn(h, ui, res, approve=skip_permissions, started=started)
        dump_ui(ui, rp.evidence / "final")
        res.raw_paths += [str(rp.evidence / "final.png"), str(rp.evidence / "final.txt")]
    except Exception as exc:  # noqa: BLE001 — every driver failure must land in the result
        LOG.exception("%s round failed", surface)
        res.error = res.error or f"hub driver: {exc!r}"
        if ui is not None:
            dump_ui(ui, rp.evidence / "failure")
    finally:
        _collect_transcript(h or Handle(surface, rp, matrix_slot(surface)), res, gateway, started)
        if not res.response and ui is not None:
            res.response = _state(ui).get("lastText", "")[-2000:]
        if ui is not None:
            ui.close()
        if h is not None:
            stop(h)
            _copy_logs(h, gateway, res)
            (rp.evidence / "hub_notes.json").write_text(json.dumps({
                "surface": surface, "slot": h.slot.__dict__, "notes": h.notes,
                "gemini_before": before, "gemini_after": _gemini_snapshot(rp.home)}, indent=2), encoding="utf-8")
            res.raw_paths.append(str(rp.evidence / "hub_notes.json"))
        # Evidence must never carry the gateway key, including texts copied out of the UI.
        res.response = redact(res.response, gateway)
        res.error = redact(res.error, gateway)
    return res
