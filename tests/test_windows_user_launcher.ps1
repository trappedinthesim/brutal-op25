$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $taskRoot 'install/user-launcher.ps1')
$taskTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$taskFolder = Join-Path $taskTempRoot ('brutal-shortcut-test-' + [guid]::NewGuid().ToString('N'))
$taskLauncherRoot = Join-Path $taskFolder 'Install With Spaces'
$taskPrograms = Join-Path $taskFolder 'Start Menu'
try {
    New-Item -ItemType Directory -Path $taskLauncherRoot -Force | Out-Null
    $taskLauncher = Join-Path $taskLauncherRoot 'Launch-Brutal-OP25.cmd'
    Set-Content -LiteralPath $taskLauncher -Value '@echo off' -NoNewline
    if (-not (Install-BrutalStartMenuShortcut $taskLauncherRoot $taskPrograms)) {
        throw 'Shortcut creation returned false.'
    }
    $taskPath = Join-Path $taskPrograms 'Brutal OP25.lnk'
    $taskShell = New-Object -ComObject WScript.Shell
    $taskShortcut = $taskShell.CreateShortcut($taskPath)
    if ($taskShortcut.TargetPath -cne $taskLauncher -or
        $taskShortcut.WorkingDirectory -cne $taskLauncherRoot) {
        throw 'Shortcut target or working directory was incorrect.'
    }
    if (-not (Install-BrutalStartMenuShortcut $taskLauncherRoot $taskPrograms)) {
        throw 'Shortcut refresh returned false.'
    }
    $taskShortcut.Description = 'User-owned shortcut'
    $taskShortcut.Save()
    if (Install-BrutalStartMenuShortcut $taskLauncherRoot $taskPrograms) {
        throw 'A user-owned shortcut was overwritten.'
    }
    if ($taskShell.CreateShortcut($taskPath).Description -cne 'User-owned shortcut') {
        throw 'A user-owned shortcut was changed.'
    }
    Write-Host 'Windows Start menu shortcut tests passed.'
} finally {
    $taskResolved = [IO.Path]::GetFullPath($taskFolder)
    if (-not $taskResolved.StartsWith($taskTempRoot, [StringComparison]::OrdinalIgnoreCase) -or
        -not ([IO.Path]::GetFileName($taskResolved)).StartsWith('brutal-shortcut-test-')) {
        throw 'Unsafe temporary shortcut cleanup target.'
    }
    Remove-Item -LiteralPath $taskResolved -Recurse -Force -ErrorAction SilentlyContinue
}
