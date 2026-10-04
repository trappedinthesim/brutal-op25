param([Parameter(Mandatory=$true)][ValidateSet('Update','Uninstall')][string]$Action,
      [string]$InstallPath = '', [switch]$Staged, [int]$ParentProcessId = 0)
$ErrorActionPreference = 'Stop'
$taskPowerShell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'

if (-not $Staged) {
    $taskRoot = Split-Path -Parent $PSScriptRoot
    $taskStagedScript = Join-Path ([IO.Path]::GetTempPath()) `
        ('BrutalOP25-action-' + [guid]::NewGuid().ToString('N') + '.ps1')
    Copy-Item -LiteralPath $PSCommandPath -Destination $taskStagedScript
    # The installed script must exit before Update moves its own program folder.
    Start-Process -FilePath $taskPowerShell -WindowStyle Normal -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ('"' + $taskStagedScript + '"'),
        '-Action', $Action, '-InstallPath', ('"' + $taskRoot + '"'),
        '-Staged', '-ParentProcessId', [string]$PID)
    return
}

$taskDownload = ''
try {
    $taskStagePath = [IO.Path]::GetFullPath($PSCommandPath)
    $taskTempPath = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    if (-not $taskStagePath.StartsWith($taskTempPath, [StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $taskStagePath) -notlike 'BrutalOP25-action-*.ps1') {
        throw 'The desktop action was not staged safely; nothing was changed.'
    }
    if ($ParentProcessId -gt 0) {
        for ($taskAttempt = 0; $taskAttempt -lt 50; $taskAttempt++) {
            if (-not (Get-Process -Id $ParentProcessId -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Milliseconds 100
        }
        if (Get-Process -Id $ParentProcessId -ErrorAction SilentlyContinue) {
            throw 'The launcher is still closing. Try the action again.'
        }
    }
    if ($Action -eq 'Update') {
        $taskDownload = Join-Path ([IO.Path]::GetTempPath()) `
            ('BrutalOP25-update-' + [guid]::NewGuid().ToString('N') + '.ps1')
        Write-Host 'Downloading the latest official Brutal OP25 updater...'
        Invoke-WebRequest -UseBasicParsing `
            'https://raw.githubusercontent.com/trappedinthesim/brutal-op25/main/bootstrap/Install-Brutal-OP25.ps1' `
            -OutFile $taskDownload
        & $taskDownload -Update -NoLaunch -InstallPath $InstallPath
        Write-Host 'Update complete. Use Launch Brutal OP25 to start listening.'
    } else {
        . (Join-Path $InstallPath 'install/user-launcher.ps1')
        Invoke-BrutalUninstall $InstallPath | Out-Null
    }
} catch {
    Write-Host ('Action needs attention: ' + $_.Exception.Message) -ForegroundColor Yellow
} finally {
    if ($taskDownload -and (Test-Path -LiteralPath $taskDownload)) {
        Remove-Item -LiteralPath $taskDownload -Force -ErrorAction SilentlyContinue
    }
    Read-Host 'Press Enter to close' | Out-Null
    if ($taskStagePath -and $taskStagePath.StartsWith($taskTempPath, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $taskStagePath) -like 'BrutalOP25-action-*.ps1') {
        Remove-Item -LiteralPath $taskStagePath -Force -ErrorAction SilentlyContinue
    }
}
