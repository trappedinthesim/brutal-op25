# Runs generate_logo_options.py with your OpenAI key read from a file you choose.
# The key is held in this process only for the run and removed afterwards; it is never printed or saved.
#   .\tools\make-logos.ps1 -KeyFile C:\path\to\openai-key.txt
param([Parameter(Mandatory)][string]$KeyFile)
$ErrorActionPreference = 'Stop'
$key = (Get-Content -Raw -LiteralPath $KeyFile).Trim()
if (-not $key) { throw 'The key file is empty.' }
$env:OPENAI_API_KEY = $key
$key = $null
try {
    Push-Location (Split-Path -Parent $PSScriptRoot)
    py -m tools.generate_logo_options
} finally {
    Pop-Location
    Remove-Item Env:OPENAI_API_KEY -ErrorAction SilentlyContinue
}
