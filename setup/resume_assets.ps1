[CmdletBinding(DefaultParameterSetName = 'ProjectAssets')]
param(
    [Parameter(ParameterSetName = 'ProjectAssets')]
    [switch]$SkipModel,
    [Parameter(Mandatory, ParameterSetName = 'OllamaRuntime')]
    [switch]$OllamaRuntime
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'checkpoint.ps1')
$tag = if ($OllamaRuntime) { 'v0.40.17' } else { 'assets-2026-11-20' }
$repo = if ($OllamaRuntime) { 'ollama/ollama' } else { 'egemencamozu/bist-harness' }
$base = "https://github.com/$repo/releases/download/$tag"
$store = Join-Path $root '.assets'
$lockName = if ($OllamaRuntime) { 'ollama-runtime.lock' } else { 'release.lock' }
$lock = Open-CheckpointLock $root $lockName

function Test-AssetHash([string]$Path, [string]$Expected) {
    (Test-Path -LiteralPath $Path -PathType Leaf) -and
        ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -eq $Expected)
}

function Receive-ReleaseAsset($Asset, [string]$PartialPath) {
    $name = $Asset.name
    if ($Asset.digest -notmatch '^sha256:([0-9a-f]{64})$' -or
        $Asset.browser_download_url -cne "$base/$name" -or $Asset.size -le 0) {
        throw "Missing or invalid Release identity for $name"
    }
    $hash = $Matches[1]
    $directory = Join-Path $store $hash
    $ready = Join-Path $directory $name
    $partial = if ($PartialPath) { $PartialPath } else { "$ready.partial" }
    $operation = "download.$($name.ToLowerInvariant())"
    New-Item -ItemType Directory -Path $directory -Force | Out-Null

    if (!(Test-AssetHash $ready $hash)) {
        Write-CheckpointEntry $root $operation in_progress $hash $tag
        try {
            $partialSize = 0
            if (Test-Path -LiteralPath $partial) { $partialSize = (Get-Item -LiteralPath $partial).Length }
            if ($partialSize -ne $Asset.size -or !(Test-AssetHash $partial $hash)) {
                $offset = if ($partialSize -lt $Asset.size) { $partialSize } else { 0 }
                Write-Host "Downloading $name from byte $offset of $($Asset.size)"
                $options = @('--fail', '--location', '--silent', '--show-error', '--connect-timeout', '30',
                    '--speed-time', '60', '--speed-limit', '1024', '--continue-at', $offset, '--output', $partial)
                curl.exe @options $Asset.browser_download_url
                if ($LASTEXITCODE -ne 0) { throw "curl exit $LASTEXITCODE for $name; partial retained" }
            }
            if ((Get-Item -LiteralPath $partial).Length -ne $Asset.size -or !(Test-AssetHash $partial $hash)) {
                throw "Release size or SHA-256 mismatch for $name"
            }

            $download = [IO.File]::Open($partial, 'Open', 'ReadWrite', 'None')
            try { $download.Flush($true) } finally { $download.Dispose() }
            if ([IO.File]::Exists($ready)) {
                [IO.File]::Replace($partial, $ready, [NullString]::Value)
            } else {
                [IO.File]::Move($partial, $ready)
            }
        } catch {
            Write-CheckpointEntry $root $operation failed $hash 'Download or integrity check failed; see console.'
            throw
        }
    }
    Write-CheckpointEntry $root $operation completed $hash "SHA-256 verified against GitHub Release $tag."
    $ready
}

function Install-ReleaseAsset([string]$Path, [string]$Hash, [scriptblock]$Copy) {
    $operation = "install.$([IO.Path]::GetFileName($Path).ToLowerInvariant())"
    if (Test-Path -LiteralPath $Path) {
        if (!(Test-AssetHash $Path $Hash)) {
            Write-CheckpointEntry $root $operation failed $Hash 'Existing destination differs from Release asset.'
            throw "Existing destination differs from Release asset: $Path"
        }
    } else {
        Write-CheckpointEntry $root $operation in_progress $Hash $tag
        New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force | Out-Null
        $temp = "$Path.partial"
        try {
            $target = [IO.File]::Open($temp, 'Create', 'Write', 'None')
            try {
                & $Copy $target
                $target.Flush($true)
            } finally {
                $target.Dispose()
            }
            if (!(Test-AssetHash $temp $Hash)) { throw "Install checksum mismatch for $Path" }
            [IO.File]::Move($temp, $Path)
        } catch {
            Write-CheckpointEntry $root $operation failed $Hash 'Install or integrity check failed; see console.'
            throw
        }
    }
    Write-CheckpointEntry $root $operation completed $Hash "Installed SHA-256 verified against $tag."
    Write-Host "Verified $Path"
}

function Get-ReleaseAsset([string]$Name) {
    if (!$assets.ContainsKey($Name)) { throw "Release asset not found: $Name" }
    $assets[$Name]
}

function Install-OllamaRuntime {
    $archive = Get-ReleaseAsset 'ollama-windows-amd64.zip'
    $hash = '3dd80f6e3a9699f2eadf4ac418f00529cee594df9557541806eda1f1f3f5588a'
    if ($archive.digest -ne "sha256:$hash") { throw 'Unexpected Ollama archive checksum' }
    $destination = Join-Path $root '.tools/ollama-0.40.17'
    $exe = Join-Path $destination 'ollama.exe'
    Write-CheckpointEntry $root 'ollama.runtime' in_progress $hash 'Preparing the pinned Ollama runtime.'
    try {
        if (!(Test-Path -LiteralPath $destination)) {
            $download = Receive-ReleaseAsset $archive (Join-Path $store 'ollama-0.40.17-windows-amd64.zip.partial')
            $extract = "$destination.partial"
            New-Item -ItemType Directory -Path $extract -Force | Out-Null
            tar.exe -xf $download -C $extract
            if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath (Join-Path $extract 'ollama.exe'))) {
                throw 'Ollama archive extraction failed'
            }
            [IO.Directory]::Move($extract, $destination)
        }
        $version = & {
            $ErrorActionPreference = 'Continue'
            $output = & $exe --version 2>&1
            [PSCustomObject]@{ ExitCode = $LASTEXITCODE; Text = ($output -join ' ') }
        }
        if ($version.ExitCode -ne 0 -or $version.Text -notmatch '\b0\.40\.17\b') {
            throw 'Unexpected Ollama executable version'
        }
        Write-CheckpointEntry $root 'ollama.runtime' completed $hash 'Official archive and local client version verified.'
        Write-Host "Verified $exe"
    } catch {
        Write-CheckpointEntry $root 'ollama.runtime' failed $hash 'Runtime preparation failed; see console.'
        throw
    }
}

try {
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$repo/releases/tags/$tag" -TimeoutSec 25
    $assets = @{}
    foreach ($asset in $release.assets) {
        if ($assets.ContainsKey($asset.name)) { throw "Duplicate Release asset: $($asset.name)" }
        $assets[$asset.name] = $asset
    }

    if ($OllamaRuntime) {
        Install-OllamaRuntime
        return
    }

    $sumFile = Receive-ReleaseAsset (Get-ReleaseAsset 'SHA256SUMS.txt')
    $hashes = @{}
    foreach ($line in Get-Content -LiteralPath $sumFile -Encoding utf8) {
        if (!$line.Trim() -or $line.TrimStart().StartsWith('#')) { continue }
        if ($line -notmatch '^([a-f0-9]{64})\s+([a-zA-Z0-9_.-]+)$' -or $hashes.ContainsKey($Matches[2])) {
            throw 'Malformed or duplicate entry in SHA256SUMS.txt'
        }
        $hashes[$Matches[2]] = $Matches[1]
    }

    $dbAsset = Get-ReleaseAsset 'bist.sqlite.gz'
    if (!$hashes['bist.sqlite'] -or $dbAsset.digest -ne ('sha256:' + $hashes['bist.sqlite.gz'])) {
        throw 'Database checksum missing or inconsistent'
    }
    $compressed = Receive-ReleaseAsset $dbAsset
    Install-ReleaseAsset (Join-Path $root 'data/db/bist.sqlite') $hashes['bist.sqlite'] {
        param($Target)
        $inputFile = [IO.File]::OpenRead($compressed)
        try {
            $gzip = [IO.Compression.GZipStream]::new($inputFile, [IO.Compression.CompressionMode]::Decompress, $true)
            try { $gzip.CopyTo($Target) } finally { $gzip.Dispose() }
        } finally {
            $inputFile.Dispose()
        }
    }

    if (!$SkipModel) {
        $model = 'bist-4b-q8_0.gguf'
        $pattern = '^' + [regex]::Escape($model) + '\.part(\d+)$'
        $partNames = @($hashes.Keys | Where-Object { $_ -match $pattern })
        if (!$hashes[$model] -or $partNames.Count -eq 0) { throw 'Missing model checksums' }
        $modelPath = Join-Path $root "models/$model"
        $parts = @()
        for ($i = 0; $i -lt $partNames.Count; $i++) {
            $name = "$model.part$i"
            $asset = Get-ReleaseAsset $name
            if ($asset.digest -ne ('sha256:' + $hashes[$name])) { throw "Inconsistent checksum for $name" }
            if (!(Test-Path -LiteralPath $modelPath)) { $parts += Receive-ReleaseAsset $asset }
        }
        Install-ReleaseAsset $modelPath $hashes[$model] {
            param($Target)
            foreach ($part in $parts) {
                $inputFile = [IO.File]::OpenRead($part)
                try { $inputFile.CopyTo($Target) } finally { $inputFile.Dispose() }
            }
        }
    }
} finally {
    $lock.Dispose()
}
