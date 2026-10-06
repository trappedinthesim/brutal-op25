param([switch]$Update, [switch]$NoLaunch, [string]$ArchivePath = '', [string]$InstallPath = '',
      [string]$DesktopDirectory = '', [string]$ProgramsDirectory = '')
$ErrorActionPreference = 'Stop'
if (-not $InstallPath) { $InstallPath = Join-Path $env:USERPROFILE 'BrutalOP25' }
$InstallPath = [IO.Path]::GetFullPath($InstallPath)
$taskParent = Split-Path -Parent $InstallPath
$taskName = Split-Path -Leaf $InstallPath
if ($taskName -eq '' -or $taskParent -eq $InstallPath) { throw 'Choose a normal installation folder, not a drive root.' }
New-Item -ItemType Directory -Path $taskParent -Force | Out-Null
$taskWork = Join-Path ([IO.Path]::GetTempPath()) ('BrutalOP25-bootstrap-' + [guid]::NewGuid().ToString('N'))
$taskBackup = ''
$taskMoved = $false
function Get-BrutalProgramManifest([string]$Root) {
    $taskBase = [IO.Path]::GetFullPath($Root).TrimEnd('\')
    $taskLines = [System.Collections.Generic.List[string]]::new()
    foreach ($taskEntry in @(Get-ChildItem -LiteralPath $taskBase -Recurse -Force)) {
        if ($taskEntry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Linked item found in program folder: $($taskEntry.FullName)"
        }
        if ($taskEntry.PSIsContainer) { continue }
        $taskRelative = $taskEntry.FullName.Substring($taskBase.Length + 1).Replace('\','/')
        if ($taskRelative -in @('.brutal-op25-install','.brutal-op25-manifest')) { continue }
        $taskLines.Add($taskRelative + "`t" + (Get-FileHash -LiteralPath $taskEntry.FullName -Algorithm SHA256).Hash)
    }
    return ([string]::Join("`n", @($taskLines | Sort-Object)) + "`n")
}
function Remove-BrutalOldProgramVersions([string]$Parent, [string]$Name,
                                         [string]$Install, [string]$Keep) {
    $taskRemovedCount = 0
    $taskLegacyCount = 0
    $taskOtherCount = 0
    $taskPattern = '^' + [regex]::Escape($Name) + '\.previous\.\d{8}-\d{6}$'
    $taskSafeParent = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
    foreach ($taskCandidate in @(Get-ChildItem -LiteralPath $Parent -Directory)) {
        $taskPath = [IO.Path]::GetFullPath($taskCandidate.FullName)
        if ($taskCandidate.Name -notmatch $taskPattern -or $taskPath -ieq $Keep -or
            [IO.Path]::GetDirectoryName($taskPath).TrimEnd('\') -ine $taskSafeParent -or
            ($taskCandidate.Attributes -band [IO.FileAttributes]::ReparsePoint)) { continue }
        $taskMarker = Join-Path $taskPath '.brutal-op25-install'
        $taskManifest = Join-Path $taskPath '.brutal-op25-manifest'
        if (-not (Test-Path -LiteralPath $taskManifest -PathType Leaf)) {
            $taskLegacyCount++
            continue
        }
        if (-not (Test-Path -LiteralPath $taskMarker -PathType Leaf) -or
            -not (Test-Path -LiteralPath (Join-Path $taskPath 'Launch-Brutal-OP25.cmd') -PathType Leaf) -or
            -not (Test-Path -LiteralPath (Join-Path $taskPath 'build/image-release.txt') -PathType Leaf) -or
            (Get-Content -LiteralPath $taskMarker -Raw).Trim() -ine $Install) {
            $taskOtherCount++
            continue
        }
        if ([IO.File]::ReadAllText($taskManifest) -cne (Get-BrutalProgramManifest $taskPath)) {
            $taskOtherCount++
            continue
        }
        Remove-Item -LiteralPath $taskPath -Recurse -Force
        $taskRemovedCount++
    }
    if ($taskRemovedCount) { Write-Host "Removed $taskRemovedCount older Brutal OP25 program version(s)." }
    if ($taskLegacyCount) {
        Write-Warning "Kept $taskLegacyCount older backup folder(s) without a cleanup inventory beside $Install. This does not mean you changed them."
        Write-Host 'The current installation does not use these folders. They were not auto-deleted because their contents cannot be verified.'
    }
    if ($taskOtherCount) {
        Write-Warning "Kept $taskOtherCount other backup folder(s) that could not be verified beside $Install. They may contain files worth keeping."
    }
}
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
    foreach ($taskFile in @('Launch-Brutal-OP25.cmd','install/install-brutal-wsl.ps1',
                           'install/user-launcher.ps1','install/desktop-actions.ps1',
                           'install/uninstall-brutal-data.sh',
                           'src/brutal-logo.png','build/image-release.txt')) {
        if (-not (Test-Path -LiteralPath (Join-Path $taskPayload $taskFile) -PathType Leaf)) {
            throw "The downloaded source archive is missing $taskFile."
        }
    }
    $taskImage = (Get-Content -LiteralPath (Join-Path $taskPayload 'build/image-release.txt') -Raw).Trim()
    if ($taskImage -notmatch '^ghcr\.io/trappedinthesim/brutal-op25-receiver:[a-zA-Z0-9._-]+$') {
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
    if ($LASTEXITCODE -ne 0) { throw 'Linux engine or image preparation stopped. See the specific setup message above.' }
    [IO.File]::WriteAllText((Join-Path $InstallPath '.brutal-op25-install'), $InstallPath)
    . (Join-Path $InstallPath 'install/user-launcher.ps1')
    try {
        if (Install-BrutalStartMenuShortcut $InstallPath $ProgramsDirectory) {
            Write-Host 'Start menu: Brutal OP25'
        }
    } catch {
        Write-Warning ('Could not create the Start-menu shortcut: ' + $_.Exception.Message)
    }
    try {
        if (Install-BrutalDesktopFolder $InstallPath $DesktopDirectory) {
            Write-Host 'Desktop: OP25 folder with Launch, Update, and Uninstall shortcuts.'
        }
    } catch {
        Write-Warning ('Could not create the Desktop OP25 shortcuts: ' + $_.Exception.Message)
    }
    [IO.File]::WriteAllText((Join-Path $InstallPath '.brutal-op25-manifest'),
        (Get-BrutalProgramManifest $InstallPath))
    if ($Update) {
        & (Join-Path $InstallPath 'Launch-Brutal-OP25.cmd') --update-image
        if ($LASTEXITCODE -ne 0) { throw 'New release image could not be fetched; previous program files will be restored.' }
    }
    Write-Host "Brutal OP25 ready at $InstallPath"
    if ($taskBackup) { Write-Host "Previous program files kept at $taskBackup" }
    if ($Update) {
        try { Remove-BrutalOldProgramVersions $taskParent $taskName $InstallPath $taskBackup }
        catch { Write-Warning ('Old program version cleanup was skipped: ' + $_.Exception.Message) }
    }
    if (-not $NoLaunch) { & (Join-Path $InstallPath 'Launch-Brutal-OP25.cmd') }
} catch {
    if ($taskBackup -and $taskMoved -and (Test-Path -LiteralPath $InstallPath)) {
        $taskFailed = Join-Path $taskParent ($taskName + '.failed.' + [guid]::NewGuid().ToString('N'))
        Move-Item -LiteralPath $InstallPath -Destination $taskFailed
        Move-Item -LiteralPath $taskBackup -Destination $InstallPath
        Write-Warning "Previous program files restored. Failed update retained at $taskFailed"
    } elseif ($taskBackup -and -not (Test-Path -LiteralPath $InstallPath) -and (Test-Path -LiteralPath $taskBackup)) {
        Move-Item -LiteralPath $taskBackup -Destination $InstallPath
    } elseif (-not $Update -and $taskMoved -and (Test-Path -LiteralPath $InstallPath -PathType Container)) {
        $taskFailed = Join-Path $taskParent ($taskName + '.incomplete.' + [guid]::NewGuid().ToString('N'))
        Move-Item -LiteralPath $InstallPath -Destination $taskFailed
        Write-Warning "Incomplete program files kept at $taskFailed. Rerun the same install command after addressing the setup message."
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
