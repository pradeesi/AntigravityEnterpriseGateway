#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: Unified Enterprise Gateway & Model Armor Uninstallation Script
# ==============================================================================
# Author: Pradeep Singh
# License: Apache-2.0
#
# Purpose:
#   Clean, dependency-ordered uninstallation script that tears down the Cloud Run
#   Enterprise Gateway service, Google Cloud Model Armor + Cloud SDP (DLP)
#   templates, and optionally the Secret Manager secret and Service Account.
#
# Architecture / Context:
#   Organized into 6 explicit functional blocks mirroring `install.sh`:
#     - BLOCK 1: Unified Settings Loader (`settings.env` + `.env`).
#     - BLOCK 2: Structured Semantic Logging Helpers (`INFO`, `WARN`, `ERROR`).
#     - BLOCK 3: CLI Usage & Flag Parser (`parse_args`).
#     - BLOCK 4: Interactive GCP Project Selector & Teardown Confirmation.
#     - BLOCK 5: Dependency-Ordered Resource Teardown Engine.
#     - BLOCK 6: Main Entrypoint & Completion Summary.
#
# Dependencies / Side Effects:
#   - Requires `gcloud` and `curl` installed and authenticated.
#   - Permanently deletes selected Cloud Run, Model Armor, and SDP resources.
# ==============================================================================

set -euo pipefail

# ==============================================================================
# BLOCK 1: UNIFIED SETTINGS LOADER (`settings.env` + `.env`)
# ==============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_FILE="${SETTINGS_FILE:-${SCRIPT_DIR}/settings.env}"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env}"

CALLER_PROJECT_ID="${PROJECT_ID:-}"
CALLER_REGION="${REGION:-}"
CALLER_SERVICE_NAME="${SERVICE_NAME:-}"
CALLER_SA_NAME="${SA_NAME:-}"
CALLER_SECRET_NAME="${SECRET_NAME:-}"
CALLER_SDP_INSPECT_ID="${SDP_INSPECT_TEMPLATE_ID:-}"
CALLER_SDP_DEID_ID="${SDP_DEID_TEMPLATE_ID:-}"
CALLER_ARMOR_TEMPLATE_ID="${MODEL_ARMOR_TEMPLATE_ID:-}"
CALLER_DELETE_RUN="${DELETE_CLOUD_RUN_SERVICE:-}"
CALLER_DELETE_ARMOR="${DELETE_MODEL_ARMOR_SDP:-}"
CALLER_DELETE_SECRET="${DELETE_SECRET:-}"
CALLER_DELETE_SA="${DELETE_SERVICE_ACCOUNT:-}"

if [[ -f "${SETTINGS_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${SETTINGS_FILE}"
  set +a
fi

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

PROJECT_ID="${CALLER_PROJECT_ID:-${PROJECT_ID:-}}"
REGION="${CALLER_REGION:-${REGION:-europe-west1}}"
SERVICE_NAME="${CALLER_SERVICE_NAME:-${SERVICE_NAME:-antigravity-gateway}}"
SA_NAME="${CALLER_SA_NAME:-${SA_NAME:-agy-gateway-sa}}"
SECRET_NAME="${CALLER_SECRET_NAME:-${SECRET_NAME:-agy-gateway-api-key}}"

SDP_INSPECT_TEMPLATE_ID="${CALLER_SDP_INSPECT_ID:-${SDP_INSPECT_TEMPLATE_ID:-agy-pci-creds-pii-inspect}}"
SDP_DEID_TEMPLATE_ID="${CALLER_SDP_DEID_ID:-${SDP_DEID_TEMPLATE_ID:-agy-pci-creds-pii-deid}}"
MODEL_ARMOR_TEMPLATE_ID="${CALLER_ARMOR_TEMPLATE_ID:-${MODEL_ARMOR_TEMPLATE_ID:-agy-enterprise-armor}}"

DELETE_CLOUD_RUN_SERVICE="${CALLER_DELETE_RUN:-${DELETE_CLOUD_RUN_SERVICE:-true}}"
DELETE_MODEL_ARMOR_SDP="${CALLER_DELETE_ARMOR:-${DELETE_MODEL_ARMOR_SDP:-true}}"
DELETE_SECRET="${CALLER_DELETE_SECRET:-${DELETE_SECRET:-false}}"
DELETE_SERVICE_ACCOUNT="${CALLER_DELETE_SA:-${DELETE_SERVICE_ACCOUNT:-false}}"

AUTO_APPROVE="false"
NON_INTERACTIVE="false"
PROJECT_EXPLICIT="false"


# ==============================================================================
# BLOCK 2: STRUCTURED SEMANTIC LOGGING HELPERS
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Prints a structured INFO log message with an ISO-8601 UTC timestamp.
# Parameters:
#   - $* (string): Log message text.
# Return Value:
#   - Returns 0.
# Exceptions/Errors:
#   - None.
# ------------------------------------------------------------------------------
log_info() {
  printf "[%s] [INFO]  %s\n" "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$*"
}

# ------------------------------------------------------------------------------
# Summary: Prints a structured WARN log message to stderr.
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
# Summary: Prints a structured ERROR log message to stderr.
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
# BLOCK 3: CLI USAGE & FLAG PARSER
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Displays CLI usage help and default teardown flags from `settings.env`.
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

Tears down the Antigravity Enterprise Gateway Cloud Run service and Google Cloud
Model Armor + Cloud SDP (DLP) templates in strict dependency order.

Options:
  --project=PROJECT_ID          GCP Project ID (lists all projects interactively if omitted)
  --region=REGION               Cloud Run & Model Armor region (default: ${REGION})
  --service-name=NAME           Cloud Run service name (default: ${SERVICE_NAME})
  --skip-armor                  Keep Model Armor & Cloud SDP templates
  --delete-secret               Also delete Secret Manager secret (${SECRET_NAME})
  --delete-sa                   Also delete Gateway Service Account (${SA_NAME})
  --non-interactive             Do not prompt for interactive project selection
  --yes, -y                     Skip interactive teardown confirmation prompt
  --help, -h                    Show this help message
EOF
  exit 0
}

# ------------------------------------------------------------------------------
# Summary: Parses command-line arguments and checks required CLI binaries.
# Parameters:
#   - "$@" (array): Command-line arguments passed to `uninstall.sh`.
# Return Value:
#   - Returns 0 on valid arguments.
# Exceptions/Errors:
#   - Exits with code 1 on unknown flags or missing binaries.
# ------------------------------------------------------------------------------
parse_args() {
  for arg in "$@"; do
    case "${arg}" in
      --project=*)
        PROJECT_ID="${arg#*=}"
        PROJECT_EXPLICIT="true"
        ;;
      --region=*)
        REGION="${arg#*=}"
        ;;
      --service-name=*)
        SERVICE_NAME="${arg#*=}"
        ;;
      --skip-armor)
        DELETE_MODEL_ARMOR_SDP="false"
        ;;
      --delete-secret)
        DELETE_SECRET="true"
        ;;
      --delete-sa)
        DELETE_SERVICE_ACCOUNT="true"
        ;;
      --non-interactive)
        NON_INTERACTIVE="true"
        ;;
      --yes|-y)
        AUTO_APPROVE="true"
        ;;
      --help|-h)
        usage
        ;;
      *)
        log_error "Unknown argument: ${arg}"
        usage
        ;;
    esac
  done

  for cmd in gcloud curl; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
      log_error "Required CLI tool '${cmd}' is not installed."
      exit 1
    fi
  done
}


# ==============================================================================
# BLOCK 4: INTERACTIVE GCP PROJECT SELECTOR & TEARDOWN CONFIRMATION
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Lists accessible ACTIVE GCP projects and asks the user to select one if omitted.
# Parameters:
#   - None (populates and validates global PROJECT_ID).
# Return Value:
#   - Returns 0 once PROJECT_ID is verified.
# Exceptions/Errors:
#   - Exits with code 1 if non-interactive mode lacks PROJECT_ID or access fails.
# ------------------------------------------------------------------------------
select_gcp_project() {
  if [[ "${PROJECT_EXPLICIT}" == "true" && -n "${PROJECT_ID}" && "${PROJECT_ID}" != "REPLACE_WITH_PROJECT_ID" ]]; then
    return 0
  fi

  if [[ "${NON_INTERACTIVE}" == "true" ]]; then
    if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "REPLACE_WITH_PROJECT_ID" ]]; then
      log_error "PROJECT_ID is required in --non-interactive mode. Pass --project=<PROJECT_ID>."
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
  echo "  SELECT GOOGLE CLOUD PROJECT TO UNINSTALL FROM"
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
  fi
  echo "================================================================================"

  while true; do
    local prompt_label="Select project number"
    if [[ "${#proj_ids[@]}" -gt 0 ]]; then
      prompt_label+=" [1-${#proj_ids[@]}] or type a Project ID"
    else
      prompt_label="Enter GCP Project ID"
    fi
    if [[ -n "${default_proj}" ]]; then
      prompt_label+=" [${default_proj}]"
    fi

    local selection=""
    read -r -p "${prompt_label}: " selection
    selection="$(echo "${selection}" | xargs)"

    if [[ -z "${selection}" && -n "${default_proj}" ]]; then
      PROJECT_ID="${default_proj}"
      break
    elif [[ "${selection}" =~ ^[0-9]+$ ]] && (( selection >= 1 && selection <= ${#proj_ids[@]} )); then
      PROJECT_ID="${proj_ids[$((selection - 1))]}"
      break
    elif [[ -n "${selection}" ]]; then
      PROJECT_ID="${selection}"
      break
    fi
    log_warn "Please enter a valid number from the list or a Project ID."
  done

  if ! gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
    log_error "Unable to access GCP project '${PROJECT_ID}'."
    exit 1
  fi
}

# ------------------------------------------------------------------------------
# Summary: Shows the teardown plan and prompts the operator for confirmation unless `--yes` is set.
# Parameters:
#   - None.
# Return Value:
#   - Returns 0 if confirmed; exits 0 cleanly if user cancels.
# Exceptions/Errors:
#   - None.
# ------------------------------------------------------------------------------
confirm_uninstall() {
  SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

  if [[ "${AUTO_APPROVE}" == "true" ]]; then
    return 0
  fi

  cat <<EOF

================================================================================
  UNINSTALLATION PLAN — PROJECT: ${PROJECT_ID} (REGION: ${REGION})
================================================================================
  [1] Delete Cloud Run Service (${SERVICE_NAME})           : ${DELETE_CLOUD_RUN_SERVICE}
  [2] Delete Model Armor & SDP Templates                   : ${DELETE_MODEL_ARMOR_SDP}
        - Model Armor : ${MODEL_ARMOR_TEMPLATE_ID}
        - SDP De-id   : ${SDP_DEID_TEMPLATE_ID}
        - SDP Inspect : ${SDP_INSPECT_TEMPLATE_ID}
  [3] Delete Secret Manager Key (${SECRET_NAME})           : ${DELETE_SECRET}
  [4] Delete Service Account (${SA_EMAIL}) : ${DELETE_SERVICE_ACCOUNT}
================================================================================
EOF
  local reply=""
  read -r -p "Are you sure you want to permanently delete the enabled resources above? [y/N]: " reply
  if [[ ! "${reply}" =~ ^[Yy]$ ]]; then
    log_info "Uninstallation cancelled by user."
    exit 0
  fi
}


# ==============================================================================
# BLOCK 5: DEPENDENCY-ORDERED RESOURCE TEARDOWN ENGINE
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Tears down Cloud Run, Model Armor/SDP templates, optional Secret/SA, and local config.
# Parameters:
#   - None.
# Return Value:
#   - Returns 0 when all enabled teardown steps complete.
# Exceptions/Errors:
#   - Logs warnings and continues idempotently when resources are already absent.
# ------------------------------------------------------------------------------
execute_teardown() {
  # 1. Delete Cloud Run Service first so live traffic stops referencing templates/secrets.
  if [[ "${DELETE_CLOUD_RUN_SERVICE,,}" == "true" ]]; then
    log_info "Deleting Cloud Run service '${SERVICE_NAME}' in '${REGION}'..."
    if gcloud run services describe "${SERVICE_NAME}" --project="${PROJECT_ID}" --region="${REGION}" >/dev/null 2>&1; then
      gcloud run services delete "${SERVICE_NAME}" \
        --project="${PROJECT_ID}" \
        --region="${REGION}" \
        --quiet
      log_info "Deleted Cloud Run service '${SERVICE_NAME}'."
    else
      log_warn "Cloud Run service '${SERVICE_NAME}' not found in '${REGION}' (already deleted)."
    fi
  fi

  # 2. Delete Model Armor -> SDP De-identify -> SDP Inspect templates via modular manager.
  if [[ "${DELETE_MODEL_ARMOR_SDP,,}" == "true" ]]; then
    bash "${SCRIPT_DIR}/model-armor-sdp/model_armor_manager.sh" deprovision \
      --project="${PROJECT_ID}" \
      --region="${REGION}" \
      --inspect-template="${SDP_INSPECT_TEMPLATE_ID}" \
      --deid-template="${SDP_DEID_TEMPLATE_ID}" \
      --armor-template="${MODEL_ARMOR_TEMPLATE_ID}" \
      --non-interactive \
      --yes
  fi

  # 3. Optional Secret Manager Secret deletion.
  if [[ "${DELETE_SECRET,,}" == "true" ]]; then
    log_info "Deleting Secret Manager secret '${SECRET_NAME}'..."
    if gcloud secrets describe "${SECRET_NAME}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
      gcloud secrets delete "${SECRET_NAME}" --project="${PROJECT_ID}" --quiet
      log_info "Deleted Secret Manager secret '${SECRET_NAME}'."
    else
      log_warn "Secret '${SECRET_NAME}' not found (already deleted)."
    fi
  fi

  # 4. Optional Service Account deletion (clean up project IAM bindings first to avoid tombstoned principals).
  if [[ "${DELETE_SERVICE_ACCOUNT,,}" == "true" ]]; then
    log_info "Deleting Service Account '${SA_EMAIL}'..."
    if gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
      for role in "roles/aiplatform.user" "roles/modelarmor.user" "roles/dlp.user"; do
        gcloud projects remove-iam-policy-binding "${PROJECT_ID}" \
          --member="serviceAccount:${SA_EMAIL}" \
          --role="${role}" \
          --condition=None \
          --quiet >/dev/null 2>&1 || true
      done
      gcloud iam service-accounts delete "${SA_EMAIL}" --project="${PROJECT_ID}" --quiet
      log_info "Deleted Service Account '${SA_EMAIL}'."
    else
      log_warn "Service Account '${SA_EMAIL}' not found (already deleted)."
    fi
  fi

  # 5. Clean up local generated MDM config if present.
  if [[ -f "${SCRIPT_DIR}/admin_settings.local.json" ]]; then
    rm -f "${SCRIPT_DIR}/admin_settings.local.json"
    log_info "Removed local generated file 'admin_settings.local.json'."
  fi
}


# ==============================================================================
# BLOCK 6: MAIN ENTRYPOINT & COMPLETION SUMMARY
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Runs argument parsing, project selection, confirmation, and teardown.
# Parameters:
#   - "$@" (array): Command-line arguments.
# Return Value:
#   - Returns 0 on completion.
# Exceptions/Errors:
#   - Exits non-zero on invalid flags or inaccessible GCP project.
# ------------------------------------------------------------------------------
main() {
  parse_args "$@"
  select_gcp_project
  confirm_uninstall
  execute_teardown

  cat <<EOF

================================================================================
  ANTIGRAVITY ENTERPRISE GATEWAY UNINSTALLATION COMPLETE
================================================================================
  GCP Project ID : ${PROJECT_ID}
  GCP Region     : ${REGION}
================================================================================
EOF
}

main "$@"
