#!/usr/bin/env bash
# ==============================================================================
# FILE HEADER: startup_linux_test.sh — Ubuntu 22.04 Antigravity verification VM
# ==============================================================================
# Purpose:
#   First-boot Compute Engine startup script that turns a fresh Ubuntu 22.04 VM
#   into a headless Antigravity test bench: the latest public Antigravity CLI,
#   desktop App, VS Code + Antigravity extension, the ACP server used by
#   JetBrains/Zed, Zed itself, Google Chrome, Xvfb, and a Python harness venv.
#
# Architecture / Context:
#   Part of agy-config/verification/. Injected with
#   `--metadata-from-file=startup-script=infra/startup_linux_test.sh`. Unlike
#   vm-provisioning/linux/startup_linux.sh it installs no RDP server and no
#   public web listener: the VM is reached only through IAP, and GUI surfaces
#   run under Xvfb and are driven over the Chrome DevTools Protocol.
#
# Dependencies / Side Effects:
#   - Runs as root on boot; logs to /var/log/agy-verify-install.log.
#   - Resolves "latest" versions at boot from the public release manifests and
#     records them in /var/log/agy-verify-versions.json.
#   - Installs into /usr/local/bin/agy, /opt/antigravity-app, /opt/agy-acp-server,
#     /opt/zed.app, /opt/agy-verify (vsix + venv). Idempotent via a done marker.
# ==============================================================================

set -uo pipefail
export HOME=/root
export DEBIAN_FRONTEND=noninteractive

readonly LOG_FILE="/var/log/agy-verify-install.log"
readonly DONE_MARKER="/var/log/agy-verify-install.done"
readonly VERSIONS_FILE="/var/log/agy-verify-versions.json"
readonly VERIFY_ROOT="/opt/agy-verify"
readonly CLI_MANIFEST="https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/linux_amd64.json"
readonly HUB_RELEASES="https://antigravity-hub-auto-updater-974169037036.us-central1.run.app/releases"
readonly OPENVSX_API="https://open-vsx.org/api/Google/google-antigravity"
readonly ACP_REGISTRY="https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json"

exec > >(tee -a "${LOG_FILE}") 2>&1

if [[ -f "${DONE_MARKER}" ]]; then
  echo "INFO: verification bench already installed (${DONE_MARKER}); nothing to do."
  exit 0
fi

# ------------------------------------------------------------------------------
# Summary: Prints a timestamped, level-tagged log line.
# Parameters:
#   - $1 (string): Level (INFO, WARN, ERROR).
#   - $2 (string): Message.
# Return Value:
#   - Always 0.
# Exceptions/Errors:
#   - None.
# ------------------------------------------------------------------------------
log() {
  printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$2"
}

# ------------------------------------------------------------------------------
# Summary: Installs OS packages for Electron apps, Xvfb automation, Zed (software
#          Vulkan), and the Python harness.
# Parameters:
#   - None.
# Return Value:
#   - 0 on success.
# Exceptions/Errors:
#   - Exits non-zero if apt-get cannot install the mandatory packages.
# ------------------------------------------------------------------------------
install_packages() {
  log INFO "[1/8] Installing OS packages"
  apt-get update -y || return 1
  apt-get install -y --no-install-recommends \
    ca-certificates curl wget tar unzip jq git gpg apt-transport-https \
    python3 python3-venv python3-pip \
    xvfb x11-utils xauth xdotool imagemagick dbus-x11 fonts-dejavu-core \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 libgtk-3-0 libx11-xcb1 libxcb-dri3-0 libsecret-1-0 \
    xdg-utils libvulkan1 mesa-vulkan-drivers acl e2fsprogs || return 1
}

# ------------------------------------------------------------------------------
# Summary: Installs Google Chrome stable (web UI tests and CDP client checks).
# Parameters:
#   - None.
# Return Value:
#   - 0 on success; non-fatal failure is logged.
# Exceptions/Errors:
#   - Logs WARN when the Chrome package can't be downloaded.
# ------------------------------------------------------------------------------
install_chrome() {
  log INFO "[2/8] Installing Google Chrome"
  if wget -q -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb; then
    apt-get install -y /tmp/google-chrome.deb || log WARN "Chrome install failed"
    rm -f /tmp/google-chrome.deb
  else
    log WARN "Chrome download failed"
  fi
}

# ------------------------------------------------------------------------------
# Summary: Installs the latest public Antigravity CLI after a SHA-512 check.
# Parameters:
#   - None.
# Return Value:
#   - 0 on success.
# Exceptions/Errors:
#   - Returns 1 if the manifest, download, or checksum fails.
# ------------------------------------------------------------------------------
install_cli() {
  log INFO "[3/8] Installing Antigravity CLI from ${CLI_MANIFEST}"
  local manifest url sha
  manifest="$(curl -fsSL "${CLI_MANIFEST}")" || return 1
  url="$(jq -r '.url' <<<"${manifest}")"
  sha="$(jq -r '.sha512' <<<"${manifest}")"
  CLI_VERSION="$(jq -r '.version' <<<"${manifest}")"
  curl -fsSL "${url}" -o /tmp/agy_cli.tar.gz || return 1
  # Refuse to install a binary whose digest doesn't match the release manifest.
  echo "${sha}  /tmp/agy_cli.tar.gz" | sha512sum -c - || return 1
  mkdir -p /tmp/agy_cli && tar -xzf /tmp/agy_cli.tar.gz -C /tmp/agy_cli || return 1
  # The release tarball ships a single executable named `antigravity`; install it as `agy`.
  local bin
  bin="$(find /tmp/agy_cli -type f \( -name agy -o -name antigravity \) | head -n 1)"
  [[ -n "${bin}" ]] || { log ERROR "no agy/antigravity executable in the CLI tarball"; return 1; }
  install -m 0755 "${bin}" /usr/local/bin/agy || return 1
  rm -rf /tmp/agy_cli /tmp/agy_cli.tar.gz
  /usr/local/bin/agy --version || true
}

# ------------------------------------------------------------------------------
# Summary: Installs the latest Antigravity desktop App (Linux x64 tarball).
# Parameters:
#   - None.
# Return Value:
#   - 0 on success.
# Exceptions/Errors:
#   - Returns 1 if the release manifest or download fails.
# ------------------------------------------------------------------------------
install_app() {
  log INFO "[4/8] Installing Antigravity desktop App"
  local releases exec_id url
  releases="$(curl -fsSL "${HUB_RELEASES}")" || return 1
  APP_VERSION="$(jq -r '.[0].version' <<<"${releases}")"
  exec_id="$(jq -r '.[0].execution_id' <<<"${releases}")"
  url="https://storage.googleapis.com/antigravity-public/antigravity-hub/${APP_VERSION}-${exec_id}/linux-x64/Antigravity.tar.gz"
  mkdir -p /opt/antigravity-app
  curl -fsSL "${url}" -o /tmp/Antigravity.tar.gz || return 1
  tar -xzf /tmp/Antigravity.tar.gz -C /opt/antigravity-app --strip-components=1 \
    || tar -xzf /tmp/Antigravity.tar.gz -C /opt/antigravity-app
  rm -f /tmp/Antigravity.tar.gz
  chmod -R a+rX /opt/antigravity-app
  local app_bin
  app_bin="$(find /opt/antigravity-app -maxdepth 2 -type f -executable \( -name antigravity -o -name Antigravity \) | head -n 1)"
  [[ -n "${app_bin}" ]] && ln -sf "${app_bin}" /usr/local/bin/antigravity-desktop
}

# ------------------------------------------------------------------------------
# Summary: Installs VS Code and downloads the latest Antigravity VSIX (installed
#          per test user by the harness so every round starts clean).
# Parameters:
#   - None.
# Return Value:
#   - 0 on success.
# Exceptions/Errors:
#   - Returns 1 if VS Code or the VSIX can't be downloaded.
# ------------------------------------------------------------------------------
install_vscode() {
  log INFO "[5/8] Installing VS Code and the Antigravity VSIX"
  echo "code code/add-microsoft-repo boolean true" | debconf-set-selections
  curl -fsSL -L "https://update.code.visualstudio.com/latest/linux-deb-x64/stable" -o /tmp/vscode.deb || return 1
  apt-get install -y /tmp/vscode.deb || return 1
  rm -f /tmp/vscode.deb
  local meta url
  meta="$(curl -fsSL "${OPENVSX_API}")" || return 1
  VSIX_VERSION="$(jq -r '.version' <<<"${meta}")"
  url="$(jq -r '.files.download' <<<"${meta}")"
  mkdir -p "${VERIFY_ROOT}/vsix"
  curl -fsSL -L "${url}" -o "${VERIFY_ROOT}/vsix/google-antigravity.vsix" || return 1
  chmod 0644 "${VERIFY_ROOT}/vsix/google-antigravity.vsix"
}

# ------------------------------------------------------------------------------
# Summary: Installs the ACP server that JetBrains and Zed download from the ACP
#          agent registry, after a SHA-256 check.
# Parameters:
#   - None.
# Return Value:
#   - 0 on success.
# Exceptions/Errors:
#   - Returns 1 if the registry entry, download, or checksum fails.
# ------------------------------------------------------------------------------
install_acp_server() {
  log INFO "[6/8] Installing the Antigravity ACP server from the ACP registry"
  local entry url sha
  entry="$(curl -fsSL "${ACP_REGISTRY}" | jq -c '.agents[] | select(.id=="antigravity-acp")')" || return 1
  ACP_VERSION="$(jq -r '.version' <<<"${entry}")"
  url="$(jq -r '.distribution.binary["linux-x86_64"].archive' <<<"${entry}")"
  sha="$(jq -r '.distribution.binary["linux-x86_64"].sha256' <<<"${entry}")"
  curl -fsSL "${url}" -o /tmp/acp.zip || return 1
  echo "${sha}  /tmp/acp.zip" | sha256sum -c - || return 1
  rm -rf /opt/agy-acp-server && mkdir -p /opt/agy-acp-server
  unzip -q /tmp/acp.zip -d /opt/agy-acp-server || return 1
  rm -f /tmp/acp.zip
  chmod -R a+rX /opt/agy-acp-server
  find /opt/agy-acp-server -name 'agy_acp_server*' -exec chmod 0755 {} \;
}

# ------------------------------------------------------------------------------
# Summary: Installs Zed system-wide for the single real-editor ACP smoke test.
# Parameters:
#   - None.
# Return Value:
#   - 0 on success; failure is non-fatal (ACP is also tested at protocol level).
# Exceptions/Errors:
#   - Logs WARN when the Zed tarball can't be downloaded.
# ------------------------------------------------------------------------------
install_zed() {
  log INFO "[7/8] Installing Zed"
  if curl -fsSL -L "https://zed.dev/api/releases/stable/latest/zed-linux-x86_64.tar.gz" -o /tmp/zed.tar.gz; then
    rm -rf /opt/zed.app && tar -xzf /tmp/zed.tar.gz -C /opt && rm -f /tmp/zed.tar.gz
    ln -sf /opt/zed.app/bin/zed /usr/local/bin/zed
    ZED_VERSION="$(/opt/zed.app/bin/zed --version 2>/dev/null | head -n 1 || echo unknown)"
  else
    log WARN "Zed download failed"
    ZED_VERSION="not-installed"
  fi
}

# ------------------------------------------------------------------------------
# Summary: Creates the Python harness venv (CDP + ACP clients) and writes the
#          resolved versions file.
# Parameters:
#   - None.
# Return Value:
#   - 0 on success.
# Exceptions/Errors:
#   - Returns 1 if pip can't install the harness dependencies.
# ------------------------------------------------------------------------------
finish_bench() {
  log INFO "[8/8] Creating harness venv and versions file"
  python3 -m venv "${VERIFY_ROOT}/venv" || return 1
  "${VERIFY_ROOT}/venv/bin/pip" install --quiet websocket-client requests pyyaml || return 1
  chmod -R a+rX "${VERIFY_ROOT}"
  local code_version chrome_version
  code_version="$(code --version --no-sandbox --user-data-dir=/tmp/vsc-ver 2>/dev/null | head -n 1 || echo unknown)"
  chrome_version="$(google-chrome --version 2>/dev/null || echo unknown)"
  rm -rf /tmp/vsc-ver
  jq -n --arg cli "${CLI_VERSION:-unknown}" --arg app "${APP_VERSION:-unknown}" \
        --arg vsix "${VSIX_VERSION:-unknown}" --arg acp "${ACP_VERSION:-unknown}" \
        --arg zed "${ZED_VERSION:-unknown}" --arg code "${code_version}" \
        --arg chrome "${chrome_version}" --arg os "$(lsb_release -ds 2>/dev/null)" \
        '{cli:$cli, desktop_app:$app, vscode_extension:$vsix, acp_server:$acp, zed:$zed, vscode:$code, chrome:$chrome, os:$os}' \
        > "${VERSIONS_FILE}"
  cat "${VERSIONS_FILE}"
}

# ------------------------------------------------------------------------------
# Summary: Runs every install stage; mandatory stages abort the bench build.
# Parameters:
#   - None.
# Return Value:
#   - 0 when the bench is ready (done marker written).
# Exceptions/Errors:
#   - Exits 1 when a mandatory stage fails (no done marker, so a reboot retries).
# ------------------------------------------------------------------------------
main() {
  install_packages || { log ERROR "package install failed"; exit 1; }
  install_chrome
  install_cli || { log ERROR "CLI install failed"; exit 1; }
  install_app || { log ERROR "App install failed"; exit 1; }
  install_vscode || { log ERROR "VS Code install failed"; exit 1; }
  install_acp_server || { log ERROR "ACP server install failed"; exit 1; }
  install_zed
  finish_bench || { log ERROR "harness venv failed"; exit 1; }
  touch "${DONE_MARKER}"
  log INFO "Verification bench ready."
}

main
