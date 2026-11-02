# `settings.json` — Antigravity CLI Global Security & Sandbox Profile

## 1. What This File Is Used For

[`settings.json`](./settings.json) (`~/.gemini/antigravity-cli/settings.json`) is the **global configuration, terminal sandbox, and fine-grained tool permissions profile** for **Antigravity CLI (`agy`)** only.

> [!IMPORTANT]
> Live verification (2026-11, CLI 1.4.12, VS Code extension 1.10.0) showed that **VS Code and Visual Studio don't read this file**: the extension starts `agy --hub --app_data_dir=antigravity`, which uses the App's settings store and reads `~/.gemini/config/config.json`. Put rules every surface must enforce in [`config.json`](../03-desktop-hub-config/README.md) `userSettings.globalPermissionGrants` (the CLI merges those too). In CLI 1.4.12, `ask` rules aren't enforced (an `allow` for the same command wins), and `agy --settings '{...}'` can drop this file's deny rules for a session; deny rules in `config.json` survive both. See [`verification/`](../../verification/README.md).

When deployed and kernel-locked by an enterprise administrator, this file enforces:
1. **Mandatory OS Terminal Sandboxing (`enableTerminalSandbox: true`)**: Isolates agent-executed shell commands inside Linux kernel namespaces (`exebox`) or macOS Seatbelt (`sandbox-exec` SBPL) profiles (and Windows 11 24H2+ AppContainer process security environments).
2. **Scoped Tool Approval Policy (`toolPermission: "proceed-in-sandbox"`)**: Allows explicitly safe commands to run inside the isolated sandbox while forcing interactive human review whenever a command requests host-level (`unsandboxed`) execution.
3. **Plan-First Execution Mode (`agentMode: "plan"`, `artifactReviewPolicy: "asks-for-review"`)**: Requires the agent to outline an implementation plan and wait for developer approval before mutating files.
4. **Strict Workspace Containment (`allowNonWorkspaceAccess: false`)**: Blocks reading or modifying files outside active workspace folders unless explicitly granted in `permissions.allow`.
5. **595+ Fine-Grained `Allow / Ask / Deny` Rules (`permissions`)**: Enforces `Deny > Ask > Allow` precedence across 7 resource selectors (`command`, `unsandboxed`, `read_file`, `write_file`, `read_url`, `execute_url`, `mcp`), blocking file deletion (`rm`, `shred`, `Remove-Item`, `git clean -fd`), credential theft (`.ssh`, `.aws`, `.kube`, `/etc/shadow`, `.pem`, `.env`), privilege escalation (`sudo`, `chattr`, `chflags`, `icacls`), lateral movement (`ssh`, `scp`, `nc`), and cloud metadata SSRF (`169.254.169.254`).

### Critical Operational & Security Caveats

* **Caveat 1 — Never put `"unsandboxed(*)"` in `permissions.deny`**: Due to V1 `Covers` semantics, an `unsandboxed(...)` deny rule covers *both* unsandboxed and sandboxed command requests, breaking all sandboxed terminal execution. Use `"enableTerminalSandbox": true` + `"toolPermission": "proceed-in-sandbox"` instead.
* **Caveat 2 — POSIX Absolute Paths Only in `read_file` / `write_file`**: On Linux/macOS, `exebox` translates file rules into kernel bind mounts and fails if a path is relative, contains `*` globs, or starts with a Windows drive letter (`C:\...`). Also **never** put root OS directories (`write_file(/usr)`, `write_file(/bin)`, `write_file(/etc)`) in `permissions.deny` on Linux because `/` is already read-only inside `exebox` and a deny mount on `/usr` or `/bin` hides `/usr/bin/bash`.
* **Caveat 3 — Normalize via `agy --version` (`MarshalSparse`) Before Kernel Locking**: Antigravity CLI normalizes `settings.json` on startup using sparse persistence (writing only keys that differ from defaults). If `chattr +i` / `chflags schg` is applied *before* normalization, startup hits `EPERM` during rewrite and aborts sandbox initialization. Always run `su - <DEV_USER> -c "agy --version"` once **before** locking the file!
* **Caveat 4 — Allow Reading `~/.gemini` for Lazy MCP Schemas**: When `allowNonWorkspaceAccess: false` is set, include `"read_file(/home/<DEV_USER>/.gemini)"` in `permissions.allow` while keeping `"write_file(/home/<DEV_USER>/.gemini)"` in `permissions.deny` so the agent can read lazy-loaded MCP tool JSON schemas.
* **Caveat 5 — Kernel Immutability Is Mandatory**: Because the developer owns `~/.gemini/antigravity-cli/`, `chown root:root` + `chmod 0444` alone can be bypassed via `mv -f` atomic file replacement (`rename()`). Always apply `chattr +i` (Linux), `chflags schg` (macOS), or explicit `icacls /deny (WD,AD,WEA,WA,DE,WDAC,WO)` (Windows).

---

## 2. Official Public Documentation Links

* **Complete `settings.json` Keys & CLI Flags Table**:
  * [CLI Commands & Configuration Keys (`#configuration-keys-settingsjson`)](https://antigravity.google/docs/cli/reference/#configuration-keys-settingsjson)
* **How the CLI Reads, Normalizes (`MarshalSparse`), and Saves `settings.json`**:
  * [Antigravity Settings — CLI Tab (`?tab=cli`)](https://antigravity.google/docs/settings/?tab=cli)
  * [Object Settings (`permissions`, `statusLine`, `title`, `sandboxProxy`)](https://antigravity.google/docs/settings/#object-settings)
* **Terminal Sandbox Architecture & Escape Hatches**:
  * [Terminal Sandbox (`?tab=cli`)](https://antigravity.google/docs/sandbox/?tab=cli)
* **Fine-Grained `Allow / Ask / Deny` Permission Matching Rules**:
  * [Agent Permissions (`?tab=cli`)](https://antigravity.google/docs/permissions/?tab=cli)
  * [Agent Execution & Permission Settings](https://antigravity.google/docs/agent-settings/?tab=cli)

---

## 3. Where This File Should Go (Target Locations)

Before deploying manually, replace `__DEV_USER__` in [`settings.json`](./settings.json) with the developer's actual OS username (and `/home/__DEV_USER__` with `/Users/<USERNAME>` on macOS or `C:/Users/<USERNAME>` on Windows).

| Operating System | Exact Target File Path | Parent Dir Owner | File Owner & Mode | Immutability Lock |
| :--- | :--- | :--- | :--- | :--- |
| **Linux** | `/home/<USERNAME>/.gemini/antigravity-cli/settings.json` | `<USERNAME>:<USERNAME>` (`0755`) | `root:root` (`0644` or `0444`) | `chattr +i` *(after `agy --version`)* |
| **macOS** | `/Users/<USERNAME>/.gemini/antigravity-cli/settings.json` | `<USERNAME>:staff` (`0755`) | `root:wheel` (`0644` or `0444`) | `chflags schg` *(after `agy --version`)* |
| **Windows** | `C:\Users\<USERNAME>\.gemini\antigravity-cli\settings.json` | `<USERNAME>` | `Administrators` (`ReadOnly`) | `icacls /deny "<USERNAME>:(WD,AD,WEA,WA,DE,WDAC,WO)"` + `attrib +R` |

> **Important Note on Hooks & MCP**: `~/.gemini/antigravity-cli/settings.json` does **not** load lifecycle hooks or MCP servers. Global hooks belong in [`~/.gemini/config/hooks.json`](../06-lifecycle-hooks/README.md) and MCP servers belong in [`~/.gemini/config/mcp_config.json`](../05-mcp-config/README.md).

---

## 4. Allowed Keywords & Configuration Reference Tables

### Table A — All Top-Level Keywords Allowed in `~/.gemini/antigravity-cli/settings.json`

| Option Key Name | Data Type | System Default | Allowed Values / Schema | Description |
| :--- | :--- | :--- | :--- | :--- |
| `$schema` | `string` | — | `"https://antigravity.google/schemas/v1/settings.json"` | Optional JSON Schema URL enabling IDE autocomplete and hover validation. Ignored and preserved by `agy`. |
| `agentMode` | `string` | `""` (`default`) | `""` \| `"accept-edits"` \| `"auto"` \| `"plan"` | Startup execution mode. `""` prompts for diff review; `"accept-edits"` auto-approves workspace edits; `"plan"` outlines an implementation plan before edits; `"auto"` (Preview; non-enterprise accounts only) auto-evaluates commands. Overridable per session via `--mode` unless restricted. |
| `toolPermission` | `string` | `"request-review"` | `"request-review"` \| `"proceed-in-sandbox"` \| `"always-proceed"` \| `"strict"` | Global tool safety preset. `"request-review"` prompts for write/bash/web/MCP unless allowed; `"proceed-in-sandbox"` auto-runs sandboxed commands and asks outside sandbox; `"strict"` prompts before every action (even allowed ones); `"always-proceed"` auto-runs unless Ask/Deny matches. **Deny rules apply in every mode.** |
| `enableTerminalSandbox` | `boolean` | `false` | `true` \| `false` | Restricts agent-launched shell commands to OS containment boundaries (Linux namespaces, macOS `sandbox-exec`, Windows 11 24H2+ AppContainer). Set to `true` for enterprise hardening. |
| `allowNonWorkspaceAccess` | `boolean` | `false` | `true` \| `false` | Controls whether the agent can read/edit files outside active workspace directories, subject to `permissions`. Keep `false` on enterprise workstations. |
| `artifactReviewPolicy` | `string` | `"asks-for-review"` | `"asks-for-review"` \| `"agent-decides"` \| `"always-proceed"` | Controls whether the agent pauses when requesting feedback on an artifact (e.g., implementation plan). |
| `permissions` | `object` | `{}` | `{"allow": string[], "ask": string[], "deny": string[]}` | Fine-grained `action(target)` tool access lists evaluated strictly in `Deny > Ask > Allow` priority order (see **Table B** below). |
| `sandboxProxy` | `object` | — | `{"http": {"address": "host:port", "certFile": "/path/single-root-ca.pem", "username": "...", "password": "..."}}` | Routes outbound network traffic from sandboxed terminal commands through your corporate HTTP proxy instead of the built-in proxy (`address` and `certFile` must both be set; **`certFile` must contain a single PEM X.509 certificate**, not a multi-cert bundle like `/etc/ssl/certs/ca-certificates.crt`, or `localcert` rejects it with `trailing data after certificate`). |
| `colorScheme` | `string` | `"terminal"` | `"terminal"` \| `"light"` \| `"solarized light"` \| `"colorblind-friendly light"` \| `"dark"` \| `"solarized dark"` \| `"colorblind-friendly dark"` \| `"tokyo night"` | Visual TUI color theme (`"terminal"` inherits host terminal ANSI palette). |
| `altScreenMode` | `string` | `"default"` | `"default"` \| `"always"` \| `"never"` | Terminal screen buffer behavior: `"default"` (inline chat + alt-screen diff/help overlays), `"always"` (full-screen TUI), `"never"` (strictly inline stdout; available only in `settings.json`). |
| `verbosity` | `string` | `"medium"` | `"high"` \| `"medium"` \| `"low"` | Controls TUI detail level (`"high"` shows all thoughts/tools; `"medium"` groups thoughts; `"low"` shows responses + token summary). |
| `runningLightSpeed` | `string` | `"medium"` | `"fast"` \| `"medium"` \| `"slow"` \| `"off"` | Speed of the TUI progress animation bar. |
| `notifications` | `boolean` | `false` | `true` \| `false` | Rings terminal bell and triggers desktop notification when agent awaits approval or finishes a turn. |
| `showTips` | `boolean` | `true` | `true` \| `false` | Displays usage tips while responses generate. |
| `showFeedbackSurvey` | `boolean` | `true` | `true` \| `false` | Displays periodic post-task quality feedback surveys. |
| `editor` | `string` | `"auto"` | `"auto"` \| `"vim"` \| `"emacs"` \| `<custom_cmd>` | External editor binary launched for `Ctrl+G` prompt composition and `/open`. |
| `editorMode` | `string` | `"default"` | `"default"` \| `"vim"` | Keymap inside the TUI prompt input box (`"default"` standard editing or `"vim"` modal editing). |
| `vimInsertFirst` | `boolean` | `false` | `true` \| `false` | When `editorMode` is `"vim"`, starts prompt in Insert mode and submits on bare `Enter`. |
| `copyOnSelect` | `boolean` | `true` | `true` \| `false` | Copies mouse-selected text to clipboard automatically in `altScreenMode`. |
| `hideActiveItems` | `boolean` | `false` | `true` \| `false` | Hides the active subagents / background tasks bar beneath the prompt box. |
| `pickerGrouping` | `string` | `"none"` | `"none"` \| `"grouped"` | Controls `/resume` session picker layout (`"none"` chronological or `"grouped"` by workspace). |
| `queuedMessages` | `string` | `"queue"` | `"queue"` \| `"send-immediately"` | Behavior when typing while agent works (`"queue"` waits for turn end; `"send-immediately"` interrupts). |
| `clearScrollbackOnResize` | `boolean` | `true` | `true` \| `false` | Clears terminal scrollback buffer when redrawing inline conversation on window resize (`settings.json` only). |
| `disableSlashCommands` | `boolean` | `false` | `true` \| `false` | In headless print mode (`-p`), treats leading `/` literally instead of expanding slash commands/skills. |
| `historySize` | `integer` | `2000` | `-1` (unlimited), `0` (disable), or positive integer | Number of prompt history entries retained on disk at CLI exit. |
| `useTerminalCursor` | `boolean` | `false` | `true` \| `false` | Uses native terminal cursor shape instead of TUI block cursor. |
| `useG1Credits` | `boolean` | `false` | `true` \| `false` | Uses Google One AI credits when consumer quota runs out *(not applicable to Enterprise/Gateway accounts)*. |
| `model` | `string` | `""` | Model label string | Persisted `/model` selection *(overridden/constrained by `admin_settings.json` `models` catalog in Gateway mode)*. |
| `modelProvider` | `string` | `""` | `""` \| `"gemini"` | Direct `GEMINI_API_KEY` mode *(leave unset `""` when using Enterprise Gateway)*. |
| `trustedWorkspaces` | `string[]` | `[]` | Array of absolute directory paths | Workspace directories trusted by the user. |
| `statusLine` | `object` | — | `{"command": string, "type": "command", "enabled": bool, "padding": int, "stack_with_default": bool}` | Custom shell script rendering the TUI status bar from session JSON on `stdin`. |
| `title` | `object` | — | `{"command": string, "type": "command", "enabled": bool}` | Custom shell script setting the terminal window title from session JSON on `stdin`. |
| `customModelsConfig` | `object` | — | `{"customModels": [{"modelName": "...", "label": "..."}]}` | Extra models for direct `GEMINI_API_KEY` mode *(ignored in Enterprise Gateway mode)*. |
| `gcp` | `object` | — | `{"project": string, "location": "global"\|"us"\|"eu"}` | Saved project metadata for interactive Google Cloud OAuth *(ignored in Enterprise Gateway mode)*. |

### Table B — `permissions.{allow,ask,deny}` Action Selectors & Target Syntax

Every entry inside `permissions.allow`, `permissions.ask`, and `permissions.deny` uses `action(target)` with **no space** before `(`. Priority is strictly **`Deny > Ask > Allow`**.

| Action Selector | Target Syntax Examples | Matching Semantics & Sandbox Integration |
| :--- | :--- | :--- |
| `command(...)` | `command(git status)`<br>`command(regex:^git\s+status(\s+[^;&\|`$()\r\n>]*)?$)`<br>`command(regex:^(\S*[/\\])?rm(\.exe)?(\s+.*\|$))` | On Linux/macOS (`bash`/`zsh`), literal rules match whitespace-split token prefixes (`["git", "status", ...]`). On **Windows PowerShell** (`powershell`/`pwsh`) or when shell substitutions (`$(...)`) are present, `RequiresExactMatch` is `true`, so literal rules match only the exact raw string; pair literal rules with anchored `command(regex:...)` patterns for cross-OS allow/ask/deny enforcement. |
| `unsandboxed(...)` | `unsandboxed(docker build)`<br>`unsandboxed(regex:docker compose .*)` | *(Enterprise/Business accounts)* Grants or prompts for host-level execution **outside** the OS terminal sandbox. **Never** place `unsandboxed(*)` in `deny` (blocks sandboxed commands too). On Windows hosts without native sandbox support, pair approved `command(...)` allow entries with `unsandboxed(...)` allow entries. |
| `read_file(...)` | `read_file(/home/alice/workspace)`<br>`read_file(/etc/shadow)`<br>`read_file(*)` | Recursive read permission on a file or directory. Populates read-only bind mounts in Linux `exebox` / macOS `sandbox-exec`. Denying `read_file` implicitly denies `write_file`. Use exact POSIX paths starting with `/` (no `*` globs inside paths). |
| `write_file(...)` | `write_file(/home/alice/workspace)`<br>`write_file(/home/alice/.gemini)`<br>`write_file(*)` | Recursive read+write permission on a file or directory. Populates read-write bind mounts in the sandbox. Allowing `write_file` implicitly grants `read_file`. |
| `read_url(...)` | `read_url(docs.cloud.google.com)`<br>`read_url(pastebin.com)`<br>`read_url(*)` | Matches domain and all subdomains (ignoring path). Governs `read_url_content`, Browser Subagent page loads, **and** outbound network domain allowlists inside the terminal sandbox. |
| `execute_url(...)` | `execute_url(localhost)`<br>`execute_url(webhook.site)`<br>`execute_url(*)` | Governs interactive Browser Subagent UI actuation (clicking buttons, filling forms, executing page interactions) on the specified domain. |
| `mcp(...)` | `mcp(catalog/ping_catalog)`<br>`mcp(corp_docs/*)`<br>`mcp(*)` | Governs Model Context Protocol tool execution for a specific tool (`server/tool`), an entire server (`server/*`), or all MCP servers (`*`). |

---

## 5. Manual Administrator Commands (Deploy, Normalize & Lock)

### A. Linux (Run as `root` / `sudo`)

```bash
DEV_USER="alice"   # <-- Replace with target developer OS username
USER_HOME="$(getent passwd "${DEV_USER}" | cut -d: -f6)"
TARGET_FILE="${USER_HOME}/.gemini/antigravity-cli/settings.json"

# 1. Unlock existing file if previously locked
sudo chattr -i "${TARGET_FILE}" 2>/dev/null || true

# 2. Ensure parent directories exist and are owned by the developer (so CLI runtime logs/state still work)
sudo mkdir -p "${USER_HOME}/.gemini/antigravity-cli"
sudo chown "${DEV_USER}:${DEV_USER}" "${USER_HOME}/.gemini" "${USER_HOME}/.gemini/antigravity-cli"

# 3. Render __DEV_USER__ placeholders for this developer
sed -e "s|/home/__DEV_USER__|${USER_HOME}|g" -e "s|__DEV_USER__|${DEV_USER}|g" \
  ./settings.json | sudo tee "${TARGET_FILE}" >/dev/null

# 4. CRITICAL: Normalize sparse JSON via `agy --version` BEFORE locking with chattr +i
sudo chown "${DEV_USER}:${DEV_USER}" "${TARGET_FILE}"
sudo chmod 0644 "${TARGET_FILE}"
if command -v agy >/dev/null 2>&1; then
  sudo su - "${DEV_USER}" -c "agy --version" >/dev/null 2>&1 || true
fi

# 5. Transfer file ownership to root:root, set read-only permissions, and lock in Linux kernel
sudo chown root:root "${TARGET_FILE}"
sudo chmod 0644 "${TARGET_FILE}"
sudo chattr +i "${TARGET_FILE}"

# 6. Verify ownership and 'i' immutable attribute
ls -la "${TARGET_FILE}"
sudo lsattr "${TARGET_FILE}"
```

*To unlock later for admin edits on Linux:*
```bash
sudo chattr -i "/home/${DEV_USER}/.gemini/antigravity-cli/settings.json"
```

### B. macOS (Run as `root` / `sudo` or via Jamf / Kandji)

```bash
DEV_USER="alice"   # <-- Replace with target macOS developer username
USER_HOME="/Users/${DEV_USER}"
TARGET_FILE="${USER_HOME}/.gemini/antigravity-cli/settings.json"

# 1. Unlock existing file if previously locked with schg
sudo chflags noschg,nouchg "${TARGET_FILE}" 2>/dev/null || true

# 2. Create parent directories owned by developer:staff
sudo mkdir -p "${USER_HOME}/.gemini/antigravity-cli"
sudo chown "${DEV_USER}:staff" "${USER_HOME}/.gemini" "${USER_HOME}/.gemini/antigravity-cli"

# 3. Render __DEV_USER__ placeholders
sed -e "s|/Users/__DEV_USER__|${USER_HOME}|g" -e "s|__DEV_USER__|${DEV_USER}|g" \
  ./settings.json | sudo tee "${TARGET_FILE}" >/dev/null

# 4. CRITICAL: Normalize sparse JSON via `agy --version` BEFORE locking with chflags schg
sudo chown "${DEV_USER}:staff" "${TARGET_FILE}"
sudo chmod 0644 "${TARGET_FILE}"
if command -v agy >/dev/null 2>&1; then
  sudo su - "${DEV_USER}" -c "agy --version" >/dev/null 2>&1 || true
fi

# 5. Transfer ownership to root:wheel and apply macOS system-immutable flag
sudo chown root:wheel "${TARGET_FILE}"
sudo chmod 0644 "${TARGET_FILE}"
sudo chflags schg "${TARGET_FILE}"

# 6. Verify ownership and 'schg' flag
ls -lO "${TARGET_FILE}"
```

*To unlock later for admin edits on macOS:*
```bash
sudo chflags noschg,nouchg "/Users/${DEV_USER}/.gemini/antigravity-cli/settings.json"
```

### C. Windows 10 / 11 / Server (Run in Elevated Administrator PowerShell)

```powershell
$DevUser    = "alice"   # <-- Replace with target Windows username
$UserHome   = "C:\Users\$DevUser"
$ForwardHome = $UserHome -replace '\\', '/'
$TargetDir  = "$UserHome\.gemini\antigravity-cli"
$TargetFile = "$TargetDir\settings.json"

# 1. Unlock existing file if present
if (Test-Path -LiteralPath $TargetFile) {
    attrib.exe -R $TargetFile
    icacls.exe $TargetFile /remove:d $DevUser | Out-Null
    icacls.exe $TargetFile /grant "${DevUser}:(M)" | Out-Null
}

# 2. Create parent directory and render __DEV_USER__ placeholders
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
$Raw = Get-Content -LiteralPath ".\settings.json" -Raw
$Rendered = ($Raw -replace '/home/__DEV_USER__', $ForwardHome) -replace '__DEV_USER__', $DevUser
# Write UTF-8 without BOM (PowerShell 5.1 Set-Content -Encoding UTF8 prepends 0xEF 0xBB 0xBF, which Go json.Unmarshal rejects)
[System.IO.File]::WriteAllText($TargetFile, $Rendered, (New-Object System.Text.UTF8Encoding($false)))

# 3. Lock with Administrator ownership + Read-Only attribute + NTFS Deny Write/Delete ACE
takeown.exe /F $TargetFile /A | Out-Null
icacls.exe $TargetFile /inheritance:r `
    /grant:r "SYSTEM:(F)" `
    /grant:r "Administrators:(F)" `
    /grant:r "${DevUser}:(R)" `
    /deny "${DevUser}:(WD,AD,WEA,WA,DE,WDAC,WO)" | Out-Null
attrib.exe +R $TargetFile

# 4. Verify ACLs
icacls.exe $TargetFile
```

*To unlock later for admin edits on Windows:*
```powershell
$TargetFile = "C:\Users\$DevUser\.gemini\antigravity-cli\settings.json"
attrib.exe -R $TargetFile
icacls.exe $TargetFile /remove:d $DevUser | Out-Null
```
