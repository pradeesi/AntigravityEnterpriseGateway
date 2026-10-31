# ==============================================================================
# FILE HEADER: Studio State, Two-Way Sync, Presets & MDM Bundle Engine
# ==============================================================================
# Purpose:
#   Manages the canonical catalog of all 8 Antigravity admin configuration
#   groups, starter presets/recipes, two-way synchronization between structured
#   UI form state and raw configuration text (preserving custom JSON keys),
#   OS-specific kernel lock CLI generation, and BOM-free MDM `.zip` packaging.
#
# Architecture / Context:
#   Stateless domain engine imported by `app.py` and paired with
#   `validator_engine.py`. Reads sibling `../agy-config/configs/` baseline files
#   read-only when present, while maintaining full embedded fallbacks so Docker,
#   Cloud Run, and GKE containers run standalone without external volume mounts.
#
# Dependencies / Side Effects:
#   Uses Python 3.11+ standard library modules (`copy`, `io`, `json`, `os`,
#   `pathlib`, `re`, `zipfile`) plus `validator_engine`. Zero disk writes.
# ==============================================================================

from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import re
from typing import Any
import zipfile

from validator_engine import detect_file_type, validate_bundle

ALL_OS = ["linux", "macos", "windows"]
ALL_SURFACES = ["cli", "desktop", "web", "ide"]

SURFACE_LABELS = {
    "cli": "AGY CLI",
    "desktop": "AGY Desktop",
    "web": "AGY Web Hub",
    "ide": "AGY IDE Plugins",
}

OS_LABELS = {
    "linux": "Linux",
    "macos": "macOS",
    "windows": "Windows",
}

# ==============================================================================
# BLOCK 1: CANONICAL 8-GROUP ANTIGRAVITY CONFIGURATION CATALOG
# ==============================================================================
FILE_CATALOG: list[dict[str, Any]] = [
    {
        "id": "admin_settings",
        "group_code": "01",
        "group_title": "Tier-1 MDM Gateway & Models",
        "filename": "admin_settings.json",
        "short_label": "01 · admin_settings.json",
        "language": "json",
        "os": ["linux", "macos", "windows"],
        "surfaces": ["cli", "desktop", "web", "ide"],
        "surface_details": [
            "AGY CLI (1.2.15+)",
            "AGY Desktop App (2.15.0+)",
            "AGY Web Hub (agy --hub)",
            "VS Code & Visual Studio",
            "JetBrains IDEs & Zed (ACP 1.3.0+)",
        ],
        "doc_title": "Configure an Enterprise Gateway (Google Cloud Docs)",
        "doc_url": "https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/deploy-enterprise-gateway?hl=en",
        "mandatory_status": "Mandatory",
        "mandatory_variant": "danger",
        "mandatory_note": "Required for Tier-1 MDM Enterprise Gateway routing (or use Tier-2 01b env vars).",
        "summary": "Highest-precedence Tier-1 MDM policy enforcing Enterprise Gateway URL, wire protocol, FinOps attribution headers, TLS CA bundle, and approved Gemini model catalog.",
        "permissions_summary": {
            "linux": "root:root · chmod 0644 · chattr +i",
            "macos": "root:wheel · chmod 0644 · chflags schg",
            "windows": "BOM-free UTF-8 · attrib +R · SYSTEM/Admins:(F), Users:(R,RX), Deny Write/Delete",
        },
        "paths": {
            "linux": "/etc/antigravity/admin_settings.json",
            "macos": "/Library/Application Support/Antigravity/admin_settings.json",
            "windows": "C:\\ProgramData\\Antigravity\\admin_settings.json",
        },
    },
    {
        "id": "gateway_env",
        "group_code": "01b",
        "group_title": "Tier-2 Gateway Environment",
        "filename": "antigravity-gateway.env",
        "short_label": "01b · antigravity-gateway.env",
        "language": "env",
        "os": ["linux", "macos", "windows"],
        "surfaces": ["cli", "desktop", "web", "ide"],
        "surface_details": [
            "AGY CLI (1.2.15+)",
            "AGY Desktop App (2.15.0+)",
            "AGY Web Hub (agy --hub)",
            "VS Code & Visual Studio",
            "JetBrains IDEs & Zed (ACP 1.3.0+)",
        ],
        "doc_title": "Connect Antigravity to an Enterprise Gateway (Tier-2 Env Vars)",
        "doc_url": "https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/connect-enterprise-gateway?hl=en",
        "mandatory_status": "Conditional",
        "mandatory_variant": "warning",
        "mandatory_note": "Required when omitting apiKey from admin_settings.json or for containers/CI.",
        "summary": "Tier-2 AGY_LLM_GATEWAY_* environment profile for per-developer token injection, CI/CD runners, or container workstations (overrides Tier-3 user settings; overridden by Tier-1 MDM).",
        "permissions_summary": {
            "linux": "root:root · chmod 0644 · chattr +i",
            "macos": "root:wheel · chmod 0644 · chflags schg",
            "windows": "Machine Environment Registry (HKLM) · Administrator Write Only",
        },
        "paths": {
            "linux": "/etc/profile.d/antigravity-gateway.sh",
            "macos": "/etc/zshrc  (or /Library/LaunchAgents/com.google.antigravity.env.plist)",
            "windows": "HKLM\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment",
        },
    },
    {
        "id": "cli_settings",
        "group_code": "02",
        "group_title": "CLI & VS Code Sandbox Policy",
        "filename": "settings.json",
        "short_label": "02 · settings.json (CLI)",
        "language": "json",
        "os": ["linux", "macos", "windows"],
        "surfaces": ["cli", "ide"],
        "surface_details": [
            "AGY CLI (agy)",
            "VS Code Extension (Google.google-antigravity)",
            "Visual Studio Extension",
        ],
        "doc_title": "Antigravity CLI Configuration Reference (settings.json)",
        "doc_url": "https://antigravity.google/docs/cli/reference/",
        "mandatory_status": "Recommended",
        "mandatory_variant": "primary",
        "mandatory_note": "Mandatory to enforce CLI / VS Code sandbox & allow/ask/deny permissions.",
        "summary": "Controls Antigravity CLI, VS Code, and Visual Studio agent mode, exebox/Seatbelt terminal sandboxing, sandbox HTTP proxy, transcript retention, and allow/ask/deny grants.",
        "permissions_summary": {
            "linux": "{user}:{user} · chmod 0644 · agy --version pre-init · chattr +i",
            "macos": "{user}:staff · chmod 0644 · agy --version pre-init · chflags schg",
            "windows": "BOM-free UTF-8 · attrib +R · icacls Deny (WD,AD,WEA,WA,DE,WDAC,WO)",
        },
        "paths": {
            "linux": "/home/{user}/.gemini/antigravity-cli/settings.json",
            "macos": "/Users/{user}/.gemini/antigravity-cli/settings.json",
            "windows": "C:\\Users\\{user}\\.gemini\\antigravity-cli\\settings.json",
        },
    },
    {
        "id": "desktop_config",
        "group_code": "03",
        "group_title": "Desktop & Web Hub Policy",
        "filename": "config.json",
        "short_label": "03 · config.json (Desktop/Hub)",
        "language": "json",
        "os": ["linux", "macos", "windows"],
        "surfaces": ["desktop", "web"],
        "surface_details": [
            "AGY Desktop App (2.15.0+)",
            "AGY Self-Hosted Web Hub (agy --hub)",
        ],
        "doc_title": "Antigravity Desktop & Hub Settings Reference",
        "doc_url": "https://antigravity.google/docs/settings/",
        "mandatory_status": "Recommended",
        "mandatory_variant": "primary",
        "mandatory_note": "Mandatory to lock Desktop App & Web Hub auto-execution, JS policy & global grants.",
        "summary": "Governs Antigravity Desktop App and self-hosted Web Hub (agy --hub) auto-execution policy, browser JS execution, artifact review, and globalPermissionGrants.",
        "permissions_summary": {
            "linux": "{user}:{user} · chmod 0644 · chattr +i",
            "macos": "{user}:staff · chmod 0644 · chflags schg",
            "windows": "BOM-free UTF-8 · attrib +R · icacls Deny (WD,AD,WEA,WA,DE,WDAC,WO)",
        },
        "paths": {
            "linux": "/home/{user}/.gemini/config/config.json",
            "macos": "/Users/{user}/.gemini/config/config.json",
            "windows": "C:\\Users\\{user}\\.gemini\\config\\config.json",
        },
    },
    {
        "id": "browser_allowlist",
        "group_code": "04",
        "group_title": "Browser Subagent Allowlist",
        "filename": "browserAllowlist.txt",
        "short_label": "04 · browserAllowlist.txt",
        "language": "text",
        "os": ["linux", "macos", "windows"],
        "surfaces": ["desktop", "web"],
        "surface_details": [
            "AGY Desktop App (Browser Subagent)",
            "AGY Web Hub (Browser Subagent)",
        ],
        "doc_title": "Antigravity Browser Subagent Domain Allowlist",
        "doc_url": "https://antigravity.google/docs/ide/browser/",
        "mandatory_status": "Optional",
        "mandatory_variant": "secondary",
        "mandatory_note": "Recommended on Desktop/Hub to restrict Browser Subagent to approved domains.",
        "summary": "Newline-delimited hostname allowlist restricting which domains the embedded Chromium Browser Subagent can open without security prompts.",
        "permissions_summary": {
            "linux": "{user}:{user} · chmod 0644 · chattr +i",
            "macos": "{user}:staff · chmod 0644 · chflags schg",
            "windows": "BOM-free UTF-8 · attrib +R · icacls Deny (WD,AD,WEA,WA,DE,WDAC,WO)",
        },
        "paths": {
            "linux": "/home/{user}/.gemini/antigravity/browserAllowlist.txt",
            "macos": "/Users/{user}/.gemini/antigravity/browserAllowlist.txt",
            "windows": "C:\\Users\\{user}\\.gemini\\antigravity\\browserAllowlist.txt",
        },
    },
    {
        "id": "mcp_config",
        "group_code": "05",
        "group_title": "Enterprise MCP Server Registry",
        "filename": "mcp_config.json",
        "short_label": "05 · mcp_config.json",
        "language": "json",
        "os": ["linux", "macos", "windows"],
        "surfaces": ["cli", "desktop", "web", "ide"],
        "surface_details": [
            "AGY CLI",
            "AGY Desktop App",
            "AGY Web Hub (agy --hub)",
            "VS Code, Visual Studio, JetBrains & Zed IDEs",
        ],
        "doc_title": "Antigravity Model Context Protocol (MCP) Docs",
        "doc_url": "https://antigravity.google/docs/mcp/",
        "mandatory_status": "Optional",
        "mandatory_variant": "secondary",
        "mandatory_note": "Mandatory when registering approved MCP servers or filtering MCP tools.",
        "summary": "Registers approved local stdio and remote Streamable HTTP MCP servers with per-server enabledTools and disabledTools filters.",
        "permissions_summary": {
            "linux": "{user}:{user} · chmod 0644 · chattr +i",
            "macos": "{user}:staff · chmod 0644 · chflags schg",
            "windows": "BOM-free UTF-8 · attrib +R · icacls Deny (WD,AD,WEA,WA,DE,WDAC,WO)",
        },
        "paths": {
            "linux": "/home/{user}/.gemini/config/mcp_config.json",
            "macos": "/Users/{user}/.gemini/config/mcp_config.json",
            "windows": "C:\\Users\\{user}\\.gemini\\config\\mcp_config.json",
        },
    },
    {
        "id": "hooks_config",
        "group_code": "06",
        "group_title": "Lifecycle Hooks Wiring",
        "filename": "hooks.json",
        "short_label": "06 · hooks.json",
        "language": "json",
        "os": ["linux", "macos", "windows"],
        "surfaces": ["cli", "desktop", "web", "ide"],
        "surface_details": [
            "AGY CLI",
            "AGY Desktop App",
            "AGY Web Hub (agy --hub)",
            "VS Code, Visual Studio, JetBrains & Zed IDEs",
        ],
        "doc_title": "Antigravity Lifecycle Hooks Documentation",
        "doc_url": "https://antigravity.google/docs/hooks/",
        "mandatory_status": "Optional",
        "mandatory_variant": "secondary",
        "mandatory_note": "Mandatory when enforcing synchronous PreToolUse blocking & SIEM audit hooks.",
        "summary": "Wires deterministic PreToolUse policy blockers, PostToolUse SIEM JSONL loggers, and optional SessionStart compliance banners.",
        "permissions_summary": {
            "linux": "{user}:{user} · chmod 0644 · chattr +i",
            "macos": "{user}:staff · chmod 0644 · chflags schg",
            "windows": "BOM-free UTF-8 · attrib +R · icacls Deny (WD,AD,WEA,WA,DE,WDAC,WO)",
        },
        "paths": {
            "linux": "/home/{user}/.gemini/config/hooks.json",
            "macos": "/Users/{user}/.gemini/config/hooks.json",
            "windows": "C:\\Users\\{user}\\.gemini\\config\\hooks.json",
        },
    },
    {
        "id": "guard_sh",
        "group_code": "07a",
        "group_title": "POSIX Security Guard Script",
        "filename": "agy_security_guard.sh",
        "short_label": "07a · agy_security_guard.sh",
        "language": "bash",
        "os": ["linux", "macos"],
        "surfaces": ["cli", "desktop", "web", "ide"],
        "surface_details": [
            "AGY CLI (Linux & macOS)",
            "AGY Desktop & Web Hub (Linux & macOS)",
            "IDE Plugins via hooks.json (Linux & macOS)",
        ],
        "doc_title": "Antigravity PreToolUse & PostToolUse Guard Hooks",
        "doc_url": "https://antigravity.google/docs/hooks/",
        "mandatory_status": "Conditional (POSIX)",
        "mandatory_variant": "warning",
        "mandatory_note": "Mandatory on Linux & macOS whenever hooks.json invokes agy_security_guard.sh.",
        "summary": "Root-owned executable Bash script invoked by hooks.json on Linux/macOS to block destructive commands, credentials, SSRF, and write JSONL audit events (exit 2 = hard block).",
        "permissions_summary": {
            "linux": "root:root · chmod 0755 (executable) · chattr +i",
            "macos": "root:wheel · chmod 0755 (executable) · chflags schg",
            "windows": "",
        },
        "paths": {
            "linux": "/usr/local/bin/agy_security_guard.sh",
            "macos": "/usr/local/bin/agy_security_guard.sh",
            "windows": "",
        },
    },
    {
        "id": "guard_ps1",
        "group_code": "07b",
        "group_title": "Windows Security Guard Script",
        "filename": "agy_security_guard.ps1",
        "short_label": "07b · agy_security_guard.ps1",
        "language": "powershell",
        "os": ["windows"],
        "surfaces": ["cli", "desktop", "web", "ide"],
        "surface_details": [
            "AGY CLI (Windows)",
            "AGY Desktop & Web Hub (Windows)",
            "IDE Plugins via hooks.json (Windows)",
        ],
        "doc_title": "Antigravity PreToolUse & PostToolUse Guard Hooks",
        "doc_url": "https://antigravity.google/docs/hooks/",
        "mandatory_status": "Conditional (Win)",
        "mandatory_variant": "warning",
        "mandatory_note": "Mandatory on Windows whenever hooks.json is deployed (primary guard without exebox).",
        "summary": "Administrator-locked PowerShell script acting as the primary runtime command & DLP gatekeeper on Windows workstations where kernel exebox is unavailable.",
        "permissions_summary": {
            "linux": "",
            "macos": "",
            "windows": "CRLF · attrib +R · SYSTEM/Admins:(F), Users:(R,RX), Deny Write/Delete",
        },
        "paths": {
            "linux": "",
            "macos": "",
            "windows": "C:\\ProgramData\\Antigravity\\bin\\agy_security_guard.ps1",
        },
    },
    {
        "id": "acp_json",
        "group_code": "08a",
        "group_title": "JetBrains & Zed ACP Server",
        "filename": "acp.json",
        "short_label": "08a · acp.json (JetBrains/Zed)",
        "language": "json",
        "os": ["linux", "macos", "windows"],
        "surfaces": ["ide"],
        "surface_details": [
            "JetBrains IDEs (IntelliJ, PyCharm, GoLand, WebStorm)",
            "Zed Editor (ACP 1.3.0+)",
        ],
        "doc_title": "Connect JetBrains & Zed IDEs to Enterprise Gateway (ACP)",
        "doc_url": "https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/connect-enterprise-gateway?hl=en",
        "mandatory_status": "Mandatory (ACP)",
        "mandatory_variant": "danger",
        "mandatory_note": "Required for JetBrains IDEs & Zed Editor to launch 'agy acp' with Gateway env vars.",
        "summary": "Agent Client Protocol (ACP 1.3.0+) server definition launching 'agy acp' with Gateway environment variables inside JetBrains IDEs and Zed.",
        "permissions_summary": {
            "linux": "{user}:{user} · chmod 0644 · chattr +i",
            "macos": "{user}:staff · chmod 0644 · chflags schg",
            "windows": "BOM-free UTF-8 · attrib +R · icacls Deny (WD,AD,WEA,WA,DE,WDAC,WO)",
        },
        "paths": {
            "linux": "/home/{user}/.jetbrains/acp.json  (Zed: ~/.config/zed/settings.json)",
            "macos": "/Users/{user}/.jetbrains/acp.json  (Zed: ~/.config/zed/settings.json)",
            "windows": "C:\\Users\\{user}\\.jetbrains\\acp.json  (Zed: %APPDATA%\\Zed\\settings.json)",
        },
    },
    {
        "id": "acp_auth",
        "group_code": "08b",
        "group_title": "ACP Gateway Auth Mode",
        "filename": "antigravity-acp-settings.json",
        "short_label": "08b · antigravity-acp/settings.json",
        "language": "json",
        "os": ["linux", "macos", "windows"],
        "surfaces": ["ide"],
        "surface_details": [
            "JetBrains IDEs (ACP Gateway Auth)",
            "Zed Editor (ACP Gateway Auth)",
        ],
        "doc_title": "Connect JetBrains & Zed IDEs to Enterprise Gateway (ACP)",
        "doc_url": "https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/connect-enterprise-gateway?hl=en",
        "mandatory_status": "Mandatory (ACP)",
        "mandatory_variant": "danger",
        "mandatory_note": 'Required companion ({"auth":{"type":"gateway"}}) so JetBrains & Zed skip Google OAuth.',
        "summary": 'Mandatory companion file setting {"auth": {"type": "gateway"}} so JetBrains and Zed ACP sessions bypass consumer Google OAuth sign-in.',
        "permissions_summary": {
            "linux": "{user}:{user} · chmod 0644 · chattr +i",
            "macos": "{user}:staff · chmod 0644 · chflags schg",
            "windows": "BOM-free UTF-8 · attrib +R · icacls Deny (WD,AD,WEA,WA,DE,WDAC,WO)",
        },
        "paths": {
            "linux": "/home/{user}/.gemini/antigravity-acp/settings.json",
            "macos": "/Users/{user}/.gemini/antigravity-acp/settings.json",
            "windows": "C:\\Users\\{user}\\.gemini\\antigravity-acp\\settings.json",
        },
    },
]

FILE_CATALOG_BY_ID: dict[str, dict[str, Any]] = {item["id"]: item for item in FILE_CATALOG}

REFERENCE_GUIDE: dict[str, list[dict[str, str]]] = {
    "os_requirements": [
        {
            "os": "Windows",
            "min_version": "Windows 10 (64-bit), Windows 11, or Windows Server 2022+",
            "architectures": "x64 (Intel/AMD), ARM64 (32-bit is not supported)",
            "hardware_runtime": "8 GB RAM min (16 GB+ recommended) · PowerShell 5.1+ / 7+",
            "sandbox_lock": "PreToolUse PowerShell guard · BOM-free UTF-8 + attrib.exe +R + icacls.exe /deny",
        },
        {
            "os": "macOS",
            "min_version": "macOS 12 (Monterey) or later",
            "architectures": "Apple Silicon (arm64 M-series), 64-bit Intel (x86_64)",
            "hardware_runtime": "8 GB RAM min (16 GB+ recommended) · Zsh / Bash",
            "sandbox_lock": "Seatbelt kernel sandbox (sandbox-exec) · root:wheel + chflags schg",
        },
        {
            "os": "Linux",
            "min_version": "glibc >= 2.28, glibcxx >= 3.4.25 (Ubuntu 20.04+/22.04+, Debian 10+, RHEL 8+, Fedora 36+)",
            "architectures": "x86_64 (amd64), ARM64",
            "hardware_runtime": "8 GB RAM min (16 GB+ recommended) · e2fsprogs (chattr/lsattr)",
            "sandbox_lock": "Native exebox namespace sandbox · root:root + chattr +i",
        },
    ],
    "version_requirements": [
        {
            "surface": "AGY CLI (agy)",
            "min_version": "1.2.15 or later",
            "platforms_protocols": "Linux (x86_64), macOS (arm64), Windows (x86_64) · genai & openai",
            "notes": "Honors 3-tier Gateway precedence (MDM > Env Vars > User Settings); test headless via agy -p \"...\".",
            "doc_label": "CLI Reference",
            "doc_url": "https://antigravity.google/docs/cli/reference/",
        },
        {
            "surface": "AGY Desktop App",
            "min_version": "2.15.0 or later",
            "platforms_protocols": "Windows 10/11 (64-bit), macOS (arm64/x86_64), Linux (x86_64) · genai & openai",
            "notes": "Automatically suppresses interactive Google OAuth sign-in when gateway.enabled is true (PAYG billing).",
            "doc_label": "Connect Guide",
            "doc_url": "https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/connect-enterprise-gateway?hl=en",
        },
        {
            "surface": "AGY Web (Cloud SaaS vs. Self-Hosted Hub)",
            "min_version": "Cloud SaaS: Unsupported · Hub (agy --hub): CLI 1.2.15+",
            "platforms_protocols": "Self-hosted agy --hub (:4400) on Linux, macOS, Windows · genai & openai",
            "notes": "Public cloud Antigravity Web requires interactive Google sign-in and does NOT support Gateway; self-hosted agy --hub inherits workstation MDM policies.",
            "doc_label": "Gateway Docs",
            "doc_url": "https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/deploy-enterprise-gateway?hl=en",
        },
        {
            "surface": "AGY IDE — VS Code & Visual Studio",
            "min_version": "VS Code 1.90+ · Bundled CLI 1.2.15+",
            "platforms_protocols": "Windows, macOS, Linux · genai & openai",
            "notes": "Official Google.google-antigravity extension auto-downloads CLI 1.2.15+ and enforces Tier-1 admin_settings.json + CLI settings.json.",
            "doc_label": "IDE Extensions",
            "doc_url": "https://antigravity.google/docs/ide/extensions",
        },
        {
            "surface": "AGY IDE — JetBrains IDEs",
            "min_version": "IDE 2026.2.1+ · ACP Server 1.3.0+ (CLI 1.2.15+)",
            "platforms_protocols": "Windows, macOS, Linux · genai ONLY (openai unsupported)",
            "notes": "Requires ~/.jetbrains/acp.json AND ~/.gemini/antigravity-acp/settings.json ({\"auth\":{\"type\":\"gateway\"}}).",
            "doc_label": "ACP Setup",
            "doc_url": "https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/connect-enterprise-gateway?hl=en",
        },
        {
            "surface": "AGY IDE — Zed Editor",
            "min_version": "Zed 0.140.0+ · ACP Server 1.3.0+ (CLI 1.2.15+)",
            "platforms_protocols": "Windows, macOS, Linux · genai ONLY (openai unsupported)",
            "notes": "Requires agent_servers.Antigravity in Zed settings.json AND ~/.gemini/antigravity-acp/settings.json.",
            "doc_label": "ACP Setup",
            "doc_url": "https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/connect-enterprise-gateway?hl=en",
        },
    ],
}

DEFAULT_GUARD_SH = """#!/usr/bin/env bash
# ==============================================================================
# File: /usr/local/bin/agy_security_guard.sh
# Purpose: Synchronous PreToolUse policy blocker (exit 2) & PostToolUse JSONL
#          SIEM telemetry logger for Antigravity on Linux and macOS workstations.
# Architecture/Context: Invoked automatically by ~/.gemini/config/hooks.json.
# Dependencies/Side Effects: Reads hook JSON on stdin; writes JSONL audit record.
# ==============================================================================
set -euo pipefail

PHASE="${1:-pre}"
AUDIT_LOG="${AGY_AUDIT_LOG_PATH:-/tmp/agy_security_audit.log}"
PAYLOAD="$(cat)"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
CURRENT_USER="$(id -un)"

printf '{"timestamp":"%s","phase":"%s","user":"%s","event":%s}\\n' \\
  "${TIMESTAMP}" "${PHASE}" "${CURRENT_USER}" "${PAYLOAD:-{}}" >> "${AUDIT_LOG}" 2>/dev/null || true

block_with_violation() {
  printf 'SECURITY_POLICY_VIOLATION [%s]: %s\\n' "$1" "$2" >&2
  exit 2
}

if [[ "${PHASE}" == "pre" ]]; then
  if printf '%s' "${PAYLOAD}" | grep -Eqi '(\\b(rm|rmdir|unlink|shred|srm|del|erase|remove-item)\\s+|\\bgit\\s+clean\\s+[^"]*-[a-zA-Z]*[fdX]|shutil\\.rmtree)'; then
    block_with_violation "RULE-1-NO-DELETE" "Destructive file or directory deletion by the agent is prohibited."
  fi
  if printf '%s' "${PAYLOAD}" | grep -Eqi '(/etc/(shadow|gshadow|sudoers)|admin_settings\\.json|\\.(pem|key|p12|pfx|kdbx)("|\x27|\\s|$)|[\\/](id_rsa|id_ed25519|\\.env)("|\x27|\\s|$))'; then
    block_with_violation "RULE-2-SENSITIVE-DATA" "Access to OS password stores, private keys, or MDM settings is prohibited."
  fi
  if printf '%s' "${PAYLOAD}" | grep -Eqi '(169\\.254\\.169\\.254|metadata\\.google\\.internal|pastebin\\.com|webhook\\.site|ngrok\\.io|trycloudflare\\.com|transfer\\.sh)'; then
    block_with_violation "RULE-5-RESTRICTED-URL" "Access to cloud metadata endpoints, tunnels, or paste sites is prohibited."
  fi
  if printf '%s' "${PAYLOAD}" | grep -Eqi '(BLOCK_BY_HOOK_TEST|--dangerously-skip|chattr\\s+-i|chflags\\s+noschg|\\b(sudo|su|doas|pkexec|nmap|sqlmap|nc|netcat|socat)\\s+)'; then
    block_with_violation "RULE-4-PRIVILEGE-OR-EXPLOIT" "Privilege escalation, lock bypass, or network exploitation utilities are prohibited."
  fi
fi

exit 0
"""

DEFAULT_GUARD_PS1 = """<#
==============================================================================
File: C:\\ProgramData\\Antigravity\\bin\\agy_security_guard.ps1
Purpose: Synchronous PreToolUse policy blocker (exit 2) & PostToolUse JSONL
         SIEM telemetry logger for Antigravity on Windows workstations.
Architecture/Context: Invoked by ~/.gemini/config/hooks.json via powershell.exe.
Dependencies/Side Effects: Reads hook JSON on stdin; writes JSONL audit record.
==============================================================================
#>
param([Parameter(Position = 0)][string]$Phase = "pre")
$ErrorActionPreference = "SilentlyContinue"

$AuditLog = if ($env:AGY_AUDIT_LOG_PATH) { $env:AGY_AUDIT_LOG_PATH } else { "C:\\Windows\\Temp\\agy_security_audit.log" }
$Payload = [Console]::In.ReadToEnd()
$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

$PayloadJson = if ([string]::IsNullOrWhiteSpace($Payload)) { "{}" } else { $Payload.Trim() }
Add-Content -Path $AuditLog -Value "{`"timestamp`":`"$Timestamp`",`"phase`":`"$Phase`",`"user`":`"$CurrentUser`",`"event`":$PayloadJson}" -Encoding UTF8 -ErrorAction SilentlyContinue

function Stop-WithPolicyViolation([string]$RuleId, [string]$Reason) {
    [Console]::Error.WriteLine("SECURITY_POLICY_VIOLATION [$RuleId]: $Reason")
    exit 2
}

if ($Phase -eq "pre") {
    if ($Payload -match '(?i)(\\b(rm|rmdir|unlink|shred|del|erase|rd|remove-item|sdelete)\\s+|shutil\\.rmtree)') {
        Stop-WithPolicyViolation "RULE-1-NO-DELETE" "File or directory deletion by the Antigravity agent is prohibited."
    }
    if ($Payload -match '(?i)([\\\\/]+Windows[\\\\/]+System32[\\\\/]+config[\\\\/]+(SAM|SYSTEM|SECURITY)|NTDS\\.dit|ProgramData[\\\\/]+Antigravity[\\\\/]+admin_settings\\.json|\\.(pem|key|p12|pfx|kdbx)("|\x27|\\s|$)|[\\\\/](id_rsa|id_ed25519|\\.env)("|\x27|\\s|$))') {
        Stop-WithPolicyViolation "RULE-2-SENSITIVE-DATA" "Access to SAM/NTDS hives, private keys, or MDM settings is prohibited."
    }
    if ($Payload -match '(?i)(BLOCK_BY_HOOK_TEST|--dangerously-skip|\\b(sudo|runas|icacls|takeown|attrib|nmap|sqlmap|mimikatz|enter-pssession|invoke-command)\\s+)') {
        Stop-WithPolicyViolation "RULE-4-ANTI-EXPLOIT" "Privilege escalation, ACL modification, and offensive utilities are prohibited."
    }
    if ($Payload -match '(?i)(169\\.254\\.169\\.254|metadata\\.google\\.internal|pastebin\\.com|webhook\\.site|ngrok\\.io|trycloudflare\\.com|transfer\\.sh)') {
        Stop-WithPolicyViolation "RULE-5-RESTRICTED-URL" "Access to cloud instance metadata endpoints, paste sites, or tunnels is prohibited."
    }
}

exit 0
"""

DEFAULT_MODELS_LIST: list[dict[str, str]] = [
    {"modelId": "gemini-4-argon-high", "displayName": "Gemini 4 Argon (High Thinking)"},
    {"modelId": "gemini-4-argon-medium", "displayName": "Gemini 4 Argon (Medium Thinking)"},
    {"modelId": "gemini-4-argon-low", "displayName": "Gemini 4 Argon (Low Thinking)"},
    {"modelId": "gemini-3.1-pro-preview", "displayName": "Gemini 3.1 Pro"},
    {"modelId": "gemini-3.8-flash", "displayName": "Gemini 3.8 Flash"},
    {"modelId": "gemini-3.7-flash", "displayName": "Gemini 3.7 Flash"},
    {"modelId": "gemini-3.1-flash-lite", "displayName": "Gemini 3.1 Flash-Lite"},
]


def _default_balanced_permissions(dev_user: str) -> dict[str, list[str]]:
    """Build the default cross-OS balanced allow/ask/deny permission ruleset.

    Summary:
        Produces a clean, scannable enterprise baseline that works across Linux
        (`exebox`), macOS (`sandbox-exec`), and Windows (`RequiresExactMatch`
        PowerShell regex companions).
    Parameters:
        dev_user (str): Target workstation developer username.
    Return Value:
        dict[str, list[str]]: Dictionary with `allow`, `ask`, and `deny` arrays.
    Exceptions/Errors:
        None.
    """
    u = dev_user.strip() or "alice"
    return {
        "allow": [
            "command(echo)",
            "command(ls)",
            "command(pwd)",
            "command(cat)",
            "command(git status)",
            "command(git diff)",
            "command(git log)",
            "command(go test)",
            "command(pytest)",
            r"command(regex:^(?i)(echo|write-output|write-host|ls|get-childitem|pwd|get-location)(\s+[^;&|`$()\r\n>]*)?$)",
            r"command(regex:^git\s+(status|diff|log)(\s+[^;&|`$()\r\n>]*)?$)",
            r"command(regex:^(go\s+test|pytest)(\s+[^;&|`$()\r\n>]*)?$)",
            f"read_file(/home/{u}/workspace)",
            f"read_file(/home/{u}/.gemini)",
            f"read_file(/Users/{u}/workspace)",
            f"read_file(/Users/{u}/.gemini)",
            f"write_file(/home/{u}/workspace)",
            f"write_file(/Users/{u}/workspace)",
            "read_url(localhost)",
            "read_url(127.0.0.1)",
            "read_url(antigravity.google)",
            "read_url(docs.cloud.google.com)",
            "read_url(cloud.google.com)",
            "mcp(catalog/ping_catalog)",
            "mcp(catalog/search_catalog)",
            "mcp(corp_docs/read_doc)",
            "mcp(corp_docs/search_docs)",
        ],
        "ask": [
            "command(git commit)",
            "command(git push)",
            "command(docker build)",
            "command(kubectl apply)",
            "unsandboxed(docker build)",
            f"write_file(/home/{u}/workspace/package.json)",
            f"write_file(/Users/{u}/workspace/package.json)",
            "read_url(github.com)",
            "mcp(corp_docs/create_ticket)",
        ],
        "deny": [
            "command(rm)",
            "command(rmdir)",
            "command(unlink)",
            "command(shred)",
            "command(del)",
            "command(Remove-Item)",
            "command(sudo)",
            "command(su)",
            "command(chattr)",
            "command(chflags)",
            "command(icacls)",
            "command(ssh)",
            "command(scp)",
            "command(nc)",
            "command(nmap)",
            "read_file(/etc/shadow)",
            "read_file(/etc/sudoers)",
            "read_file(/etc/antigravity/admin_settings.json)",
            "read_file(/private/etc/master.passwd)",
            "read_file(/Library/Keychains)",
            f"read_file(/home/{u}/.ssh)",
            f"read_file(/Users/{u}/.ssh)",
            f"write_file(/home/{u}/.gemini)",
            f"write_file(/Users/{u}/.gemini)",
            "read_url(169.254.169.254)",
            "read_url(metadata.google.internal)",
            "read_url(pastebin.com)",
            "read_url(ngrok.io)",
            "mcp(untrusted_external/*)",
            "mcp(catalog/drop_catalog_table)",
            "mcp(corp_docs/delete_repository)",
        ],
    }


def build_default_state(dev_user: str = "alice") -> dict[str, Any]:
    """Create the initial Balanced Enterprise studio state dictionary.

    Summary:
        Returns a complete JSON-serializable state model covering OS & surface
        selection, Gateway settings, CLI/Desktop sandbox policies, permissions,
        browser allowlist, MCP servers, hooks, ACP IDE settings, and round-trip
        custom key storage.
    Parameters:
        dev_user (str): Default developer workstation username.
    Return Value:
        dict[str, Any]: Canonical studio state dictionary.
    Exceptions/Errors:
        None.
    """
    user_clean = (dev_user or os.getenv("DEFAULT_DEV_USER", "alice")).strip() or "alice"
    perms = _default_balanced_permissions(user_clean)

    return {
        "os_list": ["linux", "macos", "windows"],
        "surfaces": ["cli", "desktop", "web", "ide"],
        "selected_file_ids": None,
        "dev_user": user_clean,
        "sync_permissions": True,
        "active_preset": "balanced",
        "gateway": {
            "enabled": True,
            "url": "https://REPLACE_WITH_GATEWAY_URL",
            "apiKey": "REPLACE_WITH_GATEWAY_API_KEY",
            "omitApiKeyInMdm": False,
            "wireProtocol": "genai",
            "caCertPath": "/etc/ssl/certs/ca-certificates.crt",
            "customHeaders": [
                {"key": "X-Cost-Center", "value": "CC-9941-SEC"},
                {"key": "X-Corporate-BU", "value": "Enterprise-Security"},
                {"key": "X-Enterprise-Surface", "value": "MDM-Managed-Workstation"},
                {"key": "X-Goog-User-Project", "value": "REPLACE_WITH_PROJECT_ID"},
            ],
            "defaultModelId": "gemini-3.8-flash",
            "models": copy.deepcopy(DEFAULT_MODELS_LIST),
        },
        "gateway_env": {
            "exportPrefix": True,
            "url": "https://REPLACE_WITH_GATEWAY_URL",
            "apiKey": "${REPLACE_WITH_GATEWAY_API_KEY}",
            "wireProtocol": "genai",
            "caCert": "/etc/ssl/certs/ca-certificates.crt",
            "headers": "X-Cost-Center: CC-9941-SEC,X-Corporate-BU: Enterprise-Security,X-Goog-User-Project: REPLACE_WITH_PROJECT_ID",
            "models": ",".join(m["modelId"] for m in DEFAULT_MODELS_LIST),
        },
        "cli": {
            "agentMode": "plan",
            "toolPermission": "proceed-in-sandbox",
            "enableTerminalSandbox": True,
            "allowNonWorkspaceAccess": False,
            "artifactReviewPolicy": "asks-for-review",
            "historySize": 50,
            "includeOptionalUiKeys": False,
            "notifications": False,
            "showFeedbackSurvey": False,
            "showTips": False,
            "sandboxProxyEnabled": False,
            "sandboxProxyAddress": "",
            "sandboxProxyCertFile": "",
            "sandboxProxyUsername": "",
            "sandboxProxyPassword": "",
            "permissions": copy.deepcopy(perms),
        },
        "desktop": {
            "autoExecutionPolicy": "CASCADE_COMMANDS_AUTO_EXECUTION_PROCEED_IN_SANDBOX",
            "artifactReviewMode": "ARTIFACT_REVIEW_MODE_ALWAYS",
            "browserJsExecutionPolicy": "BROWSER_JS_EXECUTION_POLICY_DISABLED",
            "enableTerminalSandbox": True,
            "sandboxAllowNetwork": False,
            "nonWorkspaceFileAccessPolicy": "",
            "internetAccessPolicy": "",
            "permissions": copy.deepcopy(perms),
        },
        "browser_domains": [
            "localhost",
            "127.0.0.1",
            "antigravity.google",
            "docs.cloud.google.com",
            "cloud.google.com",
            "pkg.go.dev",
            "docs.python.org",
            "internal.corp.example.com",
        ],
        "mcp_servers": [
            {
                "name": "catalog",
                "transport": "stdio",
                "command": "/usr/local/bin/mock_mcp_server.py",
                "args": ["catalog"],
                "serverUrl": "",
                "disabled": True,
                "timeoutSeconds": 60,
                "enabledTools": ["ping_catalog", "search_catalog", "get_service_owner"],
                "disabledTools": ["drop_catalog_table", "export_all_records", "delete_service", "update_permissions"],
                "env": {},
            },
            {
                "name": "corp_docs",
                "transport": "http",
                "command": "",
                "args": [],
                "serverUrl": "https://mcp-corp-docs.internal.example.com/mcp/",
                "disabled": True,
                "timeoutSeconds": 180,
                "enabledTools": ["read_doc", "search_docs", "create_ticket"],
                "disabledTools": ["delete_repository", "grant_external_access", "export_space", "modify_acl"],
                "env": {},
            },
            {
                "name": "untrusted_external",
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "@untrusted/external-mcp-server"],
                "serverUrl": "",
                "disabled": True,
                "timeoutSeconds": 60,
                "enabledTools": [],
                "disabledTools": ["*"],
                "env": {},
            },
        ],
        "hooks": {
            "enablePreToolUse": True,
            "preMatcher": ".*",
            "preCommand": "/usr/local/bin/agy_security_guard.sh pre",
            "preTimeout": 10,
            "enablePostToolUse": True,
            "postMatcher": ".*",
            "postCommand": "/usr/local/bin/agy_security_guard.sh post",
            "postTimeout": 10,
            "enableSessionStartBanner": False,
            "sessionBannerText": "CORPORATE AI GOVERNANCE NOTICE: All prompts and tool invocations are audited under enterprise policy.",
        },
        "acp": {
            "command": "/usr/local/bin/agy",
            "args": ["acp"],
            "authType": "gateway",
        },
        "scripts": {
            "guard_sh": DEFAULT_GUARD_SH,
            "guard_ps1": DEFAULT_GUARD_PS1,
        },
        "extra_json_keys": {},
    }


# ==============================================================================
# BLOCK 2: STARTER PRESETS & CURATED ENTERPRISE RECIPES
# ==============================================================================
PRESET_METADATA: list[dict[str, str]] = [
    {
        "id": "balanced",
        "category": "Core Presets",
        "label": "Balanced Enterprise (Recommended)",
        "description": "Full Gateway + Gemini 4/3 catalog, sandboxed plan mode, safe git/test grants, lazy MCP, and Pre/Post guard hooks.",
    },
    {
        "id": "repo_baseline",
        "category": "Core Presets",
        "label": "Full 595-Rule Hardened Baseline (agy-config/configs)",
        "description": "Loads the complete live-validated 8-module enterprise baseline from ../agy-config/configs/.",
    },
    {
        "id": "hardened",
        "category": "Core Presets",
        "label": "High-Security Zero-Trust",
        "description": "Strict human review on all tools, ephemeral historySize=0, wildcard mcp(*) deny, and compliance banner.",
    },
    {
        "id": "blank",
        "category": "Core Presets",
        "label": "Minimal Clean Starter",
        "description": "Lightweight valid skeleton with zero extra rules for authoring custom policies from scratch.",
    },
    {
        "id": "recipe_split_finops_key",
        "category": "Admin Recipes (ADMIN_POLICY_EXAMPLES.md)",
        "label": "Recipe 01 · Split MDM FinOps + Per-User Tier-2 Key",
        "description": "Pins Gateway URL & X-Cost-Center in world-readable admin_settings.json while omitting apiKey to Tier-2 env vars.",
    },
    {
        "id": "recipe_corp_tls_proxy",
        "category": "Admin Recipes (ADMIN_POLICY_EXAMPLES.md)",
        "label": "Recipe 02 · Corporate TLS Inspection & sandboxProxy",
        "description": "Configures single-cert corporate root CA PEM in both caCertPath and CLI sandboxProxy.http.",
    },
    {
        "id": "recipe_bastion_strict",
        "category": "Admin Recipes (ADMIN_POLICY_EXAMPLES.md)",
        "label": "Recipe 03 · Production Bastion Read-Only Strict Mode",
        "description": "Locks CLI/Desktop to read-only inspection (toolPermission=strict, historySize=0, write_file(*) denied).",
    },
    {
        "id": "recipe_mcp_zero_trust",
        "category": "Admin Recipes (ADMIN_POLICY_EXAMPLES.md)",
        "label": "Recipe 04 · Zero-Trust MCP Allowlist (mcp(*) Deny)",
        "description": "Blocks all unapproved MCP servers via mcp(*) deny while explicitly allowing vetted read-only catalog tools.",
    },
    {
        "id": "recipe_dlp_banner_hooks",
        "category": "Admin Recipes (ADMIN_POLICY_EXAMPLES.md)",
        "label": "Recipe 05 · SessionStart Banner + Secret DLP Hook",
        "description": "Injects an ephemeral SessionStart compliance banner and inspects write_file|edit_file|sed_file for secrets.",
    },
    {
        "id": "recipe_windows_enterprise",
        "category": "Admin Recipes (ADMIN_POLICY_EXAMPLES.md)",
        "label": "Recipe 06 · Windows PowerShell-Safe Enterprise Profile",
        "description": "Scopes to Windows, clears Linux caCertPath, adds PowerShell RequiresExactMatch regex + unsandboxed grants, and wires PS1 guard.",
    },
    {
        "id": "recipe_jetbrains_zed_acp",
        "category": "Admin Recipes (ADMIN_POLICY_EXAMPLES.md)",
        "label": "Recipe 07 · JetBrains & Zed ACP Gateway Profile",
        "description": "Scopes to IDE Plugins, enforces genai wire protocol, and configures acp.json + antigravity-acp/settings.json.",
    },
]


def _resolve_repo_baseline_dir(custom_dir: str | None = None) -> Path | None:
    """Locate the sibling `agy-config/configs` directory if available on disk.

    Summary:
        Checks `custom_dir`, `REPO_BASELINE_DIR` env var, and `../agy-config/configs`
        relative to this module so the studio can load the full 595-rule repo
        baseline when running from the repository checkout.
    Parameters:
        custom_dir (str | None): Optional directory override.
    Return Value:
        Path | None: Resolved `Path` if directory exists, else `None`.
    Exceptions/Errors:
        None.
    """
    candidates = [
        custom_dir,
        os.getenv("REPO_BASELINE_DIR"),
        str(Path(__file__).resolve().parent.parent / "agy-config" / "configs"),
    ]
    for raw in candidates:
        if not raw:
            continue
        p = Path(raw).expanduser().resolve()
        if p.is_dir() and (p / "01-admin-settings" / "admin_settings.json").is_file():
            return p
    return None


def load_preset_state(preset_id: str, dev_user: str = "alice") -> dict[str, Any]:
    """Build a complete studio state initialized from a named preset or recipe.

    Summary:
        Generates any of the 4 core presets or 7 curated enterprise recipes from
        `ADMIN_POLICY_EXAMPLES.md` with clean, zero-placeholder configuration.
    Parameters:
        preset_id (str): Identifier from `PRESET_METADATA`.
        dev_user (str): Target workstation developer username.
    Return Value:
        dict[str, Any]: Fully populated studio state dictionary.
    Exceptions/Errors:
        ValueError: If `preset_id` is unknown.
    """
    valid_ids = {p["id"] for p in PRESET_METADATA}
    if preset_id not in valid_ids:
        raise ValueError(f"Unknown preset identifier: {preset_id}")

    u = (dev_user or "alice").strip() or "alice"
    state = build_default_state(dev_user=u)
    state["active_preset"] = preset_id

    if preset_id == "balanced":
        return state

    if preset_id == "repo_baseline":
        repo_dir = _resolve_repo_baseline_dir()
        if repo_dir is not None:
            file_pairs = [
                ("admin_settings", repo_dir / "01-admin-settings" / "admin_settings.json"),
                ("cli_settings", repo_dir / "02-cli-settings" / "settings.json"),
                ("desktop_config", repo_dir / "03-desktop-hub-config" / "config.json"),
                ("browser_allowlist", repo_dir / "04-browser-allowlist" / "browserAllowlist.txt"),
                ("mcp_config", repo_dir / "05-mcp-config" / "mcp_config.json"),
                ("hooks_config", repo_dir / "06-lifecycle-hooks" / "hooks.json"),
                ("guard_sh", repo_dir / "07-security-guard-scripts" / "agy_security_guard.sh"),
                ("guard_ps1", repo_dir / "07-security-guard-scripts" / "agy_security_guard.ps1"),
                ("acp_json", repo_dir / "08-acp-ide-configs" / "acp.json"),
                ("acp_auth", repo_dir / "08-acp-ide-configs" / "antigravity-acp-settings.json"),
            ]
            for fid, fpath in file_pairs:
                if fpath.is_file():
                    raw = fpath.read_text(encoding="utf-8").replace("__DEV_USER__", u)
                    state = parse_file_into_state(fid, raw, state)
            state["active_preset"] = "repo_baseline"
        return state

    if preset_id == "hardened":
        state["cli"]["agentMode"] = "plan"
        state["cli"]["toolPermission"] = "strict"
        state["cli"]["historySize"] = 0
        state["cli"]["includeOptionalUiKeys"] = True
        state["desktop"]["autoExecutionPolicy"] = "CASCADE_COMMANDS_AUTO_EXECUTION_DISABLED"
        state["desktop"]["nonWorkspaceFileAccessPolicy"] = "NON_WORKSPACE_FILE_ACCESS_POLICY_DISABLED"
        state["desktop"]["internetAccessPolicy"] = "INTERNET_ACCESS_POLICY_DISABLED"
        strict_perms = {
            "allow": [
                f"read_file(/home/{u}/workspace)",
                f"read_file(/home/{u}/.gemini)",
                f"read_file(/Users/{u}/workspace)",
                f"read_file(/Users/{u}/.gemini)",
                "mcp(catalog/ping_catalog)",
            ],
            "ask": [
                "command(git status)",
                "command(git diff)",
                r"command(regex:^git\s+(status|diff)(\s+[^;&|`$()\r\n>]*)?$)",
                f"write_file(/home/{u}/workspace)",
                f"write_file(/Users/{u}/workspace)",
            ],
            "deny": state["cli"]["permissions"]["deny"] + ["mcp(*)", "execute_url(*)"],
        }
        state["cli"]["permissions"] = copy.deepcopy(strict_perms)
        state["desktop"]["permissions"] = copy.deepcopy(strict_perms)
        state["browser_domains"] = ["localhost", "127.0.0.1", "internal.corp.example.com"]
        state["hooks"]["enableSessionStartBanner"] = True
        return state

    if preset_id == "blank":
        state["gateway"]["customHeaders"] = [
            {"key": "X-Goog-User-Project", "value": "REPLACE_WITH_PROJECT_ID"}
        ]
        state["gateway"]["models"] = [
            {"modelId": "gemini-3.8-flash", "displayName": "Gemini 3.8 Flash"},
            {"modelId": "gemini-3.1-pro-preview", "displayName": "Gemini 3.1 Pro"},
        ]
        empty_perms = {
            "allow": [f"read_file(/home/{u}/workspace)", f"write_file(/home/{u}/workspace)"],
            "ask": [],
            "deny": ["command(rm)", "read_file(/etc/shadow)"],
        }
        state["cli"]["permissions"] = copy.deepcopy(empty_perms)
        state["desktop"]["permissions"] = copy.deepcopy(empty_perms)
        state["browser_domains"] = ["localhost", "docs.cloud.google.com"]
        state["mcp_servers"] = []
        return state

    if preset_id == "recipe_split_finops_key":
        state["gateway"]["omitApiKeyInMdm"] = True
        state["gateway"]["apiKey"] = ""
        state["gateway_env"]["apiKey"] = "${REPLACE_WITH_GATEWAY_API_KEY}"
        return state

    if preset_id == "recipe_corp_tls_proxy":
        state["gateway"]["caCertPath"] = "/etc/antigravity/certs/corp-root-ca.pem"
        state["gateway_env"]["caCert"] = "/etc/antigravity/certs/corp-root-ca.pem"
        state["cli"]["sandboxProxyEnabled"] = True
        state["cli"]["sandboxProxyAddress"] = "http://proxy.internal.example.com:3128"
        state["cli"]["sandboxProxyCertFile"] = "/etc/antigravity/certs/corp-root-ca.pem"
        return state

    if preset_id == "recipe_bastion_strict":
        state["os_list"] = ["linux"]
        state["surfaces"] = ["cli"]
        state["cli"]["agentMode"] = "plan"
        state["cli"]["toolPermission"] = "strict"
        state["cli"]["historySize"] = 0
        state["cli"]["includeOptionalUiKeys"] = True
        bastion_perms = {
            "allow": [
                "command(ls)",
                "command(pwd)",
                "command(git status)",
                f"read_file(/home/{u}/workspace)",
            ],
            "ask": ["command(kubectl get)", "command(journalctl)"],
            "deny": ["write_file(*)", "command(rm)", "command(sudo)", "mcp(*)"],
        }
        state["cli"]["permissions"] = copy.deepcopy(bastion_perms)
        state["desktop"]["permissions"] = copy.deepcopy(bastion_perms)
        return state

    if preset_id == "recipe_mcp_zero_trust":
        state["mcp_servers"][0]["disabled"] = False
        perms = state["cli"]["permissions"]
        if "mcp(*)" not in perms["deny"]:
            perms["deny"].append("mcp(*)")
        state["desktop"]["permissions"] = copy.deepcopy(perms)
        return state

    if preset_id == "recipe_dlp_banner_hooks":
        state["hooks"]["enableSessionStartBanner"] = True
        state["hooks"]["preMatcher"] = "^(run_command|bash|write_file|edit_file|sed_file)$"
        return state

    if preset_id == "recipe_windows_enterprise":
        state["os_list"] = ["windows"]
        state["surfaces"] = ["cli", "desktop", "ide"]
        state["gateway"]["caCertPath"] = ""
        state["gateway_env"]["caCert"] = ""
        state["acp"]["command"] = "C:\\Program Files\\Antigravity\\bin\\agy.exe"
        state["hooks"]["preCommand"] = (
            "powershell.exe -NoProfile -ExecutionPolicy Bypass "
            "-File C:\\ProgramData\\Antigravity\\bin\\agy_security_guard.ps1 pre"
        )
        state["hooks"]["postCommand"] = (
            "powershell.exe -NoProfile -ExecutionPolicy Bypass "
            "-File C:\\ProgramData\\Antigravity\\bin\\agy_security_guard.ps1 post"
        )
        win_allow = [
            "command(echo)",
            "unsandboxed(echo)",
            "command(git status)",
            "unsandboxed(git status)",
            "command(pytest)",
            "unsandboxed(pytest)",
            r"command(regex:^(?i)(echo|write-output|write-host|ls|get-childitem|pwd|get-location)(\s+[^;&|`$()\r\n>]*)?$)",
            r"unsandboxed(regex:^(?i)(echo|write-output|write-host|ls|get-childitem|pwd|get-location)(\s+[^;&|`$()\r\n>]*)?$)",
            r"command(regex:^git\s+(status|diff|log)(\s+[^;&|`$()\r\n>]*)?$)",
            r"unsandboxed(regex:^git\s+(status|diff|log)(\s+[^;&|`$()\r\n>]*)?$)",
            r"command(regex:^pytest(\s+[^;&|`$()\r\n>]*)?$)",
            r"unsandboxed(regex:^pytest(\s+[^;&|`$()\r\n>]*)?$)",
        ]
        win_deny = [
            "command(rm)",
            "command(del)",
            "command(Remove-Item)",
            "command(icacls)",
            "command(takeown)",
            "command(attrib)",
            "command(reg)",
            "command(schtasks)",
        ]
        state["cli"]["permissions"] = {"allow": list(win_allow), "ask": [], "deny": list(win_deny)}
        state["desktop"]["permissions"] = {"allow": list(win_allow), "ask": [], "deny": list(win_deny)}
        return state

    if preset_id == "recipe_jetbrains_zed_acp":
        state["surfaces"] = ["ide"]
        state["gateway"]["wireProtocol"] = "genai"
        state["gateway_env"]["wireProtocol"] = "genai"
        return state

    return state


# ==============================================================================
# BLOCK 3: ACTIVE SCOPE RESOLUTION & FILE RENDERERS
# ==============================================================================
def get_active_file_ids(
    os_list: list[str],
    surfaces: list[str],
    allow_empty: bool = False,
) -> list[str]:
    """Filter the canonical file catalog to files matching the active OS & surface.

    Summary:
        Returns the ordered list of `file_id` values whose supported `os` and
        `surfaces` intersect the administrator's selected OS and surface scopes.
    Parameters:
        os_list (list[str]): Selected operating systems.
        surfaces (list[str]): Selected Antigravity surfaces.
        allow_empty (bool): When `True`, returns `[]` if `os_list` or `surfaces`
            is empty (used by progressive step-by-step UI).
    Return Value:
        list[str]: Matching canonical file IDs in catalog order.
    Exceptions/Errors:
        None.
    """
    if allow_empty and (not os_list or not surfaces):
        return []
    os_set = set(os_list or ALL_OS)
    surf_set = set(surfaces or ALL_SURFACES)
    active: list[str] = []
    for item in FILE_CATALOG:
        if os_set.intersection(item["os"]) and surf_set.intersection(item["surfaces"]):
            active.append(item["id"])
    return active


def _merge_extra_keys(base_obj: dict[str, Any], extra_obj: dict[str, Any] | None) -> dict[str, Any]:
    """Overlay preserved custom/unknown JSON keys onto a rendered config dict.

    Summary:
        Recursively merges unknown/custom JSON properties imported or typed by
        an administrator in the raw code editor so nested custom fields (for
        example under `gateway`, `models`, `userSettings`, `mcpServers.<name>`,
        `hooks`, or `agent_servers.Antigravity`) survive visual form edits.
    Parameters:
        base_obj (dict[str, Any]): Newly compiled canonical JSON object.
        extra_obj (dict[str, Any] | None): Previously preserved unknown keys.
    Return Value:
        dict[str, Any]: Deep-merged dictionary with canonical keys taking
        precedence over stale custom keys at each dictionary level.
    Exceptions/Errors:
        None.
    """
    if not isinstance(extra_obj, dict) or not extra_obj:
        return base_obj
    merged = copy.deepcopy(extra_obj)
    for k, v in base_obj.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = _merge_extra_keys(v, merged[k])
        else:
            merged[k] = copy.deepcopy(v)
    return merged


def _extract_session_banner_text(sess_arr: Any, fallback: str) -> str:
    """Extract `ephemeralMessage` text from a `SessionStart` hook array.

    Summary:
        Parses `hooks.SessionStart[0].hooks[0].command` (such as
        `printf '%s\\n' '{"injectSteps": [{"ephemeralMessage": "..."}]}'`) back
        into `hooks.sessionBannerText` so raw `hooks.json` edits sync cleanly
        to the Left-Pane Compliance Banner input.
    Parameters:
        sess_arr (Any): Parsed `hooks.SessionStart` JSON value.
        fallback (str): Previous `sessionBannerText` fallback if unparseable.
    Return Value:
        str: Extracted banner string or `fallback`.
    Exceptions/Errors:
        None.
    """
    if not (isinstance(sess_arr, list) and sess_arr and isinstance(sess_arr[0], dict)):
        return fallback
    inner_hooks = sess_arr[0].get("hooks")
    if not (isinstance(inner_hooks, list) and inner_hooks and isinstance(inner_hooks[0], dict)):
        return fallback
    cmd = str(inner_hooks[0].get("command", ""))
    if not cmd:
        return fallback

    # Try single-quoted printf payload first (unescaping POSIX '\'' sequences)
    sq_match = re.search(r"printf\s+(?:'%s\\n'|\"%s\\n\")\s+'(.*)'\s*$", cmd, flags=re.DOTALL)
    candidate_json = sq_match.group(1).replace("'\\''", "'") if sq_match else ""
    if candidate_json:
        try:
            payload_obj = json.loads(candidate_json)
            steps = payload_obj.get("injectSteps") if isinstance(payload_obj, dict) else None
            if isinstance(steps, list) and steps and isinstance(steps[0], dict) and "ephemeralMessage" in steps[0]:
                return str(steps[0]["ephemeralMessage"])
        except json.JSONDecodeError:
            pass

    # Fallback regex extraction if user formatted the echo/printf command differently
    msg_match = re.search(r'"ephemeralMessage"\s*:\s*"((?:\\.|[^"\\])*)"', cmd)
    if msg_match:
        try:
            return str(json.loads(f'"{msg_match.group(1)}"'))
        except json.JSONDecodeError:
            return msg_match.group(1)
    return fallback


def render_single_file(file_id: str, state: dict[str, Any]) -> str:
    """Compile a single canonical Antigravity file from the structured state.

    Summary:
        Renders deterministic, BOM-free UTF-8 output for `file_id`, applying
        cross-surface permission sync (`sync_permissions`) and merging any
        preserved custom JSON keys or extra `.env` entries.
    Parameters:
        file_id (str): Canonical studio file identifier.
        state (dict[str, Any]): Current structured studio state.
    Return Value:
        str: Formatted configuration file content.
    Exceptions/Errors:
        KeyError: If `file_id` is not recognized.
    """
    gw = state.get("gateway", {})
    env_cfg = state.get("gateway_env", {})
    cli_cfg = state.get("cli", {})
    desk_cfg = state.get("desktop", {})
    hooks_cfg = state.get("hooks", {})
    acp_cfg = state.get("acp", {})
    extra_all = state.get("extra_json_keys", {})
    sync_perms = bool(state.get("sync_permissions", True))

    if file_id == "admin_settings":
        headers_dict = {
            str(h.get("key", "")).strip(): str(h.get("value", "")).strip()
            for h in gw.get("customHeaders", [])
            if isinstance(h, dict) and str(h.get("key", "")).strip()
        }
        gw_block: dict[str, Any] = {
            "enabled": bool(gw.get("enabled", True)),
            "url": str(gw.get("url", "")).strip(),
        }
        if not gw.get("omitApiKeyInMdm", False) and str(gw.get("apiKey", "")).strip():
            gw_block["apiKey"] = str(gw.get("apiKey", "")).strip()
        gw_block["wireProtocol"] = str(gw.get("wireProtocol", "genai")).strip() or "genai"
        if headers_dict:
            gw_block["customHeaders"] = headers_dict

        models_list: list[dict[str, str]] = []
        for m in gw.get("models", []):
            if isinstance(m, dict) and str(m.get("modelId", "")).strip():
                entry: dict[str, str] = {"modelId": str(m["modelId"]).strip()}
                if str(m.get("displayName", "")).strip():
                    entry["displayName"] = str(m["displayName"]).strip()
                models_list.append(entry)

        doc: dict[str, Any] = {}
        ca_path = str(gw.get("caCertPath", "")).strip()
        if ca_path:
            doc["caCertPath"] = ca_path
        doc["gateway"] = gw_block
        raw_default_model = gw.get("defaultModelId")
        default_model_str = "gemini-3.8-flash" if raw_default_model is None else str(raw_default_model).strip()
        doc["models"] = {
            "defaultModelId": default_model_str,
            "list": models_list,
        }
        doc = _merge_extra_keys(doc, extra_all.get("admin_settings"))
        return json.dumps(doc, indent=2) + "\n"

    if file_id == "gateway_env":
        pfx = "export " if env_cfg.get("exportPrefix", True) else ""
        lines = [
            "# ==============================================================================",
            "# Antigravity Tier-2 Enterprise Gateway Environment Configuration",
            "# Linux: /etc/profile.d/antigravity-gateway.sh | macOS: /etc/zshrc | Windows: HKLM Env",
            "# ==============================================================================",
            f'{pfx}AGY_LLM_GATEWAY_URL="{env_cfg.get("url", "")}"',
            f'{pfx}AGY_LLM_GATEWAY_API_KEY="{env_cfg.get("apiKey", "")}"',
            f'{pfx}AGY_LLM_GATEWAY_WIRE_PROTOCOL="{env_cfg.get("wireProtocol", "genai") or "genai"}"',
        ]
        if str(env_cfg.get("caCert", "")).strip():
            lines.append(f'{pfx}AGY_LLM_GATEWAY_CA_CERT="{env_cfg.get("caCert", "").strip()}"')
        if str(env_cfg.get("headers", "")).strip():
            lines.append(f'{pfx}AGY_LLM_GATEWAY_HEADERS="{env_cfg.get("headers", "").strip()}"')
        if str(env_cfg.get("models", "")).strip():
            lines.append(f'{pfx}AGY_LLM_GATEWAY_MODELS="{env_cfg.get("models", "").strip()}"')
        for extra_ln in env_cfg.get("extraLines", []):
            if str(extra_ln).strip():
                lines.append(str(extra_ln).strip())
        return "\n".join(lines) + "\n"

    if file_id == "cli_settings":
        perms = cli_cfg.get("permissions", {"allow": [], "ask": [], "deny": []})
        doc = {
            "agentMode": str(cli_cfg.get("agentMode", "plan")),
            "allowNonWorkspaceAccess": bool(cli_cfg.get("allowNonWorkspaceAccess", False)),
            "artifactReviewPolicy": str(cli_cfg.get("artifactReviewPolicy", "asks-for-review")),
            "enableTerminalSandbox": bool(cli_cfg.get("enableTerminalSandbox", True)),
            "permissions": {
                "allow": list(perms.get("allow", [])),
                "ask": list(perms.get("ask", [])),
                "deny": list(perms.get("deny", [])),
            },
            "toolPermission": str(cli_cfg.get("toolPermission", "proceed-in-sandbox")),
        }
        if cli_cfg.get("includeOptionalUiKeys", False) or cli_cfg.get("historySize", 50) != 50:
            doc["historySize"] = int(cli_cfg.get("historySize", 50))
        if cli_cfg.get("includeOptionalUiKeys", False):
            doc["notifications"] = bool(cli_cfg.get("notifications", False))
            doc["showFeedbackSurvey"] = bool(cli_cfg.get("showFeedbackSurvey", False))
            doc["showTips"] = bool(cli_cfg.get("showTips", False))

        if cli_cfg.get("sandboxProxyEnabled", False) or str(cli_cfg.get("sandboxProxyAddress", "")).strip():
            http_proxy: dict[str, str] = {
                "address": str(cli_cfg.get("sandboxProxyAddress", "")).strip(),
                "certFile": str(cli_cfg.get("sandboxProxyCertFile", "")).strip(),
            }
            if str(cli_cfg.get("sandboxProxyUsername", "")).strip():
                http_proxy["username"] = str(cli_cfg.get("sandboxProxyUsername", "")).strip()
            if str(cli_cfg.get("sandboxProxyPassword", "")).strip():
                http_proxy["password"] = str(cli_cfg.get("sandboxProxyPassword", "")).strip()
            doc["sandboxProxy"] = {"http": http_proxy}

        doc = _merge_extra_keys(doc, extra_all.get("cli_settings"))
        return json.dumps(doc, indent=2) + "\n"

    if file_id == "desktop_config":
        source_perms = (
            cli_cfg.get("permissions", {})
            if sync_perms
            else desk_cfg.get("permissions", {})
        )
        us: dict[str, Any] = {
            "autoExecutionPolicy": str(
                desk_cfg.get("autoExecutionPolicy", "CASCADE_COMMANDS_AUTO_EXECUTION_PROCEED_IN_SANDBOX")
            ),
            "artifactReviewMode": str(desk_cfg.get("artifactReviewMode", "ARTIFACT_REVIEW_MODE_ALWAYS")),
            "browserJsExecutionPolicy": str(
                desk_cfg.get("browserJsExecutionPolicy", "BROWSER_JS_EXECUTION_POLICY_DISABLED")
            ),
            "enableTerminalSandbox": bool(desk_cfg.get("enableTerminalSandbox", True)),
            "globalPermissionGrants": {
                "allow": list(source_perms.get("allow", [])),
                "ask": list(source_perms.get("ask", [])),
                "deny": list(source_perms.get("deny", [])),
            },
            "sandboxAllowNetwork": bool(desk_cfg.get("sandboxAllowNetwork", False)),
        }
        if str(desk_cfg.get("nonWorkspaceFileAccessPolicy", "")).strip():
            us["nonWorkspaceFileAccessPolicy"] = str(desk_cfg["nonWorkspaceFileAccessPolicy"]).strip()
        if str(desk_cfg.get("internetAccessPolicy", "")).strip():
            us["internetAccessPolicy"] = str(desk_cfg["internetAccessPolicy"]).strip()

        doc = _merge_extra_keys({"userSettings": us}, extra_all.get("desktop_config"))
        return json.dumps(doc, indent=2) + "\n"

    if file_id == "browser_allowlist":
        header = [
            "# ==============================================================================",
            "# File: ~/.gemini/antigravity/browserAllowlist.txt",
            "# Trusted hostnames/domains for the Antigravity Browser Subagent",
            "# ==============================================================================",
        ]
        domains = [str(d).strip() for d in state.get("browser_domains", []) if str(d).strip()]
        return "\n".join(header + domains) + "\n"

    if file_id == "mcp_config":
        servers_dict: dict[str, Any] = {}
        for srv in state.get("mcp_servers", []):
            if not isinstance(srv, dict) or not str(srv.get("name", "")).strip():
                continue
            name = str(srv["name"]).strip()
            entry_cfg: dict[str, Any] = copy.deepcopy(srv["extra"]) if isinstance(srv.get("extra"), dict) else {}
            if srv.get("transport") == "http" or str(srv.get("serverUrl", "")).strip():
                entry_cfg.pop("command", None)
                entry_cfg.pop("args", None)
                entry_cfg["serverUrl"] = str(srv.get("serverUrl", "")).strip()
            else:
                entry_cfg.pop("serverUrl", None)
                entry_cfg.pop("url", None)
                entry_cfg["command"] = str(srv.get("command", "")).strip()
                entry_cfg["args"] = [str(a) for a in srv.get("args", []) if str(a).strip()]
            entry_cfg["disabled"] = bool(srv.get("disabled", True))
            if srv.get("timeoutSeconds") is not None and srv.get("timeoutSeconds") != "":
                entry_cfg["timeoutSeconds"] = int(srv["timeoutSeconds"])
            if "enabledTools" in srv and isinstance(srv["enabledTools"], list):
                entry_cfg["enabledTools"] = [str(t).strip() for t in srv["enabledTools"] if str(t).strip()]
            if "disabledTools" in srv and isinstance(srv["disabledTools"], list):
                entry_cfg["disabledTools"] = [str(t).strip() for t in srv["disabledTools"] if str(t).strip()]
            if isinstance(srv.get("env"), dict) and srv["env"]:
                entry_cfg["env"] = dict(srv["env"])
            if isinstance(srv.get("tools"), dict) and srv["tools"]:
                entry_cfg["tools"] = copy.deepcopy(srv["tools"])
            servers_dict[name] = entry_cfg

        doc = _merge_extra_keys({"mcpServers": servers_dict}, extra_all.get("mcp_config"))
        return json.dumps(doc, indent=2) + "\n"

    if file_id == "hooks_config":
        hooks_map: dict[str, Any] = {}
        if hooks_cfg.get("enableSessionStartBanner", False):
            banner_msg = str(hooks_cfg.get("sessionBannerText", "")).strip()
            banner_payload = json.dumps({"injectSteps": [{"ephemeralMessage": banner_msg}]})
            # Escape single quotes using standard POSIX '\'' idiom so apostrophes in banners never break bash/sh
            safe_banner_payload = banner_payload.replace("'", "'\\''")
            hooks_map["SessionStart"] = [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"printf '%s\\n' '{safe_banner_payload}'",
                            "timeout": 5,
                        }
                    ],
                }
            ]
        if hooks_cfg.get("enablePreToolUse", True):
            hooks_map["PreToolUse"] = [
                {
                    "matcher": str(hooks_cfg.get("preMatcher", ".*")).strip() or ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": str(hooks_cfg.get("preCommand", "/usr/local/bin/agy_security_guard.sh pre")).strip(),
                            "timeout": int(hooks_cfg.get("preTimeout", 10)),
                        }
                    ],
                }
            ]
        if hooks_cfg.get("enablePostToolUse", True):
            hooks_map["PostToolUse"] = [
                {
                    "matcher": str(hooks_cfg.get("postMatcher", ".*")).strip() or ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": str(hooks_cfg.get("postCommand", "/usr/local/bin/agy_security_guard.sh post")).strip(),
                            "timeout": int(hooks_cfg.get("postTimeout", 10)),
                        }
                    ],
                }
            ]
        doc = _merge_extra_keys({"hooks": hooks_map}, extra_all.get("hooks_config"))
        return json.dumps(doc, indent=2) + "\n"

    if file_id == "guard_sh":
        return str(state.get("scripts", {}).get("guard_sh", DEFAULT_GUARD_SH)).lstrip("\ufeff")

    if file_id == "guard_ps1":
        return str(state.get("scripts", {}).get("guard_ps1", DEFAULT_GUARD_PS1)).lstrip("\ufeff")

    if file_id == "acp_json":
        headers_kv = ",".join(
            f'{h["key"]}: {h["value"]}'
            for h in gw.get("customHeaders", [])
            if isinstance(h, dict) and str(h.get("key", "")).strip()
        )
        models_csv = ",".join(
            str(m["modelId"]).strip()
            for m in gw.get("models", [])
            if isinstance(m, dict) and str(m.get("modelId", "")).strip()
        )
        acp_env: dict[str, str] = {}
        if isinstance(acp_cfg.get("extraEnv"), dict):
            for ek, ev in acp_cfg["extraEnv"].items():
                acp_env[str(ek)] = str(ev)
        acp_env["AGY_LLM_GATEWAY_URL"] = str(gw.get("url", "https://REPLACE_WITH_GATEWAY_URL")).strip()
        acp_env["AGY_LLM_GATEWAY_API_KEY"] = str(
            gw.get("apiKey") or env_cfg.get("apiKey") or "REPLACE_WITH_GATEWAY_API_KEY"
        ).strip()
        acp_env["AGY_LLM_GATEWAY_WIRE_PROTOCOL"] = str(gw.get("wireProtocol", "genai")).strip() or "genai"
        if str(gw.get("caCertPath", "")).strip():
            acp_env["AGY_LLM_GATEWAY_CA_CERT"] = str(gw.get("caCertPath", "")).strip()
        if headers_kv:
            acp_env["AGY_LLM_GATEWAY_HEADERS"] = headers_kv
        if models_csv:
            acp_env["AGY_LLM_GATEWAY_MODELS"] = models_csv

        raw_args = acp_cfg.get("args")
        acp_args = (
            [str(a) for a in raw_args if str(a).strip()]
            if isinstance(raw_args, list)
            else ["acp"]
        )
        doc = {
            "agent_servers": {
                "Antigravity": {
                    "command": str(acp_cfg.get("command", "/usr/local/bin/agy")).strip(),
                    "args": acp_args,
                    "env": acp_env,
                }
            }
        }
        doc = _merge_extra_keys(doc, extra_all.get("acp_json"))
        return json.dumps(doc, indent=2) + "\n"

    if file_id == "acp_auth":
        doc = {"auth": {"type": str(acp_cfg.get("authType", "gateway")).strip() or "gateway"}}
        doc = _merge_extra_keys(doc, extra_all.get("acp_auth"))
        return json.dumps(doc, indent=2) + "\n"

    raise KeyError(f"Unsupported file_id: {file_id}")


# ==============================================================================
# BLOCK 4: TWO-WAY PARSER (RAW CODE / IMPORT -> STRUCTURED STATE)
# ==============================================================================
def parse_file_into_state_with_status(
    file_id: str,
    raw_text: str,
    current_state: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Parse raw text edits or an imported file into structured state with sync status.

    Summary:
        Implements the reverse half of two-way Form <-> Code synchronization
        across all 11 canonical files. Symmetrically reflects property additions,
        updates, AND deletions (for example removing `customHeaders`, optional
        `.env` lines, `historySize`, `timeoutSeconds`, or `SessionStart` hooks)
        while preserving unknown JSON properties in `state["extra_json_keys"]`.
    Parameters:
        file_id (str): Canonical studio file identifier.
        raw_text (str): Raw text from the code editor or file upload.
        current_state (dict[str, Any]): Existing studio state to update.
    Return Value:
        tuple[dict[str, Any], bool]: `(updated_state, code_synced)` where
        `code_synced` is `False` when a JSON file contains mid-edit syntax errors
        or a non-object top-level value so the UI can warn accurately instead of
        falsely reporting `"Two-Way Synced"`.
    Exceptions/Errors:
        None.
    """
    state = copy.deepcopy(current_state)
    clean_text = (raw_text or "").lstrip("\ufeff")
    extra_all = state.setdefault("extra_json_keys", {})
    sync_perms = bool(state.get("sync_permissions", True))

    if file_id == "guard_sh":
        state.setdefault("scripts", {})["guard_sh"] = clean_text
        return state, True

    if file_id == "guard_ps1":
        state.setdefault("scripts", {})["guard_ps1"] = clean_text
        return state, True

    if file_id == "browser_allowlist":
        domains: list[str] = []
        for ln in clean_text.splitlines():
            st = ln.strip()
            if st and not st.startswith("#"):
                domains.append(st)
        state["browser_domains"] = domains
        return state, True

    if file_id == "gateway_env":
        env_state = state.setdefault("gateway_env", {})
        has_any_gw_var = bool(re.search(r"^(?:export\s+)?AGY_LLM_GATEWAY_[A-Z_]+=", clean_text, flags=re.MULTILINE))
        if has_any_gw_var:
            env_state["exportPrefix"] = bool(
                re.search(r"^export\s+AGY_LLM_GATEWAY_[A-Z_]+=", clean_text, flags=re.MULTILINE)
            )
        mapping = {
            "AGY_LLM_GATEWAY_URL": ("url", ""),
            "AGY_LLM_GATEWAY_API_KEY": ("apiKey", ""),
            "AGY_LLM_GATEWAY_WIRE_PROTOCOL": ("wireProtocol", "genai"),
            "AGY_LLM_GATEWAY_CA_CERT": ("caCert", ""),
            "AGY_LLM_GATEWAY_HEADERS": ("headers", ""),
            "AGY_LLM_GATEWAY_MODELS": ("models", ""),
        }
        for env_key, (field_name, default_val) in mapping.items():
            m = re.search(rf"^(?:export\s+)?{env_key}=(.*)$", clean_text, flags=re.MULTILINE)
            if m:
                parsed_val = m.group(1).strip().strip('"').strip("'")
                env_state[field_name] = parsed_val or default_val
            else:
                # Reset deleted or commented-out env vars so form & recompile reflect deletion
                env_state[field_name] = default_val

        extra_lines: list[str] = []
        known_prefixes = tuple(mapping.keys())
        for raw_ln in clean_text.splitlines():
            st_ln = raw_ln.strip()
            if not st_ln or st_ln.startswith("#"):
                continue
            unprefixed = re.sub(r"^export\s+", "", st_ln)
            key_part = unprefixed.split("=", 1)[0].strip()
            if key_part not in known_prefixes:
                extra_lines.append(st_ln)
        env_state["extraLines"] = extra_lines
        return state, True

    # Parse JSON files
    try:
        parsed = json.loads(clean_text)
    except json.JSONDecodeError:
        return state, False
    if not isinstance(parsed, dict):
        return state, False

    if file_id == "admin_settings":
        gw_state = state.setdefault("gateway", {})
        env_state = state.setdefault("gateway_env", {})
        gw_obj = parsed.get("gateway") if isinstance(parsed.get("gateway"), dict) else {}
        gw_state["caCertPath"] = str(parsed.get("caCertPath") or gw_obj.get("caCertPath") or "")
        gw_state["enabled"] = bool(gw_obj.get("enabled", True))
        gw_state["url"] = str(gw_obj.get("url", ""))
        if "apiKey" in gw_obj:
            gw_state["apiKey"] = str(gw_obj.get("apiKey", ""))
            gw_state["omitApiKeyInMdm"] = False
        else:
            gw_state["omitApiKeyInMdm"] = True
        gw_state["wireProtocol"] = str(gw_obj.get("wireProtocol", "genai")) or "genai"

        # Keep Tier-2 env URL & wireProtocol aligned just like Left-Pane admin_settings form inputs
        env_state["url"] = gw_state["url"]
        env_state["wireProtocol"] = gw_state["wireProtocol"]

        hdrs = gw_obj.get("customHeaders")
        if isinstance(hdrs, dict):
            gw_state["customHeaders"] = [{"key": str(k), "value": str(v)} for k, v in hdrs.items()]
        else:
            gw_state["customHeaders"] = []

        if isinstance(parsed.get("models"), dict):
            models_obj = parsed["models"]
            gw_state["defaultModelId"] = str(models_obj.get("defaultModelId") or "")
            if isinstance(models_obj.get("list"), list):
                parsed_models: list[dict[str, str]] = []
                for item in models_obj["list"]:
                    if isinstance(item, dict) and item.get("modelId"):
                        parsed_models.append(
                            {
                                "modelId": str(item["modelId"]),
                                "displayName": str(item.get("displayName", "")),
                            }
                        )
                    elif isinstance(item, str) and item.strip():
                        parsed_models.append({"modelId": item.strip(), "displayName": ""})
                gw_state["models"] = parsed_models
            else:
                gw_state["models"] = []
        elif isinstance(gw_obj.get("models"), dict) and isinstance(gw_obj["models"].get("filter"), list):
            # Support Preview v2.0 nested models.filter on import prior to Auto-Fix
            gw_state["models"] = [
                {"modelId": str(m).strip(), "displayName": ""}
                for m in gw_obj["models"]["filter"]
                if str(m).strip()
            ]
        else:
            gw_state["defaultModelId"] = ""
            gw_state["models"] = []

        known_root = {"caCertPath", "gateway", "models"}
        extra: dict[str, Any] = {k: v for k, v in parsed.items() if k not in known_root}
        if isinstance(parsed.get("models"), dict):
            extra_models = {k: v for k, v in parsed["models"].items() if k not in {"defaultModelId", "list"}}
            if extra_models:
                extra["models"] = extra_models
        if isinstance(parsed.get("gateway"), dict):
            extra_gw = {
                k: v
                for k, v in parsed["gateway"].items()
                if k not in {"enabled", "url", "apiKey", "wireProtocol", "customHeaders"}
            }
            if extra_gw:
                extra["gateway"] = extra_gw
        extra_all["admin_settings"] = extra

    elif file_id == "cli_settings":
        cli_state = state.setdefault("cli", {})
        cli_state["agentMode"] = str(parsed.get("agentMode", "")) if "agentMode" in parsed else "plan"
        cli_state["toolPermission"] = str(parsed.get("toolPermission", "proceed-in-sandbox"))
        cli_state["artifactReviewPolicy"] = str(parsed.get("artifactReviewPolicy", "asks-for-review"))
        cli_state["enableTerminalSandbox"] = bool(parsed.get("enableTerminalSandbox", True))
        cli_state["allowNonWorkspaceAccess"] = bool(parsed.get("allowNonWorkspaceAccess", False))

        has_opt_ui = any(k in parsed for k in ("notifications", "showFeedbackSurvey", "showTips"))
        cli_state["includeOptionalUiKeys"] = has_opt_ui
        cli_state["notifications"] = bool(parsed.get("notifications", False))
        cli_state["showFeedbackSurvey"] = bool(parsed.get("showFeedbackSurvey", False))
        cli_state["showTips"] = bool(parsed.get("showTips", False))
        if (
            "historySize" in parsed
            and isinstance(parsed["historySize"], int)
            and not isinstance(parsed["historySize"], bool)
        ):
            cli_state["historySize"] = int(parsed["historySize"])
        else:
            cli_state["historySize"] = 50

        sbp = parsed.get("sandboxProxy")
        if isinstance(sbp, dict) and isinstance(sbp.get("http"), dict):
            h = sbp["http"]
            cli_state["sandboxProxyEnabled"] = True
            cli_state["sandboxProxyAddress"] = str(h.get("address", ""))
            cli_state["sandboxProxyCertFile"] = str(h.get("certFile", ""))
            cli_state["sandboxProxyUsername"] = str(h.get("username", ""))
            cli_state["sandboxProxyPassword"] = str(h.get("password", ""))
        else:
            cli_state["sandboxProxyEnabled"] = False
            cli_state["sandboxProxyAddress"] = ""
            cli_state["sandboxProxyCertFile"] = ""
            cli_state["sandboxProxyUsername"] = ""
            cli_state["sandboxProxyPassword"] = ""

        perms_obj = parsed.get("permissions")
        norm_perms = (
            {
                "allow": [str(x) for x in perms_obj.get("allow", []) if isinstance(x, str)],
                "ask": [str(x) for x in perms_obj.get("ask", []) if isinstance(x, str)],
                "deny": [str(x) for x in perms_obj.get("deny", []) if isinstance(x, str)],
            }
            if isinstance(perms_obj, dict)
            else {"allow": [], "ask": [], "deny": []}
        )
        cli_state["permissions"] = norm_perms
        if sync_perms:
            state.setdefault("desktop", {})["permissions"] = copy.deepcopy(norm_perms)

        known_cli = {
            "agentMode",
            "allowNonWorkspaceAccess",
            "artifactReviewPolicy",
            "enableTerminalSandbox",
            "permissions",
            "toolPermission",
            "historySize",
            "notifications",
            "showFeedbackSurvey",
            "showTips",
            "sandboxProxy",
        }
        extra_cli: dict[str, Any] = {k: v for k, v in parsed.items() if k not in known_cli}
        if isinstance(sbp, dict):
            extra_sbp = {k: v for k, v in sbp.items() if k != "http"}
            if isinstance(sbp.get("http"), dict):
                extra_http = {
                    k: v
                    for k, v in sbp["http"].items()
                    if k not in {"address", "certFile", "username", "password"}
                }
                if extra_http:
                    extra_sbp["http"] = extra_http
            if extra_sbp:
                extra_cli["sandboxProxy"] = extra_sbp
        extra_all["cli_settings"] = extra_cli

    elif file_id == "desktop_config":
        desk_state = state.setdefault("desktop", {})
        us = parsed.get("userSettings") if isinstance(parsed.get("userSettings"), dict) else {}
        desk_state["autoExecutionPolicy"] = str(
            us.get("autoExecutionPolicy", "CASCADE_COMMANDS_AUTO_EXECUTION_PROCEED_IN_SANDBOX")
        )
        desk_state["artifactReviewMode"] = str(us.get("artifactReviewMode", "ARTIFACT_REVIEW_MODE_ALWAYS"))
        desk_state["browserJsExecutionPolicy"] = str(
            us.get("browserJsExecutionPolicy", "BROWSER_JS_EXECUTION_POLICY_DISABLED")
        )
        desk_state["nonWorkspaceFileAccessPolicy"] = str(us.get("nonWorkspaceFileAccessPolicy", ""))
        desk_state["internetAccessPolicy"] = str(us.get("internetAccessPolicy", ""))
        desk_state["enableTerminalSandbox"] = bool(us.get("enableTerminalSandbox", True))
        desk_state["sandboxAllowNetwork"] = bool(us.get("sandboxAllowNetwork", False))

        grants = us.get("globalPermissionGrants")
        norm_grants = (
            {
                "allow": [str(x) for x in grants.get("allow", []) if isinstance(x, str)],
                "ask": [str(x) for x in grants.get("ask", []) if isinstance(x, str)],
                "deny": [str(x) for x in grants.get("deny", []) if isinstance(x, str)],
            }
            if isinstance(grants, dict)
            else {"allow": [], "ask": [], "deny": []}
        )
        desk_state["permissions"] = norm_grants
        if sync_perms:
            state.setdefault("cli", {})["permissions"] = copy.deepcopy(norm_grants)

        known_us = {
            "autoExecutionPolicy",
            "artifactReviewMode",
            "browserJsExecutionPolicy",
            "nonWorkspaceFileAccessPolicy",
            "internetAccessPolicy",
            "enableTerminalSandbox",
            "sandboxAllowNetwork",
            "globalPermissionGrants",
        }
        extra_desk: dict[str, Any] = {k: v for k, v in parsed.items() if k != "userSettings"}
        extra_us = {k: v for k, v in us.items() if k not in known_us}
        if extra_us:
            extra_desk["userSettings"] = extra_us
        extra_all["desktop_config"] = extra_desk

    elif file_id == "mcp_config":
        servers_in = parsed.get("mcpServers")
        known_srv_keys = {
            "serverUrl",
            "url",
            "command",
            "args",
            "disabled",
            "timeoutSeconds",
            "enabledTools",
            "disabledTools",
            "env",
            "tools",
        }
        if isinstance(servers_in, dict):
            new_servers: list[dict[str, Any]] = []
            for sname, scfg in servers_in.items():
                if not isinstance(scfg, dict):
                    continue
                srv_url = str(scfg.get("serverUrl") or scfg.get("url") or "")
                raw_timeout = scfg.get("timeoutSeconds")
                timeout_val = (
                    int(raw_timeout)
                    if isinstance(raw_timeout, (int, float)) and not isinstance(raw_timeout, bool)
                    else None
                )
                srv_entry: dict[str, Any] = {
                    "name": str(sname),
                    "transport": "http" if srv_url else "stdio",
                    "command": str(scfg.get("command", "")),
                    "args": [str(a) for a in scfg.get("args", [])] if isinstance(scfg.get("args"), list) else [],
                    "serverUrl": srv_url,
                    "disabled": bool(scfg.get("disabled", False)),
                    "timeoutSeconds": timeout_val,
                    "enabledTools": list(scfg.get("enabledTools", [])) if isinstance(scfg.get("enabledTools"), list) else [],
                    "disabledTools": list(scfg.get("disabledTools", [])) if isinstance(scfg.get("disabledTools"), list) else [],
                    "env": dict(scfg.get("env", {})) if isinstance(scfg.get("env"), dict) else {},
                    "tools": copy.deepcopy(scfg.get("tools", {})) if isinstance(scfg.get("tools"), dict) else {},
                    "extra": {k: copy.deepcopy(v) for k, v in scfg.items() if k not in known_srv_keys},
                }
                new_servers.append(srv_entry)
            state["mcp_servers"] = new_servers
        else:
            state["mcp_servers"] = []
        extra_all["mcp_config"] = {k: v for k, v in parsed.items() if k != "mcpServers"}

    elif file_id == "hooks_config":
        hooks_state = state.setdefault("hooks", {})
        hooks_obj = parsed.get("hooks") if isinstance(parsed.get("hooks"), dict) else {}

        pre_arr = hooks_obj.get("PreToolUse")
        if isinstance(pre_arr, list) and pre_arr and isinstance(pre_arr[0], dict):
            hooks_state["enablePreToolUse"] = True
            hooks_state["preMatcher"] = str(pre_arr[0].get("matcher", ".*"))
            inner_h = pre_arr[0].get("hooks", [])
            if isinstance(inner_h, list) and inner_h and isinstance(inner_h[0], dict):
                hooks_state["preCommand"] = str(inner_h[0].get("command", ""))
                hooks_state["preTimeout"] = int(inner_h[0].get("timeout", 10))
        else:
            hooks_state["enablePreToolUse"] = False

        post_arr = hooks_obj.get("PostToolUse")
        if isinstance(post_arr, list) and post_arr and isinstance(post_arr[0], dict):
            hooks_state["enablePostToolUse"] = True
            hooks_state["postMatcher"] = str(post_arr[0].get("matcher", ".*"))
            inner_p = post_arr[0].get("hooks", [])
            if isinstance(inner_p, list) and inner_p and isinstance(inner_p[0], dict):
                hooks_state["postCommand"] = str(inner_p[0].get("command", ""))
                hooks_state["postTimeout"] = int(inner_p[0].get("timeout", 10))
        else:
            hooks_state["enablePostToolUse"] = False

        sess_arr = hooks_obj.get("SessionStart")
        if isinstance(sess_arr, list) and sess_arr:
            hooks_state["enableSessionStartBanner"] = True
            hooks_state["sessionBannerText"] = _extract_session_banner_text(
                sess_arr,
                str(hooks_state.get("sessionBannerText", "")),
            )
        else:
            hooks_state["enableSessionStartBanner"] = False

        extra_hooks: dict[str, Any] = {k: v for k, v in parsed.items() if k != "hooks"}
        unknown_hook_phases = {
            k: v for k, v in hooks_obj.items() if k not in {"PreToolUse", "PostToolUse", "SessionStart"}
        }
        if unknown_hook_phases:
            extra_hooks["hooks"] = unknown_hook_phases
        extra_all["hooks_config"] = extra_hooks

    elif file_id == "acp_json":
        acp_state = state.setdefault("acp", {})
        gw_state = state.setdefault("gateway", {})
        env_state = state.setdefault("gateway_env", {})
        agent_servers = parsed.get("agent_servers") if isinstance(parsed.get("agent_servers"), dict) else {}
        agy_srv = agent_servers.get("Antigravity") if isinstance(agent_servers.get("Antigravity"), dict) else {}
        if agy_srv:
            acp_state["command"] = str(agy_srv.get("command", ""))
            if isinstance(agy_srv.get("args"), list):
                acp_state["args"] = [str(a) for a in agy_srv["args"] if str(a).strip()]
            env_in = agy_srv.get("env")
            if isinstance(env_in, dict):
                known_acp_env = {
                    "AGY_LLM_GATEWAY_URL",
                    "AGY_LLM_GATEWAY_API_KEY",
                    "AGY_LLM_GATEWAY_WIRE_PROTOCOL",
                    "AGY_LLM_GATEWAY_CA_CERT",
                    "AGY_LLM_GATEWAY_HEADERS",
                    "AGY_LLM_GATEWAY_MODELS",
                }
                if "AGY_LLM_GATEWAY_URL" in env_in:
                    gw_state["url"] = str(env_in.get("AGY_LLM_GATEWAY_URL", ""))
                    env_state["url"] = gw_state["url"]
                if "AGY_LLM_GATEWAY_WIRE_PROTOCOL" in env_in:
                    gw_state["wireProtocol"] = str(env_in.get("AGY_LLM_GATEWAY_WIRE_PROTOCOL", "genai")) or "genai"
                    env_state["wireProtocol"] = gw_state["wireProtocol"]
                if "AGY_LLM_GATEWAY_API_KEY" in env_in:
                    key_val = str(env_in.get("AGY_LLM_GATEWAY_API_KEY", ""))
                    if gw_state.get("omitApiKeyInMdm", False):
                        env_state["apiKey"] = key_val
                    else:
                        gw_state["apiKey"] = key_val
                gw_state["caCertPath"] = str(env_in.get("AGY_LLM_GATEWAY_CA_CERT", ""))

                if "AGY_LLM_GATEWAY_HEADERS" in env_in and str(env_in["AGY_LLM_GATEWAY_HEADERS"]).strip():
                    parsed_hdrs: list[dict[str, str]] = []
                    for pair in str(env_in["AGY_LLM_GATEWAY_HEADERS"]).split(","):
                        if ":" in pair:
                            hk, hv = pair.split(":", 1)
                            if hk.strip():
                                parsed_hdrs.append({"key": hk.strip(), "value": hv.strip()})
                    gw_state["customHeaders"] = parsed_hdrs
                else:
                    gw_state["customHeaders"] = []

                if "AGY_LLM_GATEWAY_MODELS" in env_in and str(env_in["AGY_LLM_GATEWAY_MODELS"]).strip():
                    existing_names = {
                        str(m.get("modelId", "")): str(m.get("displayName", ""))
                        for m in gw_state.get("models", [])
                        if isinstance(m, dict)
                    }
                    gw_state["models"] = [
                        {"modelId": mid.strip(), "displayName": existing_names.get(mid.strip(), "")}
                        for mid in str(env_in["AGY_LLM_GATEWAY_MODELS"]).split(",")
                        if mid.strip()
                    ]
                elif "AGY_LLM_GATEWAY_MODELS" not in env_in:
                    gw_state["models"] = []

                acp_state["extraEnv"] = {
                    str(k): str(v) for k, v in env_in.items() if k not in known_acp_env
                }

        extra_acp: dict[str, Any] = {k: v for k, v in parsed.items() if k != "agent_servers"}
        extra_servers: dict[str, Any] = {k: v for k, v in agent_servers.items() if k != "Antigravity"}
        if agy_srv:
            extra_agy = {k: v for k, v in agy_srv.items() if k not in {"command", "args", "env"}}
            if extra_agy:
                extra_servers["Antigravity"] = extra_agy
        if extra_servers:
            extra_acp["agent_servers"] = extra_servers
        extra_all["acp_json"] = extra_acp

    elif file_id == "acp_auth":
        auth_obj = parsed.get("auth") if isinstance(parsed.get("auth"), dict) else {}
        state.setdefault("acp", {})["authType"] = str(auth_obj.get("type", "gateway")) or "gateway"
        extra_auth_doc: dict[str, Any] = {k: v for k, v in parsed.items() if k != "auth"}
        extra_auth_inner = {k: v for k, v in auth_obj.items() if k != "type"}
        if extra_auth_inner:
            extra_auth_doc["auth"] = extra_auth_inner
        extra_all["acp_auth"] = extra_auth_doc

    return state, True


def parse_file_into_state(
    file_id: str,
    raw_text: str,
    current_state: dict[str, Any],
) -> dict[str, Any]:
    """Parse raw text edits or an imported file into structured studio state.

    Summary:
        Compatibility wrapper around `parse_file_into_state_with_status`
        returning the updated studio state dictionary.
    Parameters:
        file_id (str): Canonical studio file identifier.
        raw_text (str): Raw text from the code editor or file upload.
        current_state (dict[str, Any]): Existing studio state to update.
    Return Value:
        dict[str, Any]: Updated studio state copy (returns `current_state`
        unchanged if JSON is mid-edit / syntactically invalid).
    Exceptions/Errors:
        None.
    """
    updated_state, _ = parse_file_into_state_with_status(file_id, raw_text, current_state)
    return updated_state


# ==============================================================================
# BLOCK 5: OS-SPECIFIC PER-FILE & BUNDLE ADMIN PERMISSIONS / LOCK COMMANDS
# ==============================================================================
def build_per_file_admin_commands(
    file_id: str,
    os_list: list[str],
    dev_user: str = "alice",
) -> dict[str, dict[str, str]]:
    """Generate manual file permission, lock, and unlock CLI commands for one file.

    Summary:
        Produces single-file OS deployment, ownership/permission (`chown`/`chmod`),
        `MarshalSparse` pre-init (for `cli_settings`), BOM-free UTF-8 write
        guidance (Windows), and kernel immutability (`chattr +i`, `chflags schg`,
        `attrib +R` + `icacls /deny`) commands displayed in the Left-Panel File
        Reference Card.
    Parameters:
        file_id (str): Canonical studio file identifier from `FILE_CATALOG`.
        os_list (list[str]): Selected operating systems.
        dev_user (str): Target workstation developer username.
    Return Value:
        dict[str, dict[str, str]]: Map of `os -> {"lock": str, "unlock": str}`
        for each applicable OS in `os_list`.
    Exceptions/Errors:
        None.
    """
    meta = FILE_CATALOG_BY_ID.get(file_id)
    if not meta:
        return {}
    u = (dev_user or "alice").strip() or "alice"
    per_os: dict[str, dict[str, str]] = {}

    if "linux" in os_list and "linux" in meta["os"]:
        lin_raw = meta["paths"]["linux"].replace("{user}", u)
        lin_target = lin_raw.split("  (")[0].strip()
        lin_parent = str(Path(lin_target).parent)
        is_root_file = lin_target.startswith(("/etc/", "/usr/"))
        owner = "root:root" if is_root_file else f"{u}:{u}"
        mode = "0755" if file_id == "guard_sh" else "0644"
        pre_init = (
            f"# Run MarshalSparse pre-init once BEFORE chattr +i so agy does not hit EPERM on startup\n"
            f"sudo -u {u} /usr/local/bin/agy --version >/dev/null 2>&1 || true\n\n"
            if file_id == "cli_settings"
            else ""
        )
        per_os["linux"] = {
            "lock": (
                f"# 1. Create parent directory and set file ownership & permissions\n"
                f'sudo mkdir -p "{lin_parent}"\n'
                f'sudo chown {owner} "{lin_target}"\n'
                f'sudo chmod {mode} "{lin_target}"\n\n'
                f"{pre_init}"
                f"# 2. Set Linux ext4/xfs immutable bit (blocks mv -f atomic rename)\n"
                f'sudo chattr +i "{lin_target}"\n'
                f'lsattr "{lin_target}"'
            ),
            "unlock": (
                f"# Remove immutable bit before editing or replacing file\n"
                f'sudo chattr -i "{lin_target}"'
            ),
        }

    if "macos" in os_list and "macos" in meta["os"]:
        mac_raw = meta["paths"]["macos"].replace("{user}", u)
        mac_target = mac_raw.split("  (")[0].strip()
        mac_parent = str(Path(mac_target).parent)
        is_root_mac = mac_target.startswith(("/Library/", "/etc/", "/usr/"))
        owner_mac = "root:wheel" if is_root_mac else f"{u}:staff"
        mode_mac = "0755" if file_id == "guard_sh" else "0644"
        pre_init_mac = (
            f"# Normalize CLI settings once as developer user BEFORE chflags schg\n"
            f"sudo -u {u} /usr/local/bin/agy --version >/dev/null 2>&1 || true\n\n"
            if file_id == "cli_settings"
            else ""
        )
        per_os["macos"] = {
            "lock": (
                f"# 1. Create parent directory and set file ownership & permissions\n"
                f'sudo mkdir -p "{mac_parent}"\n'
                f'sudo chown {owner_mac} "{mac_target}"\n'
                f'sudo chmod {mode_mac} "{mac_target}"\n\n'
                f"{pre_init_mac}"
                f"# 2. Enforce APFS system immutable flag (chflags schg)\n"
                f'sudo chflags schg "{mac_target}"\n'
                f'ls -lO "{mac_target}"'
            ),
            "unlock": (
                f"# Clear APFS system immutable flag prior to maintenance updates\n"
                f'sudo chflags noschg "{mac_target}"'
            ),
        }

    if "windows" in os_list and "windows" in meta["os"]:
        if file_id == "gateway_env":
            per_os["windows"] = {
                "lock": (
                    "# Elevated PowerShell: Set Machine-level Environment Variables (HKLM — Read-Only for standard users)\n"
                    '[Environment]::SetEnvironmentVariable("AGY_LLM_GATEWAY_URL", "https://REPLACE_WITH_GATEWAY_URL", "Machine")\n'
                    '[Environment]::SetEnvironmentVariable("AGY_LLM_GATEWAY_API_KEY", "REPLACE_WITH_GATEWAY_API_KEY", "Machine")\n'
                    '[Environment]::SetEnvironmentVariable("AGY_LLM_GATEWAY_WIRE_PROTOCOL", "genai", "Machine")'
                ),
                "unlock": (
                    "# Elevated PowerShell: Clear Machine-level Gateway Environment Variables\n"
                    '[Environment]::SetEnvironmentVariable("AGY_LLM_GATEWAY_URL", $null, "Machine")\n'
                    '[Environment]::SetEnvironmentVariable("AGY_LLM_GATEWAY_API_KEY", $null, "Machine")\n'
                    '[Environment]::SetEnvironmentVariable("AGY_LLM_GATEWAY_WIRE_PROTOCOL", $null, "Machine")'
                ),
            }
        else:
            win_raw = meta["paths"]["windows"].replace("{user}", u)
            win_target = win_raw.split("  (")[0].strip()
            win_parent = win_target.rsplit("\\", 1)[0]
            reader_principal = "Users" if win_target.startswith("C:\\ProgramData") else f"$($DevUser)"
            bom_note = (
                "# Write UTF-8 WITHOUT BOM (PowerShell 5.1 Set-Content -Encoding UTF8 adds fatal BOM!)\n"
                "# [System.IO.File]::WriteAllText($Target, $JsonContent, (New-Object System.Text.UTF8Encoding($false)))\n\n"
                if meta["language"] == "json"
                else ""
            )
            per_os["windows"] = {
                "lock": (
                    f'# Elevated PowerShell: Set ReadOnly BEFORE non-SYNCHRONIZE Deny ACL\n'
                    f'$DevUser = "{u}"\n'
                    f'$Target = "{win_target}"\n'
                    f'New-Item -ItemType Directory -Force -Path "{win_parent}" | Out-Null\n'
                    f"{bom_note}"
                    f"attrib.exe +R $Target\n"
                    f'icacls.exe $Target /inheritance:r /grant:r "SYSTEM:(F)" "Administrators:(F)" "{reader_principal}:(R,RX)" /deny "$($DevUser):(WD,AD,WEA,WA,DE,WDAC,WO)" | Out-Null\n'
                    f"icacls.exe $Target"
                ),
                "unlock": (
                    f"# Elevated PowerShell: Remove Deny ACL BEFORE clearing ReadOnly attribute\n"
                    f'$DevUser = "{u}"\n'
                    f'$Target = "{win_target}"\n'
                    f"icacls.exe $Target /remove:d $DevUser | Out-Null\n"
                    f"attrib.exe -R $Target"
                ),
            }

    return per_os


def build_admin_lock_commands(
    os_list: list[str],
    surfaces: list[str],
    dev_user: str = "alice",
    active_file_ids: list[str] | None = None,
) -> dict[str, dict[str, str]]:
    """Generate copy-pasteable OS root/admin deployment, lock, and unlock CLI blocks.

    Summary:
        Produces verified `chattr +i` (Linux with `MarshalSparse` pre-init),
        `chflags schg` (macOS), and BOM-free `UTF8Encoding($false)` + `attrib +R`
        + `icacls /deny (WD,AD,WEA,WA,DE,WDAC,WO)` (Windows) scripts scoped to
        the selected files and surfaces.
    Parameters:
        os_list (list[str]): Selected operating systems.
        surfaces (list[str]): Selected Antigravity surfaces.
        dev_user (str): Target workstation developer username.
        active_file_ids (list[str] | None): Optional subset of selected file IDs.
    Return Value:
        dict[str, dict[str, str]]: Map of `os -> {"lock": str, "unlock": str}`.
    Exceptions/Errors:
        None.
    """
    u = (dev_user or "alice").strip() or "alice"
    resolved_ids = (
        list(active_file_ids)
        if active_file_ids is not None
        else get_active_file_ids(os_list, surfaces)
    )
    id_set = set(resolved_ids)
    commands: dict[str, dict[str, str]] = {}

    if "linux" in os_list:
        lin_map = {
            "admin_settings": "/etc/antigravity/admin_settings.json",
            "gateway_env": "/etc/profile.d/antigravity-gateway.sh",
            "cli_settings": f"/home/{u}/.gemini/antigravity-cli/settings.json",
            "desktop_config": f"/home/{u}/.gemini/config/config.json",
            "browser_allowlist": f"/home/{u}/.gemini/antigravity/browserAllowlist.txt",
            "mcp_config": f"/home/{u}/.gemini/config/mcp_config.json",
            "hooks_config": f"/home/{u}/.gemini/config/hooks.json",
            "guard_sh": "/usr/local/bin/agy_security_guard.sh",
            "acp_json": f"/home/{u}/.jetbrains/acp.json",
            "acp_auth": f"/home/{u}/.gemini/antigravity-acp/settings.json",
        }
        lin_files = [p for fid, p in lin_map.items() if fid in id_set]
        if lin_files:
            joined_lin = " \\\n  ".join(lin_files)
            pre_step = (
                f"# 1. Run MarshalSparse pre-init once BEFORE chattr +i so agy does not hit EPERM on startup\n"
                f"sudo -u {u} /usr/local/bin/agy --version >/dev/null 2>&1 || true\n\n"
                if "cli_settings" in id_set
                else ""
            )
            perm_lines: list[str] = []
            if "admin_settings" in id_set:
                perm_lines.append("sudo chown root:root /etc/antigravity/admin_settings.json && sudo chmod 0644 /etc/antigravity/admin_settings.json")
            if "guard_sh" in id_set:
                perm_lines.append("sudo chown root:root /usr/local/bin/agy_security_guard.sh && sudo chmod 0755 /usr/local/bin/agy_security_guard.sh")
            perm_block = ("\n".join(perm_lines) + "\n") if perm_lines else ""
            commands["linux"] = {
                "lock": (
                    f"{pre_step}"
                    f"# Set ownership, permissions, and kernel immutable bit (blocks mv -f atomic rename)\n"
                    f"{perm_block}"
                    f"sudo chattr +i \\\n  {joined_lin}\n\n"
                    f"# Verify immutable 'i' attribute\n"
                    f"lsattr {lin_files[0]}"
                ),
                "unlock": (
                    f"# Remove Linux ext4/xfs immutable flag prior to policy updates\n"
                    f"sudo chattr -i \\\n  {joined_lin}"
                ),
            }

    if "macos" in os_list:
        mac_map = {
            "admin_settings": '"/Library/Application Support/Antigravity/admin_settings.json"',
            "gateway_env": '"/etc/antigravity-gateway.env"',
            "cli_settings": f'"/Users/{u}/.gemini/antigravity-cli/settings.json"',
            "desktop_config": f'"/Users/{u}/.gemini/config/config.json"',
            "browser_allowlist": f'"/Users/{u}/.gemini/antigravity/browserAllowlist.txt"',
            "mcp_config": f'"/Users/{u}/.gemini/config/mcp_config.json"',
            "hooks_config": f'"/Users/{u}/.gemini/config/hooks.json"',
            "guard_sh": '"/usr/local/bin/agy_security_guard.sh"',
            "acp_json": f'"/Users/{u}/.jetbrains/acp.json"',
            "acp_auth": f'"/Users/{u}/.gemini/antigravity-acp/settings.json"',
        }
        mac_files = [p for fid, p in mac_map.items() if fid in id_set]
        if mac_files:
            joined_mac = " \\\n  ".join(mac_files)
            pre_mac = (
                f"# 1. Normalize CLI settings once as developer user\n"
                f"sudo -u {u} /usr/local/bin/agy --version >/dev/null 2>&1 || true\n\n"
                if "cli_settings" in id_set
                else ""
            )
            perm_mac: list[str] = []
            if "admin_settings" in id_set:
                perm_mac.append('sudo chown root:wheel "/Library/Application Support/Antigravity/admin_settings.json" && sudo chmod 0644 "/Library/Application Support/Antigravity/admin_settings.json"')
            if "guard_sh" in id_set:
                perm_mac.append('sudo chown root:wheel "/usr/local/bin/agy_security_guard.sh" && sudo chmod 0755 "/usr/local/bin/agy_security_guard.sh"')
            perm_mac_block = ("\n".join(perm_mac) + "\n") if perm_mac else ""
            commands["macos"] = {
                "lock": (
                    f"{pre_mac}"
                    f"# Apply root:wheel ownership and APFS system immutable flag (chflags schg)\n"
                    f"{perm_mac_block}"
                    f"sudo chflags schg \\\n  {joined_mac}\n\n"
                    f"# Verify 'schg' flag\n"
                    f"ls -lO {mac_files[0]}"
                ),
                "unlock": (
                    f"# Clear macOS APFS system immutable flag (noschg)\n"
                    f"sudo chflags noschg \\\n  {joined_mac}"
                ),
            }

    if "windows" in os_list:
        win_map = {
            "admin_settings": "C:\\ProgramData\\Antigravity\\admin_settings.json",
            "cli_settings": f"C:\\Users\\{u}\\.gemini\\antigravity-cli\\settings.json",
            "desktop_config": f"C:\\Users\\{u}\\.gemini\\config\\config.json",
            "browser_allowlist": f"C:\\Users\\{u}\\.gemini\\antigravity\\browserAllowlist.txt",
            "mcp_config": f"C:\\Users\\{u}\\.gemini\\config\\mcp_config.json",
            "hooks_config": f"C:\\Users\\{u}\\.gemini\\config\\hooks.json",
            "guard_ps1": "C:\\ProgramData\\Antigravity\\bin\\agy_security_guard.ps1",
            "acp_json": f"C:\\Users\\{u}\\.jetbrains\\acp.json",
            "acp_auth": f"C:\\Users\\{u}\\.gemini\\antigravity-acp\\settings.json",
        }
        win_files = [p for fid, p in win_map.items() if fid in id_set]
        if win_files:
            win_array = ",\n  ".join(f'"{p}"' for p in win_files)
            commands["windows"] = {
                "lock": (
                    f"# Elevated PowerShell: BOM-free UTF-8 + ReadOnly BEFORE non-SYNCHRONIZE Deny ACL\n"
                    f"$DevUser = \"{u}\"\n"
                    f"$Targets = @(\n  {win_array}\n)\n"
                    f"foreach ($File in $Targets) {{\n"
                    f"  if (Test-Path $File) {{\n"
                    f"    attrib.exe +R $File\n"
                    f"    icacls.exe $File /inheritance:r /grant:r \"SYSTEM:(F)\" \"Administrators:(F)\" \"$($DevUser):(R,RX)\" /deny \"$($DevUser):(WD,AD,WEA,WA,DE,WDAC,WO)\" | Out-Null\n"
                    f"  }}\n"
                    f"}}"
                ),
                "unlock": (
                    f"# Elevated PowerShell: Remove Deny ACL BEFORE clearing ReadOnly attribute\n"
                    f"$DevUser = \"{u}\"\n"
                    f"$Targets = @(\n  {win_array}\n)\n"
                    f"foreach ($File in $Targets) {{\n"
                    f"  if (Test-Path $File) {{\n"
                    f"    icacls.exe $File /remove:d $DevUser | Out-Null\n"
                    f"    attrib.exe -R $File\n"
                    f"  }}\n"
                    f"}}"
                ),
            }

    return commands


# ==============================================================================
# BLOCK 6: COMPLETE COMPILE PASS & BOM-FREE MDM ZIP BUNDLE GENERATOR
# ==============================================================================
def compile_studio_state(state: dict[str, Any]) -> dict[str, Any]:
    """Compile structured studio state into rendered files, validation & CLI commands.

    Summary:
        Single stateless orchestration pass invoked by `POST /api/compile`,
        `POST /api/sync-code`, `POST /api/autofix`, and `POST /api/import`.
        Supports both progressive step-by-step selection (`os_list == []`,
        `surfaces == []`, or `selected_file_ids` subset) and full-catalog API
        defaults when `selected_file_ids` is `None`.
    Parameters:
        state (dict[str, Any]): Current structured studio state.
    Return Value:
        dict[str, Any]: Dictionary containing `state`, `available_file_ids`,
        `active_file_ids`, `files`, `validation`, `admin_cli`, and `per_file_cli`.
    Exceptions/Errors:
        None.
    """
    raw_os = state.get("os_list")
    if isinstance(raw_os, list):
        os_list = [o for o in raw_os if o in OS_LABELS]
    else:
        os_list = list(ALL_OS)

    raw_surfaces = state.get("surfaces")
    if isinstance(raw_surfaces, list):
        surfaces = [s for s in raw_surfaces if s in SURFACE_LABELS]
    else:
        surfaces = list(ALL_SURFACES)

    dev_user = (str(state.get("dev_user", "alice")).strip()) or "alice"

    state["os_list"] = os_list
    state["surfaces"] = surfaces
    state["dev_user"] = dev_user

    available_ids = get_active_file_ids(os_list, surfaces, allow_empty=True)
    raw_selected = state.get("selected_file_ids")
    if raw_selected is None:
        active_ids = list(available_ids)
    elif isinstance(raw_selected, list):
        sel_set = {str(x) for x in raw_selected}
        active_ids = [fid for fid in available_ids if fid in sel_set]
        state["selected_file_ids"] = list(active_ids)
    else:
        active_ids = list(available_ids)
        state["selected_file_ids"] = None

    files_map: dict[str, str] = {}
    for fid in active_ids:
        files_map[fid] = render_single_file(fid, state)

    validation = validate_bundle(
        files_map=files_map,
        os_list=os_list or list(ALL_OS),
        surfaces=surfaces or list(ALL_SURFACES),
        dev_user=dev_user,
    )
    admin_cli = build_admin_lock_commands(os_list, surfaces, dev_user, active_file_ids=active_ids)
    per_file_cli = {
        fid: build_per_file_admin_commands(fid, os_list, dev_user)
        for fid in available_ids
    }
    all_files_cli = {
        item["id"]: build_per_file_admin_commands(item["id"], list(ALL_OS), dev_user)
        for item in FILE_CATALOG
    }

    return {
        "state": state,
        "available_file_ids": available_ids,
        "active_file_ids": active_ids,
        "files": files_map,
        "validation": validation,
        "admin_cli": admin_cli,
        "per_file_cli": per_file_cli,
        "all_files_cli": all_files_cli,
    }


def _archive_rel_paths_for_os(file_id: str, target_os: str, dev_user: str) -> list[str]:
    """Map a canonical `file_id` + OS to exact relative archive paths in the MDM ZIP.

    Summary:
        Organizes exported files under `linux/`, `macos/`, and `windows/`
        mirrors matching real workstation root directories.
    Parameters:
        file_id (str): Canonical studio file identifier.
        target_os (str): `"linux"`, `"macos"`, or `"windows"`.
        dev_user (str): Workstation developer username.
    Return Value:
        list[str]: Relative paths inside the `.zip` archive.
    Exceptions/Errors:
        None.
    """
    u = dev_user.strip() or "alice"
    if target_os == "linux":
        mapping = {
            "admin_settings": ["linux/etc/antigravity/admin_settings.json"],
            "gateway_env": ["linux/etc/profile.d/antigravity-gateway.sh"],
            "cli_settings": [f"linux/home/{u}/.gemini/antigravity-cli/settings.json"],
            "desktop_config": [f"linux/home/{u}/.gemini/config/config.json"],
            "browser_allowlist": [f"linux/home/{u}/.gemini/antigravity/browserAllowlist.txt"],
            "mcp_config": [f"linux/home/{u}/.gemini/config/mcp_config.json"],
            "hooks_config": [f"linux/home/{u}/.gemini/config/hooks.json"],
            "guard_sh": ["linux/usr/local/bin/agy_security_guard.sh"],
            "acp_json": [f"linux/home/{u}/.jetbrains/acp.json"],
            "acp_auth": [f"linux/home/{u}/.gemini/antigravity-acp/settings.json"],
        }
        return mapping.get(file_id, [])

    if target_os == "macos":
        mapping = {
            "admin_settings": ["macos/Library/Application Support/Antigravity/admin_settings.json"],
            "gateway_env": ["macos/etc/antigravity-gateway.env"],
            "cli_settings": [f"macos/Users/{u}/.gemini/antigravity-cli/settings.json"],
            "desktop_config": [f"macos/Users/{u}/.gemini/config/config.json"],
            "browser_allowlist": [f"macos/Users/{u}/.gemini/antigravity/browserAllowlist.txt"],
            "mcp_config": [f"macos/Users/{u}/.gemini/config/mcp_config.json"],
            "hooks_config": [f"macos/Users/{u}/.gemini/config/hooks.json"],
            "guard_sh": ["macos/usr/local/bin/agy_security_guard.sh"],
            "acp_json": [f"macos/Users/{u}/.jetbrains/acp.json"],
            "acp_auth": [f"macos/Users/{u}/.gemini/antigravity-acp/settings.json"],
        }
        return mapping.get(file_id, [])

    if target_os == "windows":
        mapping = {
            "admin_settings": ["windows/ProgramData/Antigravity/admin_settings.json"],
            "gateway_env": ["windows/ProgramData/Antigravity/antigravity-gateway.env"],
            "cli_settings": [f"windows/Users/{u}/.gemini/antigravity-cli/settings.json"],
            "desktop_config": [f"windows/Users/{u}/.gemini/config/config.json"],
            "browser_allowlist": [f"windows/Users/{u}/.gemini/antigravity/browserAllowlist.txt"],
            "mcp_config": [f"windows/Users/{u}/.gemini/config/mcp_config.json"],
            "hooks_config": [f"windows/Users/{u}/.gemini/config/hooks.json"],
            "guard_ps1": ["windows/ProgramData/Antigravity/bin/agy_security_guard.ps1"],
            "acp_json": [f"windows/Users/{u}/.jetbrains/acp.json"],
            "acp_auth": [f"windows/Users/{u}/.gemini/antigravity-acp/settings.json"],
        }
        return mapping.get(file_id, [])

    return []


def build_mdm_zip_bundle(state: dict[str, Any]) -> bytes:
    """Create a complete BOM-free UTF-8 MDM `.zip` bundle in memory.

    Summary:
        Renders all active files for the selected OSes and surfaces, adapts
        OS-specific line endings (LF for POSIX, CRLF for `.ps1` on Windows, zero
        UTF-8 BOM everywhere), includes OS lock/unlock scripts, and returns raw
        `.zip` archive bytes.
    Parameters:
        state (dict[str, Any]): Current structured studio state.
    Return Value:
        bytes: In-memory `.zip` archive payload.
    Exceptions/Errors:
        None.
    """
    compiled = compile_studio_state(copy.deepcopy(state))
    files_map: dict[str, str] = compiled["files"]
    os_list: list[str] = compiled["state"]["os_list"]
    surfaces: list[str] = compiled["state"]["surfaces"]
    dev_user: str = compiled["state"]["dev_user"]
    admin_cli: dict[str, dict[str, str]] = compiled["admin_cli"]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for target_os in os_list:
            for fid, raw_text in files_map.items():
                rel_paths = _archive_rel_paths_for_os(fid, target_os, dev_user)
                if not rel_paths:
                    continue
                bom_free = raw_text.lstrip("\ufeff")
                normalized_lf = bom_free.replace("\r\n", "\n")
                # On Windows, strip Linux /etc/ssl caCertPath in the Windows copy if multi-OS
                if target_os == "windows" and fid == "admin_settings" and len(os_list) > 1:
                    try:
                        adm_obj = json.loads(normalized_lf)
                        if adm_obj.get("caCertPath") == "/etc/ssl/certs/ca-certificates.crt":
                            adm_obj.pop("caCertPath", None)
                            normalized_lf = json.dumps(adm_obj, indent=2) + "\n"
                    except json.JSONDecodeError:
                        pass
                # PowerShell scripts use CRLF; JSON/env/sh use clean LF (UTF-8 without BOM)
                payload_str = normalized_lf.replace("\n", "\r\n") if fid == "guard_ps1" else normalized_lf
                payload_bytes = payload_str.encode("utf-8")

                for rel_p in rel_paths:
                    info = zipfile.ZipInfo(rel_p)
                    info.external_attr = (0o755 << 16) if rel_p.endswith(".sh") else (0o644 << 16)
                    zf.writestr(info, payload_bytes)

        # Include OS lock/unlock scripts
        if "linux" in admin_cli:
            lin_script = (
                "#!/usr/bin/env bash\nset -euo pipefail\n\n"
                + admin_cli["linux"]["lock"]
                + "\n\n# --- UNLOCK REFERENCE ---\n# "
                + admin_cli["linux"]["unlock"].replace("\n", "\n# ")
                + "\n"
            )
            info_lin = zipfile.ZipInfo("scripts/lock_linux.sh")
            info_lin.external_attr = 0o755 << 16
            zf.writestr(info_lin, lin_script.encode("utf-8"))

        if "macos" in admin_cli:
            mac_script = (
                "#!/usr/bin/env bash\nset -euo pipefail\n\n"
                + admin_cli["macos"]["lock"]
                + "\n\n# --- UNLOCK REFERENCE ---\n# "
                + admin_cli["macos"]["unlock"].replace("\n", "\n# ")
                + "\n"
            )
            info_mac = zipfile.ZipInfo("scripts/lock_macos.sh")
            info_mac.external_attr = 0o755 << 16
            zf.writestr(info_mac, mac_script.encode("utf-8"))

        if "windows" in admin_cli:
            win_script = (
                admin_cli["windows"]["lock"]
                + "\n\n<# --- UNLOCK REFERENCE ---\n"
                + admin_cli["windows"]["unlock"]
                + "\n#>\n"
            ).replace("\n", "\r\n")
            zf.writestr("scripts/lock_windows.ps1", win_script.encode("utf-8"))

        readme_lines = [
            "# Antigravity Enterprise MDM Policy Bundle",
            "",
            f"- **Selected OS Targets**: {', '.join(OS_LABELS[o] for o in os_list)}",
            f"- **Selected Surfaces**: {', '.join(SURFACE_LABELS[s] for s in surfaces)}",
            f"- **Target Workstation User**: `{dev_user}`",
            "- **Encoding Guarantee**: All JSON, `.env`, `.txt`, and script files are encoded as **UTF-8 without BOM**.",
            "",
            "## Deployment Order",
            "1. Replace any `REPLACE_WITH_*` placeholders with your deployed Enterprise Gateway URL, API key, and GCP Billing Project ID.",
            "2. Copy the files under `linux/`, `macos/`, or `windows/` to their matching workstation root paths.",
            "3. Execute the matching lock script in `scripts/` (`lock_linux.sh`, `lock_macos.sh`, or `lock_windows.ps1`) as `root` / Administrator.",
            "",
            "## Official Public Documentation",
            "- Admin Guide: https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/deploy-enterprise-gateway?hl=en",
            "- Developer Guide: https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/connect-enterprise-gateway?hl=en",
        ]
        zf.writestr("README_DEPLOYMENT.md", ("\n".join(readme_lines) + "\n").encode("utf-8"))

    return buf.getvalue()


def import_archive_or_files(
    uploaded_items: list[tuple[str, bytes]],
    current_state: dict[str, Any],
) -> dict[str, Any]:
    """Ingest uploaded single files or `.zip` policy bundles into studio state.

    Summary:
        Inspects raw bytes for leading UTF-8 BOM (`0xEF 0xBB 0xBF`), unpacks any
        `.zip` archives in memory (with zip-slip/size bounds), auto-detects each
        file's canonical slot, updates `state`, and validates all imported files.
    Parameters:
        uploaded_items (list[tuple[str, bytes]]): List of `(filename, raw_bytes)`.
        current_state (dict[str, Any]): Current structured studio state.
    Return Value:
        dict[str, Any]: Compiled studio payload plus `imported_files` metadata
        and BOM-aware validation results.
    Exceptions/Errors:
        ValueError: If a `.zip` file is corrupt or exceeds uncompressed safety
        bounds (`32 MiB`).
    """
    state = copy.deepcopy(current_state)
    raw_texts: dict[str, str] = {}
    bom_flags: dict[str, bool] = {}
    imported_meta: list[dict[str, Any]] = []
    max_uncompressed_bytes = 32 * 1024 * 1024
    total_bytes = 0

    expanded_entries: list[tuple[str, bytes]] = []
    for fname, fbytes in uploaded_items:
        if fname.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(fbytes), mode="r") as zf:
                    for zinfo in zf.infolist():
                        if zinfo.is_dir():
                            continue
                        zname = zinfo.filename.replace("\\", "/")
                        base = zname.split("/")[-1]
                        if base.startswith(".") and base != ".env":
                            continue
                        if base.lower().endswith(".md") or "scripts/lock_" in zname:
                            continue
                        total_bytes += zinfo.file_size
                        if total_bytes > max_uncompressed_bytes:
                            raise ValueError("Uploaded ZIP archive exceeds 32 MiB uncompressed safety limit.")
                        expanded_entries.append((zname, zf.read(zinfo)))
            except zipfile.BadZipFile as exc:
                raise ValueError(f"Invalid or corrupted ZIP archive: {fname}") from exc
        else:
            total_bytes += len(fbytes)
            if total_bytes > max_uncompressed_bytes:
                raise ValueError("Uploaded files exceed 32 MiB safety limit.")
            expanded_entries.append((fname, fbytes))

    for entry_name, entry_bytes in expanded_entries:
        has_bom = entry_bytes.startswith(b"\xef\xbb\xbf")
        decoded = entry_bytes.decode("utf-8", errors="replace")
        fid = detect_file_type(entry_name, decoded)
        raw_texts[fid] = decoded
        bom_flags[fid] = has_bom
        state = parse_file_into_state(fid, decoded, state)
        imported_meta.append(
            {
                "source_name": entry_name,
                "detected_file_id": fid,
                "had_utf8_bom": has_bom,
            }
        )

    # Ensure OS, surfaces, and selected_file_ids cover every imported file so progressive UI reveals it
    if not state.get("os_list"):
        state["os_list"] = list(ALL_OS)
    if not state.get("surfaces"):
        state["surfaces"] = list(ALL_SURFACES)

    os_set = set(state["os_list"])
    surf_set = set(state["surfaces"])
    for fid in raw_texts:
        meta = FILE_CATALOG_BY_ID.get(fid)
        if meta:
            if not os_set.intersection(meta["os"]):
                os_set.update(meta["os"])
            if not surf_set.intersection(meta["surfaces"]):
                surf_set.update(meta["surfaces"])
    state["os_list"] = [o for o in ALL_OS if o in os_set]
    state["surfaces"] = [s for s in ALL_SURFACES if s in surf_set]

    if isinstance(state.get("selected_file_ids"), list):
        merged_sel = list(dict.fromkeys(list(state["selected_file_ids"]) + list(raw_texts.keys())))
        state["selected_file_ids"] = merged_sel

    compiled = compile_studio_state(state)
    # Preserve exact uploaded raw text (and BOM errors/syntax errors) so the user can inspect & Auto-Fix!
    for fid, raw_val in raw_texts.items():
        compiled["files"][fid] = raw_val
        if fid not in compiled["active_file_ids"]:
            compiled["active_file_ids"].append(fid)

    compiled["validation"] = validate_bundle(
        files_map=compiled["files"],
        os_list=compiled["state"]["os_list"] or list(ALL_OS),
        surfaces=compiled["state"]["surfaces"] or list(ALL_SURFACES),
        dev_user=compiled["state"]["dev_user"],
        bom_map=bom_flags,
    )
    compiled["imported_files"] = imported_meta
    return compiled
