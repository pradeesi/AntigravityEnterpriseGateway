# `browserAllowlist.txt` — Antigravity Browser Subagent Domain Allowlist

## 1. What This File Is Used For

[`browserAllowlist.txt`](./browserAllowlist.txt) (`~/.gemini/antigravity/browserAllowlist.txt`) is the **local domain allowlist** for Antigravity's built-in **Browser Subagent** (used when the agent launches or drives an isolated local Chrome profile to inspect dev servers, verify UI changes, or read web documentation).

Antigravity's browser integration enforces a **two-layer URL security model**:
1. **Layer 1 — Server-Side Denylist (Highest Precedence)**: Before navigating to any URL, Antigravity checks the target hostname against Google's `BadUrlsChecker` service (or fails closed if unreachable). A denylisted domain can **never** be overridden by `browserAllowlist.txt`.
2. **Layer 2 — Local Allowlist (`browserAllowlist.txt`)**: By default on a fresh install, `browserAllowlist.txt` contains only `localhost`. Whenever the Browser Subagent attempts to open a URL not listed in `browserAllowlist.txt`, Antigravity blocks navigation and presents an interactive **"Always allow"** button — clicking that button appends the domain to `~/.gemini/antigravity/browserAllowlist.txt`.

### Why Kernel Locking `browserAllowlist.txt` Matters in Enterprise Environments

* Populating `browserAllowlist.txt` with your organization's approved domains (e.g., `localhost`, `127.0.0.1`, `docs.cloud.google.com`, `internal.corp.example.com`) and locking the file with `chattr +i` (Linux), `chflags schg` (macOS), or `icacls /deny` (Windows) prevents developers or prompt-injected agents from persisting unapproved external websites into the trusted browser list.
* Pair `browserAllowlist.txt` with `read_url(...)` and `execute_url(...)` rules in [`settings.json`](../02-cli-settings/README.md) and [`config.json`](../03-desktop-hub-config/README.md) (plus `"browserJsExecutionPolicy": "BROWSER_JS_EXECUTION_POLICY_DISABLED"` in `config.json`) to enforce defense-in-depth across headless URL fetches (`read_url_content`), sandboxed `curl` calls, and Chrome actuation.

> [!NOTE]
> **Antigravity 2.x Architecture Note (Verified in Client Source & Live Tests):** While `browserAllowlist.txt` remains documented in public IDE docs, the Antigravity 2.x Hub (`2.28.2`) and CLI (`1.4.12`) permission stores evaluate `read_url(<domain>)` and `execute_url(<domain>)` grants in [`config.json`](../03-desktop-hub-config/README.md) and [`settings.json`](../02-cli-settings/README.md) (alongside `browserJsExecutionPolicy` in `config.json`) rather than reading `browserAllowlist.txt`. Rely on `config.json`, `settings.json`, and `hooks.json` for active URL/egress enforcement; deploying and locking `browserAllowlist.txt` is optional legacy defense-in-depth.

---

## 2. Official Public Documentation Links

* **Browser Allowlist & Denylist Two-Layer Security Guide**:
  * [Allowlist and Denylist (`~/.gemini/antigravity/browserAllowlist.txt`)](https://antigravity.google/docs/ide/allowlist-denylist/)
* **Browser Subagent Overview & Isolated Chrome Profile**:
  * [Browser Overview](https://antigravity.google/docs/ide/browser/)
  * [Separate Chrome Profile](https://antigravity.google/docs/ide/separate-chrome-profile/)
* **Interaction with `read_url(...)`, `execute_url(...)`, and Strict Mode**:
  * [Agent Permissions — Understanding `read_url` and `execute_url`](https://antigravity.google/docs/permissions/#supported-actions-and-matching-rules)
  * [Antigravity Settings — Browser URL Allowlist and Denylist](https://antigravity.google/docs/settings/#browser-url-allowlist-and-denylist)

---

## 3. Where This File Should Go (Target Locations)

| Operating System | Exact Target File Path | Parent Dir Owner | File Owner & Mode | Immutability Lock |
| :--- | :--- | :--- | :--- | :--- |
| **Linux** | `/home/<USERNAME>/.gemini/antigravity/browserAllowlist.txt` | `<USERNAME>:<USERNAME>` (`0755`) | `root:root` (`0644` or `0444`) | `chattr +i` |
| **macOS** | `/Users/<USERNAME>/.gemini/antigravity/browserAllowlist.txt` | `<USERNAME>:staff` (`0755`) | `root:wheel` (`0644` or `0444`) | `chflags schg` |
| **Windows** | `C:\Users\<USERNAME>\.gemini\antigravity\browserAllowlist.txt` | `<USERNAME>` | `Administrators` (`ReadOnly`) | `icacls /deny "<USERNAME>:(WD,AD,WEA,WA,DE,WDAC,WO)"` + `attrib +R` |

---

## 4. Allowed Syntax, Entry Formats & Directives Table

Unlike JSON configuration files, `browserAllowlist.txt` is a **UTF-8 line-delimited plaintext file** (one hostname/domain rule per line).

| Entry / Token Pattern | Syntax Type | Allowed? | Example | Evaluation Behavior |
| :--- | :--- | :---: | :--- | :--- |
| `# <comment text>` | Comment line | **Yes** | `# Approved Corporate Domains` | Lines starting with `#` and blank/whitespace-only lines are ignored by the parser. |
| `localhost` | Loopback hostname | **Yes** *(Default)* | `localhost` | Built-in initial default entry; permits local web app preview and dev-server testing across ports. |
| `<IPv4>` or `<IPv6>` | Loopback / IP literal | **Yes** | `127.0.0.1` | Permits direct loopback or approved internal IP address navigation. |
| `<exact-fqdn>` | Hostname / Domain | **Yes** | `docs.cloud.google.com` | Trusts the specified domain (and subdomains per hostname matching rules) across standard HTTP/HTTPS ports. |
| `<parent-domain>` | Apex / Internal Domain | **Yes** | `internal.corp.example.com` | Trusts internal documentation portals, intranet dashboards, or artifact registries. |
| `http://...` / URL paths | Scheme or path suffix | **Avoid** *(Use bare hostname)* | Use `pkg.go.dev` *(not `https://pkg.go.dev/std`)* | Allowlist matching evaluates hostnames rather than URL path segments; specify clean hostnames/domains only. |
| Denylisted malicious host | Blocked by Layer 1 | **No** *(Overridden)* | Known phishing/malware domain | Server-side `BadUrlsChecker` denylist **always** overrides `browserAllowlist.txt`. |

---

## 5. Manual Administrator Commands (Deploy, Set Permissions & Lock)

### A. Linux (Run as `root` / `sudo`)

```bash
DEV_USER="alice"   # <-- Replace with target developer OS username
USER_HOME="$(getent passwd "${DEV_USER}" | cut -d: -f6)"
TARGET_FILE="${USER_HOME}/.gemini/antigravity/browserAllowlist.txt"

# 1. Unlock existing file if previously locked
sudo chattr -i "${TARGET_FILE}" 2>/dev/null || true

# 2. Ensure parent directories exist and belong to the developer (so ~/.gemini/antigravity/brain artifacts stay writable!)
sudo mkdir -p "${USER_HOME}/.gemini/antigravity"
sudo chown "${DEV_USER}:${DEV_USER}" "${USER_HOME}/.gemini" "${USER_HOME}/.gemini/antigravity"

# 3. Copy browserAllowlist.txt, set root:root ownership (0644), and lock with chattr +i
sudo install -m 0644 -o root -g root ./browserAllowlist.txt "${TARGET_FILE}"
sudo chattr +i "${TARGET_FILE}"

# 4. Verify ownership and 'i' immutable attribute
ls -la "${TARGET_FILE}"
sudo lsattr "${TARGET_FILE}"
```

*To unlock later for admin edits on Linux:*
```bash
sudo chattr -i "/home/${DEV_USER}/.gemini/antigravity/browserAllowlist.txt"
```

### B. macOS (Run as `root` / `sudo` or via Jamf / Kandji)

```bash
DEV_USER="alice"   # <-- Replace with target macOS developer username
USER_HOME="/Users/${DEV_USER}"
TARGET_FILE="${USER_HOME}/.gemini/antigravity/browserAllowlist.txt"

# 1. Remove macOS system-immutable flag if present
sudo chflags noschg,nouchg "${TARGET_FILE}" 2>/dev/null || true

# 2. Ensure parent directories belong to developer:staff
sudo mkdir -p "${USER_HOME}/.gemini/antigravity"
sudo chown "${DEV_USER}:staff" "${USER_HOME}/.gemini" "${USER_HOME}/.gemini/antigravity"

# 3. Install file as root:wheel (0644) and lock with chflags schg
sudo install -m 0644 -o root -g wheel ./browserAllowlist.txt "${TARGET_FILE}"
sudo chflags schg "${TARGET_FILE}"

# 4. Verify ownership and 'schg' flag
ls -lO "${TARGET_FILE}"
```

*To unlock later for admin edits on macOS:*
```bash
sudo chflags noschg,nouchg "/Users/${DEV_USER}/.gemini/antigravity/browserAllowlist.txt"
```

### C. Windows 10 / 11 / Server (Run in Elevated Administrator PowerShell)

```powershell
$DevUser    = "alice"   # <-- Replace with target Windows username
$TargetDir  = "C:\Users\$DevUser\.gemini\antigravity"
$TargetFile = "$TargetDir\browserAllowlist.txt"

# 1. Unlock existing file if present
if (Test-Path -LiteralPath $TargetFile) {
    attrib.exe -R $TargetFile
    icacls.exe $TargetFile /remove:d $DevUser | Out-Null
    icacls.exe $TargetFile /grant "${DevUser}:(M)" | Out-Null
}

# 2. Ensure parent directory exists and copy browserAllowlist.txt
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
Copy-Item -LiteralPath ".\browserAllowlist.txt" -Destination $TargetFile -Force

# 3. Set Administrator ownership, ReadOnly attribute, and explicit Deny Write/Delete ACL
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
$TargetFile = "C:\Users\$DevUser\.gemini\antigravity\browserAllowlist.txt"
attrib.exe -R $TargetFile
icacls.exe $TargetFile /remove:d $DevUser | Out-Null
```
