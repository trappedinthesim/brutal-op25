$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskTest = Join-Path ([IO.Path]::GetTempPath()) ('BrutalOP25-bootstrap-test-' + [guid]::NewGuid().ToString('N'))
$taskBootstrap = Join-Path $taskRoot 'bootstrap/Install-Brutal-OP25.ps1'
function New-TestArchive([string]$Target, [int]$ExitCode) {
    $taskFolder = Join-Path $taskTest ('fixture-' + $ExitCode)
    $taskPayload = Join-Path $taskFolder 'brutal-op25-main'
    New-Item -ItemType Directory -Path (Join-Path $taskPayload 'install') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $taskPayload 'build') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $taskPayload 'Launch-Brutal-OP25.cmd') -Value ("@echo off`r`nexit /b $ExitCode")
    Set-Content -LiteralPath (Join-Path $taskPayload 'install/install-brutal-wsl.ps1') -Value '# fixture'
    Set-Content -LiteralPath (Join-Path $taskPayload 'build/image-release.txt') -Value 'ghcr.io/trappedinthesim/brutal-op25-receiver:0.3.0-dev.6'
    Compress-Archive -LiteralPath $taskPayload -DestinationPath $Target
}
try {
    New-Item -ItemType Directory -Path $taskTest | Out-Null
    $taskFirst = Join-Path $taskTest 'first.zip'
    $taskBad = Join-Path $taskTest 'bad.zip'
    $taskInstall = Join-Path $taskTest 'installed'
    New-TestArchive $taskFirst 0
    New-TestArchive $taskBad 7
    $taskFailed = $false
    try { & $taskBootstrap -ArchivePath $taskBad -InstallPath $taskInstall -NoLaunch }
    catch { $taskFailed = $true }
    if (-not $taskFailed -or (Test-Path -LiteralPath $taskInstall)) {
        throw 'Failed first install blocked a clean retry.'
    }
    & $taskBootstrap -ArchivePath $taskFirst -InstallPath $taskInstall -NoLaunch
    if (-not (Test-Path -LiteralPath (Join-Path $taskInstall 'Launch-Brutal-OP25.cmd'))) { throw 'Initial bootstrap failed.' }
    $taskFailed = $false
    try { & $taskBootstrap -ArchivePath $taskBad -InstallPath $taskInstall -Update -NoLaunch }
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
