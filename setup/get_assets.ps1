# Downloads the frozen database + the fine-tuned model from the private GitHub release, verifies every sha256,
# installs them (data/db/bist.sqlite, models/bist-4b-q8_0.gguf) and registers the Ollama model "bist-analist".
#
#   powershell -ExecutionPolicy Bypass -File setup\get_assets.ps1            # DB + model (~4,5 GB)
#   powershell -ExecutionPolicy Bypass -File setup\get_assets.ps1 -SkipModel # DB only (~15 MB)
#
# Needs: gh (GitHub CLI, logged in with access to the repo), and for the model: Ollama running.
param(
    [string]$Tag = "assets-2026-11-20",
    [string]$Repo = "egemencamozu/bist-harness",
    [switch]$SkipModel
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$dl = Join-Path $root ".assets"
New-Item -ItemType Directory -Force $dl | Out-Null

function Get-Expected([string]$name) {
    $line = Get-Content (Join-Path $dl "SHA256SUMS.txt") | Where-Object { $_ -match "^[0-9a-f]{64}\s+$([regex]::Escape($name))$" }
    if (-not $line) { throw "no checksum for $name in SHA256SUMS.txt" }
    return ($line -split "\s+")[0]
}
function Test-Sha([string]$path, [string]$name) {
    $actual = (Get-FileHash $path -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne (Get-Expected $name)) { throw "sha256 mismatch for $name ($path)" }
    Write-Output "  ok  $name"
}

Write-Output "[1/4] downloading release $Tag ..."
$patterns = @("SHA256SUMS.txt", "bist.sqlite.gz")
if (-not $SkipModel) { $patterns += "bist-4b-q8_0.gguf.part*" }
$args_ = @("release", "download", $Tag, "--repo", $Repo, "--dir", $dl, "--clobber")
foreach ($p in $patterns) { $args_ += @("--pattern", $p) }
& gh @args_
if ($LASTEXITCODE -ne 0) { throw "gh release download failed (logged in? access to $Repo?)" }

Write-Output "[2/4] database ..."
Test-Sha (Join-Path $dl "bist.sqlite.gz") "bist.sqlite.gz"
$dbDir = Join-Path $root "data\db"
New-Item -ItemType Directory -Force $dbDir | Out-Null
$dbPath = Join-Path $dbDir "bist.sqlite"
$in = [IO.File]::OpenRead((Join-Path $dl "bist.sqlite.gz"))
$gz = New-Object IO.Compression.GZipStream($in, [IO.Compression.CompressionMode]::Decompress)
$out = [IO.File]::Create($dbPath)
try { $gz.CopyTo($out) } finally { $out.Close(); $gz.Close(); $in.Close() }
Test-Sha $dbPath "bist.sqlite"

if ($SkipModel) { Write-Output "done (model skipped)."; exit 0 }

Write-Output "[3/4] model (joining parts) ..."
$parts = Get-ChildItem $dl -Filter "bist-4b-q8_0.gguf.part*" | Sort-Object Name
foreach ($p in $parts) { Test-Sha $p.FullName $p.Name }
$modelDir = Join-Path $root "models"
New-Item -ItemType Directory -Force $modelDir | Out-Null
$gguf = Join-Path $modelDir "bist-4b-q8_0.gguf"
$out = [IO.File]::Create($gguf)
try {
    foreach ($p in $parts) { $s = [IO.File]::OpenRead($p.FullName); try { $s.CopyTo($out) } finally { $s.Close() } }
} finally { $out.Close() }
Test-Sha $gguf "bist-4b-q8_0.gguf"

Write-Output "[4/4] ollama create bist-analist ..."
@(
    "FROM ./bist-4b-q8_0.gguf",
    "RENDERER qwen3.5",
    "PARSER qwen3.5",
    "PARAMETER temperature 0",
    "PARAMETER seed 42",
    "PARAMETER num_ctx 4096"
) | Set-Content -Path (Join-Path $modelDir "Modelfile") -Encoding ascii
Push-Location $modelDir
try {
    ollama create bist-analist -f Modelfile
    if ($LASTEXITCODE -ne 0) { throw "ollama create failed (is Ollama running?)" }
} finally { Pop-Location }
ollama list
Write-Output "done. The downloaded parts in .assets\ can be deleted."
