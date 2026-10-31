#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: Local Quick-Start Launcher — Antigravity Admin Policy Studio
# ==============================================================================
# Purpose:
#   Creates an isolated Python virtual environment (`.venv`), installs pinned
#   dependencies, loads `.env` if present, and launches the Antigravity Admin
#   Policy Studio locally.
#
# Architecture / Context:
#   Convenience developer/administrator launcher inside `agy-policy-studio/`.
#
# Dependencies / Side Effects:
#   Requires `python3` (3.11+) with `venv` and `pip`. Writes local `.venv/`
#   (excluded via `.gitignore`).
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

export FLASK_HOST="${FLASK_HOST:-0.0.0.0}"
export PORT="${PORT:-8090}"

if [[ ! -d ".venv" ]]; then
  echo "[INFO] Creating Python virtual environment in ${SCRIPT_DIR}/.venv"
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

echo "[INFO] Launching Antigravity Admin Policy Studio at http://localhost:${PORT}"
exec python3 app.py
