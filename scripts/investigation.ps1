[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][ValidateSet('doctor','plan-validate','start','tasks','submit','work','resume','status','result','report','profile-update')][string]$Command,
  [Parameter(Mandatory=$true)][string]$Workspace,
  [string]$PythonExecutable='python',
  [string]$Spec, [string]$Runtime, [string]$Scenario, [string]$RunId, [Alias("MonitorId")][string]$ProfileMonitorId, [string]$Profile,
  [string]$TaskId, [string]$Result, [int]$TaskVersion, [string]$Languages, [switch]$Monitor
)
$ErrorActionPreference='Stop'
$python = $PythonExecutable
if ($Monitor) { $argsList = @('-m','research_harness.investigation_cli','monitor','--workspace',$Workspace,$Command) } else { $argsList = @('-m','research_harness.investigation_cli','--workspace',$Workspace,$Command) }
if ($Command -eq 'plan-validate') { $argsList += @('--plan',$Spec) }
if ($Command -eq 'start') { $argsList += @('--spec',$Spec,'--runtime',$Runtime); if ($Scenario) {$argsList += @('--scenario',$Scenario)} }
if ($Command -in @('tasks','work','resume','result','report','status') -and $RunId) { $argsList += $RunId }
if ($Command -eq 'submit') { $argsList += @($RunId,$TaskId,'--result',$Result,'--task-version',$TaskVersion) }
if ($Command -eq 'report' -and $Languages) { $argsList += @('--languages',$Languages) }
if ($Command -eq 'profile-update') { $monitorId = if ($ProfileMonitorId) { $ProfileMonitorId } else { $RunId }; $argsList += @($monitorId,'--profile',$Profile) }
& $python @argsList
exit $LASTEXITCODE
