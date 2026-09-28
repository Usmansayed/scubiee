# Quick Vulkan bench for Qwen3.5-0.8B Q4 (llama.cpp), bypassing Ollama.
# Requires tools/llama-cpp/vulkan-b10797 from ggerganov release b10797.

$ErrorActionPreference = "Stop"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -ErrorAction SilentlyContinue
if (-not $root) { $root = "C:\Users\usman\Downloads\context-engine" }
$root = "C:\Users\usman\Downloads\context-engine"

$bench = Join-Path $root "tools\llama-cpp\vulkan-b10797\llama-bench.exe"
$gguf = Join-Path $root "models\qwen35-0.8b-gguf\Qwen3.5-0.8B-Q4_K_M.gguf"
$icd = Get-ChildItem "C:\Windows\System32\DriverStore\FileRepository" -Recurse -Filter "amd-vulkan64.json" -ErrorAction SilentlyContinue |
  Where-Object { $_.FullName -match 'u0403196' } |
  Select-Object -First 1 -ExpandProperty FullName
if (-not $icd) {
  $icd = Get-ChildItem "C:\Windows\System32\DriverStore\FileRepository" -Recurse -Filter "amd-vulkan64.json" -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1 -ExpandProperty FullName
}

$env:VK_ICD_FILENAMES = $icd
$env:VK_LOADER_LAYERS_DISABLE = "*"
$env:DISABLE_LAYER_AMD_SWITCHABLE_GRAPHICS_1 = "1"
$env:GGML_VK_DISABLE_INTEGER_DOT_PRODUCT = "1"

Write-Host "ICD: $icd"
& $bench -m $gguf -ngl 99 -p 64 -n 128 -r 3
