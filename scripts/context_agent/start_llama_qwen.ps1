# Start Qwen3-1.7B Q4_K_M on llama.cpp with Vulkan (AMD).
# Usage:  .\scripts\context_agent\start_llama_qwen.ps1
param(
  [string]$Model = "C:\Users\usman\models\Qwen3-1.7B-Q4_K_M.gguf",
  [int]$Port = 8080,
  [int]$Ngl = 99,
  [int]$Ctx = 8192
)

$ErrorActionPreference = "Stop"
$exe = (Get-Command llama-server -ErrorAction SilentlyContinue).Source
if (-not $exe) {
  throw "llama-server not found. Install: winget install ggml.llamacpp"
}
if (-not (Test-Path $Model)) {
  throw "Model missing: $Model"
}

# Already up?
try {
  $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2 -UseBasicParsing
  if ($r.StatusCode -eq 200) {
    Write-Host "llama-server already healthy on :$Port"
    exit 0
  }
} catch { }

Write-Host "Starting llama-server Vulkan ngl=$Ngl port=$Port"
Write-Host "  model=$Model"
$argList = @(
  "-m", $Model,
  "--port", "$Port",
  "--host", "127.0.0.1",
  "-c", "$Ctx",
  "-ngl", "$Ngl",
  "--jinja"
)
$logDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..\out")).Path
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdout = Join-Path $logDir "llama_qwen_server.log"
$stderr = Join-Path $logDir "llama_qwen_server.log.err"
Start-Process -FilePath $exe -ArgumentList $argList -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden
Start-Sleep -Seconds 2
$ok = $false
for ($i = 0; $i -lt 60; $i++) {
  try {
    $m = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2 -UseBasicParsing
    if ($m.StatusCode -eq 200) { $ok = $true; break }
  } catch { Start-Sleep -Seconds 1 }
}
if ($ok) { Write-Host "READY http://127.0.0.1:$Port" } else { Write-Host "WARN: started but /v1/models not ready — see $stderr"; exit 1 }
