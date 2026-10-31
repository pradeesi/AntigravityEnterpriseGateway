#!/usr/bin/env bash
# ==============================================================================
# File: /usr/local/bin/agy_security_guard.sh
# Purpose: Synchronous PreToolUse policy blocker (exit 2) & PostToolUse JSONL
#          SIEM telemetry logger for Antigravity on Linux and macOS workstations.
# Architecture/Context: Invoked automatically by ~/.gemini/config/hooks.json
#          exclusively when the Antigravity AI agent proposes (`pre`) or finishes
#          (`post`) a tool call. Never intercepts interactive commands typed
#          manually by the developer in their host shell.
# Dependencies/Side Effects: Reads hook event JSON from stdin; appends JSONL
#          audit records to AGY_AUDIT_LOG_PATH (default: /tmp/agy_security_audit.log);
#          writes violation reason to stderr and exits 2 on PreToolUse block.
# ==============================================================================
set -euo pipefail

# ==============================================================================
# BLOCK 1: RUNTIME INPUT & AUDIT TELEMETRY INITIALIZATION
# ==============================================================================
PHASE="${1:-pre}"
AUDIT_LOG="${AGY_AUDIT_LOG_PATH:-/tmp/agy_security_audit.log}"
PAYLOAD="$(cat)"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
CURRENT_USER="$(id -un)"

# ------------------------------------------------------------------------------
# Function: write_siem_audit_entry
# Summary: Appends a single-line JSONL record for SIEM / Chronicle / Splunk agents.
# Parameters:
#   None (reads global TIMESTAMP, PHASE, CURRENT_USER, PAYLOAD, AUDIT_LOG).
# Return Value:
#   0 always (never fails open or crashes tool execution if log disk is full).
# Exceptions/Errors:
#   Suppresses filesystem write errors on /tmp audit log if inaccessible.
# ------------------------------------------------------------------------------
write_siem_audit_entry() {
  printf '{"timestamp":"%s","phase":"%s","user":"%s","event":%s}\n' \
    "${TIMESTAMP}" "${PHASE}" "${CURRENT_USER}" "${PAYLOAD:-{}}" >> "${AUDIT_LOG}" 2>/dev/null || true
}

# ------------------------------------------------------------------------------
# Function: block_with_violation
# Summary: Emits structured policy block message to stderr and terminates with
#          exit code 2 so Antigravity hard-blocks the proposed tool call.
# Parameters:
#   $1 (str): Rule identifier code (e.g., RULE-1-NO-DELETE).
#   $2 (str): Human- and model-readable security explanation.
# Return Value:
#   Does not return; exits process with status code 2.
# Exceptions/Errors:
#   Exits 2.
# ------------------------------------------------------------------------------
block_with_violation() {
  local rule_id="$1"
  local message="$2"
  printf 'SECURITY_POLICY_VIOLATION [%s]: %s\n' "${rule_id}" "${message}" >&2
  exit 2
}

# ==============================================================================
# BLOCK 2: SYNCHRONOUS PRE-TOOL-USE POLICY EVALUATION (5 DEFENSE DOMAINS)
# ==============================================================================
# ------------------------------------------------------------------------------
# Function: evaluate_pre_tool_rules
# Summary: Evaluates serialized stdin toolCall JSON against 5 enterprise security
#          regex domains before any command, file, URL, or MCP tool executes.
# Parameters:
#   $1 (str): Raw JSON payload received from Antigravity on stdin.
# Return Value:
#   0 if compliant; exits 2 via block_with_violation if any rule matches.
# Exceptions/Errors:
#   Exits 2 on security policy match.
# ------------------------------------------------------------------------------
evaluate_pre_tool_rules() {
  local payload="$1"

  # Domain 1: File & Directory Deletion / Wipe Prevention (Shell + Scripting APIs)
  if printf '%s' "${payload}" | grep -Eqi '(\b(rm|rmdir|unlink|shred|srm|trash|gio|del|erase|rd|remove-item|deltree|sdelete|truncate)\s+|\bfind\s+[^"]*-(delete|exec\s+rm|execdir\s+rm)|\bgit\s+clean\s+[^"]*-[a-zA-Z]*[fdX]|\brsync\s+[^"]*--delete|os\.(remove|unlink)|shutil\.rmtree|fs\.(unlink|rmSync)|File\.delete|FileUtils\.rm)'; then
    block_with_violation "RULE-1-NO-DELETE" "File or directory deletion by the Antigravity agent is strictly prohibited."
  fi

  # Domain 2: OS Password Stores, Private Keys, Certificates & MDM Config Tampering
  if printf '%s' "${payload}" | grep -Eqi '(/etc/(shadow|gshadow|passwd|master\.passwd|sudoers|security|pam\.d|ssh|ssl/private|pki/tls/private|kubernetes|openvpn|wireguard|ipsec|krb5\.keytab|fstab|crypttab|crontab|cron\.|systemd/system|init\.d|ld\.so\.preload|hosts\.allow|hosts\.deny)|/etc/antigravity/admin_settings\.json|/private/etc/(master\.passwd|sudoers|ssh)|/Library/(Keychains|LaunchDaemons|LaunchAgents)|[\\/]+Windows[\\/]+System32[\\/]+config[\\/]+(SAM|SYSTEM|SECURITY)|NTDS\.dit|Unattend\.xml|ProgramData[\\/]+Antigravity[\\/]+admin_settings\.json|\.(pem|crt|cer|der|key|p12|pfx|jks|keystore|kdbx|ovpn|rdp|htpasswd|pgpass|netrc|git-credentials|npmrc|pypirc)("|\x27|\s|$)|[\\/](id_rsa|id_ed25519|id_ecdsa|id_dsa|authorized_keys|known_hosts|\.rhosts|\.shosts|\.Xauthority|\.env)("|\x27|\s|$)|\b(certutil|security|secret-tool|pass|keytool|vault|1password|keepassxc-cli)\s+)'; then
    block_with_violation "RULE-2-SENSITIVE-DATA" "Access to OS/system files, password databases, certificates, private keys, or remote login data is prohibited."
  fi

  # Domain 3: Network Probing, Remote Login & Lateral Movement Utilities
  if printf '%s' "${payload}" | grep -Eqi '(\b(ping|ping6|fping|arping|traceroute|traceroute6|tracert|pathping|mtr|ssh|sshd|scp|sftp|ssh-keygen|ssh-add|ssh-agent|ssh-keyscan|sshpass|plink|pscp|psftp|putty|telnet|ftp|tftp|lftp|ncftp|rsync|rsh|rlogin|rcp|rexec|nc|netcat|ncat|socat|cryptcat|xfreerdp|rdesktop|mstsc|winrs|enter-pssession|invoke-command|new-pssession|test-netconnection)\s+|/dev/(tcp|udp)/)'; then
    block_with_violation "RULE-3-NETWORK-REMOTE" "Network probing (ping/traceroute) and remote login/transfer utilities (ssh/scp/sftp/telnet/ftp/rdp/netcat) are prohibited."
  fi

  # Domain 4: Offensive Exploitation, DoS/Stress Tools, Privilege Escalation & Lock Bypass
  if printf '%s' "${payload}" | grep -Eqi '(BLOCK_BY_HOOK_TEST|--dangerously-skip|chattr\s+-i|chflags\s+noschg|\b(sudo|su|doas|pkexec|runas|gsudo|chmod|chown|chgrp|setfacl|icacls|takeown|nmap|zenmap|masscan|rustscan|zmap|nikto|sqlmap|gobuster|dirb|ffuf|wfuzz|feroxbuster|nuclei|hydra|medusa|john|hashcat|msfconsole|msfvenom|metasploit|searchsploit|responder|impacket|crackmapexec|netexec|mimikatz|bloodhound|sharphound|rubeus|chisel|ligolo|proxychains|tcpdump|tshark|wireshark|ettercap|bettercap|aircrack-ng|hping|hping3|slowloris|siege|ab|wrk|vegeta|hey|locust|k6|stress|stress-ng|iperf|iperf3|loic|hoic|goldeneye|hulk|shutdown|reboot|halt|poweroff|init|telinit|systemctl|service|launchctl|stop-service|restart-service|stop-computer|restart-computer|kill|killall|pkill|taskkill|stop-process|dd|mkfs|mke2fs|fdisk|sfdisk|parted|gdisk|wipefs|blkdiscard|mount|umount|diskutil|hdiutil|diskpart|format|bcdedit|vssadmin|wbadmin|wmic|cipher|iptables|ip6tables|nft|ufw|firewall-cmd|pfctl|netsh|route|ifconfig|insmod|rmmod|modprobe|sysctl|kexec|crontab|schtasks|useradd|usermod|userdel|passwd|chpasswd|visudo|dscl|sysadminctl|regedit|regsvr32|rundll32|mshta|cscript|wscript|bitsadmin|strace|ltrace|gdb|lldb|dtrace|bpftrace|nsenter|unshare|chroot|capsh|setcap)\s+|\b(ba|z|k|da)?sh\s+-[a-zA-Z]*i|\bcurl\s+[^"]*(-d|--data|-F|--form|-T|--upload-file)|\bwget\s+[^"]*(--post-data|--post-file))'; then
    block_with_violation "RULE-4-ANTI-EXPLOIT-DESTRUCTIVE" "Offensive security tools, DoS/stress utilities, privilege escalation, service disruption, and system-modifying commands are prohibited."
  fi

  # Domain 5: Cloud Instance Metadata SSRF & Unapproved Exfiltration Tunnels/Webhooks
  if printf '%s' "${payload}" | grep -Eqi '(169\.254\.169\.254|metadata\.google\.internal|100\.100\.100\.200|pastebin\.com|requestbin\.com|webhook\.site|pipedream\.net|interact\.sh|oastify\.com|burpcollaborator\.net|ngrok\.io|ngrok-free\.app|trycloudflare\.com|localtunnel\.me|serveo\.net|transfer\.sh|file\.io|0x0\.st|termbin\.com|api\.telegram\.org)'; then
    block_with_violation "RULE-5-RESTRICTED-URL" "Access to cloud instance metadata endpoints, paste sites, tunnels, or unapproved webhooks is prohibited."
  fi
}

# ==============================================================================
# BLOCK 3: MAIN ENTRYPOINT
# ==============================================================================
write_siem_audit_entry

if [[ "${PHASE}" == "pre" ]]; then
  evaluate_pre_tool_rules "${PAYLOAD}"
fi

exit 0
