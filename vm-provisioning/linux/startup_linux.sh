#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: GCE Startup Script — Vanilla Antigravity Ubuntu 22.04 LTS VM
# ==============================================================================
# Author: Pradeep Singh
# License: Apache-2.0
#
# Purpose:
#   Automated first-boot Compute Engine startup script (`startup-script`) that
#   configures an Ubuntu 22.04 LTS VM with a 100% vanilla Google Antigravity
#   workstation: Antigravity CLI (`agy`), Antigravity Desktop App (XFCE4/XRDP),
#   Visual Studio Code + `Google.google-antigravity` extension, and Browser Web
#   UI (`antigravity-web`) over Nginx WebSocket multiplexing on port 4400.
#
# Architecture / Context:
#   Injected via `--metadata-from-file=startup-script=linux/startup_linux.sh` by
#   `linux/provision_linux_vm.sh` (and top-level `install.sh`). Organized into
#   6 modular installation blocks with idempotency protection so subsequent VM
#   reboots exit immediately once `/var/log/antigravity-install.done` exists.
#
# Dependencies / Side Effects:
#   - Executes as `root` during GCE boot and logs to `/var/log/antigravity-install.log`.
#   - Installs system packages, `/usr/local/bin/agy`, `/opt/antigravity-app`,
#     `/usr/bin/code`, `/etc/skel/.vscode/extensions`, `/etc/nginx/sites-enabled/antigravity.conf`,
#     `/usr/local/bin/antigravity-login`, and `/usr/local/bin/antigravity-web`.
# ==============================================================================

set -euo pipefail
export HOME=/root
export DEBIAN_FRONTEND=noninteractive

readonly LOG_FILE="/var/log/antigravity-install.log"
readonly DONE_MARKER="/var/log/antigravity-install.done"

exec > >(tee -a "${LOG_FILE}") 2>&1

# Idempotency guard: prevent re-downloading installers on ordinary VM reboots.
if [[ -f "${DONE_MARKER}" ]]; then
  echo "=== Vanilla Antigravity Linux setup already completed (${DONE_MARKER} present). ==="
  exit 0
fi

# ==============================================================================
# BLOCK 1: SYSTEM DEPENDENCIES, CHROMIUM LIBS, NGINX & XFCE4 / XRDP DESKTOP
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Installs core Linux utilities, Electron/Chromium shared libraries, Nginx, and XFCE4/XRDP.
# Parameters:
#   - None.
# Return Value:
#   - Returns 0 when apt package installation finishes.
# Exceptions/Errors:
#   - Exits non-zero if `apt-get` cannot reach Ubuntu repositories.
# ------------------------------------------------------------------------------
install_system_and_desktop_packages() {
  echo "=== [1/6] Installing Linux system dependencies & XFCE4/XRDP desktop libraries ==="
  apt-get update -y
  apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    wget \
    tar \
    unzip \
    git \
    jq \
    gpg \
    apt-transport-https \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libgtk-3-0 \
    libx11-xcb1 \
    libxcb-dri3-0 \
    xdg-utils \
    dbus-x11 \
    nginx \
    xfce4 \
    xfce4-goodies \
    xrdp
}


# ==============================================================================
# BLOCK 2: VANILLA ANTIGRAVITY CLI (`agy`) INSTALLATION
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Installs the official standalone Antigravity CLI binary into `/usr/local/bin/agy`.
# Parameters:
#   - None.
# Return Value:
#   - Returns 0 after verifying binary permissions.
# Exceptions/Errors:
#   - Exits non-zero if `https://antigravity.google/cli/install.sh` download fails.
# ------------------------------------------------------------------------------
install_antigravity_cli() {
  echo "=== [2/6] Installing Vanilla Antigravity CLI ('agy') to /usr/local/bin/agy ==="
  rm -f /usr/local/bin/agy
  curl -fsSL https://antigravity.google/cli/install.sh | bash -s -- --dir /usr/local/bin
  chmod 0755 /usr/local/bin/agy
  /usr/local/bin/agy --version || true
}


# ==============================================================================
# BLOCK 3: VANILLA ANTIGRAVITY DESKTOP APPLICATION (LINUX X64)
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Resolves latest Antigravity Hub release, extracts to `/opt/antigravity-app`, and creates XFCE launcher.
# Parameters:
#   - None (populates global `HUB_VERSION`).
# Return Value:
#   - Returns 0 when `/usr/local/bin/antigravity-desktop` and `.desktop` entry are installed.
# Exceptions/Errors:
#   - Falls back to release `2.26.0` (`6546645232517120`) if release manifest query is transiently unavailable.
# ------------------------------------------------------------------------------
install_antigravity_desktop_app() {
  echo "=== [3/6] Installing Vanilla Antigravity Desktop App (Linux x64) ==="
  local releases_json
  releases_json="$(curl -fsSL "https://antigravity-hub-auto-updater-974169037036.us-central1.run.app/releases" || true)"
  HUB_VERSION="$(echo "${releases_json}" | jq -r '.[0].version // "2.26.0"')"
  local hub_exec_id
  hub_exec_id="$(echo "${releases_json}" | jq -r '.[0].execution_id // "6546645232517120"')"
  local linux_app_url="https://storage.googleapis.com/antigravity-public/antigravity-hub/${HUB_VERSION}-${hub_exec_id}/linux-x64/Antigravity.tar.gz"

  echo "Downloading Antigravity Desktop App v${HUB_VERSION} from ${linux_app_url}..."
  mkdir -p /opt/antigravity-app
  curl -fsSL "${linux_app_url}" -o /tmp/Antigravity.tar.gz
  tar -xzf /tmp/Antigravity.tar.gz -C /opt/antigravity-app --strip-components=1 \
    || tar -xzf /tmp/Antigravity.tar.gz -C /opt/antigravity-app
  rm -f /tmp/Antigravity.tar.gz
  chmod -R a+rX /opt/antigravity-app

  local app_bin
  app_bin="$(find /opt/antigravity-app -maxdepth 2 -type f -executable \( -name "antigravity" -o -name "Antigravity" \) | head -n 1 || true)"
  if [[ -n "${app_bin}" ]]; then
    ln -sf "${app_bin}" /usr/local/bin/antigravity-desktop
  fi

  cat <<'DESKTOP_EOF' > /usr/share/applications/antigravity.desktop
[Desktop Entry]
Name=Google Antigravity
Comment=Google Antigravity AI Development Platform
Exec=/usr/local/bin/antigravity-desktop --no-sandbox %U
Terminal=false
Type=Application
Categories=Development;IDE;
DESKTOP_EOF
  chmod 0644 /usr/share/applications/antigravity.desktop
}


# ==============================================================================
# BLOCK 4: MICROSOFT VS CODE & OFFICIAL GOOGLE ANTIGRAVITY EXTENSION (`VSIX`)
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Installs VS Code `.deb` and pre-seeds `Google.google-antigravity` across `/etc/skel` and all users.
# Parameters:
#   - None.
# Return Value:
#   - Returns 0 after seeding `/etc/skel/.vscode/extensions` and `/etc/profile.d/antigravity-vscode-ext.sh`.
# Exceptions/Errors:
#   - Falls back to Visual Studio Marketplace URL if OpenVSX API metadata is empty.
# ------------------------------------------------------------------------------
install_vscode_and_antigravity_extension() {
  echo "=== [4/6] Installing Microsoft Visual Studio Code & Google Antigravity Extension ==="
  # Pre-seed debconf so `code.postinst` never blocks waiting on interactive repo prompts on Ubuntu 22.04.
  echo "code code/add-microsoft-repo boolean true" | debconf-set-selections
  if ! command -v code >/dev/null 2>&1; then
    curl -fsSL -L "https://update.code.visualstudio.com/latest/linux-deb-x64/stable" -o /tmp/vscode.deb
    apt-get install -y /tmp/vscode.deb
    rm -f /tmp/vscode.deb
  fi
  code --version --no-sandbox --user-data-dir=/tmp/vscode-root-check || true

  mkdir -p /opt/antigravity-vscode
  local vsix_path="/opt/antigravity-vscode/google-antigravity.vsix"
  local vsix_url
  vsix_url="$(curl -fsSL "https://open-vsx.org/api/Google/google-antigravity" | jq -r '.files.download // empty' || true)"
  if [[ -z "${vsix_url}" ]]; then
    vsix_url="https://marketplace.visualstudio.com/_apis/public/gallery/publishers/Google/vsextensions/google-antigravity/latest/vspackage"
  fi

  echo "Downloading Google Antigravity VS Code VSIX from ${vsix_url}..."
  curl -fsSL -L "${vsix_url}" -o "${vsix_path}"
  chmod 0644 "${vsix_path}"

  # Seed `/etc/skel` so newly created local Linux accounts inherit the extension immediately.
  mkdir -p /etc/skel/.vscode/extensions
  code --install-extension "${vsix_path}" \
    --extensions-dir /etc/skel/.vscode/extensions \
    --user-data-dir /tmp/vscode-skel-data \
    --no-sandbox \
    --force || true
  rm -rf /tmp/vscode-skel-data /tmp/vscode-root-check

  # Seed all pre-existing user home directories under `/home/*`.
  local udir uname
  for udir in /home/*; do
    [[ -d "${udir}" ]] || continue
    uname="$(basename "${udir}")"
    sudo -u "${uname}" -H code --install-extension "${vsix_path}" --force 2>/dev/null || true
  done

  # Seed future GCE OS Login / SSH users whose home directories are created dynamically at first login.
  cat <<'PROFILE_EOF' > /etc/profile.d/antigravity-vscode-ext.sh
if command -v code >/dev/null 2>&1 && [[ -f /opt/antigravity-vscode/google-antigravity.vsix ]]; then
    if [[ ! -d "${HOME}/.vscode/extensions" ]] || ! ls "${HOME}/.vscode/extensions"/google.google-antigravity-* >/dev/null 2>&1; then
        mkdir -p "${HOME}/.vscode/extensions" 2>/dev/null || true
        cp -rn /etc/skel/.vscode/extensions/* "${HOME}/.vscode/extensions/" 2>/dev/null || true
    fi
fi
PROFILE_EOF
  chmod 0644 /etc/profile.d/antigravity-vscode-ext.sh
}


# ==============================================================================
# BLOCK 5: NGINX WEBSOCKET MULTIPLEXER, `antigravity-login` & `antigravity-web`
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Installs Chrome, configures Nginx `:4400` -> `127.0.0.1:4401` WebSocket proxy, and writes OAuth/Web helpers.
# Parameters:
#   - None.
# Return Value:
#   - Returns 0 after restarting `nginx` and `xrdp`.
# Exceptions/Errors:
#   - Non-fatal fallback if optional Chrome `.deb` download fails.
# ------------------------------------------------------------------------------
configure_browser_oauth_and_web_hub() {
  echo "=== [5/6] Configuring Browser OAuth Helper (antigravity-login) & Web UI (antigravity-web) ==="
  if ! command -v google-chrome >/dev/null 2>&1; then
    wget -q -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb || true
    apt-get install -y /tmp/google-chrome.deb || true
    rm -f /tmp/google-chrome.deb
  fi

  rm -f /etc/nginx/sites-enabled/*
  echo "set \$antigravity_oauth_port 4401;" > /etc/nginx/antigravity_oauth_port.conf
  chmod 0666 /etc/nginx/antigravity_oauth_port.conf

  # Inject `useWebSocket="true"` via `<head>` sub_filter so `agy --hub` multiplexes all 6+
  # Connect-RPC server-streaming channels over a single `/connect-websocket` socket instead
  # of stalling Chromium's 6-connection-per-origin HTTP/1.1 limit.
  cat <<'NGINX_EOF' > /etc/nginx/sites-enabled/antigravity.conf
map $http_upgrade $connection_upgrade {
    default upgrade;
    ""      close;
}

server {
    listen 0.0.0.0:4400;
    listen [::]:4400;
    server_name _;

    client_max_body_size 100M;
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
    proxy_buffering off;
    proxy_request_buffering off;

    location = /auth/callback {
        include /etc/nginx/antigravity_oauth_port.conf;
        proxy_pass http://127.0.0.1:$antigravity_oauth_port;
        proxy_http_version 1.1;
        proxy_set_header Host "localhost:$antigravity_oauth_port";
    }

    location / {
        proxy_pass http://127.0.0.1:4401;
        proxy_http_version 1.1;
        proxy_set_header Host "localhost:4401";
        proxy_set_header Origin "http://localhost:4401";
        proxy_set_header Accept-Encoding "";
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_hide_header Content-Security-Policy;
        proxy_hide_header Cross-Origin-Opener-Policy;

        sub_filter_once on;
        sub_filter '<head>' '<head><script>(function(){const g=URLSearchParams.prototype.get;URLSearchParams.prototype.get=function(k){return k==="useWebSocket"?"true":g.call(this,k)};})();</script>';
    }
}
NGINX_EOF
  systemctl enable nginx || true
  systemctl restart nginx || true

  # `AGY_CLI_CDE_AUTH_ACTION=login` uses `https://antigravity.google/oauth-callback` so remote SSH
  # users never hang on unreachable `localhost:<random_port>` browser redirects. Mirror the token
  # to `antigravity-oauth-token` so both `agy --hub` and standalone `agy` share one sign-in.
  cat <<'LOGIN_EOF' > /usr/local/bin/antigravity-login
#!/usr/bin/env bash
set -euo pipefail
PROJECT_ID="${1:-${GOOGLE_CLOUD_PROJECT:-}}"
if [[ -z "${PROJECT_ID}" ]]; then
    PROJECT_ID=$(curl -fsSL -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/project/project-id 2>/dev/null || echo "")
fi

echo "================================================================================"
echo "Antigravity — Browser-Friendly OAuth Sign-In (No localhost redirect)"
echo "================================================================================"
echo "Select Account Type:"
echo "  [1] Google Cloud / Workspace Business Account [Default]"
echo "  [2] Personal Google Account (@gmail.com)"
read -r -p "Enter choice [1 or 2, default=1]: " ACC_CHOICE || ACC_CHOICE="1"

if [[ "${ACC_CHOICE}" == "2" ]]; then
    export AGY_CDE_ENTERPRISE_AUTH="false"
else
    export AGY_CDE_ENTERPRISE_AUTH="true"
    if [[ -n "${PROJECT_ID}" ]]; then
        export GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
        echo "Binding Google Cloud Project: ${GOOGLE_CLOUD_PROJECT}"
    fi
fi

echo ""
echo "Open the URL below in your browser, click 'Sign in', copy the code from"
echo "https://antigravity.google/oauth-callback, and paste it below:"
echo "--------------------------------------------------------------------------------"
AGY_CLI_CDE_AUTH_ACTION=login /usr/local/bin/agy
if [[ -f "${HOME}/.gemini/jetski-standalone-oauth-token" ]]; then
    mkdir -p "${HOME}/.gemini/antigravity-cli"
    cp -f "${HOME}/.gemini/jetski-standalone-oauth-token" "${HOME}/.gemini/antigravity-cli/antigravity-oauth-token"
    chmod 0600 "${HOME}/.gemini/antigravity-cli/antigravity-oauth-token"
fi
LOGIN_EOF
  chmod 0755 /usr/local/bin/antigravity-login

  cat <<'WEB_EOF' > /usr/local/bin/antigravity-web
#!/usr/bin/env bash
set -euo pipefail
PUBLIC_PORT="${1:-4400}"
INTERNAL_PORT=4401
PUBLIC_IP=$(curl -fsSL -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip 2>/dev/null || hostname -I | awk "{print \$1}")
DEFAULT_PROJECT=$(curl -fsSL -H "Metadata-Flavor: Google" http://metadata.google.internal/computeMetadata/v1/project/project-id 2>/dev/null || echo "")

if [[ ! -f "/etc/antigravity/admin_settings.json" && ! -f "${HOME}/.antigravity/settings.json" && -z "${AGY_LLM_GATEWAY_URL:-}" ]]; then
    if ! AGY_CLI_CDE_AUTH_ACTION=check /usr/local/bin/agy >/dev/null 2>&1; then
        echo "You are not signed into Antigravity yet."
        echo "Starting one-time OAuth sign-in (uses https://antigravity.google/oauth-callback)..."
        echo ""
        /usr/local/bin/antigravity-login "${DEFAULT_PROJECT}"
        echo ""
    else
        AGY_CLI_CDE_AUTH_ACTION=check /usr/local/bin/agy || true
    fi
fi

if [[ -f "${HOME}/.gemini/jetski-standalone-oauth-token" ]]; then
    mkdir -p "${HOME}/.gemini/antigravity-cli"
    cp -f "${HOME}/.gemini/jetski-standalone-oauth-token" "${HOME}/.gemini/antigravity-cli/antigravity-oauth-token"
    chmod 0600 "${HOME}/.gemini/antigravity-cli/antigravity-oauth-token"
fi

pkill -f "agy --hub" 2>/dev/null || true
sleep 1
sudo systemctl restart nginx 2>/dev/null || true

echo "================================================================================"
echo "Starting Antigravity Browser Web UI"
echo "  Public IP URL (No SSH Tunnel Needed): http://${PUBLIC_IP}:${PUBLIC_PORT}"
echo "  Localhost URL (If using SSH Tunnel):  http://localhost:${PUBLIC_PORT}"
echo "================================================================================"

exec env GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-${DEFAULT_PROJECT}}" AGY_ENABLE_HUB=1 /usr/local/bin/agy --hub --hub-port="${INTERNAL_PORT}" 2>&1 | sed "s|http://localhost:${INTERNAL_PORT}|http://${PUBLIC_IP}:${PUBLIC_PORT}|g"
WEB_EOF
  chmod 0755 /usr/local/bin/antigravity-web

  systemctl enable xrdp || true
  systemctl restart xrdp || true
}


# ==============================================================================
# BLOCK 6: STARTUP ORCHESTRATION & COMPLETION MARKER
# ==============================================================================

# ------------------------------------------------------------------------------
# Summary: Runs all 5 installation stages in order and records completion marker.
# Parameters:
#   - None.
# Return Value:
#   - Returns 0 and writes `/var/log/antigravity-install.done`.
# Exceptions/Errors:
#   - Exits non-zero if a mandatory installation stage fails.
# ------------------------------------------------------------------------------
main() {
  install_system_and_desktop_packages
  install_antigravity_cli
  install_antigravity_desktop_app
  install_vscode_and_antigravity_extension
  configure_browser_oauth_and_web_hub

  echo "=== [6/6] Vanilla Antigravity Linux Installation Complete (Desktop v${HUB_VERSION}) ==="
  touch "${DONE_MARKER}"
}

main
