#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: provision_test_vms.sh — Create the disposable AGY verification bench
# ==============================================================================
# Purpose:
#   Creates the IAP-only firewall rule and the two disposable test VMs (Ubuntu
#   22.04 and Windows Server 2022) used by the settings-scope verification, and
#   installs every Antigravity surface through the startup scripts in this folder.
#
# Architecture / Context:
#   Part of agy-config/verification/infra. The VMs have no service account and
#   accept SSH/RDP only from Google's IAP range (35.235.240.0/20). They keep an
#   ephemeral external IP for outbound downloads only (ingress stays IAP-only).
#   Gateway secrets are copied later by the operator (see ../README.md).
#
# Dependencies / Side Effects:
#   gcloud (authenticated), a settings.env next to ../settings.env.example.
#   Creates billable Compute Engine resources; delete them with
#   deprovision_test_vms.sh when the verification is done.
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-${SCRIPT_DIR}/../settings.env}"

#######################################
# Structured log line on stderr.
# Arguments: $1 level, $2... message
#######################################
log() {
  local level="$1"; shift
  printf '%s %-5s provision: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${level}" "$*" >&2
}

[[ -r "${ENV_FILE}" ]] || { log ERROR "settings file not found: ${ENV_FILE} (copy settings.env.example)"; exit 2; }
# shellcheck disable=SC1090
source "${ENV_FILE}"
for var in PROJECT_ID ZONE NETWORK SUBNET FIREWALL_RULE NETWORK_TAG LINUX_VM WINDOWS_VM MACHINE_TYPE; do
  [[ -n "${!var:-}" ]] || { log ERROR "${var} is not set in ${ENV_FILE}"; exit 2; }
done
[[ "${PROJECT_ID}" =~ ^[a-z][a-z0-9-]{4,28}[a-z0-9]$ ]] || { log ERROR "PROJECT_ID looks invalid"; exit 2; }

log INFO "creating IAP-only firewall rule ${FIREWALL_RULE}"
gcloud compute firewall-rules create "${FIREWALL_RULE}" --project="${PROJECT_ID}" --quiet \
  --network="${NETWORK}" --direction=INGRESS --allow=tcp:22,tcp:3389 \
  --source-ranges=35.235.240.0/20 --target-tags="${NETWORK_TAG}" \
  --description="AGY settings-scope verification: SSH/RDP from IAP only"

log INFO "creating ${LINUX_VM} (Ubuntu 22.04)"
gcloud compute instances create "${LINUX_VM}" --project="${PROJECT_ID}" --zone="${ZONE}" --quiet \
  --machine-type="${MACHINE_TYPE}" --subnet="${SUBNET}" --tags="${NETWORK_TAG}" \
  --image-family=ubuntu-2204-lts --image-project=ubuntu-os-cloud --boot-disk-size=100GB \
  --no-service-account --no-scopes --labels=purpose=agy-settings-scope \
  --metadata-from-file=startup-script="${SCRIPT_DIR}/startup_linux_test.sh"

log INFO "creating ${WINDOWS_VM} (Windows Server 2022)"
gcloud compute instances create "${WINDOWS_VM}" --project="${PROJECT_ID}" --zone="${ZONE}" --quiet \
  --machine-type="${MACHINE_TYPE}" --subnet="${SUBNET}" --tags="${NETWORK_TAG}" \
  --image-family=windows-2022 --image-project=windows-cloud --boot-disk-size=100GB \
  --no-service-account --no-scopes --labels=purpose=agy-settings-scope \
  --metadata=enable-windows-ssh=TRUE \
  --metadata-from-file=windows-startup-script-ps1="${SCRIPT_DIR}/startup_windows_test.ps1"

log INFO "done. Benches report readiness in /var/log/agy-verify-versions.json (Linux) and"
log INFO "C:\\ProgramData\\agy-verify\\install.done (Windows). Connect with --tunnel-through-iap."
