<#
.SYNOPSIS
Run the same changed scenarios with clean RAM in rounds 0 and 1; optionally score with the configured LLM.
#>
param(
    [string]$PythonExe = 'python',
    [string[]]$ScenarioId = @('SC-121', 'SC-123'),
    [string]$ScenarioDir = '',
    [string]$OutputDir = '',
    [switch]$Judge
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $ScenarioDir) { $ScenarioDir = Join-Path $repoRoot 'dataset/main/m2_transcripts/scenarios_complete' }
if (-not $OutputDir) { $OutputDir = Join-Path $repoRoot ('outputs/self-agent/two-rounds/' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
if (Test-Path -LiteralPath $OutputDir) { throw 'Choose a new output directory to preserve the previous experiment.' }
$oldPath = $env:PYTHONPATH
$oldFlag = $env:KNOWLEDGE_GAP_LOOP_ENABLED
try {
    $env:PYTHONPATH = (Join-Path $repoRoot 'src')
    if ($oldPath) { $env:PYTHONPATH += [IO.Path]::PathSeparator + $oldPath }
    $env:KNOWLEDGE_GAP_LOOP_ENABLED = 'true'
    $round0 = Join-Path $OutputDir 'round0'
    $round1 = Join-Path $OutputDir 'round1'
    # Fresh learning memory per experiment. Existing runs are never deleted or read as lessons.
    $memory = Join-Path $OutputDir 'learning-memory'
    Write-Output "Fresh experiment memory: $memory"
    $common = @('-m', 'self_agent.scenario_runner', '--scenarios', $ScenarioDir, '--limit', '0')
    foreach ($id in $ScenarioId) { $common += @('--scenario-id', $id) }
    $v0 = $common + @('--round', '0', '--output', $round0, '--learning-root', $memory, '--runtime-root', (Join-Path $round0 'runtime'))
    & $PythonExe @v0
    if ($LASTEXITCODE -ne 0) { throw 'Round 0 failed; inspect its reports. Round 1 was not started.' }
    $v1 = $common + @('--round', '1', '--baseline', $round0, '--learning-root', $memory,
                      '--output', $round1, '--runtime-root', (Join-Path $round1 'runtime'))
    & $PythonExe @v1
    if ($LASTEXITCODE -ne 0) { throw 'Round 1 failed; inspect its reports.' }
    if ($Judge) {
        & $PythonExe -m self_agent.evaluation.compare_scenario_rounds --round0 $round0 --round1 $round1 --scenarios $ScenarioDir --output (Join-Path $OutputDir 'comparison.json')
        if ($LASTEXITCODE -ne 0) { throw 'Evaluation failed; dialogue reports were preserved.' }
    }
    Write-Output "Results: $OutputDir"
} finally {
    $env:PYTHONPATH = $oldPath
    $env:KNOWLEDGE_GAP_LOOP_ENABLED = $oldFlag
}
