function Install-BrutalIcon([string]$Root) {
    $taskPngPath = Join-Path $Root 'src/brutal-logo.png'
    $taskIconPath = Join-Path $Root 'src/brutal-logo.ico'
    if (-not (Test-Path -LiteralPath $taskPngPath -PathType Leaf)) {
        throw 'The Brutal OP25 logo is missing.'
    }
    if (Test-Path -LiteralPath $taskIconPath -PathType Leaf) { return $taskIconPath }
    $taskPng = [IO.File]::ReadAllBytes($taskPngPath)
    $taskSignature = [byte[]]@(137,80,78,71,13,10,26,10)
    if ($taskPng.Length -lt 24) { throw 'The Brutal OP25 logo is not a valid PNG.' }
    for ($taskIndex = 0; $taskIndex -lt $taskSignature.Length; $taskIndex++) {
        if ($taskPng[$taskIndex] -ne $taskSignature[$taskIndex]) {
            throw 'The Brutal OP25 logo is not a valid PNG.'
        }
    }
    $taskWidth = [Net.IPAddress]::NetworkToHostOrder([BitConverter]::ToInt32($taskPng, 16))
    $taskHeight = [Net.IPAddress]::NetworkToHostOrder([BitConverter]::ToInt32($taskPng, 20))
    if ($taskWidth -lt 16 -or $taskWidth -gt 256 -or $taskHeight -lt 16 -or $taskHeight -gt 256) {
        throw 'The Brutal OP25 logo must be between 16 and 256 pixels for a Windows icon.'
    }
    $taskStream = [IO.File]::Open($taskIconPath, [IO.FileMode]::Create, [IO.FileAccess]::Write)
    $taskWriter = [IO.BinaryWriter]::new($taskStream)
    try {
        $taskWriter.Write([uint16]0)
        $taskWriter.Write([uint16]1)
        $taskWriter.Write([uint16]1)
        $taskWriter.Write([byte]($taskWidth % 256))
        $taskWriter.Write([byte]($taskHeight % 256))
        $taskWriter.Write([byte]0)
        $taskWriter.Write([byte]0)
        $taskWriter.Write([uint16]1)
        $taskWriter.Write([uint16]32)
        $taskWriter.Write([uint32]$taskPng.Length)
        $taskWriter.Write([uint32]22)
        $taskWriter.Write($taskPng)
    } finally {
        $taskWriter.Dispose()
    }
    return $taskIconPath
}

function Install-BrutalManagedShortcut([string]$ShortcutPath, [string]$TargetPath,
                                       [string]$WorkingDirectory, [string]$Description,
                                       [string]$IconPath, [string]$Arguments = '') {
    New-Item -ItemType Directory -Path (Split-Path -Parent $ShortcutPath) -Force | Out-Null
    $taskShortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($ShortcutPath)
    if ((Test-Path -LiteralPath $ShortcutPath) -and
        ($taskShortcut.Description -cne $Description -or $taskShortcut.TargetPath -ine $TargetPath)) {
        Write-Warning "An existing user-owned shortcut was left unchanged: $ShortcutPath"
        return $false
    }
    $taskShortcut.TargetPath = $TargetPath
    $taskShortcut.WorkingDirectory = $WorkingDirectory
    $taskShortcut.Description = $Description
    $taskShortcut.IconLocation = $IconPath
    $taskShortcut.Arguments = $Arguments
    $taskShortcut.Save()
    return $true
}

function Install-BrutalStartMenuShortcut([string]$Root, [string]$ProgramsDirectory = '') {
    if (-not $ProgramsDirectory) {
        $ProgramsDirectory = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    }
    $taskLauncher = Join-Path $Root 'Launch-Brutal-OP25.cmd'
    if (-not (Test-Path -LiteralPath $taskLauncher -PathType Leaf)) {
        throw 'The Brutal OP25 Windows launcher is missing.'
    }
    $taskIcon = Install-BrutalIcon $Root
    return Install-BrutalManagedShortcut (Join-Path $ProgramsDirectory 'Brutal OP25.lnk') `
        $taskLauncher $Root 'Managed by Brutal OP25 setup' $taskIcon
}

function Install-BrutalDesktopFolder([string]$Root, [string]$DesktopDirectory = '') {
    if (-not $DesktopDirectory) { $DesktopDirectory = [Environment]::GetFolderPath('DesktopDirectory') }
    if (-not $DesktopDirectory) { throw 'Windows could not locate your Desktop folder.' }
    $taskFolder = Join-Path $DesktopDirectory 'OP25'
    if ((Test-Path -LiteralPath $taskFolder) -and
        -not (Test-Path -LiteralPath $taskFolder -PathType Container)) {
        throw "Desktop OP25 is a file, not a folder: $taskFolder"
    }
    if ((Test-Path -LiteralPath $taskFolder) -and
        ((Get-Item -LiteralPath $taskFolder).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Desktop OP25 is a linked folder; setup will not modify it.'
    }
    $taskLauncher = Join-Path $Root 'Launch-Brutal-OP25.cmd'
    $taskActionScript = Join-Path $Root 'install/desktop-actions.ps1'
    if (-not (Test-Path -LiteralPath $taskLauncher -PathType Leaf) -or
        -not (Test-Path -LiteralPath $taskActionScript -PathType Leaf)) {
        throw 'Brutal OP25 launch or desktop-action files are missing.'
    }
    $taskIcon = Install-BrutalIcon $Root
    $taskPowerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $taskActions = @(
        @{ Name = 'Launch Brutal OP25'; Target = $taskLauncher; Arguments = '' },
        @{ Name = 'Update Brutal OP25'; Target = $taskPowerShell;
           Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $taskActionScript + '" -Action Update' },
        @{ Name = 'Uninstall Brutal OP25'; Target = $taskPowerShell;
           Arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $taskActionScript + '" -Action Uninstall' }
    )
    $taskResults = @()
    foreach ($taskAction in $taskActions) {
        $taskResults += Install-BrutalManagedShortcut (Join-Path $taskFolder ($taskAction.Name + '.lnk')) `
            $taskAction.Target $DesktopDirectory ('Managed by Brutal OP25 setup: ' + $taskAction.Name) `
            $taskIcon $taskAction.Arguments
    }
    return ($taskResults -notcontains $false)
}

function Remove-BrutalManagedShortcut([string]$ShortcutPath, [string]$TargetPath,
                                      [string]$Description) {
    if (-not (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)) { return }
    $taskShortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($ShortcutPath)
    if ($taskShortcut.Description -cne $Description -or $taskShortcut.TargetPath -ine $TargetPath) {
        Write-Warning "User-owned shortcut left in place: $ShortcutPath"
        return
    }
    Remove-Item -LiteralPath $ShortcutPath -Force
}

function Remove-BrutalShortcuts([string]$Root, [string]$DesktopDirectory = '',
                                [string]$ProgramsDirectory = '') {
    if (-not $DesktopDirectory) { $DesktopDirectory = [Environment]::GetFolderPath('DesktopDirectory') }
    if (-not $ProgramsDirectory) {
        $ProgramsDirectory = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    }
    $taskFolder = Join-Path $DesktopDirectory 'OP25'
    $taskSkipDesktop = (Test-Path -LiteralPath $taskFolder) -and
        ((Get-Item -LiteralPath $taskFolder).Attributes -band [IO.FileAttributes]::ReparsePoint)
    $taskLauncher = Join-Path $Root 'Launch-Brutal-OP25.cmd'
    $taskPowerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
    Remove-BrutalManagedShortcut (Join-Path $ProgramsDirectory 'Brutal OP25.lnk') `
        $taskLauncher 'Managed by Brutal OP25 setup'
    if ($taskSkipDesktop) {
        Write-Warning 'Desktop OP25 is a linked folder; its contents were left unchanged.'
    } else {
        foreach ($taskAction in @('Launch Brutal OP25', 'Update Brutal OP25', 'Uninstall Brutal OP25')) {
            $taskTarget = if ($taskAction -eq 'Launch Brutal OP25') { $taskLauncher } else { $taskPowerShell }
            Remove-BrutalManagedShortcut (Join-Path $taskFolder ($taskAction + '.lnk')) `
                $taskTarget ('Managed by Brutal OP25 setup: ' + $taskAction)
        }
        if ((Test-Path -LiteralPath $taskFolder -PathType Container) -and
            -not (Get-ChildItem -LiteralPath $taskFolder -Force | Select-Object -First 1)) {
            Remove-Item -LiteralPath $taskFolder
        }
    }
}

function Invoke-BrutalUninstall([string]$Root, [string]$DesktopDirectory = '',
                                 [string]$ProgramsDirectory = '', [switch]$NoPrompt) {
    $taskRoot = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $taskDriveRoot = [IO.Path]::GetPathRoot($taskRoot).TrimEnd('\')
    $taskHome = [IO.Path]::GetFullPath($env:USERPROFILE).TrimEnd('\')
    $taskDesktop = [IO.Path]::GetFullPath([Environment]::GetFolderPath('DesktopDirectory')).TrimEnd('\')
    if ($taskRoot -ieq $taskDriveRoot -or $taskRoot -ieq $taskHome -or $taskRoot -ieq $taskDesktop) {
        throw 'Refusing to uninstall from a drive root, home folder, or Desktop.'
    }
    $taskDirectory = Get-Item -LiteralPath $taskRoot -ErrorAction Stop
    if ($taskDirectory.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'Refusing to uninstall a linked or redirected program folder.'
    }
    $taskMarker = Join-Path $taskRoot '.brutal-op25-install'
    if (-not (Test-Path -LiteralPath $taskMarker -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $taskRoot 'Launch-Brutal-OP25.cmd') -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $taskRoot 'build/image-release.txt') -PathType Leaf) -or
        (Get-Content -LiteralPath $taskMarker -Raw).Trim() -ine $taskRoot) {
        throw 'This folder is not a verified Brutal OP25 installation; nothing was removed.'
    }
    Write-Host "Program folder: $taskRoot"
    Write-Host 'This removes the entire program folder, including any files you added inside it.' -ForegroundColor Yellow
    Write-Host 'Saved systems, Docker images, Ubuntu WSL, and the Windows USB bridge will be kept.'
    Write-Host 'Close any running Brutal OP25 receiver before uninstalling.'
    if (-not $NoPrompt -and (Read-Host 'Type UNINSTALL to remove the program and shortcuts') -cne 'UNINSTALL') {
        Write-Host 'Uninstall cancelled; nothing was removed.'
        return $false
    }
    $taskRemoved = Join-Path (Split-Path -Parent $taskRoot) `
        ((Split-Path -Leaf $taskRoot) + '.uninstalling.' + [guid]::NewGuid().ToString('N'))
    Move-Item -LiteralPath $taskRoot -Destination $taskRemoved
    try {
        Remove-Item -LiteralPath $taskRemoved -Recurse -Force
    } catch {
        if (-not (Test-Path -LiteralPath $taskRoot) -and (Test-Path -LiteralPath $taskRemoved)) {
            Move-Item -LiteralPath $taskRemoved -Destination $taskRoot
        }
        throw
    }
    Remove-BrutalShortcuts $taskRoot $DesktopDirectory $ProgramsDirectory
    Write-Host 'Brutal OP25 program files and managed shortcuts were removed.'
    Write-Host 'Saved systems and shared dependencies remain available for a future reinstall.'
    return $true
}
