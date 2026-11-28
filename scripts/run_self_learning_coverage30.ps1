<#
.SYNOPSIS
Run the fixed coverage subset of 30 M1 scenarios through the existing two-round runner.
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
$selectionPath = Join-Path $repoRoot 'dataset/transcript/selections/self_learning_coverage30.json'
$selection = Get-Content -LiteralPath $selectionPath -Raw -Encoding utf8 | ConvertFrom-Json
if ($selection.schema_version -ne 2) { throw 'Unsupported coverage selection version.' }
$entries = @($selection.scenarios)
$ids = @($entries | ForEach-Object { [string]$_.scenario_id })
if ($ids.Count -ne 30 -or @($ids | Select-Object -Unique).Count -ne 30) {
    throw 'Coverage selection must contain exactly 30 unique scenarios.'
}
if (@($entries.source_file | Select-Object -Unique).Count -ne 30) {
    throw 'Coverage selection must contain exactly 30 unique source files.'
}
$scenarioDir = Join-Path $repoRoot $selection.source_directory
foreach ($entry in $entries) {
    $sid = [string]$entry.scenario_id
    if ($sid -notmatch '^SC-\d{3}$') { throw "Invalid scenario ID: $sid" }
    $sourceFile = [string]$entry.source_file
    if ($sourceFile -notmatch '^SC-\d{3}\.json$') { throw "Invalid scenario source file: $sourceFile" }
    $sourcePath = Join-Path $scenarioDir $sourceFile
    $actualHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -ne [string]$entry.source_sha256) {
        throw "Dataset changed for $sid. Review and update the selection before starting a new experiment."
    }
    $scenario = Get-Content -LiteralPath $sourcePath -Raw -Encoding utf8 | ConvertFrom-Json
    if ([string]$scenario.scenario_id -ne $sid) {
        throw "Scenario ID mismatch: $sourceFile contains $($scenario.scenario_id), expected $sid."
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
$summary = $selection.summary
Write-Output ("Fixed coverage selection: {0} SC, {1} personas, {2} hard-case labels including standard." -f `
    $summary.scenario_count, $summary.persona_count, $summary.hard_case_label_count_including_standard)
Write-Output ("{0} sessions / {1} customer turns per round; both rounds: {2} sessions / {3} customer turns." -f `
    $summary.sessions_per_round, $summary.customer_turns_per_round, `
    (2 * $summary.sessions_per_round), (2 * $summary.customer_turns_per_round))
try {
    & (Join-Path $PSScriptRoot 'run_self_learning_parallel_two_rounds.ps1') @options
} finally {
    if (-not $List -and (Test-Path -LiteralPath $OutputDir -PathType Container)) {
        Copy-Item -LiteralPath $selectionPath -Destination (Join-Path $OutputDir 'coverage_selection.json')
    }
}
