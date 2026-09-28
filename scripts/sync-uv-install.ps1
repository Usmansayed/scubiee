# Sync the uv-tool Scubiee install with this checkout (BETA-04 / BETA-18).
#
# Why not `uv tool install --reinstall .`: that rebuilds the tool env and swaps
# onnxruntime-directml for plain onnxruntime (dense then fails until
# `scubiee setup --repair`). This script replaces only the scubiee package
# (--no-deps) inside the existing tool env, so FastEmbed / DirectML stay put.
#
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File scripts/sync-uv-install.ps1            # sync + verify
#   powershell -ExecutionPolicy Bypass -File scripts/sync-uv-install.ps1 -CheckOnly # verify only
#   powershell -ExecutionPolicy Bypass -File scripts/sync-uv-install.ps1 -RestartEngine
#
# Running MCP bridges keep old code in memory: reload Scubiee MCP in Cursor/Kiro
# after syncing (or pass -RestartEngine for the HTTP engine).

param(
    [switch]$CheckOnly,
    [switch]$RestartEngine
)

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ToolRoot = Join-Path $env:APPDATA "uv\tools\scubiee"
$Py = Join-Path $ToolRoot "Scripts\python.exe"
$SitePackages = Join-Path $ToolRoot "Lib\site-packages"
# Must match [tool.setuptools.packages.find].include in pyproject.toml.
$Packages = @("pipeline", "hybrid_cbm", "conductor", "enrich", "metadata", "repo_ir",
              "parse_harness", "graphify", "trace_lab")

# Never let an agent shell's PYTHONPATH=packages mask the installed code.
Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue

if (-not (Test-Path $Py)) {
    Write-Host "[sync] uv-tool scubiee not found at $ToolRoot. Install first: uv tool install ." -ForegroundColor Red
    exit 1
}

if (-not $CheckOnly) {
    Write-Host "[sync] Reinstalling scubiee from $Repo into $ToolRoot (no deps) ..."
    uv pip install --python $Py --reinstall-package scubiee --no-deps --refresh-package scubiee $Repo
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# Parity: every packaged .py in the checkout must be byte-identical in site-packages.
$pkgRoot = Join-Path $Repo "packages"
$differ = @()
$missing = @()
foreach ($pkg in $Packages) {
    $src = Join-Path $pkgRoot $pkg
    if (-not (Test-Path $src)) { continue }
    Get-ChildItem $src -Recurse -Filter *.py |
        Where-Object { $_.FullName -notmatch '\\__pycache__\\' } |
        ForEach-Object {
            $rel = $_.FullName.Substring($pkgRoot.Length + 1)
            $dst = Join-Path $SitePackages $rel
            if (-not (Test-Path $dst)) { $missing += $rel }
            elseif ((Get-FileHash $_.FullName).Hash -ne (Get-FileHash $dst).Hash) { $differ += $rel }
        }
}

# Feature probe with the tool interpreter and no PYTHONPATH.
$probe = & $Py -c "import pipeline, pipeline.ignore as ig, pipeline.mcp_locate as ml; print(pipeline.__file__); print(int(hasattr(ml, 'format_gate_ignore_lines') or hasattr(ig, 'format_gate_ignore_lines')))" 2>&1
$probeOk = ($LASTEXITCODE -eq 0) -and (($probe | Select-Object -Last 1) -eq "1")

$ignorePresent = Test-Path (Join-Path $SitePackages "pipeline\ignore.py")
Write-Host "[sync] ignore.py present: $ignorePresent"
Write-Host "[sync] differ: $($differ.Count)  missing: $($missing.Count)"
$differ | Select-Object -First 20 | ForEach-Object { Write-Host "  differ  $_" }
$missing | Select-Object -First 20 | ForEach-Object { Write-Host "  missing $_" }
Write-Host "[sync] probe: $($probe -join ' | ')"

$ok = $ignorePresent -and $probeOk -and ($differ.Count -eq 0) -and ($missing.Count -eq 0)

# Issue 7: running MCP bridges keep the old worker code in memory. Publishing a
# new build stamp makes each bridge respawn its worker on the next tool call
# (initialize is replayed; the host's stdio connection stays up).
if ($ok -and -not $CheckOnly) {
    $stamp = & $Py -c "from pipeline.mcp_hot_reload import write_active_build_stamp as w; print(w()['build_id'])" 2>$null
    Write-Host "[sync] active build stamp: $($stamp | Select-Object -Last 1) (bridges respawn workers on next call)"
}

if ($RestartEngine -and -not $CheckOnly) {
    Write-Host "[sync] Restarting engine so it loads the synced code ..."
    & (Join-Path $env:USERPROFILE ".local\bin\scubiee.exe") engine stop
    & (Join-Path $env:USERPROFILE ".local\bin\scubiee.exe") engine ensure $Repo
}

if ($ok) {
    Write-Host "[sync] OK: uv-tool install matches workspace. Connected MCP sessions pick up the new code on their next call (restart the engine with -RestartEngine)." -ForegroundColor Green
    exit 0
}
Write-Host "[sync] FAIL: install and workspace still differ." -ForegroundColor Red
exit 2
