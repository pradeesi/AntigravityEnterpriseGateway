#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: Unified Enterprise Gateway & Model Armor Installation Script
# ==============================================================================
# Author: Pradeep Singh
# License: Apache-2.0
#
# Purpose:
#   Interactive and automated end-to-end installer that lists accessible Google
#   Cloud projects for selection, allows reviewing/overriding defaults from
#   `settings.env`, provisions Cloud SDP (DLP) + Model Armor security templates,
#   and deploys either the Python or Go Enterprise Gateway to GCP Cloud Run.
#
# Architecture / Context:
#   Organized into 8 explicit functional blocks:
#     - BLOCK 1: Unified Settings Loader (`settings.env` + `.env`).
#     - BLOCK 2: Structured Semantic Logging Helpers (`INFO`, `WARN`, `ERROR`).
#     - BLOCK 3: CLI Usage & Flag Parser (`parse_args`).
#     - BLOCK 4: Interactive GCP Project Selector & Settings Customizer.
#     - BLOCK 5: GCP API Enablement, Service Account & Secret Manager Setup.
#     - BLOCK 6: Google Cloud Model Armor & Cloud SDP Layer Provisioning.
#     - BLOCK 7: Cloud Run Gateway Deployment & Live Telemetry Smoke Probe.
#     - BLOCK 8: Client Config Generation (`admin_settings.local.json`) & Entrypoint.
#
# Dependencies / Side Effects:
#   - Requires `gcloud`, `curl`, `jq`, and `openssl` installed and authenticated.
#   - Provisions IAM bindings, Secret Manager secrets, optional SDP/Model Armor
#     templates, and a Cloud Run service in the selected GCP project.
# ==============================================================================

set -euo pipefail

# ==============================================================================
# BLOCK 1: UNIFIED SETTINGS LOADER (`settings.env` + `.env`)
# ==============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETTINGS_FILE="${SETTINGS_FILE:-${SCRIPT_DIR}/settings.env}"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/.env}"

# Capture any pre-exported shell overrides before sourcing settings files.
CALLER_PROJECT_ID="${PROJECT_ID:-}"
CALLER_REGION="${REGION:-}"
CALLER_RUNTIME="${GATEWAY_RUNTIME:-}"
CALLER_API_KEY="${GATEWAY_API_KEY:-}"
CALLER_PORT="${PORT:-}"
CALLER_LOG_LEVEL="${LOG_LEVEL:-}"
CALLER_LOG_TELEMETRY_PAYLOADS="${LOG_TELEMETRY_PAYLOADS:-}"
CALLER_SERVICE_NAME="${SERVICE_NAME:-}"
CALLER_SA_NAME="${SA_NAME:-}"
CALLER_SECRET_NAME="${SECRET_NAME:-}"
CALLER_CLOUD_RUN_INGRESS="${CLOUD_RUN_INGRESS:-}"
CALLER_CLOUD_RUN_CPU="${CLOUD_RUN_CPU:-}"
CALLER_CLOUD_RUN_MEMORY="${CLOUD_RUN_MEMORY:-}"
CALLER_CLOUD_RUN_MIN_INSTANCES="${CLOUD_RUN_MIN_INSTANCES:-}"
CALLER_CLOUD_RUN_MAX_INSTANCES="${CLOUD_RUN_MAX_INSTANCES:-}"
CALLER_CLOUD_RUN_TIMEOUT="${CLOUD_RUN_TIMEOUT:-}"
CALLER_ENABLE_ARMOR="${ENABLE_MODEL_ARMOR:-}"
CALLER_ARMOR_MODE="${MODEL_ARMOR_MODE:-}"
CALLER_ARMOR_FAIL_CLOSED="${MODEL_ARMOR_FAIL_CLOSED:-}"
CALLER_SDP_INSPECT_ID="${SDP_INSPECT_TEMPLATE_ID:-}"
CALLER_SDP_DEID_ID="${SDP_DEID_TEMPLATE_ID:-}"
CALLER_ARMOR_TEMPLATE_ID="${MODEL_ARMOR_TEMPLATE_ID:-}"
CALLER_RUN_TESTS="${RUN_VERIFICATION_TESTS:-}"
CALLER_COST_CENTER_MAP="${COST_CENTER_PROJECT_MAP:-}"
CALLER_MODEL_REGION_MAP="${MODEL_REGION_MAP:-}"
CALLER_FAILOVER_REGIONS="${FAILOVER_REGIONS:-}"
CALLER_FALLBACK_MODEL="${DEFAULT_FLASH_FALLBACK_MODEL:-}"
CALLER_OPENAI_URL="${OPENAI_UPSTREAM_BASE_URL:-}"

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

# Restore caller overrides where non-empty, falling back to `settings.env` defaults.
PROJECT_ID="${CALLER_PROJECT_ID:-${PROJECT_ID:-}}"
REGION="${CALLER_REGION:-${REGION:-europe-west1}}"
GATEWAY_RUNTIME="${CALLER_RUNTIME:-${GATEWAY_RUNTIME:-python}}"
GATEWAY_API_KEY="${CALLER_API_KEY:-${GATEWAY_API_KEY:-REPLACE_WITH_GATEWAY_API_KEY}}"
PORT="${CALLER_PORT:-${PORT:-8080}}"
LOG_LEVEL="${CALLER_LOG_LEVEL:-${LOG_LEVEL:-INFO}}"
LOG_TELEMETRY_PAYLOADS="${CALLER_LOG_TELEMETRY_PAYLOADS:-${LOG_TELEMETRY_PAYLOADS:-false}}"

SERVICE_NAME="${CALLER_SERVICE_NAME:-${SERVICE_NAME:-antigravity-gateway}}"
SA_NAME="${CALLER_SA_NAME:-${SA_NAME:-agy-gateway-sa}}"
SECRET_NAME="${CALLER_SECRET_NAME:-${SECRET_NAME:-agy-gateway-api-key}}"
CLOUD_RUN_INGRESS="${CALLER_CLOUD_RUN_INGRESS:-${CLOUD_RUN_INGRESS:-all}}"
CLOUD_RUN_CPU="${CALLER_CLOUD_RUN_CPU:-${CLOUD_RUN_CPU:-1}}"
CLOUD_RUN_MEMORY="${CALLER_CLOUD_RUN_MEMORY:-${CLOUD_RUN_MEMORY:-512Mi}}"
CLOUD_RUN_MIN_INSTANCES="${CALLER_CLOUD_RUN_MIN_INSTANCES:-${CLOUD_RUN_MIN_INSTANCES:-1}}"
CLOUD_RUN_MAX_INSTANCES="${CALLER_CLOUD_RUN_MAX_INSTANCES:-${CLOUD_RUN_MAX_INSTANCES:-10}}"
CLOUD_RUN_TIMEOUT="${CALLER_CLOUD_RUN_TIMEOUT:-${CLOUD_RUN_TIMEOUT:-3600}}"

ENABLE_MODEL_ARMOR="${CALLER_ENABLE_ARMOR:-${ENABLE_MODEL_ARMOR:-true}}"
MODEL_ARMOR_MODE="${CALLER_ARMOR_MODE:-${MODEL_ARMOR_MODE:-inline}}"
MODEL_ARMOR_FAIL_CLOSED="${CALLER_ARMOR_FAIL_CLOSED:-${MODEL_ARMOR_FAIL_CLOSED:-true}}"
SDP_INSPECT_TEMPLATE_ID="${CALLER_SDP_INSPECT_ID:-${SDP_INSPECT_TEMPLATE_ID:-agy-pci-creds-pii-inspect}}"
SDP_DEID_TEMPLATE_ID="${CALLER_SDP_DEID_ID:-${SDP_DEID_TEMPLATE_ID:-agy-pci-creds-pii-deid}}"
MODEL_ARMOR_TEMPLATE_ID="${CALLER_ARMOR_TEMPLATE_ID:-${MODEL_ARMOR_TEMPLATE_ID:-agy-enterprise-armor}}"
RUN_VERIFICATION_TESTS="${CALLER_RUN_TESTS:-${RUN_VERIFICATION_TESTS:-true}}"

COST_CENTER_PROJECT_MAP="${CALLER_COST_CENTER_MAP:-${COST_CENTER_PROJECT_MAP:-}}"
MODEL_REGION_MAP="${CALLER_MODEL_REGION_MAP:-${MODEL_REGION_MAP:-}}"
FAILOVER_REGIONS="${CALLER_FAILOVER_REGIONS:-${FAILOVER_REGIONS:-}}"
DEFAULT_FLASH_FALLBACK_MODEL="${CALLER_FALLBACK_MODEL:-${DEFAULT_FLASH_FALLBACK_MODEL:-gemini-3.8-flash}}"
OPENAI_UPSTREAM_BASE_URL="${CALLER_OPENAI_URL:-${OPENAI_UPSTREAM_BASE_URL:-}}"

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
# Summary: Displays CLI usage help and default values loaded from `settings.env`.
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

Deploys the Antigravity Enterprise Gateway (Python or Go) and optional Google
Cloud Model Armor + Cloud SDP (DLP) security templates to GCP Cloud Run using
defaults from 'settings.env'.

Options:
  --project=PROJECT_ID          GCP Project ID (lists all projects interactively if omitted)
  --region=REGION               Cloud Run & Model Armor region (default: ${REGION})
  --runtime=python|go           Gateway implementation to deploy (default: ${GATEWAY_RUNTIME})
  --service-name=NAME           Cloud Run service name (default: ${SERVICE_NAME})
  --ingress=MODE                Cloud Run ingress: all | internal | internal-and-cloud-load-balancing (default: ${CLOUD_RUN_INGRESS})
  --enable-armor=true|false     Provision & enable Model Armor + Cloud SDP (default: ${ENABLE_MODEL_ARMOR})
  --skip-armor                  Shortcut for --enable-armor=false
  --armor-mode=inline|native    Model Armor enforcement mode (default: ${MODEL_ARMOR_MODE})
  --skip-tests                  Skip the 9 live Model Armor verification tests
  --non-interactive             Accept settings.env / CLI values without interactive prompts
  --help, -h                    Show this help message
EOF
  exit 0
}

# ------------------------------------------------------------------------------
# Summary: Parses command-line flags and verifies required workstation binaries.
# Parameters:
#   - "$@" (array): Command-line arguments passed to `install.sh`.
# Return Value:
#   - Returns 0 on valid arguments.
# Exceptions/Errors:
#   - Exits with code 1 if an invalid flag or missing prerequisite tool is detected.
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
      --runtime=*)
        GATEWAY_RUNTIME="${arg#*=}"
        ;;
      --service-name=*)
        SERVICE_NAME="${arg#*=}"
        ;;
      --ingress=*)
        CLOUD_RUN_INGRESS="${arg#*=}"
        ;;
      --enable-armor=*)
        ENABLE_MODEL_ARMOR="${arg#*=}"
        ;;
      --skip-armor)
        ENABLE_MODEL_ARMOR="false"
        ;;
      --armor-mode=*)
        MODEL_ARMOR_MODE="${arg#*=}"
        ;;
      --skip-tests)
        RUN_VERIFICATION_TESTS="false"
        ;;
      --non-interactive)
        NON_INTERACTIVE="true"
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

  for cmd in gcloud curl jq openssl; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
      log_error "Required CLI tool '${cmd}' is not installed."
      exit 1
    fi
  done
}


# ==============================================================================
# BLOCK 4: INTERACTIVE GCP PROJECT SELECTOR & SETTINGS CUSTOMIZER
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Lists all accessible ACTIVE GCP projects and asks the user to choose one.
# Parameters:
#   - None (populates and validates global PROJECT_ID).
# Return Value:
#   - Returns 0 once PROJECT_ID is chosen and verified via `gcloud projects describe`.
# Exceptions/Errors:
#   - Exits with code 1 if non-interactive mode lacks PROJECT_ID or project access fails.
# ------------------------------------------------------------------------------
select_gcp_project() {
  if [[ "${PROJECT_EXPLICIT}" == "true" && -n "${PROJECT_ID}" && "${PROJECT_ID}" != "REPLACE_WITH_PROJECT_ID" ]]; then
    if ! gcloud projects describe "${PROJECT_ID}" >/dev/null 2>&1; then
      log_error "Unable to access GCP project '${PROJECT_ID}'. Check permissions and authentication."
      exit 1
    fi
    log_info "Using CLI-specified GCP Project ID: ${PROJECT_ID}"
    return 0
  fi

  if [[ "${NON_INTERACTIVE}" == "true" ]]; then
    if [[ -z "${PROJECT_ID}" || "${PROJECT_ID}" == "REPLACE_WITH_PROJECT_ID" ]]; then
      log_error "PROJECT_ID is empty in --non-interactive mode. Pass --project=<PROJECT_ID> or set PROJECT_ID in settings.env."
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
  echo "  STEP 1: SELECT TARGET GOOGLE CLOUD PROJECT"
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
    read -r -p "${prompt_label}: " selection
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
    log_warn "Project '${PROJECT_ID}' could not be verified. Please check the ID and try again."
  done

  log_info "Selected GCP Project ID: ${PROJECT_ID}"
}

# ------------------------------------------------------------------------------
# Summary: Displays effective `settings.env` values and lets the user override any setting.
# Parameters:
#   - None (mutates global deployment configuration variables if customized).
# Return Value:
#   - Returns 0 after validating `GATEWAY_RUNTIME` and `MODEL_ARMOR_MODE`.
# Exceptions/Errors:
#   - Exits with code 1 if `GATEWAY_RUNTIME` is not `python`/`go` or source dir is missing.
# ------------------------------------------------------------------------------
review_and_customize_settings() {
  if [[ "${NON_INTERACTIVE}" != "true" ]]; then
    cat <<EOF

================================================================================
  STEP 2: REVIEW UNIFIED DEPLOYMENT SETTINGS (Loaded from settings.env)
================================================================================
  GCP Project ID           : ${PROJECT_ID}
  Gateway Runtime          : ${GATEWAY_RUNTIME}  (options: python | go)
  GCP Region               : ${REGION}
  Cloud Run Service Name   : ${SERVICE_NAME}
  Cloud Run Ingress        : ${CLOUD_RUN_INGRESS}  (options: all | internal | internal-and-cloud-load-balancing)
  Service Account          : ${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com
  Secret Manager Key       : ${SECRET_NAME}
  Cloud Run Sizing         : ${CLOUD_RUN_CPU} vCPU, ${CLOUD_RUN_MEMORY}, min=${CLOUD_RUN_MIN_INSTANCES}, max=${CLOUD_RUN_MAX_INSTANCES}, timeout=${CLOUD_RUN_TIMEOUT}s
  Enable Model Armor + SDP : ${ENABLE_MODEL_ARMOR}
  Model Armor Mode         : ${MODEL_ARMOR_MODE}  (options: inline | native | disabled)
  Model Armor Template ID  : ${MODEL_ARMOR_TEMPLATE_ID}
  SDP Inspect / De-id IDs  : ${SDP_INSPECT_TEMPLATE_ID} / ${SDP_DEID_TEMPLATE_ID}
  Run Verification Tests   : ${RUN_VERIFICATION_TESTS}
================================================================================
EOF
    local customize_choice=""
    read -r -p "Press [Enter] to deploy with these settings, or type 'c' to customize: " customize_choice
    if [[ "${customize_choice}" =~ ^[Cc] ]]; then
      local input_val=""

      read -r -p "  Gateway Runtime (python/go) [${GATEWAY_RUNTIME}]: " input_val
      GATEWAY_RUNTIME="${input_val:-${GATEWAY_RUNTIME}}"

      read -r -p "  GCP Region [${REGION}]: " input_val
      REGION="${input_val:-${REGION}}"

      read -r -p "  Cloud Run Service Name [${SERVICE_NAME}]: " input_val
      SERVICE_NAME="${input_val:-${SERVICE_NAME}}"

      read -r -p "  Cloud Run Ingress (all/internal/internal-and-cloud-load-balancing) [${CLOUD_RUN_INGRESS}]: " input_val
      CLOUD_RUN_INGRESS="${input_val:-${CLOUD_RUN_INGRESS}}"

      read -r -p "  Service Account Name [${SA_NAME}]: " input_val
      SA_NAME="${input_val:-${SA_NAME}}"

      read -r -p "  Secret Manager Secret Name [${SECRET_NAME}]: " input_val
      SECRET_NAME="${input_val:-${SECRET_NAME}}"

      read -r -p "  Cloud Run Min Instances [${CLOUD_RUN_MIN_INSTANCES}]: " input_val
      CLOUD_RUN_MIN_INSTANCES="${input_val:-${CLOUD_RUN_MIN_INSTANCES}}"

      read -r -p "  Cloud Run Max Instances [${CLOUD_RUN_MAX_INSTANCES}]: " input_val
      CLOUD_RUN_MAX_INSTANCES="${input_val:-${CLOUD_RUN_MAX_INSTANCES}}"

      read -r -p "  Enable Model Armor + Cloud SDP (true/false) [${ENABLE_MODEL_ARMOR}]: " input_val
      ENABLE_MODEL_ARMOR="${input_val:-${ENABLE_MODEL_ARMOR}}"

      if [[ "${ENABLE_MODEL_ARMOR,,}" == "true" ]]; then
        read -r -p "  Model Armor Mode (inline/native) [${MODEL_ARMOR_MODE}]: " input_val
        MODEL_ARMOR_MODE="${input_val:-${MODEL_ARMOR_MODE}}"

        read -r -p "  Model Armor Template ID [${MODEL_ARMOR_TEMPLATE_ID}]: " input_val
        MODEL_ARMOR_TEMPLATE_ID="${input_val:-${MODEL_ARMOR_TEMPLATE_ID}}"

        read -r -p "  Run 5 Live Verification Tests (true/false) [${RUN_VERIFICATION_TESTS}]: " input_val
        RUN_VERIFICATION_TESTS="${input_val:-${RUN_VERIFICATION_TESTS}}"
      fi
    fi
  fi

  GATEWAY_RUNTIME="${GATEWAY_RUNTIME,,}"
  ENABLE_MODEL_ARMOR="${ENABLE_MODEL_ARMOR,,}"
  MODEL_ARMOR_MODE="${MODEL_ARMOR_MODE,,}"
  CLOUD_RUN_INGRESS="${CLOUD_RUN_INGRESS,,}"

  if [[ "${GATEWAY_RUNTIME}" != "python" && "${GATEWAY_RUNTIME}" != "go" ]]; then
    log_error "Invalid GATEWAY_RUNTIME='${GATEWAY_RUNTIME}'. Must be 'python' or 'go'."
    exit 1
  fi

  if [[ ! -d "${SCRIPT_DIR}/${GATEWAY_RUNTIME}" ]]; then
    log_error "Gateway runtime source directory '${SCRIPT_DIR}/${GATEWAY_RUNTIME}' does not exist."
    exit 1
  fi

  if [[ "${ENABLE_MODEL_ARMOR}" == "true" && "${MODEL_ARMOR_MODE}" != "inline" && "${MODEL_ARMOR_MODE}" != "native" ]]; then
    log_error "Invalid MODEL_ARMOR_MODE='${MODEL_ARMOR_MODE}'. Expected 'inline' or 'native' when ENABLE_MODEL_ARMOR=true."
    exit 1
  fi

  SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
}


# ==============================================================================
# BLOCK 5: GCP API ENABLEMENT, SERVICE ACCOUNT & SECRET MANAGER SETUP
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Enables required GCP services, ensures the Gateway SA + IAM roles, and manages the API key secret.
# Parameters:
#   - None (updates global GATEWAY_API_KEY from Secret Manager).
# Return Value:
#   - Returns 0 on success.
# Exceptions/Errors:
#   - Exits non-zero if API enablement, IAM binding, or Secret Manager access fails.
# ------------------------------------------------------------------------------
provision_iam_and_secret() {
  log_info "Enabling Cloud Run, Cloud Build, Artifact Registry, Secret Manager, and Vertex AI APIs..."
  local -a apis=(
    "aiplatform.googleapis.com"
    "secretmanager.googleapis.com"
    "run.googleapis.com"
    "cloudbuild.googleapis.com"
    "artifactregistry.googleapis.com"
  )
  if [[ "${ENABLE_MODEL_ARMOR}" == "true" ]]; then
    apis+=("modelarmor.googleapis.com" "dlp.googleapis.com")
  fi
  gcloud services enable "${apis[@]}" --project="${PROJECT_ID}"

  if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" &>/dev/null; then
    log_info "Creating Gateway Service Account '${SA_EMAIL}'..."
    gcloud iam service-accounts create "${SA_NAME}" \
      --project="${PROJECT_ID}" \
      --display-name="Antigravity Enterprise Gateway"
  fi

  log_info "Binding IAM roles to '${SA_EMAIL}'..."
  local -a sa_roles=("roles/aiplatform.user")
  if [[ "${ENABLE_MODEL_ARMOR}" == "true" ]]; then
    sa_roles+=("roles/modelarmor.user" "roles/dlp.user")
  fi
  for role in "${sa_roles[@]}"; do
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
      --member="serviceAccount:${SA_EMAIL}" \
      --role="${role}" \
      --condition=None \
      --quiet >/dev/null || true
  done

  if ! gcloud secrets describe "${SECRET_NAME}" --project="${PROJECT_ID}" &>/dev/null; then
    log_info "Creating Secret Manager secret '${SECRET_NAME}'..."
    if [[ -n "${GATEWAY_API_KEY}" && "${GATEWAY_API_KEY}" != "REPLACE_WITH_GATEWAY_API_KEY" ]]; then
      printf "%s" "${GATEWAY_API_KEY}" | gcloud secrets create "${SECRET_NAME}" \
        --project="${PROJECT_ID}" \
        --data-file=-
    else
      openssl rand -base64 32 | tr -d '\n' | gcloud secrets create "${SECRET_NAME}" \
        --project="${PROJECT_ID}" \
        --data-file=-
    fi
  else
    log_info "Reusing existing Secret Manager secret '${SECRET_NAME}'."
  fi

  gcloud secrets add-iam-policy-binding "${SECRET_NAME}" \
    --project="${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null

  GATEWAY_API_KEY="$(gcloud secrets versions access latest --secret="${SECRET_NAME}" --project="${PROJECT_ID}")"
}


# ==============================================================================
# BLOCK 6: GOOGLE CLOUD MODEL ARMOR & CLOUD SDP LAYER PROVISIONING
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Delegates SDP + Model Armor template provisioning and verification to `model_armor_manager.sh`.
# Parameters:
#   - None (sets EFFECTIVE_ARMOR_MODE and EFFECTIVE_ARMOR_TEMPLATE for Cloud Run).
# Return Value:
#   - Returns 0 on success.
# Exceptions/Errors:
#   - Exits non-zero if `model_armor_manager.sh` fails provisioning or verification tests.
# ------------------------------------------------------------------------------
provision_model_armor_layer() {
  if [[ "${ENABLE_MODEL_ARMOR}" != "true" ]]; then
    log_info "Model Armor provisioning disabled (ENABLE_MODEL_ARMOR=false)."
    EFFECTIVE_ARMOR_MODE="disabled"
    EFFECTIVE_ARMOR_TEMPLATE=""
    return 0
  fi

  EFFECTIVE_ARMOR_MODE="${MODEL_ARMOR_MODE}"
  EFFECTIVE_ARMOR_TEMPLATE="${MODEL_ARMOR_TEMPLATE_ID}"

  local -a armor_args=(
    "provision"
    "--project=${PROJECT_ID}"
    "--region=${REGION}"
    "--sa-name=${SA_NAME}"
    "--inspect-template=${SDP_INSPECT_TEMPLATE_ID}"
    "--deid-template=${SDP_DEID_TEMPLATE_ID}"
    "--armor-template=${MODEL_ARMOR_TEMPLATE_ID}"
    "--non-interactive"
  )
  if [[ "${RUN_VERIFICATION_TESTS,,}" != "true" ]]; then
    armor_args+=("--skip-tests")
  fi

  log_info "Provisioning Cloud SDP (DLP) & Google Cloud Model Armor templates..."
  bash "${SCRIPT_DIR}/model-armor-sdp/model_armor_manager.sh" "${armor_args[@]}"
}


# ==============================================================================
# BLOCK 7: CLOUD RUN GATEWAY DEPLOYMENT & LIVE TELEMETRY SMOKE PROBE
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Deploys the selected Gateway runtime (`./python` or `./go`) to Cloud Run and verifies connectivity.
# Parameters:
#   - None (sets global GATEWAY_URL).
# Return Value:
#   - Returns 0 when Cloud Run service is live and responds 200 OK to telemetry smoke test.
# Exceptions/Errors:
#   - Exits with code 1 if `gcloud run deploy` or post-deploy smoke test fails.
# ------------------------------------------------------------------------------
deploy_cloud_run_gateway() {
  local source_dir="${SCRIPT_DIR}/${GATEWAY_RUNTIME}"
  log_info "Deploying '${GATEWAY_RUNTIME}' Enterprise Gateway ('${SERVICE_NAME}') to Cloud Run in '${REGION}' (ingress=${CLOUD_RUN_INGRESS})..."

  # `--no-invoker-iam-check` ensures Cloud Run / org Domain Restricted Sharing never intercepts
  # the `Authorization: Bearer <GATEWAY_API_KEY>` header sent by Antigravity clients (and avoids
  # `allUsers` IAM binding errors under `constraints/iam.allowedPolicyMemberDomains`).
  # For private VPC-only access, combine `--no-invoker-iam-check` with `--ingress=internal`.
  gcloud run deploy "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --source="${source_dir}" \
    --no-invoker-iam-check \
    --ingress="${CLOUD_RUN_INGRESS}" \
    --service-account="${SA_EMAIL}" \
    --port="${PORT}" \
    --set-env-vars="^@^PROJECT_ID=${PROJECT_ID}@REGION=${REGION}@LOG_LEVEL=${LOG_LEVEL}@LOG_TELEMETRY_PAYLOADS=${LOG_TELEMETRY_PAYLOADS}@ENABLE_MODEL_ARMOR=${ENABLE_MODEL_ARMOR}@MODEL_ARMOR_TEMPLATE_ID=${EFFECTIVE_ARMOR_TEMPLATE}@MODEL_ARMOR_MODE=${EFFECTIVE_ARMOR_MODE}@MODEL_ARMOR_FAIL_CLOSED=${MODEL_ARMOR_FAIL_CLOSED}@COST_CENTER_PROJECT_MAP=${COST_CENTER_PROJECT_MAP}@MODEL_REGION_MAP=${MODEL_REGION_MAP}@FAILOVER_REGIONS=${FAILOVER_REGIONS}@DEFAULT_FLASH_FALLBACK_MODEL=${DEFAULT_FLASH_FALLBACK_MODEL}@OPENAI_UPSTREAM_BASE_URL=${OPENAI_UPSTREAM_BASE_URL}" \
    --set-secrets="GATEWAY_API_KEY=${SECRET_NAME}:latest" \
    --timeout="${CLOUD_RUN_TIMEOUT}" \
    --cpu="${CLOUD_RUN_CPU}" \
    --memory="${CLOUD_RUN_MEMORY}" \
    --min-instances="${CLOUD_RUN_MIN_INSTANCES}" \
    --max-instances="${CLOUD_RUN_MAX_INSTANCES}" \
    --quiet

  GATEWAY_URL="$(gcloud run services describe "${SERVICE_NAME}" \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --format='value(status.url)')"

  # Probe /v1beta:recordCodeAssistMetrics because GFE on *.run.app reserves /*z paths (/healthz).
  log_info "Running post-deployment authenticated smoke check against ${GATEWAY_URL}/v1beta:recordCodeAssistMetrics..."
  local smoke_code
  smoke_code="$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    "${GATEWAY_URL}/v1beta:recordCodeAssistMetrics" \
    -H "Authorization: Bearer ${GATEWAY_API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{}' || echo "000")"

  if [[ "${smoke_code}" != "200" ]]; then
    if [[ "${CLOUD_RUN_INGRESS}" != "all" ]]; then
      log_warn "Cloud Run service uses private ingress ('${CLOUD_RUN_INGRESS}'); external probe returned HTTP ${smoke_code}. Verify from inside your authorized VPC / Load Balancer."
      return 0
    fi
    log_error "Post-deployment smoke check returned HTTP ${smoke_code} (expected 200)."
    exit 1
  fi
  log_info "Smoke check passed (HTTP 200 OK)."
}


# ==============================================================================
# BLOCK 8: CLIENT CONFIG GENERATION & DEPLOYMENT SUMMARY ENTRYPOINT
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Generates a git-ignored `admin_settings.local.json` populated with live Gateway credentials.
# Parameters:
#   - None (reads `admin_settings.json`, writes `admin_settings.local.json` with 0600 permissions).
# Return Value:
#   - Returns 0.
# Exceptions/Errors:
#   - Logs a warning if template `admin_settings.json` is missing.
# ------------------------------------------------------------------------------
generate_local_client_config() {
  local template_file="${SCRIPT_DIR}/admin_settings.json"
  local output_file="${SCRIPT_DIR}/admin_settings.local.json"
  if [[ ! -f "${template_file}" ]]; then
    log_warn "Template '${template_file}' not found; skipping admin_settings.local.json generation."
    return 0
  fi

  jq \
    --arg url "${GATEWAY_URL}" \
    --arg key "${GATEWAY_API_KEY}" \
    '.gateway.url = $url | .gateway.apiKey = $key' \
    "${template_file}" > "${output_file}"
  chmod 600 "${output_file}"
}

# ------------------------------------------------------------------------------
# Summary: Orchestrates the complete installation workflow from project selection to smoke check.
# Parameters:
#   - "$@" (array): Command-line arguments.
# Return Value:
#   - Returns 0 on successful deployment.
# Exceptions/Errors:
#   - Exits non-zero if any stage fails.
# ------------------------------------------------------------------------------
main() {
  parse_args "$@"
  select_gcp_project
  review_and_customize_settings
  provision_iam_and_secret
  provision_model_armor_layer
  deploy_cloud_run_gateway
  generate_local_client_config

  cat <<EOF

================================================================================
  ANTIGRAVITY ENTERPRISE GATEWAY DEPLOYMENT COMPLETE
================================================================================
  GCP Project ID         : ${PROJECT_ID}
  GCP Region             : ${REGION}
  Deployed Runtime       : ${GATEWAY_RUNTIME}
  Cloud Run Service      : ${SERVICE_NAME}
  Gateway URL            : ${GATEWAY_URL}
  Secret Manager Key     : ${SECRET_NAME}
  Model Armor Mode       : ${EFFECTIVE_ARMOR_MODE} (${EFFECTIVE_ARMOR_TEMPLATE:-none})
  Generated MDM Config   : ${SCRIPT_DIR}/admin_settings.local.json (chmod 600, git-ignored)

  Quick CLI Verification:
    AGY_LLM_GATEWAY_URL="${GATEWAY_URL}" \\
    AGY_LLM_GATEWAY_API_KEY="\$(gcloud secrets versions access latest --secret=${SECRET_NAME} --project=${PROJECT_ID})" \\
    agy -p "Respond with OK if connected through Enterprise Gateway."

  Uninstall Command:
    ./uninstall.sh --project=${PROJECT_ID} --region=${REGION}
================================================================================
EOF
}

main "$@"
