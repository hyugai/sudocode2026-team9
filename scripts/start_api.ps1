# Run from any working directory using this project's Python environment.
[CmdletBinding()]
param(
    [string]$BindAddress = '127.0.0.1',
    [ValidateRange(1, 65535)]
    [int]$Port = 8000,
    [switch]$Reload
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ApiPython = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $ApiPython -PathType Leaf)) {
    throw "Project Python not found: $ApiPython. Create and install the project's .venv first."
}

$ApiArguments = @(
    '-X', 'utf8', '-m', 'uvicorn',
    'telesale_agent.entrypoints.api.chat:app',
    '--app-dir', 'src', '--host', $BindAddress, '--port', "$Port"
)
if ($Reload) {
    $ApiArguments += '--reload'
}

Write-Host "Backend Python: $ApiPython"
Push-Location -LiteralPath $ProjectRoot
try {
    & $ApiPython @ApiArguments
    $ApiExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $ApiExitCode
