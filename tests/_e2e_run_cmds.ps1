# Real scubiee CLI combination test - user-side commands only
# Run from repo root: powershell -File tests\_e2e_run_cmds.ps1

$ErrorActionPreference = "Continue"
Remove-Item Env:CTX_HOME -ErrorAction SilentlyContinue
$env:Path = "$env:APPDATA\uv\tools\scubiee\Scripts;$env:USERPROFILE\.local\bin;$env:Path"
Set-Location "C:\Users\usman\Downloads\context-engine"

$log = Join-Path $PSScriptRoot "_e2e_cmd_results.txt"
"" | Set-Content $log
function Log($id, $cmd, $exit, $note) {
    $line = "[$id] exit=$exit | $cmd | $note"
    Add-Content $log $line
    Write-Host $line
}

function Run($id, $cmd, $expect) {
    Write-Host "`n=== $id : $cmd ===" -ForegroundColor Cyan
    $out = Invoke-Expression "$cmd 2>&1" | Out-String
    $exit = $LASTEXITCODE
    if ($null -eq $exit) { $exit = 0 }
    $tail = if ($out.Length -gt 400) { $out.Substring(0, 400) + "..." } else { $out.Trim() }
    $tail = ($tail -replace "`r`n", " | ").Trim()
    Log $id $cmd $exit "$expect :: $tail"
    return $exit
}

Add-Content $log "=== Scubiee real CLI test $(Get-Date -Format o) ==="
Add-Content $log "Repo: $(Get-Location)"
Add-Content $log "Version: $(scubiee --version 2>&1 | Select-Object -First 1)"

# --- Baseline ---
Run "B1" "scubiee --version" "OK"
Run "B3" "scubiee doctor" "ANY"
Run "B5" "scubiee status ." "ANY"
Run "B7" "scubiee setup --repair" "OK"
Run "B8" "scubiee init ." "OK"
Run "B10" "scubiee status ." "OK enrolled"

# --- Global stop ---
Run "G1" "scubiee stop -y" "OK"
Run "G2" "scubiee stop -y" "NOOP"
Run "G3" "scubiee init ." "BLOCK"
Run "G5" "scubiee setup --repair" "OK repair allowed"
Run "G12" "scubiee doctor" "OK read-only"
Run "G14" "scubiee halt" "OK recovery"
Run "G17" "scubiee resume" "OK"
Run "G18" "scubiee init ." "OK idempotent"

# --- Halt / unlock ---
Run "H1" "scubiee halt" "OK"
Run "H2" "scubiee resume" "OK after halt"

# --- Repo wipe (enrolled) ---
Run "W1" "scubiee wipe . --confirm" "OK repo wipe"
$idExists = Test-Path ".scubiee\id.json"
Add-Content $log "[W1-check] .scubiee/id.json exists=$idExists (expect false after wipe)"

# Re-init for more tests
Run "W1b" "scubiee init ." "OK re-init after repo wipe"
Run "W2" "scubiee stop -y" "OK before full wipe prep"

# --- Full wipe (keep package) ---
Run "G16" "scubiee wipe --all" "CONFIRM exit 2"
Run "G16b" "scubiee wipe --all --confirm --keep-package" "OK full clean"

$homeExists = Test-Path "$env:USERPROFILE\.scubiee"
Add-Content $log "[G16b-check] ~/.scubiee exists=$homeExists (expect false)"
$idAfter = Test-Path ".scubiee\id.json"
Add-Content $log "[G16b-check] .scubiee/id.json exists=$idAfter (expect false)"

# --- Post full wipe: setup + init again ---
Run "P1" "scubiee setup --repair" "OK after full wipe"
Run "P2" "scubiee init ." "OK fresh init"
Run "P3" "scubiee status ." "OK"

# --- Help / read-only ---
Run "R1" "scubiee --help" "OK no unicode crash"
Run "R2" "scubiee halt --help" "OK"
Run "R3" "scubiee wipe --help" "OK"
Run R4 "scubiee list" "OK"

# --- Connect dry-run (no IDE writes) — see docs/scubiee-connect-e2e-manual-test.md ---
Run "C1" "scubiee connect --cursor --claude-code --codex --opencode --amp --pi --dry-run" "OK"
Run "C2" "scubiee connect --all --dry-run" "OK all tools"

Add-Content $log "=== DONE $(Get-Date -Format o) ==="
Write-Host "`nResults written to $log" -ForegroundColor Green
