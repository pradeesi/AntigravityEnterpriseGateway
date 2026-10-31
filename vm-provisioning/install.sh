#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: Unified GCP Client VM Provisioning Orchestrator (Linux & Windows)
# ==============================================================================
# Author: Pradeep Singh
# License: Apache-2.0
#
# Purpose:
#   Unified interactive and automated installer that lists accessible Google
#   Cloud projects for selection, lets the operator review or customize defaults
#   from `settings.env`, and provisions Vanilla Antigravity Compute Engine VMs
#   for Ubuntu 22.04 LTS (`linux`), Windows Server 2022 (`windows`), or `both`.
#
# Architecture / Context:
#   Mirrors `enterprise-gateway/install.sh` in structure and ergonomics:
#     - BLOCK 1: Library & Unified Settings Initialization (`settings.env` + `.env`).
#     - BLOCK 2: CLI Usage & Flag Parser (`parse_args`).
#     - BLOCK 3: Interactive GCP Project Selector & Settings Customizer.
#     - BLOCK 4: OS-Target Provisioning Dispatcher (`linux` | `windows` | `both`).
#     - BLOCK 5: Main Entrypoint & Unified Summary.
#
# Dependencies / Side Effects:
#   - Requires authenticated `gcloud` CLI.
#   - Delegates VM creation to `linux/provision_linux_vm.sh` and/or
#     `windows/provision_windows_vm.sh`.
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
Usage: ./install.sh [OPTIONS]

Provisions Shielded Google Compute Engine VMs pre-installed with Vanilla
Antigravity (CLI, Desktop App, Web UI on :${HUB_WEB_PORT}, and VS Code + Plugin)
for Linux (Ubuntu 22.04 LTS), Windows Server 2022, or both.

Options:
  -p, --project=PROJECT_ID       GCP Project ID (lists all projects interactively if omitted)
  -o, --os=both|linux|windows    Target VM OS to provision (default: ${TARGET_OS})
  -r, --region=REGION            Compute Engine Region (default: ${REGION})
  -z, --zone=ZONE                Compute Engine Zone (default: ${ZONE})
      --linux-name=NAME          Linux VM Instance Name (default: ${LINUX_VM_NAME})
      --windows-name=NAME        Windows VM Instance Name (default: ${WINDOWS_VM_NAME})
      --linux-machine=TYPE       Linux Machine Type (default: ${LINUX_MACHINE_TYPE})
      --windows-machine=TYPE     Windows Machine Type (default: ${WINDOWS_MACHINE_TYPE})
  -y, --yes, --recreate          Automatically recreate existing VMs without prompting
      --non-interactive          Accept settings.env / CLI values without interactive prompts
  -h, --help                     Show this help message
EOF
  exit 0
}

# ------------------------------------------------------------------------------
# Summary: Parses `--flag=value` and `--flag value` CLI options defensively.
# Parameters:
#   - "$@" (array): Command-line arguments passed to `install.sh`.
# Return Value:
#   - Returns 0 on valid arguments.
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
        shift 2
        ;;
      --os=*)
        TARGET_OS="${1#*=}"
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
      --linux-machine)
        [[ -z "${2:-}" ]] && { log_error "--linux-machine requires a machine type."; exit 1; }
        LINUX_MACHINE_TYPE="$2"
        shift 2
        ;;
      --linux-machine=*)
        LINUX_MACHINE_TYPE="${1#*=}"
        shift
        ;;
      --windows-machine)
        [[ -z "${2:-}" ]] && { log_error "--windows-machine requires a machine type."; exit 1; }
        WINDOWS_MACHINE_TYPE="$2"
        shift 2
        ;;
      --windows-machine=*)
        WINDOWS_MACHINE_TYPE="${1#*=}"
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
      *)
        log_error "Unknown argument: $1"
        usage
        ;;
    esac
  done
}


# ==============================================================================
# BLOCK 3: INTERACTIVE SETTINGS REVIEW & CUSTOMIZER
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Displays effective `settings.env` values and lets the user override any parameter.
# Parameters:
#   - None (mutates global configuration variables if customized interactively).
# Return Value:
#   - Returns 0 after validating `TARGET_OS` and normalizing `REGION` / `ZONE`.
# Exceptions/Errors:
#   - Exits with code 1 if `TARGET_OS` is not `both`, `linux`, or `windows`.
# ------------------------------------------------------------------------------
review_and_customize_vm_settings() {
  normalize_region_and_zone

  if [[ "${NON_INTERACTIVE}" != "true" ]]; then
    cat <<EOF

================================================================================
  REVIEW UNIFIED GCP VM SETTINGS (Loaded from settings.env)
================================================================================
  GCP Project ID         : ${PROJECT_ID}
  Target VM OS           : ${TARGET_OS}  (options: both | linux | windows)
  Region / Zone          : ${REGION} / ${ZONE}
  Linux VM               : ${LINUX_VM_NAME} (${LINUX_MACHINE_TYPE}, ${LINUX_DISK_SIZE}, ${LINUX_IMAGE_FAMILY})
  Windows VM             : ${WINDOWS_VM_NAME} (${WINDOWS_MACHINE_TYPE}, ${WINDOWS_DISK_SIZE}, ${WINDOWS_IMAGE_FAMILY})
  Shared Firewall / Tag  : ${FIREWALL_RULE} (tag: ${NETWORK_TAG}, Web UI :${HUB_WEB_PORT})
  Auto-Recreate Existing : ${AUTO_RECREATE}
================================================================================
EOF
    local customize_choice=""
    read -r -p "Press [Enter] to provision with these settings, or type 'c' to customize: " customize_choice
    if [[ "${customize_choice}" =~ ^[Cc] ]]; then
      local input_val=""

      read -r -p "  Target VM OS (both/linux/windows) [${TARGET_OS}]: " input_val
      TARGET_OS="${input_val:-${TARGET_OS}}"

      read -r -p "  Compute Engine Region [${REGION}]: " input_val
      if [[ -n "${input_val}" && "${input_val}" != "${REGION}" ]]; then
        REGION="${input_val}"
        ZONE=""
      fi

      normalize_region_and_zone
      read -r -p "  Compute Engine Zone [${ZONE}]: " input_val
      ZONE="${input_val:-${ZONE}}"
      normalize_region_and_zone

      if [[ "${TARGET_OS,,}" == "both" || "${TARGET_OS,,}" == "linux" ]]; then
        read -r -p "  Linux VM Name [${LINUX_VM_NAME}]: " input_val
        LINUX_VM_NAME="${input_val:-${LINUX_VM_NAME}}"

        read -r -p "  Linux Machine Type [${LINUX_MACHINE_TYPE}]: " input_val
        LINUX_MACHINE_TYPE="${input_val:-${LINUX_MACHINE_TYPE}}"

        read -r -p "  Linux Boot Disk Size [${LINUX_DISK_SIZE}]: " input_val
        LINUX_DISK_SIZE="${input_val:-${LINUX_DISK_SIZE}}"
      fi

      if [[ "${TARGET_OS,,}" == "both" || "${TARGET_OS,,}" == "windows" ]]; then
        read -r -p "  Windows VM Name [${WINDOWS_VM_NAME}]: " input_val
        WINDOWS_VM_NAME="${input_val:-${WINDOWS_VM_NAME}}"

        read -r -p "  Windows Machine Type [${WINDOWS_MACHINE_TYPE}]: " input_val
        WINDOWS_MACHINE_TYPE="${input_val:-${WINDOWS_MACHINE_TYPE}}"

        read -r -p "  Windows Boot Disk Size [${WINDOWS_DISK_SIZE}]: " input_val
        WINDOWS_DISK_SIZE="${input_val:-${WINDOWS_DISK_SIZE}}"
      fi

      read -r -p "  Auto-Recreate Existing VM(s) (true/false) [${AUTO_RECREATE}]: " input_val
      AUTO_RECREATE="${input_val:-${AUTO_RECREATE}}"
    fi
  fi

  TARGET_OS="${TARGET_OS,,}"
  if [[ "${TARGET_OS}" != "both" && "${TARGET_OS}" != "linux" && "${TARGET_OS}" != "windows" ]]; then
    log_error "Invalid TARGET_OS='${TARGET_OS}'. Must be 'both', 'linux', or 'windows'."
    exit 1
  fi
}


# ==============================================================================
# BLOCK 4: OS-TARGET PROVISIONING DISPATCHER
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Dispatches VM creation to `linux/provision_linux_vm.sh` and/or `windows/provision_windows_vm.sh`.
# Parameters:
#   - None (passes resolved globals cleanly to child scripts).
# Return Value:
#   - Returns 0 when all requested VMs are provisioned.
# Exceptions/Errors:
#   - Exits non-zero if a child provisioner fails.
# ------------------------------------------------------------------------------
dispatch_vm_provisioning() {
  local -a shared_flags=(
    "--project=${PROJECT_ID}"
    "--region=${REGION}"
    "--zone=${ZONE}"
  )
  if [[ "${AUTO_RECREATE,,}" == "true" ]]; then
    shared_flags+=("--recreate")
  fi
  if [[ "${NON_INTERACTIVE}" == "true" ]]; then
    shared_flags+=("--non-interactive")
  fi

  export PROJECT_ID REGION ZONE NETWORK_TAG FIREWALL_RULE HUB_WEB_PORT
  export LINUX_DISK_SIZE LINUX_DISK_TYPE LINUX_IMAGE_FAMILY LINUX_IMAGE_PROJECT
  export WINDOWS_DISK_SIZE WINDOWS_DISK_TYPE WINDOWS_IMAGE_FAMILY WINDOWS_IMAGE_PROJECT WINDOWS_ADMIN_USER

  if [[ "${TARGET_OS}" == "both" || "${TARGET_OS}" == "linux" ]]; then
    log_info "Dispatching Linux VM provisioning (${LINUX_VM_NAME})..."
    bash "${SCRIPT_DIR}/linux/provision_linux_vm.sh" \
      "${shared_flags[@]}" \
      "--name=${LINUX_VM_NAME}" \
      "--machine-type=${LINUX_MACHINE_TYPE}"
  fi

  if [[ "${TARGET_OS}" == "both" || "${TARGET_OS}" == "windows" ]]; then
    log_info "Dispatching Windows VM provisioning (${WINDOWS_VM_NAME})..."
    bash "${SCRIPT_DIR}/windows/provision_windows_vm.sh" \
      "${shared_flags[@]}" \
      "--name=${WINDOWS_VM_NAME}" \
      "--machine-type=${WINDOWS_MACHINE_TYPE}"
  fi
}


# ==============================================================================
# BLOCK 5: MAIN ENTRYPOINT & UNIFIED COMPLETION SUMMARY
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Runs argument parsing, project selection, settings customization, and VM creation.
# Parameters:
#   - "$@" (array): Command-line arguments.
# Return Value:
#   - Returns 0 on success.
# Exceptions/Errors:
#   - Exits non-zero on validation or provisioning failure.
# ------------------------------------------------------------------------------
main() {
  parse_args "$@"
  require_gcloud_auth
  select_gcp_project "${NON_INTERACTIVE}" "${PROJECT_EXPLICIT}"
  review_and_customize_vm_settings
  dispatch_vm_provisioning

  cat <<EOF

================================================================================
  GCP CLIENT VM PROVISIONING COMPLETE
================================================================================
  GCP Project ID   : ${PROJECT_ID}
  Zone / Region    : ${ZONE} (${REGION})
  Provisioned OS   : ${TARGET_OS}

  Unified Teardown Command:
    ./uninstall.sh --project=${PROJECT_ID} --zone=${ZONE} --os=${TARGET_OS}
================================================================================
EOF
}

main "$@"
