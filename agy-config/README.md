# Antigravity Enterprise Client & MDM Security Configuration Suite (`agy-config`)

Production-ready, modular workstation governance package for **Google Antigravity** across **Linux**, **macOS**, and **Windows 10/11/Server** covering all client surfaces: **Antigravity Desktop App (`2.15.0+`)**, **Antigravity CLI (`agy 1.2.15+`)**, **Web Hub (`agy --hub`)**, **VS Code & Visual Studio**, and **JetBrains IDEs & Zed (`ACP 1.3.0+`)**.

Every configuration file lives in its own dedicated module directory under [`configs/`](./configs/) alongside a comprehensive per-file `README.md` documenting **what the file does**, **official public documentation links**, **exact target OS paths**, **all allowed configuration keywords/schemas**, and **step-by-step manual Administrator lock/unlock commands**.

> **Administrator Policy Cookbook**: Looking for ready-to-use recipes (blocking/allowlisting MCP servers or individual MCP tools, locking down model pickers, enforcing workspace sandboxes, configuring JetBrains/Zed ACP, or disabling Browser Subagent JS) mapped by **OS path (Linux, macOS, Windows)** and **surface (CLI, Desktop, Web Hub, IDE Plugins)**? See **[`ADMIN_POLICY_EXAMPLES.md`](./ADMIN_POLICY_EXAMPLES.md)**.

---

## 1. Application Architecture

When Enterprise Gateway mode (`gateway.enabled: true`) is active, Antigravity bypasses interactive Google OAuth sign-in and routes all model inference through your self-hosted **Antigravity Enterprise Gateway** (`aiplatform.googleapis.com` backend). Because cloud-hosted seat-level admin toggles do not apply in Gateway mode, workstation governance is enforced through **five coordinated local defense layers** locked at the OS kernel/filesystem level:

```text
+---------------------------------------------------------------------------------------------------+
|                           MANAGED DEVELOPER WORKSTATION (Linux / macOS / Windows)                 |
|                                                                                                   |
|  [Layer 1: Gateway & Model Catalog]                                                               |
|    • 01-admin-settings/admin_settings.json  --> Tier-1 MDM Gateway URL, API Key, CA, Model List   |
|    • 08-acp-ide-configs/{acp.json, ...}     --> JetBrains & Zed ACP Server Gateway Binding        |
|                                                                                                   |
|  [Layer 2: OS Sandbox & 595+ Fine-Grained Allow/Ask/Deny Rules (Deny > Ask > Allow)]              |
|    • 02-cli-settings/settings.json          --> CLI & VS Code (`exebox` / `sandbox-exec` + rules) |
|    • 03-desktop-hub-config/config.json      --> Desktop App & Web Hub (`userSettings` + grants)   |
|                                                                                                   |
|  [Layer 3: Browser Subagent Two-Layer URL Control]                                                |
|    • 04-browser-allowlist/browserAllowlist.txt --> Trusted domains + JS execution disabled        |
|                                                                                                   |
|  [Layer 4: Model Context Protocol (MCP) Registry & Tool Filtering]                                |
|    • 05-mcp-config/mcp_config.json          --> Approved MCP servers, enabledTools, disabledTools |
|                                                                                                   |
|  [Layer 5: Synchronous PreToolUse Active Blocker & PostToolUse SIEM Audit]                        |
|    • 06-lifecycle-hooks/hooks.json          --> Intercepts every agent tool call (`matcher: .*`)  |
|    • 07-security-guard-scripts/*.{sh,ps1}   --> Blocks destructive/SSRF/cred payloads (exit 2)    |
|                                                                                                   |
|  [Kernel & Filesystem Immutability Lock — Prevents `mv -f` Atomic Rename Bypass]                  |
|    • Linux: root:root + chattr +i  |  macOS: root:wheel + chflags schg  |  Win: icacls /deny      |
+---------------------------------------------------------------------------------------------------+
```

### Quick Navigation — Per-File Documentation & Keyword Reference Guides

| # | Config Module Directory | Canonical File(s) | Target Surfaces | Detailed Per-File Guide |
| :-: | :--- | :--- | :--- | :--- |
| **01** | [`configs/01-admin-settings/`](./configs/01-admin-settings/) | [`admin_settings.json`](./configs/01-admin-settings/admin_settings.json) | All Surfaces (Tier-1 MDM) | [Read `01-admin-settings/README.md`](./configs/01-admin-settings/README.md) |
| **02** | [`configs/02-cli-settings/`](./configs/02-cli-settings/) | [`settings.json`](./configs/02-cli-settings/settings.json) | CLI (`agy`), VS Code, Visual Studio | [Read `02-cli-settings/README.md`](./configs/02-cli-settings/README.md) |
| **03** | [`configs/03-desktop-hub-config/`](./configs/03-desktop-hub-config/) | [`config.json`](./configs/03-desktop-hub-config/config.json) | Desktop App, Web Hub (`agy --hub`), CLI grants | [Read `03-desktop-hub-config/README.md`](./configs/03-desktop-hub-config/README.md) |
| **04** | [`configs/04-browser-allowlist/`](./configs/04-browser-allowlist/) | [`browserAllowlist.txt`](./configs/04-browser-allowlist/browserAllowlist.txt) | Desktop App, IDE, Web Hub, CLI `/browser` | [Read `04-browser-allowlist/README.md`](./configs/04-browser-allowlist/README.md) |
| **05** | [`configs/05-mcp-config/`](./configs/05-mcp-config/) | [`mcp_config.json`](./configs/05-mcp-config/mcp_config.json) | Desktop App, CLI (`agy`), IDE | [Read `05-mcp-config/README.md`](./configs/05-mcp-config/README.md) |
| **06** | [`configs/06-lifecycle-hooks/`](./configs/06-lifecycle-hooks/) | [`hooks.json`](./configs/06-lifecycle-hooks/hooks.json) | Desktop App, CLI (`agy`), IDE | [Read `06-lifecycle-hooks/README.md`](./configs/06-lifecycle-hooks/README.md) |
| **07** | [`configs/07-security-guard-scripts/`](./configs/07-security-guard-scripts/) | [`agy_security_guard.sh`](./configs/07-security-guard-scripts/agy_security_guard.sh)<br>[`agy_security_guard.ps1`](./configs/07-security-guard-scripts/agy_security_guard.ps1) | Linux/macOS (`sh`) & Windows (`ps1`) Hook Engine | [Read `07-security-guard-scripts/README.md`](./configs/07-security-guard-scripts/README.md) |
| **08** | [`configs/08-acp-ide-configs/`](./configs/08-acp-ide-configs/) | [`acp.json`](./configs/08-acp-ide-configs/acp.json)<br>[`antigravity-acp-settings.json`](./configs/08-acp-ide-configs/antigravity-acp-settings.json) | JetBrains IDEs & Zed Editor (ACP Server) | [Read `08-acp-ide-configs/README.md`](./configs/08-acp-ide-configs/README.md) |

### Official Public Documentation Index

* **Enterprise Gateway Admin Deployment Guide**: https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/deploy-enterprise-gateway?hl=en
* **Enterprise Gateway Developer & ACP Connection Guide**: https://docs.cloud.google.com/gemini/enterprise/docs/ai-developer-tools/connect-enterprise-gateway?hl=en
* **Antigravity CLI Reference & `settings.json` Keys**: https://antigravity.google/docs/cli/reference/#configuration-keys-settingsjson
* **Antigravity Global & Project Settings**: https://antigravity.google/docs/settings/
* **Agent Permissions (`Allow / Ask / Deny` Engine)**: https://antigravity.google/docs/permissions/
* **Terminal Sandbox (`exebox` / `sandbox-exec`)**: https://antigravity.google/docs/sandbox/
* **Browser Allowlist & Denylist**: https://antigravity.google/docs/ide/allowlist-denylist/
* **Model Context Protocol (`mcp_config.json`)**: https://antigravity.google/docs/mcp/
* **Lifecycle Hooks (`hooks.json`)**: https://antigravity.google/docs/hooks/

---

## 2. Project Directory Structure

```text
agy-config/
├── README.md                                        # Master architecture, matrix, env vars & playbooks
├── ADMIN_POLICY_EXAMPLES.md                         # 20 scenario-driven admin recipes by OS path & AGY surface
├── settings.env                                     # Non-secret defaults (Gateway URL placeholder, FinOps headers, model catalog)
├── .env.example                                     # Template for local git-ignored `.env` secret overrides (GATEWAY_API_KEY)
├── .gitignore                                       # Blocks `.env*`, keys, certs, audit logs, and backup artifacts
├── install.sh                                       # Unified Linux & macOS installer, normalizer, and kernel locker
├── uninstall.sh                                     # Unified Linux & macOS unlocker (`--unlock`) and remover (`--purge`)
├── configs/                                         # Self-contained modular AGY configuration directories
│   ├── 01-admin-settings/
│   │   ├── admin_settings.json                      # Tier-1 MDM Gateway URL, API key, CA bundle & approved models
│   │   └── README.md                                # OS paths, Precedence, Keyword Table & Admin Lock CLI
│   ├── 02-cli-settings/
│   │   ├── settings.json                            # CLI & VS Code sandbox (`enableTerminalSandbox`) + 595+ permission rules
│   │   └── README.md                                # All 32 `settings.json` keys, 7 action selectors, MarshalSparse & Lock CLI
│   ├── 03-desktop-hub-config/
│   │   ├── config.json                              # Desktop App & Web Hub `userSettings` + `globalPermissionGrants`
│   │   └── README.md                                # Proto enums, `jq` merge strategy, OS paths & Admin Lock CLI
│   ├── 04-browser-allowlist/
│   │   ├── browserAllowlist.txt                     # Trusted hostnames for the Antigravity Browser Subagent
│   │   └── README.md                                # Two-layer URL security model, syntax rules & Admin Lock CLI
│   ├── 05-mcp-config/
│   │   ├── mcp_config.json                          # Approved MCP servers, `enabledTools`, `disabledTools`, per-tool `eager` map
│   │   └── README.md                                # Full `mcpServers` property table, schema rules & Admin Lock CLI
│   ├── 06-lifecycle-hooks/
│   │   ├── hooks.json                               # Global `PreToolUse` & `PostToolUse` hook definitions
│   │   └── README.md                                # All 6 hook events, stdin/stdout JSON contract & Admin Lock CLI
│   ├── 07-security-guard-scripts/
│   │   ├── agy_security_guard.sh                    # Bash PreToolUse blocker (exit 2) & JSONL SIEM logger (Linux/macOS)
│   │   ├── agy_security_guard.ps1                   # PowerShell PreToolUse blocker (exit 2) & JSONL SIEM logger (Windows)
│   │   └── README.md                                # 5 defense domains, env vars, exit codes & `0755`/ACL Lock CLI
│   └── 08-acp-ide-configs/
│       ├── acp.json                                 # JetBrains (`~/.jetbrains/acp.json`) & Zed `agent_servers` config
│       ├── antigravity-acp-settings.json            # ACP server auth mode (`{"auth": {"type": "gateway"}}`)
│       └── README.md                                # ACP keywords, `AGY_LLM_GATEWAY_*` env vars & Admin Lock CLI
└── scripts/                                         # Platform-specific MDM deployment, audit & lock automation
    ├── deploy_and_lock_linux.sh                     # Linux root/Ansible script (`MarshalSparse` + `chattr +i`)
    ├── deploy_and_lock_macos.sh                     # macOS root/Jamf/Kandji script (`/etc/ssl/cert.pem` + `chflags schg`)
    └── deploy_and_lock_windows.ps1                  # Windows Admin PowerShell/Intune script (`takeown` + `icacls /deny`)
```

---

## 3. Frameworks & Libraries

This configuration and endpoint-hardening suite relies strictly on zero-dependency, native OS administration primitives so MDM agents can execute it on air-gapped or freshly provisioned machines without external runtimes:

* **GNU Bash 4.0+ / Zsh** (`install.sh`, `uninstall.sh`, `deploy_and_lock_linux.sh`, `deploy_and_lock_macos.sh`, `agy_security_guard.sh`)
* **Linux `e2fsprogs` (`chattr`, `lsattr`)** — Kernel inode immutability (`EXT4_IMMUTABLE_FL`) preventing file modification or `rename()` replacement inside user-owned `~/.gemini` directories.
* **macOS BSD File Flags (`chflags schg`, `ls -lO`, `dscl`)** — APFS/HFS+ system-immutable kernel enforcement.
* **Windows PowerShell 5.1+ / 7+ & NTFS ACL Utilities (`icacls.exe`, `takeown.exe`, `attrib.exe`)** — Administrator ownership + explicit `Deny (WD,AD,WEA,WA,DE,WDAC,WO)` Access Control Entries.
* **Optional `jq` (`1.6+`)** — Used automatically when present to non-destructively merge `userSettings` into pre-existing Desktop `config.json` or Zed `settings.json` files.

---

## 4. Environment Variables

All scripts load defaults from [`settings.env`](./settings.env) and optional git-ignored overrides from `.env` (copied from [`.env.example`](./.env.example)). Zero live credentials or project IDs are hardcoded in any template.

| Variable Name | Data Type | Purpose | Example Value |
| :--- | :--- | :--- | :--- |
| `AGY_DEV_USER` | `string` | Target non-root OS developer username (auto-detected or prompted if blank). | `"alice"` |
| `GATEWAY_URL` | `string` (URL) | HTTPS base endpoint of your deployed Antigravity Enterprise Gateway. | `"https://gateway.corp.example.com"` |
| `GATEWAY_API_KEY` | `string` (Secret) | Bearer API key validated by your Enterprise Gateway (set in `.env` or MDM secret variable). | `"agy_live_9f8e7d6c..."` |
| `GATEWAY_WIRE_PROTOCOL` | `string` | Wire protocol (`"genai"` default; `"openai"` not supported on JetBrains/Zed ACP). | `"genai"` |
| `CA_CERT_PATH` | `string` (Path) | Corporate Root CA PEM bundle path (auto-mapped to `/etc/ssl/cert.pem` on macOS). | `"/etc/ssl/certs/ca-certificates.crt"` |
| `COST_CENTER` | `string` | Injected into `gateway.customHeaders["X-Cost-Center"]` for FinOps chargeback. | `"CC-9941-SEC"` |
| `CORPORATE_BU` | `string` | Injected into `gateway.customHeaders["X-Corporate-BU"]`. | `"Enterprise-Security"` |
| `ENTERPRISE_SURFACE` | `string` | Injected into `gateway.customHeaders["X-Enterprise-Surface"]`. | `"MDM-Managed-Workstation"` |
| `BILLING_PROJECT_ID` | `string` | Injected into `gateway.customHeaders["X-Goog-User-Project"]` for quota/billing routing. | `"corp-ai-prod-01"` |
| `DEPLOY_ACP_CONFIGS` | `boolean` (`"true"`/`"false"`) | Whether to deploy and lock JetBrains & Zed ACP configuration files (`08-acp-ide-configs`). | `"true"` |
| `WINDOWS_ADD_UNSANDBOXED_ALLOW` | `boolean` (`"true"`/`"false"`) | On Windows, pairs `command(...)` allow rules with `unsandboxed(...)` allow grants when OS sandboxing is unavailable. | `"true"` |
| `AGY_AUDIT_LOG_PATH` | `string` (Path) | Destination JSONL audit trail file written by `agy_security_guard.{sh,ps1}`. | `"/tmp/agy_security_audit.log"` |

---

## 5. Local Execution Instructions

### A. Linux & macOS Workstations

```bash
# 1. Navigate to the modular agy-config directory
cd /path/to/AntigravityEnterpriseGateway/agy-config

# 2. Create your local git-ignored .env file and set GATEWAY_URL, GATEWAY_API_KEY, and BILLING_PROJECT_ID
cp .env.example .env
chmod 0600 .env
# Edit .env with your preferred editor (e.g., nano .env or vim .env)

# 3. Deploy all configurations, normalize sparse CLI settings, and apply kernel locks (chattr +i / chflags schg)
sudo ./install.sh --user <DEVELOPER_USERNAME>

# 4. Audit file ownership, permissions, and kernel immutable flags at any time
sudo ./install.sh --user <DEVELOPER_USERNAME> --status

# 5. Unlock files temporarily for maintenance (or pass --purge to remove all managed policy files)
sudo ./uninstall.sh --user <DEVELOPER_USERNAME> --unlock
```

### B. Windows 10 / 11 / Server Workstations (Elevated Administrator PowerShell)

```powershell
# 1. Navigate to agy-config and create local .env from .env.example
Set-Location C:\path\to\AntigravityEnterpriseGateway\agy-config
Copy-Item .env.example .env
notepad.exe .env

# 2. Deploy all policy files, rewrite Windows PowerShell hook paths, and lock with NTFS Deny ACLs
.\scripts\deploy_and_lock_windows.ps1 -Action Deploy -User <DEVELOPER_USERNAME>

# 3. Verify file status and icacls permissions
.\scripts\deploy_and_lock_windows.ps1 -Action Status -User <DEVELOPER_USERNAME>

# 4. Unlock for maintenance (or use -Action Purge to remove managed files)
.\scripts\deploy_and_lock_windows.ps1 -Action Unlock -User <DEVELOPER_USERNAME>
```

---

## 6. Cloud Deployment Playbooks (Google Cloud Run & GKE)

While `admin_settings.json` and the `~/.gemini/*` files run on developer endpoints (or remote Cloud Workstations / Compute Engine VMs), enterprises commonly distribute this configuration bundle centrally or bake it into **containerized Antigravity CLI / Cloud Workstation runners** hosted on **Google Cloud Run Jobs** or **Google Kubernetes Engine (GKE)** connected to the [Enterprise Gateway](../enterprise-gateway/README.md).

### A. Containerizing a Governed Headless Antigravity CLI Runner (`Dockerfile` Example)

```dockerfile
FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates curl jq python3 && rm -rf /var/lib/apt/lists/*

# Install Antigravity CLI (v1.2.15+) and create unprivileged developer user 'agy'
RUN useradd -m -s /bin/bash agy \
    && curl -fsSL https://antigravity.google/cli/install.sh -o /tmp/install.sh \
    && bash /tmp/install.sh && rm -f /tmp/install.sh

# Copy modular security policies (without secrets) and lock root-owned policy files
COPY configs/01-admin-settings/admin_settings.json /etc/antigravity/admin_settings.json
COPY configs/02-cli-settings/settings.json         /home/agy/.gemini/antigravity-cli/settings.json
COPY configs/05-mcp-config/mcp_config.json         /home/agy/.gemini/config/mcp_config.json
COPY configs/06-lifecycle-hooks/hooks.json         /home/agy/.gemini/config/hooks.json
COPY configs/07-security-guard-scripts/agy_security_guard.sh /usr/local/bin/agy_security_guard.sh

RUN sed -i 's|__DEV_USER__|agy|g' /home/agy/.gemini/antigravity-cli/settings.json \
    && chown -R agy:agy /home/agy/.gemini \
    && chown root:root /etc/antigravity/admin_settings.json \
       /home/agy/.gemini/antigravity-cli/settings.json \
       /home/agy/.gemini/config/mcp_config.json \
       /home/agy/.gemini/config/hooks.json \
       /usr/local/bin/agy_security_guard.sh \
    && chmod 0755 /usr/local/bin/agy_security_guard.sh \
    && chmod 0644 /etc/antigravity/admin_settings.json \
       /home/agy/.gemini/antigravity-cli/settings.json \
       /home/agy/.gemini/config/mcp_config.json \
       /home/agy/.gemini/config/hooks.json

USER agy
WORKDIR /home/agy/workspace
ENTRYPOINT ["agy"]
```

### B. Deploying as a Governed Cloud Run Job (Injecting Secrets from Secret Manager)

```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="europe-west1"
export GATEWAY_URL="https://antigravity-gateway-xxxxx.a.run.app"

# 1. Build and push the governed CLI container image to Artifact Registry
gcloud builds submit --tag "${REGION}-docker.pkg.dev/${PROJECT_ID}/antigravity/agy-governed-cli:latest"

# 2. Create a Cloud Run Job injecting AGY_LLM_GATEWAY_URL and Secret Manager API key at runtime
gcloud run jobs create agy-governed-runner \
  --image="${REGION}-docker.pkg.dev/${PROJECT_ID}/antigravity/agy-governed-cli:latest" \
  --region="${REGION}" \
  --set-env-vars="AGY_LLM_GATEWAY_URL=${GATEWAY_URL},AGY_LLM_GATEWAY_WIRE_PROTOCOL=genai" \
  --set-secrets="AGY_LLM_GATEWAY_API_KEY=agy-gateway-api-key:latest" \
  --args="-p,Audit repository dependencies for deprecated APIs"
```

### C. Hosting Policy ConfigMaps & Workload Runners on Google Kubernetes Engine (GKE)

Mount the sanitized files from `configs/` as immutable read-only Kubernetes `ConfigMap` volumes and inject `AGY_LLM_GATEWAY_API_KEY` from a Kubernetes `Secret` (synced via Secret Manager CSI Driver):

```bash
# 1. Create a read-only ConfigMap directly from the modular configs/ templates
kubectl create namespace antigravity-runners --dry-run=client -o yaml | kubectl apply -f -

kubectl -n antigravity-runners create configmap agy-enterprise-policies \
  --from-file=admin_settings.json=configs/01-admin-settings/admin_settings.json \
  --from-file=settings.json=configs/02-cli-settings/settings.json \
  --from-file=mcp_config.json=configs/05-mcp-config/mcp_config.json \
  --from-file=hooks.json=configs/06-lifecycle-hooks/hooks.json \
  --from-file=agy_security_guard.sh=configs/07-security-guard-scripts/agy_security_guard.sh \
  --dry-run=client -o yaml | kubectl apply -f -

# 2. Create the gateway API key Secret from environment variable (never hardcoded in YAML)
kubectl -n antigravity-runners create secret generic agy-gateway-credentials \
  --from-literal=api-key="${GATEWAY_API_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Example GKE `Job` manifest mounting the read-only `ConfigMap` (`readOnly: true` prevents any container-level tampering even without `CAP_LINUX_IMMUTABLE`):

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: agy-governed-agent-job
  namespace: antigravity-runners
spec:
  template:
    spec:
      restartPolicy: Never
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
      containers:
        - name: agy-cli
          image: europe-west1-docker.pkg.dev/REPLACE_WITH_PROJECT_ID/antigravity/agy-governed-cli:latest
          args: ["-p", "Summarize security posture of workspace"]
          env:
            - name: AGY_LLM_GATEWAY_URL
              value: "https://REPLACE_WITH_GATEWAY_URL"
            - name: AGY_LLM_GATEWAY_API_KEY
              valueFrom:
                secretKeyRef:
                  name: agy-gateway-credentials
                  key: api-key
          volumeMounts:
            - name: policy-bundle
              mountPath: /etc/antigravity/admin_settings.json
              subPath: admin_settings.json
              readOnly: true
            - name: policy-bundle
              mountPath: /home/agy/.gemini/config/mcp_config.json
              subPath: mcp_config.json
              readOnly: true
            - name: policy-bundle
              mountPath: /home/agy/.gemini/config/hooks.json
              subPath: hooks.json
              readOnly: true
            - name: guard-script
              mountPath: /usr/local/bin/agy_security_guard.sh
              subPath: agy_security_guard.sh
              readOnly: true
      volumes:
        - name: policy-bundle
          configMap:
            name: agy-enterprise-policies
            defaultMode: 0444
        - name: guard-script
          configMap:
            name: agy-enterprise-policies
            defaultMode: 0555
```
