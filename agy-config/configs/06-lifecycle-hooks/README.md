# `hooks.json` — Lifecycle Security & SIEM Audit Hooks Configuration

## 1. What This File Is Used For

[`hooks.json`](./hooks.json) (`~/.gemini/config/hooks.json`) configures **synchronous execution-loop lifecycle hooks** across **Antigravity Desktop App**, **Antigravity CLI (`agy`)**, and **Antigravity IDE**.

Hooks execute custom scripts or shell commands at deterministic points in the agent loop — receiving full JSON context (`conversationId`, `workspacePaths`, `modelName`, `toolCall.name`, `toolCall.args`) on `stdin` — without interfering with commands typed manually by the human developer in their own terminal.

> [!IMPORTANT]
> Live verification (2026-11) showed two format rules. **(1) Use a named hook group** (`{"agy-security-guard": {"enabled": true, "PreToolUse": [...]}}`): the earlier `{"hooks": {"PreToolUse": [...]}}` shape worked on the CLI but was **ignored by the JetBrains/Zed ACP server**. **(2) On Windows, write the guard path with forward slashes** (`-File C:/ProgramData/Antigravity/bin/agy_security_guard.ps1`): the ACP server splits hook commands POSIX-style, drops backslashes, reports "External hook ... failed to execute" and then denies every tool call. `hooks.json` is the only file-based control the ACP server honors.

In this enterprise security configuration, [`hooks.json`](./hooks.json) wires every tool invocation (`"matcher": ""`) into our hardened OS guard scripts ([`agy_security_guard.sh` / `agy_security_guard.ps1`](../07-security-guard-scripts/README.md)):
1. **`PreToolUse` (Active Policy Blocker)**: Fires *before* any tool (`run_command`, `view_file`, `write_to_file`, `replace_file_content`, `read_url_content`, `call_mcp_tool`, etc.) executes. Inspects the full serialized `toolCall` arguments for destructive file deletions, credential/SAM/shadow reads, network probing (`ssh`/`nc`/`ping`), exploit tools (`nmap`/`sqlmap`/`mimikatz`), or cloud metadata SSRF (`169.254.169.254`), and immediately aborts execution on policy match.
   * *Critical on Windows*: On Windows 10, Windows Server, or pre-24H2 Windows 11 builds where native OS terminal sandboxing is unavailable, `PreToolUse` acts as the primary synchronous command-payload gatekeeper!
2. **`PostToolUse` (SIEM / Compliance Telemetry Logger)**: Fires immediately *after* each tool call completes (capturing `error` status if any) and appends structured JSONL audit records for Splunk, Google SecOps (Chronicle), or Datadog ingestion.

### Important Operational Notes

* **Global Location Only**: Always place global hooks in `~/.gemini/config/hooks.json`. Hooks placed inside `~/.gemini/antigravity-cli/settings.json` are **ignored** by Antigravity CLI.
* **Windows Command Path Quoting Rule**: On Windows, configure the handler `command` without escaped inner quotes around the space-free script path:
  ```json
  "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/ProgramData/Antigravity/bin/agy_security_guard.ps1 pre"
  ```
  *(Our [`deploy_and_lock_windows.ps1`](../../scripts/deploy_and_lock_windows.ps1) script performs this exact rewrite automatically.)*

---

## 2. Official Public Documentation Links

* **Lifecycle Hooks Guide & Complete Schema Specification**:
  * [Hooks Overview (`~/.gemini/config/hooks.json`)](https://antigravity.google/docs/hooks/)
  * [Schema and File Format (`#schema-and-file-format`)](https://antigravity.google/docs/hooks/#schema-and-file-format)
  * [Supported Events & Matcher Regex (`#supported-events`)](https://antigravity.google/docs/hooks/#supported-events)
  * [Supported Tool Names & Arguments (`#supported-tools`)](https://antigravity.google/docs/hooks/#supported-tools)
  * [Hook Handler Configuration (`#hook-handler-configuration`)](https://antigravity.google/docs/hooks/#hook-handler-configuration)
  * [Input (`stdin`) and Output (`stdout`) JSON Contract (`#input-and-output-contract`)](https://antigravity.google/docs/hooks/#input-and-output-contract)

---

## 3. Where This File Should Go (Target Locations)

| Operating System | Exact Global Target File Path | Guard Script Referenced by `command` | File Owner & Mode | Immutability Lock |
| :--- | :--- | :--- | :--- | :--- |
| **Linux** | `/home/<USERNAME>/.gemini/config/hooks.json` | `/usr/local/bin/agy_security_guard.sh` | `root:root` (`0644` or `0444`) | `chattr +i` |
| **macOS** | `/Users/<USERNAME>/.gemini/config/hooks.json` | `/usr/local/bin/agy_security_guard.sh` | `root:wheel` (`0644` or `0444`) | `chflags schg` |
| **Windows** | `C:\Users\<USERNAME>\.gemini\config\hooks.json` | `C:\ProgramData\Antigravity\bin\agy_security_guard.ps1` | `Administrators` (`ReadOnly`) | `icacls /deny "<USERNAME>:(WD,AD,WEA,WA,DE,WDAC,WO)"` + `attrib +R` |

*Additional scopes supported by Antigravity (for non-security team formatters/linters): `<workspace>/.agents/hooks.json` (workspace level) and `<plugin-root>/hooks.json` (plugin level).*

---

## 4. Allowed Keywords & Configuration Reference Tables

### Table A — `hooks.json` Structure, Hook Definition Fields & Handler Properties

`hooks.json` maps one or more hook group names (e.g., `"hooks"`, `"enterprise-security-guard"`, `"my-linter-hook"`) to event definitions:

| JSON Key Path | Data Type | Default | Required? | Allowed Values / Description |
| :--- | :--- | :--- | :---: | :--- |
| `<hookGroupName>` | `object` | — | **Required** | Top-level named hook definition object (e.g., `"hooks"` in our canonical template, or multiple named groups like `"safety-gate"`). |
| `<hookGroupName>.enabled` | `boolean` | `true` | Optional | Set to `false` to temporarily disable a hook group without deleting its configuration. |
| `<hookGroupName>.SessionStart` | `Handler[]` | `[]` | Optional | Array of handler objects executed once when a new conversation session starts, before the first model call *(matcher ignored)*. |
| `<hookGroupName>.PreToolUse` | `MatcherRule[]` | `[]` | Optional | Array of `{matcher, hooks}` rules executed **before** a tool runs (can allow, prompt, modify args, or block). |
| `<hookGroupName>.PostToolUse` | `MatcherRule[]` | `[]` | Optional | Array of `{matcher, hooks}` rules executed **after** a tool finishes (receives `error` string if tool failed). |
| `<hookGroupName>.PreInvocation` | `Handler[]` | `[]` | Optional | Array of handler objects executed before Antigravity calls the LLM *(matcher ignored)*. |
| `<hookGroupName>.PostInvocation` | `Handler[]` | `[]` | Optional | Array of handler objects executed immediately after each LLM invocation completes *(matcher ignored)*. |
| `<hookGroupName>.Stop` | `Handler[]` | `[]` | Optional | Array of handler objects executed when the agent execution loop terminates *(matcher ignored)*. |
| `MatcherRule.matcher` | `string` | `""` (all) | Optional (`PreToolUse` / `PostToolUse`) | Regex or wildcard matching tool names: `""` or `"*"` or `".*"` matches all tools; `"run_command"` matches one tool; `"run_command\|view_file"` matches multiple; `"browser_.*"` matches prefix. |
| `MatcherRule.hooks` | `Handler[]` | — | **Required** | Ordered list of command handlers triggered when `matcher` matches `toolCall.name`. |
| `Handler.type` | `string` | `"command"` | Optional | Handler execution type. Currently `"command"` is the only supported value. |
| `Handler.command` | `string` | — | **Required** | Shell command executed by Antigravity (`sh -c` on Linux/macOS, `cmd /c` on Windows), receiving event JSON on `stdin`. |
| `Handler.timeout` | `integer` | `30` | Optional | Maximum execution duration in seconds before the hook process is terminated (`10` in our security profile). |

### Table B — Hook `stdin` / `stdout` JSON Contract & Blocking Semantics

| Lifecycle Event | `stdin` Payload Fields *(in addition to Common Fields\**)* | `stdout` JSON Output Keywords / Exit Code Behavior |
| :--- | :--- | :--- |
| **`PreToolUse`** | • `toolCall.name` (`string`, e.g., CLI `1.4+` & Desktop/IDE names `"run_command"`, `"read_file"`, `"write_file"`, `"edit_file"`, `"view_file"`, `"write_to_file"`, `"replace_file_content"`, `"multi_replace_file_content"`, `"sed_file"`, `"read_url_content"`, `"search_web"`, `"mcp_<server>_<tool>"`, `"call_mcp_tool"`, `"list_dir"`, `"find_by_name"`, `"grep_search"`, `"manage_task"`, `"schedule"`, `"invoke_subagent"`, `"generate_image"`)<br>• `toolCall.args` (`object`)<br>• `stepIdx` (`integer`) | **Method 1 (JSON `stdout`, exit `0`)**:<br>• `decision`: `"allow"` \| `"auto_approve"` \| `"deny"` \| `"ask"` \| `"force_ask"` \| `"deny_unless_prior_grant"`<br>• `reason` (`string`, optional explanation)<br>• `overwrite` (`object`, shallow merge into `toolCall.args`)<br>• `permissionOverrides` (`string[]`)<br>**Method 2 (Process Exit Code `2`)**:<br>Writing policy violation text to `stderr` and exiting with code `2` hard-blocks tool execution immediately. |
| **`PostToolUse`** | • `toolCall.name` (`string`)<br>• `toolCall.args` (`object`)<br>• `stepIdx` (`integer`)<br>• `error` (`string`, empty if tool succeeded) | Returns `{}` (or empty stdout with exit `0`). |
| **`SessionStart`** | *(Common fields only)* | Optional `{"injectSteps": [{"systemMessage": ...}]}`. |
| **`PreInvocation`** | • `invocationNum` (`integer`)<br>• `initialNumSteps` (`integer`) | Optional `{"injectSteps": [{"systemMessage": ...} \| {"userMessage": "..."} \| {"ephemeralMessage": "..."} \| {"toolCall": ...}]}`. |
| **`PostInvocation`** | • `invocationNum` (`integer`)<br>• `initialNumSteps` (`integer`) | Optional `{"injectSteps": [...], "terminationBehavior": "" \| "force_continue" \| "terminate"}`. |
| **`Stop`** | • `executionNum` (`integer`)<br>• `terminationReason` (`string`, e.g., `"model_stop"`, `"error"`)<br>• `error` (`string`)<br>• `fullyIdle` (`boolean`) | `{"decision": "continue" \| "stop", "reason": "..."}`. |

*\*Common `stdin` fields included on every event: `conversationId` (`string`), `workspacePaths` (`string[]`), `transcriptPath` (`string`), `artifactDirectoryPath` (`string`), and `modelName` (`string`).*

---

## 5. Manual Administrator Commands (Deploy, Set Permissions & Lock)

> **Prerequisite**: Install and lock the executable guard script in [`../07-security-guard-scripts/`](../07-security-guard-scripts/README.md) alongside `hooks.json` so every `PreToolUse` / `PostToolUse` invocation resolves cleanly.

### A. Linux (Run as `root` / `sudo`)

```bash
DEV_USER="alice"   # <-- Replace with target developer OS username
USER_HOME="$(getent passwd "${DEV_USER}" | cut -d: -f6)"
TARGET_FILE="${USER_HOME}/.gemini/config/hooks.json"

# 1. Unlock existing file if previously locked
sudo chattr -i "${TARGET_FILE}" 2>/dev/null || true

# 2. Ensure parent directories exist and belong to the developer
sudo mkdir -p "${USER_HOME}/.gemini/config"
sudo chown "${DEV_USER}:${DEV_USER}" "${USER_HOME}/.gemini" "${USER_HOME}/.gemini/config"

# 3. Install hooks.json owned by root:root (0644) and lock with chattr +i
sudo install -m 0644 -o root -g root ./hooks.json "${TARGET_FILE}"
sudo chattr +i "${TARGET_FILE}"

# 4. Verify ownership and 'i' immutable attribute
ls -la "${TARGET_FILE}"
sudo lsattr "${TARGET_FILE}"
```

*To unlock later for admin edits on Linux:*
```bash
sudo chattr -i "/home/${DEV_USER}/.gemini/config/hooks.json"
```

### B. macOS (Run as `root` / `sudo` or via Jamf / Kandji)

```bash
DEV_USER="alice"   # <-- Replace with target macOS developer username
USER_HOME="/Users/${DEV_USER}"
TARGET_FILE="${USER_HOME}/.gemini/config/hooks.json"

# 1. Remove macOS system-immutable flag if present
sudo chflags noschg,nouchg "${TARGET_FILE}" 2>/dev/null || true

# 2. Ensure parent directories belong to developer:staff
sudo mkdir -p "${USER_HOME}/.gemini/config"
sudo chown "${DEV_USER}:staff" "${USER_HOME}/.gemini" "${USER_HOME}/.gemini/config"

# 3. Install hooks.json as root:wheel (0644) and lock with chflags schg
sudo install -m 0644 -o root -g wheel ./hooks.json "${TARGET_FILE}"
sudo chflags schg "${TARGET_FILE}"

# 4. Verify ownership and 'schg' flag
ls -lO "${TARGET_FILE}"
```

*To unlock later for admin edits on macOS:*
```bash
sudo chflags noschg,nouchg "/Users/${DEV_USER}/.gemini/config/hooks.json"
```

### C. Windows 10 / 11 / Server (Run in Elevated Administrator PowerShell)

```powershell
$DevUser    = "alice"   # <-- Replace with target Windows username
$TargetDir  = "C:\Users\$DevUser\.gemini\config"
$TargetFile = "$TargetDir\hooks.json"

# 1. Unlock existing file if present
if (Test-Path -LiteralPath $TargetFile) {
    attrib.exe -R $TargetFile
    icacls.exe $TargetFile /remove:d $DevUser | Out-Null
    icacls.exe $TargetFile /grant "${DevUser}:(M)" | Out-Null
}

# 2. Create parent directory and rewrite command path for Windows PowerShell guard script (no inner quotes around -File path)
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
$Raw = Get-Content -LiteralPath ".\hooks.json" -Raw
$WinHooks = $Raw -replace '/usr/local/bin/agy_security_guard\.sh', 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\ProgramData\\Antigravity\\bin\\agy_security_guard.ps1'
[System.IO.File]::WriteAllText($TargetFile, $WinHooks, (New-Object System.Text.UTF8Encoding($false)))

# 3. Lock with Administrator ownership + NTFS Deny Write/Delete ACL
takeown.exe /F $TargetFile /A | Out-Null
icacls.exe $TargetFile /inheritance:r `
    /grant:r "SYSTEM:(F)" `
    /grant:r "Administrators:(F)" `
    /grant:r "${DevUser}:(R)" `
    /deny "${DevUser}:(WD,AD,WEA,WA,DE,WDAC,WO)" | Out-Null
attrib.exe +R $TargetFile

# 4. Verify JSON validity and ACLs
Get-Content -LiteralPath $TargetFile -Raw | ConvertFrom-Json | Out-Null
icacls.exe $TargetFile
```

*To unlock later for admin edits on Windows:*
```powershell
$TargetFile = "C:\Users\$DevUser\.gemini\config\hooks.json"
attrib.exe -R $TargetFile
icacls.exe $TargetFile /remove:d $DevUser | Out-Null
```
