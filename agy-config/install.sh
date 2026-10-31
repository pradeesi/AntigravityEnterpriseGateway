#!/usr/bin/env bash
# ==============================================================================
# File: install.sh
# Purpose: Unified cross-Unix entrypoint for deploying, auditing, and kernel-
#          locking Google Antigravity Enterprise Gateway & Security Configs on
#          Linux (`chattr +i`) and macOS (`chflags schg`) workstations.
# Architecture/Context: Auto-detects the host OS (`uname -s`) and delegates all
#          CLI flags and `settings.env` / `.env` values to the corresponding
#          platform script in `scripts/deploy_and_lock_{linux,macos}.sh`.
#          For Windows workstations, run `scripts\deploy_and_lock_windows.ps1`
#          in an Elevated Administrator PowerShell session.
# Dependencies/Side Effects: Requires `sudo` / root privileges when running
#          deployment (`--deploy`) or status/unlock actions.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ------------------------------------------------------------------------------
# Function: print_usage
# Summary: Displays unified installer flags and Windows PowerShell equivalent.
# Parameters:
#   None.
# Return Value:
#   0 on success.
# Exceptions/Errors:
#   None.
# ------------------------------------------------------------------------------
print_usage() {
  cat <<'EOF'
Antigravity Enterprise Config — Unified Workstation Installer & Locker

Usage (Linux & macOS):
  sudo ./install.sh [OPTIONS]

Options:
  --user <USERNAME>           Developer OS username to configure (auto-detected
                              or prompted interactively if omitted)
  --gateway-url <HTTPS_URL>   Override Enterprise Gateway URL from settings.env/.env
  --gateway-api-key <KEY>     Override Enterprise Gateway Bearer API key
  --project <PROJECT_ID>      Override X-Goog-User-Project billing/quota project
  --no-acp                    Skip JetBrains & Zed ACP configuration files
  --status                    Audit deployed files, permissions, and kernel locks
  -h, --help                  Show this help banner and exit

Windows (Run in Elevated Administrator PowerShell):
  .\scripts\deploy_and_lock_windows.ps1 -Action Deploy -User <USERNAME>
EOF
}

# ------------------------------------------------------------------------------
# Function: main
# Summary: Detects host OS, handles --help without requiring root, and dispatches
#          to the OS-specific deployment & locking script.
# Parameters:
#   "$@" (array): CLI arguments forwarded to platform script.
# Return Value:
#   Exit status of platform script.
# Exceptions/Errors:
#   Exits 1 on unsupported host OS.
# ------------------------------------------------------------------------------
main() {
  for arg in "$@"; do
    case "${arg}" in
      -h|--help)
        print_usage
        exit 0
        ;;
    esac
  done

  local os_kernel
  os_kernel="$(uname -s)"

  case "${os_kernel}" in
    Linux)
      exec bash "${SCRIPT_DIR}/scripts/deploy_and_lock_linux.sh" "$@"
      ;;
    Darwin)
      exec bash "${SCRIPT_DIR}/scripts/deploy_and_lock_macos.sh" "$@"
      ;;
    *)
      printf '[ERROR] Unsupported Unix kernel: %s. On Windows, run scripts\\deploy_and_lock_windows.ps1 in Admin PowerShell.\n' "${os_kernel}" >&2
      exit 1
      ;;
  esac
}

main "$@"
