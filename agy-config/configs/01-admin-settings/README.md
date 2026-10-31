# `admin_settings.json` — Enterprise Gateway & Approved Model Catalog (Tier-1 MDM)

## 1. What This File Is Used For

[`admin_settings.json`](./admin_settings.json) is the **highest-precedence (Tier-1 MDM) administrator configuration file** for Google Antigravity.

When deployed by an enterprise administrator or Mobile Device Management (MDM) agent (Jamf Pro, Kandji, Microsoft Intune, Ansible, Puppet, Chef, or Google Workspace Endpoint Management), this file:

1. **Activates Enterprise Gateway Mode (`gateway.enabled: true`)**: Routes all model inference requests from the developer workstation to your organization's self-hosted **Antigravity Enterprise Gateway** instead of `googleapis.com`, bypassing interactive browser-based Google Account sign-in.
2. **Authenticates Workstation Traffic (`gateway.apiKey`)**: Attaches `Authorization: Bearer <apiKey>` to every outgoing inference request while emitting `User-Agent: antigravity/<VERSION> (aidev_client; auth_method=gateway)` and `X-Goog-Api-Client` so consumption bills on a pay-as-you-go (PAYG) basis under your Gemini Enterprise agreement.
3. **Pins Non-Overridable Attribution & Routing Headers (`gateway.customHeaders`)**: Injects corporate FinOps chargeback headers (`X-Cost-Center`, `X-Corporate-BU`) and target GCP project headers (`X-Goog-User-Project`) that developers **cannot** override via environment variables or user settings.
4. **Trusts Internal Corporate TLS Certificates (`caCertPath`)**: Configures Antigravity's TLS client to trust your private PKI / internal Load Balancer root CA bundle.
5. **Restricts the Selectable Model Catalog (`models`)**: Enforces the default model (`models.defaultModelId`) and restricts the model picker to organization-approved model IDs (`models.list`).

### Surfaces That Read This File & 3-Tier Precedence

| Antigravity Surface | Minimum Version | Reads `admin_settings.json`? | Notes |
| :--- | :--- | :---: | :--- |
| **Antigravity Desktop App** | `2.15.0+` | Yes | Displays `Connected: Enterprise Gateway` in status bar |
| **Antigravity CLI (`agy`)** | `1.2.15+` | Yes | Headless (`agy -p`) & interactive TUI |
| **VS Code & Visual Studio Extensions** | `agy 1.2.15+` | Yes | Extension delegates to bundled/system `agy` CLI |
| **JetBrains IDEs & Zed (ACP Server)** | `1.3.0+` | Yes | Requires `wireProtocol: "genai"` and `~/.gemini/antigravity-acp/settings.json` |
| **Antigravity on the Web** | N/A | No | Web requires interactive Google sign-in |

Antigravity merges gateway settings **field-by-field** across three tiers (higher tier wins on conflict; `customHeaders` merges per header key with Tier 1 winning on colliding keys):
1. **Tier 1 (Highest — MDM)**: `admin_settings.json` (system-wide administrator path).
2. **Tier 2 (Environment Variables)**: `AGY_LLM_GATEWAY_*` environment variables.
3. **Tier 3 (Lowest — User Settings)**: `~/.antigravity/settings.json` (`%USERPROFILE%\.antigravity\settings.json` on Windows), which uses the **exact same JSON schema** as `admin_settings.json` *(note: the ACP server does not read Tier 3)*.

---

## 2. Official Public Documentation Links

* **Administrator Deployment Guide (`admin_settings.json`, OS paths, MDM scripts, Precedence & Schema)**:
  * [Configure an enterprise gateway for Google Antigravity](https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/deploy-enterprise-gateway?hl=en)
  * [Deploy settings using MDM (`#deploy-mdm`)](https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/deploy-enterprise-gateway?hl=en#deploy-mdm)
  * [Settings precedence (`#settings-precedence`)](https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/deploy-enterprise-gateway?hl=en#settings-precedence)
  * [Configuration example (`#config-example`)](https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/deploy-enterprise-gateway?hl=en#config-example)
* **Developer Connection Guide (`AGY_LLM_GATEWAY_*` Tier-2 Environment Variables & IDE Setup)**:
  * [Connect Antigravity to an Enterprise Gateway](https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/connect-enterprise-gateway?hl=en)

---

## 3. Where This File Should Go (Target Locations)

### Tier-1 MDM System Paths (Enforced, Non-Overridable)

| Operating System | Exact Target File Path | Required Owner | Recommended Mode / ACL | Immutability Flag |
| :--- | :--- | :--- | :--- | :--- |
| **Linux** | `/etc/antigravity/admin_settings.json` | `root:root` | `0644` (`-rw-r--r--`)* | `chattr +i` |
| **macOS** | `/Library/Application Support/Antigravity/admin_settings.json` | `root:wheel` | `0644` (`-rw-r--r--`)* | `chflags schg` |
| **Windows** | `C:\ProgramData\Antigravity\admin_settings.json` (`%ProgramData%\Antigravity\admin_settings.json`) | `Administrators` (`*S-1-5-32-544`) | `SYSTEM:(F)`, `Administrators:(F)`, `Users:(R)` + Deny `(WD,AD,WEA,WA,DE,WDAC,WO)` | `attrib +R` + NTFS Deny ACE |

*\*Note: All local users running Antigravity must have read (`r` / `0644` or `0444`) access to `admin_settings.json` so the unprivileged Antigravity client process can parse the gateway URL and API key at startup. If you prefer per-developer API keys rather than a workstation-readable shared key in `admin_settings.json`, omit `gateway.apiKey` from `admin_settings.json` and inject `AGY_LLM_GATEWAY_API_KEY` into each developer's user session.*

### Optional Tier-3 User Fallback Path (Same JSON Schema, Lowest Precedence)

* **Linux**: `/home/<USERNAME>/.antigravity/settings.json`
* **macOS**: `/Users/<USERNAME>/.antigravity/settings.json`
* **Windows**: `C:\Users\<USERNAME>\.antigravity\settings.json`

---

## 4. Allowed Keywords & Configuration Reference Table

### Table A — `admin_settings.json` JSON Keywords

| JSON Key Path | Data Type | Required? | Default Value | Allowed Values / Format | Description |
| :--- | :--- | :---: | :--- | :--- | :--- |
| `caCertPath` | `string` | Optional | System trust store (`SSL_CERT_FILE`) | Absolute filesystem path to PEM bundle (e.g., `/etc/ssl/certs/ca-certificates.crt` on Linux, `/etc/ssl/cert.pem` on macOS, `C:\ProgramData\Antigravity\corp-root-ca.pem` on Windows) | Corporate Root Certificate Authority (CA) bundle used to verify the Enterprise Gateway's TLS certificate. Prevents `x509: certificate signed by unknown authority` errors on internal load balancers. |
| `gateway` | `object` | Required | — | JSON object | Root container for Enterprise Gateway connection, authentication, wire protocol, and custom attribution header settings. |
| `gateway.enabled` | `boolean` | Required | `false` | `true` \| `false` | Turns Enterprise Gateway routing mode on (`true`) or off (`false`). In JSON files (`admin_settings.json` and `~/.antigravity/settings.json`), `gateway.enabled` **must** be explicitly `true` to activate gateway routing and suppress Google OAuth sign-in prompts. |
| `gateway.url` | `string` | Required (when `enabled: true`) | `""` | Base `https://` URL (no trailing path; e.g., `https://gateway.corp.example.com`) | HTTPS base endpoint of your Enterprise Gateway. Antigravity appends `/v1beta/models/{MODEL_ID}:streamGenerateContent?alt=sse` (for `genai`) or `/v1/chat/completions` (for `openai`). |
| `gateway.apiKey` | `string` | Optional (if set via env) | `""` | Non-empty opaque token string | Gateway-issued API key sent as `Authorization: Bearer <apiKey>` on every request. Validated by your Enterprise Gateway against Secret Manager. Omit here only if provisioning per-user keys via `AGY_LLM_GATEWAY_API_KEY`. |
| `gateway.wireProtocol` | `string` | Optional | `"genai"` | `"genai"` \| `"openai"` | API wire protocol used for inference calls. `"genai"` sends Gemini `generateContent` payloads to `/v1beta/models/...`; `"openai"` sends OpenAI Chat Completions payloads to `/v1/chat/completions`. **Important**: JetBrains IDEs and Zed (ACP server) support **only** `"genai"`. |
| `gateway.customHeaders` | `object` (`map<string,string>`) | Optional | `{}` | Arbitrary HTTP header key-value string pairs (e.g., `{"X-Cost-Center": "CC-9941-SEC", "X-Goog-User-Project": "my-gcp-proj"}`) | Static HTTP headers attached to every request sent to the Enterprise Gateway. Merged per-key with Tier-2/Tier-3 headers, with `admin_settings.json` keys taking highest precedence so developers cannot spoof FinOps attribution. |
| `models` | `object` | Optional | Server defaults | JSON object | Root container restricting which LLM models appear in the Antigravity UI/CLI model selector and setting the startup default. |
| `models.defaultModelId` | `string` | Optional | First entry or client default | Model ID string matching an entry in `models.list` (e.g., `"gemini-3.8-flash"`) | Model ID automatically selected by default for new conversations across Antigravity App, CLI, and IDEs. |
| `models.list` | `array<object>` | Optional | `[]` | Array of model descriptor objects (`[{"modelId": "..."}]`) | Explicit allowlist of models exposed to developers in the Antigravity model picker. Every listed `modelId` must be routable by your Enterprise Gateway. |
| `models.list[].modelId` | `string` | Required (per list item) | — | Valid Vertex AI / Gateway model ID (e.g., `"gemini-3.8-flash"`, `"gemini-3.7-flash"`, `"gemini-3.1-pro-preview"`, `"gemini-3.1-flash-lite"`, `"gemini-4-argon-high"`) | Canonical model identifier sent in the request URL (`/v1beta/models/{modelId}:streamGenerateContent`) or OpenAI `model` body field. |
| `models.list[].displayName` | `string` | Optional | `modelId` | Human-readable label (e.g., `"Gemini 3.8 Flash"`) | Optional friendly label displayed in client UI model dropdowns alongside `modelId`. |
| `models.tiers` | `object` | Optional | `{}` | Optional tier mapping (`flash`, `pro`, `flashLite` string arrays) | Optional tier grouping hinting which approved model IDs correspond to fast (`flash`), deep reasoning (`pro`), and background utility (`flashLite`) agent sub-tasks. |

### Table B — Equivalent Tier-2 Environment Variables (`AGY_LLM_GATEWAY_*`)

For Docker containers, CI/CD runners, or per-developer API key injection where Tier-2 environment variables complement `admin_settings.json`:

| Environment Variable | Maps to `admin_settings.json` Key | Format / Example |
| :--- | :--- | :--- |
| `AGY_LLM_GATEWAY_URL` | `gateway.url` *(also implies `gateway.enabled = true` in CLI/App)* | `https://gateway.corp.example.com` |
| `AGY_LLM_GATEWAY_API_KEY` | `gateway.apiKey` | `agy_live_9f8e7d6c5b4a...` |
| `AGY_LLM_GATEWAY_WIRE_PROTOCOL` | `gateway.wireProtocol` | `genai` or `openai` |
| `AGY_LLM_GATEWAY_CA_CERT` | `caCertPath` *(falls back to `SSL_CERT_FILE`)* | `/etc/ssl/certs/ca-certificates.crt` |
| `AGY_LLM_GATEWAY_HEADERS` | `gateway.customHeaders` | Comma- or newline-separated `KEY: VALUE` pairs (e.g., `X-Cost-Center: Platform-Engineering,X-Corporate-BU: DevTools`) |
| `AGY_LLM_GATEWAY_MODELS` | `models.list` | Comma-separated model IDs (e.g., `gemini-3.8-flash,gemini-3.7-flash,gemini-3.1-pro-preview`) |

---

## 5. Manual Administrator Commands (Deploy, Set Permissions & Lock)

Before deploying, replace `REPLACE_WITH_GATEWAY_URL`, `REPLACE_WITH_GATEWAY_API_KEY`, and `REPLACE_WITH_PROJECT_ID` in [`admin_settings.json`](./admin_settings.json) (or run the automated [`install.sh`](../../install.sh) script at the root of `agy-config/`).

### A. Linux (Run as `root` / `sudo`)

```bash
# 1. Unlock existing file if previously locked with chattr +i
sudo chattr -i /etc/antigravity/admin_settings.json 2>/dev/null || true

# 2. Create directory owned by root:root (0755) and install file with 0644 permissions
sudo mkdir -p /etc/antigravity
sudo chown root:root /etc/antigravity
sudo chmod 0755 /etc/antigravity
sudo install -m 0644 -o root -g root ./admin_settings.json /etc/antigravity/admin_settings.json

# 3. Apply Linux kernel immutability flag so even processes with CAP_DAC_OVERRIDE or accidental scripts cannot alter it
sudo chattr +i /etc/antigravity/admin_settings.json

# 4. Verify ownership, mode (-rw-r--r--), and 'i' immutable attribute
ls -la /etc/antigravity/admin_settings.json
sudo lsattr /etc/antigravity/admin_settings.json
```

*To unlock later for admin edits on Linux:*
```bash
sudo chattr -i /etc/antigravity/admin_settings.json
```

### B. macOS (Run as `root` / `sudo` or via Jamf / Kandji)

```bash
# 1. Clear macOS system-immutable flag if already present
sudo chflags noschg,nouchg "/Library/Application Support/Antigravity/admin_settings.json" 2>/dev/null || true

# 2. Create directory owned by root:wheel and install file (adjusting CA path to /etc/ssl/cert.pem if using system CA)
sudo mkdir -p "/Library/Application Support/Antigravity"
sudo chown root:wheel "/Library/Application Support/Antigravity"
sudo chmod 0755 "/Library/Application Support/Antigravity"
sed 's|/etc/ssl/certs/ca-certificates.crt|/etc/ssl/cert.pem|g' ./admin_settings.json \
  | sudo tee "/Library/Application Support/Antigravity/admin_settings.json" >/dev/null
sudo chown root:wheel "/Library/Application Support/Antigravity/admin_settings.json"
sudo chmod 0644 "/Library/Application Support/Antigravity/admin_settings.json"

# 3. Apply macOS kernel system-immutable flag (schg)
sudo chflags schg "/Library/Application Support/Antigravity/admin_settings.json"

# 4. Verify ownership, permissions, and 'schg' flag
ls -lO "/Library/Application Support/Antigravity/admin_settings.json"
```

*To unlock later for admin edits on macOS:*
```bash
sudo chflags noschg,nouchg "/Library/Application Support/Antigravity/admin_settings.json"
```

### C. Windows 10 / 11 / Server (Run in Elevated Administrator PowerShell)

> **Security Note (from Official Admin Guide)**: Always remove or take ownership of `$env:ProgramData\Antigravity` first so a non-admin user who pre-created that directory cannot retain `CREATOR OWNER` write permissions.

```powershell
# 1. Define target directory and file path
$Dir  = Join-Path $env:ProgramData "Antigravity"
$File = Join-Path $Dir "admin_settings.json"

# 2. Unlock existing file if present, or ensure clean Administrator-owned directory
if (Test-Path -LiteralPath $File) {
    icacls.exe $File /reset | Out-Null
    attrib.exe -R $File
}
if (-not (Test-Path -LiteralPath $Dir)) {
    New-Item -ItemType Directory -Path $Dir -Force | Out-Null
}

# 3. Lock folder ownership to Administrators (*S-1-5-32-544) & SYSTEM (*S-1-5-18), Read+Execute for Users (*S-1-5-32-545)
icacls.exe $Dir /setowner "*S-1-5-32-544" | Out-Null
icacls.exe $Dir /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-545:(OI)(CI)RX" | Out-Null

# 4. Copy admin_settings.json and apply Read-Only attribute BEFORE Deny WriteAttributes (WA) ACE
Copy-Item -LiteralPath ".\admin_settings.json" -Destination $File -Force
takeown.exe /F $File /A | Out-Null
attrib.exe +R $File
icacls.exe $File /inheritance:r /grant:r "*S-1-5-18:(F)" "*S-1-5-32-544:(F)" "*S-1-5-32-545:(R)" /deny "*S-1-5-32-545:(WD,AD,WEA,WA,DE,WDAC,WO)" | Out-Null

# 5. Verify ACLs and ReadOnly attribute
Get-Item -LiteralPath $File -Force | Select-Object FullName, IsReadOnly, Length
icacls.exe $File
```

*To unlock later for admin edits on Windows:*
```powershell
$File = Join-Path $env:ProgramData "Antigravity\admin_settings.json"
icacls.exe $File /remove:d "*S-1-5-32-545" | Out-Null
attrib.exe -R $File
```

---

## 6. Critical Operational Guardrails & Preview v2.0 vs. Official GA Reference

### A. Mandatory Flash Model Requirement (`MODEL_PLACEHOLDER_M50` Prevention)

Antigravity relies on a **tiered multi-model execution engine**: even when a developer selects a frontier Pro or Argon model (`gemini-3.1-pro-preview` or `gemini-4-argon-high`) for primary reasoning, the client executes background **conversation titling, trajectory checkpointing, context summarization, and fast tool grounding** on a **Flash-tier** model.

* **Client Requirement**: Always include at least one Flash model (e.g., `gemini-3.8-flash` or `gemini-3.7-flash`) in `models.list` (and `AGY_LLM_GATEWAY_MODELS`). Omitting a Flash tier on unpatched clients can cause background tasks to fall back to the internal enum `MODEL_PLACEHOLDER_M50`, triggering `HTTP 404 NOT_FOUND: Publisher Model .../models/MODEL_PLACEHOLDER_M50 was not found`.
* **Gateway Defense-in-Depth**: Both the Python and Go Enterprise Gateway runtimes in `enterprise-gateway/` automatically intercept any `MODEL_PLACEHOLDER_M50` / `MODEL_PLACEHOLDER_*` request, rewrite it to `DEFAULT_FLASH_FALLBACK_MODEL` (`gemini-3.8-flash`), and emit a structured `WARN` log entry so background tasks never fail.

### B. Static Model Discovery & Official Vertex AI Model Garden Links

Antigravity does **not** dynamically poll `GET /v1/models` on startup; administrators define the exact approved catalog statically via `models.list` in `admin_settings.json` (or `AGY_LLM_GATEWAY_MODELS`). Verify model availability and regional endpoints in Vertex AI Model Garden:

| Agent Tier | Recommended Model ID | Vertex AI Model Garden Link |
| :--- | :--- | :--- |
| **Primary Agent & Background Flash (Mandatory)** | `gemini-3.8-flash` *(or `gemini-3.7-flash`)* | `https://console.cloud.google.com/vertex-ai/publishers/google/model-garden/gemini-3.8-flash` |
| **Complex Architecture & Deep Reasoning** | `gemini-3.1-pro-preview` | `https://console.cloud.google.com/vertex-ai/publishers/google/model-garden/gemini-3.1-pro-preview` |
| **High-Frequency Utility & Summarization** | `gemini-3.1-flash-lite` | `https://console.cloud.google.com/vertex-ai/publishers/google/model-garden/gemini-3.1-flash-lite` |

### C. Containerized & Remote Development Environments (`Dockerfile` Example)

For ephemeral cloud development environments (DevContainers, GitHub Codespaces, Cloud Workstations, or CI/CD runners) where MDM agents are absent, bake your internal Root CA and Tier-2 `AGY_LLM_GATEWAY_*` variables directly into the developer container image (and pass `AGY_LLM_GATEWAY_API_KEY` at runtime — **never** bake secrets into image layers):

```dockerfile
FROM ubuntu:24.04

# 1. Install internal corporate Root CA into system trust store
COPY corp-internal-ca.crt /usr/local/share/ca-certificates/corp-internal-ca.crt
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 2. Configure non-secret Tier-2 Antigravity Gateway settings
ENV AGY_LLM_GATEWAY_URL="https://gateway.internal.corp.example.com"
ENV AGY_LLM_GATEWAY_WIRE_PROTOCOL="genai"
ENV AGY_LLM_GATEWAY_CA_CERT="/etc/ssl/certs/ca-certificates.crt"
ENV AGY_LLM_GATEWAY_MODELS="gemini-3.8-flash,gemini-3.1-pro-preview,gemini-3.1-flash-lite"
ENV AGY_LLM_GATEWAY_HEADERS="X-Cost-Center: Cloud-Dev-Env,X-Corporate-BU: Platform"
# Inject AGY_LLM_GATEWAY_API_KEY at `docker run -e AGY_LLM_GATEWAY_API_KEY=...` or via K8s Secret.
```

### D. Compatibility Note: Early `v2.0 (Enterprise Preview)` PDF vs. Official GA Specification

If you are referencing an earlier **Document Version 2.0 (Enterprise Preview)** PDF alongside the live Google Cloud documentation, note the following breaking changes between the early preview draft and the **Official GA Antigravity client binary** implemented in this repository:

| Area | Early `v2.0 (Enterprise Preview)` PDF Draft | Official GA Specification (Implemented in This Repo) |
| :--- | :--- | :--- |
| **macOS MDM Path** | `/Library/Application Support/Google/Antigravity/admin_settings.json` | `/Library/Application Support/Antigravity/admin_settings.json` *(no `/Google/` segment)* |
| **Windows MDM Path** | `%ProgramData%\Google\Antigravity\admin_settings.json` | `%ProgramData%\Antigravity\admin_settings.json` *(no `\Google\` segment)* |
| **CA Certificate Key** | Nested `gateway.caCertPath` | Top-level `caCertPath` |
| **Model Allowlist Schema** | Nested `gateway.models.filter: ["..."]` | Top-level `models: { "defaultModelId": "...", "list": [{"modelId": "..."}] }` |
| **OAuth Login Suppression** | Separate `auth.suppressInteractiveLogin: true` | Automatic when `gateway.enabled: true` |
| **`AGY_LLM_GATEWAY_HEADERS`** | JSON object string (`'{"X-Cost-Center":"..."}'`) | Comma- or newline-separated `KEY: VALUE` pairs (`"X-Cost-Center: Platform-Eng"`) |
| **Headless CLI Prompt Flag** | `agy prompt "..."` | `agy -p "..."` |
| **IDE Extension Support** | Listed VS Code & JetBrains as *"Not supported in Day 0 MVP"* | Supported in GA: VS Code / Visual Studio (`agy 1.2.15+`) and JetBrains / Zed (`ACP 1.3.0+`, `genai` protocol) |
| **Cloud Run IAM Flag** | Suggested `--no-allow-unauthenticated` with IAM tokens | **Never** enable Cloud Run IAM invoker checks or IAP on `Authorization` (intercepts `Bearer <GATEWAY_API_KEY>`); use `--no-invoker-iam-check` + `--ingress=internal` for private VPC access |

