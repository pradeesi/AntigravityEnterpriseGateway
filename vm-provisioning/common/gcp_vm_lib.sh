#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: Shared Google Compute Engine VM Provisioning & Teardown Library
# ==============================================================================
# Author: Pradeep Singh
# License: Apache-2.0
#
# Purpose:
#   Shared modular Bash library providing unified settings loading, semantic
#   logging, interactive GCP project selection, region/zone normalization, VPC
#   network/subnet/firewall resolution, VM instance creation, and reference-safe
#   shared firewall/subnet teardown for both Linux and Windows client VMs.
#
# Architecture / Context:
#   Sourced by `install.sh`, `uninstall.sh`, `linux/provision_linux_vm.sh`,
#   `linux/deprovision_linux_vm.sh`, `windows/provision_windows_vm.sh`, and
#   `windows/deprovision_windows_vm.sh`. Eliminates ~95% code duplication across
#   operating system scripts while preserving standalone execution of each script.
#
# Dependencies / Side Effects:
#   - Requires authenticated `gcloud` CLI.
#   - Enables `compute.googleapis.com` and manages VPC networks, regional subnets,
#     tag-scoped firewall rules, and Compute Engine VM instances.
# ==============================================================================

# Guard against multiple sourcing within the same shell process.
if [[ "${_AGY_GCP_VM_LIB_LOADED:-false}" == "true" ]]; then
  return 0
fi
readonly _AGY_GCP_VM_LIB_LOADED="true"

# ==============================================================================
# BLOCK 1: STRUCTURED SEMANTIC LOGGING HELPERS (`INFO`, `WARN`, `ERROR`)
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Prints a structured INFO log line with an ISO-8601 UTC timestamp.
# Parameters:
#   - $* (string): Informational message text.
# Return Value:
#   - Returns 0.
# Exceptions/Errors:
#   - None.
# ------------------------------------------------------------------------------
log_info() {
  printf "[%s] [INFO]  %s\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$*"
}

# ------------------------------------------------------------------------------
# Summary: Prints a structured WARN log line with an ISO-8601 UTC timestamp to stderr.
# Parameters:
#   - $* (string): Warning message text.
# Return Value:
#   - Returns 0.
# Exceptions/Errors:
#   - None.
# ------------------------------------------------------------------------------
log_warn() {
  printf "[%s] [WARN]  %s\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$*" >&2
}

# ------------------------------------------------------------------------------
# Summary: Prints a structured ERROR log line with an ISO-8601 UTC timestamp to stderr.
# Parameters:
#   - $* (string): Error message text.
# Return Value:
#   - Returns 0.
# Exceptions/Errors:
#   - None.
# ------------------------------------------------------------------------------
log_error() {
  printf "[%s] [ERROR] %s\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$*" >&2
}


# ==============================================================================
# BLOCK 2: UNIFIED CONFIGURATION LOADER (`settings.env` + `.env` + ENV OVERRIDES)
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Loads `settings.env` and optional `.env` while preserving caller env overrides.
# Parameters:
#   - $1 (string): Root directory path of `vm-provisioning`.
# Return Value:
#   - Returns 0 and populates global VM configuration variables.
# Exceptions/Errors:
#   - None (falls back to built-in safe defaults if `settings.env` is absent).
# ------------------------------------------------------------------------------
load_vm_settings() {
  local root_dir="$1"
  local settings_file="${SETTINGS_FILE:-${root_dir}/settings.env}"
  local env_file="${ENV_FILE:-${root_dir}/.env}"

  # Snapshot any caller-exported shell variables so they take precedence over files.
  local caller_project_id="${PROJECT_ID:-}"
  local caller_target_os="${TARGET_OS:-}"
  local caller_region="${REGION:-}"
  local caller_zone="${ZONE:-}"
  local caller_linux_vm="${LINUX_VM_NAME:-}"
  local caller_linux_type="${LINUX_MACHINE_TYPE:-}"
  local caller_linux_disk="${LINUX_DISK_SIZE:-}"
  local caller_win_vm="${WINDOWS_VM_NAME:-}"
  local caller_win_type="${WINDOWS_MACHINE_TYPE:-}"
  local caller_win_disk="${WINDOWS_DISK_SIZE:-}"
  local caller_net_tag="${NETWORK_TAG:-}"
  local caller_fw_rule="${FIREWALL_RULE:-}"
  local caller_hub_port="${HUB_WEB_PORT:-}"
  local caller_auto_recreate="${AUTO_RECREATE:-}"
  local caller_auto_approve="${AUTO_APPROVE:-}"

  if [[ -f "${settings_file}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${settings_file}"
    set +a
  fi

  if [[ -f "${env_file}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${env_file}"
    set +a
  fi

  PROJECT_ID="${caller_project_id:-${PROJECT_ID:-}}"
  TARGET_OS="${caller_target_os:-${TARGET_OS:-both}}"
  REGION="${caller_region:-${REGION:-europe-west1}}"
  ZONE="${caller_zone:-${ZONE:-europe-west1-b}}"

  LINUX_VM_NAME="${caller_linux_vm:-${LINUX_VM_NAME:-antigravity-linux-vm}}"
  LINUX_MACHINE_TYPE="${caller_linux_type:-${LINUX_MACHINE_TYPE:-e2-standard-4}}"
  LINUX_DISK_SIZE="${caller_linux_disk:-${LINUX_DISK_SIZE:-50GB}}"
  LINUX_DISK_TYPE="${LINUX_DISK_TYPE:-pd-balanced}"
  LINUX_IMAGE_FAMILY="${LINUX_IMAGE_FAMILY:-ubuntu-2204-lts}"
  LINUX_IMAGE_PROJECT="${LINUX_IMAGE_PROJECT:-ubuntu-os-cloud}"

  WINDOWS_VM_NAME="${caller_win_vm:-${WINDOWS_VM_NAME:-antigravity-windows-vm}}"
  WINDOWS_MACHINE_TYPE="${caller_win_type:-${WINDOWS_MACHINE_TYPE:-e2-standard-4}}"
  WINDOWS_DISK_SIZE="${caller_win_disk:-${WINDOWS_DISK_SIZE:-60GB}}"
  WINDOWS_DISK_TYPE="${WINDOWS_DISK_TYPE:-pd-balanced}"
  WINDOWS_IMAGE_FAMILY="${WINDOWS_IMAGE_FAMILY:-windows-2022}"
  WINDOWS_IMAGE_PROJECT="${WINDOWS_IMAGE_PROJECT:-windows-cloud}"
  WINDOWS_ADMIN_USER="${WINDOWS_ADMIN_USER:-agyadmin}"

  NETWORK_TAG="${caller_net_tag:-${NETWORK_TAG:-antigravity-client-vm}}"
  FIREWALL_RULE="${caller_fw_rule:-${FIREWALL_RULE:-antigravity-client-vms-allow-access}}"
  HUB_WEB_PORT="${caller_hub_port:-${HUB_WEB_PORT:-4400}}"

  AUTO_RECREATE="${caller_auto_recreate:-${AUTO_RECREATE:-false}}"
  AUTO_APPROVE="${caller_auto_approve:-${AUTO_APPROVE:-false}}"
}


# ==============================================================================
# BLOCK 3: GCLOUD AUTHENTICATION & INTERACTIVE GCP PROJECT SELECTOR
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Verifies `gcloud` installation and active authentication session.
# Parameters:
#   - None (sets global `ACTIVE_ACCOUNT`).
# Return Value:
#   - Returns 0 if an active `gcloud` account exists.
# Exceptions/Errors:
#   - Exits with code 1 if `gcloud` is missing or unauthenticated.
# ------------------------------------------------------------------------------
require_gcloud_auth() {
  if ! command -v gcloud >/dev/null 2>&1; then
    log_error "Required CLI tool 'gcloud' is not installed."
    exit 1
  fi

  ACTIVE_ACCOUNT="$(gcloud auth list --filter="status:ACTIVE" --format="value(account)" --limit=1 2>/dev/null || true)"
  if [[ -z "${ACTIVE_ACCOUNT}" ]]; then
    log_error "No active gcloud authentication detected. Run 'gcloud auth login' first."
    exit 1
  fi
  log_info "Authenticated GCP Account: ${ACTIVE_ACCOUNT}"
}

# ------------------------------------------------------------------------------
# Summary: Lists accessible ACTIVE GCP projects and prompts the operator to choose one.
# Parameters:
#   - $1 (string, optional): Non-interactive flag ("true" or "false", default "false").
#   - $2 (string, optional): Explicit CLI project flag ("true" or "false", default "false").
# Return Value:
#   - Returns 0 once `PROJECT_ID` is chosen and verified via `gcloud projects describe`.
# Exceptions/Errors:
#   - Exits with code 1 if non-interactive mode lacks `PROJECT_ID` or project access fails.
# ------------------------------------------------------------------------------
select_gcp_project() {
  local non_interactive="${1:-false}"
  local project_explicit="${2:-false}"

  if [[ "${project_explicit}" == "true" && -n "${PROJECT_ID}" && "${PROJECT_ID}" != "REPLACE_WITH_PROJECT_ID" ]]; then
    if ! gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
      log_error "Unable to access GCP project '${PROJECT_ID}'. Check permissions and authentication."
      exit 1
    fi
    log_info "Using CLI-specified GCP Project ID: ${PROJECT_ID}"
    return 0
  fi

  if [[ "${non_interactive}" == "true" ]]; then
    if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "REPLACE_WITH_PROJECT_ID" ]]; then
      log_error "PROJECT_ID is empty in --non-interactive mode. Pass --project=<PROJECT_ID> or set PROJECT_ID in settings.env."
      exit 1
    fi
    if ! gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
      log_error "Unable to access GCP project '${PROJECT_ID}'."
      exit 1
    fi
    return 0
  fi

  local default_proj="${PROJECT_ID}"
  if [[ -z "${default_proj}" || "${default_proj}" == "REPLACE_WITH_PROJECT_ID" ]]; then
    default_proj="$(gcloud config get-value project 2>/dev/null || true)"
  fi

  log_info "Fetching accessible ACTIVE Google Cloud projects..."
  local -a proj_ids=()
  local -a proj_names=()
  while IFS=$'\t' read -r pid pname; do
    [[ -z "${pid}" ]] && continue
    proj_ids+=("${pid}")
    proj_names+=("${pname:-Unnamed}")
  done < <(gcloud projects list --filter="lifecycleState:ACTIVE" --sort-by="projectId" --format="value(projectId,name)" 2>/dev/null || true)

  echo ""
  echo "================================================================================"
  echo "  SELECT TARGET GOOGLE CLOUD PROJECT"
  echo "================================================================================"
  if [[ "${#proj_ids[@]}" -gt 0 ]]; then
    local idx
    for idx in "${!proj_ids[@]}"; do
      local default_tag=""
      if [[ "${proj_ids[$idx]}" == "${default_proj}" ]]; then
        default_tag="  <-- [default]"
      fi
      printf "  [%2d] %-34s (%s)%s\n" "$((idx + 1))" "${proj_ids[$idx]}" "${proj_names[$idx]}" "${default_tag}"
    done
  else
    log_warn "No projects returned by 'gcloud projects list'. You may enter a Project ID directly."
  fi
  echo "================================================================================"

  while true; do
    local prompt_label="Select project number"
    if [[ "${#proj_ids[@]}" -gt 0 ]]; then
      prompt_label+=" [1-${#proj_ids[@]}] or type a Project ID"
    else
      prompt_label="Enter target GCP Project ID"
    fi
    if [[ -n "${default_proj}" ]]; then
      prompt_label+=" [${default_proj}]"
    fi

    local selection=""
    if ! read -r -p "${prompt_label}: " selection; then
      echo ""
      log_error "No project selection received."
      exit 1
    fi
    selection="$(echo "${selection}" | xargs)"

    if [[ -z "${selection}" && -n "${default_proj}" ]]; then
      PROJECT_ID="${default_proj}"
    elif [[ "${selection}" =~ ^[0-9]+$ ]] && (( selection >= 1 && selection <= ${#proj_ids[@]} )); then
      PROJECT_ID="${proj_ids[$((selection - 1))]}"
    elif [[ -n "${selection}" ]]; then
      PROJECT_ID="${selection}"
    else
      log_warn "Please select a number from the list or enter a valid GCP Project ID."
      continue
    fi

    if gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
      break
    fi
    log_warn "Project '${PROJECT_ID}' could not be verified. Check the ID and try again."
  done

  log_info "Selected GCP Project ID: ${PROJECT_ID}"
}


# ==============================================================================
# BLOCK 4: REGION / ZONE NORMALIZATION & SHARED VPC / FIREWALL RESOLUTION
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Synchronizes `REGION` and `ZONE` so they always belong to the same GCP region.
# Parameters:
#   - None (reads/updates global `REGION` and `ZONE`).
# Return Value:
#   - Returns 0.
# Exceptions/Errors:
#   - None.
# ------------------------------------------------------------------------------
normalize_region_and_zone() {
  # europe-west1 and europe-west4 expose zones b/c/d rather than zone a.
  if [[ -n "${REGION}" ]]; then
    if [[ -z "${ZONE}" || "${ZONE}" != "${REGION}"* ]]; then
      if [[ "${REGION}" == "europe-west1" || "${REGION}" == "europe-west4" ]]; then
        ZONE="${REGION}-b"
      else
        ZONE="${REGION}-a"
      fi
    fi
  fi
  REGION="${ZONE%-*}"
}

# ------------------------------------------------------------------------------
# Summary: Enables Compute Engine API, discovers/creates VPC + subnet, and configures firewall rule.
# Parameters:
#   - None (populates globals `DETECTED_NETWORK` and `DETECTED_SUBNET`).
# Return Value:
#   - Returns 0 when network, subnet, and tag-scoped firewall rule are ready.
# Exceptions/Errors:
#   - Exits non-zero if Compute Engine API enablement or VPC/firewall creation fails.
# ------------------------------------------------------------------------------
ensure_gcp_vm_network_and_firewall() {
  normalize_region_and_zone

  log_info "Ensuring Compute Engine API (compute.googleapis.com) is enabled on '${PROJECT_ID}'..."
  gcloud services enable compute.googleapis.com --project="${PROJECT_ID}" --quiet

  log_info "Resolving VPC network and regional subnet in '${PROJECT_ID}' (${REGION})..."
  DETECTED_NETWORK=""
  local available_networks
  available_networks="$(gcloud compute networks list --project="${PROJECT_ID}" --format="value(name)" --limit=20 --quiet 2>/dev/null || true)"

  local net_candidate
  for net_candidate in default default-vpc; do
    if echo "${available_networks}" | grep -Fxq "${net_candidate}"; then
      DETECTED_NETWORK="${net_candidate}"
      break
    fi
  done

  if [[ -z "${DETECTED_NETWORK}" ]]; then
    DETECTED_NETWORK="$(echo "${available_networks}" | head -n 1)"
  fi

  if [[ -z "${DETECTED_NETWORK}" ]]; then
    log_warn "No existing VPC network found. Creating auto-mode network 'antigravity-vpc'..."
    DETECTED_NETWORK="antigravity-vpc"
    gcloud compute networks create "${DETECTED_NETWORK}" \
      --project="${PROJECT_ID}" \
      --subnet-mode=auto \
      --quiet
  fi

  DETECTED_SUBNET="$(gcloud compute networks subnets list \
    --project="${PROJECT_ID}" \
    --network="${DETECTED_NETWORK}" \
    --filter="region:${REGION}" \
    --format="value(name)" \
    --limit=1 \
    --quiet 2>/dev/null || true)"

  if [[ -z "${DETECTED_SUBNET}" ]]; then
    DETECTED_SUBNET="antigravity-subnet-${REGION}"
    log_warn "No subnet found in '${REGION}' for network '${DETECTED_NETWORK}'. Creating '${DETECTED_SUBNET}'..."
    gcloud compute networks subnets create "${DETECTED_SUBNET}" \
      --project="${PROJECT_ID}" \
      --network="${DETECTED_NETWORK}" \
      --region="${REGION}" \
      --range="10.132.0.0/20" \
      --quiet || true
  fi

  log_info "Ensuring tag-scoped VPC firewall rule '${FIREWALL_RULE}' (tcp:22,3389,${HUB_WEB_PORT})..."
  if ! gcloud compute firewall-rules describe "${FIREWALL_RULE}" --project="${PROJECT_ID}" --quiet &>/dev/null; then
    gcloud compute firewall-rules create "${FIREWALL_RULE}" \
      --project="${PROJECT_ID}" \
      --network="${DETECTED_NETWORK}" \
      --direction=INGRESS \
      --priority=1000 \
      --action=ALLOW \
      --rules="tcp:22,tcp:3389,tcp:${HUB_WEB_PORT}" \
      --source-ranges=0.0.0.0/0 \
      --target-tags="${NETWORK_TAG}" \
      --description="Allow SSH (22), RDP (3389), and Antigravity Web UI (${HUB_WEB_PORT}) for Antigravity client VMs" \
      --quiet
    log_info "Created VPC firewall rule '${FIREWALL_RULE}'."
  else
    log_info "VPC firewall rule '${FIREWALL_RULE}' already exists."
  fi
}


# ==============================================================================
# BLOCK 5: SHIELDED GCE INSTANCE CREATION / RECREATION ENGINE
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Creates (or optionally deletes and recreates) a Shielded GCE VM instance.
# Parameters:
#   - $1 (string): VM instance name (`vm_name`).
#   - $2 (string): Compute Engine machine type (`machine_type`).
#   - $3 (string): Boot disk size (`disk_size`, e.g., `50GB`).
#   - $4 (string): Boot disk type (`disk_type`, e.g., `pd-balanced`).
#   - $5 (string): OS image family (`image_family`).
#   - $6 (string): OS image project (`image_project`).
#   - $7 (string): Metadata startup key (`startup-script` or `windows-startup-script-ps1`).
#   - $8 (string): Absolute path to the startup script file (`startup_file`).
#   - $9 (string): Instance description string (`description`).
# Return Value:
#   - Returns 0 and sets globals `LAST_VM_EXTERNAL_IP` and `LAST_VM_INTERNAL_IP`.
# Exceptions/Errors:
#   - Exits non-zero if `startup_file` is missing or `gcloud compute instances create` fails.
# ------------------------------------------------------------------------------
create_or_recreate_gce_vm() {
  local vm_name="$1"
  local machine_type="$2"
  local disk_size="$3"
  local disk_type="$4"
  local image_family="$5"
  local image_project="$6"
  local metadata_key="$7"
  local startup_file="$8"
  local description="$9"

  if [[ ! -f "${startup_file}" ]]; then
    log_error "Startup script file not found: ${startup_file}"
    exit 1
  fi

  if gcloud compute instances describe "${vm_name}" --zone="${ZONE}" --project="${PROJECT_ID}" --quiet &>/dev/null; then
    log_warn "VM instance '${vm_name}' already exists in zone '${ZONE}'."
    local recreate_choice="n"
    if [[ "${AUTO_RECREATE,,}" == "true" ]]; then
      recreate_choice="y"
    elif [[ "${NON_INTERACTIVE:-false}" != "true" && -t 0 ]]; then
      read -r -p "  Delete and recreate existing VM '${vm_name}'? [y/N]: " recreate_choice
    fi

    if [[ "${recreate_choice,,}" == "y" || "${recreate_choice,,}" == "yes" ]]; then
      log_info "Deleting existing VM '${vm_name}' in '${ZONE}'..."
      gcloud compute instances delete "${vm_name}" --zone="${ZONE}" --project="${PROJECT_ID}" --quiet
    else
      log_info "Keeping existing VM '${vm_name}' without recreation."
    fi
  fi

  if ! gcloud compute instances describe "${vm_name}" --zone="${ZONE}" --project="${PROJECT_ID}" --quiet &>/dev/null; then
    local -a subnet_arg=()
    if [[ -n "${DETECTED_SUBNET:-}" ]]; then
      subnet_arg=(--subnet="${DETECTED_SUBNET}")
    fi

    log_info "Creating Shielded Compute Engine VM '${vm_name}' (${machine_type}, ${image_family})..."
    gcloud compute instances create "${vm_name}" \
      --project="${PROJECT_ID}" \
      --zone="${ZONE}" \
      --machine-type="${machine_type}" \
      --image-family="${image_family}" \
      --image-project="${image_project}" \
      --boot-disk-size="${disk_size}" \
      --boot-disk-type="${disk_type}" \
      --shielded-secure-boot \
      --shielded-vtpm \
      --shielded-integrity-monitoring \
      --network="${DETECTED_NETWORK}" \
      "${subnet_arg[@]}" \
      --scopes="https://www.googleapis.com/auth/cloud-platform" \
      --tags="${NETWORK_TAG}" \
      --metadata-from-file="${metadata_key}=${startup_file}" \
      --description="${description}" \
      --quiet
    log_info "Created VM '${vm_name}' in '${ZONE}'."
  fi

  LAST_VM_EXTERNAL_IP="$(gcloud compute instances describe "${vm_name}" \
    --zone="${ZONE}" \
    --project="${PROJECT_ID}" \
    --format="value(networkInterfaces[0].accessConfigs[0].natIP)" \
    --quiet 2>/dev/null || echo "N/A")"

  LAST_VM_INTERNAL_IP="$(gcloud compute instances describe "${vm_name}" \
    --zone="${ZONE}" \
    --project="${PROJECT_ID}" \
    --format="value(networkInterfaces[0].networkIP)" \
    --quiet 2>/dev/null || echo "N/A")"
}


# ==============================================================================
# BLOCK 6: IDEMPOTENT VM DELETION & REFERENCE-COUNTED NETWORK CLEANUP
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Auto-detects the zone of an existing VM by name if present in `PROJECT_ID`.
# Parameters:
#   - $1 (string): VM instance name (`vm_name`).
#   - $2 (string): Fallback zone if the VM does not exist (`fallback_zone`).
# Return Value:
#   - Echoes the resolved zone string to stdout.
# Exceptions/Errors:
#   - None.
# ------------------------------------------------------------------------------
resolve_vm_zone() {
  local vm_name="$1"
  local fallback_zone="$2"
  local detected_zone
  detected_zone="$(gcloud compute instances list \
    --project="${PROJECT_ID}" \
    --filter="name=${vm_name}" \
    --format="value(zone)" \
    --limit=1 \
    --quiet 2>/dev/null || true)"

  if [[ -n "${detected_zone}" ]]; then
    echo "${detected_zone}"
  else
    echo "${fallback_zone}"
  fi
}

# ------------------------------------------------------------------------------
# Summary: Deletes a GCE VM instance idempotently if it exists in the specified zone.
# Parameters:
#   - $1 (string): VM instance name (`vm_name`).
#   - $2 (string): Compute Engine zone (`target_zone`).
# Return Value:
#   - Returns 0.
# Exceptions/Errors:
#   - Logs an informational message if the VM is already absent.
# ------------------------------------------------------------------------------
delete_gce_vm_instance() {
  local vm_name="$1"
  local target_zone="$2"

  log_info "Checking Compute Engine VM '${vm_name}' in zone '${target_zone}'..."
  if gcloud compute instances describe "${vm_name}" --zone="${target_zone}" --project="${PROJECT_ID}" --quiet &>/dev/null; then
    log_info "Deleting VM '${vm_name}' in zone '${target_zone}'..."
    gcloud compute instances delete "${vm_name}" \
      --zone="${target_zone}" \
      --project="${PROJECT_ID}" \
      --quiet
    log_info "Deleted VM '${vm_name}'."
  else
    log_info "VM '${vm_name}' not found in zone '${target_zone}' (already deleted)."
  fi
}

# ------------------------------------------------------------------------------
# Summary: Deletes the shared firewall rule and auto-created subnet ONLY if no tagged VMs remain.
# Parameters:
#   - $1 (string): Region (`target_region`) used to check `antigravity-subnet-<region>`.
# Return Value:
#   - Returns 0.
# Exceptions/Errors:
#   - Preserves shared firewall/subnet safely when another tagged client VM is still running.
# ------------------------------------------------------------------------------
cleanup_shared_vm_network_if_unused() {
  local target_region="$1"

  # Both Linux and Windows client VMs share `NETWORK_TAG` (`antigravity-client-vm`).
  # Never delete the shared firewall rule or subnet while a sibling VM still exists.
  log_info "Checking for remaining VMs tagged '${NETWORK_TAG}' before removing '${FIREWALL_RULE}'..."
  local remaining_vms
  remaining_vms="$(gcloud compute instances list \
    --project="${PROJECT_ID}" \
    --filter="tags.items=${NETWORK_TAG}" \
    --format="value(name)" \
    --limit=5 \
    --quiet 2>/dev/null || true)"

  if [[ -n "${remaining_vms}" ]]; then
    log_info "Preserving shared firewall rule '${FIREWALL_RULE}' and subnet; active tagged VM(s) remain: $(echo "${remaining_vms}" | tr '\n' ' ')"
    return 0
  fi

  if gcloud compute firewall-rules describe "${FIREWALL_RULE}" --project="${PROJECT_ID}" --quiet &>/dev/null; then
    log_info "Deleting unused VPC firewall rule '${FIREWALL_RULE}'..."
    gcloud compute firewall-rules delete "${FIREWALL_RULE}" \
      --project="${PROJECT_ID}" \
      --quiet
    log_info "Deleted VPC firewall rule '${FIREWALL_RULE}'."
  else
    log_info "VPC firewall rule '${FIREWALL_RULE}' not found (already deleted)."
  fi

  local auto_subnet="antigravity-subnet-${target_region}"
  if gcloud compute networks subnets describe "${auto_subnet}" --region="${target_region}" --project="${PROJECT_ID}" --quiet &>/dev/null; then
    log_info "Deleting auto-created regional subnet '${auto_subnet}' (${target_region})..."
    gcloud compute networks subnets delete "${auto_subnet}" \
      --region="${target_region}" \
      --project="${PROJECT_ID}" \
      --quiet || true
    log_info "Deleted regional subnet '${auto_subnet}'."
  fi
}
