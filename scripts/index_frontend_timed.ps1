# Timed frontend-mcp index (DML device 1, batch 16, seq 128, compress=mix)
$ErrorActionPreference = "Continue"
$root = "C:\Users\usman\Downloads\context-engine"
$py = Join-Path $root ".venv\Scripts\python.exe"
$fm = Join-Path $root "testdata\frontend-mcp"
$log = Join-Path $root "out\index_frontend_dml16.log"
$env:PYTHONPATH = Join-Path $root "packages"
$env:CTX_EMBED_BATCH = "16"
$env:CTX_EMBED_SEQ = "128"
$env:CTX_ACCEL_PROFILE = "dml"
$env:PYTHONUTF8 = "1"
# mix is pipeline default; set explicitly so logs are clear
$env:CTX_COMPRESS = "mix"
$env:CTX_COMPRESS_MAX_CHARS = "512"

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$start = Get-Date
"INDEX_START iso=$($start.ToString('o')) compress=mix" | Set-Content -Path $log -Encoding UTF8
& $py -u -m pipeline index $fm --force --fast --roots "src,packages,coordination_layer" *>> $log
$code = $LASTEXITCODE
$sw.Stop()
$end = Get-Date
"INDEX_END exit=$code elapsed_sec=$([math]::Round($sw.Elapsed.TotalSeconds,1)) elapsed=$($sw.Elapsed.ToString()) iso=$($end.ToString('o'))" | Add-Content -Path $log -Encoding UTF8
Write-Output "DONE exit=$code sec=$([math]::Round($sw.Elapsed.TotalSeconds,1))"
