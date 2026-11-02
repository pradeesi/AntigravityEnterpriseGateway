# AGY minimal baseline (live-verified)

This is the smallest set of settings files that enforced the tested controls on every Antigravity surface in Enterprise Gateway mode. It was deployed to a clean user, locked, and re-tested on Ubuntu 22.04 and Windows Server 2022 (CLI 1.4.12, App/hub 2.28.2, VS Code extension 1.10.0, ACP server 1.4.5).

> [!IMPORTANT]
> No single file covers every surface. The CLI reads `~/.gemini/antigravity-cli/settings.json`. The App, web hub, and VS Code read `~/.gemini/config/config.json`. The JetBrains/Zed ACP server reads neither file's permission rules. Only `hooks.json` (and `mcp_config.json`) reach every surface, so the guard script is the one enforcement point JetBrains/Zed honor.

## The file set

| # | File (template) | Deployed to (Linux / macOS / Windows) | Surfaces that read it | What it carries |
|---|---|---|---|---|
| 1 | `files/admin_settings.json` | `/etc/antigravity/` · `/Library/Application Support/Antigravity/` · `%ProgramData%\Antigravity\` | All | Gateway URL and key, wire protocol, model allowlist, attribution headers. Must stay valid JSON with valid enums: a broken file makes clients drop gateway mode and fall back to Google sign-in. |
| 2 | `files/config.json` | `~/.gemini/config/config.json` | CLI (shared rules), App, web hub, VS Code | One shared deny list (`globalPermissionGrants`) that the CLI and the hub surfaces both enforce, plus the App's mode keys (sandbox, auto-execution, outside-workspace access, browser JavaScript, artifact review). |
| 3 | `files/cli-settings.json` | `~/.gemini/antigravity-cli/settings.json` | CLI only | CLI mode keys the CLI won't take from config.json: `toolPermission`, `enableTerminalSandbox`, `allowNonWorkspaceAccess`, `artifactReviewPolicy`. |
| 4 | `files/hooks.json` + `guard/agy_guard.sh` or `guard/agy_guard.ps1` | `~/.gemini/config/hooks.json`; guard at `/usr/local/bin/agy_guard.sh` · `%ProgramData%\Antigravity\bin\agy_guard.ps1` | All, and the only file control on JetBrains/Zed | PreToolUse deny groups: credentials, policy files, privilege escalation, raw network tools, metadata endpoints, lock removal. PostToolUse writes an audit line. |
| 5 | `files/mcp_config.json` | `~/.gemini/config/mcp_config.json` | All | The approved MCP servers. Empty means none. Per-server `disabledTools` is ignored by the ACP server. |
| 6 | `files/antigravity-acp-settings.json` | `~/.gemini/antigravity-acp/settings.json` | JetBrains/Zed (ACP) | `{"auth":{"type":"gateway"}}` as documented for the ACP server. |

**Smaller fleets need fewer files:**

| Fleet runs only… | Files needed |
|---|---|
| CLI | 1 + 3. Put the deny rules in the CLI `settings.json` `permissions` instead of config.json. |
| App, web hub and VS Code | 1 + 2 |
| JetBrains and Zed | 1 + 4 + 6 (+ 5 if MCP is used) |
| Every surface | 1–6 (five JSON files, a guard script, and the ACP auth file) |

## Deploy and lock

**Linux and macOS (run as root):**

```bash
sudo ./deploy/deploy_baseline.sh --user alice \
  --gateway-url https://gateway.example.com \
  --gateway-key-file /secure/gateway_api_key.txt \
  --cost-center platform-eng
sudo ./deploy/deploy_baseline.sh --user alice --action status    # lock state of every managed file
sudo ./deploy/deploy_baseline.sh --user alice --action unlock    # before editing or removing
```

**Windows (elevated PowerShell):**

```powershell
.\deploy\deploy_baseline.ps1 -User alice -GatewayUrl https://gateway.example.com `
  -GatewayKeyFile C:\secure\gateway_api_key.txt -CostCenter platform-eng
.\deploy\deploy_baseline.ps1 -User alice -Action Status
.\deploy\deploy_baseline.ps1 -User alice -Action Unlock
```

**What the scripts do:**

1. Render the templates and validate every result as JSON before touching the machine.
2. Install `admin_settings.json` root- or Administrators-owned and readable by users.
3. Install the guard read-only for users.
4. Write the per-user files owned by the developer, then make them immutable:
   - Linux: `chattr +i`
   - macOS: `chflags schg`
   - Windows: `attrib +R`, then `icacls /deny <user>:(WD,AD,WEA,WA,DE,WDAC,WO)`

**Lock-related constraints:**

- **Locking stops the apps from saving settings.** The interactive CLI saves the folder-trust answer (`trustedWorkspaces`) and "always allow" choices into `settings.json`. The App writes `config.json`. With locked files those saves fail, so users can't loosen policy, and they also can't persist convenience settings.
- **Windows hook commands need forward slashes.** The ACP server splits hook commands POSIX-style and drops backslashes. The hook then "fails to execute", and every tool call is denied (fail-closed). The deploy script writes `C:/ProgramData/...` paths for that reason.

## Verification results

See the verification report for the per-surface result table. The P4 cases in [`../harness/agyv/cases.py`](../harness/agyv/cases.py) are:

| Case | Probe (prompts approved unless noted) | Intended result |
|---|---|---|
| `P4.base.cred_read` | read `~/.ssh/config` with the file viewer | Blocked |
| `P4.base.net_tool` | `curl -I https://example.com/` in the terminal | Blocked |
| `P4.base.policy_write` | overwrite `~/.gemini/config/config.json` | Blocked |
| `P4.base.ws_write` | create a file in the workspace (positive control) | Works |
| `P4.base.ws_cmd` | `touch` a file in the workspace (positive control) | Works |
| `P4.base.outside_read` | read a file outside the workspace, prompts rejected | Asked (CLI/hub) or blocked (ACP boundary) |

## Known limits of this baseline

- **Ask rules aren't enforced by CLI 1.4.12.** The baseline relies on deny rules and the guard, not on ask rules.
- **`--dangerously-skip-permissions` opens network egress inside the CLI sandbox.** Deny rules and the guard still apply. The guard blocks raw network tools for that reason.
- **VS Code workspace settings can relocate `--gemini_dir`.** In VS Code extension 1.10.0, `antigravity.serverArgs` is not restricted to machine scope: a trusted workspace whose `.vscode/settings.json` passes `--gemini_dir=<alt>` points the Hub backend away from `~/.gemini/config/{config,hooks,mcp_config}.json`. Keep VS Code Workspace Trust enabled (Restricted Mode disables the extension on untrusted folders) or pin `antigravity.serverArgs` via managed VS Code enterprise policy.
- **Repository `.agents/hooks.json` runs automatically on CLI, App, and VS Code.** Opening a repository that contains `.agents/hooks.json` runs its hook commands without a separate hooks-trust prompt on CLI (`-p`), Desktop App, and VS Code (ACP prompts specifically). Treat untrusted repositories accordingly.
- **The guard is pattern-based** and sees only what the agent passes to a tool. It complements the sandbox and the gateway (Model Armor/SDP) and doesn't replace them.
- **No Windows sandbox on Server 2022.** The Windows sandbox needs Windows 11 24H2 or later with the August 2026 update. On other Windows versions `proceed-in-sandbox` behaves like request-review.
- **macOS wasn't live-tested.** The macOS paths and `chflags` come from the official docs and the client source.
