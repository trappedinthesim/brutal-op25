param(
    [ValidateSet('connect','detach')][string]$Mode = 'connect',
    [ValidateSet('rtl','rtlv4','rspdxr2')][string]$Profile = 'rtl',
    [string]$BusId = ''
)
$ErrorActionPreference = 'Stop'
$taskUsb = Join-Path $env:ProgramFiles 'usbipd-win/usbipd.exe'
$taskAttachedHere = $false
$taskSelectedBus = ''

function Get-BrutalUsbBridge {
    if (Test-Path -LiteralPath $taskUsb -PathType Leaf) { return }
    $taskDownloadDir = Join-Path ([IO.Path]::GetTempPath()) ('BrutalOP25-usb-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $taskDownloadDir | Out-Null
    try {
        $taskMsi = Join-Path $taskDownloadDir 'usbipd-win_5.3.0_x64.msi'
        Write-Host 'Installing the Windows USB bridge from its official signed release. Administrator approval is required.'
        Invoke-WebRequest -UseBasicParsing 'https://github.com/dorssel/usbipd-win/releases/download/v5.3.0/usbipd-win_5.3.0_x64.msi' -OutFile $taskMsi
        if ((Get-FileHash -LiteralPath $taskMsi -Algorithm SHA256).Hash -ne '1c984914aec944de19b64eff232421439629699f8138e3ddc29301175bc6d938') {
            throw 'USB bridge package checksum did not match the vetted release. Nothing was installed.'
        }
        $taskSignature = Get-AuthenticodeSignature -LiteralPath $taskMsi
        if ($taskSignature.Status -ne 'Valid' -or $taskSignature.SignerCertificate.Subject -notmatch 'Frans van Dorsselaer') {
            throw 'USB bridge installer signature was not valid. Nothing was installed.'
        }
        $taskProcess = Start-Process msiexec.exe -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ArgumentList @('/i',('"'+$taskMsi+'"'),'/qn','/norestart')
        if ($taskProcess.ExitCode -eq 3010) { throw 'The USB bridge installed but Windows needs a restart. Relaunch afterward.' }
        if ($taskProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $taskUsb -PathType Leaf)) {
            throw 'USB bridge installation failed or administrator approval was declined.'
        }
    } finally {
        if (Test-Path -LiteralPath $taskDownloadDir -PathType Container) {
            try { Remove-Item -LiteralPath $taskDownloadDir -Recurse -Force }
            catch { Write-Warning "Temporary USB installer could not be removed: $taskDownloadDir" }
        }
    }
}

try {
    if ($Mode -eq 'detach') {
        if ($BusId -notmatch '^[0-9]+-[0-9]+(\.[0-9]+)*$') { throw 'Invalid USB bus ID for detach.' }
        if (-not (Test-Path -LiteralPath $taskUsb -PathType Leaf)) { throw 'USB bridge is missing; cannot detach this radio.' }
        & $taskUsb detach --busid $BusId
        if ($LASTEXITCODE -ne 0) { throw "Could not return USB bus $BusId to Windows." }
        Write-Host 'Radio returned to Windows.'
        exit 0
    }
    $taskExpected = if ($Profile -eq 'rspdxr2') { 'SDRplay RSPdx-R2 (1DF7:3060)' } else { 'RTL-SDR (0BDA:2832 or 0BDA:2838)' }
    $taskPattern = if ($Profile -eq 'rspdxr2') { '^USB\\VID_1DF7&PID_3060\\[A-Za-z0-9_-]+$' } else { '^USB\\VID_0BDA&PID_283[28]\\[A-Za-z0-9_-]+$' }
    $taskPnp = @(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match $taskPattern })
    if (-not $taskPnp.Count -and -not (Test-Path -LiteralPath $taskUsb -PathType Leaf)) {
        throw "Selected radio not detected: $taskExpected. Plug it in before installing the Windows USB bridge."
    }
    Get-BrutalUsbBridge
    $taskStateText = & $taskUsb state
    if ($LASTEXITCODE -ne 0) { throw 'The Windows USB bridge could not list connected devices.' }
    $taskBridge = @((($taskStateText | ConvertFrom-Json).Devices) | Where-Object { $_.BusId -and $_.InstanceId -match $taskPattern })
    $taskCandidates = @($taskPnp) + @($taskBridge)
    $taskSeen = @{}
    $taskRadios = @()
    foreach ($taskCandidate in $taskCandidates) {
        if ($taskSeen.ContainsKey($taskCandidate.InstanceId)) { continue }
        $taskSeen[$taskCandidate.InstanceId] = $true
        $taskRadios += $taskCandidate.InstanceId
    }
    if (-not $taskRadios.Count) {
        throw "Selected radio not detected: $taskExpected. Plug it in, check its USB cable/port, and close any Windows SDR app using it."
    }
    for ($taskIndex = 0; $taskIndex -lt $taskRadios.Count; $taskIndex++) {
        Write-Host ('{0}. {1} - serial {2}' -f ($taskIndex+1),$taskExpected,$taskRadios[$taskIndex].Split('\')[-1])
    }
    $taskChoice = if ($taskRadios.Count -eq 1) { '1' } else { Read-Host 'Choose the radio number (q cancels)' }
    if ($taskChoice -eq 'q') { throw 'Radio connection cancelled. Your saved systems were not changed.' }
    if ($taskChoice -notmatch '^[0-9]+$' -or [int]$taskChoice -lt 1 -or [int]$taskChoice -gt $taskRadios.Count) {
        throw 'Choose one of the listed radio numbers.'
    }
    $taskIdentity = $taskRadios[[int]$taskChoice-1]
    $taskMatch = @($taskBridge | Where-Object { $_.InstanceId -eq $taskIdentity })
    if ($taskMatch.Count -ne 1 -or $taskMatch[0].BusId -notmatch '^[0-9]+-[0-9]+(\.[0-9]+)*$') {
        throw 'Windows sees the radio but the USB bridge cannot identify its unique live bus. Reconnect it and retry.'
    }
    $taskSelectedBus = $taskMatch[0].BusId
    if (-not $taskMatch[0].PersistedGuid) {
        Write-Host 'Sharing only this radio with WSL. Approve the Windows administrator prompt.'
        $taskProcess = Start-Process $taskUsb -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ArgumentList @('bind','--busid',$taskSelectedBus)
        if ($taskProcess.ExitCode -ne 0) { throw 'USB sharing was declined or failed. No radio was attached.' }
    }
    if (-not $taskMatch[0].ClientIPAddress) {
        Write-Host 'Connecting this radio to Ubuntu WSL. Windows SDR apps cannot use it during this session.'
        & $taskUsb attach --wsl --busid $taskSelectedBus
        if ($LASTEXITCODE -ne 0) { throw 'USB forwarding to WSL failed. Check the bridge message above.' }
        $taskAttachedHere = $true
    } else {
        Write-Host 'This radio is already forwarded to WSL. Its existing connection will be left in place.'
    }
    $taskSerial = $taskIdentity.Split('\')[-1]
    if ($taskSerial -notmatch '^[A-Za-z0-9_-]+$') { throw 'The selected radio serial is not safe to use for Linux verification.' }
    $taskAttachedFlag = if ($taskAttachedHere) { '1' } else { '0' }
    Write-Output "BRUTAL_USB=$taskSelectedBus|$taskSerial|$taskAttachedFlag"
} catch {
    if ($taskAttachedHere -and $taskSelectedBus -match '^[0-9]+-[0-9]+(\.[0-9]+)*$') {
        & $taskUsb detach --busid $taskSelectedBus 2>$null | Out-Null
    }
    Write-Host ('USB setup needs attention: ' + $_.Exception.Message) -ForegroundColor Yellow
    exit 1
}
