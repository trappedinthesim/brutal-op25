$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskTest = Join-Path ([IO.Path]::GetTempPath()) ('BrutalOP25-bootstrap-test-' + [guid]::NewGuid().ToString('N'))
$taskBootstrap = Join-Path $taskRoot 'bootstrap/Install-Brutal-OP25.ps1'
function New-TestArchive([string]$Target, [int]$ExitCode) {
    $taskFolder = Join-Path $taskTest ('fixture-' + $ExitCode)
    $taskPayload = Join-Path $taskFolder 'brutal-op25-main'
    New-Item -ItemType Directory -Path (Join-Path $taskPayload 'install') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $taskPayload 'build') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $taskPayload 'src') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $taskPayload 'Launch-Brutal-OP25.cmd') -Value ("@echo off`r`nexit /b $ExitCode")
    Set-Content -LiteralPath (Join-Path $taskPayload 'install/install-brutal-wsl.ps1') -Value '# fixture'
    Copy-Item -LiteralPath (Join-Path $taskRoot 'install/user-launcher.ps1') -Destination (Join-Path $taskPayload 'install/user-launcher.ps1')
    Copy-Item -LiteralPath (Join-Path $taskRoot 'install/desktop-actions.ps1') -Destination (Join-Path $taskPayload 'install/desktop-actions.ps1')
    Copy-Item -LiteralPath (Join-Path $taskRoot 'src/brutal-logo.png') -Destination (Join-Path $taskPayload 'src/brutal-logo.png')
    Set-Content -LiteralPath (Join-Path $taskPayload 'build/image-release.txt') -Value 'ghcr.io/trappedinthesim/brutal-op25-receiver:0.3.0-dev.14'
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
    Write-Output 'PASS: Git-free Windows bootstrap and failed-update rollback'
} finally {
    $taskResolved = [IO.Path]::GetFullPath($taskTest)
    $taskTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if ($taskResolved.StartsWith($taskTemp, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $taskResolved) -like 'BrutalOP25-bootstrap-test-*' -and
        (Test-Path -LiteralPath $taskResolved)) {
        Remove-Item -LiteralPath $taskResolved -Recurse -Force
    }
}
