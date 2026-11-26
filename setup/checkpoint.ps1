[CmdletBinding()]
param(
    [string]$Operation,
    [ValidateSet('pending', 'in_progress', 'failed', 'completed')]
    [string]$Status,
    [string]$Fingerprint,
    [string]$Detail
)

function Read-Checkpoint([string]$Root) {
    $path = Join-Path $Root 'CHECKPOINT.json'
    $state = Get-Content -LiteralPath $path -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    if ($state.schema_version -ne 1 -or $state.branch -ne 'feature/speech-layer' -or
        $state.baseline_commit -notmatch '^[a-f0-9]{40}$' -or $state.entries -isnot [PSCustomObject]) {
        throw "Invalid checkpoint: $path"
    }
    foreach ($entry in $state.entries.PSObject.Properties) {
        if ($entry.Value.status -notin 'pending', 'in_progress', 'failed', 'completed') {
            throw "Invalid checkpoint status for $($entry.Name)"
        }
    }
    $state
}

function Open-CheckpointLock([string]$Root, [string]$Name) {
    $directory = Join-Path $Root '.assets'
    New-Item -ItemType Directory -Force -Path $directory -ErrorAction Stop | Out-Null
    [IO.File]::Open((Join-Path $directory $Name), 'OpenOrCreate', 'ReadWrite', 'None')
}

function Write-CheckpointEntry(
    [string]$Root, [string]$Name, [string]$NewStatus, [string]$Identity, [string]$Message
) {
    if ($Name -notmatch '^[a-z0-9][a-z0-9_.-]*$' -or
        $NewStatus -notin 'pending', 'in_progress', 'failed', 'completed' -or
        ($Identity -and $Identity -notmatch '^[0-9a-f]{64}$')) {
        throw 'Invalid checkpoint operation, status or SHA-256 fingerprint'
    }
    if ($NewStatus -eq 'completed' -and (!$Identity -or !$Message)) {
        throw 'Completion requires a fingerprint and verification detail'
    }

    $lock = Open-CheckpointLock $Root 'checkpoint.lock'
    $path = Join-Path $Root 'CHECKPOINT.json'
    $temp = Join-Path $Root ('.CHECKPOINT.' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        $state = Read-Checkpoint $Root
        $entry = [PSCustomObject][ordered]@{
            status = $NewStatus
            updated_at = [DateTimeOffset]::UtcNow.ToString('o')
        }
        if ($Identity) { $entry | Add-Member -NotePropertyName fingerprint -NotePropertyValue $Identity }
        if ($Message) { $entry | Add-Member -NotePropertyName detail -NotePropertyValue $Message }
        $state.entries | Add-Member -NotePropertyName $Name -NotePropertyValue $entry -Force

        $json = ($state | ConvertTo-Json -Depth 8) + [Environment]::NewLine
        $bytes = [Text.UTF8Encoding]::new($false).GetBytes($json)
        $stream = [IO.File]::Open($temp, 'CreateNew', 'Write', 'None')
        try {
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush($true)
        } finally {
            $stream.Dispose()
        }
        [IO.File]::Replace($temp, $path, [NullString]::Value)
    } finally {
        try {
            if ([IO.File]::Exists($temp)) { [IO.File]::Delete($temp) }
        } finally {
            $lock.Dispose()
        }
    }
}

if ($MyInvocation.InvocationName -ne '.') {
    $root = Split-Path -Parent $PSScriptRoot
    if ($Operation) {
        Write-CheckpointEntry $root $Operation $Status $Fingerprint $Detail
    } else {
        Read-Checkpoint $root | ConvertTo-Json -Depth 8
    }
}
