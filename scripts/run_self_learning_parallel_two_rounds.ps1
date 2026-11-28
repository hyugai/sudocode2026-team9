<#
.SYNOPSIS
Run a frozen self-learning experiment over the first N main scenarios, two workers by default.
#>
param(
    [string]$PythonExe = 'python',
    [string]$ScenarioDir = '',
    [string[]]$ScenarioId = @(),
    [ValidateRange(1,10000)][int]$Limit = 60,
    [ValidateRange(1,2)][int]$Workers = 2,
    [string]$OutputDir = '',
    [switch]$Judge,
    [switch]$AllowNoLessons,
    [switch]$Strict,
    [switch]$List
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $ScenarioDir) { $ScenarioDir = Join-Path $repoRoot 'dataset/transcript/M1' }
if (-not $OutputDir) { $OutputDir = Join-Path $repoRoot ('outputs/self-agent/parallel-two-rounds/' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
$savedPath = $env:PYTHONPATH
$savedFlag = $env:KNOWLEDGE_GAP_LOOP_ENABLED
try {
    $env:PYTHONPATH = Join-Path $repoRoot 'src'
    if ($savedPath) { $env:PYTHONPATH += [IO.Path]::PathSeparator + $savedPath }
    $env:KNOWLEDGE_GAP_LOOP_ENABLED = 'true'
    $runnerArgs = @('-m','self_agent.parallel_two_rounds','--scenarios',$ScenarioDir,
        '--limit',"$Limit",'--workers',"$Workers",'--output',$OutputDir)
    foreach ($id in $ScenarioId) { $runnerArgs += @('--scenario-id',$id) }
    if ($Judge) { $runnerArgs += '--judge' }
    if ($AllowNoLessons) { $runnerArgs += '--allow-no-lessons' }
    if ($Strict) { $runnerArgs += '--strict' }
    if ($List) { $runnerArgs += '--list' }
    & $PythonExe @runnerArgs
    if ($LASTEXITCODE -ne 0) { throw "Experiment stopped; inspect $OutputDir/summary.json and worker console.log files." }
} finally {
    $env:PYTHONPATH = $savedPath
    $env:KNOWLEDGE_GAP_LOOP_ENABLED = $savedFlag
}
