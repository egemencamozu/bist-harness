# One-shot downloads for Phase 5 on a good connection (resumable; safe to re-run).
#   powershell -ExecutionPolicy Bypass -File training\fetch_all.ps1
# 1) the Ollama candidate models (bake-off), 2) the separate GPU training environment (.venv-train).
# The base-model weights for training are downloaded by train_qlora.py itself on its first (pilot) run.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
[Environment]::SetEnvironmentVariable("OLLAMA_NOPRUNE", "1", "User")   # keep partial blobs across restarts
$env:OLLAMA_NOPRUNE = "1"
if (-not (Get-Process -Name "ollama" -ErrorAction SilentlyContinue)) {
    Start-Process -FilePath "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"; Start-Sleep -Seconds 8
}
# 1) models in the background (pull_models.ps1 retries until each one is listed)
$pull = Start-Process -FilePath "powershell" -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
    (Join-Path $PSScriptRoot "pull_models.ps1") -PassThru -WindowStyle Hidden
Write-Output "model downloads started (pid $($pull.Id)); log: $env:TEMP\bist_pull_models.log"
# 2) training environment (CUDA PyTorch + Unsloth/TRL) in parallel
Set-Location $root
if (-not (Test-Path ".venv-train")) { uv venv .venv-train --python 3.12 }
uv pip install --python .venv-train\Scripts\python.exe torch --index-url https://download.pytorch.org/whl/cu128
uv pip install --python .venv-train\Scripts\python.exe triton-windows unsloth trl peft datasets bitsandbytes accelerate
.venv-train\Scripts\python.exe -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
Wait-Process -Id $pull.Id
ollama list
