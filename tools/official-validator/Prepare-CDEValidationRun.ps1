[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$CaseId,
    [Parameter(Mandatory = $true)][string]$SequencePath,
    [Parameter(Mandatory = $true)][string]$ValidatorExe,
    [Parameter(Mandatory = $true)][string]$EvidenceRoot,
    [string]$InstallerPath,
    [string]$ManualPath,
    [switch]$LaunchValidator
)

$ErrorActionPreference = "Stop"

function Get-FileRecord {
    param([string]$Path, [string]$BasePath)
    $item = Get-Item -LiteralPath $Path
    $relative = [System.IO.Path]::GetRelativePath($BasePath, $item.FullName).Replace("\\", "/")
    return [ordered]@{
        relative_path = $relative
        size = $item.Length
        sha256 = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        last_write_time_utc = $item.LastWriteTimeUtc.ToString("o")
    }
}

$sequence = (Resolve-Path -LiteralPath $SequencePath).Path
$validator = (Resolve-Path -LiteralPath $ValidatorExe).Path
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$runId = "$CaseId-$timestamp"
$runDir = Join-Path $EvidenceRoot $runId
$rawDir = Join-Path $runDir "raw-report"
New-Item -ItemType Directory -Force -Path $rawDir | Out-Null

$files = Get-ChildItem -LiteralPath $sequence -File -Recurse | Sort-Object FullName | ForEach-Object {
    Get-FileRecord -Path $_.FullName -BasePath $sequence
}

$os = Get-CimInstance Win32_OperatingSystem
$culture = Get-Culture
$timeZone = Get-TimeZone
$validatorItem = Get-Item -LiteralPath $validator

$environment = [ordered]@{
    schema_version = "0.1.0"
    run_id = $runId
    case_id = $CaseId
    prepared_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    validator = [ordered]@{
        path = $validator
        file_version = $validatorItem.VersionInfo.FileVersion
        product_version = $validatorItem.VersionInfo.ProductVersion
        sha256 = (Get-FileHash -LiteralPath $validator -Algorithm SHA256).Hash.ToLowerInvariant()
        installer_path = if ($InstallerPath) { (Resolve-Path -LiteralPath $InstallerPath).Path } else { $null }
        installer_sha256 = if ($InstallerPath) { (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null }
        manual_path = if ($ManualPath) { (Resolve-Path -LiteralPath $ManualPath).Path } else { $null }
        manual_sha256 = if ($ManualPath) { (Get-FileHash -LiteralPath $ManualPath -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null }
    }
    os = [ordered]@{
        caption = $os.Caption
        version = $os.Version
        build_number = $os.BuildNumber
        architecture = $os.OSArchitecture
    }
    locale = $culture.Name
    timezone_id = $timeZone.Id
    sequence_path = $sequence
    sequence_file_count = @($files).Count
}

$environment | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runDir "environment.json") -Encoding UTF8
@{
    schema_version = "0.1.0"
    run_id = $runId
    case_id = $CaseId
    root = $sequence
    files = @($files)
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runDir "input-manifest.json") -Encoding UTF8

@{
    schema_version = "0.1.0"
    run_id = $runId
    case_id = $CaseId
    state = "PREPARED"
    operator_notes = $null
    official_findings = @()
    target_rule_observed_state = $null
    unexpected_rule_ids = @()
    repeat_run_equal = $null
    review_status = "NOT_REVIEWED"
} | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $runDir "observation.json") -Encoding UTF8

Write-Host "Prepared: $runDir"
Write-Host "Export the unmodified official report to: $rawDir"

if ($LaunchValidator) {
    Start-Process -FilePath $validator -Wait
}
