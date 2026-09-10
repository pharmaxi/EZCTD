param(
  [Parameter(Mandatory=$true)][string]$PreparedPackageRoot,
  [Parameter(Mandatory=$true)][string]$EvidenceRoot,
  [string]$ValidatorVersion = "1.1.0",
  [string]$ValidatorBinary = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path
$RunPlanPath = Join-Path $RepoRoot "tests/p0_b0/official-validator/calibration_run_plan.json"
$CaptureScript = Join-Path $PSScriptRoot "capture-validator-run.ps1"

if (!(Test-Path $PreparedPackageRoot -PathType Container)) { throw "Prepared package root not found: $PreparedPackageRoot" }
if (!(Test-Path $RunPlanPath -PathType Leaf)) { throw "Run plan missing: $RunPlanPath" }
New-Item -ItemType Directory -Force -Path $EvidenceRoot | Out-Null

$plan = Get-Content $RunPlanPath -Raw | ConvertFrom-Json
if ($plan.status -ne "NOT_RUN") { throw "Run plan source must remain NOT_RUN" }
if ($plan.runs.Count -ne $plan.expected_run_count) { throw "Run-plan count mismatch" }

$instantiated = @()
foreach ($run in $plan.runs) {
  $package = Join-Path $PreparedPackageRoot $run.case_id
  if (!(Test-Path $package -PathType Container)) { throw "Prepared package missing for $($run.run_id): $package" }

  # capture-validator-run uses the supplied ID as the evidence folder. Use run_id rather
  # than case_id so repeated baseline controls remain independent evidence records.
  & $CaptureScript `
    -CaseId $run.run_id `
    -InputPackage $package `
    -OutputRoot $EvidenceRoot `
    -ValidatorVersion $ValidatorVersion `
    -ValidatorBinary $ValidatorBinary

  $resultPath = Join-Path (Join-Path $EvidenceRoot $run.run_id) "result.json"
  $result = Get-Content $resultPath -Raw | ConvertFrom-Json
  $result | Add-Member -NotePropertyName source_case_id -NotePropertyValue $run.case_id -Force
  $result | Add-Member -NotePropertyName run_role -NotePropertyValue $run.role -Force
  $result | Add-Member -NotePropertyName restart_before -NotePropertyValue ([bool]$run.restart_before) -Force
  $result | ConvertTo-Json -Depth 12 | Set-Content $resultPath -Encoding UTF8

  $instantiated += [ordered]@{
    run_id = $run.run_id
    case_id = $run.case_id
    role = $run.role
    restart_before = [bool]$run.restart_before
    package_path = (Resolve-Path $package).Path
    evidence_path = (Resolve-Path (Join-Path $EvidenceRoot $run.run_id)).Path
  }
}

$batch = [ordered]@{
  schema_version = "0.1.0"
  batch_id = $plan.batch_id
  created_at = (Get-Date).ToUniversalTime().ToString('o')
  validator_target = $plan.validator_target
  validator_version = $ValidatorVersion
  run_count = $instantiated.Count
  status = "PREPARED_NOT_RUN"
  runs = $instantiated
}
$batch | ConvertTo-Json -Depth 12 | Set-Content (Join-Path $EvidenceRoot "run-plan-instance.json") -Encoding UTF8

Write-Host "Prepared $($instantiated.Count) independent run evidence folders."
Write-Host "Execute in listed order. Respect restart_before flags. Finalize each result before aggregation."
