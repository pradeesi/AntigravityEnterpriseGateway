#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: Windows Server 2022 GCP VM Provisioning Script
# ==============================================================================
# Author: Pradeep Singh
# License: Apache-2.0
#
# Purpose:
#   Provisions a Shielded Windows Server 2022 Datacenter Desktop Experience VM
#   on Google Compute Engine and attaches `windows/startup_windows.ps1` to
#   install vanilla Antigravity (CLI `agy.exe`, Desktop App `Antigravity-x64.exe`,
#   and Microsoft Visual Studio Code + `Google.google-antigravity` extension).
#
# Architecture / Context:
#   Can be invoked directly (`./windows/provision_windows_vm.sh`) or orchestrated
#   by top-level `./install.sh`. Sources `../common/gcp_vm_lib.sh` so networking,
#   project selection, and Shielded VM logic remain 100% DRY across OS targets.
#
# Dependencies / Side Effects:
#   - Requires authenticated `gcloud` CLI.
#   - Creates Compute Engine instance (`WINDOWS_VM_NAME`) and shared VPC firewall
#     rule (`FIREWALL_RULE`) if not already present.
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

VM_NAME="${VM_NAME:-${WINDOWS_VM_NAME}}"
MACHINE_TYPE="${MACHINE_TYPE:-${WINDOWS_MACHINE_TYPE}}"
DISK_SIZE="${DISK_SIZE:-${WINDOWS_DISK_SIZE}}"
DISK_TYPE="${DISK_TYPE:-${WINDOWS_DISK_TYPE}}"
IMAGE_FAMILY="${IMAGE_FAMILY:-${WINDOWS_IMAGE_FAMILY}}"
IMAGE_PROJECT="${IMAGE_PROJECT:-${WINDOWS_IMAGE_PROJECT}}"

NON_INTERACTIVE="${NON_INTERACTIVE:-false}"
PROJECT_EXPLICIT="false"


# ==============================================================================
# BLOCK 2: CLI USAGE & DEFENSIVE ARGUMENT PARSER
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Displays CLI usage help and default Windows VM settings from `settings.env`.
# Parameters:
#   - None.
# Return Value:
#   - Exits with status code 0.
# Exceptions/Errors:
#   - None.
# ------------------------------------------------------------------------------
usage() {
  cat <<EOF
Usage: ./windows/provision_windows_vm.sh [OPTIONS]

Provisions a Shielded Windows Server 2022 Datacenter GCE VM pre-configured with
Vanilla Antigravity (CLI agy.exe, Desktop App, and VS Code + Plugin).

Options:
  -p, --project=PROJECT_ID     GCP Project ID (lists all projects interactively if omitted)
  -z, --zone=ZONE              Compute Engine Zone (default: ${ZONE})
  -r, --region=REGION          Compute Engine Region (default: ${REGION})
  -n, --name=VM_NAME           Windows VM Instance Name (default: ${VM_NAME})
  -m, --machine-type=TYPE      Compute Engine Machine Type (default: ${MACHINE_TYPE})
  -y, --yes, --recreate        Automatically recreate VM if it already exists
      --non-interactive        Do not prompt interactively (requires PROJECT_ID)
  -h, --help                   Show this help message
EOF
  exit 0
}

# ------------------------------------------------------------------------------
# Summary: Parses both `--flag=value` and `--flag value` CLI styles defensively.
# Parameters:
#   - "$@" (array): Command-line arguments.
# Return Value:
#   - Returns 0 on valid flags.
# Exceptions/Errors:
#   - Exits with code 1 on unknown or malformed options.
# ------------------------------------------------------------------------------
parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -p|--project)
        [[ -z "${2:-}" ]] && { log_error "--project requires a non-empty GCP Project ID."; exit 1; }
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
      -r|--region)
        [[ -z "${2:-}" ]] && { log_error "--region requires a Compute Engine region."; exit 1; }
        REGION="$2"
        shift 2
        ;;
      --region=*)
        REGION="${1#*=}"
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
      -m|--machine-type)
        [[ -z "${2:-}" ]] && { log_error "--machine-type requires a machine type."; exit 1; }
        MACHINE_TYPE="$2"
        shift 2
        ;;
      --machine-type=*)
        MACHINE_TYPE="${1#*=}"
        shift
        ;;
      -y|--yes|--recreate)
        AUTO_RECREATE="true"
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
# BLOCK 3: WINDOWS VM PROVISIONING & CONNECTION SUMMARY ORCHESTRATION
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Provisions VPC/firewall + Windows GCE instance and prints RDP/serial instructions.
# Parameters:
#   - "$@" (array): Command-line arguments.
# Return Value:
#   - Returns 0 on successful VM creation.
# Exceptions/Errors:
#   - Exits non-zero if GCP authentication, project access, or GCE creation fails.
# ------------------------------------------------------------------------------
main() {
  parse_args "$@"

  echo "================================================================================"
  echo "  Google Antigravity — Vanilla Windows Server 2022 GCP VM Provisioning"
  echo "================================================================================"

  require_gcloud_auth
  select_gcp_project "${NON_INTERACTIVE}" "${PROJECT_EXPLICIT}"
  ensure_gcp_vm_network_and_firewall

  cat <<EOF

--------------------------------------------------------------------------------
  Windows VM Deployment Configuration:
    Project ID        : ${PROJECT_ID}
    Zone / Region     : ${ZONE} (${REGION})
    VPC Network       : ${DETECTED_NETWORK} ${DETECTED_SUBNET:+(Subnet: ${DETECTED_SUBNET})}
    VM Instance       : ${VM_NAME} (${MACHINE_TYPE}, ${DISK_SIZE} ${DISK_TYPE})
    OS Image Family   : ${IMAGE_FAMILY} (${IMAGE_PROJECT})
    Startup Script    : ${SCRIPT_DIR}/startup_windows.ps1
--------------------------------------------------------------------------------
EOF

  create_or_recreate_gce_vm \
    "${VM_NAME}" \
    "${MACHINE_TYPE}" \
    "${DISK_SIZE}" \
    "${DISK_TYPE}" \
    "${IMAGE_FAMILY}" \
    "${IMAGE_PROJECT}" \
    "windows-startup-script-ps1" \
    "${SCRIPT_DIR}/startup_windows.ps1" \
    "Vanilla Google Antigravity Windows Client Workstation VM (CLI, Desktop, VS Code + AGY Plugin)"

  cat <<EOF

================================================================================
  VANILLA ANTIGRAVITY WINDOWS CLIENT VM READY
================================================================================
  Windows VM    : ${VM_NAME}
  External IP   : ${LAST_VM_EXTERNAL_IP}
  Internal IP   : ${LAST_VM_INTERNAL_IP}
--------------------------------------------------------------------------------
  1. Generate Windows RDP Credentials (${WINDOWS_ADMIN_USER}):
     gcloud compute reset-windows-password ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID} --user=${WINDOWS_ADMIN_USER} --quiet

  2. Connect via Remote Desktop (RDP — tcp:3389):
     Connect Microsoft Remote Desktop / Remmina / FreeRDP to: ${LAST_VM_EXTERNAL_IP}:3389
     (Or tunnel over IAP: gcloud compute start-iap-tunnel ${VM_NAME} 3389 --zone=${ZONE} --project=${PROJECT_ID} --local-host-port=localhost:13389)

  3. Verify Vanilla Antigravity Inside Windows PowerShell:
     PS> agy --version
     PS> code --list-extensions --show-versions
     PS> Get-Content C:\AntigravitySetup\antigravity-install.log -Tail 30

  4. Check First-Boot Sysprep / Startup Progress from Workstation (~2-3 mins):
     gcloud compute instances get-serial-port-output ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID} --port=1 | tail -n 35

  Teardown Command:
     ./windows/deprovision_windows_vm.sh --project=${PROJECT_ID} --zone=${ZONE}
================================================================================
EOF
}

main "$@"
