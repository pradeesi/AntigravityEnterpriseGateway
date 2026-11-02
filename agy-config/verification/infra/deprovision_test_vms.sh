#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: deprovision_test_vms.sh — Delete the disposable AGY verification bench
# ==============================================================================
# Purpose:
#   Deletes the two test VMs and the IAP-only firewall rule created by
#   provision_test_vms.sh. The gateway API key copies on the VMs are destroyed
#   with the boot disks.
#
# Architecture / Context:
#   Part of agy-config/verification/infra. Only touches resources named in
#   settings.env, and refuses to delete a VM that lacks the
#   purpose=agy-settings-scope label (protects unrelated machines).
#
# Dependencies / Side Effects:
#   gcloud (authenticated), settings.env. Irreversible deletion.
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
  printf '%s %-5s deprovision: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${level}" "$*" >&2
}

[[ -r "${ENV_FILE}" ]] || { log ERROR "settings file not found: ${ENV_FILE}"; exit 2; }
# shellcheck disable=SC1090
source "${ENV_FILE}"
for var in PROJECT_ID ZONE FIREWALL_RULE LINUX_VM WINDOWS_VM; do
  [[ -n "${!var:-}" ]] || { log ERROR "${var} is not set in ${ENV_FILE}"; exit 2; }
done

for vm in "${LINUX_VM}" "${WINDOWS_VM}"; do
  label="$(gcloud compute instances describe "${vm}" --project="${PROJECT_ID}" --zone="${ZONE}" --quiet \
    --format='value(labels.purpose)' 2>/dev/null || true)"
  if [[ "${label}" != "agy-settings-scope" ]]; then
    log WARN "skipping ${vm}: missing or unexpected purpose label ('${label}')"
    continue
  fi
  log INFO "deleting ${vm}"
  gcloud compute instances delete "${vm}" --project="${PROJECT_ID}" --zone="${ZONE}" --quiet
done

log INFO "deleting firewall rule ${FIREWALL_RULE}"
gcloud compute firewall-rules delete "${FIREWALL_RULE}" --project="${PROJECT_ID}" --quiet
log INFO "bench removed"
