param(
    [ValidateSet('check-api','start','stop')][string]$Mode = 'start',
    [string]$Address = '',
    [int]$ServerProcessId = 0,
    [switch]$LicenseAccepted
)
$ErrorActionPreference = 'Stop'
# PowerShell launched through WSL may not auto-load Windows modules.
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop
if ($Mode -eq 'start') {
    Import-Module NetTCPIP, PnpDevice -ErrorAction Stop
} elseif ($Mode -eq 'stop') {
    Import-Module CimCmdlets -ErrorAction Stop
}
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskServer = Join-Path $PSScriptRoot 'vendor\rsp-tcp\rsp_tcp.exe'
$taskApi = Join-Path $env:ProgramFiles 'SDRplay\API\x64\sdrplay_api.dll'
$taskApiService = 'SDRplayAPIService'
$taskExpectedServerHash = '93F007D74AAFFBF8B7F1EBC05402B09F6CB424E39BE612A1DE19EC13559028CD'
$taskExpectedInstallerHash = '8AD5C36F1CA26CF7A61010C3F3C80DAE69D4468EF5E59F7A0D42FB135A1C7326'
$taskUsb = Join-Path $env:ProgramFiles 'usbipd-win\usbipd.exe'

function Test-BrutalWindowsApi {
    return ((Test-Path -LiteralPath $taskApi -PathType Leaf) -and
            $null -ne (Get-Service -Name $taskApiService -ErrorAction SilentlyContinue))
}

function Install-BrutalWindowsApi {
    if (-not $LicenseAccepted) {
        throw 'The SDRplay driver license must be reviewed and accepted before installing its Windows API.'
    }
    $taskTemp = Join-Path ([IO.Path]::GetTempPath()) ('BrutalOP25-rsp-api-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $taskTemp | Out-Null
    try {
        $taskInstaller = Join-Path $taskTemp 'SDRplay-API-Windows.exe'
        Write-Host 'Downloading the official SDRplay Windows API. Administrator approval may be requested.'
        Invoke-WebRequest -UseBasicParsing 'https://sdrplay.com/download/hardware-api-windows/?wpdmdl=1905' -OutFile $taskInstaller
        if ((Get-FileHash -LiteralPath $taskInstaller -Algorithm SHA256).Hash -ne $taskExpectedInstallerHash) {
            throw 'SDRplay changed its Windows API download. Nothing was installed; the project must review the new release.'
        }
        $taskSignature = Get-AuthenticodeSignature -LiteralPath $taskInstaller
        if ($taskSignature.Status -ne 'Valid' -or
            $taskSignature.SignerCertificate.Subject -notmatch 'SDRPLAY LIMITED') {
            throw 'The official SDRplay Windows API signature could not be verified.'
        }
        $taskProcess = Start-Process -FilePath $taskInstaller -Verb RunAs -WindowStyle Hidden -Wait -PassThru `
            -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-')
        if ($taskProcess.ExitCode -eq 3010) {
            throw 'The SDRplay API installed, but Windows needs a restart. Relaunch Brutal OP25 afterward.'
        }
        if ($taskProcess.ExitCode -ne 0 -or -not (Test-BrutalWindowsApi)) {
            throw 'SDRplay Windows API installation did not complete. Check the Windows approval prompt and retry.'
        }
    } finally {
        if (Test-Path -LiteralPath $taskTemp -PathType Container) {
            Remove-Item -LiteralPath $taskTemp -Recurse -Force
        }
    }
}

try {
    if ($Mode -eq 'check-api') {
        if (Test-BrutalWindowsApi) { exit 0 }
        exit 10
    }
    if ($Mode -eq 'stop') {
        if ($ServerProcessId -le 0) { throw 'A valid SDRplay server process ID is required.' }
        $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$ServerProcessId" -ErrorAction SilentlyContinue
        if ($taskProcess -and $taskProcess.ExecutablePath -and
            [IO.Path]::GetFullPath($taskProcess.ExecutablePath) -ieq [IO.Path]::GetFullPath($taskServer)) {
            Stop-Process -Id $ServerProcessId -ErrorAction Stop
        }
        foreach ($taskSuffix in @('.in','.out','.err')) {
            $taskLogFile = Join-Path ([IO.Path]::GetTempPath()) ('BrutalOP25-rsp-tcp' + $taskSuffix)
            Remove-Item -LiteralPath $taskLogFile -Force -ErrorAction SilentlyContinue
        }
        exit 0
    }
    if ($Address -notmatch '^\d{1,3}(?:\.\d{1,3}){3}$') { throw 'Invalid WSL host address.' }
    $taskIp = [Net.IPAddress]::Parse($Address)
    if ($taskIp.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) { throw 'Only the WSL IPv4 host address is supported.' }
    $taskInterface = @(Get-NetIPAddress -IPAddress $Address -ErrorAction SilentlyContinue |
        Where-Object { $_.InterfaceAlias -like 'vEthernet (WSL*' })
    if ($taskInterface.Count -ne 1) { throw 'The stream address is not this computer WSL virtual network interface.' }
    if (-not (Test-Path -LiteralPath $taskServer -PathType Leaf) -or
        (Get-FileHash -LiteralPath $taskServer -Algorithm SHA256).Hash -ne $taskExpectedServerHash) {
        throw 'The SDRplay sample server is missing or differs from the reviewed build. Reinstall Brutal OP25.'
    }
    if (-not (Test-BrutalWindowsApi)) { Install-BrutalWindowsApi }
    $taskService = Get-Service -Name $taskApiService
    if ($taskService.Status -ne 'Running') {
        Start-Service -Name $taskApiService
        $taskService.WaitForStatus('Running', [TimeSpan]::FromSeconds(10))
    }
    $taskPnpRadios = @(Get-PnpDevice -PresentOnly | Where-Object {
        $_.InstanceId -match '^USB\\VID_1DF7&PID_3060\\[A-Za-z0-9_-]+$'
    })
    if (-not $taskPnpRadios.Count) {
        throw 'No RSPdx-R2 is connected to Windows. Connect the radio, then retry.'
    }
    if ($taskPnpRadios.Count -ne 1) {
        throw 'More than one RSPdx-R2 is connected. Disconnect the others before starting.'
    }
    $taskBridgeState = if (Test-Path -LiteralPath $taskUsb -PathType Leaf) {
        (& $taskUsb state | ConvertFrom-Json).Devices
    } else { @() }
    $taskRadio = @($taskBridgeState | Where-Object { $_.InstanceId -eq $taskPnpRadios[0].InstanceId })
    if ($taskRadio.Count -gt 1) { throw 'The USB bridge returned conflicting identities for the SDRplay radio.' }
    $taskRadio = if ($taskRadio.Count) { $taskRadio[0] } else { $null }
    if ($taskRadio -and $taskRadio.BusId -notmatch '^[0-9]+-[0-9]+(\.[0-9]+)*$') {
        throw 'The selected SDRplay radio has no safe USB bus identity.'
    }
    if ($taskRadio -and $taskRadio.ClientIPAddress) {
        & $taskUsb detach --busid $taskRadio.BusId
        if ($LASTEXITCODE -ne 0) { throw 'Could not return the RSPdx-R2 from WSL to Windows.' }
    }
    if ($taskRadio -and $taskRadio.PersistedGuid) {
        Write-Host 'Returning only the RSPdx-R2 to its Windows driver. Approve the administrator prompt.'
        $taskUnbind = Start-Process -FilePath $taskUsb -Verb RunAs -WindowStyle Hidden -Wait -PassThru `
            -ArgumentList @('unbind','--busid',$taskRadio.BusId)
        if ($taskUnbind.ExitCode -ne 0) { throw 'The SDRplay radio could not be released from the WSL USB bridge.' }
    }
    $taskListener = [Net.Sockets.TcpListener]::new($taskIp, 1234)
    try { $taskListener.Start() }
    catch { throw 'The local SDRplay stream port 1234 is already in use. Close the other receiver and retry.' }
    finally { $taskListener.Stop() }
    $env:PATH = (Split-Path -Parent $taskApi) + ';' + $env:PATH
    $taskLogBase = Join-Path ([IO.Path]::GetTempPath()) 'BrutalOP25-rsp-tcp'
    $taskLog = $taskLogBase + '.err'
    $taskOutput = $taskLogBase + '.out'
    $taskInput = $taskLogBase + '.in'
    [IO.File]::WriteAllText($taskInput, '')
    $taskProcess = Start-Process -FilePath $taskServer -WindowStyle Hidden -PassThru `
        -RedirectStandardInput $taskInput -RedirectStandardOutput $taskOutput -RedirectStandardError $taskLog `
        -ArgumentList @('-a',$Address,'-p','1234','-P','0','-s','1000000')
    try {
        $taskConnected = $false
        for ($taskAttempt = 0; $taskAttempt -lt 30 -and -not $taskConnected; $taskAttempt++) {
            Start-Sleep -Milliseconds 250
            if ($taskProcess.HasExited) {
                $taskDetail = if (Test-Path -LiteralPath $taskLog) { (Get-Content -LiteralPath $taskLog -Tail 8) -join ' ' } else { '' }
                throw "The SDRplay sample server exited ($($taskProcess.ExitCode)). $taskDetail"
            }
            try {
                $taskClient = [Net.Sockets.TcpClient]::new()
                $taskClient.Connect($taskIp, 1234)
                $taskClient.ReceiveTimeout = 2000
                $taskHeader = New-Object byte[] 12
                $taskRead = $taskClient.GetStream().Read($taskHeader, 0, 12)
                if ($taskRead -eq 12 -and [Text.Encoding]::ASCII.GetString($taskHeader, 0, 4) -eq 'RTL0') {
                    $taskConnected = $true
                }
            } catch { Start-Sleep -Milliseconds 250 }
            finally { if ($taskClient) { $taskClient.Dispose(); $taskClient = $null } }
        }
        if (-not $taskConnected) { throw 'The Windows SDRplay server did not deliver a valid radio stream.' }
        Write-Host 'RSPdx-R2 is streaming from Windows to Linux. No USB forwarding is needed for this radio.'
        Write-Output "BRUTAL_RSP_TCP=$Address`:1234|$($taskProcess.Id)"
    } catch {
        if (-not $taskProcess.HasExited) { Stop-Process -Id $taskProcess.Id -ErrorAction SilentlyContinue }
        throw
    }
} catch {
    Write-Host ('SDRplay setup needs attention: ' + $_.Exception.Message) -ForegroundColor Yellow
    exit 1
}
