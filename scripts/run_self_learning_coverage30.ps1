<#
.SYNOPSIS
Run the fixed coverage subset of 30 main scenarios through the existing two-round runner.
.DESCRIPTION
Validates the selection and source hashes before any LLM/DB work. -List is offline.
No changes to learning, end-session timing, routing, judge or runtime isolation.
#>
param(
    [string]$PythonExe = 'python',
    [ValidateRange(1,2)][int]$Workers = 2,
    [string]$OutputDir = '',
    [switch]$Judge,
    [switch]$Strict,
    [switch]$List
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$selectionPath = Join-Path $repoRoot 'dataset/main/selections/self_learning_coverage30.json'
$selection = Get-Content -LiteralPath $selectionPath -Raw -Encoding utf8 | ConvertFrom-Json
if ($selection.schema_version -ne 1) { throw 'Unsupported coverage selection version.' }
$entries = @($selection.scenarios)
$ids = @($entries | ForEach-Object { [string]$_.scenario_id })
if ($ids.Count -ne 30 -or @($ids | Select-Object -Unique).Count -ne 30) {
    throw 'Coverage selection must contain exactly 30 unique scenarios.'
}
$scenarioDir = Join-Path $repoRoot $selection.source_directory
foreach ($entry in $entries) {
    $sid = [string]$entry.scenario_id
    if ($sid -notmatch '^SC-(\d{3})$') { throw "Invalid scenario ID: $sid" }
    $number = [int]$Matches[1]
    if ($number -lt 1 -or $number -gt 120) { throw "Scenario outside SC-001 through SC-120: $sid" }
    $sourcePath = Join-Path $scenarioDir ($sid + '.json')
    $actualHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne [string]$entry.source_sha256) {
        throw "Dataset changed for $sid. Review and update the selection before starting a new experiment."
    }
}
if (-not $OutputDir) {
    $OutputDir = Join-Path $repoRoot ('outputs/self-agent/coverage30/' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
}
if (-not $List -and (Test-Path -LiteralPath $OutputDir)) {
    throw 'Output directory already exists; choose a new directory to preserve earlier runs.'
}
$options = @{
    PythonExe = $PythonExe
    ScenarioDir = $scenarioDir
    ScenarioId = $ids
    Workers = $Workers
    OutputDir = $OutputDir
}
if ($Judge) { $options.Judge = $true }
if ($Strict) { $options.Strict = $true }
if ($List) { $options.List = $true }
Write-Output 'Fixed coverage selection: 30 SC, 12 personas, 13 hard-case labels including standard.'
Write-Output '63 sessions / 202 customer turns per round; both rounds: 126 sessions / 404 customer turns.'
try {
    & (Join-Path $PSScriptRoot 'run_self_learning_parallel_two_rounds.ps1') @options
} finally {
    if (-not $List -and (Test-Path -LiteralPath $OutputDir -PathType Container)) {
        Copy-Item -LiteralPath $selectionPath -Destination (Join-Path $OutputDir 'coverage_selection.json')
    }
}
