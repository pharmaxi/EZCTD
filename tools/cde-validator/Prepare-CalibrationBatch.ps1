param(
  [Parameter(Mandatory=$true)][string]$BaselineSequence,
  [Parameter(Mandatory=$true)][string]$SmokeDirectory,
  [Parameter(Mandatory=$true)][string]$LeafRelativePath,
  [string]$OutputRoot = "build/cde-validator-calibration-01",
  [string]$EvidenceRoot = "build/cde-validator-calibration-evidence",
  [string]$ValidatorVersion = "1.1.0",
  [string]$ValidatorBinary = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$Manifest = Join-Path $RepoRoot "tests/p0_b0/official-validator/calibration_manifest.json"
$PrepareScript = Join-Path $RepoRoot "tests/p0_b0/prepare_differential_packages.py"
$CaptureScript = Join-Path $PSScriptRoot "capture-validator-run.ps1"

if (!(Test-Path $BaselineSequence -PathType Container)) { throw "Baseline sequence directory not found: $BaselineSequence" }
if (!(Test-Path $SmokeDirectory -PathType Container)) { throw "Smoke directory not found: $SmokeDirectory" }
if (!(Test-Path $Manifest -PathType Leaf)) { throw "Calibration manifest missing: $Manifest" }
if (!(Test-Path $PrepareScript -PathType Leaf)) { throw "Differential package script missing: $PrepareScript" }
if (!(Test-Path (Join-Path $BaselineSequence $LeafRelativePath) -PathType Leaf)) { throw "Baseline replacement leaf not found: $LeafRelativePath" }

$manifestPayload = Get-Content $Manifest -Raw | ConvertFrom-Json
if ($manifestPayload.status -ne "NOT_RUN") { throw "Calibration manifest is not in NOT_RUN state" }
if ($manifestPayload.cases.Count -ne $manifestPayload.expected_case_count) { throw "Calibration case-count mismatch" }

foreach ($case in $manifestPayload.cases) {
  $pdf = Join-Path $SmokeDirectory $case.file_name
  if (!(Test-Path $pdf -PathType Leaf)) { throw "Smoke PDF missing: $pdf" }
}

New-Item -ItemType Directory -Force -Path $OutputRoot, $EvidenceRoot | Out-Null

python $PrepareScript `
  --baseline $BaselineSequence `
  --smoke-dir $SmokeDirectory `
  --manifest $Manifest `
  --leaf $LeafRelativePath `
  --output $OutputRoot
if ($LASTEXITCODE -ne 0) { throw "Differential package preparation failed" }

$batchInventory = @()
foreach ($case in $manifestPayload.cases) {
  $package = Join-Path $OutputRoot $case.case_id
  if (!(Test-Path $package -PathType Container)) { throw "Prepared package missing: $package" }
  & $CaptureScript `
    -CaseId $case.case_id `
    -InputPackage $package `
    -OutputRoot $EvidenceRoot `
    -ValidatorVersion $ValidatorVersion `
    -ValidatorBinary $ValidatorBinary
  $batchInventory += [ordered]@{
    case_id = $case.case_id
    rule_id = $case.rule_id
    role = $case.role
    package_path = (Resolve-Path $package).Path
    evidence_path = (Resolve-Path (Join-Path $EvidenceRoot $case.case_id)).Path
    questions = $case.questions
  }
}

$batch = [ordered]@{
  schema_version = "0.1.0"
  batch_id = $manifestPayload.batch_id
  created_at = (Get-Date).ToUniversalTime().ToString('o')
  validator_target = $manifestPayload.validator_target
  validator_version = $ValidatorVersion
  validator_binary_sha256 = if ($ValidatorBinary -and (Test-Path $ValidatorBinary)) { (Get-FileHash $ValidatorBinary -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null }
  baseline_path = (Resolve-Path $BaselineSequence).Path
  baseline_inventory = @(
    Get-ChildItem -Path $BaselineSequence -File -Recurse | Sort-Object FullName | ForEach-Object {
      [ordered]@{
        path = [IO.Path]::GetRelativePath((Resolve-Path $BaselineSequence).Path, $_.FullName).Replace('\\','/')
        size = $_.Length
        sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
      }
    }
  )
  leaf_relative_path = $LeafRelativePath.Replace('\\','/')
  cases = $batchInventory
  official_observations = 0
  status = "PREPARED_NOT_RUN"
}

$batch | ConvertTo-Json -Depth 20 | Set-Content -Path (Join-Path $EvidenceRoot "batch.json") -Encoding UTF8

Write-Host "Prepared $($batchInventory.Count) calibration packages."
Write-Host "Run the official CDE validator manually for each package, preserve complete reports/screenshots, edit result.json, and finalize with Finalize-OfficialRun.ps1."
