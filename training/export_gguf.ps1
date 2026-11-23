# Merged 16-bit safetensors -> GGUF -> Ollama model (no compiler needed on Windows).
#   powershell -ExecutionPolicy Bypass -File training\export_gguf.ps1 [-Quant Q8_0|Q4_K_M] [-Name bist-analist]
# Prerequisite: training\train_qlora.py --out <Run> --export-only  (writes <Run>\merged).
# Uses a pinned llama.cpp tag: only its Python converter + gguf-py (~4 MB, training\fetch_llama_convert.py).
#   Q8_0 / BF16 / F16 are written by the converter directly (no binaries).
#   Q4_K_M (same as Ollama's qwen3.5:4b) additionally needs the prebuilt llama-quantize.exe (23 MB download).
# Ollama's own qwen3.5:4b is the same llama.cpp GGUF layout (arch qwen35), so the chat format is applied by Ollama's
# built-in RENDERER/PARSER qwen3.5 exactly as for the base model.
param(
    [string]$Run = "training\output\bist-4b",
    [string]$Quant = "Q8_0",
    [string]$Name = "bist-analist",
    [string]$Tag = "b12648"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv-train\Scripts\python.exe"
$tools = Join-Path $root ".tools\llama.cpp-$Tag"
$runDir = Join-Path $root $Run
if (-not (Test-Path (Join-Path $runDir "merged\config.json"))) { throw "merged model missing: run train_qlora.py --export-only first" }
$direct = @{ "Q8_0" = "q8_0"; "BF16" = "bf16"; "F16" = "f16" }

# 1) converter + gguf-py only (resumable: already fetched files are skipped)
Write-Output "[1/4] fetching llama.cpp $Tag converter (~4 MB) ..."
& $py (Join-Path $PSScriptRoot "fetch_llama_convert.py") --tag $Tag --dest "$tools\src"
if ($LASTEXITCODE -ne 0) { throw "converter download failed" }

$q = "bist-4b-$($Quant.ToLower()).gguf"
Push-Location $runDir   # relative ASCII file names: native tools never see the non-ASCII project path
try {
    # 2) safetensors -> GGUF (text model only; no vision tower, no MTP block). convert_for_ollama.py keeps the
    #    separate attn_qkv/attn_gate/ssm_beta/ssm_alpha tensors that Ollama's bundled llama.cpp loads (426 tensors,
    #    same names/shapes as Ollama's own qwen3.5:4b). Always re-converted (~2 min) so a stale file is never reused.
    $convert = Join-Path $PSScriptRoot "convert_for_ollama.py"
    if ($direct.ContainsKey($Quant)) {
        Write-Output "[2/4] converting merged -> $q ..."
        & $py $convert "$tools\src" "merged" --no-mtp --outtype $direct[$Quant] --outfile $q
        if ($LASTEXITCODE -ne 0) { throw "convert_hf_to_gguf failed" }
    } else {
        $bf16 = "bist-4b-bf16.gguf"
        Write-Output "[2/4] converting merged -> $bf16 ..."
        & $py $convert "$tools\src" "merged" --no-mtp --outtype bf16 --outfile $bf16
        if ($LASTEXITCODE -ne 0) { throw "convert_hf_to_gguf failed" }
        $quantize = Get-ChildItem "$tools\bin" -Recurse -Filter "llama-quantize.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $quantize) {
            Write-Output "[2/4] downloading llama-quantize ($Tag Windows CPU build, 23 MB) ..."
            New-Item -ItemType Directory -Force "$tools\bin" | Out-Null
            curl.exe -L --fail --retry 10 --retry-all-errors --retry-delay 3 -C - -o "$tools\bin.zip" `
                "https://github.com/ggml-org/llama.cpp/releases/download/$Tag/llama-$Tag-bin-win-cpu-x64.zip"
            if ($LASTEXITCODE -ne 0) { throw "llama-quantize download failed" }
            Expand-Archive "$tools\bin.zip" "$tools\bin" -Force
            $quantize = Get-ChildItem "$tools\bin" -Recurse -Filter "llama-quantize.exe" | Select-Object -First 1
        }
        Write-Output "[2/4] quantizing -> $q ..."
        & $quantize.FullName $bf16 $q $Quant
        if ($LASTEXITCODE -ne 0) { throw "llama-quantize failed" }
    }
    # 3) Modelfile (same decoding settings as the harness: temperature 0, seed 42, ctx 4096)
    Write-Output "[3/4] writing Modelfile ..."
    @(
        "FROM ./$q",
        "RENDERER qwen3.5",
        "PARSER qwen3.5",
        "PARAMETER temperature 0",
        "PARAMETER seed 42",
        "PARAMETER num_ctx 4096"
    ) | Set-Content -Path "Modelfile" -Encoding ascii
    # 4) Ollama model
    Write-Output "[4/4] ollama create $Name ..."
    ollama create $Name -f Modelfile
    if ($LASTEXITCODE -ne 0) { throw "ollama create failed" }
} finally {
    Pop-Location
}
ollama list
# smoke test: the runner must load the GGUF and answer in coherent Turkish (a layout mismatch fails right here)
Write-Output "smoke test (model loads + answers) ..."
ollama run $Name --think=false --keepalive 0 "Merhaba, kendini tek cumleyle tanit."   # ASCII: PowerShell 5.1 reads BOM-less scripts as ANSI
if ($LASTEXITCODE -ne 0) { throw "smoke test failed: Ollama could not run $Name" }
Write-Output "done: $Name ($Quant). Sha256 of the GGUF (recorded with every analysis as the model id):"
(Get-FileHash (Join-Path $runDir $q) -Algorithm SHA256).Hash
