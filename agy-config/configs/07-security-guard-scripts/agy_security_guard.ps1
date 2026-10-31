<#
==============================================================================
File: C:\ProgramData\Antigravity\bin\agy_security_guard.ps1
Purpose: Synchronous PreToolUse policy blocker (exit 2) & PostToolUse JSONL
         SIEM telemetry logger for Antigravity on Windows 10/11 & Server.
Architecture/Context: Invoked by ~/.gemini/config/hooks.json on Windows exclusively
         when the Antigravity AI agent proposes (`pre`) or finishes (`post`) a tool
         call. Acts as the primary runtime command gatekeeper on Windows machines
         where native OS terminal sandboxing is unavailable.
Dependencies/Side Effects: Reads hook JSON from stdin; appends JSONL audit records
         to $env:AGY_AUDIT_LOG_PATH (default: C:\Windows\Temp\agy_security_audit.log);
         writes violation reason to stderr and exits 2 on PreToolUse block.
==============================================================================
#>
param(
    [Parameter(Position = 0)]
    [string]$Phase = "pre"
)

$ErrorActionPreference = "SilentlyContinue"

# ==============================================================================
# BLOCK 1: RUNTIME INPUT & SIEM AUDIT LOGGING HELPERS
# ==============================================================================
$AuditLog = if ($env:AGY_AUDIT_LOG_PATH) { $env:AGY_AUDIT_LOG_PATH } else { "C:\Windows\Temp\agy_security_audit.log" }
$Payload = [Console]::In.ReadToEnd()
$Timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

<#
.SYNOPSIS
    Appends a single structured JSONL audit event to the local SIEM log file.
.PARAMETER RawPayload
    Raw JSON string read from standard input.
.OUTPUTS
    None.
#>
function Write-SiemAuditEntry {
    param([string]$RawPayload)
    $PayloadJson = if ([string]::IsNullOrWhiteSpace($RawPayload)) { "{}" } else { $RawPayload.Trim() }
    $AuditEntry = "{`"timestamp`":`"$Timestamp`",`"phase`":`"$Phase`",`"user`":`"$CurrentUser`",`"event`":$PayloadJson}"
    Add-Content -Path $AuditLog -Value $AuditEntry -Encoding UTF8 -ErrorAction SilentlyContinue
}

<#
.SYNOPSIS
    Writes a standardized policy violation message to stderr and exits with code 2.
.PARAMETER RuleId
    Identifier of the triggered security policy rule.
.PARAMETER Reason
    Explanation returned to Antigravity for why the tool call was blocked.
.OUTPUTS
    Terminates process with exit code 2.
#>
function Stop-WithPolicyViolation {
    param(
        [string]$RuleId,
        [string]$Reason
    )
    [Console]::Error.WriteLine("SECURITY_POLICY_VIOLATION [$RuleId]: $Reason")
    exit 2
}

# ==============================================================================
# BLOCK 2: SYNCHRONOUS PRE-TOOL-USE POLICY EVALUATION (5 DEFENSE DOMAINS)
# ==============================================================================
<#
.SYNOPSIS
    Evaluates the proposed toolCall JSON payload against 5 security regex domains.
.PARAMETER RawPayload
    Raw JSON string read from standard input.
.OUTPUTS
    None if compliant; terminates with exit code 2 on violation.
#>
function Test-PreToolSecurityRules {
    param([string]$RawPayload)

    # Domain 1: File & Directory Deletion / Wipe Prevention
    if ($RawPayload -match '(?i)(\b(rm|rmdir|unlink|shred|srm|trash|del|erase|rd|remove-item|ri|deltree|sdelete|truncate)\s+|\bfind\s+[^"]*-(delete|exec\s+rm)|\bgit\s+clean\s+[^"]*-[a-zA-Z]*[fdX]|os\.(remove|unlink)|shutil\.rmtree|fs\.(unlink|rmSync))') {
        Stop-WithPolicyViolation -RuleId "RULE-1-NO-DELETE" -Reason "File or directory deletion by the Antigravity agent is strictly prohibited."
    }

    # Domain 2: Windows SAM/NTDS, OS Password Databases, Certificates, Keys & MDM Configs
    # Note: Use [\\/]+ so paths match single backslashes, JSON-escaped double backslashes (\\), and forward slashes (/).
    if ($RawPayload -match '(?i)([\\/]+Windows[\\/]+System32[\\/]+config[\\/]+(SAM|SYSTEM|SECURITY)|NTDS\.dit|[\\/]+Windows[\\/]+Panther[\\/]+Unattend\.xml|ProgramData[\\/]+Antigravity[\\/]+admin_settings\.json|/etc/(shadow|gshadow|passwd|master\.passwd|sudoers)|\.ssh|\.gnupg|\.(pem|crt|cer|der|key|p12|pfx|jks|keystore|kdbx|ovpn|rdp|htpasswd|pgpass|netrc|git-credentials|npmrc|pypirc)("|\x27|\s|$)|[\\/](id_rsa|id_ed25519|id_ecdsa|id_dsa|authorized_keys|known_hosts|\.env)("|\x27|\s|$)|\b(certutil|security|secret-tool|pass|keytool|vault|1password|keepassxc-cli)\s+)') {
        Stop-WithPolicyViolation -RuleId "RULE-2-SENSITIVE-DATA" -Reason "Access to OS/system files, password databases, certificates, private keys, or remote login data is prohibited."
    }

    # Domain 3: Network Probing, Remote Login & Lateral Movement
    if ($RawPayload -match '(?i)\b(ping|ping6|fping|arping|traceroute|tracert|pathping|mtr|ssh|sshd|scp|sftp|ssh-keygen|ssh-add|ssh-keyscan|plink|pscp|psftp|putty|telnet|ftp|tftp|rsync|rsh|rlogin|rcp|nc|netcat|ncat|socat|xfreerdp|rdesktop|mstsc|winrs|enter-pssession|invoke-command|new-pssession|test-netconnection)\s+') {
        Stop-WithPolicyViolation -RuleId "RULE-3-NETWORK-REMOTE" -Reason "Network probing (ping/tracert) and remote login/transfer utilities (ssh/scp/sftp/telnet/ftp/rdp/winrs) are prohibited."
    }

    # Domain 4: Vulnerability Exploitation, DoS/Stress Testing, Privilege Escalation & ACL Bypass
    if ($RawPayload -match '(?i)(BLOCK_BY_HOOK_TEST|--dangerously-skip|\b(sudo|su|runas|gsudo|icacls|cacls|takeown|attrib|nmap|zenmap|masscan|rustscan|zmap|nikto|sqlmap|gobuster|dirb|ffuf|wfuzz|feroxbuster|nuclei|hydra|medusa|john|hashcat|msfconsole|msfvenom|metasploit|responder|impacket|crackmapexec|netexec|mimikatz|bloodhound|sharphound|rubeus|chisel|ligolo|proxychains|tcpdump|tshark|wireshark|bettercap|hping3|slowloris|siege|ab|wrk|vegeta|hey|locust|k6|stress|loic|hoic|shutdown|reboot|Stop-Service|Restart-Service|Stop-Computer|Restart-Computer|kill|taskkill|Stop-Process|diskpart|format|Format-Volume|Clear-Disk|Initialize-Disk|bcdedit|vssadmin|wbadmin|wmic|cipher|netsh|route|schtasks|Register-ScheduledTask|New-LocalUser|Add-LocalGroupMember|reg|regedit|regsvr32|rundll32|mshta|cscript|wscript|bitsadmin|certreq)\s+|\bcurl\s+[^"]*(-d|--data|-F|--form|-T|--upload-file)|\bwget\s+[^"]*(--post-data|--post-file))') {
        Stop-WithPolicyViolation -RuleId "RULE-4-ANTI-EXPLOIT-DESTRUCTIVE" -Reason "Offensive security tools, DoS/stress utilities, privilege escalation, service disruption, and system-modifying commands are prohibited."
    }

    # Domain 5: Cloud Metadata SSRF & Data Exfiltration Endpoints
    if ($RawPayload -match '(?i)(169\.254\.169\.254|metadata\.google\.internal|100\.100\.100\.200|pastebin\.com|requestbin\.com|webhook\.site|pipedream\.net|interact\.sh|oastify\.com|burpcollaborator\.net|ngrok\.io|ngrok-free\.app|trycloudflare\.com|localtunnel\.me|serveo\.net|transfer\.sh|file\.io|0x0\.st|termbin\.com|api\.telegram\.org)') {
        Stop-WithPolicyViolation -RuleId "RULE-5-RESTRICTED-URL" -Reason "Access to cloud instance metadata endpoints, paste sites, tunnels, or unapproved webhooks is prohibited."
    }
}

# ==============================================================================
# BLOCK 3: MAIN ENTRYPOINT
# ==============================================================================
Write-SiemAuditEntry -RawPayload $Payload

if ($Phase -eq "pre") {
    Test-PreToolSecurityRules -RawPayload $Payload
}

exit 0
