# Repair a broken `uv tool install scubiee` on Windows.
# Use when you see: "failed to locate pyvenv.cfg", faiss import errors, or Access denied on uninstall.
#
# Close Cursor first (or disable Scubiee MCP) so ctx-mcp/python releases file locks.

$ErrorActionPreference = "Stop"
$UvToolRoot = Join-Path $env:APPDATA "uv\tools\scubiee"
$LocalBin = Join-Path $env:USERPROFILE ".local\bin"
$Version = if ($args.Count -gt 0) { $args[0] } else { "0.2.46" }
$IndexUrl = "https://pypi.org/simple"

Write-Host "[repair] Stopping processes using uv scubiee tool ..."
Get-Process python*, scubiee, ctx* -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "*\uv\tools\scubiee\*" } |
    ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

if (Test-Path $UvToolRoot) {
    Write-Host "[repair] Removing broken tool env: $UvToolRoot"
    Remove-Item -Recurse -Force $UvToolRoot -ErrorAction SilentlyContinue
    if (Test-Path $UvToolRoot) {
        Write-Host "[repair] ERROR: could not delete $UvToolRoot — quit Cursor and retry." -ForegroundColor Red
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
    & $Py -m pip download "faiss-cpu==1.15.0" -d $WhlDir --no-deps --quiet
    $Whl = Get-ChildItem "$WhlDir\faiss_cpu-*.whl" | Select-Object -First 1
    if (-not $Whl) {
        Write-Host "[repair] ERROR: could not download faiss wheel." -ForegroundColor Red
        exit 1
    }
    uv pip install --force-reinstall $Whl.FullName --python $Py
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$env:PATH = "$LocalBin;$env:PATH"
Write-Host "[repair] Verifying ..."
& scubiee --version
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[repair] OK. Run: scubiee setup --repair" -ForegroundColor Green
