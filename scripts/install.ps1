# Context Engine installer (Windows) — ONE command for full MCP setup
# powershell -ExecutionPolicy Bypass -File scripts\install.ps1

param(
  [ValidateSet("auto", "cuda", "dml", "coreml", "cpu")]
  [string]$Profile = "auto",
  [string]$IndexPath = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> Installing Context Engine (Cursor MCP)"

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
  Write-Host "==> Creating .venv"
  py -3 -m venv .venv
}
$py = (Resolve-Path .\.venv\Scripts\python.exe).Path

Write-Host "==> Package + Graphify + MCP"
& $py -m pip install -U pip setuptools wheel
& $py -m pip install -e ".[mcp]"

Write-Host "==> Configure (GPU/CPU, start service, register MCP)"
$setupArgs = @()
if ($Profile -ne "auto") {
  $setupArgs += @("--profile", $Profile)
}
if ($IndexPath -ne "") {
  $setupArgs += @("--register", "--repo", $IndexPath)
}
& $py -m pipeline setup @setupArgs
if ($LASTEXITCODE -ne 0) {
  throw "pipeline setup failed with exit $LASTEXITCODE"
}

Write-Host ""
Write-Host "Done. Context Engine MCP is installed."
Write-Host "  1. Reload MCP in Cursor (Settings → MCP → refresh)"
Write-Host "  2. Use tools: search_code, locate_capability, status, …"
Write-Host "  Optional CLI: .\.venv\Scripts\ctx.exe search `"your query`" ."
Write-Host "  Optional UI:  http://127.0.0.1:8765/dashboard"
