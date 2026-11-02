# `config.json` — Antigravity Desktop App & Web Hub Global Security Configuration

## 1. What This File Is Used For

[`config.json`](./config.json) (`~/.gemini/config/config.json`) is the **global user settings and permission grants backing store** for the **Antigravity Desktop Application (`antigravity` `2.15.0+`)** and **Antigravity Web Hub (`agy --hub`)**.

In addition, **Antigravity CLI (`agy`)** also reads `userSettings.globalPermissionGrants` from `~/.gemini/config/config.json` via `CliSettingsStore.GetGlobalPermissionGrants` and merges those rules into its global permission evaluation alongside [`~/.gemini/antigravity-cli/settings.json`](../02-cli-settings/README.md).

When deployed and kernel-locked by an enterprise administrator, [`config.json`](./config.json) enforces:
1. **Desktop Terminal Sandbox Isolation (`userSettings.enableTerminalSandbox: true`)**: Forces all agent-launched commands inside the Desktop App and Hub into OS kernel namespaces (Linux) or Seatbelt `sandbox-exec` containers (macOS).
2. **Sandbox-Scoped Command Execution (`userSettings.autoExecutionPolicy: "CASCADE_COMMANDS_AUTO_EXECUTION_PROCEED_IN_SANDBOX"`)**: Equivalent to CLI `toolPermission: "proceed-in-sandbox"` — commands execute automatically *only* inside the isolated sandbox, and pause for explicit human approval if host access is requested.
3. **Outbound Sandbox Network Lock (`userSettings.sandboxAllowNetwork: false`)**: Disables unrestricted outbound internet sockets from sandboxed terminal processes, restricting connectivity strictly to domains permitted by `read_url(...)` grants.
4. **Browser JavaScript Execution Disabled (`userSettings.browserJsExecutionPolicy: "BROWSER_JS_EXECUTION_POLICY_DISABLED"`)**: Blocks the Browser Subagent from evaluating arbitrary JavaScript on visited pages unless overridden by policy.
5. **Mandatory Artifact Review (`userSettings.artifactReviewMode: "ARTIFACT_REVIEW_MODE_ALWAYS"`)**: Requires human approval on implementation plans before autonomous code execution proceeds.
6. **595+ Global Permission Grants (`userSettings.globalPermissionGrants`)**: Mirrors the exact `allow`, `ask`, and `deny` rules enforced in CLI `settings.json` so Desktop App, Web Hub, VS Code, Visual Studio, and CLI share one rule set (live-verified 2026-11: the CLI merges these rules but ignores this file's App mode keys such as `enableTerminalSandbox`, `autoExecutionPolicy` and `nonWorkspaceFileAccessPolicy`; JetBrains/Zed ignore this file entirely).

> **Tip — Preserving Installed Plugins During Deployment**: `~/.gemini/config/config.json` can also store non-security Desktop metadata (such as enabled plugin state). On workstations where developers already have an existing `config.json`, merge `userSettings` safely using `jq -s '.[0] * .[1]' existing.json config.json` before applying `chattr +i` / `chflags schg` (shown in Section 5 below).

---

## 2. Official Public Documentation Links

* **Antigravity App Global Settings & Permission Presets**:
  * [Settings — Antigravity App (`#settings-architecture`)](https://antigravity.google/docs/settings/#settings-architecture)
  * [Agent Settings — Enterprise & Previous Permission Settings (`#previous-permission-settings`)](https://antigravity.google/docs/agent-settings/#previous-permission-settings)
* **Desktop Terminal Sandbox & Network Isolation**:
  * [Terminal Sandbox — Antigravity App](https://antigravity.google/docs/sandbox/)
* **Global Permission Grants (`Allow / Ask / Deny` Rules & `action(target)` Syntax)**:
  * [Agent Permissions — Antigravity App](https://antigravity.google/docs/permissions/)

---

## 3. Where This File Should Go (Target Locations)

Before deploying manually, replace `__DEV_USER__` in [`config.json`](./config.json) with the target developer's OS username (and `/home/__DEV_USER__` with `/Users/<USERNAME>` on macOS or `C:/Users/<USERNAME>` on Windows).

| Operating System | Primary Target Path | Legacy Fallback Mirror Path* | File Owner & Mode | Immutability Lock |
| :--- | :--- | :--- | :--- | :--- |
| **Linux** | `/home/<USERNAME>/.gemini/config/config.json` | `/home/<USERNAME>/.gemini/config.json` | `root:root` (`0644` or `0444`) | `chattr +i` |
| **macOS** | `/Users/<USERNAME>/.gemini/config/config.json` | `/Users/<USERNAME>/.gemini/config.json` | `root:wheel` (`0644` or `0444`) | `chflags schg` |
| **Windows** | `C:\Users\<USERNAME>\.gemini\config\config.json` | `C:\Users\<USERNAME>\.gemini\config.json` | `Administrators` (`ReadOnly`) | `icacls /deny "<USERNAME>:(WD,AD,WEA,WA,DE,WDAC,WO)"` + `attrib +R` |

*\*Note: Older Desktop/Hub builds checked `~/.gemini/config.json`, while current `2.15.0+` releases use `~/.gemini/config/config.json`. Our automated deployment scripts install and lock both paths to prevent version-downgrade or path-fallback bypasses.*

---

## 4. Allowed Keywords & Configuration Reference Tables

### Table A — `config.json` (`userSettings`) Keywords & Enumerated Values

| JSON Key Path | Data Type | Default Value | Allowed Enum / Format Values | Description |
| :--- | :--- | :--- | :--- | :--- |
| `userSettings` | `object` | `{}` | JSON object | Top-level container for Antigravity Desktop App and Web Hub global user preferences and security policies. |
| `userSettings.enableTerminalSandbox` | `boolean` | `false` *(Enterprise)* / `true` *(Default preset)* | `true` \| `false` | Enables OS-level terminal sandboxing (Linux namespaces / macOS Seatbelt `sandbox-exec` / Windows 11 24H2+ AppContainer) for all agent shell commands. |
| `userSettings.sandboxAllowNetwork` | `boolean` | `false` | `true` \| `false` | Controls whether sandboxed terminal commands are permitted general outbound network access (`false` restricts outbound sockets strictly to `read_url(...)` allowlisted domains). |
| `userSettings.autoExecutionPolicy` | `string` (Proto Enum) | `"CASCADE_COMMANDS_AUTO_EXECUTION_OFF"` | • `"CASCADE_COMMANDS_AUTO_EXECUTION_OFF"` *(Require Review)*<br>• `"CASCADE_COMMANDS_AUTO_EXECUTION_PROCEED_IN_SANDBOX"` *(Proceed in Sandbox — **Recommended**)*<br>• `"CASCADE_COMMANDS_AUTO_EXECUTION_EAGER"` *(Always Proceed / Turbo)* | Controls terminal command auto-execution in Enterprise/Business mode (`Settings > General > Agent Settings > Terminal Command Auto Execution`). |
| `userSettings.permissionPreset` | `string` (Proto Enum) | `"AGENT_PERMISSION_PRESET_DEFAULT"` | • `"AGENT_PERMISSION_PRESET_REQUEST_REVIEW"` *(Sandbox Off, Always Ask)*<br>• `"AGENT_PERMISSION_PRESET_DEFAULT"` *(Sandbox On, Allowed in Sandbox)*<br>• `"AGENT_PERMISSION_PRESET_AUTO"` *(Preview; non-enterprise only)*<br>• `"AGENT_PERMISSION_PRESET_TURBO"` *(Unrestricted — avoid in enterprise)* | Global permission preset in the updated Desktop permission UI (`Settings > General > Global Permissions > Permission Preset`). |
| `userSettings.artifactReviewMode` | `string` (Proto Enum) | `"ARTIFACT_REVIEW_MODE_ALWAYS"` | • `"ARTIFACT_REVIEW_MODE_ALWAYS"` *(Always Ask for Review)*<br>• `"ARTIFACT_REVIEW_MODE_AGENT_DECIDES"` *(Model Decides)*<br>• `"ARTIFACT_REVIEW_MODE_TURBO"` *(Always Proceed without waiting)* | Controls whether the Desktop agent stops and waits for developer approval on implementation plans and executable artifacts. |
| `userSettings.browserJsExecutionPolicy` | `string` (Proto Enum) | `"BROWSER_JS_EXECUTION_POLICY_ALWAYS_ASK"` | • `"BROWSER_JS_EXECUTION_POLICY_DISABLED"` *(Block JS execution — **Recommended**)*<br>• `"BROWSER_JS_EXECUTION_POLICY_ALWAYS_ASK"` *(Prompt user every time)*<br>• `"BROWSER_JS_EXECUTION_POLICY_MODEL_DECIDES"` *(Allow autonomous JS)* | Controls whether the built-in Browser Subagent can execute arbitrary JavaScript inside Chrome tabs. |
| `userSettings.nonWorkspaceFileAccessPolicy` | `string` (Proto Enum) | `"AGENT_SETTING_POLICY_DENY"` | • `"AGENT_SETTING_POLICY_DENY"` *(Always Deny outside workspace)*<br>• `"AGENT_SETTING_POLICY_ASK"` *(Always Ask)*<br>• `"AGENT_SETTING_POLICY_ALLOW"` *(Always Allow)* | Controls access to files outside open project folders (`Outside of folder file access policy`). |
| `userSettings.internetAccessPolicy` | `string` (Proto Enum) | `"AGENT_SETTING_POLICY_ASK"` | • `"AGENT_SETTING_POLICY_DENY"`<br>• `"AGENT_SETTING_POLICY_ASK"`<br>• `"AGENT_SETTING_POLICY_ALLOW"` | Baseline policy for outbound web/internet fetches when no explicit `read_url(...)` rule matches. |
| `userSettings.globalPermissionGrants` | `object` | `{}` | `{"allow": string[], "ask": string[], "deny": string[]}` | Fine-grained global permission rules backing `Settings > General > Global Permissions` (see **Table B** below). |

### Table B — `userSettings.globalPermissionGrants` Rule Lists & Selectors

| Key Path | Data Type | Precedence Rank | Supported `action(target)` Selectors | Description |
| :--- | :--- | :---: | :--- | :--- |
| `userSettings.globalPermissionGrants.deny` | `string[]` | **1 (Highest)** | `command(...)`, `unsandboxed(...)`, `read_file(...)`, `write_file(...)`, `read_url(...)`, `execute_url(...)`, `mcp(...)` | Permanently blocks matching operations immediately across Desktop App, Web Hub, and CLI. Cannot be overridden by project settings or `allow`/`ask` rules. |
| `userSettings.globalPermissionGrants.ask` | `string[]` | **2 (Medium)** | Same 7 selectors | Forces an interactive confirmation card in the Desktop/Hub UI before executing the matching tool call, even if covered by a broader `allow` rule or sandbox auto-execution. |
| `userSettings.globalPermissionGrants.allow` | `string[]` | **3 (Lowest)** | Same 7 selectors | Auto-approves matching safe operations without prompting (and mounts `read_file`/`write_file` paths and `read_url` domains into the OS sandbox). |

---

## 5. Manual Administrator Commands (Deploy, Set Permissions & Lock)

### A. Linux (Run as `root` / `sudo`)

```bash
DEV_USER="alice"   # <-- Replace with target developer OS username
USER_HOME="$(getent passwd "${DEV_USER}" | cut -d: -f6)"
PRIMARY_FILE="${USER_HOME}/.gemini/config/config.json"
LEGACY_FILE="${USER_HOME}/.gemini/config.json"

# 1. Unlock existing files if previously locked with chattr +i
sudo chattr -i "${PRIMARY_FILE}" "${LEGACY_FILE}" 2>/dev/null || true

# 2. Ensure parent directories exist and are owned by the developer
sudo mkdir -p "${USER_HOME}/.gemini/config"
sudo chown "${DEV_USER}:${DEV_USER}" "${USER_HOME}/.gemini" "${USER_HOME}/.gemini/config"

# 3. Render __DEV_USER__ placeholders and merge safely with any existing config.json via jq (if installed)
TMP_RENDERED="$(mktemp)"
sed -e "s|/home/__DEV_USER__|${USER_HOME}|g" -e "s|__DEV_USER__|${DEV_USER}|g" ./config.json > "${TMP_RENDERED}"

if [[ -s "${PRIMARY_FILE}" ]] && command -v jq >/dev/null 2>&1; then
  sudo jq -s '.[0] * .[1]' "${PRIMARY_FILE}" "${TMP_RENDERED}" > "${TMP_RENDERED}.merged"
  sudo cp -f "${TMP_RENDERED}.merged" "${PRIMARY_FILE}"
else
  sudo cp -f "${TMP_RENDERED}" "${PRIMARY_FILE}"
fi
sudo cp -f "${PRIMARY_FILE}" "${LEGACY_FILE}"
rm -f "${TMP_RENDERED}" "${TMP_RENDERED}.merged"

# 4. Set root:root ownership, read-only mode, and Linux kernel immutable flag
sudo chown root:root "${PRIMARY_FILE}" "${LEGACY_FILE}"
sudo chmod 0644 "${PRIMARY_FILE}" "${LEGACY_FILE}"
sudo chattr +i "${PRIMARY_FILE}" "${LEGACY_FILE}"

# 5. Verify ownership and 'i' immutable attribute
ls -la "${PRIMARY_FILE}" "${LEGACY_FILE}"
sudo lsattr "${PRIMARY_FILE}" "${LEGACY_FILE}"
```

*To unlock later for admin edits on Linux:*
```bash
sudo chattr -i "/home/${DEV_USER}/.gemini/config/config.json" "/home/${DEV_USER}/.gemini/config.json"
```

### B. macOS (Run as `root` / `sudo` or via Jamf / Kandji)

```bash
DEV_USER="alice"   # <-- Replace with target macOS developer username
USER_HOME="/Users/${DEV_USER}"
PRIMARY_FILE="${USER_HOME}/.gemini/config/config.json"
LEGACY_FILE="${USER_HOME}/.gemini/config.json"

# 1. Clear macOS system-immutable flags if present
sudo chflags noschg,nouchg "${PRIMARY_FILE}" "${LEGACY_FILE}" 2>/dev/null || true

# 2. Ensure parent directories exist and belong to developer:staff
sudo mkdir -p "${USER_HOME}/.gemini/config"
sudo chown "${DEV_USER}:staff" "${USER_HOME}/.gemini" "${USER_HOME}/.gemini/config"

# 3. Render __DEV_USER__ placeholders and install
sed -e "s|/Users/__DEV_USER__|${USER_HOME}|g" -e "s|__DEV_USER__|${DEV_USER}|g" ./config.json \
  | sudo tee "${PRIMARY_FILE}" "${LEGACY_FILE}" >/dev/null

# 4. Set root:wheel ownership, 0644 mode, and macOS schg immutable flag
sudo chown root:wheel "${PRIMARY_FILE}" "${LEGACY_FILE}"
sudo chmod 0644 "${PRIMARY_FILE}" "${LEGACY_FILE}"
sudo chflags schg "${PRIMARY_FILE}" "${LEGACY_FILE}"

# 5. Verify ownership and 'schg' flag
ls -lO "${PRIMARY_FILE}" "${LEGACY_FILE}"
```

*To unlock later for admin edits on macOS:*
```bash
sudo chflags noschg,nouchg "/Users/${DEV_USER}/.gemini/config/config.json" "/Users/${DEV_USER}/.gemini/config.json"
```

### C. Windows 10 / 11 / Server (Run in Elevated Administrator PowerShell)

```powershell
$DevUser     = "alice"   # <-- Replace with target Windows username
$UserHome    = "C:\Users\$DevUser"
$ForwardHome = $UserHome -replace '\\', '/'
$PrimaryFile = "$UserHome\.gemini\config\config.json"
$LegacyFile  = "$UserHome\.gemini\config.json"

# 1. Unlock existing files if present
foreach ($File in @($PrimaryFile, $LegacyFile)) {
    if (Test-Path -LiteralPath $File) {
        attrib.exe -R $File
        icacls.exe $File /remove:d $DevUser | Out-Null
        icacls.exe $File /grant "${DevUser}:(M)" | Out-Null
    }
}

# 2. Create parent directory and render __DEV_USER__ placeholders
New-Item -ItemType Directory -Force -Path "$UserHome\.gemini\config" | Out-Null
$Raw = Get-Content -LiteralPath ".\config.json" -Raw
$Rendered = ($Raw -replace '/home/__DEV_USER__', $ForwardHome) -replace '__DEV_USER__', $DevUser
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($PrimaryFile, $Rendered, $Utf8NoBom)
[System.IO.File]::WriteAllText($LegacyFile,  $Rendered, $Utf8NoBom)

# 3. Lock both files with Administrator ownership + NTFS Deny Write/Delete ACE
foreach ($File in @($PrimaryFile, $LegacyFile)) {
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

*To unlock later for admin edits on Windows:*
```powershell
foreach ($File in @("C:\Users\$DevUser\.gemini\config\config.json", "C:\Users\$DevUser\.gemini\config.json")) {
    attrib.exe -R $File
    icacls.exe $File /remove:d $DevUser | Out-Null
}
```
