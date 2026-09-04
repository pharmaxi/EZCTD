param(
  [Parameter(Mandatory = $true)]
  [string]$PayloadDirectory,
  [string]$OutputDirectory = "build/cde-validator-launch-metadata"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-7Zip {
  $command = Get-Command 7z -ErrorAction SilentlyContinue
  if ($command) { return $command.Source }
  foreach ($candidate in @(
    "$env:ProgramFiles\7-Zip\7z.exe",
    "${env:ProgramFiles(x86)}\7-Zip\7z.exe",
    "C:\ProgramData\chocolatey\bin\7z.exe"
  )) {
    if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
  }
  throw "7-Zip not found"
}

function Get-Sha256([string]$Path) {
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Get-Relative([string]$Base, [string]$Path) {
  return [IO.Path]::GetRelativePath((Resolve-Path -LiteralPath $Base).Path, (Resolve-Path -LiteralPath $Path).Path).Replace('\\','/')
}

function Get-BinaryStrings([string]$Path, [int]$MinimumLength = 5) {
  $bytes = [IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Path).Path)
  $ascii = [Text.Encoding]::ASCII.GetString($bytes)
  $unicode = [Text.Encoding]::Unicode.GetString($bytes)
  $pattern = "[ -~]{$MinimumLength,}"
  $values = New-Object System.Collections.Generic.List[string]
  foreach ($text in @($ascii, $unicode)) {
    foreach ($match in [regex]::Matches($text, $pattern)) {
      $value = $match.Value.Trim()
      if ($value.Length -ge $MinimumLength) { $values.Add($value) }
    }
  }
  return @($values | Sort-Object -Unique)
}

function Get-ArchivePaths([string]$SevenZip, [string]$Archive) {
  $output = & $SevenZip l -slt -- $Archive 2>&1
  if ($LASTEXITCODE -ne 0) { throw "Unable to list archive: $Archive" }
  $paths = @()
  foreach ($line in $output) {
    if ($line -match '^Path = (.+)$') {
      $value = $matches[1].Trim().Replace('\\','/')
      if ($value -and $value -ne (Split-Path -Leaf $Archive)) { $paths += $value }
    }
  }
  return @($paths | Sort-Object -Unique)
}

function Get-JarManifest([string]$SevenZip, [string]$Jar) {
  $output = & $SevenZip e -so -- $Jar 'META-INF/MANIFEST.MF' 2>$null
  if ($LASTEXITCODE -ne 0) { return $null }
  return (($output | ForEach-Object { [string]$_ }) -join "`n").Trim()
}

$payloadRoot = (Resolve-Path -LiteralPath $PayloadDirectory).Path
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$sevenZip = Resolve-7Zip

$rootExecutables = @(Get-ChildItem -LiteralPath $payloadRoot -File -Filter '*.exe' | Sort-Object Name)
$applicationExecutables = @($rootExecutables | Where-Object { $_.Name -notmatch '^(?i:uninst|uninstall)' })
if ($applicationExecutables.Count -ne 1) {
  throw "Expected one root application executable, found $($applicationExecutables.Count): $($applicationExecutables.Name -join ', ')"
}
$app = $applicationExecutables[0]
$appSignature = Get-AuthenticodeSignature -LiteralPath $app.FullName
$appVersion = [Diagnostics.FileVersionInfo]::GetVersionInfo($app.FullName)

$allStrings = Get-BinaryStrings $app.FullName
$launcherMarkers = @(
  $allStrings |
    Where-Object {
      $_ -match '(?i)(\.jar|jre|javaw?|classpath|mainclass|launch4j|exe4j|-Xmx|-Xms|cde|ectd|validator|validation|report|log4j|config)'
    } |
    Select-Object -First 1000
)

$rootInventory = @(
  Get-ChildItem -LiteralPath $payloadRoot -File |
    Sort-Object Name |
    ForEach-Object {
      [ordered]@{
        path = $_.Name
        size = $_.Length
        sha256 = Get-Sha256 $_.FullName
        extension = $_.Extension.ToLowerInvariant()
      }
    }
)

$configRecords = @()
$configTargets = @(
  Get-ChildItem -LiteralPath $payloadRoot -File -Recurse |
    Where-Object {
      $relative = Get-Relative $payloadRoot $_.FullName
      $normalized = $relative.Replace('\\','/')
      $_.Length -le 65536 -and
      $_.Extension.ToLowerInvariant() -in @('.properties','.ini','.conf','.config','.json','.yaml','.yml') -and
      $normalized -notmatch '^(?i:jre)/'
    } |
    Sort-Object FullName
)
foreach ($file in $configTargets) {
  $content = Get-Content -Raw -LiteralPath $file.FullName -ErrorAction SilentlyContinue
  $configRecords += [ordered]@{
    path = Get-Relative $payloadRoot $file.FullName
    size = $file.Length
    sha256 = Get-Sha256 $file.FullName
    content = $content
  }
}

$jarRecords = @()
$applicationJars = @(
  Get-ChildItem -LiteralPath $payloadRoot -File -Filter '*.jar' |
    Sort-Object Name
)
foreach ($jar in $applicationJars) {
  $paths = Get-ArchivePaths $sevenZip $jar.FullName
  $manifest = Get-JarManifest $sevenZip $jar.FullName
  $interesting = @(
    $paths |
      Where-Object {
        $_ -match '(?i)(^|/)(main|application|app|validator|validation|report|controller|service|view|ui|window|stage|launcher)[^/]*\.(class|fxml)$' -or
        $_ -match '(?i)\.(fxml|css)$' -or
        $_ -match '(?i)(report|validation|validator|main|application).*\.class$'
      } |
      Select-Object -First 500
  )
  $mainClass = $null
  if ($manifest -and $manifest -match '(?im)^Main-Class:\s*(.+)$') {
    $mainClass = $matches[1].Trim()
  }
  $jarRecords += [ordered]@{
    path = $jar.Name
    size = $jar.Length
    sha256 = Get-Sha256 $jar.FullName
    manifest = $manifest
    main_class = $mainClass
    entry_count = $paths.Count
    interesting_entries = $interesting
    fxml_count = @($paths | Where-Object { $_ -match '(?i)\.fxml$' }).Count
    class_count = @($paths | Where-Object { $_ -match '(?i)\.class$' }).Count
  }
}

$allJarPaths = @($jarRecords | ForEach-Object { $_.interesting_entries })
$uiSignals = [ordered]@{
  javafx_fxml = @($jarRecords | Where-Object { $_.fxml_count -gt 0 }).Count -gt 0
  swing_names = @($allJarPaths | Where-Object { $_ -match '(?i)(swing|jframe|jdialog)' }).Count -gt 0
  report_names = @($allJarPaths | Where-Object { $_ -match '(?i)report' }).Count -gt 0
  validator_names = @($allJarPaths | Where-Object { $_ -match '(?i)validat' }).Count -gt 0
}

$payload = [ordered]@{
  schema_version = "0.1.0"
  generated_at = (Get-Date).ToUniversalTime().ToString('o')
  safety_scope = "Static launcher strings, small configuration files, JAR manifests and JAR entry names only. No installer, executable, Java class or JAR was executed. No bytecode was decompiled."
  application = [ordered]@{
    path = Get-Relative $payloadRoot $app.FullName
    size = $app.Length
    sha256 = Get-Sha256 $app.FullName
    architecture = "x86"
    authenticode = [ordered]@{
      status = [string]$appSignature.Status
      signer_subject = if ($appSignature.SignerCertificate) { $appSignature.SignerCertificate.Subject } else { $null }
      signer_thumbprint = if ($appSignature.SignerCertificate) { $appSignature.SignerCertificate.Thumbprint } else { $null }
    }
    version_info = [ordered]@{
      product_name = $appVersion.ProductName
      product_version = $appVersion.ProductVersion
      file_version = $appVersion.FileVersion
      company_name = $appVersion.CompanyName
      file_description = $appVersion.FileDescription
    }
  }
  root_inventory = $rootInventory
  launcher_markers = $launcherMarkers
  configurations = $configRecords
  application_jars = $jarRecords
  ui_signals = $uiSignals
  conclusions = [ordered]@{
    root_application_entry_points = $applicationExecutables.Count
    selected_entry_point = Get-Relative $payloadRoot $app.FullName
    bundled_java = (Test-Path -LiteralPath (Join-Path $payloadRoot 'jre'))
    black_box_observations = 0
    next_step = "Launch this exact executable in an ephemeral Windows environment, preserving process/UI/filesystem evidence."
  }
}

$jsonPath = Join-Path $OutputDirectory 'launch-static-analysis.json'
$payload | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $jsonPath -Encoding UTF8

$lines = @(
  '# CDE eCTD validator V1.1.0 — static launch analysis',
  '',
  "- Selected entry point: **$($payload.application.path)**",
  "- Entry point SHA-256: ``$($payload.application.sha256)``",
  "- Entry point Authenticode: **$($payload.application.authenticode.status)**",
  "- Bundled Java runtime: **$($payload.conclusions.bundled_java)**",
  "- Application JARs inspected: **$($jarRecords.Count)**",
  "- Small configuration files captured: **$($configRecords.Count)**",
  "- Official black-box observations: **0**",
  '',
  '## UI and report signals',
  '',
  '| Signal | Detected |',
  '|---|---:|',
  "| JavaFX/FXML | $($uiSignals.javafx_fxml) |",
  "| Swing naming | $($uiSignals.swing_names) |",
  "| Report-related classes/resources | $($uiSignals.report_names) |",
  "| Validator-related classes/resources | $($uiSignals.validator_names) |",
  '',
  '## Application JAR summary',
  '',
  '| JAR | Bytes | Classes | FXML | Main-Class | SHA-256 |',
  '|---|---:|---:|---:|---|---|'
)
foreach ($jar in $jarRecords) {
  $lines += "| $($jar.path) | $($jar.size) | $($jar.class_count) | $($jar.fxml_count) | $($jar.main_class) | ``$($jar.sha256)`` |"
}
$lines += @(
  '',
  '## Interpretation',
  '',
  'The root application executable is now unambiguous after excluding the bundled JRE and uninstaller. Static names and manifests guide the execution adapter, but do not prove that the program launches or that a validation is performed.',
  '',
  'This analysis preserves the rule that static inspection contributes zero official black-box observations.',
  ''
)
$lines -join "`n" | Set-Content -LiteralPath (Join-Path $OutputDirectory 'launch-static-analysis.md') -Encoding UTF8

Write-Host ($payload | ConvertTo-Json -Depth 5)
