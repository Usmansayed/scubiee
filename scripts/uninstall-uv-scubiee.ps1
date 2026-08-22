# Force-uninstall scubiee when wipe/uv tool uninstall fails (Windows file locks).
# Works even when `scubiee` itself is broken (ModuleNotFoundError).
#
# 1. Quit Cursor completely (MCP keeps python.exe open), OR run this and reload Cursor.
# 2. powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1

$ErrorActionPreference = "Stop"
$UvToolRoot = Join-Path $env:APPDATA "uv\tools\scubiee"
$LocalBin = Join-Path $env:USERPROFILE ".local\bin"
$CtxHome = Join-Path $env:USERPROFILE ".context-engine"

Write-Host "[uninstall] Stopping Context Engine processes ..."
$pattern = 'scubiee|ctx-mcp|context-engine|uv\\tools\\scubiee|pipeline\.'
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath -like "*\uv\tools\scubiee\*") -or
        ($_.CommandLine -and $_.CommandLine -match $pattern)
    } |
    ForEach-Object {
        Write-Host "  taskkill /PID $($_.ProcessId) $($_.Name)"
        taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null
    }
Start-Sleep -Seconds 3

$Mcp = Join-Path $env:USERPROFILE ".cursor\mcp.json"
if (Test-Path $Mcp) {
    try {
        $json = Get-Content $Mcp -Raw | ConvertFrom-Json
        if ($json.mcpServers.PSObject.Properties.Name -contains "context-engine") {
            $json.mcpServers.PSObject.Properties.Remove("context-engine")
            $json | ConvertTo-Json -Depth 10 | Set-Content $Mcp -Encoding UTF8
            Write-Host "[uninstall] Removed context-engine from $Mcp"
        }
    } catch {
        Write-Host "[uninstall] Could not edit mcp.json: $_"
    }
}

foreach ($path in @($CtxHome, $UvToolRoot)) {
    if (Test-Path $path) {
        Write-Host "[uninstall] Removing $path"
        Remove-Item -Recurse -Force $path -ErrorAction SilentlyContinue
    }
}

uv tool uninstall scubiee 2>$null | Out-Null
if (Test-Path $UvToolRoot) {
    Remove-Item -Recurse -Force $UvToolRoot -ErrorAction SilentlyContinue
}

foreach ($name in @("scubiee.exe", "scubiee", "ctx.exe", "ctx", "ctx-mcp.exe", "ctx-mcp")) {
    Remove-Item -Force (Join-Path $LocalBin $name) -ErrorAction SilentlyContinue
}

if (Test-Path $UvToolRoot) {
    Write-Host "[uninstall] ERROR: $UvToolRoot still locked. Quit Cursor completely and re-run." -ForegroundColor Red
    exit 1
}

Write-Host "[uninstall] OK. scubiee is removed from this machine." -ForegroundColor Green
Write-Host "Reinstall: uv tool install scubiee --index-url https://pypi.org/simple"
