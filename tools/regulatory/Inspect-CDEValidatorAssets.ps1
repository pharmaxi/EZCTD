param(
  [string]$SourceDirectory = "build/regulatory-source-snapshot/assets",
  [string]$OutputDirectory = "build/cde-validator-inspection",
  [string]$EvidenceDirectory = "evidence/regulatory/snapshots/cde-validator-v1.1.0"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutputDirectory, $EvidenceDirectory | Out-Null
$extractedRoot = Join-Path $OutputDirectory "extracted"
New-Item -ItemType Directory -Force -Path $extractedRoot | Out-Null

function Get-Sha256([string]$Path) {
  return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-RelativePath([string]$Base, [string]$Path) {
  return [IO.Path]::GetRelativePath((Resolve-Path $Base).Path, (Resolve-Path $Path).Path).Replace('\\','/')
}

function Test-LikelyValidator([System.IO.FileInfo]$File, [string[]]$MemberNames) {
  $haystack = (($File.Name + " " + ($MemberNames -join " ")).ToLowerInvariant())
  return ($haystack -match "ectd" -and $haystack -match "valid|验证|validator|validate")
}

$records = @()
$sourceExists = Test-Path $SourceDirectory
$files = @()
if ($sourceExists) {
  $files = @(Get-ChildItem -Path $SourceDirectory -File -Recurse | Sort-Object FullName)
}

foreach ($file in $files) {
  $record = [ordered]@{
    source_path = Get-RelativePath $SourceDirectory $file.FullName
    file_name = $file.Name
    size = $file.Length
    sha256 = Get-Sha256 $file.FullName
    extension = $file.Extension.ToLowerInvariant()
    authenticode = $null
    version_info = $null
    archive = [ordered]@{ status = "NOT_ARCHIVE"; members = @(); extraction_status = "NOT_ATTEMPTED"; extracted_inventory = @() }
    likely_validator_asset = $false
    notes = @()
  }

  if ($file.Extension -in @('.exe', '.dll', '.msi', '.ps1', '.cat')) {
    try {
      $sig = Get-AuthenticodeSignature -FilePath $file.FullName
      $record.authenticode = [ordered]@{
        status = [string]$sig.Status
        status_message = $sig.StatusMessage
        signer_subject = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { $null }
        signer_issuer = if ($sig.SignerCertificate) { $sig.SignerCertificate.Issuer } else { $null }
        signer_thumbprint = if ($sig.SignerCertificate) { $sig.SignerCertificate.Thumbprint } else { $null }
        timestamp_subject = if ($sig.TimeStamperCertificate) { $sig.TimeStamperCertificate.Subject } else { $null }
      }
    } catch {
      $record.notes += "Authenticode inspection failed: $($_.Exception.Message)"
    }
  }

  if ($file.Extension -in @('.exe', '.dll')) {
    try {
      $vi = [Diagnostics.FileVersionInfo]::GetVersionInfo($file.FullName)
      $record.version_info = [ordered]@{
        product_name = $vi.ProductName
        product_version = $vi.ProductVersion
        file_version = $vi.FileVersion
        company_name = $vi.CompanyName
        original_filename = $vi.OriginalFilename
        internal_name = $vi.InternalName
        legal_copyright = $vi.LegalCopyright
      }
    } catch {
      $record.notes += "Version resource inspection failed: $($_.Exception.Message)"
    }
  }

  $archiveCandidate = $file.Extension -in @('.zip','.rar','.7z','.exe','.msi')
  $memberNames = @()
  if ($archiveCandidate -and (Get-Command 7z -ErrorAction SilentlyContinue)) {
    try {
      $listing = & 7z l -slt -- $file.FullName 2>&1
      if ($LASTEXITCODE -eq 0 -and ($listing -match "Path =")) {
        $members = @()
        $current = [ordered]@{}
        foreach ($line in $listing) {
          if ([string]::IsNullOrWhiteSpace($line)) {
            if ($current.Contains('Path') -and $current.Path -ne $file.FullName -and $current.Path -ne $file.Name) {
              $members += [ordered]@{
                path = $current.Path
                size = if ($current.Contains('Size')) { [int64]$current.Size } else { $null }
                packed_size = if ($current.Contains('Packed Size')) { [int64]$current.'Packed Size' } else { $null }
                modified = if ($current.Contains('Modified')) { $current.Modified } else { $null }
                attributes = if ($current.Contains('Attributes')) { $current.Attributes } else { $null }
              }
            }
            $current = [ordered]@{}
            continue
          }
          if ($line -match '^([^=]+) = (.*)$') {
            $current[$matches[1].Trim()] = $matches[2].Trim()
          }
        }
        if ($current.Contains('Path') -and $current.Path -ne $file.FullName -and $current.Path -ne $file.Name) {
          $members += [ordered]@{ path=$current.Path; size=if($current.Contains('Size')){[int64]$current.Size}else{$null}; packed_size=if($current.Contains('Packed Size')){[int64]$current.'Packed Size'}else{$null}; modified=if($current.Contains('Modified')){$current.Modified}else{$null}; attributes=if($current.Contains('Attributes')){$current.Attributes}else{$null} }
        }
        $memberNames = @($members | ForEach-Object { $_.path })
        $record.archive.status = "LISTED"
        $record.archive.members = $members

        $extractDir = Join-Path $extractedRoot (($record.sha256).Substring(0,16))
        New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
        & 7z x -y -aoa "-o$extractDir" -- $file.FullName | Out-Null
        if ($LASTEXITCODE -eq 0) {
          $record.archive.extraction_status = "EXTRACTED_FOR_METADATA_ONLY"
          $inventory = @()
          Get-ChildItem -Path $extractDir -File -Recurse | Sort-Object FullName | ForEach-Object {
            $rel = Get-RelativePath $extractDir $_.FullName
            $entry = [ordered]@{
              path = $rel
              size = $_.Length
              sha256 = Get-Sha256 $_.FullName
              extension = $_.Extension.ToLowerInvariant()
              authenticode = $null
              version_info = $null
            }
            if ($_.Extension -in @('.exe','.dll','.msi','.cat')) {
              try {
                $s = Get-AuthenticodeSignature -FilePath $_.FullName
                $entry.authenticode = [ordered]@{ status=[string]$s.Status; signer_subject=if($s.SignerCertificate){$s.SignerCertificate.Subject}else{$null}; signer_thumbprint=if($s.SignerCertificate){$s.SignerCertificate.Thumbprint}else{$null} }
              } catch {}
            }
            if ($_.Extension -in @('.exe','.dll')) {
              try {
                $v = [Diagnostics.FileVersionInfo]::GetVersionInfo($_.FullName)
                $entry.version_info = [ordered]@{ product_name=$v.ProductName; product_version=$v.ProductVersion; file_version=$v.FileVersion; company_name=$v.CompanyName; original_filename=$v.OriginalFilename }
              } catch {}
            }
            $inventory += $entry
          }
          $record.archive.extracted_inventory = $inventory
          $memberNames += @($inventory | ForEach-Object { $_.path })
        } else {
          $record.archive.extraction_status = "EXTRACTION_FAILED"
        }
      }
    } catch {
      $record.archive.status = "INSPECTION_ERROR"
      $record.notes += "7-Zip inspection failed: $($_.Exception.Message)"
    }
  }

  $record.likely_validator_asset = Test-LikelyValidator $file $memberNames
  $records += $record
}

$likely = @($records | Where-Object { $_.likely_validator_asset })
$status = if (-not $sourceExists) { "SOURCE_DIRECTORY_MISSING" } elseif ($likely.Count -gt 0) { "CANDIDATE_FOUND" } else { "UNRESOLVED_NO_CONFIRMED_VALIDATOR_ASSET" }

$payload = [ordered]@{
  schema_version = "0.1.0"
  generated_at = (Get-Date).ToUniversalTime().ToString('o')
  generator = "tools/regulatory/Inspect-CDEValidatorAssets.ps1"
  status = $status
  safety_scope = "Static metadata, hashes, Authenticode, version resources and archive listings only. No installer or executable was launched. No decompilation was performed."
  expected_product = [ordered]@{ name="CDE eCTD validation software"; target_version="1.1.0"; effective_date="2026-03-01" }
  source_directory = $SourceDirectory
  source_exists = $sourceExists
  files_inspected = $records.Count
  likely_candidates = $likely.Count
  records = $records
  unresolved = if ($likely.Count -eq 0) { @("No asset was automatically confirmed as CDE eCTD validation software V1.1.0. Manual retrieval from the CDE common-download page may still be required.") } else { @() }
}

$jsonPath = Join-Path $EvidenceDirectory "inspection.json"
$payload | ConvertTo-Json -Depth 20 | Set-Content -Path $jsonPath -Encoding UTF8

$lines = @(
  "# CDE eCTD validation software V1.1.0 asset inspection",
  "",
  "- Status: **$status**",
  "- Files inspected: $($records.Count)",
  "- Likely candidates: $($likely.Count)",
  "- Safety scope: static metadata only; nothing was executed or decompiled.",
  "",
  "## Candidate summary",
  "",
  "| File | Size | SHA-256 | Signature | Product version | Candidate |",
  "|---|---:|---|---|---|---:|"
)
foreach ($record in $records) {
  $signature = if ($record.authenticode) { $record.authenticode.status } else { "n/a" }
  $version = if ($record.version_info) { $record.version_info.product_version } else { "n/a" }
  $lines += "| $($record.source_path) | $($record.size) | ``$($record.sha256)`` | $signature | $version | $($record.likely_validator_asset) |"
}
$lines += @(
  "",
  "## Interpretation",
  "",
  "`UNRESOLVED_NO_CONFIRMED_VALIDATOR_ASSET` does not mean the official asset does not exist. CDE downloads can be dynamically linked or require manual navigation. Only a candidate with official provenance, matching product/version metadata and recorded hash may be used in P0-B0-B.",
  ""
)
$lines -join "`n" | Set-Content -Path (Join-Path $EvidenceDirectory "README.md") -Encoding UTF8

Write-Host ($payload | ConvertTo-Json -Depth 4)
