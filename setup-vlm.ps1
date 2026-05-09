param(
  [string]$EnvName = "odyseus-vlm",
  [string]$QwenUrl = "http://127.0.0.1:8012/v1",
  [string]$Model = "Qwen/Qwen3-VL-8B-Instruct",
  [string]$GpuUtil = "0.7",
  [string]$MaxModelLen = "16384"
)

$RepoDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$EnvFile = Join-Path $RepoDir ".env.vlm"

$content = @(
  "QWEN_URL=$QwenUrl"
  "GPU_UTIL=$GpuUtil"
  "MAX_MODEL_LEN=$MaxModelLen"
  "VLM_MODEL=$Model"
  "VLM_ENV_NAME=$EnvName"
)

Set-Content -Path $EnvFile -Value $content -Encoding ascii

Write-Host ""
Write-Host "Created $EnvFile"
Write-Host ""
Write-Host "Next steps on the Linux host:"
Write-Host "  1. ./setup-vlm.sh $EnvName"
Write-Host "  2. ./run-vlm.sh"
Write-Host ""
Write-Host "If the env already exists, skip step 1 and just run ./run-vlm.sh"
