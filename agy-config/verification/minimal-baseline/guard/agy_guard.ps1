<#
==============================================================================
FILE HEADER: agy_guard.ps1 — Baseline PreToolUse/PostToolUse guard (Windows)
==============================================================================
Purpose:
    Windows twin of agy_guard.sh: denies agent tool calls that touch
    credentials, Antigravity's own policy files, privilege escalation, raw
    network tools, cloud metadata endpoints, or file-lock changes, and appends
    one JSON audit line per call.

Architecture / Context:
    Wired in %USERPROFILE%\.gemini\config\hooks.json (minimal baseline) as
    `powershell.exe -NoProfile -ExecutionPolicy Bypass -File
    C:\ProgramData\Antigravity\bin\agy_guard.ps1 pre` (no inner quotes).
    hooks.json is the only file-based control every surface honors, including
    the JetBrains/Zed ACP server. Protocol: stdin {"toolCall":{"name","args"}};
    stdout JSON decision {"decision":"allow"|"deny","reason":"..."}.

Dependencies / Side Effects:
    Windows PowerShell 5.1+. Install read-only for users (Administrators full
    control) under C:\ProgramData\Antigravity\bin. Appends to
    %LOCALAPPDATA%\agy-guard\audit.jsonl (user-writable: the hook runs as the
    developer).
==============================================================================
#>
param(
    [ValidateSet('pre', 'post')]
    [string]$Phase = 'pre'
)

$ErrorActionPreference = 'Stop'
$payload = [Console]::In.ReadToEnd()
$lower = $payload.ToLowerInvariant()
$stateDir = Join-Path $env:LOCALAPPDATA 'agy-guard'

function Write-Audit {
    <#
    .SYNOPSIS
        Appends one audit record; logging failures never fail the tool call.
    .PARAMETER Decision
        allow | deny | post.
    .PARAMETER Rule
        Rule id ('' when none).
    #>
    param([string]$Decision, [string]$Rule)
    try {
        if (-not (Test-Path -LiteralPath $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }
        $line = @{ ts = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'); phase = $Phase;
                   decision = $Decision; rule = $Rule; bytes = $payload.Length } | ConvertTo-Json -Compress
        # UTF-8 without BOM: a BOM would break JSON-lines consumers.
        [System.IO.File]::AppendAllText((Join-Path $stateDir 'audit.jsonl'), $line + "`n",
            (New-Object System.Text.UTF8Encoding($false)))
    } catch {
        Write-Verbose "agy-guard audit write failed: $($_.Exception.Message)"
    }
}

function Deny-ToolCall {
    <#
    .SYNOPSIS
        Emits a deny decision on stdout and exits 0.
    .PARAMETER Rule
        Rule id.
    .PARAMETER Reason
        Human-readable reason shown to the agent.
    #>
    param([string]$Rule, [string]$Reason)
    Write-Audit -Decision 'deny' -Rule $Rule
    Write-Output (@{ decision = 'deny'; reason = "agy-guard ${Rule}: $Reason" } | ConvertTo-Json -Compress)
    exit 0
}

if ($Phase -eq 'post') {
    Write-Audit -Decision 'post' -Rule ''
    Write-Output '{}'
    exit 0
}

# Same groups and reasons as agy_guard.sh (see that file for the rationale per group).
if ($lower -match '(^|[^a-z0-9_])\.(ssh|aws|gnupg|kube)([/\\"]|$)|\.config[/\\]+gcloud|id_(rsa|ed25519|ecdsa)') {
    Deny-ToolCall 'G1-CREDENTIALS' 'access to credential stores is blocked by policy'
}
if ($lower -match '\.gemini[/\\]+config[/\\]+(config|hooks|mcp_config)\.json|antigravity-(cli|acp)[/\\]+settings\.json|admin_settings\.json|\.antigravity[/\\]+settings\.json|agy_guard\.(sh|ps1)') {
    Deny-ToolCall 'G2-POLICY-FILES' 'Antigravity policy files are read-only for the agent'
}
if ($lower -match '169\.254\.169\.254|metadata\.google\.internal') {
    Deny-ToolCall 'G5-METADATA' 'cloud metadata endpoints are blocked by policy'
}
# Command-only groups (file contents that merely mention these words stay editable).
if ($lower -match '"name"\s*:\s*"(run_command|send_command_input|terminal|execute|bash|shell)"') {
    if ($lower -match '(^|[^a-z0-9_-])(runas|sudo|gsudo)(\.exe)?(\s|$)|start-process[^"]*-verb\s+runas') {
        Deny-ToolCall 'G3-ELEVATION' 'privilege escalation is blocked by policy'
    }
    if ($lower -match '(^|[^a-z0-9_-])(curl|wget|nc|ncat|netcat)(\.exe)?(\s|$)|invoke-webrequest|invoke-restmethod|\biwr\b|\birm\b|net\.webclient|start-bitstransfer') {
        Deny-ToolCall 'G4-NETWORK-TOOL' 'raw network tools are blocked; use approved read_url domains'
    }
    if ($lower -match '(^|[^a-z0-9_-])(icacls|takeown|attrib|cacls)(\.exe)?(\s|$)|set-acl') {
        Deny-ToolCall 'G6-LOCK-REMOVAL' 'changing file locks is blocked by policy'
    }
}

Write-Audit -Decision 'allow' -Rule ''
Write-Output '{"decision":"allow"}'
exit 0
