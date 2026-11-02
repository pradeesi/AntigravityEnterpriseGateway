# ==============================================================================
# FILE HEADER: startup_windows_test.ps1 — Windows Server 2022 Antigravity verification VM
# ==============================================================================
# Purpose:
#   First-boot Compute Engine startup script that prepares a Windows Server 2022
#   VM as an Antigravity test bench: OpenSSH (for IAP-tunneled automation), the
#   latest public Antigravity CLI (agy.exe), the desktop App installer, VS Code +
#   the Antigravity VSIX, the ACP server used by JetBrains/Zed, Python for the
#   harness, and Google Chrome.
#
# Architecture / Context:
#   Part of agy-config/verification/. Injected with
#   `--metadata-from-file=windows-startup-script-ps1=infra/startup_windows_test.ps1`
#   together with `enable-windows-ssh=TRUE`. The App and the VSIX are staged in
#   C:\ProgramData\agy-verify so the harness can install them per test user,
#   keeping every test round on a clean profile.
#
# Dependencies / Side Effects:
#   - Runs as SYSTEM on every boot; exits early once the done marker exists.
#   - Logs to C:\ProgramData\agy-verify\install.log; writes versions.json there.
#   - Installs agy.exe to C:\Program Files\Antigravity\bin (added to machine PATH),
#     VS Code (system), Python 3.12 (all users), Chrome (MSI), and sshd.
# ==============================================================================

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$VerifyRoot   = "C:\ProgramData\agy-verify"
$LogFile      = Join-Path $VerifyRoot "install.log"
$DoneMarker   = Join-Path $VerifyRoot "install.done"
$VersionsFile = Join-Path $VerifyRoot "versions.json"
$CliManifest  = "https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/windows_amd64.json"
$HubReleases  = "https://antigravity-hub-auto-updater-974169037036.us-central1.run.app/releases"
$OpenVsxApi   = "https://open-vsx.org/api/Google/google-antigravity"
$AcpRegistry  = "https://cdn.agentclientprotocol.com/registry/v1/latest/registry.json"
$PythonUrl    = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"

New-Item -ItemType Directory -Force -Path $VerifyRoot | Out-Null
if (Test-Path $DoneMarker) { exit 0 }

<#
.SYNOPSIS
    Appends a timestamped, level-tagged line to the install log.
.PARAMETER Level
    INFO, WARN, or ERROR.
.PARAMETER Message
    Text to log.
.OUTPUTS
    None.
#>
function Write-Log {
    param([string]$Level, [string]$Message)
    $line = "{0} {1} {2}" -f (Get-Date).ToUniversalTime().ToString("s"), $Level, $Message
    Add-Content -Path $LogFile -Value $line
}

<#
.SYNOPSIS
    Downloads a URL to a local path, retrying transient failures.
.PARAMETER Url
    Source URL.
.PARAMETER Path
    Destination file path.
.OUTPUTS
    [bool] $true when the file was downloaded.
#>
function Get-File {
    param([string]$Url, [string]$Path)
    for ($i = 1; $i -le 3; $i++) {
        try {
            Invoke-WebRequest -Uri $Url -OutFile $Path -UseBasicParsing -ErrorAction Stop
            return $true
        } catch {
            Write-Log "WARN" "download attempt $i failed for ${Url}: $($_.Exception.Message)"
            Start-Sleep -Seconds (5 * $i)
        }
    }
    return $false
}

<#
.SYNOPSIS
    Enables OpenSSH Server with PowerShell as the default shell so the harness can
    run commands through `gcloud compute ssh --tunnel-through-iap`.
.OUTPUTS
    None. Logs WARN when a step fails.
#>
function Enable-Ssh {
    Write-Log "INFO" "[1/7] Enabling OpenSSH"
    try { & googet -noconfirm=true install google-compute-engine-ssh 2>&1 | Out-Null } catch { Write-Log "WARN" "googet ssh package: $($_.Exception.Message)" }
    if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
        try { Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null } catch { Write-Log "WARN" "OpenSSH capability: $($_.Exception.Message)" }
    }
    New-Item -Path "HKLM:\SOFTWARE\OpenSSH" -Force | Out-Null
    New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell `
        -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force | Out-Null
    Set-Service -Name sshd -StartupType Automatic -ErrorAction SilentlyContinue
    Start-Service sshd -ErrorAction SilentlyContinue
}

<#
.SYNOPSIS
    Installs the latest public agy.exe after verifying its SHA-512 digest.
.OUTPUTS
    [string] The CLI version, or "failed".
#>
function Install-Cli {
    Write-Log "INFO" "[2/7] Installing Antigravity CLI"
    try {
        $m = Invoke-RestMethod -Uri $CliManifest -UseBasicParsing
        $tmp = Join-Path $env:TEMP "agy.exe"
        if (-not (Get-File $m.url $tmp)) { return "failed" }
        $actual = (Get-FileHash -Path $tmp -Algorithm SHA512).Hash.ToLower()
        # Never stage a binary whose digest differs from the release manifest.
        if ($actual -ne $m.sha512.ToLower()) { Write-Log "ERROR" "agy.exe SHA512 mismatch"; return "failed" }
        $bin = "C:\Program Files\Antigravity\bin"
        New-Item -ItemType Directory -Force -Path $bin | Out-Null
        Copy-Item $tmp (Join-Path $bin "agy.exe") -Force
        $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
        if ($machinePath -notlike "*$bin*") {
            [Environment]::SetEnvironmentVariable("Path", "$machinePath;$bin", "Machine")
        }
        return $m.version
    } catch { Write-Log "ERROR" "CLI: $($_.Exception.Message)"; return "failed" }
}

<#
.SYNOPSIS
    Stages the latest desktop App installer, the VS Code system install, and the VSIX.
.OUTPUTS
    [hashtable] app and vsix versions.
#>
function Install-AppAndVsCode {
    Write-Log "INFO" "[3/7] Staging App installer, VS Code, and VSIX"
    $result = @{ app = "failed"; vsix = "failed" }
    $inst = Join-Path $VerifyRoot "installers"
    New-Item -ItemType Directory -Force -Path $inst | Out-Null
    try {
        $rel = (Invoke-RestMethod -Uri $HubReleases -UseBasicParsing)[0]
        $url = "https://storage.googleapis.com/antigravity-public/antigravity-hub/$($rel.version)-$($rel.execution_id)/windows-x64/Antigravity-x64.exe"
        if (Get-File $url (Join-Path $inst "Antigravity-x64.exe")) { $result.app = $rel.version }
    } catch { Write-Log "ERROR" "App: $($_.Exception.Message)" }
    try {
        $codeSetup = Join-Path $inst "VSCodeSetup-x64.exe"
        if (Get-File "https://update.code.visualstudio.com/latest/win32-x64/stable" $codeSetup) {
            Start-Process -FilePath $codeSetup -ArgumentList "/VERYSILENT", "/NORESTART", "/MERGETASKS=!runcode,addtopath" -Wait
        }
        $meta = Invoke-RestMethod -Uri $OpenVsxApi -UseBasicParsing
        New-Item -ItemType Directory -Force -Path (Join-Path $VerifyRoot "vsix") | Out-Null
        if (Get-File $meta.files.download (Join-Path $VerifyRoot "vsix\google-antigravity.vsix")) { $result.vsix = $meta.version }
    } catch { Write-Log "ERROR" "VS Code/VSIX: $($_.Exception.Message)" }
    return $result
}

<#
.SYNOPSIS
    Installs the ACP server (JetBrains/Zed backend) from the ACP registry after a
    SHA-256 check.
.OUTPUTS
    [string] The ACP server version, or "failed".
#>
function Install-AcpServer {
    Write-Log "INFO" "[4/7] Installing ACP server"
    try {
        $entry = (Invoke-RestMethod -Uri $AcpRegistry -UseBasicParsing).agents | Where-Object { $_.id -eq "antigravity-acp" }
        $bin = $entry.distribution.binary."windows-x86_64"
        $zip = Join-Path $env:TEMP "acp.zip"
        if (-not (Get-File $bin.archive $zip)) { return "failed" }
        if ((Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower() -ne $bin.sha256.ToLower()) {
            Write-Log "ERROR" "ACP SHA256 mismatch"; return "failed"
        }
        $dest = Join-Path $VerifyRoot "acp"
        if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
        Expand-Archive -Path $zip -DestinationPath $dest -Force
        return $entry.version
    } catch { Write-Log "ERROR" "ACP: $($_.Exception.Message)"; return "failed" }
}

<#
.SYNOPSIS
    Installs Python 3.12 for all users plus the harness packages.
.OUTPUTS
    None.
#>
function Install-Python {
    Write-Log "INFO" "[5/7] Installing Python and harness packages"
    $py = Join-Path $env:TEMP "python-installer.exe"
    if (Get-File $PythonUrl $py) {
        Start-Process -FilePath $py -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0" -Wait
        & "C:\Program Files\Python312\python.exe" -m pip install --quiet websocket-client requests pyyaml 2>&1 | Out-Null
    }
}

<#
.SYNOPSIS
    Installs Google Chrome Enterprise (web UI tests).
.OUTPUTS
    None.
#>
function Install-Chrome {
    Write-Log "INFO" "[6/7] Installing Chrome"
    $msi = Join-Path $env:TEMP "chrome.msi"
    if (Get-File "https://dl.google.com/chrome/install/GoogleChromeStandaloneEnterprise64.msi" $msi) {
        Start-Process msiexec.exe -ArgumentList "/i", $msi, "/qn", "/norestart" -Wait
    }
}

Enable-Ssh
$cli = Install-Cli
$appvs = Install-AppAndVsCode
$acp = Install-AcpServer
Install-Python
Install-Chrome

Write-Log "INFO" "[7/7] Writing versions file"
@{
    cli = $cli; desktop_app = $appvs.app; vscode_extension = $appvs.vsix; acp_server = $acp
    os = (Get-CimInstance Win32_OperatingSystem).Caption
} | ConvertTo-Json | Set-Content -Path $VersionsFile

if ($cli -ne "failed" -and $appvs.app -ne "failed" -and $acp -ne "failed") {
    New-Item -ItemType File -Force -Path $DoneMarker | Out-Null
    Write-Log "INFO" "Verification bench ready."
} else {
    Write-Log "ERROR" "Mandatory component failed; the next boot retries."
}
