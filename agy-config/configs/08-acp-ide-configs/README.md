# `acp.json` & `antigravity-acp-settings.json` — JetBrains IDEs & Zed Editor (ACP Server) Configuration

## 1. What These Files Are Used For

**JetBrains IDEs** (IntelliJ IDEA, PyCharm, GoLand, WebStorm, CLion, Android Studio) and **Zed** integrate with Google Antigravity (`1.3.0+`) via the **Agent Client Protocol (ACP)** server (`agy acp` / `agy_acp_server`).

Because desktop IDEs launched from the macOS Dock, Windows Start Menu, or Linux desktop launcher **do not source interactive shell profiles** (`~/.bashrc`, `~/.zshrc`), connecting JetBrains and Zed to an Enterprise Gateway requires two coordinated files:

1. **[`antigravity-acp-settings.json`](./antigravity-acp-settings.json)** *(deployed as `~/.gemini/antigravity-acp/settings.json`)*:
   * Explicitly switches the ACP server into Enterprise Gateway authentication mode (`{"auth": {"type": "gateway"}}`).
   * **Critical Difference from CLI**: Unlike `agy` CLI (where setting `AGY_LLM_GATEWAY_URL` automatically enables gateway mode), the ACP server **requires** `"auth": {"type": "gateway"}` in `~/.gemini/antigravity-acp/settings.json` unless already enabled via system-wide `admin_settings.json`.
2. **[`acp.json`](./acp.json)** *(deployed as `~/.jetbrains/acp.json` for JetBrains IDEs and merged into `settings.json` for Zed)*:
   * Registers the `Antigravity` agent server binary (`command` + `args`) and injects `AGY_LLM_GATEWAY_*` environment variables directly into the ACP server child process.
   * Note: If [`admin_settings.json`](../01-admin-settings/README.md) (Tier-1 MDM) is deployed on the workstation, its values take precedence over `env` values in `acp.json` (and the ACP server ignores Tier-3 `~/.antigravity/settings.json`).

> **Mandatory Wire Protocol Rule (`genai` Only)**: The Antigravity ACP server supports **only** `"wireProtocol": "genai"`. Setting `"openai"` in `admin_settings.json` or `AGY_LLM_GATEWAY_WIRE_PROTOCOL` fails with: `gateway.wireProtocol 'openai' is not supported by the ACP server`.

---

## 2. Official Public Documentation Links

* **Developer Connection Guide — JetBrains IDEs & Zed ACP Setup**:
  * [Connect Antigravity to an Enterprise Gateway — JetBrains IDEs (`#jetbrains-ides`)](https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/connect-enterprise-gateway?hl=en#jetbrains-ides)
  * [Connect Antigravity to an Enterprise Gateway — Zed (`#zed`)](https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/connect-enterprise-gateway?hl=en#zed)
  * [ACP Troubleshooting Table (`#troubleshooting`)](https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/connect-enterprise-gateway?hl=en#troubleshooting)
* **Antigravity IDE Extensions Documentation**:
  * [JetBrains IDEs Extension](https://antigravity.google/docs/ide/extensions/jetbrains/)
  * [Zed Extension](https://antigravity.google/docs/ide/extensions/zed/)

---

## 3. Where These Files Should Go (Target Locations)

| Source Template | Target Surface | Linux Destination Path | macOS Destination Path | Windows Destination Path |
| :--- | :--- | :--- | :--- | :--- |
| [`antigravity-acp-settings.json`](./antigravity-acp-settings.json) | **Both JetBrains & Zed** *(renamed to `settings.json`)* | `/home/<USERNAME>/.gemini/antigravity-acp/settings.json`* | `/Users/<USERNAME>/.gemini/antigravity-acp/settings.json`* | `C:\Users\<USERNAME>\.gemini\antigravity-acp\settings.json`* |
| [`acp.json`](./acp.json) | **JetBrains IDEs** | `/home/<USERNAME>/.jetbrains/acp.json` | `/Users/<USERNAME>/.jetbrains/acp.json` | `C:\Users\<USERNAME>\.jetbrains\acp.json` |
| [`acp.json`](./acp.json) | **Zed Editor** *(merged into `settings.json`)* | `/home/<USERNAME>/.config/zed/settings.json` | `/Users/<USERNAME>/Library/Application Support/Zed/settings.json` | `C:\Users\<USERNAME>\AppData\Roaming\Zed\settings.json` |

*\*Note: Respects `$GEMINI_HOME/antigravity-acp/settings.json` if `GEMINI_HOME` is customized.*

---

## 4. Allowed Keywords & Configuration Reference Tables

### Table A — `~/.gemini/antigravity-acp/settings.json` Keywords

| JSON Key Path | Data Type | Required? | Allowed Values | Description |
| :--- | :--- | :---: | :--- | :--- |
| `auth` | `object` | **Required** | JSON object | Authentication configuration container for the Antigravity ACP server. |
| `auth.type` | `string` | **Required** | `"gateway"` | Turns on Enterprise Gateway routing mode inside the ACP server so JetBrains and Zed do not prompt for interactive browser OAuth sign-in. |

### Table B — `acp.json` (JetBrains) & Zed `settings.json` (`agent_servers`) Keywords

| JSON Key Path | Data Type | Required? | Allowed Values / Example | Description |
| :--- | :--- | :---: | :--- | :--- |
| `agent_servers` | `object` | **Required** | JSON object | Root map of ACP-compatible coding agent servers configured in JetBrains or Zed. |
| `agent_servers.Antigravity` | `object` | **Required** | JSON object | Server definition block for Google Antigravity. |
| `agent_servers.Antigravity.command` | `string` | **Required** | Absolute binary path (e.g., `"/usr/local/bin/agy"`, `"/opt/homebrew/bin/agy_acp_server"`, `"C:\\Program Files\\Antigravity\\bin\\agy.exe"`) | Path to the Antigravity ACP server executable (`agy_acp_server` or `agy` CLI with `"args": ["acp"]`). |
| `agent_servers.Antigravity.args` | `string[]` | Optional | `["acp"]` (when `command` points to `agy`) or `[]` (when `command` points to standalone `agy_acp_server`) | Command-line arguments passed when launching the ACP server process. |
| `agent_servers.Antigravity.env` | `object` (`map<string,string>`) | **Required** *(unless set in `admin_settings.json`)* | `AGY_LLM_GATEWAY_*` key-value map | Environment variables passed directly to the ACP server child process (see below). |
| `...env.AGY_LLM_GATEWAY_URL` | `string` | **Required** | `"https://gateway.corp.example.com"` | HTTPS base URL of your Enterprise Gateway. |
| `...env.AGY_LLM_GATEWAY_API_KEY` | `string` | **Required** | `"agy_live_..."` | Gateway-issued Bearer token for authenticating inference requests. |
| `...env.AGY_LLM_GATEWAY_WIRE_PROTOCOL` | `string` | Optional | **`"genai"` ONLY** | Must be `"genai"` (default). `"openai"` is unsupported by the ACP server. |
| `...env.AGY_LLM_GATEWAY_CA_CERT` | `string` | Optional | `"/etc/ssl/certs/ca-certificates.crt"` | Corporate root CA PEM bundle path (falls back to `SSL_CERT_FILE`). |
| `...env.AGY_LLM_GATEWAY_HEADERS` | `string` | Optional | `"X-Cost-Center: CC-9941-SEC,X-Corporate-BU: DevTools"` | Comma- or newline-separated `KEY: VALUE` custom attribution headers. |
| `...env.AGY_LLM_GATEWAY_MODELS` | `string` | Optional | `"gemini-3.8-flash,gemini-3.7-flash,gemini-3.1-pro-preview"` | Comma-separated list of approved model IDs selectable in the IDE. |

---

## 5. Manual Administrator Commands (Deploy, Set Permissions & Lock)

### A. Linux (Run as `root` / `sudo`)

```bash
DEV_USER="alice"   # <-- Replace with target developer OS username
USER_HOME="$(getent passwd "${DEV_USER}" | cut -d: -f6)"
ACP_AUTH="${USER_HOME}/.gemini/antigravity-acp/settings.json"
JB_ACP="${USER_HOME}/.jetbrains/acp.json"
ZED_CFG="${USER_HOME}/.config/zed/settings.json"

# 1. Unlock existing files if previously locked
sudo chattr -i "${ACP_AUTH}" "${JB_ACP}" "${ZED_CFG}" 2>/dev/null || true

# 2. Create parent directories owned by the developer
sudo mkdir -p "${USER_HOME}/.gemini/antigravity-acp" "${USER_HOME}/.jetbrains" "${USER_HOME}/.config/zed"
sudo chown "${DEV_USER}:${DEV_USER}" \
  "${USER_HOME}/.gemini" "${USER_HOME}/.gemini/antigravity-acp" \
  "${USER_HOME}/.jetbrains" "${USER_HOME}/.config" "${USER_HOME}/.config/zed"

# 3. Install ACP auth settings and JetBrains/Zed ACP server definitions (merging Zed settings if jq exists)
sudo cp -f ./antigravity-acp-settings.json "${ACP_AUTH}"
sudo cp -f ./acp.json "${JB_ACP}"
if [[ -s "${ZED_CFG}" ]] && command -v jq >/dev/null 2>&1; then
  sudo jq -s '.[0] * .[1]' "${ZED_CFG}" ./acp.json > "${ZED_CFG}.tmp" && sudo mv -f "${ZED_CFG}.tmp" "${ZED_CFG}"
else
  sudo cp -f ./acp.json "${ZED_CFG}"
fi

# 4. Set root:root ownership (0644) and lock with chattr +i
sudo chown root:root "${ACP_AUTH}" "${JB_ACP}" "${ZED_CFG}"
sudo chmod 0644 "${ACP_AUTH}" "${JB_ACP}" "${ZED_CFG}"
sudo chattr +i "${ACP_AUTH}" "${JB_ACP}" "${ZED_CFG}"

# 5. Verify locks
sudo lsattr "${ACP_AUTH}" "${JB_ACP}" "${ZED_CFG}"
```

*To unlock later on Linux:*
```bash
sudo chattr -i "/home/${DEV_USER}/.gemini/antigravity-acp/settings.json" \
               "/home/${DEV_USER}/.jetbrains/acp.json" \
               "/home/${DEV_USER}/.config/zed/settings.json"
```

### B. macOS (Run as `root` / `sudo` or via Jamf / Kandji)

```bash
DEV_USER="alice"   # <-- Replace with target macOS developer username
USER_HOME="/Users/${DEV_USER}"
ACP_AUTH="${USER_HOME}/.gemini/antigravity-acp/settings.json"
JB_ACP="${USER_HOME}/.jetbrains/acp.json"
ZED_CFG="${USER_HOME}/Library/Application Support/Zed/settings.json"

# 1. Remove macOS system-immutable flags if present
sudo chflags noschg,nouchg "${ACP_AUTH}" "${JB_ACP}" "${ZED_CFG}" 2>/dev/null || true

# 2. Create parent directories owned by developer:staff
sudo mkdir -p "${USER_HOME}/.gemini/antigravity-acp" "${USER_HOME}/.jetbrains" "${USER_HOME}/Library/Application Support/Zed"
sudo chown "${DEV_USER}:staff" "${USER_HOME}/.gemini" "${USER_HOME}/.gemini/antigravity-acp" \
  "${USER_HOME}/.jetbrains" "${USER_HOME}/Library/Application Support/Zed"

# 3. Install ACP configs (adjusting macOS CA bundle path to /etc/ssl/cert.pem)
sudo cp -f ./antigravity-acp-settings.json "${ACP_AUTH}"
sed 's|/etc/ssl/certs/ca-certificates.crt|/etc/ssl/cert.pem|g' ./acp.json | sudo tee "${JB_ACP}" "${ZED_CFG}" >/dev/null

# 4. Set root:wheel ownership (0644) and lock with chflags schg
sudo chown root:wheel "${ACP_AUTH}" "${JB_ACP}" "${ZED_CFG}"
sudo chmod 0644 "${ACP_AUTH}" "${JB_ACP}" "${ZED_CFG}"
sudo chflags schg "${ACP_AUTH}" "${JB_ACP}" "${ZED_CFG}"

# 5. Verify 'schg' flags
ls -lO "${ACP_AUTH}" "${JB_ACP}" "${ZED_CFG}"
```

*To unlock later on macOS:*
```bash
sudo chflags noschg,nouchg "/Users/${DEV_USER}/.gemini/antigravity-acp/settings.json" \
                           "/Users/${DEV_USER}/.jetbrains/acp.json" \
                           "/Users/${DEV_USER}/Library/Application Support/Zed/settings.json"
```

### C. Windows 10 / 11 / Server (Run in Elevated Administrator PowerShell)

```powershell
$DevUser  = "alice"   # <-- Replace with target Windows username
$UserHome = "C:\Users\$DevUser"
$AcpAuth  = "$UserHome\.gemini\antigravity-acp\settings.json"
$JbAcp    = "$UserHome\.jetbrains\acp.json"
$ZedCfg   = "$UserHome\AppData\Roaming\Zed\settings.json"

# 1. Unlock existing files if present
foreach ($File in @($AcpAuth, $JbAcp, $ZedCfg)) {
    if (Test-Path -LiteralPath $File) {
        attrib.exe -R $File
        icacls.exe $File /remove:d $DevUser | Out-Null
        icacls.exe $File /grant "${DevUser}:(M)" | Out-Null
    }
}

# 2. Create parent directories and adapt binary path to Windows agy.exe
New-Item -ItemType Directory -Force -Path "$UserHome\.gemini\antigravity-acp", "$UserHome\.jetbrains", "$UserHome\AppData\Roaming\Zed" | Out-Null
Copy-Item -LiteralPath ".\antigravity-acp-settings.json" -Destination $AcpAuth -Force
$WinAcp = (Get-Content -LiteralPath ".\acp.json" -Raw) -replace '/usr/local/bin/agy', 'C:\\Program Files\\Antigravity\\bin\\agy.exe'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($JbAcp,  $WinAcp, $Utf8NoBom)
[System.IO.File]::WriteAllText($ZedCfg, $WinAcp, $Utf8NoBom)

# 3. Lock all three files with Administrator ownership + NTFS Deny Write/Delete ACL
foreach ($File in @($AcpAuth, $JbAcp, $ZedCfg)) {
    takeown.exe /F $File /A | Out-Null
    icacls.exe $File /inheritance:r `
        /grant:r "SYSTEM:(F)" `
        /grant:r "Administrators:(F)" `
        /grant:r "${DevUser}:(R)" `
        /deny "${DevUser}:(WD,AD,WEA,WA,DE,WDAC,WO)" | Out-Null
    attrib.exe +R $File
    icacls.exe $File
}
```

*To unlock later on Windows:*
```powershell
foreach ($File in @(
    "C:\Users\$DevUser\.gemini\antigravity-acp\settings.json",
    "C:\Users\$DevUser\.jetbrains\acp.json",
    "C:\Users\$DevUser\AppData\Roaming\Zed\settings.json"
)) {
    attrib.exe -R $File
    icacls.exe $File /remove:d $DevUser | Out-Null
}
```
