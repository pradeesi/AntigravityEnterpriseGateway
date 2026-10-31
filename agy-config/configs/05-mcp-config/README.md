# `mcp_config.json` — Model Context Protocol (MCP) Server Registry & Tool Governance

## 1. What This File Is Used For

[`mcp_config.json`](./mcp_config.json) (`~/.gemini/config/mcp_config.json`) is the **global Model Context Protocol (MCP) server registry and server-level tool filter configuration** shared across **Antigravity Desktop App**, **Antigravity CLI (`agy`)**, and **Antigravity IDE**.

When deployed and kernel-locked by an enterprise administrator, [`mcp_config.json`](./mcp_config.json) controls:
1. **Approved MCP Server Inventory (`mcpServers`)**: Registers vetted local `stdio` servers (`command` + `args`) and remote Streamable HTTP MCP gateways (`serverUrl` + `headers` / `authProviderType` / `oauth`). Because the global file is locked (`chattr +i` / `chflags schg` / `icacls /deny`), developers cannot add unvetted third-party MCP servers via `/mcp` or the MCP Store UI into the global registry.
2. **Server-Level Tool Allowlisting (`enabledTools`)**: Exposes *only* explicitly named read/query tools from a connected server while hiding all other tools on that server from the LLM's tool catalog.
3. **Server-Level Destructive Tool Denylisting (`disabledTools`)**: Strips administrative or mutating tools (e.g., `drop_catalog_table`, `delete_repository`, `modify_acl`) before tool definitions ever reach the agent.
4. **Explicit Suspension (`disabled: true`)**: Keeps a blocked server entry disabled in place (preventing a workspace config from hijacking the same server identifier if already registered).

### Defense-in-Depth Pairing with `permissions` & Schema Caveats

* **Two-Layer MCP Governance**: Pair `mcp_config.json` (which controls *which servers connect* and *which tools are exposed*) with `mcp(server/tool)` / `mcp(server/*)` rules in [`settings.json`](../02-cli-settings/README.md) (`permissions`) and [`config.json`](../03-desktop-hub-config/README.md) (`userSettings.globalPermissionGrants`), which govern whether exposed tools auto-run (`allow`), prompt for human review (`ask`), or hard-block (`deny`).
* **Critical `tools` Eager Schema & Permission Rule**:
  1. `mcp(<server>/<tool>)` and `mcp(*)` permission rules in `settings.json` and `config.json` are evaluated inside `call_mcp_tool` (**default lazy-loaded MCP mode**). Leave governed servers on default lazy loading (omit `"eager": true`) whenever you rely on `mcp(...)` `ask` or `deny` rules, because setting `"eager": true` registers tools directly as native `mcp_<server>_<tool>` functions and bypasses `call_mcp_tool`'s `mcp(...)` permission gate.
  2. If you do configure eager loading on vetted auto-approved read-only tools via `tools`, it **must** map each tool name to an object (`"tools": {"ping_catalog": {"eager": true}}`), **never** `"tools": {"eager": ["*"]}` (which fails Go struct unmarshaling into `McpServer` and drops the server).
* **Lazy-Loaded MCP Schema Read Rule**: When `allowNonWorkspaceAccess: false` is enforced in `settings.json`, ensure `"read_file(/home/<USERNAME>/.gemini)"` is present in `permissions.allow` (while keeping `"write_file(/home/<USERNAME>/.gemini)"` in `permissions.deny`) so the agent can read `~/.gemini/antigravity-cli/mcp/<server>/<tool>.json` before calling `call_mcp_tool`.
* **Remote Transport Requirement**: Remote MCP servers must use the **Streamable HTTP** transport via `serverUrl` (or `url`). Legacy `httpUrl` and deprecated HTTP+SSE-only transports are not supported.
* **Out-of-the-Box Template Safety (`disabled: true`)**: The example entries in [`mcp_config.json`](./mcp_config.json) (`catalog`, `corp_docs`, `untrusted_external`) ship with `"disabled": true` by default so Antigravity CLI/App starts instantaneously without hanging on unreachable placeholder example endpoints. Set `"disabled": false` after replacing `command` or `serverUrl` with your live internal MCP server.

---

## 2. Official Public Documentation Links

* **Model Context Protocol (MCP) Guide & Configuration Schema**:
  * [Model Context Protocol (MCP) Overview](https://antigravity.google/docs/mcp/)
  * [MCP Configuration Structure (`#mcp-configuration-structure`)](https://antigravity.google/docs/mcp/#mcp-configuration-structure)
  * [MCP Configuration Properties Table (`#mcp-configuration-properties`)](https://antigravity.google/docs/mcp/#mcp-configuration-properties)
  * [MCP Authentication (`google_credentials`, `oauth`, `headers`)](https://antigravity.google/docs/mcp/#mcp-authentication)
  * [MCP Permissions and Access Control (`mcp(server/tool)`)](https://antigravity.google/docs/mcp/#mcp-permissions-and-access-control)

---

## 3. Where This File Should Go (Target Locations)

### Global Workstation Paths (MDM-Locked Across All Projects)

| Operating System | Exact Global Target File Path | Parent Dir Owner | File Owner & Mode | Immutability Lock |
| :--- | :--- | :--- | :--- | :--- |
| **Linux** | `/home/<USERNAME>/.gemini/config/mcp_config.json` | `<USERNAME>:<USERNAME>` (`0755`) | `root:root` (`0644` or `0444`) | `chattr +i` |
| **macOS** | `/Users/<USERNAME>/.gemini/config/mcp_config.json` | `<USERNAME>:staff` (`0755`) | `root:wheel` (`0644` or `0444`) | `chflags schg` |
| **Windows** | `C:\Users\<USERNAME>\.gemini\config\mcp_config.json` | `<USERNAME>` | `Administrators` (`ReadOnly`) | `icacls /deny "<USERNAME>:(WD,AD,WEA,WA,DE,WDAC,WO)"` + `attrib +R` |

### Additional Discovery Scopes (For Reference)

* **Workspace-level config**: `<workspace>/.agents/mcp_config.json` *(governed at runtime by your global `permissions.deny` rules such as `mcp(untrusted_external/*)` even if a repository contains `.agents/mcp_config.json`)*.
* **Plugin-bundled config**: `<plugin-root>/mcp.json` *(inside installed plugins)*.
* **OAuth token cache (runtime-managed)**: `~/.gemini/antigravity/mcp_oauth_tokens.json` *(do NOT lock this token cache file if using OAuth MCP servers so automatic token refresh succeeds)*.

---

## 4. Allowed Keywords & Configuration Reference Table

| JSON Key Path | Data Type | Default Value | Required? | Description |
| :--- | :--- | :--- | :---: | :--- |
| `mcpServers` | `object` (`map<string, ServerConfig>`) | `{}` | **Required** | Root map where each property key is a unique MCP server identifier (e.g., `"catalog"`, `"corp_docs"`). Used in `mcp(<serverId>/<toolName>)` permission rules. |
| `mcpServers.<id>.command` | `string` | — | **Required for `stdio`** *(mutually exclusive with `serverUrl`)* | Executable path or binary name used to spawn a local `stdio` MCP server child process (e.g., `"/usr/local/bin/mock_mcp_server.py"`, `"node"`, `"npx"`). |
| `mcpServers.<id>.args` | `string[]` | `[]` | Optional (`stdio` only) | Array of command-line arguments passed to `command` (e.g., `["/usr/local/bin/sqlite-mcp-server.js"]`). |
| `mcpServers.<id>.env` | `object` (`map<string,string>`) | `{}` | Optional (`stdio` only) | Environment variables injected into the spawned local `stdio` MCP process. Never hardcode plaintext secrets here in git; inject via OS/secret manager at deploy time. |
| `mcpServers.<id>.cwd` | `string` | Process working dir | Optional (`stdio` only) | Working directory used when launching the local `stdio` MCP server process. |
| `mcpServers.<id>.serverUrl` | `string` | — | **Required for remote** *(alias: `url`)* | HTTPS endpoint URL of a remote MCP server speaking the **Streamable HTTP** transport (e.g., `"https://mcp-corp-docs.internal.example.com/mcp/"`). *Note: `httpUrl` is not supported.* |
| `mcpServers.<id>.url` | `string` | — | Optional alias | Supported alias for `serverUrl` on remote Streamable HTTP MCP servers. |
| `mcpServers.<id>.headers` | `object` (`map<string,string>`) | `{}` | Optional (remote only) | Custom HTTP request headers sent on remote `serverUrl` connections (e.g., `{"Authorization": "Bearer ...", "X-Cost-Center": "CC-9941"}`). |
| `mcpServers.<id>.authProviderType` | `string` | — | Optional | Built-in credential provider. Set to `"google_credentials"` to automatically attach Google Application Default Credentials (ADC) to remote GCP/Apigee MCP endpoints. |
| `mcpServers.<id>.oauth` | `object` | — | Optional (remote only) | Manual OAuth 2.0 client configuration for remote servers without Dynamic Client Registration (DCR). Redirect URI must allow `https://antigravity.google/oauth-callback`. |
| `mcpServers.<id>.oauth.clientId` | `string` | — | Required (if `oauth` set) | OAuth 2.0 Client ID registered with your identity provider. |
| `mcpServers.<id>.oauth.clientSecret` | `string` | — | Optional | OAuth 2.0 Client Secret (when required by confidential client flows). |
| `mcpServers.<id>.disabled` | `boolean` | `false` | Optional | When `true`, suspends connection to this MCP server without removing its policy definition from `mcp_config.json`. |
| `mcpServers.<id>.enabledTools` | `string[]` | All server tools | Optional | Strict allowlist of tool names exposed to the agent from this server. When set, **all unlisted tools on that server are hidden**. |
| `mcpServers.<id>.disabledTools` | `string[]` | `[]` | Optional | Denylist of tool names withheld from the agent even if advertised by the MCP server. |
| `mcpServers.<id>.timeoutSeconds` | `integer` | `300` (connect), `180` (tool call) | Optional | Positive integer overrides both connection/tool-listing timeout and per-call timeout (in seconds, e.g., `600`). `0` keeps defaults; `-1` disables timeouts. |
| `mcpServers.<id>.tools` | `object` (`map<string, {"eager": boolean}>`) | `{}` | Optional | Per-tool registration overrides, e.g. `{"ping_catalog": {"eager": true}}` to register specific tools eagerly rather than lazy-loading schemas on demand. |

---

## 5. Manual Administrator Commands (Deploy, Set Permissions & Lock)

### A. Linux (Run as `root` / `sudo`)

```bash
DEV_USER="alice"   # <-- Replace with target developer OS username
USER_HOME="$(getent passwd "${DEV_USER}" | cut -d: -f6)"
TARGET_FILE="${USER_HOME}/.gemini/config/mcp_config.json"

# 1. Unlock existing file if previously locked
sudo chattr -i "${TARGET_FILE}" 2>/dev/null || true

# 2. Ensure parent directories exist and belong to the developer
sudo mkdir -p "${USER_HOME}/.gemini/config"
sudo chown "${DEV_USER}:${DEV_USER}" "${USER_HOME}/.gemini" "${USER_HOME}/.gemini/config"

# 3. Validate JSON syntax before installing
python3 -m json.tool ./mcp_config.json >/dev/null

# 4. Install owned by root:root (0644) and lock with Linux kernel immutability
sudo install -m 0644 -o root -g root ./mcp_config.json "${TARGET_FILE}"
sudo chattr +i "${TARGET_FILE}"

# 5. Verify ownership and 'i' immutable attribute
ls -la "${TARGET_FILE}"
sudo lsattr "${TARGET_FILE}"
```

*To unlock later for admin edits on Linux:*
```bash
sudo chattr -i "/home/${DEV_USER}/.gemini/config/mcp_config.json"
```

### B. macOS (Run as `root` / `sudo` or via Jamf / Kandji)

```bash
DEV_USER="alice"   # <-- Replace with target macOS developer username
USER_HOME="/Users/${DEV_USER}"
TARGET_FILE="${USER_HOME}/.gemini/config/mcp_config.json"

# 1. Remove macOS system-immutable flag if present
sudo chflags noschg,nouchg "${TARGET_FILE}" 2>/dev/null || true

# 2. Ensure parent directories belong to developer:staff
sudo mkdir -p "${USER_HOME}/.gemini/config"
sudo chown "${DEV_USER}:staff" "${USER_HOME}/.gemini" "${USER_HOME}/.gemini/config"

# 3. Validate JSON and install as root:wheel (0644) + chflags schg
python3 -m json.tool ./mcp_config.json >/dev/null
sudo install -m 0644 -o root -g wheel ./mcp_config.json "${TARGET_FILE}"
sudo chflags schg "${TARGET_FILE}"

# 4. Verify ownership and 'schg' flag
ls -lO "${TARGET_FILE}"
```

*To unlock later for admin edits on macOS:*
```bash
sudo chflags noschg,nouchg "/Users/${DEV_USER}/.gemini/config/mcp_config.json"
```

### C. Windows 10 / 11 / Server (Run in Elevated Administrator PowerShell)

```powershell
$DevUser    = "alice"   # <-- Replace with target Windows username
$TargetDir  = "C:\Users\$DevUser\.gemini\config"
$TargetFile = "$TargetDir\mcp_config.json"

# 1. Unlock existing file if present
if (Test-Path -LiteralPath $TargetFile) {
    attrib.exe -R $TargetFile
    icacls.exe $TargetFile /remove:d $DevUser | Out-Null
    icacls.exe $TargetFile /grant "${DevUser}:(M)" | Out-Null
}

# 2. Validate JSON, create parent directory, and copy mcp_config.json
Get-Content -LiteralPath ".\mcp_config.json" -Raw | ConvertFrom-Json | Out-Null
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
Copy-Item -LiteralPath ".\mcp_config.json" -Destination $TargetFile -Force

# 3. Lock with Administrator ownership + NTFS Deny Write/Delete ACL
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
$TargetFile = "C:\Users\$DevUser\.gemini\config\mcp_config.json"
attrib.exe -R $TargetFile
icacls.exe $TargetFile /remove:d $DevUser | Out-Null
```
