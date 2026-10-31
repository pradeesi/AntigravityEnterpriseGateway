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

# Install offline-first from local `vendor/wheels/` so air-gapped workstations never require PyPI access.
if ! python3 -c "import flask, werkzeug, dotenv, gunicorn" >/dev/null 2>&1; then
  if [[ -d "${SCRIPT_DIR}/vendor/wheels" ]]; then
    echo "[INFO] Installing Python dependencies from local wheelhouse (${SCRIPT_DIR}/vendor/wheels)..."
    pip install --quiet --no-index --find-links="${SCRIPT_DIR}/vendor/wheels" -r requirements.txt \
      || pip install --quiet -r requirements.txt
  else
    pip install --quiet -r requirements.txt
  fi
fi

echo "[INFO] Launching Antigravity Admin Policy Studio at http://localhost:${PORT}"
exec python3 app.py
