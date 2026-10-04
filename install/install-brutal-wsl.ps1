param([switch]$CheckOnly, [switch]$PrepareOnly, [switch]$UpdateImage, [switch]$RollbackImage,
      [switch]$BackupProfiles, [string]$RestoreProfilesPath = '')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskDistribution = 'Ubuntu-24.04'
$taskDashboardWatcher = $null
. (Join-Path $PSScriptRoot 'user-launcher.ps1')

function Invoke-BrutalWslProbe([string[]]$Arguments) {
    # Windows PowerShell 5.1 can promote native stderr to a terminating error
    # under the script's Stop policy. A missing/outdated WSL is a normal probe
    # result; installation below must get a chance to repair it.
    $ErrorActionPreference = 'Continue'
    $taskOutput = (& wsl.exe @Arguments 2>$null | Out-String).Trim()
    return [pscustomobject]@{ ExitCode=$LASTEXITCODE; Output=$taskOutput }
}

function Test-BrutalWslDistribution {
    $taskProbe = Invoke-BrutalWslProbe @('-d',$taskDistribution,'-u','root','--','/bin/true')
    return ($taskProbe.ExitCode -eq 0)
}

function Install-BrutalWslDistribution {
    Write-Host 'Installing official Ubuntu 24.04 inside WSL. It runs in the terminal; no Docker Desktop application is installed.'
    Write-Host 'Windows may request administrator approval or a restart to enable WSL 2.'
    $taskProcess = Start-Process -FilePath 'wsl.exe' -Verb RunAs -Wait -PassThru -ArgumentList @('--install','-d',$taskDistribution,'--web-download','--no-launch')
    if ($taskProcess.ExitCode -ne 0) {
        throw "Ubuntu WSL installation exited with status $($taskProcess.ExitCode). Restart Windows if requested, then relaunch Brutal OP25."
    }
    if (-not (Test-BrutalWslDistribution)) {
        throw 'Ubuntu WSL was installed but is not ready. Restart Windows, then relaunch Brutal OP25.'
    }
}

function Assert-BrutalWslUsbSupport {
    $taskProbe = Invoke-BrutalWslProbe @('-d',$taskDistribution,'-u','root','--','uname','-r')
    $taskKernel = $taskProbe.Output
    if ($taskProbe.ExitCode -ne 0 -or $taskKernel -notmatch 'WSL2') {
        throw 'Ubuntu must run as WSL 2 for USB forwarding. Run wsl --set-version Ubuntu-24.04 2 in Windows, then relaunch.'
    }
    if ($taskKernel -notmatch '^(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?') {
        throw "Could not verify the WSL USB kernel version ($taskKernel). Update WSL, then relaunch."
    }
    $taskRevision = if ($Matches[4]) { [int]$Matches[4] } else { 0 }
    $taskVersion = [version]::new([int]$Matches[1], [int]$Matches[2], [int]$Matches[3], $taskRevision)
    if ($taskVersion -lt [version]'5.10.60.1') {
        throw "WSL kernel $taskKernel is too old for USB forwarding. Run wsl --update, restart WSL, then relaunch."
    }
}

function Assert-BrutalHostPortsFree {
    foreach ($taskPort in @(8080, 9000)) {
        $taskListener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $taskPort)
        try {
            $taskListener.Start()
        } catch {
            throw "Windows port $taskPort is already in use. Close the other receiver or program before launching Brutal OP25. Nothing was started."
        } finally {
            $taskListener.Stop()
        }
    }
}

try {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
        throw 'WSL is unavailable on this Windows installation. Windows 10 2004+ or Windows 11 with WSL 2 is required.'
    }
    $taskReady = Test-BrutalWslDistribution
    if ($CheckOnly) {
        [pscustomobject]@{ WslUbuntuReady=$taskReady; DockerDesktopRequired=$false; NoChangesMade=$true }
        return
    }
    if (($BackupProfiles -or $RestoreProfilesPath) -and -not $taskReady) {
        throw 'Ubuntu WSL is not installed yet. Install Brutal OP25 before backing up or restoring systems.'
    }
    Write-Host 'BRUTAL OP25 // WINDOWS + WSL SETUP'
    Write-Host 'Built on boatbod/op25. OP25 and Docker Engine run inside Ubuntu, not Docker Desktop.'
    try {
        if (Install-BrutalStartMenuShortcut $taskRoot) {
            Write-Host 'Next time, search the Windows Start menu for Brutal OP25.'
        }
    } catch {
        Write-Warning ('Could not create the Start menu shortcut: ' + $_.Exception.Message)
    }
    $taskDockerInstalled = $false
    if ($taskReady) {
        $taskProbe = Invoke-BrutalWslProbe @('-d',$taskDistribution,'-u','root','--','test','-x','/usr/bin/docker')
        $taskDockerInstalled = ($taskProbe.ExitCode -eq 0)
    }
    $taskInstallConsent = ''
    if (-not $taskReady -or -not $taskDockerInstalled) {
        Write-Host 'Setup will install official Ubuntu 24.04 (if missing) and Docker Engine inside Ubuntu.'
        Write-Host 'Docker Engine runs as a Linux service and may change WSL firewall behavior; no Docker Desktop account or app is needed.'
        $taskInstallConsent = if ($env:BRUTAL_DOCKER_INSTALL_ACCEPTED -eq '1') { '1' } else { Read-Host 'Install these components and continue? [y/N]' }
        if ($taskInstallConsent -notin @('1','y','Y')) { throw 'Installation declined. Nothing was installed by this step.' }
    }
    if (-not $taskReady) { Install-BrutalWslDistribution }
    Assert-BrutalWslUsbSupport
    # Windows PowerShell 5.1 strips backslashes in nested native argv.
    $taskForwardRoot = $taskRoot.Replace('\','/')
    $taskProbe = Invoke-BrutalWslProbe @('-d',$taskDistribution,'-u','root','--','wslpath','-u',$taskForwardRoot)
    $taskLinuxRoot = $taskProbe.Output
    if ($taskProbe.ExitCode -ne 0 -or -not $taskLinuxRoot.StartsWith('/')) {
        throw 'Ubuntu WSL could not access the Brutal OP25 folder. Keep it on a Windows drive visible to WSL, then relaunch.'
    }
    $taskLinuxLauncher = $taskLinuxRoot + '/install/brutal-wsl.sh'
    $taskProbe = Invoke-BrutalWslProbe @('-d',$taskDistribution,'-u','root','--','test','-f',$taskLinuxLauncher)
    if ($taskProbe.ExitCode -ne 0) {
        throw 'Ubuntu WSL cannot see the Brutal OP25 program files. Install to a normal folder under your Windows user profile, then relaunch.'
    }
    $taskLinuxArgs = @('-d',$taskDistribution,'-u','root','--','env')
    if ($taskInstallConsent) { $taskLinuxArgs += 'BRUTAL_DOCKER_INSTALL_ACCEPTED=1' }
    $taskLinuxArgs += @('bash',$taskLinuxLauncher)
    if ($PrepareOnly) {
        & wsl.exe @taskLinuxArgs --prepare-only
        if ($LASTEXITCODE -ne 0) { throw 'Linux Docker Engine or OP25 image preparation failed. See the message above.' }
        return
    }
    if ($BackupProfiles -or $RestoreProfilesPath) {
        if ($BackupProfiles) {
            $taskBackupFolder = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Brutal OP25 Backups'
            New-Item -ItemType Directory -Path $taskBackupFolder -Force | Out-Null
            $taskBackupName = 'systems-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.zip'
            $taskHostBackup = Join-Path $taskBackupFolder $taskBackupName
            $taskTransferAction = 'export'
        } else {
            $taskHostBackup = [IO.Path]::GetFullPath($RestoreProfilesPath)
            if (-not (Test-Path -LiteralPath $taskHostBackup -PathType Leaf)) { throw 'Backup ZIP not found.' }
            $taskTransferAction = 'restore'
        }
        $taskProbe = Invoke-BrutalWslProbe @('-d',$taskDistribution,'-u','root','--','wslpath','-u',$taskHostBackup.Replace('\','/'))
        $taskLinuxBackup = $taskProbe.Output
        if ($taskProbe.ExitCode -ne 0 -or -not $taskLinuxBackup.StartsWith('/')) {
            throw 'Ubuntu WSL cannot access that backup path.'
        }
        & wsl.exe @taskLinuxArgs --prepare-only
        if ($LASTEXITCODE -ne 0) { throw 'Linux Docker Engine is unavailable for profile transfer.' }
        & wsl.exe -d $taskDistribution -u root -- bash ($taskLinuxRoot + '/install/profile-data.sh') $taskTransferAction $taskLinuxBackup
        if ($LASTEXITCODE -ne 0) { throw 'Saved-system transfer failed. Existing systems were not overwritten.' }
        if ($BackupProfiles) { Write-Host "Saved-system backup: $taskHostBackup" }
        return
    }
    if ($UpdateImage -or $RollbackImage) {
        $taskAction = if ($UpdateImage) { '--update-image' } else { '--rollback-image' }
        & wsl.exe @taskLinuxArgs $taskAction
        if ($LASTEXITCODE -ne 0) { throw 'Image change failed. The saved systems were not changed.' }
        return
    }
    Assert-BrutalHostPortsFree
    Write-Host 'Dashboard link: http://127.0.0.1:8080/'
    Write-Host 'The dashboard will open in your default browser when the receiver starts.'
    $taskWatcher = Join-Path $PSScriptRoot 'open-brutal-ui.ps1'
    try {
        $taskDashboardWatcher = Start-Process -FilePath 'powershell.exe' -WindowStyle Hidden -PassThru -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"'+$taskWatcher+'"'),'-ParentProcessId',([string]$PID))
    } catch {
        Write-Host 'Automatic browser opening is unavailable. Use the dashboard link shown above.'
    }
    & wsl.exe @taskLinuxArgs
    if ($LASTEXITCODE -ne 0) { throw 'Brutal OP25 stopped with an error. See the message above; saved systems were not removed.' }
} catch {
    Write-Host ('Setup needs attention: ' + $_.Exception.Message) -ForegroundColor Yellow
    exit 1
} finally {
    if ($taskDashboardWatcher -and -not $taskDashboardWatcher.HasExited) {
        Stop-Process -Id $taskDashboardWatcher.Id -ErrorAction SilentlyContinue
    }
}
