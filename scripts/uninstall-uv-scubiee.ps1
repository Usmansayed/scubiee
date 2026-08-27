# Force-uninstall scubiee when wipe/uv tool uninstall fails (Windows file locks).
# Works even when `scubiee` itself is broken (ModuleNotFoundException).
#
# Order matters: disable MCP FIRST so Cursor cannot respawn python.exe after kill.
# Admin / reboot will NOT help — these are file locks, not ACLs.
#
# powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1

$ErrorActionPreference = "Stop"
$UvToolRoot = Join-Path $env:APPDATA "uv\tools\scubiee"
$LocalBin = Join-Path $env:USERPROFILE ".local\bin"
$CtxHome = Join-Path $env:USERPROFILE ".scubiee"

function Disable-ScubieeMcp([string]$Path, [string]$Key) {
    if (-not (Test-Path $Path)) { return }
    try {
        $json = Get-Content $Path -Raw | ConvertFrom-Json
        $servers = $json.$Key
        if ($null -eq $servers) { return }
        $changed = $false
        foreach ($name in @("scubiee")) {
            if ($servers.PSObject.Properties.Name -contains $name) {
                $entry = $servers.$name
                if ($entry -is [PSCustomObject]) {
                    $entry | Add-Member -NotePropertyName disabled -NotePropertyValue $true -Force
                }
                $servers.$name = $entry
                $changed = $true
                Write-Host "[uninstall] Disabled $name in $Path"
            }
        }
        if ($changed) {
            $json.$Key = $servers
            $json | ConvertTo-Json -Depth 20 | Set-Content $Path -Encoding UTF8
        }
    } catch {
        Write-Host "[uninstall] Could not edit $Path : $_"
    }
}

function Remove-PathWithRetry([string]$Path, [int]$Attempts = 5) {
    if (-not (Test-Path $Path)) { return $true }
    for ($i = 1; $i -le $Attempts; $i++) {
        Write-Host "[uninstall] Removing $Path (attempt $i/$Attempts)"
        Remove-Item -Recurse -Force $Path -ErrorAction SilentlyContinue
        if (-not (Test-Path $Path)) { return $true }
        $trash = "$Path.trash-$PID-$i"
        try {
            Rename-Item -Path $Path -NewName (Split-Path $trash -Leaf) -ErrorAction Stop
            Remove-Item -Recurse -Force $trash -ErrorAction SilentlyContinue
        } catch {
            # still locked
        }
        if (-not (Test-Path $Path)) { return $true }
        Start-Sleep -Seconds (1 * $i)
    }
    return -not (Test-Path $Path)
}

Write-Host "[uninstall] Disabling MCP so Cursor cannot respawn lockers ..."
Disable-ScubieeMcp (Join-Path $env:USERPROFILE ".cursor\mcp.json") "mcpServers"
$cwdCursor = Join-Path (Get-Location) ".cursor\mcp.json"
Disable-ScubieeMcp $cwdCursor "mcpServers"
Start-Sleep -Seconds 1

Write-Host "[uninstall] Stopping Scubiee processes ..."
$pattern = 'scubiee|ctx-mcp|uv\\tools\\scubiee|pipeline\.'
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

foreach ($path in @($CtxHome, $UvToolRoot)) {
    if (-not (Remove-PathWithRetry $path)) {
        Write-Host "[uninstall] ERROR: $path still locked." -ForegroundColor Red
        Write-Host "  Quit Cursor completely (File → Exit), then re-run this script." -ForegroundColor Yellow
        Write-Host "  Admin PowerShell will NOT help — these are file locks, not permissions." -ForegroundColor Yellow
        exit 1
    }
}

uv tool uninstall scubiee 2>$null | Out-Null
if (Test-Path $UvToolRoot) {
    [void](Remove-PathWithRetry $UvToolRoot)
}

foreach ($name in @("scubiee.exe", "scubiee", "ctx.exe", "ctx", "ctx-mcp.exe", "ctx-mcp")) {
    Remove-Item -Force (Join-Path $LocalBin $name) -ErrorAction SilentlyContinue
}

if (Test-Path $UvToolRoot) {
    Write-Host "[uninstall] ERROR: $UvToolRoot still locked. Quit Cursor completely and re-run." -ForegroundColor Red
    Write-Host "  Admin will not help." -ForegroundColor Yellow
    exit 1
}

Write-Host "[uninstall] OK. scubiee is removed from this machine." -ForegroundColor Green
Write-Host "Reinstall: uv tool install scubiee --index-url https://pypi.org/simple"
