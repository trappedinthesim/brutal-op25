# Read-only dashboard checks. Does not launch a browser or a receiver.
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskTokens = $null; $taskErrors = $null
$taskAst = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $taskRoot 'install/open-brutal-ui.ps1'),[ref]$taskTokens,[ref]$taskErrors)
if ($taskErrors.Count) { throw $taskErrors[0].Message }
$taskDefinition = $taskAst.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-BrutalDashboard'},$true)
if (-not $taskDefinition) { throw 'Dashboard readiness function is missing.' }
. ([scriptblock]::Create($taskDefinition.Extent.Text))
$taskDashboardUrl = 'http://127.0.0.1:8080/'

function Invoke-WebRequest {
    param([string]$Uri,[int]$TimeoutSec,[switch]$UseBasicParsing)
    if ($Uri -ne 'http://127.0.0.1:8080/' -or $TimeoutSec -ne 2) { throw 'Unexpected dashboard probe.' }
    return [pscustomobject]@{StatusCode=200;Content='<title>Brutal OP25 // Live Receiver</title>'}
}
if (-not (Test-BrutalDashboard)) { throw 'Ready dashboard was not recognized.' }

function Invoke-WebRequest {
    param([string]$Uri,[int]$TimeoutSec,[switch]$UseBasicParsing)
    return [pscustomobject]@{StatusCode=200;Content='<title>Brutal OP25 // Systems</title>'}
}
if (-not (Test-BrutalDashboard)) { throw 'Empty-library Systems dashboard was not recognized.' }

function Invoke-WebRequest {
    param([string]$Uri,[int]$TimeoutSec,[switch]$UseBasicParsing)
    return [pscustomobject]@{StatusCode=200;Content='<title>Unrelated local service</title>'}
}
if (Test-BrutalDashboard) { throw 'Unrelated local service was accepted as the dashboard.' }

function Invoke-WebRequest { throw 'Connection refused' }
if (Test-BrutalDashboard) { throw 'Unreachable dashboard was accepted.' }
Write-Host 'PASS: dashboard readiness, wrong-page rejection, and unavailable-port fallback'
