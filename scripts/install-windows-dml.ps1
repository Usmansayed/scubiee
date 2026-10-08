# Install (or reinstall) Scubiee on Windows with DirectML GPU acceleration that
# does not break on reinstall/upgrade.
#
# fastembed depends on unbounded `onnxruntime`, which collides with
# `onnxruntime-directml` (same `onnxruntime/` folder, DLLs overwrite each other,
# generic wins -> DmlExecutionProvider silently lost -> CPU embedding). The uv
# override `onnxruntime; sys_platform == 'never'` excludes the generic wheel from
# resolution so only onnxruntime-directml is installed. uv records the override
# in the tool receipt, so `uv tool upgrade scubiee` keeps it automatically.
#
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File scripts/install-windows-dml.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/install-windows-dml.ps1 -Source scubiee        # from PyPI
#   powershell -ExecutionPolicy Bypass -File scripts/install-windows-dml.ps1 -Source dist_prod/scubiee-0.3.144-py3-none-any.whl

param(
    # What to install: a PyPI name ("scubiee"), a built wheel path, or "." for the checkout.
    [string]$Source = "scubiee",
    [switch]$NoSetup
)

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Overrides = Join-Path $Repo "packaging\uv-overrides-win-dml.txt"

if (-not (Test-Path $Overrides)) {
    Write-Host "[install] overrides file missing: $Overrides" -ForegroundColor Red
    exit 1
}

# Stop the engine so the tool env is not locked during (re)install.
try { & scubiee engine stop 2>$null | Out-Null } catch {}
Start-Sleep -Seconds 2

Write-Host "[install] uv tool install --overrides $Overrides $Source"
uv tool install --force --reinstall --overrides $Overrides $Source
if ($LASTEXITCODE -ne 0) {
    Write-Host "[install] uv tool install failed (exit $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

# Verify DirectML is actually available in the installed interpreter.
$Py = Join-Path $env:APPDATA "uv\tools\scubiee\Scripts\python.exe"
if (Test-Path $Py) {
    $providers = & $Py -c "import onnxruntime as ort; print(','.join(ort.get_available_providers()))" 2>$null
    if ($providers -match "DmlExecutionProvider") {
        Write-Host "[install] OK - DirectML provider present: $providers" -ForegroundColor Green
    } else {
        Write-Host "[install] WARNING - DmlExecutionProvider NOT present ($providers). Run: scubiee setup --repair" -ForegroundColor Yellow
    }
}

if (-not $NoSetup) {
    Write-Host "[install] running scubiee setup ..."
    & scubiee setup
}

Write-Host "[install] done. Next: scubiee init ." -ForegroundColor Green
