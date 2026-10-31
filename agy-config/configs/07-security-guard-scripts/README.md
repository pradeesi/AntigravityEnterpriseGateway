# `agy_security_guard.sh` & `agy_security_guard.ps1` — Runtime PreToolUse Policy Blocker & SIEM Logger

## 1. What These Scripts Are Used For

[`agy_security_guard.sh`](./agy_security_guard.sh) (for **Linux & macOS**) and [`agy_security_guard.ps1`](./agy_security_guard.ps1) (for **Windows 10/11 & Server**) are the **executable enforcement binaries** invoked synchronously by [`~/.gemini/config/hooks.json`](../06-lifecycle-hooks/README.md) before (`PreToolUse`) and after (`PostToolUse`) every AI agent tool call.

They provide two critical enterprise security capabilities:
1. **Payload-Deep `PreToolUse` Inspection & Hard Blocking (`exit 2`)**: While static `command(...)` / `read_file(...)` permission grants evaluate binary names and file paths, `agy_security_guard` inspects the **entire serialized `toolCall` JSON** (including inline Python/Node one-liners like `os.remove(...)` / `shutil.rmtree(...)`, curl POST/upload flags `-d`/`-F`/`-T`, Windows SAM/NTDS paths, certificate/key extensions `.pem`/`.pfx`/`.kdbx`, and SSRF metadata IPs `169.254.169.254`). Any match writes a deterministic `SECURITY_POLICY_VIOLATION [RULE-*]` message to `stderr` and exits with status `2`, aborting tool execution before it touches the OS.
2. **Local JSONL Compliance & SIEM Audit Trail (`PostToolUse` & `PreToolUse`)**: Appends a timestamped single-line JSON record (`timestamp`, `phase`, `user`, `event`) for every proposed and completed tool invocation so endpoint forwarders (Fluent Bit, Splunk Universal Forwarder, Google Cloud Ops Agent / SecOps) can stream agent activity centrally.

---

## 2. Official Public Documentation Links

* **Lifecycle Hooks Input/Output Contract & Handler Execution**:
  * [Antigravity Lifecycle Hooks Overview](https://antigravity.google/docs/hooks/)
  * [PreToolUse & PostToolUse Input/Output Contract (`#pretooluse`)](https://antigravity.google/docs/hooks/#pretooluse)

---

## 3. Where These Scripts Should Go (Target Locations)

| Script File | Operating System | Exact Target Installation Path | Required Owner | Required File Mode / ACL | Immutability Lock |
| :--- | :--- | :--- | :--- | :--- | :--- |
| [`agy_security_guard.sh`](./agy_security_guard.sh) | **Linux** | `/usr/local/bin/agy_security_guard.sh` | `root:root` | **`0755`** (`-rwxr-xr-x`, executable) | `chattr +i` |
| [`agy_security_guard.sh`](./agy_security_guard.sh) | **macOS** | `/usr/local/bin/agy_security_guard.sh` | `root:wheel` | **`0755`** (`-rwxr-xr-x`, executable) | `chflags schg` |
| [`agy_security_guard.ps1`](./agy_security_guard.ps1) | **Windows** | `C:\ProgramData\Antigravity\bin\agy_security_guard.ps1` | `Administrators` | `SYSTEM:(F)`, `Administrators:(F)`, `<USER>:(RX)` + Deny `(WD,AD,WEA,WA,DE,WDAC,WO)` | `attrib +R` + NTFS Deny ACE |

---

## 4. Parameters, Environment Variables, Exit Codes & Rule Domains Reference Tables

### Table A — CLI Arguments, Environment Variables, Streams & Exit Codes

| Interface Element | Name / Value | Type | Default | Behavior |
| :--- | :--- | :--- | :--- | :--- |
| **Positional Arg 1** | `pre` \| `post` (`$1` / `-Phase`) | `string` | `"pre"` | `"pre"` logs the event **and** runs all 5 blocking security regex checks; `"post"` logs the post-execution telemetry record and exits `0`. |
| **Environment Var** | `AGY_AUDIT_LOG_PATH` | `string` (path) | Linux/macOS: `/tmp/agy_security_audit.log`<br>Windows: `C:\Windows\Temp\agy_security_audit.log` | Overrides the output file path where single-line JSONL SIEM audit records are appended. |
| **Standard Input** | `stdin` | JSON object | `{}` | Receives Antigravity's hook payload (`conversationId`, `workspacePaths`, `modelName`, `stepIdx`, `toolCall.name`, `toolCall.args`, `error`). |
| **Exit Code `0`** | Compliant / Allowed | `int` | — | Allows `PreToolUse` execution to proceed to Antigravity's sandbox and permission engine (or completes `PostToolUse` cleanly). |
| **Exit Code `2`** | Policy Violation Block | `int` | — | Immediately hard-blocks the tool call in `PreToolUse` and surfaces `stderr` output to the user/model. |

### Table B — The 5 Enforced `PreToolUse` Security Rule Domains

| Rule ID | Security Domain | Examples of Blocked Patterns |
| :--- | :--- | :--- |
| **`RULE-1-NO-DELETE`** | File & Directory Deletion / Wipe Prevention | `rm`, `rmdir`, `unlink`, `shred`, `srm`, `trash`, `del`, `erase`, `Remove-Item`, `find -delete`, `git clean -fd`, `rsync --delete`, `os.remove`, `shutil.rmtree`, `fs.rmSync` |
| **`RULE-2-SENSITIVE-DATA`** | OS Password Stores, Keys, Certs & MDM Configs | `/etc/shadow`, `/etc/sudoers`, `/Library/Keychains`, `\Windows\System32\config\SAM`, `NTDS.dit`, `admin_settings.json`, `id_rsa`, `id_ed25519`, `.env`, `.pem`, `.pfx`, `.kdbx`, `certutil`, `vault`, `1password` |
| **`RULE-3-NETWORK-REMOTE`** | Network Probing & Remote Lateral Movement | `ping`, `traceroute`, `tracert`, `ssh`, `scp`, `sftp`, `putty`, `telnet`, `ftp`, `nc`, `netcat`, `socat`, `mstsc`, `winrs`, `Enter-PSSession`, `/dev/tcp/` |
| **`RULE-4-ANTI-EXPLOIT-DESTRUCTIVE`** | Exploitation, DoS, PrivEsc & Lock Tampering | `sudo`, `su`, `chattr -i`, `chflags noschg`, `icacls`, `takeown`, `--dangerously-skip`, `nmap`, `sqlmap`, `metasploit`, `mimikatz`, `wrk`, `hping3`, `bash -i`, `curl -d/-F/-T`, `wget --post-file`, `systemctl`, `diskpart`, `regedit` |
| **`RULE-5-RESTRICTED-URL`** | Cloud Metadata SSRF & Exfiltration Tunnels | `169.254.169.254`, `metadata.google.internal`, `100.100.100.200`, `pastebin.com`, `webhook.site`, `interact.sh`, `oastify.com`, `ngrok.io`, `trycloudflare.com`, `transfer.sh`, `api.telegram.org` |

---

## 5. Manual Administrator Commands (Deploy, Set `0755` / Execute Permissions & Lock)

### A. Linux (Run as `root` / `sudo`)

```bash
TARGET_BIN="/usr/local/bin/agy_security_guard.sh"

# 1. Unlock existing binary if previously locked
sudo chattr -i "${TARGET_BIN}" 2>/dev/null || true

# 2. Validate Bash syntax, install as root:root with executable 0755 permissions, and lock with chattr +i
bash -n ./agy_security_guard.sh
sudo mkdir -p /usr/local/bin
sudo install -m 0755 -o root -g root ./agy_security_guard.sh "${TARGET_BIN}"
sudo chattr +i "${TARGET_BIN}"

# 3. Smoke-test benign vs. blocked tool payload & verify lsattr
echo '{"toolCall":{"name":"run_command","args":{"CommandLine":"git status"}}}' | "${TARGET_BIN}" pre && echo "ALLOW_OK"
ls -la "${TARGET_BIN}"
sudo lsattr "${TARGET_BIN}"
```

*To unlock later for admin edits on Linux:*
```bash
sudo chattr -i /usr/local/bin/agy_security_guard.sh
```

### B. macOS (Run as `root` / `sudo` or via Jamf / Kandji)

```bash
TARGET_BIN="/usr/local/bin/agy_security_guard.sh"

# 1. Remove macOS system-immutable flag if present
sudo chflags noschg,nouchg "${TARGET_BIN}" 2>/dev/null || true

# 2. Validate Bash syntax, install as root:wheel (0755), and lock with chflags schg
bash -n ./agy_security_guard.sh
sudo mkdir -p /usr/local/bin
sudo install -m 0755 -o root -g wheel ./agy_security_guard.sh "${TARGET_BIN}"
sudo chflags schg "${TARGET_BIN}"

# 3. Verify executable permissions and 'schg' flag
ls -lO "${TARGET_BIN}"
```

*To unlock later for admin edits on macOS:*
```bash
sudo chflags noschg,nouchg /usr/local/bin/agy_security_guard.sh
```

### C. Windows 10 / 11 / Server (Run in Elevated Administrator PowerShell)

```powershell
$DevUser    = "alice"   # <-- Replace with target Windows username (or use "*S-1-5-32-545" for all Users)
$TargetDir  = "C:\ProgramData\Antigravity\bin"
$TargetFile = "$TargetDir\agy_security_guard.ps1"

# 1. Unlock existing script if present
if (Test-Path -LiteralPath $TargetFile) {
    attrib.exe -R $TargetFile
    icacls.exe $TargetFile /reset | Out-Null
}

# 2. Create directory and copy agy_security_guard.ps1
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
Copy-Item -LiteralPath ".\agy_security_guard.ps1" -Destination $TargetFile -Force

# 3. Grant Read & Execute (RX) to developer/Users, Full Control to SYSTEM/Admins, and Deny Write/Delete
takeown.exe /F $TargetFile /A | Out-Null
icacls.exe $TargetFile /inheritance:r `
    /grant:r "SYSTEM:(F)" `
    /grant:r "Administrators:(F)" `
    /grant:r "${DevUser}:(RX)" `
    /deny "${DevUser}:(WD,AD,WEA,WA,DE,WDAC,WO)" | Out-Null
attrib.exe +R $TargetFile

# 4. Smoke-test benign payload and verify ACLs
'{"toolCall":{"name":"run_command","args":{"CommandLine":"git status"}}}' |
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $TargetFile pre
icacls.exe $TargetFile
```

*To unlock later for admin edits on Windows:*
```powershell
$TargetFile = "C:\ProgramData\Antigravity\bin\agy_security_guard.ps1"
attrib.exe -R $TargetFile
icacls.exe $TargetFile /remove:d $DevUser | Out-Null
```
