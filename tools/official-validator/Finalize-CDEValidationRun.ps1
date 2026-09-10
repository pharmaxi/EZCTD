[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RunDirectory
)

$ErrorActionPreference = "Stop"
$runDir = (Resolve-Path -LiteralPath $RunDirectory).Path
$rawDir = Join-Path $runDir "raw-report"
if (-not (Test-Path -LiteralPath $rawDir)) {
    throw "Missing raw-report directory: $rawDir"
}

$reportFiles = Get-ChildItem -LiteralPath $rawDir -File -Recurse | Sort-Object FullName | ForEach-Object {
    [ordered]@{
        relative_path = [System.IO.Path]::GetRelativePath($runDir, $_.FullName).Replace("\\", "/")
        size = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        last_write_time_utc = $_.LastWriteTimeUtc.ToString("o")
    }
}

if (@($reportFiles).Count -eq 0) {
    throw "No official report evidence found under $rawDir"
}

@{
    schema_version = "0.1.0"
    finalized_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    files = @($reportFiles)
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runDir "output-manifest.json") -Encoding UTF8

$observationPath = Join-Path $runDir "observation.json"
$observation = Get-Content -LiteralPath $observationPath -Raw | ConvertFrom-Json
$observation.state = "RAW_EVIDENCE_CAPTURED"
$observation.review_status = "NOT_REVIEWED"
$observation | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $observationPath -Encoding UTF8

Write-Host "Evidence finalized: $runDir"
Write-Host "Next: enter official findings in observation.json and review against the JSON schema."
