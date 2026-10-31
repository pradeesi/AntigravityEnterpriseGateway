#!/usr/bin/env bash
# ==============================================================================
# File: uninstall.sh
# Purpose: Unified cross-Unix unlocker and optional policy file remover for
#          Antigravity Enterprise Gateway & Security Configs on Linux and macOS.
# Architecture/Context: By default (`--unlock`), removes kernel immutability
#          (`chattr -i` on Linux, `chflags noschg,nouchg` on macOS) so an
#          administrator can inspect or edit files. Passing `--purge` unlocks
#          AND deletes all managed policy files cleanly.
# Dependencies/Side Effects: Requires `sudo` / root privileges.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ------------------------------------------------------------------------------
# Function: print_usage
# Summary: Displays unlocker/remover flags and Windows PowerShell equivalents.
# Parameters:
#   None.
# Return Value:
#   0 on success.
# Exceptions/Errors:
#   None.
# ------------------------------------------------------------------------------
print_usage() {
  cat <<'EOF'
Antigravity Enterprise Config — Unified Workstation Unlocker & Uninstaller

Usage (Linux & macOS):
  sudo ./uninstall.sh [OPTIONS]

Options:
  --user <USERNAME>   Developer OS username (auto-detected or prompted if omitted)
  --unlock            Remove kernel immutable flags only, keeping files on disk (default)
  --purge             Unlock AND delete all managed Antigravity policy files
  --no-acp            Exclude JetBrains & Zed ACP files from unlock/purge scope
  -h, --help          Show this help banner and exit

Windows Equivalents (Run in Elevated Administrator PowerShell):
  .\scripts\deploy_and_lock_windows.ps1 -Action Unlock -User <USERNAME>
  .\scripts\deploy_and_lock_windows.ps1 -Action Purge  -User <USERNAME>
EOF
}

# ------------------------------------------------------------------------------
# Function: main
# Summary: Dispatches `--unlock` (default) or `--purge` to the OS-specific script.
# Parameters:
#   "$@" (array): CLI arguments.
# Return Value:
#   Exit status of platform script.
# Exceptions/Errors:
#   Exits 1 on unsupported host OS.
# ------------------------------------------------------------------------------
main() {
  local mode_flag="--unlock"
  local forward_args=()

  while [[ $# -gt 0 ]]; do
    case "$1" in
      -h|--help)
        print_usage
        exit 0
        ;;
      --purge)
        mode_flag="--purge"
        shift
        ;;
      --unlock)
        mode_flag="--unlock"
        shift
        ;;
      *)
        forward_args+=("$1")
        shift
        ;;
    esac
  done

  local os_kernel
  os_kernel="$(uname -s)"

  case "${os_kernel}" in
    Linux)
      exec bash "${SCRIPT_DIR}/scripts/deploy_and_lock_linux.sh" "${mode_flag}" ${forward_args[@]+"${forward_args[@]}"}
      ;;
    Darwin)
      exec bash "${SCRIPT_DIR}/scripts/deploy_and_lock_macos.sh" "${mode_flag}" ${forward_args[@]+"${forward_args[@]}"}
      ;;
    *)
      printf '[ERROR] Unsupported Unix kernel: %s. On Windows, run scripts\\deploy_and_lock_windows.ps1 -Action Unlock|Purge.\n' "${os_kernel}" >&2
      exit 1
      ;;
  esac
}

main "$@"
