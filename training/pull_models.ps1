# Downloads the bake-off candidate models, retrying until each appears in `ollama list`.
# Ollama keeps partially downloaded blobs, so every attempt (and every new run of this script) resumes.
#   powershell -ExecutionPolicy Bypass -File training\pull_models.ps1
param([string[]]$Models = @("qwen3.5:4b", "qwen3.5:9b"), [int]$MaxAttempts = 40)
$log = Join-Path $env:TEMP "bist_pull_models.log"
foreach ($m in $Models) {
    for ($i = 1; $i -le $MaxAttempts; $i++) {
        if ((ollama list) -match [regex]::Escape($m)) { Add-Content $log "$(Get-Date -Format s) $m READY"; break }
        Add-Content $log "$(Get-Date -Format s) $m attempt $i"
        $err = Join-Path $env:TEMP "bist_pull_attempt.txt"
        $p = Start-Process -FilePath "ollama" -ArgumentList "pull", $m -NoNewWindow -PassThru -Wait `
            -RedirectStandardError $err -RedirectStandardOutput "$err.out"
        $last = ((Get-Content $err -Raw -Encoding utf8) -split "`r|`n" | Where-Object { $_ -match '\S' } |
            Select-Object -Last 1) -replace '\x1b\[[0-9;?]*[A-Za-z]', ''
        Add-Content $log "$(Get-Date -Format s) $m exit $($p.ExitCode): $($last.Substring(0, [Math]::Min(160, $last.Length)))"
        Start-Sleep -Seconds 10
    }
}
ollama list
