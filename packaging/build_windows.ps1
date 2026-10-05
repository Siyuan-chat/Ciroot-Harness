#requires -Version 7.0
param(
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$Python = '.local\gui-clean-venv\Scripts\python.exe'
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$root = (Get-Location).Path

if (-not [System.IO.Path]::IsPathFullyQualified($OutputRoot)) {
    throw 'OutputRoot must be a new absolute path. Existing portable packages are never overwritten.'
}
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $OutputRoot) {
    throw "OutputRoot already exists; choose a new isolated directory: $OutputRoot"
}
if (-not [System.IO.Path]::IsPathFullyQualified($Python)) {
    $Python = Join-Path $root $Python
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { throw "Build Python is missing: $Python" }
$Python = (Resolve-Path -LiteralPath $Python).Path
if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) { throw 'Run npm run build in frontend first.' }

$dist = Join-Path $OutputRoot 'dist'
$build = Join-Path $OutputRoot 'build'
$spec = Join-Path $OutputRoot 'spec'
New-Item -ItemType Directory -Path $OutputRoot -Force | Out-Null
& $Python -m PyInstaller --noconfirm --onedir --windowed --name ResearchHarnessGUI `
    --icon "$root\assets\ciroot-harness-icon.ico" `
    --paths src `
    --add-data "$root\frontend\dist;frontend\dist" `
    --add-data "$root\src\research_harness\schemas;research_harness\schemas" `
    --add-data "$root\src\research_harness\prompts;research_harness\prompts" `
    --add-data "$root\src\research_harness\gui\help;research_harness\gui\help" `
    --add-data "$root\src\research_harness\examples\investigation;research_harness\examples\investigation" `
    --collect-submodules research_harness `
    --collect-submodules langgraph `
    --collect-submodules uvicorn `
    --collect-all webview `
    --collect-all clr_loader `
    --collect-all fastembed `
    --collect-all qdrant_client `
    --collect-all pypdfium2 `
    --copy-metadata fastembed `
    --copy-metadata docling `
    --copy-metadata llama-index-core `
    --exclude-module paperqa `
    --exclude-module storm `
    --exclude-module knowledge_storm `
    --exclude-module dspy `
    --exclude-module torch `
    --exclude-module torchvision `
    --exclude-module transformers `
    --exclude-module docling `
    --exclude-module docling_core `
    --exclude-module docling_parse `
    --distpath $dist `
    --workpath $build `
    --specpath $spec `
    packaging\desktop_entry.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }

$buildEnvironmentPath = Join-Path $OutputRoot 'build-environment.json'
$buildEnvironmentScript = @'
import importlib.metadata, json, platform, sys
from pathlib import Path

packages = []
for dist in sorted(importlib.metadata.distributions(), key=lambda item: (item.metadata.get("Name") or "").casefold()):
    metadata = dist.metadata
    license_value = metadata.get("License-Expression")
    if not license_value:
        license_value = "; ".join(value.removeprefix("License :: ").replace(" :: ", " / ") for value in metadata.get_all("Classifier", []) if value.startswith("License :: "))
    if not license_value:
        license_value = (metadata.get("License") or "license metadata unavailable").splitlines()[0][:160]
    packages.append({"name": metadata.get("Name", "unknown"), "version": dist.version, "license": license_value})
try:
    pyinstaller_version = importlib.metadata.version("pyinstaller")
except importlib.metadata.PackageNotFoundError:
    raise SystemExit("PyInstaller is not installed in the selected build Python")
record = {"schema_version": "1", "python_executable": sys.executable,
          "python_version": platform.python_version(), "platform": platform.platform(),
          "pyinstaller_version": pyinstaller_version, "installed_distributions": packages,
          "scope": "build-environment inventory only; not proof that every listed package is bundled or importable from the EXE"}
Path(sys.argv[1]).write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
'@
$buildEnvironmentScript | & $Python - $buildEnvironmentPath
if ($LASTEXITCODE -ne 0) { throw "Could not record the Windows build environment: $LASTEXITCODE" }

$portableRoot = Join-Path $dist 'ResearchHarnessGUI'
foreach ($machineConfig in @('library-workspace.txt', 'rag-model-cache.txt', 'mcp-python.txt')) {
    if (Test-Path -LiteralPath (Join-Path $portableRoot $machineConfig)) {
        throw "Build unexpectedly included machine-local configuration: $machineConfig"
    }
}
Write-Output (Resolve-Path -LiteralPath (Join-Path $portableRoot 'ResearchHarnessGUI.exe')).Path
