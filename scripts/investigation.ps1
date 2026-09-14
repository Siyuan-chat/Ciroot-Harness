[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidateSet('doctor','plan-validate','start','tasks','submit','work','resume','status','result','report')][string]$Command,
  [Parameter(Mandatory=$true)][string]$Workspace,
  [string]$Spec, [string]$Runtime, [string]$Scenario, [string]$RunId,
  [string]$TaskId, [string]$Result, [int]$TaskVersion, [string]$Languages='zh,en,ja'
)
$ErrorActionPreference='Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.local\d19-runtime\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }
$argsList = @('-m','research_harness.investigation_cli','--workspace',$Workspace,$Command)
if ($Command -eq 'plan-validate') { $argsList += @('--plan',$Spec) }
if ($Command -eq 'start') { $argsList += @('--spec',$Spec,'--runtime',$Runtime); if ($Scenario) {$argsList += @('--scenario',$Scenario)} }
if ($Command -in @('tasks','work','resume','result','report')) { $argsList += $RunId }
if ($Command -eq 'submit') { $argsList += @($RunId,$TaskId,'--result',$Result,'--task-version',$TaskVersion) }
if ($Command -eq 'report') { $argsList += @('--languages',$Languages) }
$env:PYTHONPATH = Join-Path $root 'src'
& $python @argsList
exit $LASTEXITCODE
