#!/usr/bin/env bash
# ==============================================================================
# File: scripts/deploy_and_lock_macos.sh
# Purpose: Production MDM deployment, dynamic template rendering, MarshalSparse
#          normalization, and macOS system-immutable locking (`chflags schg`)
#          script for Google Antigravity CLI, Desktop App, VS Code, and ACP IDEs.
# Architecture/Context: Designed for Jamf Pro, Kandji, Mosyle, Intune, or manual
#          `sudo` execution. Reads modular templates from `../configs/01-*`
#          through `../configs/08-*`, loads `../settings.env` and optional `../.env`,
#          adapts CA bundle path (`/etc/ssl/cert.pem`), and locks with `root:wheel`
#          + `chflags schg`.
# Dependencies/Side Effects: Requires root privileges (`sudo`), `bash`/`zsh`,
#          `sed`, and `chflags`. Modifies `/Library/Application Support/Antigravity/*`,
#          `/usr/local/bin/agy_security_guard.sh`, and `/Users/<USER>/.gemini/*`.
# ==============================================================================
set -euo pipefail

# ==============================================================================
# BLOCK 1: CONFIGURATION LOADING & CLI DEFAULTS
# ==============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONFIGS_DIR="${ROOT_DIR}/configs"

if [[ -f "${ROOT_DIR}/settings.env" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/settings.env"
fi
if [[ -f "${ROOT_DIR}/.env" ]]; then
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
fi

DEV_USER="${AGY_DEV_USER:-}"
GATEWAY_URL="${GATEWAY_URL:-https://REPLACE_WITH_GATEWAY_URL}"
GATEWAY_API_KEY="${GATEWAY_API_KEY:-REPLACE_WITH_GATEWAY_API_KEY}"
GATEWAY_WIRE_PROTOCOL="${GATEWAY_WIRE_PROTOCOL:-genai}"
CA_CERT_PATH="${CA_CERT_PATH:-/etc/ssl/certs/ca-certificates.crt}"
COST_CENTER="${COST_CENTER:-CC-9941-SEC}"
CORPORATE_BU="${CORPORATE_BU:-Enterprise-Security}"
ENTERPRISE_SURFACE="${ENTERPRISE_SURFACE:-MDM-Managed-Workstation}"
BILLING_PROJECT_ID="${BILLING_PROJECT_ID:-REPLACE_WITH_PROJECT_ID}"
DEPLOY_ACP_CONFIGS="${DEPLOY_ACP_CONFIGS:-true}"
ACTION="deploy"

# ------------------------------------------------------------------------------
# Function: log_msg
# Summary: Emits structured ISO-8601 UTC log entries with severity levels.
# Parameters:
#   $1 (str): Severity level (INFO, WARN, ERROR, DEBUG).
#   $2 (str): Log message text.
# Return Value:
#   0 on success.
# Exceptions/Errors:
#   None.
# ------------------------------------------------------------------------------
log_msg() {
  local level="$1"
  local message="$2"
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  printf '[%s] [%s] %s\n' "${ts}" "${level}" "${message}"
}

# ------------------------------------------------------------------------------
# Function: print_usage
# Summary: Prints CLI options, environment overrides, and invocation examples.
# Parameters:
#   None.
# Return Value:
#   0 on success.
# Exceptions/Errors:
#   None.
# ------------------------------------------------------------------------------
print_usage() {
  cat <<'EOF'
Usage:
  sudo ./scripts/deploy_and_lock_macos.sh [OPTIONS]

Options:
  --user <USERNAME>           Developer macOS username to configure (auto-detected
                              from SUDO_USER / /dev/console or prompted if omitted)
  --gateway-url <HTTPS_URL>   Override Enterprise Gateway URL
  --gateway-api-key <KEY>     Override Enterprise Gateway Bearer API key
  --project <PROJECT_ID>      Override X-Goog-User-Project billing/quota project
  --configs-dir <PATH>        Override path to modular `configs/` directory
  --no-acp                    Skip JetBrains & Zed ACP configuration files
  --deploy                    Deploy policy files and lock with chflags schg (default)
  --unlock                    Remove chflags noschg,nouchg lock for maintenance
  --purge                     Unlock and delete all managed Antigravity policy files
  --status                    Audit file presence, ownership, modes, and schg flags
  -h, --help                  Display this help message and exit
EOF
}

# ==============================================================================
# BLOCK 2: ARGUMENT PARSING & TARGET USER VALIDATION
# ==============================================================================
# ------------------------------------------------------------------------------
# Function: parse_args
# Summary: Validates and parses command-line flags into script state variables.
# Parameters:
#   "$@" (array): Raw CLI arguments.
# Return Value:
#   0 on valid arguments.
# Exceptions/Errors:
#   Exits 1 on invalid flags or missing arguments.
# ------------------------------------------------------------------------------
parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --user)
        [[ $# -ge 2 && -n "${2:-}" ]] || { log_msg "ERROR" "--user requires a username."; exit 1; }
        DEV_USER="$2"; shift 2 ;;
      --gateway-url)
        [[ $# -ge 2 && -n "${2:-}" ]] || { log_msg "ERROR" "--gateway-url requires a URL."; exit 1; }
        GATEWAY_URL="$2"; shift 2 ;;
      --gateway-api-key)
        [[ $# -ge 2 && -n "${2:-}" ]] || { log_msg "ERROR" "--gateway-api-key requires a key."; exit 1; }
        GATEWAY_API_KEY="$2"; shift 2 ;;
      --project)
        [[ $# -ge 2 && -n "${2:-}" ]] || { log_msg "ERROR" "--project requires a GCP project ID."; exit 1; }
        BILLING_PROJECT_ID="$2"; shift 2 ;;
      --configs-dir)
        [[ $# -ge 2 && -n "${2:-}" ]] || { log_msg "ERROR" "--configs-dir requires a path."; exit 1; }
        CONFIGS_DIR="$2"; shift 2 ;;
      --no-acp)
        DEPLOY_ACP_CONFIGS="false"; shift ;;
      --deploy)
        ACTION="deploy"; shift ;;
      --unlock)
        ACTION="unlock"; shift ;;
      --purge)
        ACTION="purge"; shift ;;
      --status)
        ACTION="status"; shift ;;
      -h|--help)
        print_usage; exit 0 ;;
      *)
        log_msg "ERROR" "Unknown argument: $1"
        print_usage
        exit 1 ;;
    esac
  done
}

# ------------------------------------------------------------------------------
# Function: resolve_target_user
# Summary: Resolves active macOS console user via SUDO_USER, /dev/console
#          (Jamf/Kandji root context), or interactive prompt.
# Parameters:
#   None.
# Return Value:
#   Sets global DEV_USER.
# Exceptions/Errors:
#   Exits 1 if username cannot be determined.
# ------------------------------------------------------------------------------
resolve_target_user() {
  if [[ -z "${DEV_USER}" ]]; then
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
      DEV_USER="${SUDO_USER}"
      log_msg "INFO" "Auto-detected macOS user from SUDO_USER: '${DEV_USER}'"
    elif [[ -e "/dev/console" ]]; then
      local console_user
      console_user="$(stat -f "%Su" /dev/console 2>/dev/null || true)"
      if [[ -n "${console_user}" && "${console_user}" != "root" && "${console_user}" != "loginwindow" ]]; then
        DEV_USER="${console_user}"
        log_msg "INFO" "Auto-detected active macOS console user: '${DEV_USER}'"
      fi
    fi
  fi

  if [[ -z "${DEV_USER}" ]]; then
    if [[ -t 0 ]]; then
      read -r -p "Enter target macOS developer username to configure: " DEV_USER
    else
      log_msg "ERROR" "No developer username specified. Pass --user <USERNAME> or set AGY_DEV_USER."
      exit 1
    fi
  fi

  [[ -n "${DEV_USER}" ]] || { log_msg "ERROR" "Developer username cannot be empty."; exit 1; }
}

# ------------------------------------------------------------------------------
# Function: validate_environment
# Summary: Verifies root privileges, macOS user account, home path, and templates.
# Parameters:
#   None.
# Return Value:
#   Populates USER_HOME, EFFECTIVE_CA_PATH, and TARGET_FILES.
# Exceptions/Errors:
#   Exits 1 on validation failure.
# ------------------------------------------------------------------------------
validate_environment() {
  if [[ "${EUID}" -ne 0 ]]; then
    log_msg "ERROR" "This script must run as root (use sudo)."
    exit 1
  fi

  resolve_target_user

  if ! id "${DEV_USER}" >/dev/null 2>&1; then
    log_msg "ERROR" "macOS user '${DEV_USER}' does not exist on this Mac."
    exit 1
  fi

  if command -v dscl >/dev/null 2>&1; then
    USER_HOME="$(dscl . -read "/Users/${DEV_USER}" NFSHomeDirectory 2>/dev/null | awk '{print $2}' || true)"
  fi
  if [[ -z "${USER_HOME:-}" || ! -d "${USER_HOME}" ]]; then
    USER_HOME="/Users/${DEV_USER}"
  fi

  EFFECTIVE_CA_PATH="${CA_CERT_PATH}"
  if [[ "${EFFECTIVE_CA_PATH}" == "/etc/ssl/certs/ca-certificates.crt" && -f "/etc/ssl/cert.pem" ]]; then
    EFFECTIVE_CA_PATH="/etc/ssl/cert.pem"
  fi

  SRC_ADMIN="${CONFIGS_DIR}/01-admin-settings/admin_settings.json"
  SRC_CLI="${CONFIGS_DIR}/02-cli-settings/settings.json"
  SRC_DESKTOP="${CONFIGS_DIR}/03-desktop-hub-config/config.json"
  SRC_BROWSER="${CONFIGS_DIR}/04-browser-allowlist/browserAllowlist.txt"
  SRC_MCP="${CONFIGS_DIR}/05-mcp-config/mcp_config.json"
  SRC_HOOKS="${CONFIGS_DIR}/06-lifecycle-hooks/hooks.json"
  SRC_GUARD="${CONFIGS_DIR}/07-security-guard-scripts/agy_security_guard.sh"
  SRC_ACP="${CONFIGS_DIR}/08-acp-ide-configs/acp.json"
  SRC_ACP_AUTH="${CONFIGS_DIR}/08-acp-ide-configs/antigravity-acp-settings.json"

  TARGET_FILES=(
    "/Library/Application Support/Antigravity/admin_settings.json"
    "${USER_HOME}/.gemini/antigravity-cli/settings.json"
    "${USER_HOME}/.gemini/config/config.json"
    "${USER_HOME}/.gemini/config.json"
    "${USER_HOME}/.gemini/antigravity/browserAllowlist.txt"
    "${USER_HOME}/.gemini/config/mcp_config.json"
    "${USER_HOME}/.gemini/config/hooks.json"
    "/usr/local/bin/agy_security_guard.sh"
  )

  if [[ "${DEPLOY_ACP_CONFIGS}" == "true" ]]; then
    TARGET_FILES+=(
      "${USER_HOME}/.gemini/antigravity-acp/settings.json"
      "${USER_HOME}/.jetbrains/acp.json"
      "${USER_HOME}/Library/Application Support/Zed/settings.json"
    )
  fi

  if [[ "${ACTION}" == "deploy" ]]; then
    local required=("${SRC_ADMIN}" "${SRC_CLI}" "${SRC_DESKTOP}" "${SRC_BROWSER}" "${SRC_MCP}" "${SRC_HOOKS}" "${SRC_GUARD}")
    if [[ "${DEPLOY_ACP_CONFIGS}" == "true" ]]; then
      required+=("${SRC_ACP}" "${SRC_ACP_AUTH}")
    fi
    for f in "${required[@]}"; do
      if [[ ! -f "${f}" ]]; then
        log_msg "ERROR" "Required modular config template missing: ${f}"
        exit 1
      fi
    done
  fi
}

# ==============================================================================
# BLOCK 3: UNLOCK, DEPLOY, PURGE & AUDIT OPERATIONS
# ==============================================================================
# ------------------------------------------------------------------------------
# Function: unlock_policy_files
# Summary: Clears macOS `schg` and `uchg` immutable flags across managed files.
# Parameters:
#   None.
# Return Value:
#   0 on completion.
# Exceptions/Errors:
#   Ignores missing files.
# ------------------------------------------------------------------------------
unlock_policy_files() {
  log_msg "INFO" "Removing macOS system-immutable flag (chflags noschg,nouchg) from managed policy files..."
  for file in "${TARGET_FILES[@]}"; do
    if [[ -e "${file}" ]]; then
      chflags noschg,nouchg "${file}" 2>/dev/null || true
    fi
  done
  log_msg "INFO" "All managed policy files unlocked."
}

# ------------------------------------------------------------------------------
# Function: purge_policy_files
# Summary: Unlocks and removes all managed policy files on uninstall (`--purge`).
# Parameters:
#   None.
# Return Value:
#   0 on completion.
# Exceptions/Errors:
#   None.
# ------------------------------------------------------------------------------
purge_policy_files() {
  unlock_policy_files
  log_msg "WARN" "Deleting managed Antigravity policy files for user '${DEV_USER}'..."
  for file in "${TARGET_FILES[@]}"; do
    if [[ -e "${file}" ]]; then
      rm -f "${file}"
      log_msg "INFO" "Removed: ${file}"
    fi
  done
}

# ------------------------------------------------------------------------------
# Function: render_gateway_placeholders
# Summary: Substitutes gateway URL, API key, billing project, CA path, and
#          FinOps headers into a destination JSON file.
# Parameters:
#   $1 (str): Source template path.
#   $2 (str): Destination output path.
# Return Value:
#   0 on success.
# Exceptions/Errors:
#   Exits non-zero on write failure.
# ------------------------------------------------------------------------------
render_gateway_placeholders() {
  local src="$1"
  local dst="$2"
  sed \
    -e "s|https://REPLACE_WITH_GATEWAY_URL|${GATEWAY_URL%/}|g" \
    -e "s|REPLACE_WITH_GATEWAY_API_KEY|${GATEWAY_API_KEY}|g" \
    -e "s|REPLACE_WITH_PROJECT_ID|${BILLING_PROJECT_ID}|g" \
    -e "s|\"wireProtocol\": \"genai\"|\"wireProtocol\": \"${GATEWAY_WIRE_PROTOCOL}\"|g" \
    -e "s|/etc/ssl/certs/ca-certificates.crt|${EFFECTIVE_CA_PATH}|g" \
    -e "s|CC-9941-SEC|${COST_CENTER}|g" \
    -e "s|Enterprise-Security|${CORPORATE_BU}|g" \
    -e "s|MDM-Managed-Workstation|${ENTERPRISE_SURFACE}|g" \
    "${src}" > "${dst}"
}

# ------------------------------------------------------------------------------
# Function: deploy_and_lock_policies
# Summary: Installs all modular policy files, normalizes CLI settings.json via
#          `agy --version`, sets root:wheel ownership, and locks via `chflags schg`.
# Parameters:
#   None.
# Return Value:
#   0 on success.
# Exceptions/Errors:
#   Exits non-zero if installation or chflags fails.
# ------------------------------------------------------------------------------
deploy_and_lock_policies() {
  unlock_policy_files

  log_msg "INFO" "Creating target configuration directories for '${DEV_USER}' (${USER_HOME})..."
  mkdir -p \
    "/Library/Application Support/Antigravity" \
    "${USER_HOME}/.gemini/antigravity-cli" \
    "${USER_HOME}/.gemini/config" \
    "${USER_HOME}/.gemini/antigravity" \
    /usr/local/bin

  if [[ "${DEPLOY_ACP_CONFIGS}" == "true" ]]; then
    mkdir -p \
      "${USER_HOME}/.gemini/antigravity-acp" \
      "${USER_HOME}/.jetbrains" \
      "${USER_HOME}/Library/Application Support/Zed"
  fi

  log_msg "INFO" "Rendering and installing modular policy files from '${CONFIGS_DIR}'..."
  render_gateway_placeholders "${SRC_ADMIN}" "/Library/Application Support/Antigravity/admin_settings.json"
  cp -f "${SRC_BROWSER}" "${USER_HOME}/.gemini/antigravity/browserAllowlist.txt"
  cp -f "${SRC_MCP}"     "${USER_HOME}/.gemini/config/mcp_config.json"
  cp -f "${SRC_HOOKS}"   "${USER_HOME}/.gemini/config/hooks.json"
  cp -f "${SRC_GUARD}"   "/usr/local/bin/agy_security_guard.sh"

  sed -e "s|/Users/__DEV_USER__|${USER_HOME}|g" -e "s|__DEV_USER__|${DEV_USER}|g" \
    "${SRC_CLI}" > "${USER_HOME}/.gemini/antigravity-cli/settings.json"

  local tmp_cfg
  tmp_cfg="$(mktemp)"
  sed -e "s|/Users/__DEV_USER__|${USER_HOME}|g" -e "s|__DEV_USER__|${DEV_USER}|g" \
    "${SRC_DESKTOP}" > "${tmp_cfg}"
  if [[ -s "${USER_HOME}/.gemini/config/config.json" ]] && command -v jq >/dev/null 2>&1; then
    jq -s '.[0] * .[1]' "${USER_HOME}/.gemini/config/config.json" "${tmp_cfg}" > "${tmp_cfg}.merged"
    cp -f "${tmp_cfg}.merged" "${USER_HOME}/.gemini/config/config.json"
    rm -f "${tmp_cfg}.merged"
  else
    cp -f "${tmp_cfg}" "${USER_HOME}/.gemini/config/config.json"
  fi
  cp -f "${USER_HOME}/.gemini/config/config.json" "${USER_HOME}/.gemini/config.json"
  rm -f "${tmp_cfg}"

  if [[ "${DEPLOY_ACP_CONFIGS}" == "true" ]]; then
    cp -f "${SRC_ACP_AUTH}" "${USER_HOME}/.gemini/antigravity-acp/settings.json"
    render_gateway_placeholders "${SRC_ACP}" "${USER_HOME}/.jetbrains/acp.json"
    render_gateway_placeholders "${SRC_ACP}" "${USER_HOME}/Library/Application Support/Zed/settings.json"
  fi

  chown "${DEV_USER}:staff" \
    "${USER_HOME}/.gemini" \
    "${USER_HOME}/.gemini/antigravity-cli" \
    "${USER_HOME}/.gemini/config" \
    "${USER_HOME}/.gemini/antigravity"
  if [[ "${DEPLOY_ACP_CONFIGS}" == "true" ]]; then
    chown "${DEV_USER}:staff" \
      "${USER_HOME}/.gemini/antigravity-acp" \
      "${USER_HOME}/.jetbrains" \
      "${USER_HOME}/Library/Application Support/Zed"
  fi

  # Normalize sparse CLI settings.json via `agy --version` BEFORE applying chflags schg
  chown "${DEV_USER}:staff" "${USER_HOME}/.gemini/antigravity-cli/settings.json"
  chmod 0644 "${USER_HOME}/.gemini/antigravity-cli/settings.json"
  if command -v agy >/dev/null 2>&1; then
    log_msg "INFO" "Running 'agy --version' as '${DEV_USER}' to normalize settings.json (MarshalSparse)..."
    su - "${DEV_USER}" -c "agy --version" >/dev/null 2>&1 || true
  fi

  log_msg "INFO" "Setting root:wheel ownership and strict permissions across ${#TARGET_FILES[@]} policy files..."
  for file in "${TARGET_FILES[@]}"; do
    chown root:wheel "${file}"
    if [[ "${file}" == "/usr/local/bin/agy_security_guard.sh" ]]; then
      chmod 0755 "${file}"
    else
      chmod 0644 "${file}"
    fi
  done

  log_msg "INFO" "Applying macOS system-immutable flag (chflags schg)..."
  for file in "${TARGET_FILES[@]}"; do
    chflags schg "${file}"
  done

  log_msg "INFO" "macOS MDM policy deployment and system-immutable locking complete for '${DEV_USER}'."
  check_status
}

# ------------------------------------------------------------------------------
# Function: check_status
# Summary: Audits ownership, file permissions, and `schg` flags via `ls -lO`.
# Parameters:
#   None.
# Return Value:
#   0 if all expected files exist; 1 if any file is missing.
# Exceptions/Errors:
#   Logs WARN for missing files.
# ------------------------------------------------------------------------------
check_status() {
  log_msg "INFO" "Auditing Antigravity MDM policy files on macOS for '${DEV_USER}'..."
  local missing=0
  for file in "${TARGET_FILES[@]}"; do
    if [[ -e "${file}" ]]; then
      ls -lO "${file}"
    else
      log_msg "WARN" "MISSING: ${file}"
      missing=1
    fi
  done
  return "${missing}"
}

# ==============================================================================
# BLOCK 4: MAIN ENTRYPOINT
# ==============================================================================
main() {
  parse_args "$@"
  validate_environment

  case "${ACTION}" in
    deploy) deploy_and_lock_policies ;;
    unlock) unlock_policy_files ;;
    purge)  purge_policy_files ;;
    status) check_status ;;
  esac
}

main "$@"
