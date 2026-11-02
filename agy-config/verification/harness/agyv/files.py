#!/usr/bin/env python3
"""
==============================================================================
FILE HEADER: files.py — Writers for every Antigravity settings file under test
==============================================================================
Purpose:
    Writes the exact settings files a test case places under a per-round
    HOME (CLI settings.json, shared config.json, hooks.json, mcp_config.json,
    ACP settings, user gateway settings, browser allowlist, workspace files)
    plus the machine-wide MDM admin_settings.json, so each round starts from a
    known state and differs from a control round in one file only.

Architecture / Context:
    Used by runner.py. File kinds are the "placements" of the verification
    matrix: a test passes a dict {kind: content}; anything not listed is left
    absent, so a result can be attributed to the single file that changed.

Dependencies / Side Effects:
    Python 3.10+ standard library. Creates directories and files under the
    round HOME, chowns them to the test user on Linux, and rewrites the MDM
    admin_settings.json (root-owned, mode 0644 on Linux).
==============================================================================
"""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from agyv.env import ADMIN_SETTINGS, IS_WINDOWS, TEST_USER, GatewayConfig

LOG = logging.getLogger("agyv.files")

# Kind -> path relative to the round HOME (user-scope files).
USER_FILE_PATHS: dict[str, str] = {
    "cli_settings": ".gemini/antigravity-cli/settings.json",
    "shared_config": ".gemini/config/config.json",
    "hooks": ".gemini/config/hooks.json",
    "mcp": ".gemini/config/mcp_config.json",
    "acp_settings": ".gemini/antigravity-acp/settings.json",
    "user_gateway": ".antigravity/settings.json",
    "browser_allowlist": ".gemini/antigravity/browserAllowlist.txt",
    "app_settings_dir_settings": ".gemini/antigravity/settings.json",
}


def deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Return `base` recursively updated with `extra` (lists are replaced).

    Parameters:
        base (dict): Starting document (not modified).
        extra (dict): Overrides.
    Return Value:
        dict: Merged copy.
    Exceptions/Errors:
        None.
    """
    merged = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _chown_tree(path: Path, stop_at: Path) -> None:
    """Give the test user ownership of `path` and its parents up to `stop_at`.

    Parameters:
        path (Path): File or directory just created.
        stop_at (Path): Highest directory to chown (the round HOME).
    Return Value:
        None.
    Exceptions/Errors:
        None (no-op on Windows, where rounds run under the SSH user).
    """
    if IS_WINDOWS:
        return
    current = path
    while True:
        shutil.chown(current, user=TEST_USER, group=TEST_USER)
        if current == stop_at or current.parent == current:
            break
        current = current.parent


def write_user_file(home: Path, kind: str, content: Any) -> Path:
    """Write one user-scope settings file under the round HOME.

    Parameters:
        home (Path): Round HOME directory.
        kind (str): Key of USER_FILE_PATHS.
        content (Any): dict/list → JSON; str → written verbatim (lets tests
            write malformed files on purpose).
    Return Value:
        Path: The written file.
    Exceptions/Errors:
        KeyError: Unknown kind.
        OSError: Filesystem errors.
    """
    target = home / USER_FILE_PATHS[kind]
    target.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content, indent=2)
    target.write_text(text, encoding="utf-8")
    _chown_tree(target, home)
    LOG.debug("wrote %s (%d bytes)", target, len(text))
    return target


def write_workspace_file(workspace: Path, rel: str, content: Any, home: Path) -> Path:
    """Write a file inside the round workspace (e.g. .agents/hooks.json, .vscode/settings.json).

    Parameters:
        workspace (Path): Workspace root.
        rel (str): Path relative to the workspace.
        content (Any): dict/list → JSON; str → verbatim.
        home (Path): Round HOME (ownership boundary).
    Return Value:
        Path: The written file.
    Exceptions/Errors:
        OSError: Filesystem errors.
    """
    target = workspace / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    text = content if isinstance(content, str) else json.dumps(content, indent=2)
    target.write_text(text, encoding="utf-8")
    _chown_tree(target, home)
    return target


def base_admin_settings(gateway: GatewayConfig) -> dict[str, Any]:
    """Build the documented gateway-mode admin_settings.json used by every round.

    Parameters:
        gateway (GatewayConfig): Gateway URL, key and model list.
    Return Value:
        dict: admin_settings.json document (official schema keys only).
    Exceptions/Errors:
        None.
    """
    return {
        "gateway": {
            "enabled": True,
            "url": gateway.url,
            "apiKey": gateway.api_key,
            "wireProtocol": "genai",
            "customHeaders": {"X-Cost-Center": "agy-verify"},
        },
        "models": {
            "defaultModelId": gateway.default_model,
            "list": [{"modelId": m} for m in gateway.models],
        },
    }


def write_admin_settings(gateway: GatewayConfig, extra: Any = None) -> Path:
    """Rewrite the machine-wide MDM admin_settings.json for the next round.

    Parameters:
        gateway (GatewayConfig): Gateway settings for the base document.
        extra (Any): dict merged into the base (e.g. governance sections), or a
            str written verbatim instead of the base (malformed-file tests).
    Return Value:
        Path: ADMIN_SETTINGS.
    Exceptions/Errors:
        OSError: If the file can't be written (harness must run as root/admin).
    """
    ADMIN_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(extra, str):
        text = extra
    else:
        text = json.dumps(deep_merge(base_admin_settings(gateway), extra or {}), indent=2)

    # Parallel workers share this machine-wide file. Skipping identical rewrites
    # and replacing atomically means a client that starts mid-write never reads
    # a truncated file (which would fail open to Google sign-in and taint results).
    try:
        if ADMIN_SETTINGS.read_text(encoding="utf-8") == text:
            return ADMIN_SETTINGS
    except OSError:
        pass
    tmp = ADMIN_SETTINGS.with_name(f".{ADMIN_SETTINGS.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    if not IS_WINDOWS:
        os.chmod(tmp, 0o644)
    os.replace(tmp, ADMIN_SETTINGS)
    return ADMIN_SETTINGS
