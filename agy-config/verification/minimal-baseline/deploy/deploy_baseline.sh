#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: deploy_baseline.sh — Install and lock the AGY minimal baseline (Linux/macOS)
# ==============================================================================
# Purpose:
#   Renders the minimal-baseline templates for one developer account, installs
#   them in the paths each Antigravity surface reads, and locks every file the
#   developer could otherwise edit (chattr +i on Linux, chflags schg on macOS).
#
# Architecture / Context:
#   Part of agy-config/verification/minimal-baseline. The file set was chosen
#   from live verification (CLI 1.4.12, App/hub 2.28.2, VS Code ext 1.10.0,
#   ACP server 1.4.5): admin_settings.json (all surfaces), config.json (CLI
#   shared rules + App/web/VS Code), CLI settings.json (CLI-only modes),
#   hooks.json + guard (the only control the JetBrains/Zed ACP server honors),
#   mcp_config.json (all surfaces), antigravity-acp/settings.json (ACP auth).
#
# Dependencies / Side Effects:
#   Run as root. Needs bash, sed, install; chattr (Linux) or chflags (macOS);
#   python3 is optional (used only to validate JSON). Reads the gateway key from
#   a file (never from the command line, so it stays out of shell history and
#   process listings). Overwrites the managed files listed in FILES below.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
OS_NAME="$(uname -s)"

ACTION="deploy"
DEV_USER=""
GATEWAY_URL=""
GATEWAY_KEY_FILE=""
COST_CENTER="engineering"

#######################################
# Structured log line on stderr.
# Arguments: $1 level, $2... message
#######################################
log() {
  local level="$1"; shift
  printf '%s %-5s deploy_baseline: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${level}" "$*" >&2
}

#######################################
# Print usage and exit with the given code.
# Arguments: $1 exit code
#######################################
usage() {
  cat >&2 <<'EOF'
Usage: sudo deploy_baseline.sh --user <name> [--action deploy|unlock|status]
                               [--gateway-url https://...] [--gateway-key-file <path>]
                               [--cost-center <value>]
  deploy  render + install + lock (needs --gateway-url and --gateway-key-file)
  unlock  remove the immutable flags so files can be edited or removed
  status  show managed files and their lock state
EOF
  exit "$1"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) DEV_USER="${2:-}"; shift 2 ;;
    --action) ACTION="${2:-}"; shift 2 ;;
    --gateway-url) GATEWAY_URL="${2:-}"; shift 2 ;;
    --gateway-key-file) GATEWAY_KEY_FILE="${2:-}"; shift 2 ;;
    --cost-center) COST_CENTER="${2:-}"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) log ERROR "unknown argument: $1"; usage 2 ;;
  esac
done

# ---------------------------------------------------------------- validation
[[ "$(id -u)" -eq 0 ]] || { log ERROR "run as root"; exit 1; }
[[ "${DEV_USER}" =~ ^[a-z_][a-z0-9_.-]{0,31}$ ]] || { log ERROR "invalid --user '${DEV_USER}'"; exit 2; }
id "${DEV_USER}" >/dev/null 2>&1 || { log ERROR "user ${DEV_USER} does not exist"; exit 2; }
[[ "${ACTION}" =~ ^(deploy|unlock|status)$ ]] || { log ERROR "invalid --action '${ACTION}'"; exit 2; }
[[ "${COST_CENTER}" =~ ^[A-Za-z0-9_.-]{1,64}$ ]] || { log ERROR "invalid --cost-center"; exit 2; }

if [[ "${OS_NAME}" == "Darwin" ]]; then
  ADMIN_DIR="/Library/Application Support/Antigravity"
  DEV_HOME="$(dscl . -read "/Users/${DEV_USER}" NFSHomeDirectory | awk '{print $2}')"
  DEV_GROUP="staff"
else
  ADMIN_DIR="/etc/antigravity"
  DEV_HOME="$(getent passwd "${DEV_USER}" | cut -d: -f6)"
  DEV_GROUP="$(id -gn "${DEV_USER}")"
fi
[[ -d "${DEV_HOME}" ]] || { log ERROR "home folder of ${DEV_USER} not found"; exit 2; }
GUARD_PATH="/usr/local/bin/agy_guard.sh"

# Managed files: "<template>|<destination>|<owner: root or user>"
FILES=(
  "files/admin_settings.json|${ADMIN_DIR}/admin_settings.json|root"
  "files/config.json|${DEV_HOME}/.gemini/config/config.json|user"
  "files/cli-settings.json|${DEV_HOME}/.gemini/antigravity-cli/settings.json|user"
  "files/hooks.json|${DEV_HOME}/.gemini/config/hooks.json|user"
  "files/mcp_config.json|${DEV_HOME}/.gemini/config/mcp_config.json|user"
  "files/antigravity-acp-settings.json|${DEV_HOME}/.gemini/antigravity-acp/settings.json|user"
)

#######################################
# Set or clear the OS immutable flag.
# Arguments: $1 on|off, $2 path
#######################################
set_lock() {
  local mode="$1" path="$2"
  [[ -e "${path}" ]] || return 0
  if [[ "${OS_NAME}" == "Darwin" ]]; then
    if [[ "${mode}" == "on" ]]; then chflags schg "${path}"; else chflags noschg "${path}"; fi
  else
    if [[ "${mode}" == "on" ]]; then chattr +i "${path}"; else chattr -i "${path}"; fi
  fi
}

#######################################
# Show the lock state of a path.
# Arguments: $1 path
#######################################
lock_state() {
  local path="$1"
  if [[ ! -e "${path}" ]]; then echo "missing"; return; fi
  if [[ "${OS_NAME}" == "Darwin" ]]; then
    ls -lO "${path}" | grep -q schg && echo "locked" || echo "unlocked"
  else
    lsattr -d "${path}" 2>/dev/null | cut -c1-20 | grep -q i && echo "locked" || echo "unlocked"
  fi
}

#######################################
# Render one template to stdout with the deployment values.
# Arguments: $1 template path
#######################################
render() {
  # '|' as the sed delimiter: URLs and paths contain '/'. The key is escaped for sed.
  local key_escaped
  key_escaped="$(printf '%s' "${GATEWAY_KEY}" | sed -e 's/[\\|&]/\\&/g')"
  sed -e "s|__HOME__|${DEV_HOME}|g" \
      -e "s|__GATEWAY_URL__|${GATEWAY_URL}|g" \
      -e "s|__GATEWAY_API_KEY__|${key_escaped}|g" \
      -e "s|__COST_CENTER__|${COST_CENTER}|g" \
      -e "s|__GUARD_COMMAND__|${GUARD_PATH}|g" \
      "$1"
}

# ---------------------------------------------------------------- actions
case "${ACTION}" in
  status)
    for entry in "${FILES[@]}"; do
      dest="$(cut -d'|' -f2 <<<"${entry}")"
      printf '%-9s %s\n' "$(lock_state "${dest}")" "${dest}"
    done
    printf '%-9s %s\n' "$(lock_state "${GUARD_PATH}")" "${GUARD_PATH}"
    exit 0
    ;;
  unlock)
    for entry in "${FILES[@]}"; do set_lock off "$(cut -d'|' -f2 <<<"${entry}")"; done
    set_lock off "${GUARD_PATH}"
    log INFO "unlocked managed files for ${DEV_USER}"
    exit 0
    ;;
esac

[[ "${GATEWAY_URL}" =~ ^https://[A-Za-z0-9.-]+(:[0-9]+)?(/.*)?$ ]] || { log ERROR "--gateway-url must be https://"; exit 2; }
[[ -r "${GATEWAY_KEY_FILE}" ]] || { log ERROR "--gateway-key-file is not readable"; exit 2; }
GATEWAY_KEY="$(tr -d '\r\n' < "${GATEWAY_KEY_FILE}")"
[[ -n "${GATEWAY_KEY}" ]] || { log ERROR "gateway key file is empty"; exit 2; }

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

# Render and validate everything before touching the system: a malformed
# admin_settings.json makes clients drop gateway mode and fall back to Google sign-in.
for entry in "${FILES[@]}"; do
  tpl="$(cut -d'|' -f1 <<<"${entry}")"
  render "${BASE_DIR}/${tpl}" > "${WORK}/$(basename "${tpl}")"
  if command -v python3 >/dev/null 2>&1; then
    python3 -m json.tool "${WORK}/$(basename "${tpl}")" >/dev/null \
      || { log ERROR "rendered ${tpl} is not valid JSON"; exit 3; }
  fi
done

# Unlock first so a re-deploy can overwrite previously locked files.
for entry in "${FILES[@]}"; do set_lock off "$(cut -d'|' -f2 <<<"${entry}")"; done
set_lock off "${GUARD_PATH}"

install -o root -g 0 -m 0755 "${BASE_DIR}/guard/agy_guard.sh" "${GUARD_PATH}"
for entry in "${FILES[@]}"; do
  IFS='|' read -r tpl dest owner <<<"${entry}"
  if [[ "${owner}" == "root" ]]; then
    install -d -o root -g 0 -m 0755 "$(dirname "${dest}")"
    install -o root -g 0 -m 0644 "${WORK}/$(basename "${tpl}")" "${dest}"
  else
    install -d -o "${DEV_USER}" -g "${DEV_GROUP}" -m 0755 "$(dirname "${dest}")"
    # Files stay owned by the developer (the apps expect that) but become immutable.
    install -o "${DEV_USER}" -g "${DEV_GROUP}" -m 0644 "${WORK}/$(basename "${tpl}")" "${dest}"
  fi
  set_lock on "${dest}"
  log INFO "installed and locked ${dest}"
done
set_lock on "${GUARD_PATH}"
log INFO "baseline deployed for ${DEV_USER}; verify with: sudo $0 --user ${DEV_USER} --action status"
