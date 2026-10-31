# ==============================================================================
# FILE HEADER: Deep Cross-OS Validator & Auto-Fix Engine
# ==============================================================================
# Purpose:
#   Provides schema validation, real-runtime Antigravity OS/surface constraint
#   checks, secret-hygiene scanning, auto-schema detection, and deterministic
#   one-click Auto-Fix remediation across all 8 canonical Antigravity admin
#   configuration groups.
#
# Architecture / Context:
#   Pure-Python stateless module imported by `studio_engine.py` and `app.py`.
#   Encodes real-world findings validated against Antigravity CLI (`agy`),
#   Desktop App, Web Hub (`agy --hub`), VS Code/Visual Studio extensions, and
#   JetBrains/Zed ACP servers across Linux (`exebox`), macOS (`sandbox-exec`),
#   and Windows (`powershell.exe` `RequiresExactMatch`).
#
# Dependencies / Side Effects:
#   Uses only Python 3.11+ standard library modules (`json`, `re`, `typing`).
#   Performs zero disk writes, network calls, or secret logging.
# ==============================================================================

from __future__ import annotations

import json
import re
from typing import Any

# Placeholder constants used when scrubbing live secrets
API_KEY_PLACEHOLDER = "${REPLACE_WITH_GATEWAY_API_KEY}"
RAW_KEY_PLACEHOLDER = "REPLACE_WITH_GATEWAY_API_KEY"
PROXY_PASS_PLACEHOLDER = "${REPLACE_WITH_PROXY_PASSWORD}"

SAFE_PLACEHOLDER_PATTERNS = (
    "REPLACE_WITH_",
    "${",
    "<YOUR_",
    "<GATEWAY_",
    "YOUR_",
    "EXAMPLE_",
    "PLACEHOLDER",
    "REDACTED",
    "CHANGE_ME",
)

MULTI_CERT_BUNDLE_PATHS = {
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/cert.pem",
}

LINUX_ROOT_SYSTEM_DIRS = {"/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64"}


def _is_live_secret_value(val: Any) -> bool:
    """Determine whether a configuration string looks like a live secret/token.

    Summary:
        Inspects candidate secret fields (`apiKey`, `AGY_LLM_GATEWAY_API_KEY`,
        `password`, token env vars) and flags non-empty strings that do not match
        standard template placeholders.
    Parameters:
        val (Any): Raw field value extracted from JSON or `.env` text.
    Return Value:
        bool: `True` when `val` appears to be a live plaintext credential;
        `False` when blank, non-string, or using a safe placeholder marker.
    Exceptions/Errors:
        None.
    """
    if not isinstance(val, str):
        return False
    stripped = val.strip().strip('"').strip("'")
    if not stripped or len(stripped) < 8:
        return False
    upper_val = stripped.upper()
    for marker in SAFE_PLACEHOLDER_PATTERNS:
        if marker in upper_val:
            return False
    return True


def _extract_file_rule_target(rule: str) -> tuple[str | None, str | None]:
    """Parse `read_file(...)` or `write_file(...)` permission grant strings.

    Summary:
        Extracts the tool verb (`read_file` or `write_file`) and inner path
        argument when a permission rule targets local filesystem paths.
    Parameters:
        rule (str): Permission rule string from `allow`, `ask`, or `deny`.
    Return Value:
        tuple[str | None, str | None]: `(verb, inner_path)` if matched, or
        `(None, None)` for non-file permission rules.
    Exceptions/Errors:
        None.
    """
    match = re.match(r"^(read_file|write_file)\((.*)\)$", rule.strip())
    if not match:
        return None, None
    return match.group(1), match.group(2).strip()


def _make_issue(
    code: str,
    severity: str,
    file_id: str,
    title: str,
    message: str,
    fix_label: str | None = None,
    line: int | None = None,
) -> dict[str, Any]:
    """Build a normalized validation issue dictionary for UI and API consumers.

    Summary:
        Creates a consistent JSON-serializable issue record with optional
        Auto-Fix metadata and source line coordinates.
    Parameters:
        code (str): Stable machine identifier (for example `ERR_UTF8_BOM`).
        severity (str): One of `"ERROR"`, `"WARN"`, or `"INFO"`.
        file_id (str): Canonical studio file identifier.
        title (str): Concise human-readable headline.
        message (str): Detailed explanation of why the check triggered.
        fix_label (str | None): Button caption if Auto-Fix is supported.
        line (int | None): Optional 1-based line number in the raw text.
    Return Value:
        dict[str, Any]: Structured validation finding dictionary.
    Exceptions/Errors:
        None.
    """
    return {
        "code": code,
        "severity": severity,
        "file_id": file_id,
        "title": title,
        "message": message,
        "fixable": bool(fix_label),
        "fix_label": fix_label or "",
        "line": line,
    }


def detect_file_type(filename: str, raw_text: str) -> str:
    """Auto-detect which canonical Antigravity file slot matches an input file.

    Summary:
        Combines filename heuristics and structural content inspection so pasted
        snippets or renamed uploads map cleanly to one of the 11 canonical file
        slots across the 8 Antigravity admin configuration groups.
    Parameters:
        filename (str): Uploaded filename or user hint (may be empty on paste).
        raw_text (str): Decoded text content (with or without leading BOM).
    Return Value:
        str: Canonical `file_id` (`admin_settings`, `gateway_env`,
        `cli_settings`, `desktop_config`, `browser_allowlist`, `mcp_config`,
        `hooks_config`, `guard_sh`, `guard_ps1`, `acp_json`, or `acp_auth`).
    Exceptions/Errors:
        None. Falls back to `"admin_settings"` if completely unrecognizable.
    """
    clean_name = (filename or "").strip().lower().replace("\\", "/")
    base_name = clean_name.split("/")[-1]
    clean_text = (raw_text or "").lstrip("\ufeff").strip()

    # 1. Explicit filename matches
    if "admin_settings" in base_name:
        return "admin_settings"
    if base_name.endswith(".env") or "antigravity-gateway" in base_name or clean_name.endswith("antigravity-gateway.sh"):
        return "gateway_env"
    if base_name == "browserallowlist.txt" or "allowlist" in base_name:
        return "browser_allowlist"
    if "mcp_config" in base_name:
        return "mcp_config"
    if "hooks.json" in base_name:
        return "hooks_config"
    if base_name.endswith(".ps1"):
        return "guard_ps1"
    if base_name.endswith(".sh") and "gateway" not in base_name:
        return "guard_sh"
    if "antigravity-acp" in clean_name or base_name == "antigravity-acp-settings.json":
        return "acp_auth"
    if base_name == "acp.json" or "zed/settings.json" in clean_name:
        return "acp_json"
    if base_name == "config.json":
        return "desktop_config"

    # 2. Content-based detection for pasted text or generic `settings.json`
    if clean_text.startswith("#!/usr/bin/env bash") or clean_text.startswith("#!/bin/bash"):
        if "AGY_LLM_GATEWAY_" in clean_text and "PreToolUse" not in clean_text:
            return "gateway_env"
        return "guard_sh"
    if "ConvertFrom-Json" in clean_text or "$ErrorActionPreference" in clean_text:
        return "guard_ps1"
    if re.search(r"^(export\s+)?AGY_LLM_GATEWAY_", clean_text, flags=re.MULTILINE):
        return "gateway_env"

    try:
        parsed = json.loads(clean_text)
        if isinstance(parsed, dict):
            if "gateway" in parsed or "caCertPath" in parsed or "models" in parsed:
                return "admin_settings"
            if "userSettings" in parsed:
                return "desktop_config"
            if "mcpServers" in parsed:
                return "mcp_config"
            if "hooks" in parsed:
                return "hooks_config"
            if "agent_servers" in parsed:
                return "acp_json"
            if "auth" in parsed and isinstance(parsed.get("auth"), dict) and parsed["auth"].get("type") == "gateway":
                return "acp_auth"
            if any(k in parsed for k in ("agentMode", "toolPermission", "permissions", "enableTerminalSandbox")):
                return "cli_settings"
    except json.JSONDecodeError:
        pass

    if base_name == "settings.json":
        return "cli_settings"
    if clean_text and not clean_text.startswith("{"):
        return "browser_allowlist"
    return "admin_settings"


def _build_windows_ps_companion(cmd_inner: str) -> str | None:
    """Create an anchored PowerShell-safe regex grant for a literal command rule.

    Summary:
        On Windows (`powershell.exe` / `pwsh`), `terminal.RequiresExactMatch`
        always returns `True`, so bare `command(git status)` only matches exact
        zero-argument invocations. This helper builds a safe metacharacter-free
        anchored regex companion rule.
    Parameters:
        cmd_inner (str): Inner command text from `command(<cmd_inner>)`.
    Return Value:
        str | None: `command(regex:...)` rule string, or `None` if `cmd_inner`
        is already a `regex:` rule or wildcard.
    Exceptions/Errors:
        None.
    """
    trimmed = cmd_inner.strip()
    if not trimmed or trimmed == "*" or trimmed.startswith("regex:"):
        return None
    parts = [re.escape(tok) for tok in trimmed.split()]
    joined = r"\s+".join(parts)
    return f"command(regex:^(?i){joined}(\\s+[^;&|`$()\\r\\n>]*)?$)"


def _validate_permission_grants(
    file_id: str,
    grants: dict[str, Any],
    os_list: list[str],
    allow_non_workspace: bool,
    dev_user: str,
) -> list[dict[str, Any]]:
    r"""Validate `allow`, `ask`, and `deny` permission arrays across target OSes.

    Summary:
        Enforces V1/V2 Antigravity permission invariants including the fatal
        `unsandboxed(*)` deny footgun, Linux/macOS `exebox` bind-mount path
        constraints, lazy MCP `.gemini` read grants, Windows PowerShell
        `RequiresExactMatch` regex companions, and single-token `\s+` regex traps.
    Parameters:
        file_id (str): `"cli_settings"` or `"desktop_config"`.
        grants (dict[str, Any]): Dictionary containing `allow`, `ask`, `deny`.
        os_list (list[str]): Active OS identifiers (`linux`, `macos`, `windows`).
        allow_non_workspace (bool): Whether non-workspace file access is enabled.
        dev_user (str): Workstation developer username (e.g., `"alice"`).
    Return Value:
        list[dict[str, Any]]: Validation issues detected in the grant lists.
    Exceptions/Errors:
        None.
    """
    issues: list[dict[str, Any]] = []
    allow_list = [str(x) for x in grants.get("allow", []) if isinstance(x, str)]
    ask_list = [str(x) for x in grants.get("ask", []) if isinstance(x, str)]
    deny_list = [str(x) for x in grants.get("deny", []) if isinstance(x, str)]

    # 1. Fatal `unsandboxed(*)` in `deny`
    if "unsandboxed(*)" in deny_list:
        issues.append(
            _make_issue(
                code="ERR_DENY_UNSANDBOXED_WILDCARD",
                severity="ERROR",
                file_id=file_id,
                title='Fatal "unsandboxed(*)" rule in deny list',
                message=(
                    'In Antigravity V1 Covers semantics, "unsandboxed(*)" covers BOTH '
                    "unsandboxed and sandboxed command executions (Deny > Ask > Allow), "
                    "blocking every terminal command. Enforce sandboxing via "
                    'enableTerminalSandbox: true and proceed-in-sandbox instead.'
                ),
                fix_label='Remove "unsandboxed(*)" & enforce sandbox policy',
            )
        )

    # 2. Linux / macOS `exebox` & Seatbelt path rules
    posix_active = ("linux" in os_list) or ("macos" in os_list)
    if posix_active:
        glob_rules: list[str] = []
        rel_rules: list[str] = []
        win_drive_rules: list[str] = []
        root_sys_rules: list[str] = []

        for bucket_name, bucket in (("allow", allow_list), ("ask", ask_list), ("deny", deny_list)):
            for rule in bucket:
                verb, target = _extract_file_rule_target(rule)
                if not verb or target is None:
                    continue
                if target == "*":
                    continue
                if re.match(r"^[A-Za-z]:[\\/]", target) or "\\" in target:
                    win_drive_rules.append(rule)
                    continue
                if "*" in target or "?" in target:
                    glob_rules.append(rule)
                    continue
                if not (target.startswith("/") or target.startswith("~/")):
                    rel_rules.append(rule)
                    continue
                if "linux" in os_list and bucket_name == "deny" and verb == "write_file":
                    normalized = target.rstrip("/") or "/"
                    if normalized in LINUX_ROOT_SYSTEM_DIRS:
                        root_sys_rules.append(rule)

        if glob_rules:
            issues.append(
                _make_issue(
                    code="ERR_EXEBOX_GLOB_PATH",
                    severity="ERROR",
                    file_id=file_id,
                    title="Wildcard glob in file rule breaks Linux exebox mounts",
                    message=(
                        f"Found wildcard file path(s) ({', '.join(glob_rules[:3])}). "
                        "Linux exebox translates file rules into kernel bind mounts and "
                        "fails startup with 'globs not supported'. Use exact directory "
                        "or file paths and enforce extension wildcards in PreToolUse hooks."
                    ),
                    fix_label="Convert/remove glob file rules",
                )
            )
        if rel_rules:
            issues.append(
                _make_issue(
                    code="ERR_EXEBOX_RELATIVE_PATH",
                    severity="ERROR",
                    file_id=file_id,
                    title="Relative file path breaks sandbox bind mounts",
                    message=(
                        f"Found relative file path(s) ({', '.join(rel_rules[:3])}). "
                        "Sandbox file rules must start with '/' or '~/'."
                    ),
                    fix_label="Normalize relative paths to workspace paths",
                )
            )
        if win_drive_rules:
            issues.append(
                _make_issue(
                    code="ERR_EXEBOX_WINDOWS_DRIVE_PATH",
                    severity="ERROR",
                    file_id=file_id,
                    title="Windows drive path in POSIX sandbox permissions",
                    message=(
                        f"Found Windows path(s) ({', '.join(win_drive_rules[:3])}) while "
                        "Linux/macOS is selected. On Linux, filepath.IsAbs('C:/...') is "
                        "false and causes exebox initialization to fail. Enforce Windows "
                        "system paths via command(regex:...) and PreToolUse hooks."
                    ),
                    fix_label="Remove Windows drive paths from file grants",
                )
            )
        if root_sys_rules:
            issues.append(
                _make_issue(
                    code="ERR_EXEBOX_ROOT_SYSTEM_DIR",
                    severity="ERROR",
                    file_id=file_id,
                    title="Root OS directory write_file deny hides /usr/bin/bash in exebox",
                    message=(
                        f"Found {', '.join(root_sys_rules)} in deny. Linux exebox already "
                        "mounts '/' read-only; adding a deny stub mount on /usr or /bin "
                        "(a usrmerge symlink to /usr/bin) hides /usr/bin/bash."
                    ),
                    fix_label="Remove root OS directory deny stubs",
                )
            )

    # 3. Lazy-loaded MCP schema read access when non-workspace access is disabled
    has_mcp_allow = any(r.startswith("mcp(") for r in allow_list)
    if has_mcp_allow and not allow_non_workspace and posix_active:
        user_slug = dev_user.strip() or "alice"
        missing_os: list[str] = []
        if "linux" in os_list:
            expected_lin = f"read_file(/home/{user_slug}/.gemini)"
            if expected_lin not in allow_list and "read_file(/home/__DEV_USER__/.gemini)" not in allow_list and "read_file(~/.gemini)" not in allow_list:
                missing_os.append(expected_lin)
        if "macos" in os_list:
            expected_mac = f"read_file(/Users/{user_slug}/.gemini)"
            if expected_mac not in allow_list and "read_file(/Users/__DEV_USER__/.gemini)" not in allow_list and "read_file(~/.gemini)" not in allow_list:
                missing_os.append(expected_mac)
        if missing_os:
            issues.append(
                _make_issue(
                    code="WARN_MISSING_GEMINI_READ_FOR_MCP",
                    severity="WARN",
                    file_id=file_id,
                    title="Missing ~/.gemini read grant for lazy-loaded MCP schemas",
                    message=(
                        "Non-workspace file access is disabled while MCP allow rules are "
                        "configured. Lazy-loaded MCP tools inspect tool schemas under "
                        f"~/.gemini before calling call_mcp_tool. Missing: {', '.join(missing_os)}."
                    ),
                    fix_label="Add read_file(.../.gemini) allow grant",
                )
            )

    # 4. Windows PowerShell `RequiresExactMatch` check
    if "windows" in os_list:
        all_regex_rules = [
            r for r in (allow_list + ask_list) if r.startswith("command(regex:")
        ]
        bare_cmds_missing_regex: list[str] = []
        for r in allow_list:
            m = re.match(r"^command\((?!regex:)(.+)\)$", r)
            if not m:
                continue
            inner = m.group(1).strip()
            if inner == "*":
                continue
            first_word = inner.split()[0].lower()
            covered = any(first_word in reg.lower() for reg in all_regex_rules)
            if not covered:
                bare_cmds_missing_regex.append(r)

        if bare_cmds_missing_regex:
            issues.append(
                _make_issue(
                    code="WARN_WIN_POWERSHELL_EXACT_MATCH",
                    severity="WARN",
                    file_id=file_id,
                    title="Windows PowerShell RequiresExactMatch needs anchored regex grants",
                    message=(
                        f"Literal grant(s) ({', '.join(bare_cmds_missing_regex[:3])}) only "
                        "match exact zero-argument strings on Windows PowerShell because "
                        "RequiresExactMatch is always true (for example 'echo hello' will "
                        "prompt or fail). Pair literal commands with safe anchored "
                        "command(regex:...) and unsandboxed(...) companions."
                    ),
                    fix_label="Add PowerShell-safe regex & unsandboxed companions",
                )
            )

    # 5. Single-token `\s+` regex in `deny` without literal binary block
    missing_literal_bins: list[str] = []
    deny_set = set(deny_list)
    for r in deny_list:
        m = re.match(r"^command\(regex:\^\(?([a-zA-Z0-9._-]+)\\s\+", r)
        if m and " " not in r:
            bin_name = m.group(1)
            if f"command({bin_name})" not in deny_set:
                missing_literal_bins.append(bin_name)
    if missing_literal_bins:
        uniq_bins = sorted(set(missing_literal_bins))
        issues.append(
            _make_issue(
                code="WARN_SINGLE_TOKEN_REGEX_DENY",
                severity="WARN",
                file_id=file_id,
                title="Single-token \\s+ deny regex does not match multi-word commands",
                message=(
                    "SplitCommandStringToParts splits normal commands on spaces before "
                    "matching token-by-token, so a space-free '\\s+' regex only compares "
                    f"against argv[0]. Add literal command({uniq_bins[0]}) rules or "
                    "space-delimited token patterns."
                ),
                fix_label="Add companion literal command(<bin>) deny rules",
            )
        )

    return issues


def validate_single_file(
    file_id: str,
    content: str,
    os_list: list[str],
    surfaces: list[str],
    dev_user: str = "alice",
    has_bom: bool = False,
) -> list[dict[str, Any]]:
    """Validate a single canonical Antigravity file against schema & OS rules.

    Summary:
        Runs syntax, UTF-8 BOM, Preview-vs-GA schema drift, OS path/sandbox,
        surface compatibility, MCP/Hook governance, and secret-hygiene checks.
    Parameters:
        file_id (str): Canonical studio file identifier.
        content (str): Raw text of the configuration file.
        os_list (list[str]): Selected target OSes (`linux`, `macos`, `windows`).
        surfaces (list[str]): Selected AGY surfaces (`cli`, `desktop`, `web`, `ide`).
        dev_user (str): Target developer username for path expansions.
        has_bom (bool): Explicit BOM indicator when raw uploaded bytes started
            with `0xEF 0xBB 0xBF`.
    Return Value:
        list[dict[str, Any]]: Ordered list of validation findings (`ERROR` first,
        then `WARN`, then `INFO`).
    Exceptions/Errors:
        None. Malformed JSON is captured and returned as `ERR_JSON_SYNTAX`.
    """
    issues: list[dict[str, Any]] = []
    text = content or ""

    # Check 0: UTF-8 BOM detection (fatal on Windows Go `encoding/json.Unmarshal`)
    if has_bom or text.startswith("\ufeff"):
        issues.append(
            _make_issue(
                code="ERR_UTF8_BOM",
                severity="ERROR",
                file_id=file_id,
                title="UTF-8 Byte Order Mark (BOM) detected",
                message=(
                    "Leading 0xEF 0xBB 0xBF BOM bytes cause Go encoding/json.Unmarshal in "
                    "Antigravity (especially agy.exe on Windows PowerShell 5.1) to reject "
                    "the file and silently fall back to OAuth login."
                ),
                fix_label="Strip UTF-8 BOM bytes",
                line=1,
            )
        )
        text = text.lstrip("\ufeff")

    json_files = {
        "admin_settings",
        "cli_settings",
        "desktop_config",
        "mcp_config",
        "hooks_config",
        "acp_json",
        "acp_auth",
    }

    parsed_json: dict[str, Any] | None = None
    if file_id in json_files:
        try:
            loaded = json.loads(text)
            if not isinstance(loaded, dict):
                issues.append(
                    _make_issue(
                        code="ERR_JSON_ROOT_TYPE",
                        severity="ERROR",
                        file_id=file_id,
                        title="Top-level JSON value must be an object",
                        message="Antigravity configuration files require a JSON object ({}) at the root.",
                        line=1,
                    )
                )
                return issues
            parsed_json = loaded
        except json.JSONDecodeError as exc:
            issues.append(
                _make_issue(
                    code="ERR_JSON_SYNTAX",
                    severity="ERROR",
                    file_id=file_id,
                    title=f"Malformed JSON syntax (line {exc.lineno}, col {exc.colno})",
                    message=f"{exc.msg} at line {exc.lineno}, column {exc.colno}.",
                    line=exc.lineno,
                )
            )
            return issues

    # --- File-specific rules ---
    if file_id == "admin_settings" and parsed_json is not None:
        gw = parsed_json.get("gateway")
        if not isinstance(gw, dict):
            issues.append(
                _make_issue(
                    code="ERR_MISSING_GATEWAY_OBJECT",
                    severity="ERROR",
                    file_id=file_id,
                    title='Missing top-level "gateway" object',
                    message='admin_settings.json requires a top-level "gateway" object with enabled and url.',
                    fix_label='Initialize "gateway" object',
                )
            )
            gw = {}

        if gw.get("enabled") is not True:
            issues.append(
                _make_issue(
                    code="WARN_GATEWAY_DISABLED",
                    severity="WARN",
                    file_id=file_id,
                    title="gateway.enabled is not set to true",
                    message=(
                        "Unlike AGY_LLM_GATEWAY_URL in environment variables, file-based "
                        "admin_settings.json requires gateway.enabled: true to activate "
                        "Enterprise Gateway mode and suppress interactive OAuth login."
                    ),
                    fix_label="Set gateway.enabled to true",
                )
            )

        url = str(gw.get("url", "")).strip()
        if not url:
            issues.append(
                _make_issue(
                    code="ERR_MISSING_GATEWAY_URL",
                    severity="ERROR",
                    file_id=file_id,
                    title="gateway.url is empty",
                    message="Specify your HTTPS Enterprise Gateway endpoint URL (e.g., https://REPLACE_WITH_GATEWAY_URL).",
                    fix_label="Insert placeholder HTTPS Gateway URL",
                )
            )
        elif url.startswith("http://") and "localhost" not in url and "127.0.0.1" not in url:
            issues.append(
                _make_issue(
                    code="WARN_INSECURE_HTTP_GATEWAY",
                    severity="WARN",
                    file_id=file_id,
                    title="Non-TLS http:// Gateway URL on non-loopback host",
                    message="Production Enterprise Gateways should enforce TLS (https://) to protect bearer tokens in transit.",
                    fix_label="Upgrade scheme to https://",
                )
            )

        # Preview v2.0 schema drift checks
        if "caCertPath" in gw:
            issues.append(
                _make_issue(
                    code="ERR_PREVIEW_NESTED_CACERT",
                    severity="ERROR",
                    file_id=file_id,
                    title="Preview v2.0 drift: caCertPath nested inside gateway",
                    message=(
                        'Official GA Antigravity expects "caCertPath" at the top level of '
                        'admin_settings.json, not nested inside "gateway".'
                    ),
                    fix_label="Hoist caCertPath to top level",
                )
            )
        if "models" in gw or (
            isinstance(parsed_json.get("models"), dict) and "filter" in parsed_json["models"]
        ):
            issues.append(
                _make_issue(
                    code="ERR_PREVIEW_NESTED_MODELS",
                    severity="ERROR",
                    file_id=file_id,
                    title="Preview v2.0 drift: legacy models.filter / gateway.models schema",
                    message=(
                        'Official GA uses top-level "models": {"defaultModelId": "...", '
                        '"list": [{"modelId": "..."}]} rather than gateway.models or filter.'
                    ),
                    fix_label="Migrate models to GA list schema",
                )
            )
        if "auth" in parsed_json and isinstance(parsed_json.get("auth"), dict) and "suppressInteractiveLogin" in parsed_json["auth"]:
            issues.append(
                _make_issue(
                    code="WARN_PREVIEW_SUPPRESS_LOGIN",
                    severity="WARN",
                    file_id=file_id,
                    title="Deprecated auth.suppressInteractiveLogin field",
                    message=(
                        "Official GA suppresses interactive Google sign-in automatically "
                        "whenever gateway.enabled is true."
                    ),
                    fix_label="Remove deprecated auth block",
                )
            )

        wire = str(gw.get("wireProtocol", "genai")).strip() or "genai"
        if wire not in ("genai", "openai"):
            issues.append(
                _make_issue(
                    code="ERR_INVALID_WIRE_PROTOCOL",
                    severity="ERROR",
                    file_id=file_id,
                    title=f'Invalid wireProtocol "{wire}"',
                    message='gateway.wireProtocol must be "genai" (default) or "openai".',
                    fix_label='Reset wireProtocol to "genai"',
                )
            )
        elif wire == "openai" and "ide" in surfaces:
            issues.append(
                _make_issue(
                    code="ERR_ACP_OPENAI_UNSUPPORTED",
                    severity="ERROR",
                    file_id=file_id,
                    title='JetBrains & Zed ACP server does not support wireProtocol "openai"',
                    message=(
                        "AGY IDE Plugins is selected, and JetBrains/Zed ACP (agy acp 1.3.0+) "
                        'supports only wireProtocol: "genai".'
                    ),
                    fix_label='Switch wireProtocol to "genai"',
                )
            )

        ca_cert = str(parsed_json.get("caCertPath", "")).strip()
        if os_list == ["windows"] and ca_cert.startswith("/etc/"):
            issues.append(
                _make_issue(
                    code="WARN_WINDOWS_LINUX_CACERT",
                    severity="WARN",
                    file_id=file_id,
                    title="POSIX /etc/ caCertPath set on Windows-only profile",
                    message=(
                        "On Windows, leave caCertPath empty to use the OS Certificate Store "
                        "(Cert:\\LocalMachine\\Root) or specify a Windows PEM path."
                    ),
                    fix_label="Clear POSIX caCertPath for Windows OS store",
                )
            )

        if _is_live_secret_value(gw.get("apiKey")):
            issues.append(
                _make_issue(
                    code="WARN_PLAINTEXT_SECRET",
                    severity="WARN",
                    file_id=file_id,
                    title="Plaintext API key detected in gateway.apiKey",
                    message=(
                        "Avoid committing live API keys into shared policy repositories. "
                        "Replace with a template placeholder before checking into Git, or "
                        "inject per-user keys via Tier-2 environment variables."
                    ),
                    fix_label=f'Replace with "{RAW_KEY_PLACEHOLDER}"',
                )
            )

    elif file_id == "gateway_env":
        # Check JSON-formatted AGY_LLM_GATEWAY_HEADERS (Preview v2.0 drift)
        headers_match = re.search(
            r'^(?:export\s+)?AGY_LLM_GATEWAY_HEADERS=(.*)$',
            text,
            flags=re.MULTILINE,
        )
        if headers_match:
            raw_hdr = headers_match.group(1).strip().strip('"').strip("'")
            if raw_hdr.startswith("{") and raw_hdr.endswith("}"):
                issues.append(
                    _make_issue(
                        code="WARN_ENV_JSON_HEADERS",
                        severity="WARN",
                        file_id=file_id,
                        title="Preview v2.0 drift: AGY_LLM_GATEWAY_HEADERS formatted as JSON",
                        message=(
                            "Official GA parses AGY_LLM_GATEWAY_HEADERS as comma-separated "
                            "'Key: Value' pairs (e.g., 'X-Cost-Center: CC-100,X-Corporate-BU: Eng'), "
                            "not a JSON object."
                        ),
                        fix_label="Convert JSON headers to Key: Value pairs",
                    )
                )

        proto_match = re.search(
            r'^(?:export\s+)?AGY_LLM_GATEWAY_WIRE_PROTOCOL=["\']?([^"\'\s#]+)',
            text,
            flags=re.MULTILINE,
        )
        if proto_match and proto_match.group(1).strip() == "openai" and "ide" in surfaces:
            issues.append(
                _make_issue(
                    code="ERR_ACP_OPENAI_UNSUPPORTED",
                    severity="ERROR",
                    file_id=file_id,
                    title="AGY_LLM_GATEWAY_WIRE_PROTOCOL=openai is incompatible with ACP IDEs",
                    message='JetBrains and Zed ACP servers only support AGY_LLM_GATEWAY_WIRE_PROTOCOL="genai".',
                    fix_label='Switch AGY_LLM_GATEWAY_WIRE_PROTOCOL to "genai"',
                )
            )

        key_match = re.search(
            r'^(?:export\s+)?AGY_LLM_GATEWAY_API_KEY=(.*)$',
            text,
            flags=re.MULTILINE,
        )
        if key_match and _is_live_secret_value(key_match.group(1)):
            issues.append(
                _make_issue(
                    code="WARN_PLAINTEXT_SECRET",
                    severity="WARN",
                    file_id=file_id,
                    title="Plaintext token detected in AGY_LLM_GATEWAY_API_KEY",
                    message="Scrub live bearer tokens before storing .env templates in version control.",
                    fix_label=f'Replace with "{API_KEY_PLACEHOLDER}"',
                )
            )

    elif file_id == "cli_settings" and parsed_json is not None:
        valid_modes = {"", "plan", "accept-edits", "auto"}
        mode = str(parsed_json.get("agentMode", ""))
        if mode not in valid_modes:
            issues.append(
                _make_issue(
                    code="ERR_CLI_INVALID_AGENT_MODE",
                    severity="ERROR",
                    file_id=file_id,
                    title=f'Invalid agentMode "{mode}"',
                    message='agentMode must be one of "", "plan", "accept-edits", or "auto".',
                    fix_label='Set agentMode to "plan"',
                )
            )

        valid_tp = {"proceed-in-sandbox", "request-review", "strict", "always-proceed"}
        tp = str(parsed_json.get("toolPermission", "proceed-in-sandbox"))
        if tp not in valid_tp:
            issues.append(
                _make_issue(
                    code="ERR_CLI_INVALID_TOOL_PERMISSION",
                    severity="ERROR",
                    file_id=file_id,
                    title=f'Invalid toolPermission "{tp}"',
                    message='toolPermission must be "proceed-in-sandbox", "request-review", "strict", or "always-proceed".',
                    fix_label='Set toolPermission to "proceed-in-sandbox"',
                )
            )

        # sandboxProxy.http checks
        sb_proxy = parsed_json.get("sandboxProxy")
        if isinstance(sb_proxy, dict) and isinstance(sb_proxy.get("http"), dict):
            http_cfg = sb_proxy["http"]
            addr = str(http_cfg.get("address", "")).strip()
            cert = str(http_cfg.get("certFile", "")).strip()
            if bool(addr) != bool(cert):
                issues.append(
                    _make_issue(
                        code="ERR_SANDBOX_PROXY_INCOMPLETE",
                        severity="ERROR",
                        file_id=file_id,
                        title="sandboxProxy.http requires both address and certFile",
                        message="Specify both sandboxProxy.http.address and sandboxProxy.http.certFile, or omit both.",
                        fix_label="Populate missing sandboxProxy.http field",
                    )
                )
            if cert in MULTI_CERT_BUNDLE_PATHS:
                issues.append(
                    _make_issue(
                        code="ERR_SANDBOX_PROXY_MULTI_CERT_BUNDLE",
                        severity="ERROR",
                        file_id=file_id,
                        title="Multi-CA bundle path in sandboxProxy.http.certFile",
                        message=(
                            f'"{cert}" contains multiple certificates and fails startup with '
                            '"localcert: trailing data after certificate". Provide a single-certificate '
                            "corporate root CA PEM file."
                        ),
                        fix_label="Switch to single-cert PEM path (/etc/antigravity/certs/corp-root-ca.pem)",
                    )
                )
            if _is_live_secret_value(http_cfg.get("password")):
                issues.append(
                    _make_issue(
                        code="WARN_PLAINTEXT_SECRET",
                        severity="WARN",
                        file_id=file_id,
                        title="Plaintext password in sandboxProxy.http.password",
                        message="Replace live proxy passwords with a template placeholder before sharing.",
                        fix_label=f'Replace with "{PROXY_PASS_PLACEHOLDER}"',
                    )
                )

        perms = parsed_json.get("permissions")
        if isinstance(perms, dict):
            issues.extend(
                _validate_permission_grants(
                    file_id=file_id,
                    grants=perms,
                    os_list=os_list,
                    allow_non_workspace=bool(parsed_json.get("allowNonWorkspaceAccess", False)),
                    dev_user=dev_user,
                )
            )

    elif file_id == "desktop_config" and parsed_json is not None:
        us = parsed_json.get("userSettings")
        if not isinstance(us, dict):
            issues.append(
                _make_issue(
                    code="ERR_MISSING_USER_SETTINGS",
                    severity="ERROR",
                    file_id=file_id,
                    title='Missing top-level "userSettings" object in config.json',
                    message="Antigravity Desktop App and Web Hub expect settings under userSettings.",
                    fix_label='Wrap configuration inside "userSettings"',
                )
            )
        else:
            grants = us.get("globalPermissionGrants")
            allow_non_ws = (
                str(us.get("nonWorkspaceFileAccessPolicy", "")) == "NON_WORKSPACE_FILE_ACCESS_POLICY_ENABLED"
            )
            if isinstance(grants, dict):
                issues.extend(
                    _validate_permission_grants(
                        file_id=file_id,
                        grants=grants,
                        os_list=os_list,
                        allow_non_workspace=allow_non_ws,
                        dev_user=dev_user,
                    )
                )

    elif file_id == "browser_allowlist":
        bad_lines: list[str] = []
        wildcard_lines: list[str] = []
        for idx, raw_line in enumerate(text.splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "://" in stripped or "/" in stripped:
                bad_lines.append(f"line {idx}: {stripped}")
            if stripped == "*":
                wildcard_lines.append(f"line {idx}")
        if bad_lines:
            issues.append(
                _make_issue(
                    code="WARN_BROWSER_URL_SCHEME",
                    severity="WARN",
                    file_id=file_id,
                    title="browserAllowlist.txt expects hostnames/domains, not full URLs",
                    message=(
                        f"Found URL scheme or path on {', '.join(bad_lines[:3])}. "
                        "List bare hostnames such as docs.cloud.google.com."
                    ),
                    fix_label="Strip URL schemes and paths",
                )
            )
        if wildcard_lines:
            issues.append(
                _make_issue(
                    code="WARN_BROWSER_WILDCARD_ALL",
                    severity="WARN",
                    file_id=file_id,
                    title="Wildcard '*' allows unrestricted browser subagent navigation",
                    message="Remove '*' from browserAllowlist.txt to restrict browsing to approved enterprise domains.",
                    fix_label="Remove '*' wildcard entry",
                )
            )

    elif file_id == "mcp_config" and parsed_json is not None:
        servers = parsed_json.get("mcpServers")
        if not isinstance(servers, dict):
            issues.append(
                _make_issue(
                    code="ERR_MISSING_MCP_SERVERS",
                    severity="ERROR",
                    file_id=file_id,
                    title='Missing "mcpServers" object in mcp_config.json',
                    message='mcp_config.json must define a top-level "mcpServers" dictionary.',
                    fix_label='Initialize "mcpServers" dictionary',
                )
            )
        else:
            invalid_tools_servers: list[str] = []
            eager_servers: list[str] = []
            enabled_example_servers: list[str] = []
            secret_env_servers: list[str] = []

            for srv_name, srv_cfg in servers.items():
                if not isinstance(srv_cfg, dict):
                    continue
                tools_cfg = srv_cfg.get("tools")
                if isinstance(tools_cfg, dict):
                    if isinstance(tools_cfg.get("eager"), list):
                        invalid_tools_servers.append(srv_name)
                    else:
                        for _, t_meta in tools_cfg.items():
                            if isinstance(t_meta, dict) and t_meta.get("eager") is True:
                                eager_servers.append(srv_name)
                                break

                srv_url = str(srv_cfg.get("serverUrl") or srv_cfg.get("url") or "")
                if "example.com" in srv_url and srv_cfg.get("disabled") is not True:
                    enabled_example_servers.append(srv_name)

                env_map = srv_cfg.get("env")
                if isinstance(env_map, dict):
                    for env_k, env_v in env_map.items():
                        if any(tok in env_k.upper() for tok in ("KEY", "TOKEN", "SECRET", "PASSWORD")) and _is_live_secret_value(env_v):
                            secret_env_servers.append(f"{srv_name}.{env_k}")

            if invalid_tools_servers:
                issues.append(
                    _make_issue(
                        code="ERR_MCP_INVALID_TOOLS_SCHEMA",
                        severity="ERROR",
                        file_id=file_id,
                        title="Invalid tools.eager array breaks MCP config unmarshaling",
                        message=(
                            f"Server(s) {', '.join(invalid_tools_servers)} use 'tools': {{'eager': [...]}} "
                            "which fails Go cortexmcp.McpServer JSON unmarshaling and drops the server."
                        ),
                        fix_label="Remove invalid tools.eager array",
                    )
                )
            if eager_servers:
                issues.append(
                    _make_issue(
                        code="WARN_MCP_EAGER_BYPASS",
                        severity="WARN",
                        file_id=file_id,
                        title='MCP "eager: true" tools bypass permissions.deny mcp(...) rules',
                        message=(
                            f"Server(s) {', '.join(sorted(set(eager_servers)))} set eager: true. "
                            "Antigravity enforces mcp(<server>/<tool>) grants inside call_mcp_tool "
                            "(default lazy mode); eager tools register direct mcp_<server>_<tool> "
                            "functions that bypass permissions.deny unless gated by PreToolUse hooks."
                        ),
                        fix_label="Switch MCP tools to governed lazy mode",
                    )
                )
            if enabled_example_servers:
                issues.append(
                    _make_issue(
                        code="WARN_MCP_EXAMPLE_URL_ENABLED",
                        severity="WARN",
                        file_id=file_id,
                        title="Placeholder example.com MCP server is enabled",
                        message=(
                            f"Server(s) {', '.join(enabled_example_servers)} point to example.com "
                            "without 'disabled: true', causing connection timeouts on startup."
                        ),
                        fix_label='Set "disabled": true on example.com servers',
                    )
                )
            if secret_env_servers:
                issues.append(
                    _make_issue(
                        code="WARN_PLAINTEXT_SECRET",
                        severity="WARN",
                        file_id=file_id,
                        title="Plaintext credential in MCP server env block",
                        message=f"Found live-looking secret(s) in {', '.join(secret_env_servers)}.",
                        fix_label="Replace MCP env secrets with placeholders",
                    )
                )

    elif file_id == "hooks_config" and parsed_json is not None:
        hooks = parsed_json.get("hooks")
        if not isinstance(hooks, dict):
            issues.append(
                _make_issue(
                    code="ERR_MISSING_HOOKS_OBJECT",
                    severity="ERROR",
                    file_id=file_id,
                    title='Missing top-level "hooks" object in hooks.json',
                    message='hooks.json requires a top-level "hooks" dictionary (PreToolUse, PostToolUse, SessionStart).',
                    fix_label='Initialize "hooks" dictionary',
                )
            )
        else:
            if ".toolCall.toolName" in text:
                issues.append(
                    _make_issue(
                        code="ERR_HOOK_LEGACY_TOOLNAME",
                        severity="ERROR",
                        file_id=file_id,
                        title="Invalid jq path .toolCall.toolName in hook command",
                        message=(
                            'Antigravity PreToolUse/PostToolUse stdin passes {"toolCall":{"name":"...","args":{...}}}. '
                            "Use .toolCall.name instead of .toolCall.toolName."
                        ),
                        fix_label="Replace .toolCall.toolName with .toolCall.name",
                    )
                )

            pre_list = hooks.get("PreToolUse", [])
            if isinstance(pre_list, list):
                for entry in pre_list:
                    if not isinstance(entry, dict):
                        continue
                    matcher = str(entry.get("matcher", ""))
                    if ("write_file" in matcher or "edit_file" in matcher) and "sed_file" not in matcher and matcher != ".*":
                        issues.append(
                            _make_issue(
                                code="WARN_HOOK_MISSING_SED_FILE",
                                severity="WARN",
                                file_id=file_id,
                                title="File-write PreToolUse matcher omits sed_file",
                                message=(
                                    f'Matcher "{matcher}" inspects file writes/edits without sed_file, '
                                    "allowing agents to modify files via sed_file without DLP inspection."
                                ),
                                fix_label="Include sed_file in PreToolUse matcher",
                            )
                        )
                    for h_cmd in entry.get("hooks", []) if isinstance(entry.get("hooks"), list) else []:
                        if not isinstance(h_cmd, dict):
                            continue
                        cmd_str = str(h_cmd.get("command", ""))
                        if re.search(r'-File\s+"[A-Za-z]:\\', cmd_str):
                            issues.append(
                                _make_issue(
                                    code="WARN_HOOK_WIN_QUOTED_PATH",
                                    severity="WARN",
                                    file_id=file_id,
                                    title="Inner quotes around PowerShell -File path on Windows",
                                    message=(
                                        "On Windows, invoke 'powershell.exe -NoProfile -ExecutionPolicy Bypass "
                                        "-File C:\\ProgramData\\Antigravity\\bin\\agy_security_guard.ps1 pre' "
                                        "without inner quotes around the -File path."
                                    ),
                                    fix_label="Remove inner quotes around -File path",
                                )
                            )
                        if os_list == ["windows"] and cmd_str.strip().startswith("/usr/local/bin/"):
                            issues.append(
                                _make_issue(
                                    code="WARN_HOOK_POSIX_CMD_ON_WINDOWS",
                                    severity="WARN",
                                    file_id=file_id,
                                    title="POSIX /usr/local/bin hook command on Windows-only profile",
                                    message="Switch hooks.json command to powershell.exe -File C:\\ProgramData\\Antigravity\\bin\\agy_security_guard.ps1.",
                                    fix_label="Switch hook command to Windows PowerShell guard",
                                )
                            )

    elif file_id in ("guard_sh", "guard_ps1"):
        if ".toolCall.toolName" in text or "$payload.toolCall.toolName" in text:
            issues.append(
                _make_issue(
                    code="ERR_HOOK_LEGACY_TOOLNAME",
                    severity="ERROR",
                    file_id=file_id,
                    title="Legacy toolCall.toolName field referenced in guard script",
                    message="Antigravity hook payloads provide toolCall.name rather than toolCall.toolName.",
                    fix_label="Replace toolCall.toolName with toolCall.name",
                )
            )

    elif file_id == "acp_json" and parsed_json is not None:
        servers = parsed_json.get("agent_servers")
        if not isinstance(servers, dict) or not isinstance(servers.get("Antigravity"), dict):
            issues.append(
                _make_issue(
                    code="ERR_ACP_MISSING_SERVER",
                    severity="ERROR",
                    file_id=file_id,
                    title='Missing agent_servers.Antigravity block in acp.json',
                    message="JetBrains and Zed require agent_servers.Antigravity with command, args: ['acp'], and env.",
                    fix_label="Initialize agent_servers.Antigravity block",
                )
            )
        else:
            agy_srv = servers["Antigravity"]
            env_cfg = agy_srv.get("env") if isinstance(agy_srv.get("env"), dict) else {}
            if str(env_cfg.get("AGY_LLM_GATEWAY_WIRE_PROTOCOL", "genai")).strip() == "openai":
                issues.append(
                    _make_issue(
                        code="ERR_ACP_OPENAI_UNSUPPORTED",
                        severity="ERROR",
                        file_id=file_id,
                        title="ACP server only supports AGY_LLM_GATEWAY_WIRE_PROTOCOL=genai",
                        message='JetBrains & Zed ACP (1.3.0+) rejects wireProtocol "openai". Use "genai".',
                        fix_label='Switch AGY_LLM_GATEWAY_WIRE_PROTOCOL to "genai"',
                    )
                )
            if _is_live_secret_value(env_cfg.get("AGY_LLM_GATEWAY_API_KEY")):
                issues.append(
                    _make_issue(
                        code="WARN_PLAINTEXT_SECRET",
                        severity="WARN",
                        file_id=file_id,
                        title="Plaintext API key in acp.json env.AGY_LLM_GATEWAY_API_KEY",
                        message="Replace live API keys with REPLACE_WITH_GATEWAY_API_KEY before sharing.",
                        fix_label=f'Replace with "{RAW_KEY_PLACEHOLDER}"',
                    )
                )

    elif file_id == "acp_auth" and parsed_json is not None:
        auth_obj = parsed_json.get("auth")
        if not isinstance(auth_obj, dict) or auth_obj.get("type") != "gateway":
            issues.append(
                _make_issue(
                    code="ERR_ACP_AUTH_TYPE",
                    severity="ERROR",
                    file_id=file_id,
                    title='antigravity-acp/settings.json must set auth.type = "gateway"',
                    message='Without {"auth": {"type": "gateway"}}, JetBrains and Zed ACP servers prompt for consumer login.',
                    fix_label='Set {"auth": {"type": "gateway"}}',
                )
            )

    severity_rank = {"ERROR": 0, "WARN": 1, "INFO": 2}
    issues.sort(key=lambda item: (severity_rank.get(item["severity"], 9), item["code"]))
    return issues


def validate_bundle(
    files_map: dict[str, str],
    os_list: list[str],
    surfaces: list[str],
    dev_user: str = "alice",
    bom_map: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Validate all active configuration files and cross-file governance rules.

    Summary:
        Executes `validate_single_file` across every file in `files_map`, adds
        cross-file consistency checks (such as Web Hub vs. SaaS note or CLI vs.
        Desktop permission drift), and computes summary counts per file and
        across the entire bundle.
    Parameters:
        files_map (dict[str, str]): Map of `file_id -> raw_text`.
        os_list (list[str]): Selected target OSes (`linux`, `macos`, `windows`).
        surfaces (list[str]): Selected surfaces (`cli`, `desktop`, `web`, `ide`).
        dev_user (str): Target workstation developer username.
        bom_map (dict[str, bool] | None): Optional map flagging files whose
            uploaded bytes contained a leading UTF-8 BOM.
    Return Value:
        dict[str, Any]: Summary object containing `overall_status` (`PASS`,
        `WARN`, `ERROR`), `error_count`, `warn_count`, `issues_by_file`, and
        `all_issues`.
    Exceptions/Errors:
        None.
    """
    boms = bom_map or {}
    issues_by_file: dict[str, list[dict[str, Any]]] = {}
    all_issues: list[dict[str, Any]] = []

    for fid, raw_content in files_map.items():
        file_issues = validate_single_file(
            file_id=fid,
            content=raw_content,
            os_list=os_list,
            surfaces=surfaces,
            dev_user=dev_user,
            has_bom=bool(boms.get(fid, False)),
        )
        issues_by_file[fid] = file_issues
        all_issues.extend(file_issues)

    # Informational surface note when AGY Web Hub is selected
    if "web" in surfaces and "desktop_config" in issues_by_file:
        web_note = _make_issue(
            code="INFO_WEB_HUB_SCOPE",
            severity="INFO",
            file_id="desktop_config",
            title="Web surface targets self-hosted Antigravity Web Hub (agy --hub)",
            message=(
                "Enterprise Gateway mode supports self-hosted Antigravity Web Hub "
                "(agy --hub / :4400 reading ~/.gemini/config/config.json). Consumer "
                "hosted antigravity.google SaaS web is not used in Gateway mode."
            ),
        )
        issues_by_file["desktop_config"].append(web_note)
        all_issues.append(web_note)

    error_count = sum(1 for item in all_issues if item["severity"] == "ERROR")
    warn_count = sum(1 for item in all_issues if item["severity"] == "WARN")
    fixable_count = sum(1 for item in all_issues if item.get("fixable"))

    if error_count > 0:
        overall = "ERROR"
    elif warn_count > 0:
        overall = "WARN"
    else:
        overall = "PASS"

    file_status: dict[str, str] = {}
    for fid, f_issues in issues_by_file.items():
        if any(i["severity"] == "ERROR" for i in f_issues):
            file_status[fid] = "ERROR"
        elif any(i["severity"] == "WARN" for i in f_issues):
            file_status[fid] = "WARN"
        else:
            file_status[fid] = "PASS"

    return {
        "overall_status": overall,
        "error_count": error_count,
        "warn_count": warn_count,
        "fixable_count": fixable_count,
        "file_status": file_status,
        "issues_by_file": issues_by_file,
        "all_issues": all_issues,
    }


def _autofix_permission_grants(
    grants: dict[str, Any],
    issue_code: str,
    os_list: list[str],
    dev_user: str,
) -> None:
    """Mutate a `permissions` or `globalPermissionGrants` dict to fix an issue.

    Summary:
        Applies targeted deterministic repairs for permission grant validation
        codes (`ERR_DENY_UNSANDBOXED_WILDCARD`, `ERR_EXEBOX_*`,
        `WARN_MISSING_GEMINI_READ_FOR_MCP`, `WARN_WIN_POWERSHELL_EXACT_MATCH`,
        and `WARN_SINGLE_TOKEN_REGEX_DENY`).
    Parameters:
        grants (dict[str, Any]): Mutable grant dictionary (`allow`, `ask`, `deny`).
        issue_code (str): Validation code to remediate.
        os_list (list[str]): Active OS list.
        dev_user (str): Workstation username for path expansion.
    Return Value:
        None. Mutates `grants` in-place.
    Exceptions/Errors:
        None.
    """
    allow_list = [str(x) for x in grants.get("allow", []) if isinstance(x, str)]
    ask_list = [str(x) for x in grants.get("ask", []) if isinstance(x, str)]
    deny_list = [str(x) for x in grants.get("deny", []) if isinstance(x, str)]
    user_slug = dev_user.strip() or "alice"

    if issue_code == "ERR_DENY_UNSANDBOXED_WILDCARD":
        deny_list = [r for r in deny_list if r != "unsandboxed(*)"]

    elif issue_code == "ERR_EXEBOX_GLOB_PATH":
        def _clean_glob(rules: list[str]) -> list[str]:
            cleaned: list[str] = []
            for r in rules:
                verb, target = _extract_file_rule_target(r)
                if verb and target and target != "*" and ("*" in target or "?" in target):
                    # Keep parent directory if safe non-root prefix, else drop (hook enforces globs)
                    prefix = re.split(r"[*?]", target, maxsplit=1)[0].rstrip("/")
                    if prefix and prefix not in ("", "/", "/etc", "/usr", "/bin", "/sbin", "/home", "/Users"):
                        cleaned.append(f"{verb}({prefix})")
                else:
                    cleaned.append(r)
            return list(dict.fromkeys(cleaned))

        allow_list = _clean_glob(allow_list)
        ask_list = _clean_glob(ask_list)
        deny_list = _clean_glob(deny_list)

    elif issue_code == "ERR_EXEBOX_RELATIVE_PATH":
        def _fix_rel(rules: list[str]) -> list[str]:
            fixed: list[str] = []
            for r in rules:
                verb, target = _extract_file_rule_target(r)
                if verb and target and target != "*" and not (
                    target.startswith("/") or target.startswith("~/") or re.match(r"^[A-Za-z]:[\\/]", target)
                ):
                    clean_rel = target.lstrip("./")
                    fixed.append(f"{verb}(/home/{user_slug}/workspace/{clean_rel})")
                else:
                    fixed.append(r)
            return list(dict.fromkeys(fixed))

        allow_list = _fix_rel(allow_list)
        ask_list = _fix_rel(ask_list)
        deny_list = _fix_rel(deny_list)

    elif issue_code == "ERR_EXEBOX_WINDOWS_DRIVE_PATH":
        def _strip_win(rules: list[str]) -> list[str]:
            return [
                r
                for r in rules
                if not (
                    _extract_file_rule_target(r)[1]
                    and (
                        re.match(r"^[A-Za-z]:[\\/]", _extract_file_rule_target(r)[1] or "")
                        or "\\" in (_extract_file_rule_target(r)[1] or "")
                    )
                )
            ]

        allow_list = _strip_win(allow_list)
        ask_list = _strip_win(ask_list)
        deny_list = _strip_win(deny_list)

    elif issue_code == "ERR_EXEBOX_ROOT_SYSTEM_DIR":
        filtered_deny: list[str] = []
        for r in deny_list:
            verb, target = _extract_file_rule_target(r)
            if verb == "write_file" and target and (target.rstrip("/") or "/") in LINUX_ROOT_SYSTEM_DIRS:
                continue
            filtered_deny.append(r)
        deny_list = filtered_deny

    elif issue_code == "WARN_MISSING_GEMINI_READ_FOR_MCP":
        if "linux" in os_list:
            rule_lin = f"read_file(/home/{user_slug}/.gemini)"
            if rule_lin not in allow_list:
                allow_list.append(rule_lin)
        if "macos" in os_list:
            rule_mac = f"read_file(/Users/{user_slug}/.gemini)"
            if rule_mac not in allow_list:
                allow_list.append(rule_mac)

    elif issue_code == "WARN_WIN_POWERSHELL_EXACT_MATCH":
        new_allow = list(allow_list)
        for r in allow_list:
            m = re.match(r"^command\((?!regex:)(.+)\)$", r)
            if not m:
                continue
            inner = m.group(1).strip()
            comp = _build_windows_ps_companion(inner)
            if comp and comp not in new_allow:
                new_allow.append(comp)
            unsb = f"unsandboxed({inner})"
            if os_list == ["windows"] and unsb not in new_allow:
                new_allow.append(unsb)
            if os_list == ["windows"] and comp:
                unsb_regex = comp.replace("command(regex:", "unsandboxed(regex:", 1)
                if unsb_regex not in new_allow:
                    new_allow.append(unsb_regex)
        allow_list = new_allow

    elif issue_code == "WARN_SINGLE_TOKEN_REGEX_DENY":
        additions: list[str] = []
        deny_set = set(deny_list)
        for r in deny_list:
            m = re.match(r"^command\(regex:\^\(?([a-zA-Z0-9._-]+)\\s\+", r)
            if m and " " not in r:
                lit = f"command({m.group(1)})"
                if lit not in deny_set and lit not in additions:
                    additions.append(lit)
        deny_list = additions + deny_list

    grants["allow"] = allow_list
    grants["ask"] = ask_list
    grants["deny"] = deny_list


def apply_autofix(
    file_id: str,
    content: str,
    issue_code: str,
    os_list: list[str],
    surfaces: list[str],
    dev_user: str = "alice",
) -> str:
    """Apply a single deterministic Auto-Fix or `'ALL'` fixes to a config file.

    Summary:
        Repairs schema drift, BOM bytes, sandbox/exebox/PowerShell permission
        footguns, MCP eager/example warnings, hook matchers, or plaintext
        secrets while preserving user formatting and custom keys.
    Parameters:
        file_id (str): Canonical studio file identifier.
        content (str): Current raw file text.
        issue_code (str): Specific validation `code` or `"ALL"`.
        os_list (list[str]): Active OS identifiers (`linux`, `macos`, `windows`).
        surfaces (list[str]): Active AGY surfaces (`cli`, `desktop`, `web`, `ide`).
        dev_user (str): Workstation username for path expansion.
    Return Value:
        str: Remediated BOM-free UTF-8 configuration text.
    Exceptions/Errors:
        None. Returns original text unchanged if JSON is syntactically invalid
        and cannot be parsed.
    """
    text = content or ""

    if issue_code == "ALL":
        text = text.lstrip("\ufeff")
        for _ in range(12):
            current_issues = validate_single_file(
                file_id=file_id,
                content=text,
                os_list=os_list,
                surfaces=surfaces,
                dev_user=dev_user,
                has_bom=False,
            )
            fixable = [i for i in current_issues if i.get("fixable")]
            if not fixable:
                break
            next_text = apply_autofix(
                file_id=file_id,
                content=text,
                issue_code=fixable[0]["code"],
                os_list=os_list,
                surfaces=surfaces,
                dev_user=dev_user,
            )
            if next_text == text:
                break
            text = next_text
        return text

    if issue_code == "ERR_UTF8_BOM":
        return text.lstrip("\ufeff")

    text = text.lstrip("\ufeff")

    # Non-JSON file fixes
    if file_id == "gateway_env":
        if issue_code == "WARN_ENV_JSON_HEADERS":
            def _replace_json_headers(match: re.Match[str]) -> str:
                prefix = "export " if match.group(0).lstrip().startswith("export ") else ""
                raw_val = match.group(1).strip().strip('"').strip("'")
                try:
                    hdr_dict = json.loads(raw_val)
                    if isinstance(hdr_dict, dict):
                        kv = ",".join(f"{k}: {v}" for k, v in hdr_dict.items())
                        return f'{prefix}AGY_LLM_GATEWAY_HEADERS="{kv}"'
                except json.JSONDecodeError:
                    pass
                return match.group(0)

            return re.sub(
                r'^(?:export\s+)?AGY_LLM_GATEWAY_HEADERS=(.*)$',
                _replace_json_headers,
                text,
                flags=re.MULTILINE,
            )
        if issue_code == "ERR_ACP_OPENAI_UNSUPPORTED":
            return re.sub(
                r'^((?:export\s+)?AGY_LLM_GATEWAY_WIRE_PROTOCOL=).*$',
                r'\1"genai"',
                text,
                flags=re.MULTILINE,
            )
        if issue_code == "WARN_PLAINTEXT_SECRET":
            return re.sub(
                r'^((?:export\s+)?AGY_LLM_GATEWAY_API_KEY=).*$',
                f'\\1"{API_KEY_PLACEHOLDER}"',
                text,
                flags=re.MULTILINE,
            )
        return text

    if file_id == "browser_allowlist":
        lines = text.splitlines()
        out_lines: list[str] = []
        for ln in lines:
            st = ln.strip()
            if not st or st.startswith("#"):
                out_lines.append(ln)
                continue
            if issue_code == "WARN_BROWSER_WILDCARD_ALL" and st == "*":
                continue
            if issue_code == "WARN_BROWSER_URL_SCHEME":
                cleaned = re.sub(r"^[a-zA-Z]+://", "", st).split("/")[0].strip()
                if cleaned:
                    out_lines.append(cleaned)
                continue
            out_lines.append(ln)
        return "\n".join(out_lines) + "\n"

    if file_id in ("guard_sh", "guard_ps1"):
        if issue_code == "ERR_HOOK_LEGACY_TOOLNAME":
            return text.replace(".toolCall.toolName", ".toolCall.name").replace(
                "$payload.toolCall.toolName", "$payload.toolCall.name"
            )
        return text

    # JSON-based file fixes
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return text
    if not isinstance(data, dict):
        return text

    if file_id == "admin_settings":
        gw = data.setdefault("gateway", {})
        if not isinstance(gw, dict):
            gw = {}
            data["gateway"] = gw

        if issue_code == "ERR_MISSING_GATEWAY_OBJECT":
            gw.setdefault("enabled", True)
            gw.setdefault("url", "https://REPLACE_WITH_GATEWAY_URL")
            gw.setdefault("wireProtocol", "genai")
        elif issue_code == "WARN_GATEWAY_DISABLED":
            gw["enabled"] = True
        elif issue_code == "ERR_MISSING_GATEWAY_URL":
            gw["url"] = "https://REPLACE_WITH_GATEWAY_URL"
        elif issue_code == "WARN_INSECURE_HTTP_GATEWAY":
            gw["url"] = re.sub(r"^http://", "https://", str(gw.get("url", "")))
        elif issue_code == "ERR_PREVIEW_NESTED_CACERT":
            nested_ca = gw.pop("caCertPath", None)
            if nested_ca and "caCertPath" not in data:
                data["caCertPath"] = nested_ca
        elif issue_code == "ERR_PREVIEW_NESTED_MODELS":
            legacy_models = gw.pop("models", None) or data.get("models", {})
            raw_ids: list[str] = []
            default_id = "gemini-3.8-flash"
            if isinstance(legacy_models, dict):
                default_id = str(legacy_models.get("defaultModelId") or legacy_models.get("default") or "gemini-3.8-flash")
                filt = legacy_models.get("filter") or legacy_models.get("list") or []
                if isinstance(filt, list):
                    for item in filt:
                        if isinstance(item, str):
                            raw_ids.append(item)
                        elif isinstance(item, dict) and item.get("modelId"):
                            raw_ids.append(str(item["modelId"]))
            if not raw_ids:
                raw_ids = ["gemini-3.8-flash", "gemini-3.1-pro-preview", "gemini-3.1-flash-lite"]
            data["models"] = {
                "defaultModelId": default_id,
                "list": [{"modelId": mid} for mid in raw_ids],
            }
        elif issue_code == "WARN_PREVIEW_SUPPRESS_LOGIN":
            if isinstance(data.get("auth"), dict):
                data["auth"].pop("suppressInteractiveLogin", None)
                if not data["auth"]:
                    data.pop("auth", None)
            gw["enabled"] = True
        elif issue_code in ("ERR_INVALID_WIRE_PROTOCOL", "ERR_ACP_OPENAI_UNSUPPORTED"):
            gw["wireProtocol"] = "genai"
        elif issue_code == "WARN_WINDOWS_LINUX_CACERT":
            data.pop("caCertPath", None)
        elif issue_code == "WARN_PLAINTEXT_SECRET":
            gw["apiKey"] = RAW_KEY_PLACEHOLDER

    elif file_id == "cli_settings":
        if issue_code == "ERR_CLI_INVALID_AGENT_MODE":
            data["agentMode"] = "plan"
        elif issue_code == "ERR_CLI_INVALID_TOOL_PERMISSION":
            data["toolPermission"] = "proceed-in-sandbox"
        elif issue_code == "ERR_SANDBOX_PROXY_INCOMPLETE":
            http_cfg = data.setdefault("sandboxProxy", {}).setdefault("http", {})
            http_cfg.setdefault("address", "http://proxy.internal.example.com:3128")
            http_cfg.setdefault("certFile", "/etc/antigravity/certs/corp-root-ca.pem")
        elif issue_code == "ERR_SANDBOX_PROXY_MULTI_CERT_BUNDLE":
            http_cfg = data.setdefault("sandboxProxy", {}).setdefault("http", {})
            http_cfg["certFile"] = "/etc/antigravity/certs/corp-root-ca.pem"
        elif issue_code == "WARN_PLAINTEXT_SECRET":
            http_cfg = data.get("sandboxProxy", {}).get("http", {})
            if isinstance(http_cfg, dict) and "password" in http_cfg:
                http_cfg["password"] = PROXY_PASS_PLACEHOLDER
        else:
            perms = data.setdefault("permissions", {"allow": [], "ask": [], "deny": []})
            if isinstance(perms, dict):
                _autofix_permission_grants(perms, issue_code, os_list, dev_user)
                if issue_code == "ERR_DENY_UNSANDBOXED_WILDCARD":
                    data["enableTerminalSandbox"] = True
                    data["toolPermission"] = "proceed-in-sandbox"

    elif file_id == "desktop_config":
        if issue_code == "ERR_MISSING_USER_SETTINGS":
            existing = dict(data)
            data.clear()
            data["userSettings"] = existing or {
                "autoExecutionPolicy": "CASCADE_COMMANDS_AUTO_EXECUTION_PROCEED_IN_SANDBOX",
                "enableTerminalSandbox": True,
                "globalPermissionGrants": {"allow": [], "ask": [], "deny": []},
            }
        else:
            us = data.setdefault("userSettings", {})
            grants = us.setdefault("globalPermissionGrants", {"allow": [], "ask": [], "deny": []})
            if isinstance(grants, dict):
                _autofix_permission_grants(grants, issue_code, os_list, dev_user)
                if issue_code == "ERR_DENY_UNSANDBOXED_WILDCARD":
                    us["enableTerminalSandbox"] = True
                    us["autoExecutionPolicy"] = "CASCADE_COMMANDS_AUTO_EXECUTION_PROCEED_IN_SANDBOX"

    elif file_id == "mcp_config":
        if issue_code == "ERR_MISSING_MCP_SERVERS":
            data["mcpServers"] = {}
        else:
            servers = data.get("mcpServers", {})
            if isinstance(servers, dict):
                for srv_cfg in servers.values():
                    if not isinstance(srv_cfg, dict):
                        continue
                    if issue_code == "ERR_MCP_INVALID_TOOLS_SCHEMA":
                        if isinstance(srv_cfg.get("tools"), dict) and isinstance(srv_cfg["tools"].get("eager"), list):
                            srv_cfg.pop("tools", None)
                    elif issue_code == "WARN_MCP_EAGER_BYPASS":
                        if isinstance(srv_cfg.get("tools"), dict):
                            for t_meta in srv_cfg["tools"].values():
                                if isinstance(t_meta, dict) and t_meta.get("eager") is True:
                                    t_meta["eager"] = False
                            srv_cfg.pop("tools", None)
                    elif issue_code == "WARN_MCP_EXAMPLE_URL_ENABLED":
                        srv_url = str(srv_cfg.get("serverUrl") or srv_cfg.get("url") or "")
                        if "example.com" in srv_url:
                            srv_cfg["disabled"] = True
                    elif issue_code == "WARN_PLAINTEXT_SECRET":
                        env_map = srv_cfg.get("env")
                        if isinstance(env_map, dict):
                            for ek, ev in list(env_map.items()):
                                if any(tok in ek.upper() for tok in ("KEY", "TOKEN", "SECRET", "PASSWORD")) and _is_live_secret_value(ev):
                                    env_map[ek] = f"${{REPLACE_WITH_{ek.upper()}}}"

    elif file_id == "hooks_config":
        if issue_code == "ERR_MISSING_HOOKS_OBJECT":
            data["hooks"] = {"PreToolUse": [], "PostToolUse": []}
        elif issue_code == "ERR_HOOK_LEGACY_TOOLNAME":
            raw_fixed = json.dumps(data, indent=2).replace(".toolCall.toolName", ".toolCall.name")
            return raw_fixed + "\n"
        else:
            hooks = data.get("hooks", {})
            if isinstance(hooks, dict) and isinstance(hooks.get("PreToolUse"), list):
                for entry in hooks["PreToolUse"]:
                    if not isinstance(entry, dict):
                        continue
                    if issue_code == "WARN_HOOK_MISSING_SED_FILE":
                        m_str = str(entry.get("matcher", ""))
                        if ("write_file" in m_str or "edit_file" in m_str) and "sed_file" not in m_str:
                            if m_str.startswith("^(") and m_str.endswith(")$"):
                                inner = m_str[2:-2]
                                entry["matcher"] = f"^({inner}|sed_file)$"
                            else:
                                entry["matcher"] = f"{m_str}|sed_file"
                    for h_cmd in entry.get("hooks", []) if isinstance(entry.get("hooks"), list) else []:
                        if not isinstance(h_cmd, dict):
                            continue
                        cmd_str = str(h_cmd.get("command", ""))
                        if issue_code == "WARN_HOOK_WIN_QUOTED_PATH":
                            h_cmd["command"] = re.sub(
                                r'-File\s+"([^"]+)"',
                                r"-File \1",
                                cmd_str,
                            )
                        elif issue_code == "WARN_HOOK_POSIX_CMD_ON_WINDOWS":
                            h_cmd["command"] = (
                                "powershell.exe -NoProfile -ExecutionPolicy Bypass "
                                "-File C:\\ProgramData\\Antigravity\\bin\\agy_security_guard.ps1 pre"
                            )

    elif file_id == "acp_json":
        if issue_code == "ERR_ACP_MISSING_SERVER":
            data["agent_servers"] = {
                "Antigravity": {
                    "command": "/usr/local/bin/agy",
                    "args": ["acp"],
                    "env": {
                        "AGY_LLM_GATEWAY_URL": "https://REPLACE_WITH_GATEWAY_URL",
                        "AGY_LLM_GATEWAY_API_KEY": RAW_KEY_PLACEHOLDER,
                        "AGY_LLM_GATEWAY_WIRE_PROTOCOL": "genai",
                    },
                }
            }
        else:
            agy_srv = data.setdefault("agent_servers", {}).setdefault("Antigravity", {})
            env_cfg = agy_srv.setdefault("env", {})
            if issue_code == "ERR_ACP_OPENAI_UNSUPPORTED":
                env_cfg["AGY_LLM_GATEWAY_WIRE_PROTOCOL"] = "genai"
            elif issue_code == "WARN_PLAINTEXT_SECRET":
                env_cfg["AGY_LLM_GATEWAY_API_KEY"] = RAW_KEY_PLACEHOLDER

    elif file_id == "acp_auth":
        if issue_code == "ERR_ACP_AUTH_TYPE":
            data["auth"] = {"type": "gateway"}

    return json.dumps(data, indent=2) + "\n"
