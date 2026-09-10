param(
  [Parameter(Mandatory = $true)]
  [string]$ApplicationPath,
  [Parameter(Mandatory = $true)]
  [string]$WorkingDirectory,
  [string]$OutputDirectory = "build/cde-validator-launch-recon",
  [string]$ExpectedApplicationSha256 = "",
  [int]$ObservationSeconds = 45
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Get-Sha256([string]$Path) {
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Write-Json([string]$Path, $Value) {
  $Value | ConvertTo-Json -Depth 40 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-FileInventory([string]$Root) {
  if (-not (Test-Path -LiteralPath $Root)) { return @() }
  $base = (Resolve-Path -LiteralPath $Root).Path
  return @(
    Get-ChildItem -LiteralPath $base -File -Recurse -ErrorAction SilentlyContinue |
      Sort-Object FullName |
      ForEach-Object {
        [ordered]@{
          path = [IO.Path]::GetRelativePath($base, $_.FullName).Replace('\\','/')
          size = $_.Length
          last_write_utc = $_.LastWriteTimeUtc.ToString('o')
          sha256 = Get-Sha256 $_.FullName
        }
      }
  )
}

function Get-InventoryDigest($Inventory) {
  $canonical = @($Inventory | ForEach-Object { "$($_.path)`t$($_.size)`t$($_.sha256)" }) -join "`n"
  $bytes = [Text.Encoding]::UTF8.GetBytes($canonical)
  $sha = [Security.Cryptography.SHA256]::Create()
  try { return ([BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-','').ToLowerInvariant() }
  finally { $sha.Dispose() }
}

function Get-ProcessSnapshot {
  return @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Sort-Object ProcessId |
      ForEach-Object {
        [ordered]@{
          process_id = [int]$_.ProcessId
          parent_process_id = [int]$_.ParentProcessId
          name = $_.Name
          executable_path = $_.ExecutablePath
          command_line = $_.CommandLine
          creation_date = if ($_.CreationDate) { ([Management.ManagementDateTimeConverter]::ToDateTime($_.CreationDate)).ToUniversalTime().ToString('o') } else { $null }
        }
      }
  )
}

function Get-DescendantProcesses([int]$RootPid) {
  $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
  $selected = New-Object System.Collections.Generic.List[object]
  $ids = New-Object 'System.Collections.Generic.HashSet[int]'
  [void]$ids.Add($RootPid)
  $changed = $true
  while ($changed) {
    $changed = $false
    foreach ($item in $all) {
      if ($ids.Contains([int]$item.ParentProcessId) -and -not $ids.Contains([int]$item.ProcessId)) {
        [void]$ids.Add([int]$item.ProcessId)
        $changed = $true
      }
    }
  }
  foreach ($item in $all) {
    if ($ids.Contains([int]$item.ProcessId)) {
      $selected.Add([ordered]@{
        process_id = [int]$item.ProcessId
        parent_process_id = [int]$item.ParentProcessId
        name = $item.Name
        executable_path = $item.ExecutablePath
        command_line = $item.CommandLine
      })
    }
  }
  return @($selected | Sort-Object process_id)
}

function Get-RecentFiles([datetime]$SinceUtc) {
  $roots = @($WorkingDirectory, $env:TEMP, $env:APPDATA, $env:LOCALAPPDATA) | Select-Object -Unique
  $records = New-Object System.Collections.Generic.List[object]
  foreach ($root in $roots) {
    if (-not $root -or -not (Test-Path -LiteralPath $root)) { continue }
    $base = (Resolve-Path -LiteralPath $root).Path
    Get-ChildItem -LiteralPath $base -File -Recurse -ErrorAction SilentlyContinue |
      Where-Object { $_.LastWriteTimeUtc -ge $SinceUtc } |
      Sort-Object FullName |
      Select-Object -First 2500 |
      ForEach-Object {
        $hash = $null
        if ($_.Length -le 52428800) {
          try { $hash = Get-Sha256 $_.FullName } catch {}
        }
        $records.Add([ordered]@{
          root = $base
          path = [IO.Path]::GetRelativePath($base, $_.FullName).Replace('\\','/')
          size = $_.Length
          last_write_utc = $_.LastWriteTimeUtc.ToString('o')
          sha256 = $hash
        })
      }
  }
  return @($records)
}

$nativeSource = @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class EzctdWindowProbe {
  public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr hWnd, StringBuilder text, int count);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
  public sealed class WindowInfo {
    public long Handle { get; set; }
    public uint ProcessId { get; set; }
    public bool Visible { get; set; }
    public string Title { get; set; }
    public string ClassName { get; set; }
  }
  public static List<WindowInfo> GetWindows() {
    var result = new List<WindowInfo>();
    EnumWindows((hWnd, lParam) => {
      uint pid;
      GetWindowThreadProcessId(hWnd, out pid);
      var title = new StringBuilder(2048);
      var cls = new StringBuilder(512);
      GetWindowText(hWnd, title, title.Capacity);
      GetClassName(hWnd, cls, cls.Capacity);
      result.Add(new WindowInfo { Handle=hWnd.ToInt64(), ProcessId=pid, Visible=IsWindowVisible(hWnd), Title=title.ToString(), ClassName=cls.ToString() });
      return true;
    }, IntPtr.Zero);
    return result;
  }
}
"@
Add-Type -TypeDefinition $nativeSource -Language CSharp

function Get-WindowsForPids([int[]]$ProcessIds) {
  $set = New-Object 'System.Collections.Generic.HashSet[int]'
  foreach ($id in $ProcessIds) { [void]$set.Add($id) }
  return @(
    [EzctdWindowProbe]::GetWindows() |
      Where-Object { $set.Contains([int]$_.ProcessId) } |
      ForEach-Object {
        [ordered]@{
          handle = $_.Handle
          process_id = [int]$_.ProcessId
          visible = $_.Visible
          title = $_.Title
          class_name = $_.ClassName
        }
      }
  )
}

function Get-UiAutomationTree([int[]]$ProcessIds) {
  $result = New-Object System.Collections.Generic.List[object]
  try {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    $root = [Windows.Automation.AutomationElement]::RootElement
    $condition = [Windows.Automation.Condition]::TrueCondition
    $windows = $root.FindAll([Windows.Automation.TreeScope]::Children, $condition)
    $set = New-Object 'System.Collections.Generic.HashSet[int]'
    foreach ($id in $ProcessIds) { [void]$set.Add($id) }
    foreach ($window in $windows) {
      try {
        if (-not $set.Contains([int]$window.Current.ProcessId)) { continue }
        $children = $window.FindAll([Windows.Automation.TreeScope]::Descendants, $condition)
        $nodes = New-Object System.Collections.Generic.List[object]
        $limit = [Math]::Min($children.Count, 2000)
        for ($i = 0; $i -lt $limit; $i++) {
          $element = $children.Item($i)
          try {
            $nodes.Add([ordered]@{
              name = $element.Current.Name
              automation_id = $element.Current.AutomationId
              class_name = $element.Current.ClassName
              control_type = $element.Current.ControlType.ProgrammaticName
              enabled = $element.Current.IsEnabled
              offscreen = $element.Current.IsOffscreen
            })
          } catch {}
        }
        $result.Add([ordered]@{
          process_id = [int]$window.Current.ProcessId
          name = $window.Current.Name
          automation_id = $window.Current.AutomationId
          class_name = $window.Current.ClassName
          control_type = $window.Current.ControlType.ProgrammaticName
          descendant_count = $children.Count
          descendants = @($nodes)
        })
      } catch {}
    }
  } catch {
    return [ordered]@{ status = "UNAVAILABLE"; error = "$($_.Exception.GetType().FullName): $($_.Exception.Message)"; windows = @() }
  }
  return [ordered]@{ status = "CAPTURED"; error = $null; windows = @($result) }
}

function Save-DesktopScreenshot([string]$Path) {
  try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing.Common -ErrorAction SilentlyContinue
    Add-Type -AssemblyName System.Drawing -ErrorAction SilentlyContinue
    $bounds = [Windows.Forms.SystemInformation]::VirtualScreen
    if ($bounds.Width -le 0 -or $bounds.Height -le 0) { throw "No virtual screen available" }
    $bitmap = New-Object Drawing.Bitmap $bounds.Width, $bounds.Height
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
      $graphics.CopyFromScreen($bounds.Left, $bounds.Top, 0, 0, $bitmap.Size)
      $bitmap.Save($Path, [Drawing.Imaging.ImageFormat]::Png)
    } finally {
      $graphics.Dispose()
      $bitmap.Dispose()
    }
    return [ordered]@{ status = "CAPTURED"; path = $Path; sha256 = Get-Sha256 $Path; width = $bounds.Width; height = $bounds.Height; error = $null }
  } catch {
    return [ordered]@{ status = "UNAVAILABLE"; path = $null; sha256 = $null; width = $null; height = $null; error = "$($_.Exception.GetType().FullName): $($_.Exception.Message)" }
  }
}

function Get-EnvironmentFacts {
  $os = Get-CimInstance Win32_OperatingSystem
  $computer = Get-CimInstance Win32_ComputerSystem
  $screen = $null
  try {
    Add-Type -AssemblyName System.Windows.Forms
    $screen = [ordered]@{
      virtual_width = [Windows.Forms.SystemInformation]::VirtualScreen.Width
      virtual_height = [Windows.Forms.SystemInformation]::VirtualScreen.Height
      working_area_width = [Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Width
      working_area_height = [Windows.Forms.Screen]::PrimaryScreen.WorkingArea.Height
    }
  } catch {}
  return [ordered]@{
    os_caption = $os.Caption
    os_version = $os.Version
    os_build_number = $os.BuildNumber
    architecture = $os.OSArchitecture
    computer_model = $computer.Model
    user_name = [Environment]::UserName
    session_id = [Diagnostics.Process]::GetCurrentProcess().SessionId
    culture = [Globalization.CultureInfo]::CurrentCulture.Name
    ui_culture = [Globalization.CultureInfo]::CurrentUICulture.Name
    time_zone = (Get-TimeZone).Id
    powershell = $PSVersionTable.PSVersion.ToString()
    screen = $screen
    environment_representativeness = "exploratory_outside_manual_recommendation"
  }
}

function Get-RegistrySnapshot([string]$Path) {
  $output = New-Object System.Collections.Generic.List[string]
  if (Test-Path -LiteralPath $Path) {
    Get-ChildItem -LiteralPath $Path -Recurse -ErrorAction SilentlyContinue |
      Sort-Object Name |
      Select-Object -First 10000 |
      ForEach-Object { $output.Add($_.Name) }
  }
  return @($output)
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$ApplicationPath = (Resolve-Path -LiteralPath $ApplicationPath).Path
$WorkingDirectory = (Resolve-Path -LiteralPath $WorkingDirectory).Path
$appHash = Get-Sha256 $ApplicationPath
if ($ExpectedApplicationSha256 -and $appHash -ne $ExpectedApplicationSha256.ToLowerInvariant()) {
  throw "Application SHA-256 mismatch: expected=$ExpectedApplicationSha256 actual=$appHash"
}

$startedUtc = (Get-Date).ToUniversalTime()
$preInventory = Get-FileInventory $WorkingDirectory
$preDigest = Get-InventoryDigest $preInventory
$preProcesses = Get-ProcessSnapshot
$registryBefore = Get-RegistrySnapshot 'HKCU:\Software'
Write-Json (Join-Path $OutputDirectory 'processes-before.json') $preProcesses
Write-Json (Join-Path $OutputDirectory 'registry-hkcu-software-before.json') $registryBefore

$firewall = New-Object System.Collections.Generic.List[object]
$firewallRuleNames = New-Object System.Collections.Generic.List[string]
$networkTargets = @(
  $ApplicationPath,
  (Join-Path $WorkingDirectory 'jre\jre1.8.0_202\bin\java.exe'),
  (Join-Path $WorkingDirectory 'jre\jre1.8.0_202\bin\javaw.exe')
)
foreach ($target in $networkTargets) {
  if (-not (Test-Path -LiteralPath $target)) { continue }
  $name = "EZCTD-LaunchRecon-$([Guid]::NewGuid().ToString('N'))"
  try {
    New-NetFirewallRule -DisplayName $name -Direction Outbound -Program $target -Action Block -Profile Any -ErrorAction Stop | Out-Null
    $firewallRuleNames.Add($name)
    $firewall.Add([ordered]@{ program = $target; rule_name = $name; status = "BLOCKED_OUTBOUND"; error = $null })
  } catch {
    $firewall.Add([ordered]@{ program = $target; rule_name = $name; status = "RULE_FAILED"; error = "$($_.Exception.GetType().FullName): $($_.Exception.Message)" })
  }
}

$process = $null
$startError = $null
$started = $false
$exitedEarly = $false
$exitCode = $null
$observationSamples = New-Object System.Collections.Generic.List[object]
try {
  $startInfo = New-Object Diagnostics.ProcessStartInfo
  $startInfo.FileName = $ApplicationPath
  $startInfo.WorkingDirectory = $WorkingDirectory
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $false
  $startInfo.Environment.Clear()
  foreach ($name in @('SystemRoot','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP','USERPROFILE','HOMEDRIVE','HOMEPATH','APPDATA','LOCALAPPDATA','PROGRAMDATA','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','PROCESSOR_IDENTIFIER','OS')) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ($null -ne $value) { $startInfo.Environment[$name] = $value }
  }
  $startInfo.Environment['EZCTD_RECON_MODE'] = '1'
  $process = New-Object Diagnostics.Process
  $process.StartInfo = $startInfo
  $started = $process.Start()
  if (-not $started) { throw "Process.Start returned false" }
  for ($second = 0; $second -lt $ObservationSeconds; $second += 3) {
    Start-Sleep -Seconds 3
    try { $process.Refresh() } catch {}
    $tree = Get-DescendantProcesses $process.Id
    $pids = @($tree | ForEach-Object { [int]$_.process_id })
    $windows = Get-WindowsForPids $pids
    $connections = @()
    foreach ($pid in $pids) {
      try {
        $connections += @(
          Get-NetTCPConnection -OwningProcess $pid -ErrorAction SilentlyContinue |
            ForEach-Object {
              [ordered]@{
                process_id = $pid
                state = [string]$_.State
                local_address = $_.LocalAddress
                local_port = $_.LocalPort
                remote_address = $_.RemoteAddress
                remote_port = $_.RemotePort
              }
            }
        )
      } catch {}
    }
    $observationSamples.Add([ordered]@{
      elapsed_seconds = [int]($second + 3)
      process_exited = $process.HasExited
      process_tree = $tree
      windows = $windows
      tcp_connections = $connections
    })
    if ($process.HasExited) {
      $exitedEarly = $true
      $exitCode = $process.ExitCode
      break
    }
  }
} catch {
  $startError = "$($_.Exception.GetType().FullName): $($_.Exception.Message)"
}

$finalTree = @()
$finalWindows = @()
$uiTree = [ordered]@{ status = "NOT_ATTEMPTED"; error = $null; windows = @() }
if ($started -and $process) {
  try {
    $finalTree = Get-DescendantProcesses $process.Id
    $finalPids = @($finalTree | ForEach-Object { [int]$_.process_id })
    $finalWindows = Get-WindowsForPids $finalPids
    $uiTree = Get-UiAutomationTree $finalPids
  } catch {}
}
Write-Json (Join-Path $OutputDirectory 'observation-samples.json') @($observationSamples)
Write-Json (Join-Path $OutputDirectory 'ui-automation-tree.json') $uiTree

$screenshot = Save-DesktopScreenshot (Join-Path $OutputDirectory 'desktop-final.png')

$termination = New-Object System.Collections.Generic.List[object]
if ($started -and $process) {
  try {
    $treeForTermination = Get-DescendantProcesses $process.Id | Sort-Object process_id -Descending
    foreach ($item in $treeForTermination) {
      try {
        Stop-Process -Id ([int]$item.process_id) -Force -ErrorAction Stop
        $termination.Add([ordered]@{ process_id = [int]$item.process_id; status = "TERMINATED"; error = $null })
      } catch {
        $termination.Add([ordered]@{ process_id = [int]$item.process_id; status = "TERMINATION_FAILED"; error = $_.Exception.Message })
      }
    }
  } catch {}
}
foreach ($name in $firewallRuleNames) {
  try { Remove-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue } catch {}
}

$finishedUtc = (Get-Date).ToUniversalTime()
$postInventory = Get-FileInventory $WorkingDirectory
$postDigest = Get-InventoryDigest $postInventory
$postProcesses = Get-ProcessSnapshot
$registryAfter = Get-RegistrySnapshot 'HKCU:\Software'
$recentFiles = Get-RecentFiles $startedUtc.AddSeconds(-2)
Write-Json (Join-Path $OutputDirectory 'processes-after.json') $postProcesses
Write-Json (Join-Path $OutputDirectory 'registry-hkcu-software-after.json') $registryAfter
Write-Json (Join-Path $OutputDirectory 'recent-files.json') $recentFiles

$preByPath = @{}
foreach ($item in $preInventory) { $preByPath[$item.path] = $item }
$postByPath = @{}
foreach ($item in $postInventory) { $postByPath[$item.path] = $item }
$added = @($postInventory | Where-Object { -not $preByPath.ContainsKey($_.path) })
$removed = @($preInventory | Where-Object { -not $postByPath.ContainsKey($_.path) })
$modified = @(
  $postInventory | Where-Object {
    $preByPath.ContainsKey($_.path) -and $preByPath[$_.path].sha256 -ne $_.sha256
  } | ForEach-Object {
    [ordered]@{ path = $_.path; before_sha256 = $preByPath[$_.path].sha256; after_sha256 = $_.sha256; size = $_.size }
  }
)
$registryAdded = @($registryAfter | Where-Object { $_ -notin $registryBefore })
$registryRemoved = @($registryBefore | Where-Object { $_ -notin $registryAfter })

$visibleWindows = @($finalWindows | Where-Object { $_.visible -and $_.title })
$classification = if (-not $started) {
  "START_FAILED"
} elseif ($exitedEarly) {
  "EXITED_DURING_OBSERVATION"
} elseif ($visibleWindows.Count -gt 0) {
  "VISIBLE_WINDOW_OBSERVED"
} elseif ($finalTree.Count -gt 0) {
  "PROCESS_RUNNING_NO_VISIBLE_WINDOW"
} else {
  "PROCESS_STATE_INCONCLUSIVE"
}

$result = [ordered]@{
  schema_version = "0.2.0"
  run_id = "CDE-V110-LAUNCH-RECON-001"
  run_type = "launch_reconnaissance"
  classification = $classification
  execution_mode = "direct_static_payload_no_installer"
  environment = Get-EnvironmentFacts
  safety = [ordered]@{
    synthetic_or_no_input_only = $true
    real_submission_data_present = $false
    checkout_credentials_persisted = $false
    child_environment_scrubbed = $true
    outbound_firewall = @($firewall)
    ephemeral_runner_expected = $true
  }
  validator = [ordered]@{
    name = "CDE eCTD validation software"
    declared_version = "1.1.0"
    application_path = $ApplicationPath
    application_sha256 = $appHash
  }
  execution = [ordered]@{
    started = $started
    start_error = $startError
    root_process_id = if ($process -and $started) { $process.Id } else { $null }
    exited_during_observation = $exitedEarly
    exit_code = $exitCode
    observation_seconds_requested = $ObservationSeconds
    started_at = $startedUtc.ToString('o')
    finished_at = $finishedUtc.ToString('o')
    final_process_tree = $finalTree
    final_windows = $finalWindows
    visible_window_count = $visibleWindows.Count
    ui_automation = $uiTree
    screenshot = $screenshot
    termination = @($termination)
  }
  side_effects = [ordered]@{
    payload_inventory_sha256_before = $preDigest
    payload_inventory_sha256_after = $postDigest
    payload_unchanged = ($preDigest -eq $postDigest)
    payload_added_files = $added
    payload_removed_files = $removed
    payload_modified_files = $modified
    recent_file_count = $recentFiles.Count
    recent_files = $recentFiles
    hkcu_software_added_keys = $registryAdded
    hkcu_software_removed_keys = $registryRemoved
  }
  observation_counters = [ordered]@{
    launch_reconnaissance_runs = 1
    completed_validation_runs = 0
    admissible_black_box_observations = 0
    calibration_informative_observations = 0
    repeated_baseline_controls = 0
    official_black_box_observations = 0
  }
  assertions = [ordered]@{
    software_executed = $started
    validation_invoked = $false
    terminal_validation_state_observed = $false
    native_validation_report_present = $false
    input_inventory_present = $false
  }
  interpretation = [ordered]@{
    admissible_as_validation_observation = $false
    reason = "This run only probes application launch, GUI/process visibility and side effects. No sequence was selected and validation was not invoked."
    next_gate = "Use the observed UI/process model to build a controlled validation adapter, then execute one synthetic candidate sequence with a native report and complete evidence contract."
  }
}

Write-Json (Join-Path $OutputDirectory 'launch-recon-result.json') $result
$lines = @(
  '# CDE eCTD 验证软件 V1.1.0：启动侦察 001',
  '',
  "- 分类：**$classification**",
  "- 软件进程已启动：**$started**",
  "- 可见窗口数：**$($visibleWindows.Count)**",
  "- UI Automation：**$($uiTree.status)**",
  "- 截图：**$($screenshot.status)**",
  "- payload 启动前后字节不变：**$($preDigest -eq $postDigest)**",
  "- 启动侦察次数：**1**",
  "- 完整验证运行：**0**",
  "- 官方黑盒观察：**0**",
  '',
  '## 关键边界',
  '',
  '本次只启动精确哈希匹配的官方应用，未选择序列、未点击“开始验证”、未生成原生验证报告，因此不得计为官方验证观察。',
  '',
  'GitHub 托管环境为 Windows Server，超出操作手册推荐的 Windows 7/10 范围；即使成功，也只作为执行适配侦察。',
  '',
  '## 窗口',
  '',
  '| PID | Visible | Class | Title |',
  '|---:|---:|---|---|'
)
foreach ($window in $finalWindows) {
  $title = ($window.title -replace '\|','\\|')
  $lines += "| $($window.process_id) | $($window.visible) | $($window.class_name) | $title |"
}
$lines += @(
  '',
  '## 进程树',
  '',
  '| PID | PPID | Name | Executable |',
  '|---:|---:|---|---|'
)
foreach ($item in $finalTree) {
  $lines += "| $($item.process_id) | $($item.parent_process_id) | $($item.name) | $($item.executable_path) |"
}
$lines += @(
  '',
  '## 下一步',
  '',
  '根据本次窗口、控件树和副作用，确定可重复的 UI Automation 路径；随后仅用合成候选序列完成首次完整验证。只有原生报告、截图、程序身份、输入哈希、前后完整性及复核全部通过，计数才从 0 增加到 1。',
  ''
)
$lines -join "`n" | Set-Content -LiteralPath (Join-Path $OutputDirectory 'launch-recon-result.md') -Encoding UTF8

Write-Host ($result | ConvertTo-Json -Depth 8)
exit 0
