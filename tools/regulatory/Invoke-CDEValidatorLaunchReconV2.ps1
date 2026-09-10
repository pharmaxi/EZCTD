# v2.1: deterministic process-by-payload tracking; fail closed on outbound-firewall failure.
param(
  [Parameter(Mandatory = $true)] [string]$ApplicationPath,
  [Parameter(Mandatory = $true)] [string]$PayloadDirectory,
  [string]$OutputDirectory = "build/cde-validator-launch-recon-v2",
  [Parameter(Mandatory = $true)] [string]$ExpectedApplicationSha256,
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

function Get-Inventory([string]$Root) {
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
  $canonical = (@($Inventory | ForEach-Object { "$($_.path)`t$($_.size)`t$($_.sha256)" }) -join "`n")
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try {
    $digest = $algorithm.ComputeHash([Text.Encoding]::UTF8.GetBytes($canonical))
    return ([BitConverter]::ToString($digest)).Replace('-','').ToLowerInvariant()
  } finally {
    $algorithm.Dispose()
  }
}

function Convert-CreationDate($Value) {
  if ($null -eq $Value) { return $null }
  try {
    if ($Value -is [datetime]) { return $Value.ToUniversalTime().ToString('o') }
    return ([Management.ManagementDateTimeConverter]::ToDateTime([string]$Value)).ToUniversalTime().ToString('o')
  } catch {
    return [string]$Value
  }
}

function Get-TargetProcesses([string]$PayloadRoot, [int]$RootProcessId) {
  $root = ((Resolve-Path -LiteralPath $PayloadRoot).Path.TrimEnd('\\') + '\\').ToLowerInvariant()
  return @(
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
      Where-Object {
        $path = if ($_.ExecutablePath) { ([string]$_.ExecutablePath).ToLowerInvariant() } else { '' }
        ([int]$_.ProcessId -eq $RootProcessId) -or $path.StartsWith($root)
      } |
      Sort-Object ProcessId |
      ForEach-Object {
        [ordered]@{
          process_id = [int]$_.ProcessId
          parent_process_id = [int]$_.ParentProcessId
          name = $_.Name
          executable_path = $_.ExecutablePath
          command_line = $_.CommandLine
          creation_date = Convert-CreationDate $_.CreationDate
        }
      }
  )
}

$windowType = @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class EzctdWindowProbeV21 {
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
  public static List<WindowInfo> Read() {
    var result = new List<WindowInfo>();
    EnumWindows((hWnd, lParam) => {
      uint processId;
      GetWindowThreadProcessId(hWnd, out processId);
      var title = new StringBuilder(2048);
      var cls = new StringBuilder(512);
      GetWindowText(hWnd, title, title.Capacity);
      GetClassName(hWnd, cls, cls.Capacity);
      result.Add(new WindowInfo {
        Handle=hWnd.ToInt64(), ProcessId=processId, Visible=IsWindowVisible(hWnd),
        Title=title.ToString(), ClassName=cls.ToString()
      });
      return true;
    }, IntPtr.Zero);
    return result;
  }
}
"@
Add-Type -TypeDefinition $windowType -Language CSharp

function Get-TargetWindows([int[]]$ProcessIds) {
  $set = New-Object 'System.Collections.Generic.HashSet[int]'
  foreach ($processId in $ProcessIds) { [void]$set.Add($processId) }
  return @(
    [EzctdWindowProbeV21]::Read() |
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

function Get-UiAutomation([int[]]$ProcessIds) {
  try {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    $set = New-Object 'System.Collections.Generic.HashSet[int]'
    foreach ($processId in $ProcessIds) { [void]$set.Add($processId) }
    $root = [Windows.Automation.AutomationElement]::RootElement
    $condition = [Windows.Automation.Condition]::TrueCondition
    $top = $root.FindAll([Windows.Automation.TreeScope]::Children, $condition)
    $windows = New-Object System.Collections.Generic.List[object]
    foreach ($window in $top) {
      try {
        if (-not $set.Contains([int]$window.Current.ProcessId)) { continue }
        $descendants = $window.FindAll([Windows.Automation.TreeScope]::Descendants, $condition)
        $nodes = New-Object System.Collections.Generic.List[object]
        $limit = [Math]::Min($descendants.Count, 1500)
        for ($index = 0; $index -lt $limit; $index++) {
          try {
            $element = $descendants.Item($index)
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
        $windows.Add([ordered]@{
          process_id = [int]$window.Current.ProcessId
          name = $window.Current.Name
          automation_id = $window.Current.AutomationId
          class_name = $window.Current.ClassName
          control_type = $window.Current.ControlType.ProgrammaticName
          descendant_count = $descendants.Count
          descendants = @($nodes)
        })
      } catch {}
    }
    return [ordered]@{ status='CAPTURED'; error=$null; windows=@($windows) }
  } catch {
    return [ordered]@{ status='UNAVAILABLE'; error="$($_.Exception.GetType().FullName): $($_.Exception.Message)"; windows=@() }
  }
}

function Save-Screenshot([string]$Path) {
  try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $bounds = [Windows.Forms.SystemInformation]::VirtualScreen
    if ($bounds.Width -le 0 -or $bounds.Height -le 0) { throw 'No virtual screen available' }
    $bitmap = New-Object Drawing.Bitmap $bounds.Width, $bounds.Height
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
      $graphics.CopyFromScreen($bounds.Left, $bounds.Top, 0, 0, $bitmap.Size)
      $bitmap.Save($Path, [Drawing.Imaging.ImageFormat]::Png)
    } finally {
      $graphics.Dispose(); $bitmap.Dispose()
    }
    return [ordered]@{ status='CAPTURED'; path=(Split-Path -Leaf $Path); sha256=(Get-Sha256 $Path); width=$bounds.Width; height=$bounds.Height; error=$null }
  } catch {
    return [ordered]@{ status='UNAVAILABLE'; path=$null; sha256=$null; width=$null; height=$null; error="$($_.Exception.GetType().FullName): $($_.Exception.Message)" }
  }
}

function Get-EnvironmentFacts {
  $os = Get-CimInstance Win32_OperatingSystem
  $computer = Get-CimInstance Win32_ComputerSystem
  $screen = $null
  try {
    Add-Type -AssemblyName System.Windows.Forms
    $screen = [ordered]@{ width=[Windows.Forms.SystemInformation]::VirtualScreen.Width; height=[Windows.Forms.SystemInformation]::VirtualScreen.Height }
  } catch {}
  return [ordered]@{
    os_caption = $os.Caption
    os_version = $os.Version
    os_build_number = $os.BuildNumber
    os_architecture = $os.OSArchitecture
    computer_model = $computer.Model
    user_name = [Environment]::UserName
    session_id = [Diagnostics.Process]::GetCurrentProcess().SessionId
    culture = [Globalization.CultureInfo]::CurrentCulture.Name
    ui_culture = [Globalization.CultureInfo]::CurrentUICulture.Name
    time_zone = (Get-TimeZone).Id
    powershell_version = $PSVersionTable.PSVersion.ToString()
    screen = $screen
    environment_representativeness = 'exploratory_outside_manual_recommendation'
  }
}

function Get-RecentFiles([datetime]$SinceUtc) {
  $records = New-Object System.Collections.Generic.List[object]
  foreach ($root in @($PayloadDirectory, $env:TEMP, $env:APPDATA, $env:LOCALAPPDATA) | Select-Object -Unique) {
    if (-not $root -or -not (Test-Path -LiteralPath $root)) { continue }
    $base = (Resolve-Path -LiteralPath $root).Path
    Get-ChildItem -LiteralPath $base -File -Recurse -ErrorAction SilentlyContinue |
      Where-Object { $_.LastWriteTimeUtc -ge $SinceUtc.AddSeconds(-2) } |
      Sort-Object FullName |
      Select-Object -First 1000 |
      ForEach-Object {
        $hash = $null
        if ($_.Length -le 52428800) { try { $hash = Get-Sha256 $_.FullName } catch {} }
        $records.Add([ordered]@{
          root=$base
          path=[IO.Path]::GetRelativePath($base, $_.FullName).Replace('\\','/')
          size=$_.Length
          last_write_utc=$_.LastWriteTimeUtc.ToString('o')
          sha256=$hash
        })
      }
  }
  return @($records)
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$ApplicationPath = (Resolve-Path -LiteralPath $ApplicationPath).Path
$PayloadDirectory = (Resolve-Path -LiteralPath $PayloadDirectory).Path
$applicationSha256 = Get-Sha256 $ApplicationPath
if ($applicationSha256 -ne $ExpectedApplicationSha256.ToLowerInvariant()) {
  throw "Application SHA-256 mismatch: expected=$ExpectedApplicationSha256 actual=$applicationSha256"
}

$startedUtc = (Get-Date).ToUniversalTime()
$inventoryBefore = Get-Inventory $PayloadDirectory
$digestBefore = Get-InventoryDigest $inventoryBefore
Write-Json (Join-Path $OutputDirectory 'payload-inventory-before.json') $inventoryBefore

$firewall = New-Object System.Collections.Generic.List[object]
$firewallNames = New-Object System.Collections.Generic.List[string]
$firewallReady = $true
foreach ($program in @(
  $ApplicationPath,
  (Join-Path $PayloadDirectory 'jre\jre1.8.0_202\bin\java.exe'),
  (Join-Path $PayloadDirectory 'jre\jre1.8.0_202\bin\javaw.exe')
)) {
  if (-not (Test-Path -LiteralPath $program)) { continue }
  $ruleName = "EZCTD-LaunchRecon-$([Guid]::NewGuid().ToString('N'))"
  try {
    New-NetFirewallRule -DisplayName $ruleName -Direction Outbound -Program $program -Action Block -Profile Any -ErrorAction Stop | Out-Null
    $firewallNames.Add($ruleName)
    $firewall.Add([ordered]@{ program=$program; status='BLOCKED_OUTBOUND'; rule_name=$ruleName; error=$null })
  } catch {
    $firewallReady = $false
    $firewall.Add([ordered]@{ program=$program; status='RULE_FAILED'; rule_name=$ruleName; error="$($_.Exception.GetType().FullName): $($_.Exception.Message)" })
  }
}

$rootProcess = $null
$rootProcessId = -1
$startSucceeded = $false
$startError = if ($firewallReady) { $null } else { 'Safety gate failed: one or more outbound firewall rules could not be installed.' }
$samples = New-Object System.Collections.Generic.List[object]
if ($firewallReady) {
  try {
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = $ApplicationPath
    $startInfo.WorkingDirectory = $PayloadDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $false
    $startInfo.Environment.Clear()
    foreach ($name in @('SystemRoot','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP','USERPROFILE','HOMEDRIVE','HOMEPATH','APPDATA','LOCALAPPDATA','PROGRAMDATA','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','PROCESSOR_IDENTIFIER','OS')) {
      $value = [Environment]::GetEnvironmentVariable($name)
      if ($null -ne $value) { $startInfo.Environment[$name] = $value }
    }
    $rootProcess = New-Object Diagnostics.Process
    $rootProcess.StartInfo = $startInfo
    $startSucceeded = $rootProcess.Start()
    if (-not $startSucceeded) { throw 'Process.Start returned false' }
    $rootProcessId = $rootProcess.Id
    for ($elapsed = 3; $elapsed -le $ObservationSeconds; $elapsed += 3) {
      Start-Sleep -Seconds 3
      $processes = Get-TargetProcesses $PayloadDirectory $rootProcessId
      $processIds = @($processes | ForEach-Object { [int]$_.process_id })
      $windows = Get-TargetWindows $processIds
      $connections = New-Object System.Collections.Generic.List[object]
      foreach ($processId in $processIds) {
        try {
          Get-NetTCPConnection -OwningProcess $processId -ErrorAction SilentlyContinue |
            ForEach-Object {
              $connections.Add([ordered]@{
                process_id=$processId
                state=[string]$_.State
                local_address=$_.LocalAddress
                local_port=$_.LocalPort
                remote_address=$_.RemoteAddress
                remote_port=$_.RemotePort
              })
            }
        } catch {}
      }
      $samples.Add([ordered]@{
        elapsed_seconds=$elapsed
        processes=$processes
        windows=$windows
        tcp_connections=@($connections)
      })
      if ($processes.Count -eq 0) { break }
    }
  } catch {
    $startError = "$($_.Exception.GetType().FullName): $($_.Exception.Message)"
  }
}

$allProcesses = @($samples | ForEach-Object { $_.processes } | Group-Object process_id | ForEach-Object { $_.Group[0] } | Sort-Object process_id)
$allWindows = @($samples | ForEach-Object { $_.windows } | Group-Object handle | ForEach-Object { $_.Group[-1] } | Sort-Object process_id, handle)
$visibleWindows = @($allWindows | Where-Object { $_.visible -and $_.title })
$finalProcesses = if ($startSucceeded) { Get-TargetProcesses $PayloadDirectory $rootProcessId } else { @() }
$finalIds = @($finalProcesses | ForEach-Object { [int]$_.process_id })
$finalWindows = Get-TargetWindows $finalIds
$uiAutomation = Get-UiAutomation $finalIds
Write-Json (Join-Path $OutputDirectory 'observation-samples.json') @($samples)
Write-Json (Join-Path $OutputDirectory 'ui-automation-tree.json') $uiAutomation
$screenshot = Save-Screenshot (Join-Path $OutputDirectory 'desktop-final.png')

$termination = New-Object System.Collections.Generic.List[object]
foreach ($processInfo in @($finalProcesses | Sort-Object process_id -Descending)) {
  try {
    Stop-Process -Id ([int]$processInfo.process_id) -Force -ErrorAction Stop
    $termination.Add([ordered]@{ process_id=[int]$processInfo.process_id; status='TERMINATED'; error=$null })
  } catch {
    $termination.Add([ordered]@{ process_id=[int]$processInfo.process_id; status='TERMINATION_FAILED'; error=$_.Exception.Message })
  }
}
foreach ($ruleName in $firewallNames) {
  try { Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue } catch {}
}

$finishedUtc = (Get-Date).ToUniversalTime()
$inventoryAfter = Get-Inventory $PayloadDirectory
$digestAfter = Get-InventoryDigest $inventoryAfter
Write-Json (Join-Path $OutputDirectory 'payload-inventory-after.json') $inventoryAfter
$recentFiles = Get-RecentFiles $startedUtc
Write-Json (Join-Path $OutputDirectory 'recent-files.json') $recentFiles

$before = @{}; foreach ($item in $inventoryBefore) { $before[$item.path] = $item }
$after = @{}; foreach ($item in $inventoryAfter) { $after[$item.path] = $item }
$added = @($inventoryAfter | Where-Object { -not $before.ContainsKey($_.path) })
$removed = @($inventoryBefore | Where-Object { -not $after.ContainsKey($_.path) })
$modified = @(
  $inventoryAfter |
    Where-Object { $before.ContainsKey($_.path) -and $before[$_.path].sha256 -ne $_.sha256 } |
    ForEach-Object { [ordered]@{ path=$_.path; before_sha256=$before[$_.path].sha256; after_sha256=$_.sha256 } }
)

$classification = if (-not $firewallReady) {
  'SAFETY_GATE_FAILED'
} elseif (-not $startSucceeded) {
  'START_FAILED'
} elseif ($visibleWindows.Count -gt 0) {
  'VISIBLE_WINDOW_OBSERVED'
} elseif ($allProcesses.Count -gt 0) {
  'PROCESS_OBSERVED_NO_VISIBLE_WINDOW'
} else {
  'PROCESS_STATE_INCONCLUSIVE'
}

$result = [ordered]@{
  schema_version='0.2.1'
  run_id='CDE-V110-LAUNCH-RECON-001'
  run_type='launch_reconnaissance'
  classification=$classification
  execution_mode='direct_static_payload_no_installer'
  environment=Get-EnvironmentFacts
  safety=[ordered]@{
    real_submission_data_present=$false
    sequence_selected=$false
    checkout_credentials_persisted=$false
    child_environment_scrubbed=$true
    outbound_firewall=@($firewall)
    outbound_firewall_ready=$firewallReady
    ephemeral_runner_expected=$true
  }
  validator=[ordered]@{
    name='CDE eCTD validation software'
    declared_version='1.1.0'
    application_path=$ApplicationPath
    application_sha256=$applicationSha256
  }
  execution=[ordered]@{
    start_succeeded=$startSucceeded
    start_error=$startError
    root_process_id=if ($startSucceeded) { $rootProcessId } else { $null }
    started_at=$startedUtc.ToString('o')
    finished_at=$finishedUtc.ToString('o')
    observation_seconds_requested=$ObservationSeconds
    observed_processes=$allProcesses
    observed_windows=$allWindows
    observed_visible_window_count=$visibleWindows.Count
    final_processes=$finalProcesses
    final_windows=$finalWindows
    ui_automation=$uiAutomation
    screenshot=$screenshot
    termination=@($termination)
  }
  side_effects=[ordered]@{
    payload_inventory_sha256_before=$digestBefore
    payload_inventory_sha256_after=$digestAfter
    payload_unchanged=($digestBefore -eq $digestAfter)
    added_files=$added
    removed_files=$removed
    modified_files=$modified
    recent_file_count=$recentFiles.Count
    recent_files=$recentFiles
  }
  assertions=[ordered]@{
    software_executed=$startSucceeded
    validation_invoked=$false
    terminal_validation_state_observed=$false
    native_validation_report_present=$false
    input_inventory_present=$false
  }
  observation_counters=[ordered]@{
    launch_reconnaissance_runs=1
    completed_validation_runs=0
    admissible_black_box_observations=0
    calibration_informative_observations=0
    repeated_baseline_controls=0
    official_black_box_observations=0
  }
  interpretation=[ordered]@{
    admissible_as_validation_observation=$false
    reason='Application launch only. No sequence was selected, validation was not invoked and no native validation report was produced.'
    next_gate='Use the observed process/window/UI evidence to build the first synthetic-sequence validation adapter.'
  }
}

Write-Json (Join-Path $OutputDirectory 'launch-recon-result.json') $result
$lines = @(
  '# CDE eCTD 验证软件 V1.1.0：启动侦察 001',
  '',
  "- 分类：**$classification**",
  "- 软件启动：**$startSucceeded**",
  "- 观察到的相关进程：**$($allProcesses.Count)**",
  "- 观察到的可见窗口：**$($visibleWindows.Count)**",
  "- UI Automation：**$($uiAutomation.status)**",
  "- 桌面截图：**$($screenshot.status)**",
  "- payload 启动前后字节不变：**$($digestBefore -eq $digestAfter)**",
  '- `launch_reconnaissance_runs`: **1**',
  '- `completed_validation_runs`: **0**',
  '- `official_black_box_observations`: **0**',
  '',
  '## 边界',
  '',
  '本次未选择序列、未触发验证、未生成原生验证报告；启动成功也不构成正式黑盒验证观察。运行环境为 GitHub 托管 Windows Server，超出操作手册推荐的 Windows 7/10 范围。',
  '',
  '## 观察到的窗口',
  '',
  '| PID | Visible | Class | Title |',
  '|---:|---:|---|---|'
)
foreach ($window in $allWindows) {
  $title = ([string]$window.title).Replace('|','\|')
  $lines += "| $($window.process_id) | $($window.visible) | $($window.class_name) | $title |"
}
$lines += @('', '## 观察到的进程', '', '| PID | PPID | Name | Executable |', '|---:|---:|---|---|')
foreach ($processInfo in $allProcesses) {
  $lines += "| $($processInfo.process_id) | $($processInfo.parent_process_id) | $($processInfo.name) | $($processInfo.executable_path) |"
}
$lines += @(
  '',
  '## 下一步',
  '',
  '只在本次证据表明 GUI 或可自动化控件真实存在后，才构建首次合成候选序列验证。首次完整验证必须保存原生报告、输入完整哈希、运行前后完整性、窗口或 UI 轨迹和人工复核，才能把正式观察从 0 增加到 1。',
  ''
)
$lines -join "`n" | Set-Content -LiteralPath (Join-Path $OutputDirectory 'launch-recon-result.md') -Encoding UTF8
Write-Host ($result | ConvertTo-Json -Depth 8)
exit 0
