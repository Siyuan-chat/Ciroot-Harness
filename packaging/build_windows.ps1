param(
    [string]$Python = '.local\gui-clean-venv\Scripts\python.exe'
)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$root = (Get-Location).Path
if (-not (Test-Path 'frontend\dist\index.html')) { throw 'Run npm run build in frontend first.' }
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
    --exclude-module torch `
    --exclude-module torchvision `
    --exclude-module transformers `
    --exclude-module docling `
    --exclude-module docling_core `
    --exclude-module docling_parse `
    --distpath '.local\gui-package\dist' `
    --workpath '.local\gui-package\build' `
    --specpath '.local\gui-package' `
    packaging\desktop_entry.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed: $LASTEXITCODE" }
$portableRoot = Join-Path $root '.local\gui-package\dist\ResearchHarnessGUI'
foreach ($machineConfig in @('library-workspace.txt', 'rag-model-cache.txt', 'mcp-python.txt')) {
    $machinePath = Join-Path $portableRoot $machineConfig
    if (Test-Path -LiteralPath $machinePath) { Remove-Item -LiteralPath $machinePath -Force }
}
Write-Output (Resolve-Path '.local\gui-package\dist\ResearchHarnessGUI\ResearchHarnessGUI.exe')
