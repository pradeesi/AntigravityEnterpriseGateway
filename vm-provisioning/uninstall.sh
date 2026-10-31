#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: Unified GCP Client VM Deprovisioning Orchestrator (Linux & Windows)
# ==============================================================================
# Author: Pradeep Singh
# License: Apache-2.0
#
# Purpose:
#   Clean, reference-safe uninstallation script that tears down the Antigravity
#   Linux GCE VM (`linux`), Windows GCE VM (`windows`), or `both`, and removes
#   the shared VPC firewall rule / auto-created subnet once no tagged client VMs
#   remain in the target GCP project.
#
# Architecture / Context:
#   Mirrors `enterprise-gateway/uninstall.sh` in structure:
#     - BLOCK 1: Library & Unified Settings Initialization (`settings.env` + `.env`).
#     - BLOCK 2: CLI Usage & Flag Parser (`parse_args`).
#     - BLOCK 3: Interactive GCP Project Selector & Teardown Confirmation.
#     - BLOCK 4: OS-Target Deprovisioning Dispatcher.
#     - BLOCK 5: Main Entrypoint & Completion Summary.
#
# Dependencies / Side Effects:
#   - Requires authenticated `gcloud` CLI.
#   - Permanently deletes selected Compute Engine VMs and unused network rules.
# ==============================================================================

set -euo pipefail

# ==============================================================================
# BLOCK 1: LIBRARY & UNIFIED SETTINGS INITIALIZATION
# ==============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# shellcheck source=common/gcp_vm_lib.sh
source "${SCRIPT_DIR}/common/gcp_vm_lib.sh"
load_vm_settings "${SCRIPT_DIR}"

NON_INTERACTIVE="false"
PROJECT_EXPLICIT="false"
OS_EXPLICIT="false"


# ==============================================================================
# BLOCK 2: CLI USAGE & DEFENSIVE FLAG PARSER
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Prints CLI usage instructions and defaults loaded from `settings.env`.
# Parameters:
#   - None.
# Return Value:
#   - Exits with status code 0.
# Exceptions/Errors:
#   - None.
# ------------------------------------------------------------------------------
usage() {
  cat <<EOF
Usage: ./uninstall.sh [OPTIONS]

Tears down Antigravity Compute Engine client VMs (Linux, Windows, or both) and
cleans up shared VPC firewall/subnet resources when no '${NETWORK_TAG}' VMs remain.

Options:
  -p, --project=PROJECT_ID       GCP Project ID (lists all projects interactively if omitted)
  -o, --os=both|linux|windows    Target VM OS to deprovision (default: ${TARGET_OS})
  -z, --zone=ZONE                Compute Engine Zone (default: ${ZONE}, or auto-detected)
      --linux-name=NAME          Linux VM Instance Name (default: ${LINUX_VM_NAME})
      --windows-name=NAME        Windows VM Instance Name (default: ${WINDOWS_VM_NAME})
      --non-interactive          Do not prompt interactively for project or OS selection
  -y, --yes                      Skip interactive teardown confirmation prompt
  -h, --help                     Show this help message
EOF
  exit 0
}

# ------------------------------------------------------------------------------
# Summary: Parses `--flag=value` and `--flag value` CLI options defensively.
# Parameters:
#   - "$@" (array): Command-line arguments passed to `uninstall.sh`.
# Return Value:
#   - Returns 0 on valid flags.
# Exceptions/Errors:
#   - Exits with code 1 on unknown flags or missing values.
# ------------------------------------------------------------------------------
parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -p|--project)
        [[ -z "${2:-}" ]] && { log_error "--project requires a GCP Project ID."; exit 1; }
        PROJECT_ID="$2"
        PROJECT_EXPLICIT="true"
        shift 2
        ;;
      --project=*)
        PROJECT_ID="${1#*=}"
        PROJECT_EXPLICIT="true"
        shift
        ;;
      -o|--os)
        [[ -z "${2:-}" ]] && { log_error "--os requires 'both', 'linux', or 'windows'."; exit 1; }
        TARGET_OS="$2"
        OS_EXPLICIT="true"
        shift 2
        ;;
      --os=*)
        TARGET_OS="${1#*=}"
        OS_EXPLICIT="true"
        shift
        ;;
      -z|--zone)
        [[ -z "${2:-}" ]] && { log_error "--zone requires a Compute Engine zone."; exit 1; }
        ZONE="$2"
        shift 2
        ;;
      --zone=*)
        ZONE="${1#*=}"
        shift
        ;;
      --linux-name)
        [[ -z "${2:-}" ]] && { log_error "--linux-name requires a VM name."; exit 1; }
        LINUX_VM_NAME="$2"
        shift 2
        ;;
      --linux-name=*)
        LINUX_VM_NAME="${1#*=}"
        shift
        ;;
      --windows-name)
        [[ -z "${2:-}" ]] && { log_error "--windows-name requires a VM name."; exit 1; }
        WINDOWS_VM_NAME="$2"
        shift 2
        ;;
      --windows-name=*)
        WINDOWS_VM_NAME="${1#*=}"
        shift
        ;;
      --non-interactive)
        NON_INTERACTIVE="true"
        shift
        ;;
      -y|--yes)
        AUTO_APPROVE="true"
        shift
        ;;
      -h|--help)
        usage
        ;;
      *)
        log_error "Unknown argument: $1"
        usage
        ;;
    esac
  done
}


# ==============================================================================
# BLOCK 3: TARGET OS SELECTION & TEARDOWN CONFIRMATION
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Validates `TARGET_OS` and prompts operator for teardown confirmation unless `--yes` is set.
# Parameters:
#   - None.
# Return Value:
#   - Returns 0 if confirmed; exits 0 cleanly if cancelled.
# Exceptions/Errors:
#   - Exits with code 1 if `TARGET_OS` is invalid.
# ------------------------------------------------------------------------------
confirm_vm_uninstall() {
  if [[ "${NON_INTERACTIVE}" != "true" && "${OS_EXPLICIT}" != "true" && "${AUTO_APPROVE,,}" != "true" ]]; then
    local os_input=""
    read -r -p "Target OS to deprovision (both/linux/windows) [${TARGET_OS}]: " os_input
    TARGET_OS="${os_input:-${TARGET_OS}}"
  fi

  TARGET_OS="${TARGET_OS,,}"
  if [[ "${TARGET_OS}" != "both" && "${TARGET_OS}" != "linux" && "${TARGET_OS}" != "windows" ]]; then
    log_error "Invalid TARGET_OS='${TARGET_OS}'. Must be 'both', 'linux', or 'windows'."
    exit 1
  fi

  if [[ "${AUTO_APPROVE,,}" == "true" ]]; then
    return 0
  fi

  cat <<EOF

================================================================================
  VM UNINSTALLATION PLAN — PROJECT: ${PROJECT_ID}
================================================================================
  Target OS Scope     : ${TARGET_OS}
  Linux VM Target     : $( [[ "${TARGET_OS}" == "both" || "${TARGET_OS}" == "linux" ]] && echo "${LINUX_VM_NAME}" || echo "(skipped)" )
  Windows VM Target   : $( [[ "${TARGET_OS}" == "both" || "${TARGET_OS}" == "windows" ]] && echo "${WINDOWS_VM_NAME}" || echo "(skipped)" )
  Shared Firewall     : ${FIREWALL_RULE} (deleted ONLY if no '${NETWORK_TAG}' VMs remain)
================================================================================
EOF
  local reply=""
  read -r -p "Are you sure you want to permanently delete the selected VM resource(s)? [y/N]: " reply
  if [[ ! "${reply}" =~ ^[Yy]$ ]]; then
    log_info "Uninstallation cancelled by user."
    exit 0
  fi
}


# ==============================================================================
# BLOCK 4: OS-TARGET DEPROVISIONING DISPATCHER
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Delegates VM deletion to `linux/deprovision_linux_vm.sh` and/or `windows/deprovision_windows_vm.sh`.
# Parameters:
#   - None.
# Return Value:
#   - Returns 0 when all selected VMs and unused shared network rules are removed.
# Exceptions/Errors:
#   - Exits non-zero if a child deprovisioner fails.
# ------------------------------------------------------------------------------
dispatch_vm_deprovisioning() {
  export PROJECT_ID ZONE NETWORK_TAG FIREWALL_RULE

  if [[ "${TARGET_OS}" == "both" || "${TARGET_OS}" == "linux" ]]; then
    bash "${SCRIPT_DIR}/linux/deprovision_linux_vm.sh" \
      "--project=${PROJECT_ID}" \
      "--zone=${ZONE}" \
      "--name=${LINUX_VM_NAME}" \
      "--non-interactive" \
      "--yes"
  fi

  if [[ "${TARGET_OS}" == "both" || "${TARGET_OS}" == "windows" ]]; then
    bash "${SCRIPT_DIR}/windows/deprovision_windows_vm.sh" \
      "--project=${PROJECT_ID}" \
      "--zone=${ZONE}" \
      "--name=${WINDOWS_VM_NAME}" \
      "--non-interactive" \
      "--yes"
  fi
}


# ==============================================================================
# BLOCK 5: MAIN ENTRYPOINT & COMPLETION SUMMARY
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Runs argument parsing, project selection, confirmation, and VM teardown.
# Parameters:
#   - "$@" (array): Command-line arguments.
# Return Value:
#   - Returns 0 on completion.
# Exceptions/Errors:
#   - Exits non-zero on invalid flags or inaccessible GCP project.
# ------------------------------------------------------------------------------
main() {
  parse_args "$@"
  require_gcloud_auth
  select_gcp_project "${NON_INTERACTIVE}" "${PROJECT_EXPLICIT}"
  confirm_vm_uninstall
  dispatch_vm_deprovisioning

  cat <<EOF

================================================================================
  GCP CLIENT VM UNINSTALLATION COMPLETE
================================================================================
  GCP Project ID : ${PROJECT_ID}
  Removed Scope  : ${TARGET_OS}
================================================================================
EOF
}

main "$@"
