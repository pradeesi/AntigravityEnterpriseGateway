<#
==============================================================================
FILE HEADER: deploy_baseline.ps1 — Install and lock the AGY minimal baseline (Windows)
==============================================================================
Purpose:
    Renders the minimal-baseline templates for one developer account, installs
    them where each Antigravity surface reads them, and locks the files the
    developer could otherwise edit (read-only attribute + deny-write ACL).

Architecture / Context:
    Windows twin of deploy_baseline.sh (same file set and rationale). The
    machine-wide admin_settings.json lives in %ProgramData%\Antigravity; the
    guard script in %ProgramData%\Antigravity\bin; per-user files under
    C:\Users\<user>\.gemini.

Dependencies / Side Effects:
    Run in an elevated Windows PowerShell 5.1+. Uses attrib.exe and icacls.exe.
    The deny ACE is (WD,AD,WEA,WA,DE,WDAC,WO): a generic (W) deny includes
    SYNCHRONIZE and would also break reads. attrib +R is applied before the
    deny ACE, and the ACE is removed before attrib -R on unlock. Files are
    written as UTF-8 without BOM (a BOM breaks the clients' JSON parser).
    The gateway key is read from a file, never passed on the command line.
==============================================================================
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9._-]{1,64}$')][string]$User,
    [ValidateSet('Deploy', 'Unlock', 'Status')][string]$Action = 'Deploy',
    [string]$GatewayUrl = '',
    [string]$GatewayKeyFile = '',
    [ValidatePattern('^[A-Za-z0-9_.-]{1,64}$')][string]$CostCenter = 'engineering'
)

$ErrorActionPreference = 'Stop'
$BaseDir = Split-Path -Parent $PSScriptRoot
$AdminDir = Join-Path $env:ProgramData 'Antigravity'
$GuardDir = Join-Path $AdminDir 'bin'
$GuardPath = Join-Path $GuardDir 'agy_guard.ps1'
$DenyRights = '(WD,AD,WEA,WA,DE,WDAC,WO)'

function Write-Log {
    <#
    .SYNOPSIS
        Structured log line (timestamp, level, message) on the host.
    .PARAMETER Level
        INFO | WARN | ERROR.
    .PARAMETER Message
        Text to log.
    #>
    param([string]$Level, [string]$Message)
    Write-Host ("{0} {1,-5} deploy_baseline: {2}" -f (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ'), $Level, $Message)
}

function Set-FileLock {
    <#
    .SYNOPSIS
        Locks or unlocks one file for the developer account.
    .PARAMETER Path
        File path (ignored when missing).
    .PARAMETER On
        $true to lock, $false to unlock.
    #>
    param([string]$Path, [bool]$On)
    if (-not (Test-Path -LiteralPath $Path)) { return }
    if ($On) {
        & attrib.exe +R $Path | Out-Null
        & icacls.exe $Path /deny "${User}:$DenyRights" | Out-Null
    } else {
        & icacls.exe $Path /remove:d $User | Out-Null
        & attrib.exe -R $Path | Out-Null
    }
}

function Write-Utf8NoBom {
    <#
    .SYNOPSIS
        Writes text as UTF-8 without a byte-order mark.
    .PARAMETER Path
        Destination file.
    .PARAMETER Text
        Content.
    #>
    param([string]$Path, [string]$Text)
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding($false)))
}

# ------------------------------------------------------------------ validation
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Log ERROR 'run from an elevated PowerShell'; exit 1
}
$DevHome = Join-Path 'C:\Users' $User
if (-not (Test-Path -LiteralPath $DevHome)) { Write-Log ERROR "profile folder $DevHome not found"; exit 2 }

# Forward slashes: the JetBrains/Zed ACP server splits hook commands POSIX-style and drops
# backslashes ("External hook ... failed to execute", which denies every tool call).
$GuardCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File $($GuardPath.Replace('\', '/'))"
$Files = @(
    @{ Template = 'files\admin_settings.json'; Dest = (Join-Path $AdminDir 'admin_settings.json'); Owner = 'admin' },
    @{ Template = 'files\config.json'; Dest = (Join-Path $DevHome '.gemini\config\config.json'); Owner = 'user' },
    @{ Template = 'files\cli-settings.json'; Dest = (Join-Path $DevHome '.gemini\antigravity-cli\settings.json'); Owner = 'user' },
    @{ Template = 'files\hooks.json'; Dest = (Join-Path $DevHome '.gemini\config\hooks.json'); Owner = 'user' },
    @{ Template = 'files\mcp_config.json'; Dest = (Join-Path $DevHome '.gemini\config\mcp_config.json'); Owner = 'user' },
    @{ Template = 'files\antigravity-acp-settings.json'; Dest = (Join-Path $DevHome '.gemini\antigravity-acp\settings.json'); Owner = 'user' }
)

switch ($Action) {
    'Status' {
        foreach ($f in $Files + @(@{ Dest = $GuardPath })) {
            $state = if (-not (Test-Path -LiteralPath $f.Dest)) { 'missing' }
                     elseif ((Get-Item -LiteralPath $f.Dest).IsReadOnly) { 'locked' } else { 'unlocked' }
            '{0,-9} {1}' -f $state, $f.Dest
        }
        exit 0
    }
    'Unlock' {
        foreach ($f in $Files) { if ($f.Owner -eq 'user') { Set-FileLock -Path $f.Dest -On $false } }
        Write-Log INFO "unlocked managed files for $User"
        exit 0
    }
}

if ($GatewayUrl -notmatch '^https://[A-Za-z0-9.-]+(:[0-9]+)?(/.*)?$') { Write-Log ERROR '-GatewayUrl must be https://'; exit 2 }
if (-not (Test-Path -LiteralPath $GatewayKeyFile)) { Write-Log ERROR '-GatewayKeyFile not found'; exit 2 }
$GatewayKey = (Get-Content -Raw -LiteralPath $GatewayKeyFile).Trim()
if (-not $GatewayKey) { Write-Log ERROR 'gateway key file is empty'; exit 2 }

# Render and validate everything first: a malformed admin_settings.json makes clients
# drop gateway mode and fall back to Google sign-in.
$rendered = @{}
foreach ($f in $Files) {
    $text = Get-Content -Raw -LiteralPath (Join-Path $BaseDir $f.Template)
    # JSON-escape values that land inside JSON strings (Windows paths contain backslashes).
    $homeJson = $DevHome.Replace('\', '\\')
    $text = $text.Replace('__HOME__', $homeJson).Replace('__GATEWAY_URL__', $GatewayUrl).
        Replace('__GATEWAY_API_KEY__', $GatewayKey).Replace('__COST_CENTER__', $CostCenter).
        Replace('__GUARD_COMMAND__', $GuardCommand)
    try { $null = $text | ConvertFrom-Json } catch { Write-Log ERROR "rendered $($f.Template) is not valid JSON"; exit 3 }
    $rendered[$f.Dest] = $text
}

foreach ($f in $Files) { if ($f.Owner -eq 'user') { Set-FileLock -Path $f.Dest -On $false } }
New-Item -ItemType Directory -Force -Path $GuardDir | Out-Null
Copy-Item -Force -LiteralPath (Join-Path $BaseDir 'guard\agy_guard.ps1') -Destination $GuardPath
# Users may read and execute the guard but not change it (ProgramData grants users write by default).
& icacls.exe $GuardDir /inheritance:r /grant:r 'Administrators:(OI)(CI)F' 'SYSTEM:(OI)(CI)F' 'Users:(OI)(CI)RX' | Out-Null

foreach ($f in $Files) {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $f.Dest) | Out-Null
    Write-Utf8NoBom -Path $f.Dest -Text $rendered[$f.Dest]
    if ($f.Owner -eq 'admin') {
        & icacls.exe $f.Dest /inheritance:r /grant:r 'Administrators:F' 'SYSTEM:F' 'Users:R' | Out-Null
    } else {
        Set-FileLock -Path $f.Dest -On $true
    }
    Write-Log INFO "installed and locked $($f.Dest)"
}
Write-Log INFO "baseline deployed for $User; verify with: .\deploy_baseline.ps1 -User $User -Action Status"
