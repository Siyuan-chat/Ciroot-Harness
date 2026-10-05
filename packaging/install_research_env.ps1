#requires -Version 7.0
param(
    [Parameter(Mandatory = $true)][ValidateSet('paperqa', 'storm')][string]$Profile,
    [Parameter(Mandatory = $true)][string]$BasePython,
    [Parameter(Mandatory = $true)][string]$CoreLockFile,
    [Parameter(Mandatory = $true)][string]$LockFile,
    [string]$CoreWheel,
    [string]$CoreSource,
    [string]$EnvironmentPath,
    [string]$ConfigPath
)
$ErrorActionPreference = 'Stop'

foreach ($path in @($BasePython, $CoreLockFile, $LockFile)) {
    if (-not [System.IO.Path]::IsPathFullyQualified($path)) { throw "Path must be absolute: $path" }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "File does not exist: $path" }
}
$BasePython = (Resolve-Path -LiteralPath $BasePython).Path
$CoreLockFile = (Resolve-Path -LiteralPath $CoreLockFile).Path
$LockFile = (Resolve-Path -LiteralPath $LockFile).Path
$lockParser = Join-Path $PSScriptRoot 'validate_locked_requirements.py'
if (-not (Test-Path -LiteralPath $lockParser -PathType Leaf)) { throw "Lock validator is missing: $lockParser" }
if ([bool]$CoreWheel -eq [bool]$CoreSource) { throw 'Specify exactly one of CoreWheel or CoreSource' }
if ($CoreWheel) {
    if (-not [System.IO.Path]::IsPathFullyQualified($CoreWheel) -or -not (Test-Path -LiteralPath $CoreWheel -PathType Leaf)) { throw 'CoreWheel must be an existing absolute wheel path' }
    $CoreWheel = (Resolve-Path -LiteralPath $CoreWheel).Path
}
if ($CoreSource) {
    if (-not [System.IO.Path]::IsPathFullyQualified($CoreSource) -or -not (Test-Path -LiteralPath $CoreSource -PathType Container) -or -not (Test-Path -LiteralPath (Join-Path $CoreSource 'pyproject.toml') -PathType Leaf)) { throw 'CoreSource must be an absolute project root containing pyproject.toml' }
    $CoreSource = (Resolve-Path -LiteralPath $CoreSource).Path
}
$environmentPathExplicit = -not [string]::IsNullOrWhiteSpace($EnvironmentPath)
if (-not $EnvironmentPath) { $EnvironmentPath = Join-Path (Split-Path -Parent $PSScriptRoot) ".local\research-envs\$Profile" }
if (-not [System.IO.Path]::IsPathFullyQualified($EnvironmentPath)) { throw 'EnvironmentPath must be absolute' }
$EnvironmentPath = [System.IO.Path]::GetFullPath($EnvironmentPath)
if (-not $ConfigPath) { $ConfigPath = Join-Path (Split-Path -Parent $PSScriptRoot) ".local\research-envs\$Profile.json" }
if (-not [System.IO.Path]::IsPathFullyQualified($ConfigPath)) { throw 'ConfigPath must be absolute' }
$ConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)
if (Test-Path -LiteralPath $ConfigPath) {
    throw "Refusing to overwrite an existing runtime configuration; choose a new ConfigPath: $ConfigPath"
}

function Read-LockedPins([string]$path) {
    $pins = @{}
    $parsed = & $BasePython $lockParser $path
    if ($LASTEXITCODE -ne 0) { throw "Lock file is invalid for this Python platform: $path" }
    $parsedPins = $parsed | ConvertFrom-Json
    foreach ($property in $parsedPins.PSObject.Properties) {
        $pins[$property.Name] = [string]$property.Value
    }
    return $pins
}
$corePins = Read-LockedPins $CoreLockFile
$enginePins = Read-LockedPins $LockFile
foreach ($name in $enginePins.Keys) {
    if ($corePins.ContainsKey($name) -and $corePins[$name] -ne $enginePins[$name]) {
        throw "Core and $Profile locks conflict for $name`: core=$($corePins[$name]), engine=$($enginePins[$name])"
    }
}

if ((Test-Path -LiteralPath $EnvironmentPath) -and -not $environmentPathExplicit) {
    throw "Refusing to modify an existing default research environment without an explicit EnvironmentPath: $EnvironmentPath"
}
New-Item -ItemType Directory -Path (Split-Path -Parent $EnvironmentPath) -Force | Out-Null
if (-not (Test-Path -LiteralPath $EnvironmentPath)) {
    & $BasePython -m venv $EnvironmentPath
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed with exit code $LASTEXITCODE" }
}
$venvPython = Join-Path $EnvironmentPath 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) { throw "venv Python is unavailable: $venvPython" }
& $venvPython -m pip install --disable-pip-version-check -r $CoreLockFile
if ($LASTEXITCODE -ne 0) { throw "core dependency installation failed with exit code $LASTEXITCODE" }
$corePackageHash = if ($CoreWheel) { (Get-FileHash -LiteralPath $CoreWheel -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null }
if ($CoreWheel) {
    & $venvPython -m pip install --disable-pip-version-check --force-reinstall --no-deps $CoreWheel
} else {
    & $venvPython -m pip install --disable-pip-version-check --force-reinstall --no-deps --no-build-isolation $CoreSource
}
if ($LASTEXITCODE -ne 0) { throw "core package installation failed with exit code $LASTEXITCODE" }
& $venvPython -m pip install --disable-pip-version-check -r $LockFile
if ($LASTEXITCODE -ne 0) { throw "locked dependency installation failed with exit code $LASTEXITCODE" }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw "installed environment has inconsistent dependencies: $LASTEXITCODE" }

$coreVerifier = Join-Path $PSScriptRoot 'verify_installed_core.py'
if (-not (Test-Path -LiteralPath $coreVerifier -PathType Leaf)) { throw "Core wheel verifier is missing: $coreVerifier" }
$wheelArgument = if ($CoreWheel) { $CoreWheel } else { '' }
$expectedWheelHash = if ($corePackageHash) { $corePackageHash } else { '' }
$coreMetadataJson = & $venvPython $coreVerifier $wheelArgument $expectedWheelHash
if ($LASTEXITCODE -ne 0) { throw "installed core package does not match selected package artifact: $LASTEXITCODE" }
$coreMetadata = $coreMetadataJson | ConvertFrom-Json
$coreVersion = $coreMetadata.version
$coreImportPath = $coreMetadata.import_path
$workerModule = "research_harness.engines.${Profile}_worker"
$workerMetadataJson = & $venvPython -c "import importlib, json, pathlib, sys; m=importlib.import_module('$workerModule'); p=pathlib.Path(m.__file__).resolve(); p.relative_to(pathlib.Path(sys.prefix).resolve()); print(json.dumps({'module':'$workerModule','import_path':str(p)}))"
if ($LASTEXITCODE -ne 0) { throw "installed $Profile worker could not be imported from the selected environment: $LASTEXITCODE" }
$workerMetadata = $workerMetadataJson | ConvertFrom-Json
$hash = (Get-FileHash -LiteralPath $LockFile -Algorithm SHA256).Hash.ToLowerInvariant()
$coreLockHash = (Get-FileHash -LiteralPath $CoreLockFile -Algorithm SHA256).Hash.ToLowerInvariant()
$config = [ordered]@{
    schema_version = '1'
    research_engine = [ordered]@{
        python_executable = [System.IO.Path]::GetFullPath($venvPython)
    }
    installation = [ordered]@{
        profile = $Profile
        base_python = $BasePython
        core_package_source = $(if ($CoreWheel) { $CoreWheel } else { $CoreSource })
        core_package_version = $coreVersion
        core_package_sha256 = $corePackageHash
        core_package_import_path = $coreImportPath
        verified_core_wheel_sha256 = $coreMetadata.verified_wheel_sha256
        verified_core_module_count = $coreMetadata.verified_module_count
        worker_module = $workerMetadata.module
        worker_import_path = $workerMetadata.import_path
        core_lock_file = $CoreLockFile
        core_lock_sha256 = $coreLockHash
        lock_file = $LockFile
        lock_sha256 = $hash
        research_calls_enabled = $false
        setup_only = $true
    }
}
New-Item -ItemType Directory -Path (Split-Path -Parent $ConfigPath) -Force | Out-Null
$config | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $ConfigPath -Encoding utf8
Write-Output (ConvertTo-Json -InputObject $config -Depth 4 -Compress)
