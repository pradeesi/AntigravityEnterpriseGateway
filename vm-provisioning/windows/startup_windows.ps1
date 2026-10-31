# ==============================================================================
# FILE HEADER: GCE Startup Script — Vanilla Antigravity Windows Server 2022 VM
# ==============================================================================
# Author: Pradeep Singh
# License: Apache-2.0
#
# Purpose:
#   Automated first-boot Compute Engine Windows PowerShell startup script
#   (`windows-startup-script-ps1`) that configures a Windows Server 2022
#   Datacenter Desktop Experience VM with a 100% vanilla Google Antigravity
#   workstation: Antigravity CLI (`agy.exe`), Antigravity Desktop App
#   (`Antigravity-x64.exe`), and Microsoft Visual Studio Code + official
#   `Google.google-antigravity` extension across all user profiles.
#
# Architecture / Context:
#   Injected via `--metadata-from-file=windows-startup-script-ps1=windows/startup_windows.ps1`
#   by `windows/provision_windows_vm.sh` (and top-level `install.sh`). Organized
#   into 6 explicit functional blocks with an idempotency completion marker
#   (`C:\AntigravitySetup\antigravity-install.done`).
#
# Dependencies / Side Effects:
#   - Executes as `NT AUTHORITY\SYSTEM` during GCE Sysprep / Startup and logs to
#     `C:\AntigravitySetup\antigravity-install.log` (visible via serial port 1).
#   - Updates Machine `Path`, Windows Defender Firewall (TCP 4400), `HKLM\...\Run`,
#     `C:\Program Files\Antigravity\bin\agy.exe`, `C:\Program Files\Microsoft VS Code`,
#     and `C:\Users\Default\.vscode\extensions`.
# ==============================================================================

$ErrorActionPreference = "Continue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"

$InstallRoot   = "C:\AntigravitySetup"
$LogFile       = "C:\AntigravitySetup\antigravity-install.log"
$DoneMarker    = "C:\AntigravitySetup\antigravity-install.done"
$AgySystemBin  = "C:\Program Files\Antigravity\bin"
$SharedExtDir  = "C:\ProgramData\Antigravity\vscode-extensions"

if (-not (Test-Path $InstallRoot)) {
    New-Item -ItemType Directory -Path $InstallRoot -Force | Out-Null
}

# ==============================================================================
# BLOCK 1: STRUCTURED LOGGING & IDEMPOTENCY GUARD
# ==============================================================================

<#
.SYNOPSIS
    Writes an ISO-8601 UTC timestamped log entry to both stdout (GCE serial port)
    and C:\AntigravitySetup\antigravity-install.log.
.PARAMETER Level
    Semantic log severity level (INFO, WARN, ERROR).
.PARAMETER Message
    Human-readable status message.
.OUTPUTS
    None.
#>
function Write-InstallLog {
    param(
        [Parameter(Mandatory = $false)]
        [ValidateSet("INFO", "WARN", "ERROR")]
        [string]$Level = "INFO",

        [Parameter(Mandatory = $true)]
        [string]$Message
    )
    $Stamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $Line  = "[$Stamp] [$Level] $Message"
    Write-Output $Line
    Add-Content -Path $LogFile -Value $Line -Encoding UTF8
}

if (Test-Path $DoneMarker) {
    Write-InstallLog -Level "INFO" -Message "=== Vanilla Antigravity Windows installation already completed ($DoneMarker present). ==="
    exit 0
}


# ==============================================================================
# BLOCK 2: WINDOWS DIRECTORIES, MACHINE PATH & FIREWALL RULE (TCP 4400)
# ==============================================================================

<#
.SYNOPSIS
    Creates shared installation directories, appends CLI/VS Code paths to the
    Machine PATH, and opens inbound TCP port 4400 in Windows Defender Firewall.
.OUTPUTS
    None.
#>
function Initialize-WindowsEnvironment {
    Write-InstallLog -Level "INFO" -Message "=== [1/5] Preparing Windows directories, Machine PATH & firewall rules ==="
    New-Item -ItemType Directory -Path $AgySystemBin -Force | Out-Null
    New-Item -ItemType Directory -Path $SharedExtDir -Force | Out-Null

    $MachinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    foreach ($PathEntry in @($AgySystemBin, "C:\Program Files\Microsoft VS Code\bin")) {
        if ($MachinePath -notlike "*$PathEntry*") {
            $MachinePath = "$MachinePath;$PathEntry"
        }
    }
    [Environment]::SetEnvironmentVariable("Path", $MachinePath, "Machine")
    $env:Path = "$env:Path;$AgySystemBin;C:\Program Files\Microsoft VS Code\bin"

    New-NetFirewallRule `
        -DisplayName "Antigravity Web UI (4400)" `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort 4400 `
        -ErrorAction SilentlyContinue | Out-Null
}


# ==============================================================================
# BLOCK 3: VANILLA ANTIGRAVITY CLI (`agy.exe`) WITH SHA512 VERIFICATION
# ==============================================================================

<#
.SYNOPSIS
    Downloads the latest Windows amd64 Antigravity CLI binary, verifies its
    SHA512 cryptographic digest against the release manifest, and installs it.
.OUTPUTS
    None. Logs ERROR if manifest fetch or SHA512 verification fails.
#>
function Install-AntigravityCli {
    Write-InstallLog -Level "INFO" -Message "=== [2/5] Installing Vanilla Antigravity CLI (agy.exe) ==="
    try {
        $CliManifestUrl = "https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/windows_amd64.json"
        $CliManifest    = Invoke-RestMethod -Uri $CliManifestUrl -UseBasicParsing
        $CliVersion     = $CliManifest.version
        $CliUrl         = $CliManifest.url
        $CliSha512      = $CliManifest.sha512.ToLower()

        Write-InstallLog -Level "INFO" -Message "Downloading Antigravity CLI v$CliVersion from $CliUrl..."
        $AgyExePath = Join-Path $AgySystemBin "agy.exe"
        curl.exe -fsSL -L "$CliUrl" -o "$AgyExePath"

        # Enforce cryptographic integrity before making agy.exe available system-wide.
        $ActualHash = (Get-FileHash -Path $AgyExePath -Algorithm SHA512).Hash.ToLower()
        if ($ActualHash -ne $CliSha512) {
            throw "SHA512 mismatch for agy.exe (expected $CliSha512, got $ActualHash)"
        }
        Unblock-File -Path $AgyExePath -ErrorAction SilentlyContinue
        $VerOut = & $AgyExePath --version 2>&1
        Write-InstallLog -Level "INFO" -Message "Antigravity CLI installed at $AgyExePath (Version: $VerOut)"
    } catch {
        Write-InstallLog -Level "ERROR" -Message "Failed installing Antigravity CLI: $_"
    }
}


# ==============================================================================
# BLOCK 4: VANILLA ANTIGRAVITY DESKTOP APP & PER-USER RDP LOGON HOOK
# ==============================================================================

<#
.SYNOPSIS
    Downloads Antigravity-x64.exe from the Hub updater manifest, performs silent
    staging, places a Public Desktop copy, and registers an HKLM Run hook so any
    new RDP user gets the per-user Electron app installed on first logon.
.OUTPUTS
    None.
#>
function Install-AntigravityDesktopApp {
    Write-InstallLog -Level "INFO" -Message "=== [3/5] Downloading & Installing Vanilla Antigravity Desktop App (Windows x64) ==="
    try {
        $HubReleases = Invoke-RestMethod -Uri "https://antigravity-hub-auto-updater-974169037036.us-central1.run.app/releases" -UseBasicParsing
        $HubLatest   = $HubReleases[0]
        $HubVersion  = $HubLatest.version
        $HubExecId   = $HubLatest.execution_id
        $HubUrl      = "https://storage.googleapis.com/antigravity-public/antigravity-hub/$HubVersion-$HubExecId/windows-x64/Antigravity-x64.exe"
        $HubSetupExe = Join-Path $InstallRoot "Antigravity-x64.exe"

        Write-InstallLog -Level "INFO" -Message "Downloading Antigravity Desktop App v$HubVersion from $HubUrl..."
        curl.exe -fsSL -L "$HubUrl" -o "$HubSetupExe"
        Unblock-File -Path $HubSetupExe -ErrorAction SilentlyContinue

        Write-InstallLog -Level "INFO" -Message "Running Antigravity Desktop App silent installer..."
        Start-Process -FilePath $HubSetupExe -ArgumentList "/S" -Wait -NoNewWindow -ErrorAction SilentlyContinue

        $PublicDesktop = "C:\Users\Public\Desktop"
        Copy-Item -Path $HubSetupExe -Destination (Join-Path $PublicDesktop "Antigravity-Installer.exe") -Force -ErrorAction SilentlyContinue

        # Because Electron user-scope installers target %LOCALAPPDATA% (which belongs to SYSTEM
        # during GCE boot), register HKLM\...\Run so every RDP user receives silent setup at first logon.
        $RunKeyPath = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
        Set-ItemProperty `
            -Path $RunKeyPath `
            -Name "AntigravityDesktopUserSetup" `
            -Value "cmd.exe /c if not exist `"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe`" start /wait `"`" `"$HubSetupExe`" /S" `
            -ErrorAction SilentlyContinue

        Write-InstallLog -Level "INFO" -Message "Antigravity Desktop App v$HubVersion staged at $HubSetupExe"
    } catch {
        Write-InstallLog -Level "ERROR" -Message "Failed installing Antigravity Desktop App: $_"
    }
}


# ==============================================================================
# BLOCK 5: MICROSOFT VISUAL STUDIO CODE & GOOGLE ANTIGRAVITY EXTENSION (`VSIX`)
# ==============================================================================

<#
.SYNOPSIS
    Installs system-wide Microsoft VS Code x64 silently and seeds the official
    Google.google-antigravity VSIX into ProgramData, C:\Users\Default, and all
    existing local Windows user profiles.
.OUTPUTS
    None.
#>
function Install-VsCodeAndAntigravityExtension {
    Write-InstallLog -Level "INFO" -Message "=== [4/5] Installing Microsoft Visual Studio Code (System-Wide x64) ==="
    try {
        $VsCodeSetupExe = Join-Path $InstallRoot "VSCodeSetup-x64.exe"
        $VsCodeUrl      = "https://update.code.visualstudio.com/latest/win32-x64/stable"
        Write-InstallLog -Level "INFO" -Message "Downloading VS Code System Installer from $VsCodeUrl..."
        curl.exe -fsSL -L "$VsCodeUrl" -o "$VsCodeSetupExe"
        Unblock-File -Path $VsCodeSetupExe -ErrorAction SilentlyContinue

        Write-InstallLog -Level "INFO" -Message "Running VS Code silent system installation..."
        Start-Process `
            -FilePath $VsCodeSetupExe `
            -ArgumentList "/VERYSILENT /NORESTART /MERGETASKS=!runcode,desktopicon,addcontextmenufiles,addcontextmenufolders,associatewithfiles,addtopath" `
            -Wait `
            -NoNewWindow

        $CodeCmd = "C:\Program Files\Microsoft VS Code\bin\code.cmd"
        if (Test-Path $CodeCmd) {
            $VsVer = & $CodeCmd --version 2>&1
            Write-InstallLog -Level "INFO" -Message "VS Code installed successfully: $($VsVer -join ' ')"
        } else {
            Write-InstallLog -Level "WARN" -Message "$CodeCmd not found immediately after installer exited."
        }
    } catch {
        Write-InstallLog -Level "ERROR" -Message "Failed installing Visual Studio Code: $_"
    }

    Write-InstallLog -Level "INFO" -Message "=== [5/5] Installing Official Google Antigravity VS Code Plugin (Google.google-antigravity) ==="
    try {
        $VsixPath    = Join-Path $InstallRoot "google-antigravity.vsix"
        $OpenVsxMeta = Invoke-RestMethod -Uri "https://open-vsx.org/api/Google/google-antigravity" -UseBasicParsing -ErrorAction SilentlyContinue
        $VsixUrl     = $OpenVsxMeta.files.download
        if ([string]::IsNullOrWhiteSpace($VsixUrl)) {
            $VsixUrl = "https://marketplace.visualstudio.com/_apis/public/gallery/publishers/Google/vsextensions/google-antigravity/latest/vspackage"
        }

        Write-InstallLog -Level "INFO" -Message "Downloading Google Antigravity VSIX from $VsixUrl..."
        curl.exe -fsSL -L "$VsixUrl" -o "$VsixPath"

        $CodeCmd = "C:\Program Files\Microsoft VS Code\bin\code.cmd"
        if (Test-Path $CodeCmd) {
            & $CodeCmd --install-extension "$VsixPath" --extensions-dir "$SharedExtDir" --user-data-dir "$InstallRoot\vscode-temp-data" --force 2>&1 |
                Out-String |
                ForEach-Object { Write-InstallLog -Level "INFO" -Message $_.Trim() }

            # Seed C:\Users\Default\.vscode\extensions so newly created RDP accounts inherit the extension.
            $DefaultUserExt = "C:\Users\Default\.vscode\extensions"
            New-Item -ItemType Directory -Path $DefaultUserExt -Force | Out-Null
            Copy-Item -Path "$SharedExtDir\*" -Destination $DefaultUserExt -Recurse -Force -ErrorAction SilentlyContinue

            # Seed all pre-existing user profiles in C:\Users\* along with AppData\Local\agy\bin\agy.exe.
            Get-ChildItem -Path "C:\Users" -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                if ($_.Name -notin @("Public", "Default", "Default User", "All Users")) {
                    $UserExt = Join-Path $_.FullName ".vscode\extensions"
                    New-Item -ItemType Directory -Path $UserExt -Force -ErrorAction SilentlyContinue | Out-Null
                    Copy-Item -Path "$SharedExtDir\*" -Destination $UserExt -Recurse -Force -ErrorAction SilentlyContinue

                    $UserLocalBin = Join-Path $_.FullName "AppData\Local\agy\bin"
                    New-Item -ItemType Directory -Path $UserLocalBin -Force -ErrorAction SilentlyContinue | Out-Null
                    Copy-Item -Path "C:\Program Files\Antigravity\bin\agy.exe" -Destination (Join-Path $UserLocalBin "agy.exe") -Force -ErrorAction SilentlyContinue
                }
            }

            $ExtList = & $CodeCmd --extensions-dir "$SharedExtDir" --user-data-dir "$InstallRoot\vscode-temp-data" --list-extensions --show-versions 2>&1
            Write-InstallLog -Level "INFO" -Message "Installed VS Code Extensions: $($ExtList -join ', ')"
            Remove-Item -Path "$InstallRoot\vscode-temp-data" -Recurse -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Write-InstallLog -Level "ERROR" -Message "Failed installing Google Antigravity VS Code Plugin: $_"
    }
}


# ==============================================================================
# BLOCK 6: STARTUP ORCHESTRATION & COMPLETION MARKER
# ==============================================================================
Initialize-WindowsEnvironment
Install-AntigravityCli
Install-AntigravityDesktopApp
Install-VsCodeAndAntigravityExtension

New-Item -ItemType File -Path $DoneMarker -Force | Out-Null
Write-InstallLog -Level "INFO" -Message "=== [COMPLETE] Vanilla Antigravity Windows VM Setup Finished Successfully! ==="
