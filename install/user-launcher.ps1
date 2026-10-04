function Install-BrutalStartMenuShortcut([string]$Root, [string]$ProgramsDirectory = '') {
    if (-not $ProgramsDirectory) {
        $ProgramsDirectory = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    }
    $launcher = Join-Path $Root 'Launch-Brutal-OP25.cmd'
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) {
        throw 'The Brutal OP25 Windows launcher is missing.'
    }
    $shortcutPath = Join-Path $ProgramsDirectory 'Brutal OP25.lnk'
    $description = 'Managed by Brutal OP25 setup'
    New-Item -ItemType Directory -Path $ProgramsDirectory -Force | Out-Null
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    if ((Test-Path -LiteralPath $shortcutPath) -and $shortcut.Description -ne $description) {
        Write-Warning "An existing Start menu shortcut was left unchanged: $shortcutPath"
        return $false
    }
    $shortcut.TargetPath = $launcher
    $shortcut.WorkingDirectory = $Root
    $shortcut.Description = $description
    $shortcut.Save()
    return $true
}
