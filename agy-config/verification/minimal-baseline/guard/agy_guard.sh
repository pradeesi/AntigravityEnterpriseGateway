#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: agy_guard.sh — Baseline PreToolUse/PostToolUse guard (Linux/macOS)
# ==============================================================================
# Purpose:
#   Denies agent tool calls that touch credentials, Antigravity's own policy
#   files, privilege escalation, raw network tools, cloud metadata endpoints,
#   or OS lock-removal commands, and appends one JSON audit line per call.
#
# Architecture / Context:
#   Wired in ~/.gemini/config/hooks.json (minimal baseline). hooks.json is the
#   only file-based control that every surface honors, including the
#   JetBrains/Zed ACP server, which ignores permission rules in settings files.
#   Protocol (verified live on CLI 1.4.12, App/hub 2.28.2 and ACP 1.4.5):
#   stdin carries {"toolCall":{"name":...,"args":{...}}}; stdout must be a JSON
#   decision ({"decision":"allow"} or {"decision":"deny","reason":"..."}).
#
# Dependencies / Side Effects:
#   bash, grep, date. Install root-owned (0755) at /usr/local/bin/agy_guard.sh.
#   Writes the audit trail to ${XDG_STATE_HOME:-$HOME/.local/state}/agy-guard/audit.jsonl
#   (user-writable by necessity: the hook runs as the developer).
# ==============================================================================
set -u

PHASE="${1:-pre}"
PAYLOAD="$(cat)"
LOWER="$(printf '%s' "${PAYLOAD}" | tr '[:upper:]' '[:lower:]')"
STATE_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/agy-guard"

#######################################
# Append one audit record; never fail the tool call because logging failed.
# Arguments:
#   $1 - decision (allow|deny|post)
#   $2 - rule id ("" when none)
# Outputs:
#   None (writes to the audit file).
#######################################
audit() {
  mkdir -p "${STATE_DIR}" 2>/dev/null || return 0
  printf '{"ts":"%s","phase":"%s","decision":"%s","rule":"%s","bytes":%d}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${PHASE}" "$1" "$2" "${#PAYLOAD}" \
    >> "${STATE_DIR}/audit.jsonl" 2>/dev/null || true
}

#######################################
# Print a deny decision and exit 0 (the decision travels on stdout).
# Arguments:
#   $1 - rule id
#   $2 - human-readable reason shown to the agent
#######################################
deny() {
  audit "deny" "$1"
  printf '{"decision":"deny","reason":"agy-guard %s: %s"}\n' "$1" "$2"
  exit 0
}

if [[ "${PHASE}" == "post" ]]; then
  audit "post" ""
  printf '{}\n'
  exit 0
fi

# Patterns run against the whole lower-cased payload (tool name + arguments), so a
# file viewer reading ~/.ssh and a shell command `cat ~/.ssh/...` are both caught.
# Why each group exists:
#   G1 credentials: the agent never needs SSH/cloud/GPG/Kubernetes secrets.
#   G2 policy files: the agent must not edit the controls that constrain it.
#   G3 privilege escalation: commands run as the developer; no elevation.
#   G4 raw network tools: the sandbox egress allowlist doesn't apply on every
#      surface (ACP has no sandbox), so network tools are blocked here too.
#   G5 metadata endpoints: classic credential theft on cloud VMs/workstations.
#   G6 lock removal: immutable flags/ACLs are what keep G2 effective.
if grep -Eq '(^|[^a-z0-9_])\.(ssh|aws|gnupg|kube)([/\\"]|$)|\.config[/\\]+gcloud|id_(rsa|ed25519|ecdsa)' <<<"${LOWER}"; then
  deny "G1-CREDENTIALS" "access to credential stores is blocked by policy"
fi
# Only the policy files themselves: the agent legitimately reads its own brain/skills folders
# under ~/.gemini (the ACP server even lists ~/.gemini/config/skills as an allowed root).
if grep -Eq '\.gemini[/\\]+config[/\\]+(config|hooks|mcp_config)\.json|antigravity-(cli|acp)[/\\]+settings\.json|admin_settings\.json|\.antigravity[/\\]+settings\.json|agy_guard\.(sh|ps1)' <<<"${LOWER}"; then
  deny "G2-POLICY-FILES" "Antigravity policy files are read-only for the agent"
fi
if grep -Eq '169\.254\.169\.254|metadata\.google\.internal' <<<"${LOWER}"; then
  deny "G5-METADATA" "cloud metadata endpoints are blocked by policy"
fi

# Command-only groups: matching them against file contents (e.g. a README that mentions
# sudo) would block harmless edits, so they apply to terminal tools only.
if grep -Eq '"name"[[:space:]]*:[[:space:]]*"(run_command|send_command_input|terminal|execute|bash|shell)"' <<<"${LOWER}"; then
  if grep -Eq '(^|[^a-z0-9_-])(sudo|doas|pkexec|su)([[:space:]]|$)' <<<"${LOWER}"; then
    deny "G3-ELEVATION" "privilege escalation is blocked by policy"
  fi
  if grep -Eq '(^|[^a-z0-9_-])(curl|wget|nc|ncat|netcat)(\.exe)?([[:space:]]|$)' <<<"${LOWER}"; then
    deny "G4-NETWORK-TOOL" "raw network tools are blocked; use approved read_url domains"
  fi
  if grep -Eq '(^|[^a-z0-9_-])(chattr|chflags|icacls|takeown|attrib)(\.exe)?([[:space:]]|$)' <<<"${LOWER}"; then
    deny "G6-LOCK-REMOVAL" "changing file locks is blocked by policy"
  fi
fi

audit "allow" ""
printf '{"decision":"allow"}\n'
exit 0
