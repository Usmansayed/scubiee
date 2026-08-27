# Repair a broken `uv tool install scubiee` on Windows.
# Use when you see: "failed to locate pyvenv.cfg", faiss import errors, or Access denied on uninstall.
#
# Order: disable MCP first → kill lockers → retry remove → reinstall.
# Admin / reboot will NOT help — file locks, not ACLs.
#
# powershell -ExecutionPolicy Bypass -File scripts/repair-uv-scubiee.ps1 [version]

$ErrorActionPreference = "Stop"
$UvToolRoot = Join-Path $env:APPDATA "uv\tools\scubiee"
$LocalBin = Join-Path $env:USERPROFILE ".local\bin"
$Version = if ($args.Count -gt 0) { $args[0] } else { "0.2.87" }
$IndexUrl = "https://pypi.org/simple"

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
                Write-Host "[repair] Disabled $name in $Path"
            }
        }
        if ($changed) {
            $json.$Key = $servers
            $json | ConvertTo-Json -Depth 20 | Set-Content $Path -Encoding UTF8
        }
    } catch {
        Write-Host "[repair] Could not edit $Path : $_"
    }
}

function Remove-PathWithRetry([string]$Path, [int]$Attempts = 5) {
    if (-not (Test-Path $Path)) { return $true }
    for ($i = 1; $i -le $Attempts; $i++) {
        Write-Host "[repair] Removing $Path (attempt $i/$Attempts)"
        Remove-Item -Recurse -Force $Path -ErrorAction SilentlyContinue
        if (-not (Test-Path $Path)) { return $true }
        $leaf = (Split-Path $Path -Leaf) + ".trash-$PID-$i"
        $parent = Split-Path $Path -Parent
        $trash = Join-Path $parent $leaf
        try {
            Rename-Item -Path $Path -NewName $leaf -ErrorAction Stop
            Remove-Item -Recurse -Force $trash -ErrorAction SilentlyContinue
        } catch { }
        if (-not (Test-Path $Path)) { return $true }
        # Re-kill in case MCP respawned
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -and $_.ExecutablePath -like "*\uv\tools\scubiee\*" } |
            ForEach-Object { taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null }
        Start-Sleep -Seconds (1 * $i)
    }
    return -not (Test-Path $Path)
}

Write-Host "[repair] Disabling MCP so Cursor cannot respawn lockers ..."
Disable-ScubieeMcp (Join-Path $env:USERPROFILE ".cursor\mcp.json") "mcpServers"
Disable-ScubieeMcp (Join-Path (Get-Location) ".cursor\mcp.json") "mcpServers"
Start-Sleep -Seconds 1

Write-Host "[repair] Stopping processes using uv scubiee tool ..."
$pattern = 'scubiee|ctx-mcp|uv\\tools\\scubiee|pipeline\.'
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        ($_.ExecutablePath -and $_.ExecutablePath -like "*\uv\tools\scubiee\*") -or
        ($_.CommandLine -and $_.CommandLine -match $pattern)
    } |
    ForEach-Object {
        taskkill /PID $_.ProcessId /T /F 2>$null | Out-Null
    }
Start-Sleep -Seconds 2

if (Test-Path $UvToolRoot) {
    if (-not (Remove-PathWithRetry $UvToolRoot)) {
        Write-Host "[repair] ERROR: could not delete $UvToolRoot" -ForegroundColor Red
        Write-Host "  Quit Cursor completely, then retry. Admin will not help." -ForegroundColor Yellow
        exit 1
    }
}

Write-Host "[repair] Installing scubiee==$Version via uv ..."
uv tool install --force "scubiee==$Version" --index-url $IndexUrl
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Py = Join-Path $UvToolRoot "Scripts\python.exe"
$Pyvenv = Join-Path $UvToolRoot "pyvenv.cfg"
if (-not (Test-Path $Pyvenv)) {
    Write-Host "[repair] ERROR: pyvenv.cfg still missing after install." -ForegroundColor Red
    exit 1
}

$FaissWrap = Join-Path $UvToolRoot "Lib\site-packages\faiss\class_wrappers.py"
if (-not (Test-Path $FaissWrap)) {
    Write-Host "[repair] faiss-cpu incomplete — reinstalling from wheel ..."
    $WhlDir = Join-Path $env:TEMP "faiss_whl"
    New-Item -ItemType Directory -Force -Path $WhlDir | Out-Null
    & $Py -m ensurepip --upgrade | Out-Null
    & $Py -m pip download "faiss-cpu==1.15.0" -d $WhlDir --no-deps --quiet
    $Whl = Get-ChildItem "$WhlDir\faiss_cpu-*.whl" | Select-Object -First 1
    if (-not $Whl) {
        Write-Host "[repair] ERROR: could not download faiss wheel." -ForegroundColor Red
        exit 1
    }
    uv pip install --force-reinstall --no-deps $Whl.FullName --python $Py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$env:PATH = "$LocalBin;$env:PATH"
Write-Host "[repair] Verifying ..."
& scubiee --version
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[repair] OK. Run: scubiee setup --repair" -ForegroundColor Green
Write-Host "Then reconnect MCP: scubiee connect --cursor" -ForegroundColor Green
