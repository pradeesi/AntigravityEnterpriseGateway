#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: explore_ui.py — Inspect and probe the GUI surfaces interactively
==============================================================================
Purpose:
    Launches one Antigravity GUI surface (desktop App, `agy --hub` web UI or
    VS Code extension) in a fresh round HOME through the same launcher the
    matrix uses (agyv/surfaces/hub.py), then dumps what is on screen (visible
    text, labeled interactive elements, screenshot) at each stage: ready,
    settings pages, permission cards, final state. Optionally sends a prompt,
    answers cards (approve once or reject), and reports the transcript steps,
    the cards seen, whether a given file exists afterwards, and which files
    the surface created or rewrote under ~/.gemini.

Architecture / Context:
    Operator tool next to run_matrix.py (copied to the VM with the harness).
    Used to discover selectors before writing hub.py, to capture settings-page
    evidence, and for one-off experiments (e.g. VS Code workspace settings
    pointing the backend at another gemini dir). It never writes the shared
    admin_settings.json; it only checks that it is in gateway mode.

Dependencies / Side Effects:
    Linux, run as root (spawns processes as the test user). Python 3.10+ with
    websocket-client (/opt/agy-verify/venv). Creates
    <WORK_ROOT>/rounds/explore/<surface>/<name>/{home,out,evidence}, starts and
    stops the surface processes of that round only, and prints a JSON summary.
==============================================================================
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agyv import files, transcript  # noqa: E402
from agyv.env import TEST_USER, WORK_ROOT, load_gateway, redact  # noqa: E402
from agyv.probes import RoundPaths, SurfaceResult  # noqa: E402
from agyv.surfaces import hub  # noqa: E402

LOG = logging.getLogger("agyv.explore")

# Clicks a visible button/link whose text or aria-label matches exactly (case-insensitive).
CLICK_TEXT_JS = """
((needle) => {
  const doc = %s;
  const n = needle.toLowerCase();
  const items = [...doc.querySelectorAll('button, a, [role="button"], [role="menuitem"], [role="tab"]')];
  const hit = items.find(e => ((e.innerText || '').trim().toLowerCase() === n || (e.getAttribute('aria-label') || '').trim().toLowerCase() === n));
  if (!hit) return 'missing';
  hit.click();
  return 'clicked';
})
""" % hub._DOC

# Clicks the "Open" button in the settings row whose title starts with `title`.
OPEN_ROW_JS = """
((title) => {
  const doc = %s;
  const rows = [...doc.querySelectorAll('div')].filter(d => (d.innerText || '').startsWith(title) && d.querySelector('button'));
  rows.sort((a, b) => a.innerText.length - b.innerText.length);
  if (!rows.length) return 'no-row';
  const b = [...rows[0].querySelectorAll('button')].find(x => /^(open|edit)$/i.test((x.innerText || '').trim()));
  if (!b) return 'no-button';
  b.click();
  return 'clicked';
})
""" % hub._DOC


def _make_round(surface: str, name: str) -> RoundPaths:
    """Create a clean exploration round owned by the test user.

    Parameters:
        surface (str): Surface name.
        name (str): Round name (letters, digits, dashes; keep it neutral for Model Armor).
    Return Value:
        RoundPaths: Round directories.
    Exceptions/Errors:
        ValueError: Invalid name.
        OSError: Filesystem errors.
    """
    if not name.replace("-", "").isalnum():
        raise ValueError(f"round name must be alphanumeric/dashes: {name!r}")
    base = WORK_ROOT / "rounds" / "explore" / surface / name
    if base.exists():
        hub._kill_home(base / "home")
        shutil.rmtree(base)
    rp = RoundPaths(home=base / "home", workspace=base / "home" / "ws", outside=base / "out",
                    evidence=base / "evidence")
    for path in (rp.workspace, rp.outside, rp.evidence):
        path.mkdir(parents=True, exist_ok=True)
    for path in (WORK_ROOT, WORK_ROOT / "rounds", WORK_ROOT / "rounds" / "explore", base.parent, base):
        os.chmod(path, 0o755)
    for path in (rp.home, rp.workspace, rp.outside):
        shutil.chown(path, user=TEST_USER, group=TEST_USER)
    os.chmod(rp.home, 0o700)
    return rp


def _parse_assignments(items: list[str], what: str) -> dict[str, Any]:
    """Parse KEY=JSON command-line assignments.

    Parameters:
        items (list[str]): Raw "key=json" strings.
        what (str): Label for error messages.
    Return Value:
        dict[str, Any]: key -> parsed JSON (plain strings are kept verbatim).
    Exceptions/Errors:
        ValueError: Missing "=".
    """
    out: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"{what} must look like key=JSON: {item!r}")
        key, _, raw = item.partition("=")
        try:
            out[key] = json.loads(raw)
        except json.JSONDecodeError:
            out[key] = raw
    return out


def _substitute(obj: Any, rp: RoundPaths) -> Any:
    """Replace {HOME}/{WS}/{OUT} placeholders in strings of a JSON-like object."""
    values = {"HOME": str(rp.home), "WS": str(rp.workspace), "OUT": str(rp.outside)}
    if isinstance(obj, str):
        for key, value in values.items():
            obj = obj.replace("{" + key + "}", value)
        return obj
    if isinstance(obj, dict):
        return {_substitute(k, rp): _substitute(v, rp) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute(v, rp) for v in obj]
    return obj


def _dump_other_targets(h: hub.Handle, ui: hub.Ui, prefix: Path) -> list[str]:
    """Write the visible text of every other Hub UI target (VS Code opens Settings in an editor webview).

    Parameters:
        h (hub.Handle): Launched surface.
        ui (hub.Ui): Sessions (the chat target is skipped).
        prefix (Path): Output prefix; files are <prefix>_target<N>.txt.
    Return Value:
        list[str]: Files written.
    Exceptions/Errors:
        None (unreachable targets are skipped).
    """
    written: list[str] = []
    marker = f"127.0.0.1:{h.slot.hub_port}"
    others = [t for t in hub._targets(h.slot.cdp_port)
              if marker in t.get("url", "") and t.get("id") != ui.chat_target.get("id")]
    for index, target in enumerate(others, 1):
        session = None
        try:
            session = hub.cdp.Session(target)
            text = session.ui_text()
            path = Path(f"{prefix}_target{index}.txt")
            path.write_text(f"{target.get('url', '')}\n\n{text}", encoding="utf-8")
            written.append(str(path))
        except (RuntimeError, OSError) as exc:
            LOG.debug("target dump failed: %s", exc)
        finally:
            if session is not None:
                session.close()
    return written


def _settings_pages(h: hub.Handle, ui: hub.Ui) -> list[str]:
    """Open Settings → General and the Tool Permissions dialog, dumping each page.

    Parameters:
        h (hub.Handle): Launched surface.
        ui (hub.Ui): Sessions.
    Return Value:
        list[str]: Dump prefixes written.
    Exceptions/Errors:
        None (navigation failures are logged and skipped).
    """
    written: list[str] = []
    steps = [("settings_general", CLICK_TEXT_JS, "Settings"),
             ("settings_tool_permissions", OPEN_ROW_JS, "Tool Permissions"),
             ("settings_terminal_commands", OPEN_ROW_JS, "Terminal Commands")]
    for label, js, arg in steps:
        try:
            result = ui.chat.eval(f"({js})({json.dumps(arg)})")
        except RuntimeError as exc:
            LOG.warning("%s: %s", label, exc)
            continue
        LOG.info("%s: %s", label, result)
        time.sleep(2.0)
        prefix = h.rp.evidence / label
        hub.dump_ui(ui, prefix)
        written.append(str(prefix))
        written += _dump_other_targets(h, ui, prefix)
    try:
        ui.chat.key("Escape", "Escape", 27)
        time.sleep(0.5)
        ui.chat.key("Escape", "Escape", 27)
    except RuntimeError as exc:
        LOG.debug("escape failed: %s", exc)
    return written


def main() -> int:
    """Parse arguments, run the exploration, print a JSON summary.

    Return Value:
        int: 0 on success, 1 when the surface could not be driven.
    Exceptions/Errors:
        None (errors are reported in the summary).
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--surface", required=True, choices=hub.SURFACES)
    parser.add_argument("--name", default="x1", help="round name under rounds/explore/<surface>/")
    parser.add_argument("--slot", default="explore", choices=sorted(hub.SLOTS), help="port/display slot")
    parser.add_argument("--file", action="append", default=[],
                        help="user file kind=JSON (kinds from files.USER_FILE_PATHS); {HOME}/{WS}/{OUT} allowed")
    parser.add_argument("--workspace-file", action="append", default=[], help="workspace rel/path=JSON")
    parser.add_argument("--extra-arg", action="append", default=[], help="extra surface flag (repeatable)")
    parser.add_argument("--settings-pages", action="store_true", help="dump Settings pages (Q1 evidence)")
    parser.add_argument("--prompt", default="", help="prompt to send ({HOME}/{WS}/{OUT} allowed)")
    parser.add_argument("--reject", action="store_true", help="reject cards (default: approve once)")
    parser.add_argument("--check-file", action="append", default=[], help="report whether this path exists after")
    parser.add_argument("--trust-click", action="store_true",
                        help="VS Code with --extra-arg=--enable-workspace-trust: answer the trust dialog with 'trust'")
    parser.add_argument("--hold", type=int, default=0, help="seconds to keep the surface up before stopping")
    args = parser.parse_args()

    gateway = load_gateway()
    if not hub._admin_settings_ok(gateway):
        LOG.error("admin_settings.json is not in gateway mode; not starting")
        return 1
    rp = _make_round(args.surface, args.name)
    for kind, content in _parse_assignments(args.file, "--file").items():
        files.write_user_file(rp.home, kind, _substitute(content, rp))
    for rel, content in _parse_assignments(args.workspace_file, "--workspace-file").items():
        files.write_workspace_file(rp.workspace, rel, _substitute(content, rp), rp.home)
    summary: dict[str, Any] = {"surface": args.surface, "round": str(rp.home.parent), "error": ""}
    summary["gemini_before"] = hub._gemini_snapshot(rp.home)
    res = SurfaceResult()
    h = None
    ui = None
    started = time.time()
    try:
        h = hub.launch(args.surface, rp, hub.SLOTS[args.slot], extra_args=args.extra_arg)
        if args.surface == "vscode" and "--enable-workspace-trust" in args.extra_arg:
            # Give the workbench time to raise the trust dialog, then record it before answering.
            time.sleep(15)
            summary["trust_before"] = hub.workbench_dump(h, rp.evidence / "trust_dialog")
            if args.trust_click:
                summary["trust_click"] = hub.trust_workspace(h)
                time.sleep(5)
                summary["trust_after"] = hub.workbench_dump(h, rp.evidence / "trust_after")
        try:
            ui = hub.connect(h, timeout_s=90 if "--enable-workspace-trust" in args.extra_arg else hub.READY_TIMEOUT_S)
        except RuntimeError:
            if args.surface == "vscode":
                summary["workbench_on_failure"] = hub.workbench_dump(h, rp.evidence / "workbench_failure")
            raise
        error = hub.wait_ready(h, ui, res)
        hub.dump_ui(ui, rp.evidence / "ready")
        summary["backend_argv"] = hub.backend_argv(rp.home)
        if not error and args.surface == "app":
            error = hub.select_app_project(h, ui)
        if error:
            summary["error"] = error
        elif args.settings_pages:
            summary["settings_dumps"] = _settings_pages(h, ui)
        if args.prompt and not summary["error"]:
            started = time.time()
            error = hub.send_prompt(ui, _substitute(args.prompt, rp))
            if error:
                summary["error"] = error
            else:
                hub.drive_turn(h, ui, res, approve=not args.reject, started=started)
            hub.dump_ui(ui, rp.evidence / "final")
        if args.hold:
            time.sleep(args.hold)
    except Exception as exc:  # noqa: BLE001 — report every failure in the summary
        LOG.exception("exploration failed")
        summary["error"] = repr(exc)
    finally:
        if h is not None:
            hub._collect_transcript(h, res, gateway, started)
        if ui is not None:
            ui.close()
        if h is not None:
            hub.stop(h)
            summary["notes"] = h.notes
    summary.update({
        "driver_error": res.error,
        "prompts": res.prompts,
        "steps": [{k: s.get(k) for k in ("tool", "args", "status", "denied", "error", "output")} for s in res.steps],
        "response": res.response,
        "checked_files": {p: Path(_substitute(p, rp)).exists() for p in args.check_file},
        "transcript": str(transcript.find_latest(rp.home) or ""),
        "gemini_after": hub._gemini_snapshot(rp.home),
        "evidence_dir": str(rp.evidence),
    })
    text = redact(json.dumps(summary, indent=2, default=str), gateway)
    (rp.evidence / "explore_summary.json").write_text(text, encoding="utf-8")
    print(text)
    return 1 if summary["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
