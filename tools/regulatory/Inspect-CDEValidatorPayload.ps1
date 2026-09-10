param(
  [Parameter(Mandatory = $true)]
  [string]$InstallerPath,
  [string]$OutputDirectory = "build/cde-validator-payload-inspection"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-Sha256([string]$Path) {
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-RelativePath([string]$Base, [string]$Path) {
  return [IO.Path]::GetRelativePath((Resolve-Path -LiteralPath $Base).Path, (Resolve-Path -LiteralPath $Path).Path).Replace('\\','/')
}

function Resolve-7Zip {
  $command = Get-Command 7z -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }
  $candidates = @(
    "$env:ProgramFiles\7-Zip\7z.exe",
    "${env:ProgramFiles(x86)}\7-Zip\7z.exe",
    "C:\ProgramData\chocolatey\bin\7z.exe"
  )
  foreach ($candidate in $candidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
  }
  throw "7-Zip was not found"
}

function Get-BinaryAsciiText([string]$Path) {
  $bytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Path).Path)
  return [Text.Encoding]::ASCII.GetString($bytes)
}

function Get-PeMachine([string]$Path) {
  try {
    $stream = [IO.File]::OpenRead((Resolve-Path -LiteralPath $Path).Path)
    try {
      $reader = New-Object IO.BinaryReader($stream)
      if ($reader.ReadUInt16() -ne 0x5A4D) { return $null }
      $stream.Position = 0x3C
      $offset = $reader.ReadUInt32()
      $stream.Position = $offset
      if ($reader.ReadUInt32() -ne 0x00004550) { return $null }
      $machine = $reader.ReadUInt16()
      switch ($machine) {
        0x014c { return "x86" }
        0x8664 { return "x64" }
        0x01c4 { return "ARMv7" }
        0xaa64 { return "ARM64" }
        default { return ("0x{0:x4}" -f $machine) }
      }
    } finally {
      $stream.Dispose()
    }
  } catch {
    return $null
  }
}

function Get-StaticFileRecord([string]$Base, [System.IO.FileInfo]$File) {
  $record = [ordered]@{
    path = Get-RelativePath $Base $File.FullName
    size = $File.Length
    sha256 = Get-Sha256 $File.FullName
    extension = $File.Extension.ToLowerInvariant()
    authenticode = $null
    version_info = $null
    pe_machine = $null
  }
  if ($File.Extension.ToLowerInvariant() -in @('.exe', '.dll', '.msi', '.cat')) {
    try {
      $signature = Get-AuthenticodeSignature -LiteralPath $File.FullName
      $record.authenticode = [ordered]@{
        status = [string]$signature.Status
        status_message = $signature.StatusMessage
        signer_subject = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
        signer_issuer = if ($signature.SignerCertificate) { $signature.SignerCertificate.Issuer } else { $null }
        signer_thumbprint = if ($signature.SignerCertificate) { $signature.SignerCertificate.Thumbprint } else { $null }
      }
    } catch {
      $record.authenticode = [ordered]@{ status = "INSPECTION_ERROR"; status_message = $_.Exception.Message }
    }
  }
  if ($File.Extension.ToLowerInvariant() -in @('.exe', '.dll')) {
    $record.pe_machine = Get-PeMachine $File.FullName
    try {
      $version = [Diagnostics.FileVersionInfo]::GetVersionInfo($File.FullName)
      $record.version_info = [ordered]@{
        product_name = $version.ProductName
        product_version = $version.ProductVersion
        file_version = $version.FileVersion
        company_name = $version.CompanyName
        file_description = $version.FileDescription
        original_filename = $version.OriginalFilename
        internal_name = $version.InternalName
      }
    } catch {
      $record.version_info = [ordered]@{ inspection_error = $_.Exception.Message }
    }
  }
  return $record
}

$installer = Get-Item -LiteralPath $InstallerPath
if (-not $installer.Exists) { throw "Installer not found: $InstallerPath" }

$sevenZip = Resolve-7Zip
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$extractRoot = Join-Path $OutputDirectory "payload"
if (Test-Path -LiteralPath $extractRoot) { Remove-Item -LiteralPath $extractRoot -Recurse -Force }
New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null

$installerText = Get-BinaryAsciiText $installer.FullName
$installerFormat = if ($installerText -match 'Nullsoft\.NSIS|Nullsoft Install System|NullsoftInst') {
  "NSIS"
} elseif ($installerText -match 'Inno Setup') {
  "INNO_SETUP"
} else {
  "UNKNOWN_SELF_EXTRACTOR"
}
$requiresAdministrator = $installerText -match 'requireAdministrator'

$listPath = Join-Path $OutputDirectory "installer-7z-list.txt"
$listOutput = & $sevenZip l -slt -- $installer.FullName 2>&1
$listExit = $LASTEXITCODE
$listOutput | Set-Content -LiteralPath $listPath -Encoding UTF8
if ($listExit -ne 0) { throw "7-Zip could not list installer payload; exit=$listExit" }

$extractLog = Join-Path $OutputDirectory "installer-7z-extract.txt"
$extractOutput = & $sevenZip x -y -aoa "-o$extractRoot" -- $installer.FullName 2>&1
$extractExit = $LASTEXITCODE
$extractOutput | Set-Content -LiteralPath $extractLog -Encoding UTF8
if ($extractExit -ne 0) { throw "7-Zip could not extract installer payload; exit=$extractExit" }

$files = @(Get-ChildItem -LiteralPath $extractRoot -File -Recurse | Sort-Object FullName)
$inventory = @($files | ForEach-Object { Get-StaticFileRecord $extractRoot $_ })
$executables = @($inventory | Where-Object { $_.extension -eq '.exe' })
$libraries = @($inventory | Where-Object { $_.extension -eq '.dll' })
$jars = @($inventory | Where-Object { $_.extension -eq '.jar' })
$configFiles = @($inventory | Where-Object { $_.extension -in @('.ini', '.conf', '.config', '.properties', '.xml', '.json', '.yaml', '.yml') })

$pathCorpus = ($inventory | ForEach-Object { $_.path.ToLowerInvariant() }) -join "`n"
$runtimeSignals = [ordered]@{
  java = ($jars.Count -gt 0 -or $pathCorpus -match '(^|/)jre/|java\.exe|javaw\.exe')
  dotnet = ($pathCorpus -match '\.runtimeconfig\.json|hostfxr\.dll|coreclr\.dll')
  electron = ($pathCorpus -match 'app\.asar|electron\.exe')
  qt = ($pathCorpus -match 'qt5core\.dll|qt6core\.dll')
}

$entryPointCandidates = @(
  $executables |
    Where-Object {
      $_.path -notmatch '(?i)(^|/)(uninst|uninstall|java|javaw|javaws|javac|keytool|jabswitch|jp2launcher|ssvagent|jucheck|jusched)([^/]*)\.exe$'
    } |
    Sort-Object path
)

$installerSignature = Get-AuthenticodeSignature -LiteralPath $installer.FullName
$installerVersion = [Diagnostics.FileVersionInfo]::GetVersionInfo($installer.FullName)
$payload = [ordered]@{
  schema_version = "0.1.0"
  generated_at = (Get-Date).ToUniversalTime().ToString('o')
  safety_scope = "Recursive static extraction, hashing, Authenticode, PE architecture, version resources and archive inventory only. No installer or extracted executable was launched. No decompilation was performed."
  installer = [ordered]@{
    file_name = $installer.Name
    size = $installer.Length
    sha256 = Get-Sha256 $installer.FullName
    format = $installerFormat
    requires_administrator = $requiresAdministrator
    pe_machine = Get-PeMachine $installer.FullName
    authenticode = [ordered]@{
      status = [string]$installerSignature.Status
      status_message = $installerSignature.StatusMessage
      signer_subject = if ($installerSignature.SignerCertificate) { $installerSignature.SignerCertificate.Subject } else { $null }
      signer_thumbprint = if ($installerSignature.SignerCertificate) { $installerSignature.SignerCertificate.Thumbprint } else { $null }
    }
    version_info = [ordered]@{
      product_name = $installerVersion.ProductName
      product_version = $installerVersion.ProductVersion
      file_version = $installerVersion.FileVersion
      company_name = $installerVersion.CompanyName
      file_description = $installerVersion.FileDescription
    }
  }
  extraction = [ordered]@{
    tool = $sevenZip
    list_exit_code = $listExit
    extract_exit_code = $extractExit
    status = "SUCCESS_STATIC_EXTRACTION"
    file_count = $inventory.Count
    total_bytes = [int64](($files | Measure-Object -Property Length -Sum).Sum)
  }
  runtime_signals = $runtimeSignals
  counts = [ordered]@{
    executables = $executables.Count
    libraries = $libraries.Count
    jars = $jars.Count
    config_files = $configFiles.Count
    entry_point_candidates = $entryPointCandidates.Count
  }
  entry_point_candidates = $entryPointCandidates
  executables = $executables
  jars = $jars
  config_files = $configFiles
  inventory = $inventory
  interpretation = [ordered]@{
    official_identity_basis = "Official portal URL and outer ZIP hash must remain the primary provenance. The extracted installer is unsigned and has no reliable vendor version resource."
    execution_gate = "Use only an ephemeral Windows environment, pin both outer ZIP and installer hashes, and record installation and process side effects before attempting a validation run."
    observation_count = 0
  }
}

$jsonPath = Join-Path $OutputDirectory "payload-static-inspection.json"
$payload | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

$lines = @(
  "# CDE eCTD validator V1.1.0 payload — recursive static inspection",
  "",
  "- Installer format: **$installerFormat**",
  "- Installer SHA-256: ``$($payload.installer.sha256)``",
  "- PE architecture: **$($payload.installer.pe_machine)**",
  "- Requires administrator: **$requiresAdministrator**",
  "- Authenticode: **$($payload.installer.authenticode.status)**",
  "- Extracted files: **$($payload.extraction.file_count)**",
  "- Extracted bytes: **$($payload.extraction.total_bytes)**",
  "- Executables: **$($payload.counts.executables)**",
  "- JAR files: **$($payload.counts.jars)**",
  "- Candidate application entry points: **$($payload.counts.entry_point_candidates)**",
  "- Official black-box observations: **0**",
  "",
  "## Runtime signals",
  "",
  "| Runtime | Detected |",
  "|---|---:|",
  "| Java | $($runtimeSignals.java) |",
  "| .NET | $($runtimeSignals.dotnet) |",
  "| Electron | $($runtimeSignals.electron) |",
  "| Qt | $($runtimeSignals.qt) |",
  "",
  "## Candidate entry points",
  "",
  "| Path | Architecture | Signature | Product | Version | SHA-256 |",
  "|---|---|---|---|---|---|"
)
foreach ($item in $entryPointCandidates) {
  $signature = if ($item.authenticode) { $item.authenticode.status } else { "n/a" }
  $product = if ($item.version_info) { $item.version_info.product_name } else { "n/a" }
  $version = if ($item.version_info) { $item.version_info.product_version } else { "n/a" }
  $lines += "| $($item.path) | $($item.pe_machine) | $signature | $product | $version | ``$($item.sha256)`` |"
}
$lines += @(
  "",
  "## Interpretation",
  "",
  "The absence of an Authenticode signature or populated version resource does not negate official provenance, because the bytes were obtained through the current CDE portal and pinned by the outer ZIP hash. It does mean that execution must be isolated and that identity must be checked by the complete provenance chain rather than by Windows publisher metadata alone.",
  "",
  "This report is static evidence only. Listing or extracting an installer is not an official validator black-box observation.",
  ""
)
$lines -join "`n" | Set-Content -LiteralPath (Join-Path $OutputDirectory "payload-static-inspection.md") -Encoding UTF8

Write-Host ($payload | ConvertTo-Json -Depth 5)
