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
$LocalEnvironment = @{
    WEB_ORIGIN = 'http://localhost:3000'
    SESSION_COOKIE_SECURE = 'false'
    CORS_ORIGINS = 'http://localhost:3000'
    REALTIME_ALLOWED_ORIGINS = 'http://localhost:3000'
}
$SavedEnvironment = @{}
Push-Location -LiteralPath $ProjectRoot
try {
    foreach ($VariableName in $LocalEnvironment.Keys) {
        $SavedEnvironment[$VariableName] = [Environment]::GetEnvironmentVariable($VariableName, 'Process')
        [Environment]::SetEnvironmentVariable($VariableName, $LocalEnvironment[$VariableName], 'Process')
    }
    Write-Host "Local frontend: $($LocalEnvironment.WEB_ORIGIN)"
    & $ApiPython @ApiArguments
    $ApiExitCode = $LASTEXITCODE
}
finally {
    foreach ($VariableName in $SavedEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($VariableName, $SavedEnvironment[$VariableName], 'Process')
    }
    Pop-Location
}
exit $ApiExitCode
