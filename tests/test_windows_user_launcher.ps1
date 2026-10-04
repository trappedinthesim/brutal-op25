$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $taskRoot 'install/user-launcher.ps1')
$taskTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$taskFolder = Join-Path $taskTempRoot ('brutal-shortcut-test-' + [guid]::NewGuid().ToString('N'))
$taskLauncherRoot = Join-Path $taskFolder 'Install With Spaces'
$taskPrograms = Join-Path $taskFolder 'Start Menu'
$taskDesktop = Join-Path $taskFolder 'Desktop'
try {
    New-Item -ItemType Directory -Path (Join-Path $taskLauncherRoot 'src') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $taskLauncherRoot 'install') -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $taskLauncherRoot 'build') -Force | Out-Null
    $taskLauncher = Join-Path $taskLauncherRoot 'Launch-Brutal-OP25.cmd'
    Set-Content -LiteralPath $taskLauncher -Value '@echo off' -NoNewline
    Set-Content -LiteralPath (Join-Path $taskLauncherRoot 'build/image-release.txt') -Value 'test-image'
    Copy-Item -LiteralPath (Join-Path $taskRoot 'src/brutal-logo.png') -Destination (Join-Path $taskLauncherRoot 'src/brutal-logo.png')
    Copy-Item -LiteralPath (Join-Path $taskRoot 'install/desktop-actions.ps1') -Destination (Join-Path $taskLauncherRoot 'install/desktop-actions.ps1')
    Copy-Item -LiteralPath (Join-Path $taskRoot 'install/user-launcher.ps1') -Destination (Join-Path $taskLauncherRoot 'install/user-launcher.ps1')
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
    if (-not (Install-BrutalDesktopFolder $taskLauncherRoot $taskDesktop)) {
        throw 'Desktop shortcut creation returned false.'
    }
    $taskIcon = Join-Path $taskLauncherRoot 'src/brutal-logo.ico'
    Add-Type -AssemblyName System.Drawing
    $taskLoadedIcon = [System.Drawing.Icon]::new($taskIcon)
    try {
        if ($taskLoadedIcon.Width -ne 128) { throw 'Windows could not load the app icon.' }
    } finally { $taskLoadedIcon.Dispose() }
    foreach ($taskAction in @('Launch Brutal OP25', 'Update Brutal OP25', 'Uninstall Brutal OP25')) {
        $taskLink = $taskShell.CreateShortcut((Join-Path $taskDesktop "OP25/$taskAction.lnk"))
        if (-not $taskLink.IconLocation.StartsWith($taskIcon, [StringComparison]::OrdinalIgnoreCase)) {
            throw "The $taskAction shortcut does not use the Brutal icon."
        }
        if ($taskAction -ne 'Launch Brutal OP25' -and
            ($taskLink.TargetPath -ine (Join-Path $env:WINDIR 'System32/WindowsPowerShell/v1.0/powershell.exe') -or
             $taskLink.Arguments -notmatch ('-Action ' + $taskAction.Split(' ')[0]))) {
            throw "The $taskAction shortcut does not start its expected action."
        }
    }
    $global:taskSpawn = $null
    function Start-Process {
        param([string]$FilePath, [string]$WindowStyle, [string[]]$ArgumentList)
        $global:taskSpawn = [pscustomobject]@{ FilePath=$FilePath; Arguments=$ArgumentList }
    }
    & (Join-Path $taskLauncherRoot 'install/desktop-actions.ps1') -Action Update
    Remove-Item Function:Start-Process
    if (-not $global:taskSpawn -or $global:taskSpawn.Arguments -notcontains '-Staged' -or
        $global:taskSpawn.Arguments -notcontains 'Update' -or
        $global:taskSpawn.Arguments -notcontains ('"' + $taskLauncherRoot + '"')) {
        throw 'Update did not hand off safely before replacing program files.'
    }
    $taskStageIndex = [array]::IndexOf($global:taskSpawn.Arguments, '-File') + 1
    $taskStageFile = $global:taskSpawn.Arguments[$taskStageIndex].Trim('"')
    if (-not (Test-Path -LiteralPath $taskStageFile)) { throw 'Update staging file is missing.' }
    Remove-Item -LiteralPath $taskStageFile -Force
    Remove-Variable -Name taskSpawn -Scope Global
    Set-Content -LiteralPath (Join-Path $taskLauncherRoot '.brutal-op25-install') -Value $taskLauncherRoot
    $taskCancelStage = Join-Path $taskTempRoot ('BrutalOP25-action-' + [guid]::NewGuid().ToString('N') + '.ps1')
    Copy-Item -LiteralPath (Join-Path $taskLauncherRoot 'install/desktop-actions.ps1') -Destination $taskCancelStage
    $global:taskReadCount = 0
    function Read-Host {
        $global:taskReadCount++
        if ($global:taskReadCount -eq 1) { return 'NO' }
        return ''
    }
    & $taskCancelStage -Action Uninstall -InstallPath $taskLauncherRoot -Staged | Out-Null
    Remove-Item Function:Read-Host
    if ($global:taskReadCount -ne 2 -or -not (Test-Path -LiteralPath $taskLauncherRoot)) {
        throw 'Declined uninstall did not preserve the program folder.'
    }
    Remove-Variable -Name taskReadCount -Scope Global
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
    $taskUserLinkPath = Join-Path $taskDesktop 'OP25/Update Brutal OP25.lnk'
    $taskUserLink = $taskShell.CreateShortcut($taskUserLinkPath)
    $taskUserLink.Description = 'User-owned desktop shortcut'
    $taskUserLink.Save()
    if (Install-BrutalDesktopFolder $taskLauncherRoot $taskDesktop) {
        throw 'A user-owned desktop shortcut was overwritten.'
    }
    if ($taskShell.CreateShortcut($taskUserLinkPath).Description -cne 'User-owned desktop shortcut') {
        throw 'A user-owned desktop shortcut was changed.'
    }
    $taskUserFile = Join-Path $taskDesktop 'OP25/my-notes.txt'
    Set-Content -LiteralPath $taskUserFile -Value 'keep this'
    if (-not (Invoke-BrutalUninstall $taskLauncherRoot $taskDesktop $taskPrograms -NoPrompt)) {
        throw 'Fixture uninstall did not complete.'
    }
    if ((Test-Path -LiteralPath $taskLauncherRoot) -or
        -not (Test-Path -LiteralPath $taskPath) -or
        -not (Test-Path -LiteralPath $taskUserFile) -or
        -not (Test-Path -LiteralPath $taskUserLinkPath) -or
        ((Get-ChildItem -LiteralPath (Join-Path $taskDesktop 'OP25') -Filter '*.lnk').Count -ne 1)) {
        throw 'Uninstall changed user-owned files or left managed shortcuts.'
    }
    Write-Host 'Windows Start menu, desktop icon, and uninstall tests passed.'
} finally {
    $taskResolved = [IO.Path]::GetFullPath($taskFolder)
    if (-not $taskResolved.StartsWith($taskTempRoot, [StringComparison]::OrdinalIgnoreCase) -or
        -not ([IO.Path]::GetFileName($taskResolved)).StartsWith('brutal-shortcut-test-')) {
        throw 'Unsafe temporary shortcut cleanup target.'
    }
    Remove-Item -LiteralPath $taskResolved -Recurse -Force -ErrorAction SilentlyContinue
}
