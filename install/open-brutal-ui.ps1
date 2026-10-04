param(
    [int]$ParentProcessId = 0,
    [switch]$ProbeOnly
)

$taskDashboardUrl = 'http://127.0.0.1:8080/'

function Test-BrutalDashboard {
    try {
        $taskResponse = Invoke-WebRequest -Uri $taskDashboardUrl -TimeoutSec 2 -UseBasicParsing
        return ($taskResponse.StatusCode -eq 200 -and $taskResponse.Content -match '(?is)<title>\s*Brutal OP25\b')
    } catch {
        return $false
    }
}

if ($ProbeOnly) {
    if (Test-BrutalDashboard) {
        Write-Output $taskDashboardUrl
        exit 0
    }
    exit 1
}

# The launcher owns this short-lived helper. Do not open an older receiver's
# dashboard if port 8080 was already occupied before this session began.
if (Test-BrutalDashboard) { exit 0 }
for ($taskAttempt = 0; $taskAttempt -lt 7200; $taskAttempt++) {
    if ($ParentProcessId -gt 0 -and -not (Get-Process -Id $ParentProcessId -ErrorAction SilentlyContinue)) { exit 0 }
    if (Test-BrutalDashboard) {
        Start-Process -FilePath $taskDashboardUrl
        exit 0
    }
    Start-Sleep -Seconds 1
}
