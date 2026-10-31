# Antigravity Enterprise Administrator Policy Cookbook (`ADMIN_POLICY_EXAMPLES.md`)

<!--
==============================================================================
File: agy-config/ADMIN_POLICY_EXAMPLES.md
Purpose: Comprehensive, live-validated administrator cookbook containing 20
         enterprise governance recipes for Google Antigravity, with exact file
         names, target OS paths (Linux, macOS, Windows), target client surfaces
         (AGY CLI, Desktop, Web Hub, VS Code, Visual Studio, JetBrains, Zed),
         and complete copy-pasteable configurations.
Architecture/Context: Complements agy-config/README.md and the 8 per-file
         schema guides under agy-config/configs/01-* through 08-*.
Dependencies/Side Effects: Pure documentation reference; zero live credentials,
         project IDs, or personal identifiers included.
==============================================================================
-->

This administrator cookbook provides **20 live-verified enterprise policy recipes** for governing **Google Antigravity** across **Linux**, **macOS**, and **Windows** workstations. Every example specifies:
1. **Exact canonical filename(s)**
2. **Exact destination directory and path on Linux, macOS, and Windows**
3. **Exact client surfaces governed** (`AGY CLI`, `AGY Desktop App`, `AGY Web Hub`, `VS Code / Visual Studio`, `JetBrains IDEs`, `Zed Editor`)
4. **Complete, copy-pasteable JSON / script payloads** (zero `...` placeholders) and OS immutability lock commands

---

## 1. Master Surface & OS File-Mapping Matrix

### A. Understanding Antigravity Client Surfaces in Enterprise Gateway Mode

| Surface Name | How Developers Launch It | Config Engine Used | Enterprise Gateway & Local MDM Support |
| :--- | :--- | :--- | :--- |
| **AGY CLI** | `agy` (interactive TUI) or `agy -p "..."` (headless) (`v1.2.15+`) | CLI Engine + Global Grants | **Full Support** (`admin_settings.json`, `settings.json`, `config.json` grants, `mcp_config.json`, `hooks.json`) |
| **AGY Desktop App** | Native `Antigravity` desktop app (`v2.15.0+`) | Desktop / Hub Engine | **Full Support** (`admin_settings.json`, `config.json`, `browserAllowlist.txt`, `mcp_config.json`, `hooks.json`) |
| **AGY Web Hub (Self-Hosted VM Browser UI)** | `agy --hub` (served over browser on a Linux/Cloud Workstation VM, e.g., `:4400`) | Desktop / Hub Engine | **Full Support** — runs the local Hub server on the VM and enforces all workstation MDM files (`admin_settings.json`, `config.json`, `browserAllowlist.txt`, `mcp_config.json`, `hooks.json`) |
| **Antigravity SaaS Web (`antigravity.google`)** | Cloud-hosted browser SaaS | Google Cloud OAuth SaaS | **Not Supported for Gateway/MDM** — SaaS Web requires interactive Google sign-in and does not read workstation files |
| **AGY IDE Plugins — VS Code & Visual Studio** | `Google.google-antigravity` extension (`agy v1.2.15+`) | Delegates to local `agy` binary | **Full Support** — inherits `admin_settings.json`, `settings.json`, `config.json` grants, `mcp_config.json`, and `hooks.json` |
| **AGY IDE Plugins — JetBrains IDEs** | IntelliJ, PyCharm, GoLand, WebStorm, Android Studio (`ACP v1.3.0+`) | ACP Server (`agy acp` / `agy_acp_server`) | **Supported (`genai` wire protocol only)** — reads `admin_settings.json` + `~/.gemini/antigravity-acp/settings.json` + `~/.jetbrains/acp.json` |
| **AGY IDE Plugins — Zed Editor** | Zed native Agent Panel (`ACP v1.3.0+`) | ACP Server (`agy acp` / `agy_acp_server`) | **Supported (`genai` wire protocol only)** — reads `admin_settings.json` + `~/.gemini/antigravity-acp/settings.json` + Zed `settings.json` |

---

### B. Canonical Configuration Files by OS Path & Surface

*(Replace `<USER>` with the local developer OS account username, e.g., `alice`.)*

| Canonical File Name | Template in Repo | Linux Target Path | macOS Target Path | Windows Target Path | Surfaces Governed |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`admin_settings.json`** | [`configs/01-admin-settings/admin_settings.json`](./configs/01-admin-settings/admin_settings.json) | `/etc/antigravity/admin_settings.json` | `/Library/Application Support/Antigravity/admin_settings.json` | `C:\ProgramData\Antigravity\admin_settings.json` | **All Local Surfaces**: CLI, Desktop, Web Hub (`agy --hub`), VS Code, Visual Studio, JetBrains, Zed |
| **`settings.json`** *(CLI)* | [`configs/02-cli-settings/settings.json`](./configs/02-cli-settings/settings.json) | `/home/<USER>/.gemini/antigravity-cli/settings.json` | `/Users/<USER>/.gemini/antigravity-cli/settings.json` | `C:\Users\<USER>\.gemini\antigravity-cli\settings.json` | **AGY CLI**, **VS Code**, **Visual Studio** |
| **`config.json`** *(Desktop/Hub)* | [`configs/03-desktop-hub-config/config.json`](./configs/03-desktop-hub-config/config.json) | `/home/<USER>/.gemini/config/config.json` *(+ legacy `/home/<USER>/.gemini/config.json`)* | `/Users/<USER>/.gemini/config/config.json` *(+ legacy `/Users/<USER>/.gemini/config.json`)* | `C:\Users\<USER>\.gemini\config\config.json` *(+ legacy `C:\Users\<USER>\.gemini\config.json`)* | **AGY Desktop App**, **AGY Web Hub (`agy --hub`)**, plus global permission grants merged into **AGY CLI / VS Code** |
| **`browserAllowlist.txt`** | [`configs/04-browser-allowlist/browserAllowlist.txt`](./configs/04-browser-allowlist/browserAllowlist.txt) | `/home/<USER>/.gemini/antigravity/browserAllowlist.txt` | `/Users/<USER>/.gemini/antigravity/browserAllowlist.txt` | `C:\Users\<USER>\.gemini\antigravity\browserAllowlist.txt` | **AGY Desktop App**, **AGY Web Hub (`agy --hub`)**, **VS Code**, **AGY CLI (`/browser`)** |
| **`mcp_config.json`** | [`configs/05-mcp-config/mcp_config.json`](./configs/05-mcp-config/mcp_config.json) | `/home/<USER>/.gemini/config/mcp_config.json` | `/Users/<USER>/.gemini/config/mcp_config.json` | `C:\Users\<USER>\.gemini\config\mcp_config.json` | **AGY CLI**, **AGY Desktop App**, **AGY Web Hub (`agy --hub`)**, **VS Code** |
| **`hooks.json`** | [`configs/06-lifecycle-hooks/hooks.json`](./configs/06-lifecycle-hooks/hooks.json) | `/home/<USER>/.gemini/config/hooks.json` | `/Users/<USER>/.gemini/config/hooks.json` | `C:\Users\<USER>\.gemini\config\hooks.json` | **AGY CLI**, **AGY Desktop App**, **AGY Web Hub (`agy --hub`)**, **VS Code** |
| **`agy_security_guard.sh`** | [`configs/07-security-guard-scripts/agy_security_guard.sh`](./configs/07-security-guard-scripts/agy_security_guard.sh) | `/usr/local/bin/agy_security_guard.sh` | `/usr/local/bin/agy_security_guard.sh` | *(Not used on Windows — see `.ps1` below)* | Invoked by `hooks.json` across **CLI**, **Desktop**, **Web Hub**, **VS Code** on Linux & macOS |
| **`agy_security_guard.ps1`** | [`configs/07-security-guard-scripts/agy_security_guard.ps1`](./configs/07-security-guard-scripts/agy_security_guard.ps1) | *(Not used on Linux)* | *(Not used on macOS)* | `C:\ProgramData\Antigravity\bin\agy_security_guard.ps1` | Invoked by `hooks.json` across **CLI**, **Desktop**, **Web Hub**, **VS Code** on Windows |
| **`settings.json`** *(ACP Auth)* | [`configs/08-acp-ide-configs/antigravity-acp-settings.json`](./configs/08-acp-ide-configs/antigravity-acp-settings.json) | `/home/<USER>/.gemini/antigravity-acp/settings.json` | `/Users/<USER>/.gemini/antigravity-acp/settings.json` | `C:\Users\<USER>\.gemini\antigravity-acp\settings.json` | **JetBrains IDEs** & **Zed Editor** |
| **`acp.json`** *(JetBrains)* | [`configs/08-acp-ide-configs/acp.json`](./configs/08-acp-ide-configs/acp.json) | `/home/<USER>/.jetbrains/acp.json` | `/Users/<USER>/.jetbrains/acp.json` | `C:\Users\<USER>\.jetbrains\acp.json` | **JetBrains IDEs** (IntelliJ, PyCharm, GoLand, WebStorm, CLion, Android Studio) |
| **`settings.json`** *(Zed)* | [`configs/08-acp-ide-configs/acp.json`](./configs/08-acp-ide-configs/acp.json) *(merged)* | `/home/<USER>/.config/zed/settings.json` | `/Users/<USER>/Library/Application Support/Zed/settings.json` | `C:\Users\<USER>\AppData\Roaming\Zed\settings.json` | **Zed Editor** |

---

### C. Quick Scenario Index (20 Enterprise Admin Recipes)

* **Part I — Gateway Connectivity, TLS, Models, FinOps & Wire Protocols**
  1. [Route All Surfaces Through Enterprise Gateway, Trust Private Root CA & Suppress Google Login](#example-1-route-all-surfaces-through-enterprise-gateway-trust-private-root-ca--suppress-google-login)
  2. [Restrict the Selectable Model Catalog (Allow Approved Models Only & Pin Default Model)](#example-2-restrict-the-selectable-model-catalog-allow-approved-models-only--pin-default-model)
  3. [Enforce Non-Overridable FinOps Attribution Headers & Per-Developer API Keys](#example-3-enforce-non-overridable-finops-attribution-headers--per-developer-api-keys)
  4. [Configure JetBrains IDEs & Zed Editor Plugins for Enterprise Gateway (`ACP`)](#example-4-configure-jetbrains-ides--zed-editor-plugins-for-enterprise-gateway-acp)
  5. [Switch Inference Wire Protocol to OpenAI Chat Completions (`wireProtocol: "openai"`) & ACP Boundaries](#example-5-switch-inference-wire-protocol-to-openai-chat-completions-wireprotocol-openai--acp-boundaries)
* **Part II — OS Sandboxing, Corporate Forward Proxies, Bastion Mode & Ephemeral Privacy**
  6. [Enforce Terminal Sandboxing & Block File Access Outside the Project Workspace](#example-6-enforce-terminal-sandboxing--block-file-access-outside-the-project-workspace)
  7. [Route Sandboxed Agent Network Traffic Through a Corporate Forward Proxy / SSL Inspection Gateway (`sandboxProxy`)](#example-7-route-sandboxed-agent-network-traffic-through-a-corporate-forward-proxy--ssl-inspection-gateway-sandboxproxy)
  8. [Enforce Maximum Zero-Trust "Strict Human-in-the-Loop" Mode on Production Bastions (`toolPermission: "strict"`)](#example-8-enforce-maximum-zero-trust-strict-human-in-the-loop-mode-on-production-bastions-toolpermission-strict)
  9. [Enforce Ephemeral / Zero-Disk-History Privacy Mode (`historySize: 0` & Telemetry UI Suppression)](#example-9-enforce-ephemeral--zero-disk-history-privacy-mode-historysize-0--telemetry-ui-suppression)
* **Part III — Command, File, Secret & Browser Subagent Controls**
  10. [Block Destructive Commands (`rm`, `sudo`, `ssh`) While Requiring Human Approval (`ask`) for `git push` & `kubectl`](#example-10-block-destructive-commands-rm-sudo-ssh-while-requiring-human-approval-ask-for-git-push--kubectl)
  11. [Block Agent Access to Secrets, SSH Keys, Certificates & OS Password Files Across All OSes](#example-11-block-agent-access-to-secrets-ssh-keys-certificates--os-password-files-across-all-oses)
  12. [Restrict Browser Subagent & Web Fetching to Internal / Approved Domains Only (Disable Browser JS)](#example-12-restrict-browser-subagent--web-fetching-to-internal--approved-domains-only-disable-browser-js)
* **Part IV — Model Context Protocol (MCP) Server & Tool Governance**
  13. [Block a Specific MCP Server (or Block *All* MCP Servers Globally)](#example-13-block-a-specific-mcp-server-or-block-all-mcp-servers-globally)
  14. [Allow *Only* Approved Corporate MCP Servers (Including Blocking Repo-Local `.agents/mcp_config.json`)](#example-14-allow-only-approved-corporate-mcp-servers-including-blocking-repo-local-agentsmcp_configjson)
  15. [Block Destructive Tools or Require Human Approval (`ask`) for Specific Tools Inside a Working MCP Server](#example-15-block-destructive-tools-or-require-human-approval-ask-for-specific-tools-inside-a-working-mcp-server)
* **Part V — Advanced Lifecycle Hooks (Mandatory Prompts, Inline DLP & Argument Rewriting)**
  16. [Inject Mandatory Corporate Coding & Security Directives Automatically at Every `SessionStart`](#example-16-inject-mandatory-corporate-coding--security-directives-automatically-at-every-sessionstart)
  17. [Inline DLP on Agent File Writes — Block Hardcoded API Keys & Private Keys (`PreToolUse` JSON `decision: "deny"`)](#example-17-inline-dlp-on-agent-file-writes--block-hardcoded-api-keys--private-keys-pretooluse-json-decision-deny)
  18. [Dynamically Rewrite or Sanitize Agent Tool Arguments via `PreToolUse` `overwrite` (Enforce Internal Package Mirrors / Safe Flags)](#example-18-dynamically-rewrite-or-sanitize-agent-tool-arguments-via-pretooluse-overwrite-enforce-internal-package-mirrors--safe-flags)
* **Part VI — Fleet Operations (Multi-User VDI Golden Images, Key Rotation & Tamper-Proof OS Locks)**
  19. [Pre-Seed Multi-User Golden OS Skeleton Profiles (`/etc/skel`, macOS User Template, `C:\Users\Default`) for Shared VDI & Cloud Workstations](#example-19-pre-seed-multi-user-golden-os-skeleton-profiles-etcskel-macos-user-template-cusersdefault-for-shared-vdi--cloud-workstations)
  20. [Zero-Downtime `GATEWAY_API_KEY` Rotation, SIEM JSONL Forwarding & Tamper-Proof OS Kernel / NTFS Locking](#example-20-zero-downtime-gateway_api_key-rotation-siem-jsonl-forwarding--tamper-proof-os-kernel--ntfs-locking)

---

## Part I — Gateway Connectivity, TLS, Models, FinOps & Wire Protocols

### Example 1: Route All Surfaces Through Enterprise Gateway, Trust Private Root CA & Suppress Google Login

* **Admin Goal**: Ensure developers never sign in with personal or consumer Google accounts, route 100% of inference traffic through your internal TLS-terminated Enterprise Gateway, and prevent developers from overriding the gateway URL via `AGY_LLM_GATEWAY_URL` or `~/.antigravity/settings.json`.
* **Surfaces Affected**: `AGY CLI`, `AGY Desktop App`, `AGY Web Hub (agy --hub)`, `VS Code`, `Visual Studio`, `JetBrains IDEs`, `Zed Editor`. *(Setting `"enabled": true` automatically suppresses interactive Google OAuth login across CLI, Desktop, Web Hub, and VS Code.)*
* **Target File & OS Locations**:
  * **File Name**: `admin_settings.json`
  * **Linux**: `/etc/antigravity/admin_settings.json`
  * **macOS**: `/Library/Application Support/Antigravity/admin_settings.json`
  * **Windows**: `C:\ProgramData\Antigravity\admin_settings.json`

#### Complete `admin_settings.json` Example (Linux / macOS with Custom PEM Bundle)

```json
{
  "caCertPath": "/etc/ssl/certs/ca-certificates.crt",
  "gateway": {
    "enabled": true,
    "url": "https://agy-gateway.internal.corp.example.com",
    "apiKey": "REPLACE_WITH_GATEWAY_API_KEY",
    "wireProtocol": "genai"
  }
}
```

> **OS TLS Note**:
> * On **macOS**, point `caCertPath` to `"/etc/ssl/cert.pem"` (or your deployed corporate PEM file such as `"/Library/Application Support/Antigravity/corp-root-ca.pem"`).
> * On **Windows**, either omit `"caCertPath"` if your corporate Root CA is already pushed to the Windows LocalMachine Certificate Store via Group Policy/Intune, or set `"caCertPath": "C:\\ProgramData\\Antigravity\\corp-root-ca.pem"`.

---

### Example 2: Restrict the Selectable Model Catalog (Allow Approved Models Only & Pin Default Model)

* **Admin Goal**: Restrict developers so they can **only** choose `gemini-3.8-flash` (pinned as default) and `gemini-3.1-pro-preview`, hiding experimental or unapproved models across CLI `/model`, Desktop dropdowns, and IDE pickers.
* **Surfaces Affected**: `AGY CLI`, `AGY Desktop App`, `AGY Web Hub (agy --hub)`, `VS Code`, `Visual Studio`, `JetBrains IDEs`, `Zed Editor`.
* **Target File & OS Locations**:
  * **File Name**: `admin_settings.json`
  * **Linux**: `/etc/antigravity/admin_settings.json`
  * **macOS**: `/Library/Application Support/Antigravity/admin_settings.json`
  * **Windows**: `C:\ProgramData\Antigravity\admin_settings.json`

#### Complete `admin_settings.json` Example

```json
{
  "gateway": {
    "enabled": true,
    "url": "https://agy-gateway.internal.corp.example.com",
    "apiKey": "REPLACE_WITH_GATEWAY_API_KEY",
    "wireProtocol": "genai"
  },
  "models": {
    "defaultModelId": "gemini-3.8-flash",
    "list": [
      {
        "modelId": "gemini-3.8-flash",
        "displayName": "Gemini 3.8 Flash (Standard)"
      },
      {
        "modelId": "gemini-3.1-pro-preview",
        "displayName": "Gemini 3.1 Pro (Architecture & Deep Reasoning)"
      }
    ],
    "tiers": {
      "flash": [
        "gemini-3.8-flash"
      ],
      "pro": [
        "gemini-3.1-pro-preview"
      ],
      "flashLite": [
        "gemini-3.8-flash"
      ]
    }
  }
}
```

---

### Example 3: Enforce Non-Overridable FinOps Attribution Headers & Per-Developer API Keys

* **Admin Goal**: Lock `gateway.url` and FinOps chargeback headers (`X-Cost-Center`, `X-Corporate-BU`, `X-Goog-User-Project`) at Tier-1 MDM so developers cannot spoof billing attribution, while omitting `gateway.apiKey` from the shared machine-readable `admin_settings.json` so each developer authenticates with their own individual Tier-2 `AGY_LLM_GATEWAY_API_KEY`.
* **Surfaces Affected**: `AGY CLI`, `AGY Desktop App`, `AGY Web Hub (agy --hub)`, `VS Code`, `Visual Studio`, `JetBrains IDEs`, `Zed Editor`.
* **How 3-Tier Merge Works Here**: Antigravity merges Tier-1 (`admin_settings.json`) and Tier-2 (`AGY_LLM_GATEWAY_*` env vars) field-by-field. Tier-1 locks `url`, `enabled`, and `customHeaders` (and overrides any colliding header keys set by a user); Tier-2 supplies each user's `AGY_LLM_GATEWAY_API_KEY`.
* **Target File & OS Locations**:
  1. **Machine-Wide MDM File (`admin_settings.json`)**:
     * **Linux**: `/etc/antigravity/admin_settings.json`
     * **macOS**: `/Library/Application Support/Antigravity/admin_settings.json`
     * **Windows**: `C:\ProgramData\Antigravity\admin_settings.json`
  2. **Per-User Environment Variable**:
     * **Linux / macOS**: `/etc/profile.d/agy-user-key.sh` or developer's OS keychain export
     * **Windows**: User-scope Environment Variable (`[Environment]::SetEnvironmentVariable("AGY_LLM_GATEWAY_API_KEY", "...", "User")`)

#### Step 1 — Machine-Wide `admin_settings.json` (No Shared Key Stored on Disk)

```json
{
  "gateway": {
    "enabled": true,
    "url": "https://agy-gateway.internal.corp.example.com",
    "wireProtocol": "genai",
    "customHeaders": {
      "X-Cost-Center": "CC-4410-PAYMENTS",
      "X-Corporate-BU": "Retail-Banking-Engineering",
      "X-Goog-User-Project": "corp-payments-vertex-quota"
    }
  },
  "models": {
    "defaultModelId": "gemini-3.8-flash",
    "list": [
      {
        "modelId": "gemini-3.8-flash",
        "displayName": "Gemini 3.8 Flash"
      }
    ]
  }
}
```

#### Step 2 — Per-User Environment Variable (`AGY_LLM_GATEWAY_API_KEY`)

```bash
# Linux / macOS user session:
export AGY_LLM_GATEWAY_API_KEY="REPLACE_WITH_PER_DEVELOPER_TOKEN"
```

```powershell
# Windows PowerShell (User scope):
[System.Environment]::SetEnvironmentVariable("AGY_LLM_GATEWAY_API_KEY", "REPLACE_WITH_PER_DEVELOPER_TOKEN", "User")
```

---

### Example 4: Configure JetBrains IDEs & Zed Editor Plugins for Enterprise Gateway (`ACP`)

* **Admin Goal**: Enable Antigravity inside **IntelliJ IDEA / PyCharm / GoLand / WebStorm** and **Zed** without interactive browser login, even when launched from GUI desktop icons that ignore `~/.bashrc` / `~/.zshrc`.
* **Surfaces Affected**: `JetBrains IDEs` and `Zed Editor` (`ACP Server v1.3.0+`).
* **Critical Constraint**: `wireProtocol` **must** be `"genai"`. When properly configured, `agy acp` returns `"authMethods": []` during JSON-RPC `initialize` (meaning zero interactive login prompt).
* **Target Files & OS Locations**:
  1. **ACP Auth Mode File** (named **`settings.json`** on disk):
     * **Linux**: `/home/<USER>/.gemini/antigravity-acp/settings.json`
     * **macOS**: `/Users/<USER>/.gemini/antigravity-acp/settings.json`
     * **Windows**: `C:\Users\<USER>\.gemini\antigravity-acp\settings.json`
  2. **JetBrains ACP Registry (`acp.json`)**:
     * **Linux**: `/home/<USER>/.jetbrains/acp.json`
     * **macOS**: `/Users/<USER>/.jetbrains/acp.json`
     * **Windows**: `C:\Users\<USER>\.jetbrains\acp.json`
  3. **Zed Editor Settings (`settings.json`)**:
     * **Linux**: `/home/<USER>/.config/zed/settings.json`
     * **macOS**: `/Users/<USER>/Library/Application Support/Zed/settings.json`
     * **Windows**: `C:\Users\<USER>\AppData\Roaming\Zed\settings.json`

#### File 1 — `antigravity-acp/settings.json` (Identical on Linux, macOS & Windows)

```json
{
  "auth": {
    "type": "gateway"
  }
}
```

#### File 2A — `acp.json` / Zed `settings.json` for Linux & macOS

*(On macOS Homebrew installs, adjust `command` to `"/opt/homebrew/bin/agy"` if `agy` is installed there.)*

```json
{
  "agent_servers": {
    "Antigravity": {
      "command": "/usr/local/bin/agy",
      "args": [
        "acp"
      ],
      "env": {
        "AGY_LLM_GATEWAY_URL": "https://agy-gateway.internal.corp.example.com",
        "AGY_LLM_GATEWAY_API_KEY": "REPLACE_WITH_GATEWAY_API_KEY",
        "AGY_LLM_GATEWAY_WIRE_PROTOCOL": "genai",
        "AGY_LLM_GATEWAY_HEADERS": "X-Cost-Center: CC-4410-PAYMENTS,X-Corporate-BU: Retail-Banking",
        "AGY_LLM_GATEWAY_MODELS": "gemini-3.8-flash,gemini-3.1-pro-preview"
      }
    }
  }
}
```

#### File 2B — `acp.json` / Zed `settings.json` for Windows

```json
{
  "agent_servers": {
    "Antigravity": {
      "command": "C:\\Program Files\\Antigravity\\bin\\agy.exe",
      "args": [
        "acp"
      ],
      "env": {
        "AGY_LLM_GATEWAY_URL": "https://agy-gateway.internal.corp.example.com",
        "AGY_LLM_GATEWAY_API_KEY": "REPLACE_WITH_GATEWAY_API_KEY",
        "AGY_LLM_GATEWAY_WIRE_PROTOCOL": "genai",
        "AGY_LLM_GATEWAY_HEADERS": "X-Cost-Center: CC-4410-PAYMENTS,X-Corporate-BU: Retail-Banking",
        "AGY_LLM_GATEWAY_MODELS": "gemini-3.8-flash,gemini-3.1-pro-preview"
      }
    }
  }
}
```

---

### Example 5: Switch Inference Wire Protocol to OpenAI Chat Completions (`wireProtocol: "openai"`) & ACP Boundaries

* **Admin Goal**: Route inference payloads using the OpenAI Chat Completions wire format (`POST /v1/chat/completions`) — for example, when routing through the Antigravity Enterprise Gateway's `/v1/chat/completions` endpoint, Apigee OpenAI facade, or LiteLLM — while keeping Model Armor & Cloud SDP prompt screening active.
* **Surfaces Affected**:
  * **Supported**: `AGY CLI`, `AGY Desktop App`, `AGY Web Hub (agy --hub)`, `VS Code`, `Visual Studio`.
  * **NOT Supported**: `JetBrains IDEs` and `Zed Editor` (`ACP Server` officially supports **only** `wireProtocol: "genai"`; passing `AGY_LLM_GATEWAY_WIRE_PROTOCOL=openai` in `acp.json` causes ACP gateway auth to be skipped and fall back to interactive login `authMethods`, and `/v1/models` discovery is unsupported — keep `"genai"` whenever developers use JetBrains or Zed).
* **Target File & OS Locations**:
  * **File Name**: `admin_settings.json`
  * **Linux**: `/etc/antigravity/admin_settings.json`
  * **macOS**: `/Library/Application Support/Antigravity/admin_settings.json`
  * **Windows**: `C:\ProgramData\Antigravity\admin_settings.json`

#### Complete `admin_settings.json` Example (`openai` Wire Protocol)

```json
{
  "gateway": {
    "enabled": true,
    "url": "https://agy-gateway.internal.corp.example.com",
    "apiKey": "REPLACE_WITH_GATEWAY_API_KEY",
    "wireProtocol": "openai",
    "customHeaders": {
      "X-Cost-Center": "CC-9010-PLATFORM"
    }
  },
  "models": {
    "defaultModelId": "gemini-3.8-flash",
    "list": [
      {
        "modelId": "gemini-3.8-flash",
        "displayName": "Gemini 3.8 Flash (OpenAI Wire)"
      }
    ]
  }
}
```

---

## Part II — OS Sandboxing, Corporate Forward Proxies, Bastion Mode & Ephemeral Privacy

### Example 6: Enforce Terminal Sandboxing & Block File Access Outside the Project Workspace

* **Admin Goal**: Confine all agent file reads/writes strictly to the developer's active workspace (`/home/alice/workspace`), run all agent terminal commands inside the OS sandbox (`exebox` on Linux, `sandbox-exec` on macOS) with unrestricted sandbox internet disabled, and block reading arbitrary host directories.
* **Surfaces Affected**:
  * `settings.json` governs **AGY CLI**, **VS Code**, and **Visual Studio**.
  * `config.json` governs **AGY Desktop App** and **AGY Web Hub (`agy --hub`)** (and merges `globalPermissionGrants` into CLI).
* **Target Files & OS Locations**:
  * **File 1 (`settings.json`)**:
    * **Linux**: `/home/<USER>/.gemini/antigravity-cli/settings.json`
    * **macOS**: `/Users/<USER>/.gemini/antigravity-cli/settings.json`
    * **Windows**: `C:\Users\<USER>\.gemini\antigravity-cli\settings.json`
  * **File 2 (`config.json`)**:
    * **Linux**: `/home/<USER>/.gemini/config/config.json` *(mirror to `/home/<USER>/.gemini/config.json`)*
    * **macOS**: `/Users/<USER>/.gemini/config/config.json` *(mirror to `/Users/<USER>/.gemini/config.json`)*
    * **Windows**: `C:\Users\<USER>\.gemini\config\config.json` *(mirror to `C:\Users\<USER>\.gemini\config.json`)*

#### File 1 — `settings.json` (AGY CLI & VS Code — Linux Example for User `alice`)

```json
{
  "agentMode": "plan",
  "allowNonWorkspaceAccess": false,
  "artifactReviewPolicy": "asks-for-review",
  "enableTerminalSandbox": true,
  "permissions": {
    "allow": [
      "command(ls)",
      "command(pwd)",
      "command(git status)",
      "command(git diff)",
      "command(go test)",
      "command(pytest)",
      "read_file(/home/alice/workspace)",
      "read_file(/home/alice/.gemini)",
      "write_file(/home/alice/workspace)"
    ],
    "ask": [],
    "deny": [
      "write_file(/home/alice/.gemini)"
    ]
  },
  "toolPermission": "proceed-in-sandbox"
}
```

#### File 2 — `config.json` (AGY Desktop App & AGY Web Hub `agy --hub` — Linux Example for User `alice`)

```json
{
  "userSettings": {
    "enableTerminalSandbox": true,
    "sandboxAllowNetwork": false,
    "autoExecutionPolicy": "CASCADE_COMMANDS_AUTO_EXECUTION_PROCEED_IN_SANDBOX",
    "permissionPreset": "AGENT_PERMISSION_PRESET_DEFAULT",
    "artifactReviewMode": "ARTIFACT_REVIEW_MODE_ALWAYS",
    "nonWorkspaceFileAccessPolicy": "AGENT_SETTING_POLICY_DENY",
    "internetAccessPolicy": "AGENT_SETTING_POLICY_ASK",
    "globalPermissionGrants": {
      "allow": [
        "command(ls)",
        "command(pwd)",
        "command(git status)",
        "command(git diff)",
        "command(go test)",
        "command(pytest)",
        "read_file(/home/alice/workspace)",
        "read_file(/home/alice/.gemini)",
        "write_file(/home/alice/workspace)"
      ],
      "ask": [],
      "deny": [
        "write_file(/home/alice/.gemini)"
      ]
    }
  }
}
```

> **Three Critical Cross-OS Rules for Sandbox Paths**:
> 1. **Never put `"unsandboxed(*)"` in `deny`** — Antigravity's `unsandboxed` permission covers both unsandboxed and sandboxed executions, so denying `unsandboxed(*)` blocks sandboxed commands too. Use `"toolPermission": "proceed-in-sandbox"` instead.
> 2. **Keep `"read_file(/home/<USER>/.gemini)"` in `allow`** (while keeping `"write_file(/home/<USER>/.gemini)"` in `deny`) so lazy-loaded MCP tool schemas under `~/.gemini/antigravity-cli/mcp/` remain readable when `allowNonWorkspaceAccess` is `false`.
> 3. **Windows Adjustment**: Because Windows Server / Windows 10/11 CLI does not use Linux `exebox`, pair approved commands on Windows with `unsandboxed(...)` in `allow` (e.g., `"command(git status)"` + `"unsandboxed(git status)"`) — [`scripts/deploy_and_lock_windows.ps1`](./scripts/deploy_and_lock_windows.ps1) performs this injection automatically when `WINDOWS_ADD_UNSANDBOXED_ALLOW=true`.

---

### Example 7: Route Sandboxed Agent Network Traffic Through a Corporate Forward Proxy / SSL Inspection Gateway (`sandboxProxy`)

* **Admin Goal**: Force all outbound HTTP/HTTPS network requests originating inside sandboxed terminal commands (e.g., `go test` downloading modules from Artifactory or `pip` hitting an internal proxy) through your corporate Squid / Envoy / Zscaler forward proxy with TLS certificate verification.
* **Surfaces Affected**: `AGY CLI`, `VS Code`, `Visual Studio` (Linux `exebox` & macOS `sandbox-exec` sandboxes).
* **Critical Schema & Single-Certificate PEM Rules**:
  1. Both `sandboxProxy.http.address` (`host:port`) and `sandboxProxy.http.certFile` (PEM file path) **must** be specified together.
  2. **`certFile` MUST contain a SINGLE PEM X.509 certificate** (your corporate proxy's Root CA certificate, e.g., `/etc/antigravity/corp-proxy-root-ca.pem`). Do **NOT** point `sandboxProxy.http.certFile` at a concatenated multi-CA bundle like `/etc/ssl/certs/ca-certificates.crt`, because `exebox`'s `localcert` parser rejects multi-certificate files with `localcert: trailing data after certificate`.
* **Target File & OS Locations**:
  * **File Name**: `settings.json`
  * **Linux**: `/home/<USER>/.gemini/antigravity-cli/settings.json`
  * **macOS**: `/Users/<USER>/.gemini/antigravity-cli/settings.json`

#### Complete `settings.json` Example with `sandboxProxy`

```json
{
  "allowNonWorkspaceAccess": false,
  "enableTerminalSandbox": true,
  "permissions": {
    "allow": [
      "command(curl)",
      "command(go test)",
      "command(pytest)",
      "read_file(/home/alice/workspace)",
      "read_file(/etc/antigravity/corp-proxy-root-ca.pem)",
      "write_file(/home/alice/workspace)",
      "read_url(artifactory.internal.corp.example.com)",
      "read_url(pkg.go.dev)"
    ],
    "ask": [],
    "deny": []
  },
  "sandboxProxy": {
    "http": {
      "address": "proxy.internal.corp.example.com:8080",
      "certFile": "/etc/antigravity/corp-proxy-root-ca.pem"
    }
  },
  "toolPermission": "proceed-in-sandbox"
}
```

---

### Example 8: Enforce Maximum Zero-Trust "Strict Human-in-the-Loop" Mode on Production Bastions (`toolPermission: "strict"`)

* **Admin Goal**: On SRE jump-hosts, production bastions, or PCI-DSS regulated environments, require **interactive human approval before EVERY single agent action** (even actions listed in `allow`), while keeping `deny` rules enforced as non-overridable hard blocks.
* **Surfaces Affected**: `AGY CLI`, `AGY Desktop App`, `AGY Web Hub (agy --hub)`, `VS Code`, `Visual Studio`.
* **Runtime Behavior**:
  * In interactive TUI / Desktop / IDE mode, every command, file write, or MCP call pauses for explicit human confirmation.
  * In unattended headless mode (`agy -p "..."`), any tool-executing action is refused automatically because no human is present to approve it, while `deny` rules block prohibited commands unconditionally.
* **Target Files & OS Locations**:
  * **File 1 (`settings.json`)**: `/home/<USER>/.gemini/antigravity-cli/settings.json` (Linux) | `/Users/<USER>/.gemini/antigravity-cli/settings.json` (macOS) | `C:\Users\<USER>\.gemini\antigravity-cli\settings.json` (Windows)
  * **File 2 (`config.json`)**: `/home/<USER>/.gemini/config/config.json` (Linux) | `/Users/<USER>/.gemini/config/config.json` (macOS) | `C:\Users\<USER>\.gemini\config\config.json` (Windows)

#### File 1 — `settings.json` (Bastion Strict Mode)

```json
{
  "agentMode": "plan",
  "allowNonWorkspaceAccess": false,
  "artifactReviewPolicy": "asks-for-review",
  "enableTerminalSandbox": true,
  "permissions": {
    "allow": [],
    "ask": [],
    "deny": [
      "command(rm)",
      "command(sudo)",
      "command(ssh)",
      "command(kubectl delete)"
    ]
  },
  "toolPermission": "strict"
}
```

#### File 2 — `config.json` (Desktop & Web Hub Strict Review Preset)

```json
{
  "userSettings": {
    "enableTerminalSandbox": true,
    "sandboxAllowNetwork": false,
    "autoExecutionPolicy": "CASCADE_COMMANDS_AUTO_EXECUTION_OFF",
    "permissionPreset": "AGENT_PERMISSION_PRESET_REQUEST_REVIEW",
    "artifactReviewMode": "ARTIFACT_REVIEW_MODE_ALWAYS",
    "browserJsExecutionPolicy": "BROWSER_JS_EXECUTION_POLICY_DISABLED",
    "nonWorkspaceFileAccessPolicy": "AGENT_SETTING_POLICY_DENY",
    "internetAccessPolicy": "AGENT_SETTING_POLICY_DENY",
    "globalPermissionGrants": {
      "allow": [],
      "ask": [],
      "deny": [
        "command(rm)",
        "command(sudo)",
        "command(ssh)",
        "command(kubectl delete)"
      ]
    }
  }
}
```

---

### Example 9: Enforce Ephemeral / Zero-Disk-History Privacy Mode (`historySize: 0` & Telemetry UI Suppression)

* **Admin Goal**: Prevent Antigravity CLI from persisting developer prompt history on laptop SSDs at exit (`"historySize": 0`), suppress periodic quality feedback survey prompts (`"showFeedbackSurvey": false`), and hide onboarding tip banners (`"showTips": false`).
* **Surfaces Affected**: `AGY CLI`, `VS Code`, `Visual Studio`.
* **Target File & OS Locations**:
  * **File Name**: `settings.json`
  * **Linux**: `/home/<USER>/.gemini/antigravity-cli/settings.json`
  * **macOS**: `/Users/<USER>/.gemini/antigravity-cli/settings.json`
  * **Windows**: `C:\Users\<USER>\.gemini\antigravity-cli\settings.json`

#### Complete `settings.json` Privacy & Quiet-UI Example

```json
{
  "allowNonWorkspaceAccess": false,
  "enableTerminalSandbox": true,
  "historySize": 0,
  "notifications": false,
  "showFeedbackSurvey": false,
  "showTips": false,
  "toolPermission": "proceed-in-sandbox",
  "verbosity": "low"
}
```

*(Verified with `agy --version`: `MarshalSparse` retains `"historySize": 0`, `"showFeedbackSurvey": false`, `"showTips": false`, and `"verbosity": "low"` because they differ from built-in defaults.)*

---

## Part III — Command, File, Secret & Browser Subagent Controls

### Example 10: Block Destructive Commands (`rm`, `sudo`, `ssh`) While Requiring Human Approval (`ask`) for `git push` & `kubectl`

* **Admin Goal**: Allow safe read/test commands (`git status`, `pytest`) to run automatically, force an interactive human confirmation prompt (`ask`) before `git commit`, `git push`, `docker build`, or `kubectl apply`, and **permanently block** file deletion (`rm`, `del`, `Remove-Item`), privilege escalation (`sudo`, `runas`), and lateral movement (`ssh`, `scp`, `nc`).
* **Surfaces Affected**: `AGY CLI`, `AGY Desktop App`, `AGY Web Hub (agy --hub)`, `VS Code`, `Visual Studio`.
* **Precedence Rule**: `Deny > Ask > Allow`.
* **Target Files & OS Locations**:
  * `settings.json` (`~/.gemini/antigravity-cli/settings.json` on Linux/macOS; `%USERPROFILE%\.gemini\antigravity-cli\settings.json` on Windows)
  * `config.json` (`~/.gemini/config/config.json` on Linux/macOS; `%USERPROFILE%\.gemini\config\config.json` on Windows)
  * Paired with `hooks.json` + `agy_security_guard.{sh,ps1}` (so even `python3 -c "import os; os.remove(...)"` subshell bypasses are blocked with `exit 2`).

#### Permission Block Snippet (Place Inside `permissions` in `settings.json` AND `userSettings.globalPermissionGrants` in `config.json`)

```json
{
  "allow": [
    "command(echo)",
    "command(ls)",
    "command(git status)",
    "command(git diff)",
    "command(go test)",
    "command(pytest)",
    "command(regex:^(?i)(echo|write-output|write-host|ls|get-childitem|pwd|get-location)(\\s+[^;&|`$()\\r\\n>]*)?$)",
    "command(regex:^git\\s+(status|diff)(\\s+[^;&|`$()\\r\\n>]*)?$)",
    "command(regex:^(go\\s+test|pytest)(\\s+[^;&|`$()\\r\\n>]*)?$)"
  ],
  "ask": [
    "command(git commit)",
    "command(git push)",
    "command(docker build)",
    "unsandboxed(docker build)",
    "command(kubectl apply)",
    "command(terraform apply)",
    "command(regex:^git\\s+(commit|push)(\\s+.*)?$)",
    "command(regex:^(docker\\s+build|kubectl\\s+apply|terraform\\s+apply)(\\s+.*)?$)"
  ],
  "deny": [
    "command(rm)",
    "command(rmdir)",
    "command(unlink)",
    "command(shred)",
    "command(del)",
    "command(erase)",
    "command(Remove-Item)",
    "command(ri)",
    "command(regex:(?i)^(\\S*[/\\\\])?(rm|rmdir|unlink|shred|del|erase|rd|remove-item|ri)(\\.exe)?(\\s+.*|$))",
    "command(regex:(?i)^(\\S*[/\\\\])?(sudo|su|doas|pkexec|runas|chattr|chflags|icacls|takeown|ssh|scp|sftp|nc|netcat|socat)(\\.exe)?(\\s+.*|$))",
    "command(sudo)",
    "command(su)",
    "command(doas)",
    "command(pkexec)",
    "command(runas)",
    "command(chattr)",
    "command(chflags)",
    "command(icacls)",
    "command(takeown)",
    "command(ssh)",
    "command(scp)",
    "command(sftp)",
    "command(nc)",
    "command(netcat)",
    "command(socat)"
  ]
}
```

> **Windows PowerShell Exact-Match Nuance (`agy.exe 1.4.12+`)**: On Linux and macOS (`bash` / `zsh`), simple shell commands are AST-parsed and matched by token prefix (so `"command(echo)"` covers `echo hello`). On Windows (`powershell` / `pwsh`), Antigravity forces `RequiresExactMatch = true` (`MatchesConfigAnyRaw`) because PowerShell syntax is not decomposed into POSIX AST tokens — meaning a bare literal rule like `"command(echo)"` only matches the exact 0-argument string `"echo"`. Including the anchored `command(regex:...)` rules above (`(\s+[^;&|`$()\r\n>]*)?$`) allows safe single-command arguments on Windows PowerShell while rejecting chained `;`, `|`, `&`, `` ` ``, `$(...)`, newline, and `>` redirection injections. `scripts\deploy_and_lock_windows.ps1` also generates these safe PowerShell `regex:` companions automatically during Windows deployment.

---

### Example 11: Block Agent Access to Secrets, SSH Keys, Certificates & OS Password Files Across All OSes

* **Admin Goal**: Prevent the AI agent from reading `/etc/shadow`, `/etc/sudoers`, macOS Keychains, `~/.ssh` keys, cloud credentials (`~/.aws`, `~/.kube`), `.env` files, `.pem`/`.key` certificates, or Windows `SAM` / `SYSTEM` / `NTDS.dit` hives.
* **Surfaces Affected**: `AGY CLI`, `AGY Desktop App`, `AGY Web Hub (agy --hub)`, `VS Code`, `Visual Studio`.
* **Why Two Files Work Together**:
  1. On **Linux & macOS**, `read_file(...)` / `write_file(...)` rules in `settings.json` and `config.json` must use **exact POSIX paths starting with `/`** (no `*` globs and no `C:\` Windows drive letters, which would break Linux `exebox` bind-mount parsing).
  2. Wildcard extensions (`*.pem`, `*.key`, `.env`) and Windows paths (`C:\Windows\System32\config\SAM`) are enforced synchronously across **Linux, macOS, and Windows** by `hooks.json` invoking `agy_security_guard.sh` / `agy_security_guard.ps1` (`exit 2`).
* **Target Files & OS Locations**:
  * **POSIX File Denies**: `settings.json` & `config.json` (Linux & macOS paths)
  * **Hook Configuration (`hooks.json`)**:
    * **Linux**: `/home/<USER>/.gemini/config/hooks.json`
    * **macOS**: `/Users/<USER>/.gemini/config/hooks.json`
    * **Windows**: `C:\Users\<USER>\.gemini\config\hooks.json`
  * **Guard Scripts**:
    * **Linux & macOS**: `/usr/local/bin/agy_security_guard.sh` (`0755`, `root:root` / `root:wheel`)
    * **Windows**: `C:\ProgramData\Antigravity\bin\agy_security_guard.ps1`

#### Part A — POSIX Path Denies in `settings.json` & `config.json` (Linux / macOS User `alice`)

```json
{
  "deny": [
    "read_file(/etc/shadow)",
    "read_file(/etc/gshadow)",
    "read_file(/etc/passwd)",
    "read_file(/etc/sudoers)",
    "read_file(/etc/ssh)",
    "read_file(/etc/ssl/private)",
    "read_file(/etc/kubernetes)",
    "read_file(/etc/antigravity/admin_settings.json)",
    "read_file(/private/etc/master.passwd)",
    "read_file(/Library/Keychains)",
    "read_file(/Library/Application Support/Antigravity/admin_settings.json)",
    "read_file(/home/alice/.ssh)",
    "read_file(/home/alice/.gnupg)",
    "read_file(/home/alice/.aws)",
    "read_file(/home/alice/.kube)",
    "read_file(/Users/alice/.ssh)",
    "read_file(/Users/alice/.gnupg)",
    "read_file(/Users/alice/.aws)",
    "read_file(/Users/alice/.kube)"
  ]
}
```

#### Part B — `hooks.json` for Windows (Invoking `agy_security_guard.ps1` Without Inner Quotes)

*(On Linux/macOS, `command` is `"/usr/local/bin/agy_security_guard.sh pre"` and `"post"`, as in [`configs/06-lifecycle-hooks/hooks.json`](./configs/06-lifecycle-hooks/hooks.json).)*

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\ProgramData\\Antigravity\\bin\\agy_security_guard.ps1 pre",
            "timeout": 10
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\ProgramData\\Antigravity\\bin\\agy_security_guard.ps1 post",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

---

### Example 12: Restrict Browser Subagent & Web Fetching to Internal / Approved Domains Only (Disable Browser JS)

* **Admin Goal**: Allow the agent to read documentation and preview apps **only** on `localhost`, `127.0.0.1`, `docs.cloud.google.com`, and `docs.internal.corp.example.com`; block paste sites, webhooks, tunnels (`ngrok.io`, `pastebin.com`, `webhook.site`), and cloud metadata SSRF (`169.254.169.254`, `metadata.google.internal`); and disable Browser Subagent JavaScript execution.
* **Surfaces Affected**: `AGY Desktop App`, `AGY Web Hub (agy --hub)`, `VS Code`, `AGY CLI` (`read_url_content`, sandboxed network sockets, and `/browser`).
* **Target Files & OS Locations**:
  1. **`browserAllowlist.txt`**:
     * **Linux**: `/home/<USER>/.gemini/antigravity/browserAllowlist.txt`
     * **macOS**: `/Users/<USER>/.gemini/antigravity/browserAllowlist.txt`
     * **Windows**: `C:\Users\<USER>\.gemini\antigravity\browserAllowlist.txt`
  2. **`config.json`** (`~/.gemini/config/config.json` / `%USERPROFILE%\.gemini\config\config.json`)
  3. **`settings.json`** (`~/.gemini/antigravity-cli/settings.json` / `%USERPROFILE%\.gemini\antigravity-cli\settings.json`)

#### File 1 — Complete `browserAllowlist.txt`

```text
# Enterprise Approved Browser Subagent Domains (Locked by IT Security)
localhost
127.0.0.1
antigravity.google
docs.cloud.google.com
docs.internal.corp.example.com
```

#### File 2 — `config.json` Browser & URL Policy Snippet

```json
{
  "userSettings": {
    "sandboxAllowNetwork": false,
    "browserJsExecutionPolicy": "BROWSER_JS_EXECUTION_POLICY_DISABLED",
    "internetAccessPolicy": "AGENT_SETTING_POLICY_DENY",
    "globalPermissionGrants": {
      "allow": [
        "read_url(localhost)",
        "read_url(127.0.0.1)",
        "read_url(docs.cloud.google.com)",
        "read_url(docs.internal.corp.example.com)"
      ],
      "ask": [
        "execute_url(localhost)"
      ],
      "deny": [
        "read_url(169.254.169.254)",
        "read_url(metadata.google.internal)",
        "read_url(pastebin.com)",
        "read_url(webhook.site)",
        "read_url(ngrok.io)",
        "read_url(ngrok-free.app)",
        "read_url(trycloudflare.com)",
        "execute_url(169.254.169.254)",
        "execute_url(metadata.google.internal)",
        "execute_url(webhook.site)"
      ]
    }
  }
}
```

*(Mirror the exact same `read_url(...)` and `execute_url(...)` entries inside `permissions` in `settings.json` for AGY CLI and VS Code.)*

---

## Part IV — Model Context Protocol (MCP) Server & Tool Governance

### Example 13: Block a Specific MCP Server (or Block *All* MCP Servers Globally)

* **Admin Goal**:
  * **Case A**: Block specific risky MCP servers (such as `github`, `slack`, `postgres`, or `untrusted_external`) even if a developer defines them inside a project's `<repo>/.agents/mcp_config.json`.
  * **Case B**: Completely disable **all** MCP servers across the workstation (`"mcp(*)"`).
* **Surfaces Affected**: `AGY CLI`, `AGY Desktop App`, `AGY Web Hub (agy --hub)`, `VS Code`, `Visual Studio`.
* **Critical `eager` vs. `lazy` MCP Permission Rule**:
  * `permissions.{allow,ask,deny}` `mcp(<server>/<tool>)` and `mcp(*)` rules are evaluated by `call_mcp_tool` (**default lazy-loaded MCP mode**).
  * Do **NOT** set `"tools": {"<tool>": {"eager": true}}` on MCP servers/tools that you want governed by `mcp(...)` `ask` or `deny` permission rules, because `"eager": true` registers tools directly as native `mcp_<server>_<tool>` functions and bypasses `call_mcp_tool`'s `mcp(...)` permission check (use `disabledTools` or a `PreToolUse` hook as in Example 14 if eager tools exist in workspace configs).
* **Target Files & OS Locations**:
  1. **`mcp_config.json`**:
     * **Linux**: `/home/<USER>/.gemini/config/mcp_config.json`
     * **macOS**: `/Users/<USER>/.gemini/config/mcp_config.json`
     * **Windows**: `C:\Users\<USER>\.gemini\config\mcp_config.json`
  2. **`settings.json`** (`~/.gemini/antigravity-cli/settings.json` / `%USERPROFILE%\.gemini\antigravity-cli\settings.json`)
  3. **`config.json`** (`~/.gemini/config/config.json` / `%USERPROFILE%\.gemini\config\config.json`)

#### Case A — Block Specific MCP Servers (`github`, `slack`, `untrusted_external`) While Keeping `catalog` Active

In `mcp_config.json`:
```json
{
  "mcpServers": {
    "catalog": {
      "command": "/usr/local/bin/mock_mcp_server.py",
      "args": [
        "catalog"
      ],
      "disabled": false
    },
    "untrusted_external": {
      "command": "npx",
      "args": [
        "-y",
        "@untrusted/external-mcp-server"
      ],
      "disabled": true,
      "enabledTools": [],
      "disabledTools": [
        "*"
      ]
    }
  }
}
```

In `settings.json` (`permissions`) and `config.json` (`userSettings.globalPermissionGrants`):
```json
{
  "allow": [
    "mcp(catalog/*)"
  ],
  "ask": [],
  "deny": [
    "mcp(untrusted_external/*)",
    "mcp(github/*)",
    "mcp(slack/*)",
    "mcp(postgres/*)"
  ]
}
```

#### Case B — Block *All* MCP Servers Globally

Place `{ "mcpServers": {} }` in locked `mcp_config.json` **and** add `"mcp(*)"` to `deny` in both `settings.json` and `config.json`:
```json
{
  "allow": [],
  "ask": [],
  "deny": [
    "mcp(*)"
  ]
}
```
*(Because `Deny > Ask > Allow`, `"mcp(*)"` in `deny` overrides every `allow` rule and blocks 100% of MCP servers, including workspace `.agents/mcp_config.json` and plugin-bundled `mcp.json` servers.)*

---

### Example 14: Allow *Only* Approved Corporate MCP Servers (Including Blocking Repo-Local `.agents/mcp_config.json`)

* **Admin Goal**: Allow developers to use **only** two vetted corporate MCP servers (`catalog` and `corp_docs`), and guarantee that if a developer clones a git repository containing `<repo>/.agents/mcp_config.json` with an arbitrary new server name (e.g., `shadow_ai`), that unapproved MCP server is hard-blocked before any tool call runs.
* **How Antigravity Serializes MCP Calls in `PreToolUse` `stdin`**:
  * **Eager MCP tools** pass `"toolCall": {"args": {...}, "name": "mcp_<server>_<tool>"}`.
  * **Lazy MCP tools** pass `"toolCall": {"args": {"ServerName": "<server>", "ToolName": "<tool>", ...}, "name": "call_mcp_tool"}` (or `list_resources` / `read_resource` with `ServerName`).
* **Surfaces Affected**: `AGY CLI`, `AGY Desktop App`, `AGY Web Hub (agy --hub)`, `VS Code`, `Visual Studio`.
* **Target Files & OS Locations**:
  * `mcp_config.json` (`~/.gemini/config/mcp_config.json` / `%USERPROFILE%\.gemini\config\mcp_config.json`)
  * `settings.json` & `config.json`
  * Guard Script:
    * **Linux / macOS**: `/usr/local/bin/agy_security_guard.sh`
    * **Windows**: `C:\ProgramData\Antigravity\bin\agy_security_guard.ps1`

#### Step 1 — Approved `mcp_config.json`

```json
{
  "mcpServers": {
    "catalog": {
      "serverUrl": "https://mcp-catalog.internal.corp.example.com/mcp/",
      "authProviderType": "google_credentials",
      "disabled": false
    },
    "corp_docs": {
      "serverUrl": "https://mcp-corp-docs.internal.corp.example.com/mcp/",
      "headers": {
        "X-Corporate-BU": "Engineering"
      },
      "disabled": false
    }
  }
}
```

#### Step 2 — Strict MCP Server Allowlist Check in `agy_security_guard.sh` (Linux & macOS)

Add this check inside `evaluate_pre_tool_rules()` in `/usr/local/bin/agy_security_guard.sh`:

```bash
  # Domain 6: Strict MCP Server Allowlist (Permit ONLY 'catalog' and 'corp_docs')
  if printf '%s' "${payload}" | grep -Eq '("name"\s*:\s*"mcp_|"name"\s*:\s*"call_mcp_tool"|"ServerName"\s*:)'; then
    if ! printf '%s' "${payload}" | grep -Eq '("name"\s*:\s*"mcp_(catalog|corp_docs)_|"ServerName"\s*:\s*"(catalog|corp_docs)")'; then
      block_with_violation "RULE-6-MCP-ALLOWLIST" "Unapproved MCP server blocked. Only 'catalog' and 'corp_docs' MCP servers are permitted."
    fi
  fi
```

#### Equivalent Check in `agy_security_guard.ps1` (Windows)

Add this check inside `Invoke-PreToolPolicyCheck` in `C:\ProgramData\Antigravity\bin\agy_security_guard.ps1`:

```powershell
    # Domain 6: Strict MCP Server Allowlist (Permit ONLY 'catalog' and 'corp_docs')
    if ($InputPayload -match '("name"\s*:\s*"mcp_|"name"\s*:\s*"call_mcp_tool"|"ServerName"\s*:)') {
        if ($InputPayload -notmatch '("name"\s*:\s*"mcp_(catalog|corp_docs)_|"ServerName"\s*:\s*"(catalog|corp_docs)")') {
            Stop-WithPolicyViolation -RuleId "RULE-6-MCP-ALLOWLIST" `
                -Message "Unapproved MCP server blocked. Only 'catalog' and 'corp_docs' MCP servers are permitted."
        }
    }
```

---

### Example 15: Block Destructive Tools or Require Human Approval (`ask`) for Specific Tools Inside a Working MCP Server

* **Admin Goal**: Keep the `corp_docs` MCP server active so developers can freely call read-only tools (`read_doc`, `search_docs`), force a human review prompt (`ask`) when creating tickets (`create_ticket`), and **completely block** destructive admin tools (`delete_repository`, `grant_external_access`, `modify_acl`) on that same MCP server.
* **Surfaces Affected**: `AGY CLI`, `AGY Desktop App`, `AGY Web Hub (agy --hub)`, `VS Code`, `Visual Studio`.
* **Two-Layer Defense**:
  1. **`mcp_config.json` (`enabledTools` + `disabledTools`)** strips `delete_repository`, `grant_external_access`, and `modify_acl` from the tool catalog so the LLM never sees them.
  2. **`settings.json` & `config.json` (`mcp(corp_docs/<tool>)`)** enforce runtime `allow`, `ask`, and `deny` decisions per tool.
* **Target Files & OS Locations**:
  * `mcp_config.json` (`~/.gemini/config/mcp_config.json` / `%USERPROFILE%\.gemini\config\mcp_config.json`)
  * `settings.json` (`~/.gemini/antigravity-cli/settings.json` / `%USERPROFILE%\.gemini\antigravity-cli\settings.json`)
  * `config.json` (`~/.gemini/config/config.json` / `%USERPROFILE%\.gemini\config\config.json`)

#### File 1 — `mcp_config.json` (Per-Server Tool Allowlist & Denylist — Default Lazy Mode)

*(Keep default lazy tool loading — i.e., omit `"eager": true` — so `call_mcp_tool` enforces the per-tool `allow` / `ask` / `deny` rules in `settings.json` and `config.json` below.)*

```json
{
  "mcpServers": {
    "corp_docs": {
      "serverUrl": "https://mcp-corp-docs.internal.corp.example.com/mcp/",
      "disabled": false,
      "timeoutSeconds": 180,
      "enabledTools": [
        "read_doc",
        "search_docs",
        "create_ticket"
      ],
      "disabledTools": [
        "delete_repository",
        "grant_external_access",
        "modify_acl"
      ]
    }
  }
}
```

#### File 2 — `permissions` in `settings.json` AND `userSettings.globalPermissionGrants` in `config.json`

```json
{
  "allow": [
    "mcp(corp_docs/read_doc)",
    "mcp(corp_docs/search_docs)"
  ],
  "ask": [
    "mcp(corp_docs/create_ticket)"
  ],
  "deny": [
    "mcp(corp_docs/delete_repository)",
    "mcp(corp_docs/grant_external_access)",
    "mcp(corp_docs/modify_acl)"
  ]
}
```

---

## Part V — Advanced Lifecycle Hooks (Mandatory Prompts, Inline DLP & Argument Rewriting)

### Example 16: Inject Mandatory Corporate Coding & Security Directives Automatically at Every `SessionStart`

* **Admin Goal**: Automatically inject your organization's mandatory secure-coding standards, compliance banner, or internal package-mirror rules into **every** new Antigravity conversation (even in empty directories without a `GEMINI.md` file) using a locked `SessionStart` hook returning `injectSteps`.
* **Surfaces Affected**: `AGY CLI`, `AGY Desktop App`, `AGY Web Hub (agy --hub)`, `VS Code`, `Visual Studio`.
* **Target Files & OS Locations**:
  1. **`hooks.json`**:
     * **Linux**: `/home/<USER>/.gemini/config/hooks.json`
     * **macOS**: `/Users/<USER>/.gemini/config/hooks.json`
     * **Windows**: `C:\Users\<USER>\.gemini\config\hooks.json`
  2. **Session Policy Injector Script**:
     * **Linux / macOS**: `/usr/local/bin/agy_session_banner.sh` (`0755`, `root:root` / `root:wheel`)
     * **Windows**: `C:\ProgramData\Antigravity\bin\agy_session_banner.ps1`

#### Step 1A — Linux / macOS Script (`/usr/local/bin/agy_session_banner.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail
cat >/dev/null
printf '%s\n' '{"injectSteps":[{"ephemeralMessage":"MANDATORY CORPORATE AI POLICY [CORP-SEC-2026]: (1) Never hardcode API keys, passwords, or private keys in source files; load from environment variables. (2) Use only internal package registries. (3) Include unit tests for every security-sensitive function."}]}'
```

#### Step 1B — Windows PowerShell Script (`C:\ProgramData\Antigravity\bin\agy_session_banner.ps1`)

```powershell
$null = [Console]::In.ReadToEnd()
$Banner = @{
    injectSteps = @(
        @{
            ephemeralMessage = "MANDATORY CORPORATE AI POLICY [CORP-SEC-2026]: (1) Never hardcode API keys, passwords, or private keys in source files; load from environment variables. (2) Use only internal package registries. (3) Include unit tests for every security-sensitive function."
        }
    )
} | ConvertTo-Json -Depth 5 -Compress
[Console]::Out.WriteLine($Banner)
exit 0
```

#### Step 2 — `hooks.json` Wiring `SessionStart` Alongside `PreToolUse` & `PostToolUse` (Linux / macOS Example)

*(On Windows, replace the command string with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\ProgramData\\Antigravity\\bin\\agy_session_banner.ps1`.)*

```json
{
  "hooks": {
    "SessionStart": [
      {
        "type": "command",
        "command": "/usr/local/bin/agy_session_banner.sh",
        "timeout": 5
      }
    ],
    "PreToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/local/bin/agy_security_guard.sh pre",
            "timeout": 10
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/local/bin/agy_security_guard.sh post",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

---

### Example 17: Inline DLP on Agent File Writes — Block Hardcoded API Keys & Private Keys (`PreToolUse` JSON `decision: "deny"`)

* **Admin Goal**: Inspect every proposed file creation or code edit (`write_file`, `edit_file`, `write_to_file`, `replace_file_content`, `multi_replace_file_content`, `sed_file`) *before* bytes hit the disk, and return structured `{"decision": "deny", "reason": "..."}` if the agent attempts to write AWS keys (`AKIA...`), GCP service account private keys (`-----BEGIN PRIVATE KEY-----`), or GitHub tokens (`ghp_...`) into source code.
* **Surfaces Affected**: `AGY CLI`, `AGY Desktop App`, `AGY Web Hub (agy --hub)`, `VS Code`, `Visual Studio`.
* **Target Files & OS Locations**:
  * **`hooks.json`**: `/home/<USER>/.gemini/config/hooks.json` (Linux) | `/Users/<USER>/.gemini/config/hooks.json` (macOS) | `C:\Users\<USER>\.gemini\config\hooks.json` (Windows)
  * **Inline DLP Script**:
    * **Linux / macOS**: `/usr/local/bin/agy_dlp_file_guard.py` (`0755`)
    * **Windows**: `C:\ProgramData\Antigravity\bin\agy_dlp_file_guard.ps1`

#### Step 1A — Linux / macOS Inline DLP Guard (`/usr/local/bin/agy_dlp_file_guard.py`)

```python
#!/usr/bin/env python3
"""Blocks agent file writes containing hardcoded credentials via PreToolUse JSON stdout."""
import json
import re
import sys

SECRET_PATTERNS = [
    ("AWS_ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("PEM_PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("GITHUB_PAT", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
]

event = json.loads(sys.stdin.read() or "{}")
args_blob = json.dumps(event.get("toolCall", {}).get("args", {}))

for label, pattern in SECRET_PATTERNS:
    if pattern.search(args_blob):
        print(json.dumps({
            "decision": "deny",
            "reason": f"INLINE_DLP_BLOCK [{label}]: Hardcoded credentials cannot be written to files. Use environment variables instead."
        }))
        sys.exit(0)

print(json.dumps({"decision": "allow"}))
```

#### Step 1B — Windows PowerShell Inline DLP Guard (`C:\ProgramData\Antigravity\bin\agy_dlp_file_guard.ps1`)

```powershell
$RawStdin = [Console]::In.ReadToEnd()
if ($RawStdin -match '(\bAKIA[0-9A-Z]{16}\b|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9_]{20,}\b)') {
    $Out = @{
        decision = "deny"
        reason   = "INLINE_DLP_BLOCK: Hardcoded credentials cannot be written to files. Use environment variables instead."
    } | ConvertTo-Json -Compress
    [Console]::Out.WriteLine($Out)
    exit 0
}
[Console]::Out.WriteLine('{"decision":"allow"}')
exit 0
```

#### Step 2 — Targeted `hooks.json` Matcher Rule (Matches CLI & Desktop/IDE File-Write Tools)

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "write_file|edit_file|write_to_file|replace_file_content|multi_replace_file_content|sed_file",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/local/bin/agy_dlp_file_guard.py",
            "timeout": 10
          }
        ]
      },
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/local/bin/agy_security_guard.sh pre",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

---

### Example 18: Dynamically Rewrite or Sanitize Agent Tool Arguments via `PreToolUse` `overwrite` (Enforce Internal Package Mirrors / Safe Flags)

* **Admin Goal**: Transparently rewrite `run_command` arguments before execution — for example, automatically injecting `--index-url https://pypi.internal.corp.example.com/simple` whenever the agent runs `pip install`, without failing the turn.
* **Surfaces Affected**: `AGY CLI`, `AGY Desktop App`, `AGY Web Hub (agy --hub)`, `VS Code`, `Visual Studio`.
* **How `overwrite` Works**: Returning `{"decision": "allow", "overwrite": {"CommandLine": "<modified command>"}}` on `PreToolUse` `stdout` shallow-merges `overwrite` into `toolCall.args` before execution.
* **Target Files & OS Locations**:
  * **`hooks.json`**: `/home/<USER>/.gemini/config/hooks.json` (Linux) | `/Users/<USER>/.gemini/config/hooks.json` (macOS) | `C:\Users\<USER>\.gemini\config\hooks.json` (Windows)
  * **Rewriter Script**: `/usr/local/bin/agy_arg_rewriter.py` (Linux/macOS) or `C:\ProgramData\Antigravity\bin\agy_arg_rewriter.ps1` (Windows)

#### Step 1A — Linux / macOS Rewriter Hook Script (`/usr/local/bin/agy_arg_rewriter.py`)

```python
#!/usr/bin/env python3
"""Rewrites pip install commands to enforce the internal corporate PyPI mirror."""
import json
import re
import sys

CORP_PYPI = "https://pypi.internal.corp.example.com/simple"

event = json.loads(sys.stdin.read() or "{}")
tool = event.get("toolCall", {})
args = tool.get("args", {})
cmd = args.get("CommandLine", "")

if tool.get("name") == "run_command" and re.search(r"\bpip3?\s+install\b", cmd) and "--index-url" not in cmd:
    rewritten = re.sub(r"\b(pip3?\s+install)\b", rf"\1 --index-url {CORP_PYPI}", cmd, count=1)
    print(json.dumps({
        "decision": "allow",
        "overwrite": {
            "CommandLine": rewritten
        }
    }))
else:
    print(json.dumps({"decision": "allow"}))
```

#### Step 1B — Windows PowerShell Rewriter Hook Script (`C:\ProgramData\Antigravity\bin\agy_arg_rewriter.ps1`)

```powershell
$RawStdin = [Console]::In.ReadToEnd()
$EventObj = if ($RawStdin) { $RawStdin | ConvertFrom-Json } else { $null }
$ToolName = if ($EventObj -and $EventObj.toolCall) { $EventObj.toolCall.name } else { "" }
$CmdLine  = if ($EventObj -and $EventObj.toolCall -and $EventObj.toolCall.args) { [string]$EventObj.toolCall.args.CommandLine } else { "" }

if ($ToolName -eq "run_command" -and ($CmdLine -match '\bpip3?\s+install\b') -and ($CmdLine -notmatch '--index-url')) {
    $CorpPypi  = "https://pypi.internal.corp.example.com/simple"
    $Rewritten = [regex]::Replace($CmdLine, '\b(pip3?\s+install)\b', "`$1 --index-url $CorpPypi", 1)
    $Out = @{
        decision  = "allow"
        overwrite = @{
            CommandLine = $Rewritten
        }
    } | ConvertTo-Json -Depth 5 -Compress
    [Console]::Out.WriteLine($Out)
    exit 0
}
[Console]::Out.WriteLine('{"decision":"allow"}')
exit 0
```

#### Step 2 — `hooks.json` Entry for `run_command` Argument Rewriting

*(On Windows, replace the command string with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\ProgramData\\Antigravity\\bin\\agy_arg_rewriter.ps1`.)*

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "run_command",
        "hooks": [
          {
            "type": "command",
            "command": "/usr/local/bin/agy_arg_rewriter.py",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

---

## Part VI — Fleet Operations (Multi-User VDI Golden Images, Key Rotation & Tamper-Proof OS Locks)

### Example 19: Pre-Seed Multi-User Golden OS Skeleton Profiles (`/etc/skel`, macOS User Template, `C:\Users\Default`) for Shared VDI & Cloud Workstations

* **Admin Goal**: On shared multi-user Linux hosts, Citrix / Windows Server Remote Desktop Session Hosts (RDSH), or Google Cloud Workstations where new SSO/Active Directory users log in dynamically, pre-seed the golden OS user skeleton directory so every newly created user automatically receives the baseline `~/.gemini/*` files on first login (and combine with machine-wide `admin_settings.json` + PAM/GPO login lock script).
* **Surfaces Affected**: **All Surfaces** across all newly provisioned OS user accounts.
* **Target Golden Skeleton Paths by OS**:
  * **Linux**: `/etc/antigravity/admin_settings.json` (machine-wide) + `/etc/skel/.gemini/` (copied by `useradd -m` / `pam_mkhomedir`)
  * **macOS**: `/Library/Application Support/Antigravity/admin_settings.json` (machine-wide) + Jamf/Kandji `LaunchDaemon` invoking `install.sh --user "$USER"`
  * **Windows**: `C:\ProgramData\Antigravity\admin_settings.json` (machine-wide) + `C:\Users\Default\.gemini\` (copied on first AD/local user sign-in)

#### Linux Golden Image Pre-Seeding Commands (`root`)

```bash
# 1. Install and kernel-lock machine-wide Tier-1 admin_settings.json & guard script
sudo mkdir -p /etc/antigravity
sudo install -m 0644 -o root -g root ./configs/01-admin-settings/admin_settings.json /etc/antigravity/admin_settings.json
sudo install -m 0755 -o root -g root ./configs/07-security-guard-scripts/agy_security_guard.sh /usr/local/bin/agy_security_guard.sh
sudo chattr +i /etc/antigravity/admin_settings.json /usr/local/bin/agy_security_guard.sh

# 2. Populate /etc/skel/.gemini for future user accounts created via useradd -m
sudo mkdir -p /etc/skel/.gemini/config /etc/skel/.gemini/antigravity /etc/skel/.gemini/antigravity-acp
sudo install -m 0644 ./configs/04-browser-allowlist/browserAllowlist.txt /etc/skel/.gemini/antigravity/browserAllowlist.txt
sudo install -m 0644 ./configs/05-mcp-config/mcp_config.json             /etc/skel/.gemini/config/mcp_config.json
sudo install -m 0644 ./configs/06-lifecycle-hooks/hooks.json             /etc/skel/.gemini/config/hooks.json
sudo install -m 0644 ./configs/08-acp-ide-configs/antigravity-acp-settings.json /etc/skel/.gemini/antigravity-acp/settings.json
```

#### Windows Server RDSH / VDI Golden Image Pre-Seeding Commands (Elevated PowerShell)

```powershell
# 1. Install machine-wide admin_settings.json & guard script in C:\ProgramData\Antigravity
New-Item -ItemType Directory -Force -Path "C:\ProgramData\Antigravity\bin" | Out-Null
$AdminJson = Get-Content -LiteralPath ".\configs\01-admin-settings\admin_settings.json" -Raw
[System.IO.File]::WriteAllText("C:\ProgramData\Antigravity\admin_settings.json", $AdminJson, (New-Object System.Text.UTF8Encoding($false)))
Copy-Item -LiteralPath ".\configs\07-security-guard-scripts\agy_security_guard.ps1" -Destination "C:\ProgramData\Antigravity\bin\agy_security_guard.ps1" -Force

# 2. Seed C:\Users\Default\.gemini (BOM-free UTF-8) for all future Windows user profiles
$DefGemini = "C:\Users\Default\.gemini"
New-Item -ItemType Directory -Force -Path "$DefGemini\config", "$DefGemini\antigravity", "$DefGemini\antigravity-acp" | Out-Null
Copy-Item -LiteralPath ".\configs\04-browser-allowlist\browserAllowlist.txt" -Destination "$DefGemini\antigravity\browserAllowlist.txt" -Force
[System.IO.File]::WriteAllText("$DefGemini\config\mcp_config.json", (Get-Content -LiteralPath ".\configs\05-mcp-config\mcp_config.json" -Raw), (New-Object System.Text.UTF8Encoding($false)))
[System.IO.File]::WriteAllText("$DefGemini\antigravity-acp\settings.json", '{"auth":{"type":"gateway"}}', (New-Object System.Text.UTF8Encoding($false)))
```

*(Pair golden skeleton seeding with an Ansible/GPO/Scheduled Task post-login run of `./install.sh --user <NEW_USER>` or `.\scripts\deploy_and_lock_windows.ps1 -Action Deploy -User <NEW_USER>` to substitute `<USER>` workspace paths and apply `chattr +i` / NTFS `DENY` locks.)*

---

### Example 20: Zero-Downtime `GATEWAY_API_KEY` Rotation, SIEM JSONL Forwarding & Tamper-Proof OS Kernel / NTFS Locking

* **Admin Goal**:
  1. Rotate `GATEWAY_API_KEY` across thousands of developer laptops with **zero downtime** by leveraging the Enterprise Gateway's comma-separated multi-key Secret Manager support (`NEW_KEY,OLD_KEY`), updating MDM endpoints, and retiring `OLD_KEY`.
  2. Stream every `PreToolUse` / `PostToolUse` JSONL event to Google SecOps (Chronicle), Splunk, or Datadog, and enforce tamper-proof kernel/NTFS locks across all 11 policy files.
* **Surfaces Affected**: **All Managed Workstation Surfaces**.

#### Phase 1 — Zero-Downtime Key Rotation Procedure

1. **Stage Dual Keys in Secret Manager & Roll Out a New Cloud Run Revision (Accepts Both `NEW_KEY` and `OLD_KEY` Using Constant-Time Comparison)**:
   *(Because Cloud Run resolves environment-variable secrets at revision startup, run `gcloud run services update` after adding the secret version so active instances immediately load `latest`.)*
   ```bash
   printf '%s,%s' "${NEW_GATEWAY_API_KEY}" "${OLD_GATEWAY_API_KEY}" | \
     gcloud secrets versions add agy-gateway-api-key --project="${PROJECT_ID}" --data-file=-

   gcloud run services update antigravity-gateway \
     --project="${PROJECT_ID}" \
     --region="${REGION}" \
     --set-secrets="GATEWAY_API_KEY=agy-gateway-api-key:latest"
   ```
2. **Roll Out `NEW_GATEWAY_API_KEY` to Endpoints (Unlock -> Re-Deploy -> Re-Lock Automatically)**:
   ```bash
   # Linux / macOS MDM rollout:
   GATEWAY_API_KEY="${NEW_GATEWAY_API_KEY}" sudo ./install.sh --user alice
   ```
   ```powershell
   # Windows Intune / GPO rollout:
   $env:GATEWAY_API_KEY = $NewGatewayApiKey
   .\scripts\deploy_and_lock_windows.ps1 -Action Deploy -User alice
   ```
3. **Retire `OLD_GATEWAY_API_KEY` After Fleet Convergence**:
   ```bash
   printf '%s' "${NEW_GATEWAY_API_KEY}" | \
     gcloud secrets versions add agy-gateway-api-key --project="${PROJECT_ID}" --data-file=-

   gcloud run services update antigravity-gateway \
     --project="${PROJECT_ID}" \
     --region="${REGION}" \
     --set-secrets="GATEWAY_API_KEY=agy-gateway-api-key:latest"
   ```

#### Phase 2 — Manual OS Lock Reference & Critical Platform Gotchas

##### 1. Linux (`root:root` + `chattr +i`)
* **Why `chmod 0444` alone is insufficient**: Because the developer owns `/home/alice/.gemini/config/`, standard UNIX permissions allow `mv -f evil.json ~/.gemini/config/hooks.json` (`rename()` checks parent directory write permission). `chattr +i` blocks kernel unlink/rename even in a user-owned parent directory.
* **Mandatory CLI Normalization Step**: Run `sudo su - alice -c "agy --version"` **once before** applying `chattr +i` to `/home/alice/.gemini/antigravity-cli/settings.json` so `agy` does not attempt a startup `MarshalSparse` rewrite against an immutable file.

```bash
sudo chown root:root /etc/antigravity/admin_settings.json \
  /home/alice/.gemini/antigravity-cli/settings.json \
  /home/alice/.gemini/config/config.json \
  /home/alice/.gemini/config.json \
  /home/alice/.gemini/antigravity/browserAllowlist.txt \
  /home/alice/.gemini/config/mcp_config.json \
  /home/alice/.gemini/config/hooks.json \
  /usr/local/bin/agy_security_guard.sh

sudo chmod 0755 /usr/local/bin/agy_security_guard.sh
sudo chattr +i /etc/antigravity/admin_settings.json \
  /home/alice/.gemini/antigravity-cli/settings.json \
  /home/alice/.gemini/config/config.json \
  /home/alice/.gemini/config.json \
  /home/alice/.gemini/antigravity/browserAllowlist.txt \
  /home/alice/.gemini/config/mcp_config.json \
  /home/alice/.gemini/config/hooks.json \
  /usr/local/bin/agy_security_guard.sh
```

##### 2. macOS (`root:wheel` + `chflags schg`)

```bash
sudo chown root:wheel "/Library/Application Support/Antigravity/admin_settings.json" \
  /Users/alice/.gemini/antigravity-cli/settings.json \
  /Users/alice/.gemini/config/config.json \
  /Users/alice/.gemini/config.json \
  /Users/alice/.gemini/antigravity/browserAllowlist.txt \
  /Users/alice/.gemini/config/mcp_config.json \
  /Users/alice/.gemini/config/hooks.json \
  /usr/local/bin/agy_security_guard.sh

sudo chmod 0755 /usr/local/bin/agy_security_guard.sh
sudo chflags schg "/Library/Application Support/Antigravity/admin_settings.json" \
  /Users/alice/.gemini/antigravity-cli/settings.json \
  /Users/alice/.gemini/config/config.json \
  /Users/alice/.gemini/config.json \
  /Users/alice/.gemini/antigravity/browserAllowlist.txt \
  /Users/alice/.gemini/config/mcp_config.json \
  /Users/alice/.gemini/config/hooks.json \
  /usr/local/bin/agy_security_guard.sh
```

##### 3. Windows 10 / 11 / Server (BOM-Free UTF-8 + `attrib +R` + Specific NTFS `DENY` ACEs)
* **Critical Gotcha 1 — BOM-Free UTF-8**: In Windows PowerShell 5.1, `Set-Content -Encoding UTF8` prepends a 3-byte UTF-8 BOM (`0xEF 0xBB 0xBF`) that Go's JSON parser in `agy.exe` rejects. Always write JSON files with `System.Text.UTF8Encoding($false)`.
* **Critical Gotcha 2 — Preserve `SYNCHRONIZE`**: Never use generic `icacls /deny alice:(W)` because generic `W` strips `SYNCHRONIZE` and prevents `agy.exe` from opening the file for reading. Always deny the specific write/delete rights `(WD,AD,WEA,WA,DE,WDAC,WO)` **after** running `attrib.exe +R`.
* **Critical Gotcha 3 — PowerShell Exact-Match `command(regex:...)` Grants**: On Windows (`powershell` / `pwsh`), `agy.exe` forces `RequiresExactMatch = true` (`MatchesConfigAnyRaw`), so bare literal entries like `"command(echo)"` only match zero-argument `"echo"`. Pair literal rules with anchored `command(regex:...)` rules (see [Example 10](#example-10-block-destructive-commands-rm-sudo-ssh-while-requiring-human-approval-ask-for-git-push--kubectl)).

```powershell
$TargetFile = "C:\ProgramData\Antigravity\admin_settings.json"
$JsonText   = Get-Content -LiteralPath ".\configs\01-admin-settings\admin_settings.json" -Raw

# 1. Write UTF-8 WITHOUT BOM so agy.exe parses JSON cleanly
[System.IO.File]::WriteAllText($TargetFile, $JsonText, (New-Object System.Text.UTF8Encoding($false)))

# 2. Set ReadOnly attribute BEFORE denying WriteAttributes (WA), then lock with NTFS ACLs
takeown.exe /F $TargetFile /A | Out-Null
attrib.exe +R $TargetFile
icacls.exe $TargetFile /inheritance:r `
    /grant:r "SYSTEM:(F)" `
    /grant:r "Administrators:(F)" `
    /grant:r "Users:(R)" `
    /deny "Users:(WD,AD,WEA,WA,DE,WDAC,WO)" | Out-Null
```
