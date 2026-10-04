param([switch]$Update, [switch]$NoLaunch, [string]$ArchivePath = '', [string]$InstallPath = '')
$ErrorActionPreference = 'Stop'
if (-not $InstallPath) { $InstallPath = Join-Path $env:LOCALAPPDATA 'BrutalOP25' }
$InstallPath = [IO.Path]::GetFullPath($InstallPath)
$taskParent = Split-Path -Parent $InstallPath
$taskName = Split-Path -Leaf $InstallPath
if ($taskName -eq '' -or $taskParent -eq $InstallPath) { throw 'Choose a normal installation folder, not a drive root.' }
New-Item -ItemType Directory -Path $taskParent -Force | Out-Null
$taskWork = Join-Path ([IO.Path]::GetTempPath()) ('BrutalOP25-bootstrap-' + [guid]::NewGuid().ToString('N'))
$taskBackup = ''
$taskMoved = $false
try {
    if ((Test-Path -LiteralPath $InstallPath) -and -not $Update) {
        throw "Brutal OP25 is already installed at $InstallPath. Use -Update to replace its program files. Saved systems are stored separately."
    }
    if ($Update -and -not (Test-Path -LiteralPath $InstallPath -PathType Container)) {
        throw "No installation found at $InstallPath. Run without -Update first."
    }
    New-Item -ItemType Directory -Path $taskWork | Out-Null
    $taskArchive = Join-Path $taskWork 'source.zip'
    if ($ArchivePath) {
        Copy-Item -LiteralPath ([IO.Path]::GetFullPath($ArchivePath)) -Destination $taskArchive
    } else {
        Write-Host 'Downloading Brutal OP25 source from GitHub (no Git account or client required).'
        Invoke-WebRequest -UseBasicParsing 'https://github.com/trappedinthesim/brutal-op25/archive/refs/heads/main.zip' -OutFile $taskArchive
    }
    $taskExpanded = Join-Path $taskWork 'expanded'
    Expand-Archive -LiteralPath $taskArchive -DestinationPath $taskExpanded
    $taskEntries = @(Get-ChildItem -LiteralPath $taskExpanded -Directory)
    if ($taskEntries.Count -ne 1) { throw 'The downloaded source archive has an unexpected layout.' }
    $taskPayload = $taskEntries[0].FullName
    foreach ($taskFile in @('Launch-Brutal-OP25.cmd','install/install-brutal-wsl.ps1','build/image-release.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $taskPayload $taskFile) -PathType Leaf)) {
            throw "The downloaded source archive is missing $taskFile."
        }
    }
    $taskImage = (Get-Content -LiteralPath (Join-Path $taskPayload 'build/image-release.txt') -Raw).Trim()
    if ($taskImage -notmatch '^ghcr\.io/trappedinthesim/brutal-op25:[a-zA-Z0-9._-]+$') {
        throw 'The downloaded source archive has an invalid release-image reference.'
    }
    if ($Update) {
        $taskBackup = Join-Path $taskParent ($taskName + '.previous.' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
        if (Test-Path -LiteralPath $taskBackup) { throw "Update backup path already exists: $taskBackup" }
        Move-Item -LiteralPath $InstallPath -Destination $taskBackup
    }
    Move-Item -LiteralPath $taskPayload -Destination $InstallPath
    $taskMoved = $true
    & (Join-Path $InstallPath 'Launch-Brutal-OP25.cmd') --prepare-only
    if ($LASTEXITCODE -ne 0) { throw 'New version could not prepare its Linux engine or image.' }
    if ($Update) {
        & (Join-Path $InstallPath 'Launch-Brutal-OP25.cmd') --update-image
        if ($LASTEXITCODE -ne 0) { throw 'New release image could not be fetched; previous program files will be restored.' }
    }
    Write-Host "Brutal OP25 ready at $InstallPath"
    if ($taskBackup) { Write-Host "Previous program files kept at $taskBackup" }
    if (-not $NoLaunch) { & (Join-Path $InstallPath 'Launch-Brutal-OP25.cmd') }
} catch {
    if ($taskBackup -and $taskMoved -and (Test-Path -LiteralPath $InstallPath)) {
        $taskFailed = Join-Path $taskParent ($taskName + '.failed.' + [guid]::NewGuid().ToString('N'))
        Move-Item -LiteralPath $InstallPath -Destination $taskFailed
        Move-Item -LiteralPath $taskBackup -Destination $InstallPath
        Write-Warning "Previous program files restored. Failed update retained at $taskFailed"
    } elseif ($taskBackup -and -not (Test-Path -LiteralPath $InstallPath) -and (Test-Path -LiteralPath $taskBackup)) {
        Move-Item -LiteralPath $taskBackup -Destination $InstallPath
    }
    throw
} finally {
    $taskTempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
    $taskResolved = [IO.Path]::GetFullPath($taskWork)
    if ($taskResolved.StartsWith($taskTempRoot, [StringComparison]::OrdinalIgnoreCase) -and
        (Split-Path -Leaf $taskResolved) -like 'BrutalOP25-bootstrap-*' -and
        (Test-Path -LiteralPath $taskResolved)) {
        Remove-Item -LiteralPath $taskResolved -Recurse -Force
    }
}
