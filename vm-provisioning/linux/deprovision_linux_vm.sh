#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: Linux (Ubuntu 22.04 LTS) GCP VM Deprovisioning Script
# ==============================================================================
# Author: Pradeep Singh
# License: Apache-2.0
#
# Purpose:
#   Cleanly deletes the Antigravity Linux Compute Engine VM (`LINUX_VM_NAME`)
#   and removes the shared VPC firewall rule / auto-created subnet ONLY if no
#   other client VMs tagged with `NETWORK_TAG` remain in the project.
#
# Architecture / Context:
#   Can be run standalone (`./linux/deprovision_linux_vm.sh`) or invoked by
#   top-level `./uninstall.sh`. Sources `../common/gcp_vm_lib.sh`.
#
# Dependencies / Side Effects:
#   - Requires authenticated `gcloud` CLI.
#   - Permanently deletes `LINUX_VM_NAME` and unused shared network rules.
# ==============================================================================

set -euo pipefail

# ==============================================================================
# BLOCK 1: LIBRARY & UNIFIED SETTINGS INITIALIZATION
# ==============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

# shellcheck source=../common/gcp_vm_lib.sh
source "${ROOT_DIR}/common/gcp_vm_lib.sh"
load_vm_settings "${ROOT_DIR}"

VM_NAME="${VM_NAME:-${LINUX_VM_NAME}}"
NON_INTERACTIVE="${NON_INTERACTIVE:-false}"
PROJECT_EXPLICIT="false"


# ==============================================================================
# BLOCK 2: CLI USAGE & DEFENSIVE ARGUMENT PARSER
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Prints CLI usage instructions for Linux VM teardown and exits 0.
# Parameters:
#   - None.
# Return Value:
#   - Exits with status code 0.
# Exceptions/Errors:
#   - None.
# ------------------------------------------------------------------------------
usage() {
  cat <<EOF
Usage: ./linux/deprovision_linux_vm.sh [OPTIONS]

Deletes the Antigravity Linux GCE VM and safely cleans up shared VPC firewall
and subnet resources if no sibling '${NETWORK_TAG}' VMs remain.

Options:
  -p, --project=PROJECT_ID     GCP Project ID (lists all projects interactively if omitted)
  -z, --zone=ZONE              Compute Engine Zone (default: ${ZONE}, or auto-detected)
  -n, --name=VM_NAME           Linux VM Instance Name (default: ${VM_NAME})
  -y, --yes                    Skip interactive confirmation prompt
      --non-interactive        Do not prompt interactively (requires PROJECT_ID)
  -h, --help                   Show this help message
EOF
  exit 0
}

# ------------------------------------------------------------------------------
# Summary: Parses `--flag=value` and `--flag value` CLI flags defensively.
# Parameters:
#   - "$@" (array): Command-line arguments.
# Return Value:
#   - Returns 0 on valid flags.
# Exceptions/Errors:
#   - Exits with code 1 on unknown or missing flag values.
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
      -z|--zone)
        [[ -z "${2:-}" ]] && { log_error "--zone requires a Compute Engine zone."; exit 1; }
        ZONE="$2"
        shift 2
        ;;
      --zone=*)
        ZONE="${1#*=}"
        shift
        ;;
      -n|--name|--vm-name)
        [[ -z "${2:-}" ]] && { log_error "--name requires a VM instance name."; exit 1; }
        VM_NAME="$2"
        shift 2
        ;;
      --name=*|--vm-name=*)
        VM_NAME="${1#*=}"
        shift
        ;;
      -y|--yes)
        AUTO_APPROVE="true"
        shift
        ;;
      --non-interactive)
        NON_INTERACTIVE="true"
        shift
        ;;
      -h|--help)
        usage
        ;;
      -*)
        log_error "Unknown option: $1"
        usage
        ;;
      *)
        if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "REPLACE_WITH_PROJECT_ID" ]]; then
          PROJECT_ID="$1"
          PROJECT_EXPLICIT="true"
        fi
        shift
        ;;
    esac
  done
}


# ==============================================================================
# BLOCK 3: CONFIRMATION & SAFE TEARDOWN EXECUTION
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Confirms target resources, deletes the Linux VM, and cleans unused network rules.
# Parameters:
#   - "$@" (array): Command-line arguments.
# Return Value:
#   - Returns 0 on successful teardown.
# Exceptions/Errors:
#   - Exits 0 cleanly if operator declines confirmation; exits 1 on gcloud auth failure.
# ------------------------------------------------------------------------------
main() {
  parse_args "$@"

  echo "================================================================================"
  echo "  Google Antigravity — Linux GCP VM Deprovisioning"
  echo "================================================================================"

  require_gcloud_auth
  select_gcp_project "${NON_INTERACTIVE}" "${PROJECT_EXPLICIT}"

  ZONE="$(resolve_vm_zone "${VM_NAME}" "${ZONE}")"
  REGION="${ZONE%-*}"

  cat <<EOF

--------------------------------------------------------------------------------
  Targeted Teardown Plan (${PROJECT_ID}):
    Linux VM Instance  : ${VM_NAME} (Zone: ${ZONE})
    Shared Firewall    : ${FIREWALL_RULE} (deleted ONLY if no '${NETWORK_TAG}' VMs remain)
--------------------------------------------------------------------------------
EOF

  if [[ "${AUTO_APPROVE,,}" != "true" ]]; then
    local confirm=""
    read -r -p "Are you sure you want to permanently delete '${VM_NAME}'? [y/N]: " confirm
    if [[ "${confirm,,}" != "y" && "${confirm,,}" != "yes" ]]; then
      log_info "Deprovisioning cancelled. No resources were deleted."
      exit 0
    fi
  fi

  delete_gce_vm_instance "${VM_NAME}" "${ZONE}"
  cleanup_shared_vm_network_if_unused "${REGION}"

  echo ""
  echo "================================================================================"
  echo "  DEPROVISIONING COMPLETE — Linux VM '${VM_NAME}' removed."
  echo "================================================================================"
}

main "$@"
