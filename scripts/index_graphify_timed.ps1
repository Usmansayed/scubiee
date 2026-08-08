# Timed mix index of upstream Graphify GitHub clone
$ErrorActionPreference = "Continue"
$root = "C:\Users\usman\Downloads\context-engine"
$py = Join-Path $root ".venv\Scripts\python.exe"
$repo = Join-Path $root "testdata\graphify"
$log = Join-Path $root "out\index_graphify_timing.log"
$env:PYTHONPATH = Join-Path $root "packages"
$env:CTX_EMBED_BATCH = "16"
$env:CTX_EMBED_SEQ = "128"
$env:CTX_ACCEL_PROFILE = "dml"
$env:PYTHONUTF8 = "1"
$env:CTX_COMPRESS = "mix"
$env:CTX_COMPRESS_MAX_CHARS = "512"

New-Item -ItemType Directory -Force -Path (Join-Path $root "out") | Out-Null
$sw = [Diagnostics.Stopwatch]::StartNew()
$start = Get-Date
"GRAPHIFY_INDEX_START iso=$($start.ToString('o')) compress=mix seq=128" | Set-Content $log -Encoding UTF8
Write-Output "STARTED $($start.ToString('HH:mm:ss')) indexing $repo"
& $py -u -m pipeline index $repo --force 2>&1 | Tee-Object -FilePath $log -Append
$code = $LASTEXITCODE
$sw.Stop()
$end = Get-Date
"GRAPHIFY_INDEX_END exit=$code elapsed_sec=$([math]::Round($sw.Elapsed.TotalSeconds,1)) iso=$($end.ToString('o'))" | Add-Content $log -Encoding UTF8
Write-Output "DONE exit=$code total_wall_sec=$([math]::Round($sw.Elapsed.TotalSeconds,1))"
