<#
==============================================================================
File: scripts\deploy_and_lock_windows.ps1
Purpose: Production MDM deployment, dynamic template rendering, Windows hook
         path adaptation, and NTFS Deny-ACL locking script for Google Antigravity
         CLI, Desktop App, VS Code, JetBrains IDEs, and Zed on Windows 10/11/Server.
Architecture/Context: Designed for Microsoft Intune, SCCM, GPO startup scripts,
         or Elevated Administrator PowerShell. Reads modular templates from
         `..\configs\01-*` through `..\configs\08-*`, loads `..\settings.env` and
         optional `..\.env`, adapts Windows paths (including unquoted `-File`
         PowerShell hook invocation and optional `unsandboxed(...)` allow grants),
         and locks all files with `takeown` + `icacls /deny (WD,AD,WEA,WA,DE,WDAC,WO)`.
Dependencies/Side Effects: Requires Elevated Administrator PowerShell 5.1+ or 7+
         and `icacls.exe`. Modifies `C:\ProgramData\Antigravity\*` and
         `C:\Users\<User>\.gemini\*`.
==============================================================================
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false, HelpMessage = "Target Windows developer username.")]
    [string]$User = "",

    [Parameter(Mandatory = $false, HelpMessage = "Override Enterprise Gateway HTTPS URL.")]
    [string]$GatewayUrl = "",

    [Parameter(Mandatory = $false, HelpMessage = "Override Enterprise Gateway Bearer API key.")]
    [string]$GatewayApiKey = "",

    [Parameter(Mandatory = $false, HelpMessage = "Override X-Goog-User-Project billing/quota project ID.")]
    [string]$ProjectId = "",

    [Parameter(Mandatory = $false, HelpMessage = "Directory containing modular configs subfolders.")]
    [string]$ConfigsDir = "",

    [Parameter(Mandatory = $false, HelpMessage = "Skip JetBrains and Zed ACP configuration files.")]
    [switch]$NoAcp,

    [Parameter(Mandatory = $false, HelpMessage = "Action to perform: Deploy, Unlock, Purge, or Status.")]
    [ValidateSet("Deploy", "Unlock", "Purge", "Status")]
    [string]$Action = "Deploy"
)

$ErrorActionPreference = "Stop"

# ==============================================================================
# BLOCK 1: LOGGING, PRIVILEGE CHECK & DOTENV LOADER
# ==============================================================================
<#
.SYNOPSIS
    Emits structured ISO-8601 UTC log lines with severity levels.
#>
function Write-SemanticLog {
    param(
        [Parameter(Mandatory = $true)][string]$Level,
        [Parameter(Mandatory = $true)][string]$Message
    )
    $Ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    Write-Host "[$Ts] [$Level] $Message"
}

<#
.SYNOPSIS
    Loads KEY="VALUE" pairs from settings.env and optional .env into a hashtable.
#>
function Import-EnvFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][hashtable]$Store
    )
    if (-not (Test-Path -LiteralPath $Path)) { return }
    foreach ($Line in (Get-Content -LiteralPath $Path)) {
        $Trimmed = $Line.Trim()
        if ([string]::IsNullOrWhiteSpace($Trimmed) -or $Trimmed.StartsWith("#")) { continue }
        if ($Trimmed -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            $Key = $Matches[1]
            $Val = $Matches[2].Trim()
            # Strip inline comments outside quotes and surrounding quotes
            if ($Val -match '^"([^"]*)"') { $Val = $Matches[1] }
            elseif ($Val -match "^'([^']*)'") { $Val = $Matches[1] }
            else { $Val = ($Val -split '\s+#')[0].Trim() }
            $Store[$Key] = $Val
        }
    }
}

<#
.SYNOPSIS
    Writes a string to disk encoded as standard UTF-8 WITHOUT a 3-byte BOM.
    Required because Windows PowerShell 5.1 'Set-Content -Encoding UTF8' prepends
    0xEF 0xBB 0xBF, which Go's encoding/json.Unmarshal rejects in agy.exe.
#>
function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $Utf8NoBom)
}

<#
.SYNOPSIS
    Verifies the current PowerShell process has Elevated Administrator rights.
#>
function Test-AdministratorRole {
    $Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $Principal = New-Object Security.Principal.WindowsPrincipal($Identity)
    return $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ==============================================================================
# BLOCK 2: CONFIGURATION MERGE & USER RESOLUTION
# ==============================================================================
$ScriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Definition }
$RootDir = Split-Path -Parent $ScriptDir
if ([string]::IsNullOrWhiteSpace($ConfigsDir)) {
    $ConfigsDir = Join-Path $RootDir "configs"
}
$Cfg = @{}
Import-EnvFile -Path (Join-Path $RootDir "settings.env") -Store $Cfg
Import-EnvFile -Path (Join-Path $RootDir ".env")         -Store $Cfg

$EffectiveUser          = if ($User)          { $User }          elseif ($env:AGY_DEV_USER)    { $env:AGY_DEV_USER }    else { $Cfg["AGY_DEV_USER"] }
$EffectiveGatewayUrl    = if ($GatewayUrl)    { $GatewayUrl }    elseif ($env:GATEWAY_URL)     { $env:GATEWAY_URL }     elseif ($Cfg["GATEWAY_URL"])     { $Cfg["GATEWAY_URL"] }     else { "https://REPLACE_WITH_GATEWAY_URL" }
$EffectiveGatewayApiKey = if ($GatewayApiKey) { $GatewayApiKey } elseif ($env:GATEWAY_API_KEY) { $env:GATEWAY_API_KEY } elseif ($Cfg["GATEWAY_API_KEY"]) { $Cfg["GATEWAY_API_KEY"] } else { "REPLACE_WITH_GATEWAY_API_KEY" }
$EffectiveProjectId     = if ($ProjectId)     { $ProjectId }     elseif ($env:BILLING_PROJECT_ID) { $env:BILLING_PROJECT_ID } elseif ($Cfg["BILLING_PROJECT_ID"]) { $Cfg["BILLING_PROJECT_ID"] } else { "REPLACE_WITH_PROJECT_ID" }
$EffectiveWireProtocol  = if ($Cfg["GATEWAY_WIRE_PROTOCOL"]) { $Cfg["GATEWAY_WIRE_PROTOCOL"] } else { "genai" }
$EffectiveCostCenter    = if ($Cfg["COST_CENTER"])           { $Cfg["COST_CENTER"] }           else { "CC-9941-SEC" }
$EffectiveCorporateBu   = if ($Cfg["CORPORATE_BU"])          { $Cfg["CORPORATE_BU"] }          else { "Enterprise-Security" }
$EffectiveSurface       = if ($Cfg["ENTERPRISE_SURFACE"])    { $Cfg["ENTERPRISE_SURFACE"] }    else { "MDM-Managed-Workstation" }
$DeployAcp              = (-not $NoAcp.IsPresent) -and ($Cfg["DEPLOY_ACP_CONFIGS"] -ne "false")
$AddWinUnsandboxedAllow = ($Cfg["WINDOWS_ADD_UNSANDBOXED_ALLOW"] -ne "false")

<#
.SYNOPSIS
    Dynamically resolves target Windows developer username from CLI, CIM console
    session, USERNAME env, or interactive prompt.
#>
function Resolve-TargetDeveloperUser {
    param([string]$InputUser)
    $Resolved = $InputUser
    if ([string]::IsNullOrWhiteSpace($Resolved)) {
        try {
            $ConsoleUser = (Get-CimInstance -ClassName Win32_ComputerSystem -ErrorAction SilentlyContinue).UserName
            if (-not [string]::IsNullOrWhiteSpace($ConsoleUser)) {
                $Resolved = ($ConsoleUser -split '\\')[-1]
                Write-SemanticLog -Level "INFO" -Message "Auto-detected active Windows console user: '$Resolved'"
            }
        } catch {}
    }
    if ([string]::IsNullOrWhiteSpace($Resolved) -and $env:USERNAME -and $env:USERNAME -notmatch '^(SYSTEM|Administrator)$') {
        $Resolved = $env:USERNAME
        Write-SemanticLog -Level "INFO" -Message "Auto-detected user from USERNAME env: '$Resolved'"
    }
    if ([string]::IsNullOrWhiteSpace($Resolved)) {
        if ([Environment]::UserInteractive) {
            $Resolved = Read-Host -Prompt "Enter target Windows developer username to configure"
        } else {
            Write-SemanticLog -Level "ERROR" -Message "No developer username specified. Pass -User <USERNAME> or set AGY_DEV_USER."
            exit 1
        }
    }
    if ([string]::IsNullOrWhiteSpace($Resolved)) {
        Write-SemanticLog -Level "ERROR" -Message "Developer username cannot be empty."
        exit 1
    }
    return $Resolved.Trim()
}

# ==============================================================================
# BLOCK 3: NTFS ACL UNLOCK, DEPLOY, PURGE & AUDIT FUNCTIONS
# ==============================================================================
<#
.SYNOPSIS
    Removes NTFS Deny ACEs and ReadOnly attributes from managed policy files.
#>
function Unlock-PolicyFiles {
    param(
        [string[]]$Files,
        [string]$DevUser
    )
    Write-SemanticLog -Level "INFO" -Message "Removing NTFS Deny ACLs and ReadOnly attributes for '$DevUser'..."
    foreach ($File in $Files) {
        if (Test-Path -LiteralPath $File) {
            & icacls.exe $File /remove:d $DevUser 2>$null | Out-Null
            & icacls.exe $File /remove:d "*S-1-5-32-545" 2>$null | Out-Null
            & icacls.exe $File /grant "${DevUser}:(M)" 2>$null | Out-Null
            attrib.exe -R $File 2>$null
        }
    }
    Write-SemanticLog -Level "INFO" -Message "All managed Windows policy files unlocked."
}

<#
.SYNOPSIS
    Unlocks and deletes all managed policy files on Windows (-Action Purge).
#>
function Remove-ManagedPolicyFiles {
    param(
        [string[]]$Files,
        [string]$DevUser
    )
    Unlock-PolicyFiles -Files $Files -DevUser $DevUser
    Write-SemanticLog -Level "WARN" -Message "Deleting managed Antigravity policy files for '$DevUser'..."
    foreach ($File in $Files) {
        if (Test-Path -LiteralPath $File) {
            Remove-Item -LiteralPath $File -Force
            Write-SemanticLog -Level "INFO" -Message "Removed: $File"
        }
    }
}

<#
.SYNOPSIS
    Displays file existence, ReadOnly attribute, size, and NTFS ACL entries.
#>
function Get-PolicyStatus {
    param([string[]]$Files)
    Write-SemanticLog -Level "INFO" -Message "Auditing Antigravity MDM policy files on Windows..."
    foreach ($File in $Files) {
        if (Test-Path -LiteralPath $File) {
            $Item = Get-Item -LiteralPath $File -Force
            Write-SemanticLog -Level "INFO" -Message "FOUND: $File (ReadOnly=$($Item.IsReadOnly), Bytes=$($Item.Length))"
            & icacls.exe $File
        } else {
            Write-SemanticLog -Level "WARN" -Message "MISSING: $File"
        }
    }
}

<#
.SYNOPSIS
    Renders gateway placeholders in JSON strings for Windows deployment.
#>
function Convert-GatewayPlaceholders {
    param([string]$Content)
    $CleanUrl = $EffectiveGatewayUrl.TrimEnd('/')
    $Out = $Content `
        -replace 'https://REPLACE_WITH_GATEWAY_URL', $CleanUrl `
        -replace 'REPLACE_WITH_GATEWAY_API_KEY', $EffectiveGatewayApiKey `
        -replace 'REPLACE_WITH_PROJECT_ID', $EffectiveProjectId `
        -replace '"wireProtocol":\s*"genai"', "`"wireProtocol`": `"$EffectiveWireProtocol`"" `
        -replace 'CC-9941-SEC', $EffectiveCostCenter `
        -replace 'Enterprise-Security', $EffectiveCorporateBu `
        -replace 'MDM-Managed-Workstation', $EffectiveSurface
    return $Out
}

<#
.SYNOPSIS
    Adds matching unsandboxed(...) allow grants and safe PowerShell raw-match
    command(regex:...) companions on Windows (where PowerShell forces
    RequiresExactMatch = true and native OS terminal sandboxing may be absent).
#>
function Add-WindowsUnsandboxedAllowGrants {
    param([string[]]$AllowList)
    $Updated = [System.Collections.Generic.List[string]]::new()
    foreach ($Rule in $AllowList) {
        if (-not $Updated.Contains($Rule)) { $Updated.Add($Rule) }
        if ($Rule -match '^command\((.+)\)$') {
            $Inner = $Matches[1]
            if ($AddWinUnsandboxedAllow) {
                $UnsandboxedRule = "unsandboxed($Inner)"
                if (-not $Updated.Contains($UnsandboxedRule)) {
                    $Updated.Add($UnsandboxedRule)
                }
            }
            if (($Inner -ne "*") -and (-not $Inner.StartsWith("regex:"))) {
                $EscapedCmd = ([regex]::Escape($Inner.Trim())) -replace '\\\s+', '\s+'
                $PsRegexTarget = 'regex:^(?i)' + $EscapedCmd + '(\s+[^;&|`$()\r\n>]*)?$'
                $PsCmdRule = "command($PsRegexTarget)"
                if (-not $Updated.Contains($PsCmdRule)) {
                    $Updated.Add($PsCmdRule)
                }
                if ($AddWinUnsandboxedAllow) {
                    $PsUnsandRule = "unsandboxed($PsRegexTarget)"
                    if (-not $Updated.Contains($PsUnsandRule)) {
                        $Updated.Add($PsUnsandRule)
                    }
                }
            }
        }
    }
    return $Updated.ToArray()
}

<#
.SYNOPSIS
    Installs all modular policy files and locks them with NTFS Deny ACLs.
#>
function Install-AndLockPolicies {
    param(
        [string[]]$Files,
        [string]$UserHome,
        [string]$DevUser,
        [string]$CfgRoot
    )
    $SrcAdmin   = Join-Path $CfgRoot "01-admin-settings\admin_settings.json"
    $SrcCli     = Join-Path $CfgRoot "02-cli-settings\settings.json"
    $SrcDesktop = Join-Path $CfgRoot "03-desktop-hub-config\config.json"
    $SrcBrowser = Join-Path $CfgRoot "04-browser-allowlist\browserAllowlist.txt"
    $SrcMcp     = Join-Path $CfgRoot "05-mcp-config\mcp_config.json"
    $SrcHooks   = Join-Path $CfgRoot "06-lifecycle-hooks\hooks.json"
    $SrcGuard   = Join-Path $CfgRoot "07-security-guard-scripts\agy_security_guard.ps1"
    $SrcAcp     = Join-Path $CfgRoot "08-acp-ide-configs\acp.json"
    $SrcAcpAuth = Join-Path $CfgRoot "08-acp-ide-configs\antigravity-acp-settings.json"

    $Required = @($SrcAdmin, $SrcCli, $SrcDesktop, $SrcBrowser, $SrcMcp, $SrcHooks, $SrcGuard)
    if ($DeployAcp) { $Required += @($SrcAcp, $SrcAcpAuth) }
    foreach ($Path in $Required) {
        if (-not (Test-Path -LiteralPath $Path)) {
            Write-SemanticLog -Level "ERROR" -Message "Required modular template missing: $Path"
            exit 1
        }
    }

    Unlock-PolicyFiles -Files $Files -DevUser $DevUser

    $TargetDirs = @(
        "C:\ProgramData\Antigravity",
        "C:\ProgramData\Antigravity\bin",
        "$UserHome\.gemini\antigravity-cli",
        "$UserHome\.gemini\config",
        "$UserHome\.gemini\antigravity"
    )
    if ($DeployAcp) {
        $TargetDirs += @(
            "$UserHome\.gemini\antigravity-acp",
            "$UserHome\.jetbrains",
            "$UserHome\AppData\Roaming\Zed"
        )
    }
    foreach ($Dir in $TargetDirs) {
        New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    }

    # Secure C:\ProgramData\Antigravity root folder ownership to Administrators & SYSTEM
    & icacls.exe "C:\ProgramData\Antigravity" /setowner "*S-1-5-32-544" | Out-Null
    & icacls.exe "C:\ProgramData\Antigravity" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-545:(OI)(CI)RX" | Out-Null

    # 1. admin_settings.json (remove Linux /etc/ssl/certs path if not overridden so Windows uses OS Cert Store)
    $AdminObj = (Convert-GatewayPlaceholders -Content (Get-Content -LiteralPath $SrcAdmin -Raw)) | ConvertFrom-Json
    if ($AdminObj.caCertPath -eq "/etc/ssl/certs/ca-certificates.crt") {
        $AdminObj.PSObject.Properties.Remove("caCertPath")
    }
    Write-Utf8NoBom -Path "C:\ProgramData\Antigravity\admin_settings.json" -Content ($AdminObj | ConvertTo-Json -Depth 10)

    # 2. Static & Guard files
    Copy-Item -LiteralPath $SrcGuard   -Destination "C:\ProgramData\Antigravity\bin\agy_security_guard.ps1" -Force
    Copy-Item -LiteralPath $SrcBrowser -Destination "$UserHome\.gemini\antigravity\browserAllowlist.txt" -Force
    Copy-Item -LiteralPath $SrcMcp     -Destination "$UserHome\.gemini\config\mcp_config.json" -Force

    # 3. CLI settings.json & Desktop config.json (substitute user paths + optional Windows unsandboxed allow grants)
    $ForwardHome = $UserHome -replace '\\', '/'
    $CliRaw = ((Get-Content -LiteralPath $SrcCli -Raw) -replace '/home/__DEV_USER__', $ForwardHome) -replace '__DEV_USER__', $DevUser
    $CliObj = $CliRaw | ConvertFrom-Json
    if ($CliObj.permissions -and $CliObj.permissions.allow) {
        $CliObj.permissions.allow = Add-WindowsUnsandboxedAllowGrants -AllowList $CliObj.permissions.allow
    }
    Write-Utf8NoBom -Path "$UserHome\.gemini\antigravity-cli\settings.json" -Content ($CliObj | ConvertTo-Json -Depth 10)

    $CfgRaw = ((Get-Content -LiteralPath $SrcDesktop -Raw) -replace '/home/__DEV_USER__', $ForwardHome) -replace '__DEV_USER__', $DevUser
    $CfgObj = $CfgRaw | ConvertFrom-Json
    if ($CfgObj.userSettings -and $CfgObj.userSettings.globalPermissionGrants -and $CfgObj.userSettings.globalPermissionGrants.allow) {
        $CfgObj.userSettings.globalPermissionGrants.allow = Add-WindowsUnsandboxedAllowGrants -AllowList $CfgObj.userSettings.globalPermissionGrants.allow
    }
    $CfgJson = $CfgObj | ConvertTo-Json -Depth 10
    Write-Utf8NoBom -Path "$UserHome\.gemini\config\config.json" -Content $CfgJson
    Write-Utf8NoBom -Path "$UserHome\.gemini\config.json"        -Content $CfgJson

    # 4. hooks.json (unquoted -File path for reliable execution across Windows CLI & Desktop)
    $HooksRaw = Get-Content -LiteralPath $SrcHooks -Raw
    # Forward slashes: the JetBrains/Zed ACP server splits hook commands POSIX-style and drops backslashes
    # ("External hook ... failed to execute" -> every tool call denied). PowerShell and the CLI accept '/'.
    $HooksWin = $HooksRaw -replace '/usr/local/bin/agy_security_guard\.sh', 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:/ProgramData/Antigravity/bin/agy_security_guard.ps1'
    Write-Utf8NoBom -Path "$UserHome\.gemini\config\hooks.json" -Content $HooksWin

    # 5. Optional JetBrains & Zed ACP configs
    if ($DeployAcp) {
        Copy-Item -LiteralPath $SrcAcpAuth -Destination "$UserHome\.gemini\antigravity-acp\settings.json" -Force
        $AcpRendered = (Convert-GatewayPlaceholders -Content (Get-Content -LiteralPath $SrcAcp -Raw)) `
            -replace '/usr/local/bin/agy', 'C:\\Program Files\\Antigravity\\bin\\agy.exe'
        $AcpObj = $AcpRendered | ConvertFrom-Json
        if ($AcpObj.agent_servers.Antigravity.env.AGY_LLM_GATEWAY_CA_CERT -eq "/etc/ssl/certs/ca-certificates.crt") {
            $AcpObj.agent_servers.Antigravity.env.PSObject.Properties.Remove("AGY_LLM_GATEWAY_CA_CERT")
        }
        $AcpJson = $AcpObj | ConvertTo-Json -Depth 10
        Write-Utf8NoBom -Path "$UserHome\.jetbrains\acp.json"               -Content $AcpJson
        Write-Utf8NoBom -Path "$UserHome\AppData\Roaming\Zed\settings.json" -Content $AcpJson
    }

    # 6. Lock all managed files with NTFS ACLs + ReadOnly attribute
    # Note: Use specific NTFS write/delete rights (WD,AD,WEA,WA,DE,WDAC,WO) rather than
    # generic (W), because generic (W) includes SYNCHRONIZE and would block Win32/Go
    # synchronous file reads (os.Open / Get-Content) by the non-admin developer user.
    Write-SemanticLog -Level "INFO" -Message "Applying Administrator ownership and NTFS Deny Write/Delete ACLs..."
    foreach ($File in $Files) {
        & takeown.exe /F $File /A | Out-Null
        # Set ReadOnly (+R) BEFORE applying Deny WriteAttributes (WA) ACEs
        attrib.exe +R $File
        $GrantPerm = if ($File -like "*.ps1") { "${DevUser}:(RX)" } else { "${DevUser}:(R)" }
        $UsersSidPerm = if ($File -like "*.ps1") { "*S-1-5-32-545:(RX)" } else { "*S-1-5-32-545:(R)" }
        if ($File -like "C:\ProgramData\*") {
            & icacls.exe $File /inheritance:r `
                /grant:r "SYSTEM:(F)" `
                /grant:r "Administrators:(F)" `
                /grant:r $UsersSidPerm `
                /grant:r $GrantPerm `
                /deny "${DevUser}:(WD,AD,WEA,WA,DE,WDAC,WO)" `
                /deny "*S-1-5-32-545:(WD,AD,WEA,WA,DE,WDAC,WO)" | Out-Null
        } else {
            & icacls.exe $File /inheritance:r `
                /grant:r "SYSTEM:(F)" `
                /grant:r "Administrators:(F)" `
                /grant:r $GrantPerm `
                /deny "${DevUser}:(WD,AD,WEA,WA,DE,WDAC,WO)" | Out-Null
        }
    }

    Write-SemanticLog -Level "INFO" -Message "Windows MDM policy deployment and NTFS locking complete for '$DevUser'."
    Get-PolicyStatus -Files $Files
}

# ==============================================================================
# BLOCK 4: MAIN ENTRYPOINT
# ==============================================================================
if (-not (Test-AdministratorRole)) {
    Write-SemanticLog -Level "ERROR" -Message "Run this script from an Elevated Administrator PowerShell session."
    exit 1
}

$ResolvedUser = Resolve-TargetDeveloperUser -InputUser $EffectiveUser
$UserHome = "C:\Users\$ResolvedUser"
if (-not (Test-Path -LiteralPath $UserHome)) {
    Write-SemanticLog -Level "ERROR" -Message "Windows profile directory '$UserHome' does not exist."
    exit 1
}

$ManagedFiles = @(
    "C:\ProgramData\Antigravity\admin_settings.json",
    "C:\ProgramData\Antigravity\bin\agy_security_guard.ps1",
    "$UserHome\.gemini\antigravity-cli\settings.json",
    "$UserHome\.gemini\config\config.json",
    "$UserHome\.gemini\config.json",
    "$UserHome\.gemini\antigravity\browserAllowlist.txt",
    "$UserHome\.gemini\config\mcp_config.json",
    "$UserHome\.gemini\config\hooks.json"
)
if ($DeployAcp) {
    $ManagedFiles += @(
        "$UserHome\.gemini\antigravity-acp\settings.json",
        "$UserHome\.jetbrains\acp.json",
        "$UserHome\AppData\Roaming\Zed\settings.json"
    )
}

switch ($Action) {
    "Deploy" { Install-AndLockPolicies  -Files $ManagedFiles -UserHome $UserHome -DevUser $ResolvedUser -CfgRoot $ConfigsDir }
    "Unlock" { Unlock-PolicyFiles       -Files $ManagedFiles -DevUser $ResolvedUser }
    "Purge"  { Remove-ManagedPolicyFiles -Files $ManagedFiles -DevUser $ResolvedUser }
    "Status" { Get-PolicyStatus         -Files $ManagedFiles }
}
