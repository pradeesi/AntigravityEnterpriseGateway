#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: Linux (Ubuntu 22.04 LTS) GCP VM Provisioning Script
# ==============================================================================
# Author: Pradeep Singh
# License: Apache-2.0
#
# Purpose:
#   Provisions a Shielded Ubuntu 22.04 LTS Compute Engine VM on Google Cloud and
#   attaches `linux/startup_linux.sh` to install vanilla Antigravity (CLI `agy`,
#   Desktop App over XFCE4/XRDP, Browser Web UI on `:4400`, and VS Code +
#   `Google.google-antigravity` extension).
#
# Architecture / Context:
#   Can be invoked directly (`./linux/provision_linux_vm.sh`) or orchestrated by
#   top-level `./install.sh`. Sources `../common/gcp_vm_lib.sh` so networking,
#   project selection, and Shielded VM logic remain 100% DRY across OS targets.
#
# Dependencies / Side Effects:
#   - Requires authenticated `gcloud` CLI.
#   - Creates Compute Engine instance (`LINUX_VM_NAME`) and shared VPC firewall
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

VM_NAME="${VM_NAME:-${LINUX_VM_NAME}}"
MACHINE_TYPE="${MACHINE_TYPE:-${LINUX_MACHINE_TYPE}}"
DISK_SIZE="${DISK_SIZE:-${LINUX_DISK_SIZE}}"
DISK_TYPE="${DISK_TYPE:-${LINUX_DISK_TYPE}}"
IMAGE_FAMILY="${IMAGE_FAMILY:-${LINUX_IMAGE_FAMILY}}"
IMAGE_PROJECT="${IMAGE_PROJECT:-${LINUX_IMAGE_PROJECT}}"

NON_INTERACTIVE="${NON_INTERACTIVE:-false}"
PROJECT_EXPLICIT="false"


# ==============================================================================
# BLOCK 2: CLI USAGE & DEFENSIVE ARGUMENT PARSER
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Displays CLI usage help and default Linux VM settings from `settings.env`.
# Parameters:
#   - None.
# Return Value:
#   - Exits with status code 0.
# Exceptions/Errors:
#   - None.
# ------------------------------------------------------------------------------
usage() {
  cat <<EOF
Usage: ./linux/provision_linux_vm.sh [OPTIONS]

Provisions a Shielded Ubuntu 22.04 LTS GCE VM pre-configured with Vanilla
Antigravity (CLI, XFCE4/XRDP Desktop App, Web UI on :${HUB_WEB_PORT}, and VS Code + Plugin).

Options:
  -p, --project=PROJECT_ID     GCP Project ID (lists all projects interactively if omitted)
  -z, --zone=ZONE              Compute Engine Zone (default: ${ZONE})
  -r, --region=REGION          Compute Engine Region (default: ${REGION})
  -n, --name=VM_NAME           Linux VM Instance Name (default: ${VM_NAME})
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
# BLOCK 3: LINUX VM PROVISIONING & CONNECTION SUMMARY ORCHESTRATION
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Provisions VPC/firewall + Linux GCE instance and prints SSH/RDP/Web UI commands.
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
  echo "  Google Antigravity — Vanilla Linux (Ubuntu 22.04 LTS) GCP VM Provisioning"
  echo "================================================================================"

  require_gcloud_auth
  select_gcp_project "${NON_INTERACTIVE}" "${PROJECT_EXPLICIT}"
  ensure_gcp_vm_network_and_firewall

  cat <<EOF

--------------------------------------------------------------------------------
  Linux VM Deployment Configuration:
    Project ID        : ${PROJECT_ID}
    Zone / Region     : ${ZONE} (${REGION})
    VPC Network       : ${DETECTED_NETWORK} ${DETECTED_SUBNET:+(Subnet: ${DETECTED_SUBNET})}
    VM Instance       : ${VM_NAME} (${MACHINE_TYPE}, ${DISK_SIZE} ${DISK_TYPE})
    OS Image Family   : ${IMAGE_FAMILY} (${IMAGE_PROJECT})
    Startup Script    : ${SCRIPT_DIR}/startup_linux.sh
--------------------------------------------------------------------------------
EOF

  create_or_recreate_gce_vm \
    "${VM_NAME}" \
    "${MACHINE_TYPE}" \
    "${DISK_SIZE}" \
    "${DISK_TYPE}" \
    "${IMAGE_FAMILY}" \
    "${IMAGE_PROJECT}" \
    "startup-script" \
    "${SCRIPT_DIR}/startup_linux.sh" \
    "Vanilla Google Antigravity Linux Client Workstation VM (CLI, Desktop, VS Code + AGY Plugin)"

  cat <<EOF

================================================================================
  VANILLA ANTIGRAVITY LINUX CLIENT VM READY
================================================================================
  Linux VM      : ${VM_NAME}
  External IP   : ${LAST_VM_EXTERNAL_IP}
  Internal IP   : ${LAST_VM_INTERNAL_IP}
--------------------------------------------------------------------------------
  1. Connect via SSH & Run Antigravity CLI ('agy'):
     gcloud compute ssh ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID}
     $ agy --version
     $ agy

  2. Connect via Remote Desktop (XFCE4 / XRDP on tcp:3389):
     Connect your RDP client to ${LAST_VM_EXTERNAL_IP}:3389 (or tunnel via IAP)
     Launch 'antigravity-desktop' or 'Visual Studio Code' ('code')

  3. Launch Antigravity Browser Web UI (Port ${HUB_WEB_PORT}):
     gcloud compute ssh ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID} -- -L ${HUB_WEB_PORT}:localhost:${HUB_WEB_PORT}
     $ antigravity-web
     Open: http://${LAST_VM_EXTERNAL_IP}:${HUB_WEB_PORT} (or http://localhost:${HUB_WEB_PORT})

  4. Tail First-Boot Installation Log (~2 mins on initial creation):
     gcloud compute ssh ${VM_NAME} --zone=${ZONE} --project=${PROJECT_ID} --command='tail -n 30 /var/log/antigravity-install.log'

  Teardown Command:
     ./linux/deprovision_linux_vm.sh --project=${PROJECT_ID} --zone=${ZONE}
================================================================================
EOF
}

main "$@"
