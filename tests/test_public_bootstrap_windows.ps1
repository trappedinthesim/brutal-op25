$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskTest = Join-Path ([IO.Path]::GetTempPath()) ('BrutalOP25-bootstrap-test-' + [guid]::NewGuid().ToString('N'))
$taskBootstrap = Join-Path $taskRoot 'bootstrap/Install-Brutal-OP25.ps1'
function New-TestArchive([string]$Target, [int]$ExitCode, [int]$LaunchExitCode = 0) {
    $taskFolder = Join-Path $taskTest ('fixture-' + $ExitCode)
    $taskPayload = Join-Path $taskFolder 'brutal-op25-main'
    New-Item -ItemType Directory -Path (Join-Path $taskPayload 'install') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $taskPayload 'build') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $taskPayload 'src') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $taskPayload 'Launch-Brutal-OP25.cmd') -Value ("@echo off`r`nif `"%~1`"==`"--prepare-only`" exit /b $ExitCode`r`nif `"%~1`"==`"--update-image`" exit /b $ExitCode`r`nexit /b $LaunchExitCode")
    Set-Content -LiteralPath (Join-Path $taskPayload 'install/install-brutal-wsl.ps1') -Value '# fixture'
    Copy-Item -LiteralPath (Join-Path $taskRoot 'install/user-launcher.ps1') -Destination (Join-Path $taskPayload 'install/user-launcher.ps1')
    Copy-Item -LiteralPath (Join-Path $taskRoot 'install/desktop-actions.ps1') -Destination (Join-Path $taskPayload 'install/desktop-actions.ps1')
    Copy-Item -LiteralPath (Join-Path $taskRoot 'install/uninstall-brutal-data.sh') -Destination (Join-Path $taskPayload 'install/uninstall-brutal-data.sh')
    Copy-Item -LiteralPath (Join-Path $taskRoot 'src/brutal-logo.png') -Destination (Join-Path $taskPayload 'src/brutal-logo.png')
    Set-Content -LiteralPath (Join-Path $taskPayload 'build/image-release.txt') -Value 'ghcr.io/trappedinthesim/brutal-op25-receiver:0.3.0-dev.24'
    Compress-Archive -LiteralPath $taskPayload -DestinationPath $Target
}
try {
    New-Item -ItemType Directory -Path $taskTest | Out-Null
    $taskFirst = Join-Path $taskTest 'first.zip'
    $taskBad = Join-Path $taskTest 'bad.zip'
    $taskInstall = Join-Path $taskTest 'installed'
    $taskDesktop = Join-Path $taskTest 'Desktop'
    $taskPrograms = Join-Path $taskTest 'Start Menu'
    New-TestArchive $taskFirst 0
    New-TestArchive $taskBad 7
    $taskLaunchBad = Join-Path $taskTest 'launch-bad.zip'
    New-TestArchive $taskLaunchBad 0 7
    $taskLaunchInstall = Join-Path $taskTest 'launch-installed'
    $taskLaunchDesktop = Join-Path $taskTest 'Launch Test Desktop'
    $taskLaunchPrograms = Join-Path $taskTest 'Launch Test Start Menu'
    $taskPreviousNativeSetting = $PSNativeCommandUseErrorActionPreference
    try {
        $PSNativeCommandUseErrorActionPreference = $true
        try { & $taskBootstrap -ArchivePath $taskLaunchBad -InstallPath $taskLaunchInstall -DesktopDirectory $taskLaunchDesktop -ProgramsDirectory $taskLaunchPrograms }
        catch { }
    } finally { $PSNativeCommandUseErrorActionPreference = $taskPreviousNativeSetting }
    if (-not (Test-Path -LiteralPath (Join-Path $taskLaunchInstall '.brutal-op25-install')) -or
        @(Get-ChildItem -LiteralPath $taskTest -Directory -Filter 'launch-installed.incomplete.*').Count) {
        throw 'Receiver startup failure undid a successful installation.'
    }
    $taskSpacedInstall = Join-Path $taskTest 'Install With Spaces'
    $taskSpacedDesktop = Join-Path $taskTest 'Spaced Desktop'
    $taskSpacedPrograms = Join-Path $taskTest 'Spaced Start Menu'
    foreach ($taskExtra in @($false, $true)) {
        & $taskBootstrap -ArchivePath $taskFirst -InstallPath $taskSpacedInstall -DesktopDirectory $taskSpacedDesktop -ProgramsDirectory $taskSpacedPrograms -Update:$taskExtra -NoLaunch
    }
    if ((Get-Content -LiteralPath (Join-Path $taskSpacedInstall '.brutal-op25-install') -Raw).Trim() -ine $taskSpacedInstall) {
        throw 'Install path with spaces did not survive the update.'
    }
    $taskUnrelated = Join-Path $taskTest 'UnrelatedFolder'
    New-Item -ItemType Directory -Path $taskUnrelated | Out-Null
    Set-Content -LiteralPath (Join-Path $taskUnrelated 'notes.txt') -Value 'Keep this'
    $taskFailed = $false
    try { & $taskBootstrap -ArchivePath $taskFirst -InstallPath $taskUnrelated -DesktopDirectory $taskDesktop -ProgramsDirectory $taskPrograms -Update -NoLaunch }
    catch { $taskFailed = $true }
    if (-not $taskFailed -or
        (Get-Content -LiteralPath (Join-Path $taskUnrelated 'notes.txt') -Raw).Trim() -ne 'Keep this' -or
        @(Get-ChildItem -LiteralPath $taskTest -Directory -Filter 'UnrelatedFolder.previous.*').Count) {
        throw 'Update moved or changed an unrelated directory.'
    }
    $taskFailed = $false
    try { & $taskBootstrap -ArchivePath $taskBad -InstallPath $taskInstall -DesktopDirectory $taskDesktop -ProgramsDirectory $taskPrograms -NoLaunch }
    catch { $taskFailed = $true }
    if (-not $taskFailed -or (Test-Path -LiteralPath $taskInstall)) {
        throw 'Failed first install blocked a clean retry.'
    }
    & $taskBootstrap -ArchivePath $taskFirst -InstallPath $taskInstall -DesktopDirectory $taskDesktop -ProgramsDirectory $taskPrograms -NoLaunch
    if (-not (Test-Path -LiteralPath (Join-Path $taskInstall 'Launch-Brutal-OP25.cmd'))) { throw 'Initial bootstrap failed.' }
    foreach ($taskName in @('Launch Brutal OP25', 'Update Brutal OP25', 'Uninstall Brutal OP25')) {
        if (-not (Test-Path -LiteralPath (Join-Path $taskDesktop "OP25/$taskName.lnk"))) {
            throw "Missing desktop shortcut: $taskName"
        }
    }
    $taskFailed = $false
    try { & $taskBootstrap -ArchivePath $taskBad -InstallPath $taskInstall -DesktopDirectory $taskDesktop -ProgramsDirectory $taskPrograms -Update -NoLaunch }
    catch { $taskFailed = $true }
    if (-not $taskFailed) { throw 'The failed update unexpectedly succeeded.' }
    $taskContent = Get-Content -LiteralPath (Join-Path $taskInstall 'Launch-Brutal-OP25.cmd') -Raw
    if ($taskContent -notmatch 'exit /b 0') { throw 'Previous install was not restored.' }
    & $taskBootstrap -ArchivePath $taskFirst -InstallPath $taskInstall -DesktopDirectory $taskDesktop -ProgramsDirectory $taskPrograms -Update -NoLaunch
    Start-Sleep -Seconds 1
    & $taskBootstrap -ArchivePath $taskFirst -InstallPath $taskInstall -DesktopDirectory $taskDesktop -ProgramsDirectory $taskPrograms -Update -NoLaunch
    $taskBackups = @(Get-ChildItem -LiteralPath $taskTest -Directory -Filter 'installed.previous.*')
    if ($taskBackups.Count -ne 1) { throw 'Successful updates did not retain exactly one previous program folder.' }
    Set-Content -LiteralPath (Join-Path $taskBackups[0].FullName 'user-notes.txt') -Value 'Keep this file'
    Start-Sleep -Seconds 1
    & $taskBootstrap -ArchivePath $taskFirst -InstallPath $taskInstall -DesktopDirectory $taskDesktop -ProgramsDirectory $taskPrograms -Update -NoLaunch
    $taskBackups = @(Get-ChildItem -LiteralPath $taskTest -Directory -Filter 'installed.previous.*')
    if ($taskBackups.Count -ne 2 -or
        -not (Test-Path -LiteralPath (Join-Path $taskBackups[0].FullName 'user-notes.txt')) -and
        -not (Test-Path -LiteralPath (Join-Path $taskBackups[1].FullName 'user-notes.txt'))) {
        throw 'Cleanup removed a modified previous program folder.'
    }
    $taskLegacy = Join-Path $taskTest 'installed.previous.20000101-000000'
    New-Item -ItemType Directory -Path $taskLegacy | Out-Null
    Set-Content -LiteralPath (Join-Path $taskLegacy 'unknown-file.txt') -Value 'Preserve this'
    Start-Sleep -Seconds 1
    & $taskBootstrap -ArchivePath $taskFirst -InstallPath $taskInstall -DesktopDirectory $taskDesktop -ProgramsDirectory $taskPrograms -Update -NoLaunch
    if (-not (Test-Path -LiteralPath (Join-Path $taskLegacy 'unknown-file.txt'))) {
        throw 'Cleanup removed an unverified legacy folder.'
    }
    Write-Output 'PASS: Windows update rollback, old-version cleanup, and changed-folder preservation'
} finally {
    $taskResolved = [IO.Path]::GetFullPath($taskTest)
    $taskTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($taskResolved.StartsWith($taskTemp, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $taskResolved) -like 'BrutalOP25-bootstrap-test-*' -and
        (Test-Path -LiteralPath $taskResolved)) {
        Remove-Item -LiteralPath $taskResolved -Recurse -Force
    }
}
