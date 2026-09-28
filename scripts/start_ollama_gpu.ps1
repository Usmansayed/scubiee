# Restart Ollama with AMD Vulkan pinned to RX 6500M ICD.
# Dual AMD drivers (iGPU + dGPU) crash llama --list-devices (0xC0000005)
# unless VK_ICD_FILENAMES points at a single amd-vulkan64.json.
#
# After success: ollama ps should show GPU, not 100% CPU.
# Bench: python scripts/bench_qwen35_ollama.py  (target >=100 eval tok/s)

$ErrorActionPreference = "Stop"

# Prefer discrete RX 6500M ICD (Adrenalin package with api 1.3.277)
$icdCandidates = @(
  (Get-ChildItem "C:\Windows\System32\DriverStore\FileRepository" -Recurse -Filter "amd-vulkan64.json" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match 'u0403196|B402774|B40' } |
    Sort-Object FullName -Descending |
    Select-Object -ExpandProperty FullName)
)
$icd = $icdCandidates | Where-Object { $_ -match 'u0403196' } | Select-Object -First 1
if (-not $icd) {
  $icd = Get-ChildItem "C:\Windows\System32\DriverStore\FileRepository" -Recurse -Filter "amd-vulkan64.json" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName
}
if (-not $icd) { throw "No amd-vulkan64.json found. Install/update AMD Adrenalin." }

Write-Host "Using Vulkan ICD: $icd"

# System loader (avoid Ollama bundled vulkan-1.dll crash / zero devices)
$bundled = "$env:LOCALAPPDATA\Programs\Ollama\lib\ollama\vulkan\vulkan-1.dll"
if (Test-Path $bundled) {
  if (-not (Test-Path "$bundled.bundled")) {
    Rename-Item $bundled "vulkan-1.dll.bundled" -Force
  } else {
    Remove-Item $bundled -Force -ErrorAction SilentlyContinue
  }
}

# Persist for future sessions
[Environment]::SetEnvironmentVariable("VK_ICD_FILENAMES", $icd, "User")
[Environment]::SetEnvironmentVariable("VK_LOADER_LAYERS_DISABLE", "*", "User")
[Environment]::SetEnvironmentVariable("DISABLE_LAYER_AMD_SWITCHABLE_GRAPHICS_1", "1", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_VULKAN", "1", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_FLASH_ATTENTION", "1", "User")
[Environment]::SetEnvironmentVariable("OLLAMA_NUM_PARALLEL", "1", "User")
[Environment]::SetEnvironmentVariable("GGML_VK_DISABLE_INTEGER_DOT_PRODUCT", "1", "User")

Get-Process | Where-Object { $_.ProcessName -match 'ollama' } | Stop-Process -Force
Start-Sleep -Seconds 2

$bat = @"
@echo off
set VK_ICD_FILENAMES=$icd
set VK_LOADER_LAYERS_DISABLE=*
set DISABLE_LAYER_AMD_SWITCHABLE_GRAPHICS_1=1
set OLLAMA_VULKAN=1
set OLLAMA_FLASH_ATTENTION=1
set OLLAMA_NUM_PARALLEL=1
set OLLAMA_DEBUG=1
set GGML_VK_DISABLE_INTEGER_DOT_PRODUCT=1
"$env:LOCALAPPDATA\Programs\Ollama\ollama.exe" serve
"@
$batPath = Join-Path $PSScriptRoot "_ollama_serve_gpu.cmd"
Set-Content -Path $batPath -Value $bat -Encoding ASCII
Start-Process -FilePath $batPath -WindowStyle Hidden
Start-Sleep -Seconds 5

Write-Host "Ollama:" (curl.exe -s http://127.0.0.1:11434/api/version)
Write-Host "Warming qwen3.5-0.8b-q4 via API..."
$ErrorActionPreference = "Continue"
$body = '{"model":"qwen3.5-0.8b-q4","prompt":"OK","stream":false,"think":false,"options":{"num_predict":4,"num_gpu":99}}'
curl.exe -s http://127.0.0.1:11434/api/generate -H "Content-Type: application/json" -d $body | Out-Null
ollama ps
Write-Host ""
Write-Host "Expect PROCESSOR column to show GPU. Then: python scripts/bench_qwen35_ollama.py"
