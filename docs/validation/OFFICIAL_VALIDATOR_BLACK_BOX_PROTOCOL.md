# CDE eCTD 验证软件 V1.1.0 黑盒观察方案

> 状态：执行前协议。本文定义何时可以把 `official_black_box_observations` 从 0 增加，以及每个数字实际证明什么。它不是验证结果，也不宣称 EZCTD 已与 CDE 软件一致。

## 1. 当前事实

截至本方案形成时：

- 官方外层 ZIP：`eCTD验证软件V1.1.0.zip`
- 外层 ZIP SHA-256：`d3f143873fb37b78dbc952c8d8d6db5a13a82c5ba5a77798b8319852b9ed2b36`
- ZIP 内安装程序：`eCTD验证软件安装包.exe`
- 安装程序 SHA-256：`66c5f189e0a3308568ad99e22da6062b7bbf9d61adec757f3f233521c4c7b8f8`
- 操作手册 SHA-256：`30eef1b42d6fc980b243bcc667291eb7abc9ddc2c4dc33a5c8a67cb1368f583b`
- 安装程序类型：NSIS 3.05，自解压 GUI 安装程序，x86，要求管理员权限
- 安装程序 Authenticode：未签名
- 安装程序产品名、产品版本、公司名资源：空
- 软件已执行：否
- 可采信的完整验证运行：0

安装程序未签名并不否定官方来源；但身份不能依赖 Windows 发布者字段，只能依赖完整证据链：

```text
当前 CDE eCTD 专栏控件
→ 当前同源 common.js 中的下载地址
→ HTTP 响应及文件名
→ 外层 ZIP 哈希
→ 内层安装程序哈希
→ 安装后实际执行文件哈希
```

上述任一环节缺失，不得把运行结果归属于本次固定的 CDE V1.1.0 软件。

## 2. 不再只使用一个含糊计数

后续状态文件同时维护五个数字：

| 计数 | 含义 | 是否能用于规则校准 |
|---|---|---:|
| `launch_reconnaissance_runs` | 安装、启动、窗口和进程侦察 | 否 |
| `completed_validation_runs` | 确实触发验证并达到终态的运行 | 不一定 |
| `admissible_black_box_observations` | 输入、程序身份、原始输出、截图和完整性均满足合同 | 可作为事实观察 |
| `calibration_informative_observations` | 基线足够稳定，且没有上游错误遮蔽目标规则 | 是 |
| `repeated_baseline_controls` | 相同基线的独立完整重复 | 用于判断稳定性 |

兼容字段：

```text
official_black_box_observations
= admissible_black_box_observations
```

启动程序、看到主窗口、安装成功、点击“启动验证”但无原始报告，均不得增加此兼容字段。

## 3. 四类运行

### 3.1 执行侦察（不计数）

目的仅为回答：

- 安装是否成功；
- 安装目录和卸载项是什么；
- 主程序入口是什么；
- 是否需要 Java、浏览器或其他运行时；
- 是纯 GUI 还是存在未记载 CLI；
- 输入选择器要求序列文件夹还是更上层目录；
- 报告输出格式和默认目录是什么；
- 启动、验证、完成和失败时出现哪些窗口、进程和文件。

侦察输出必须包括安装前后文件系统、注册表、服务、计划任务、进程和网络连接差异。它仍是 `launch_reconnaissance_runs += 1`，而不是官方验证观察。

### 3.2 完整验证运行

必须确认验证动作已被触发并达到可判定终态，包括成功、完成但资料有错误、或应用程序明确给出最终失败。仅启动软件不属于完整验证运行。

### 3.3 可采信黑盒观察

完整验证运行还必须满足第 6 节全部证据条件。满足后才计为 1 次 `admissible_black_box_observations`。

### 3.4 可用于校准的观察

在可采信基础上，还需证明：

- 输入序列可被验证器正常遍历；
- 目标 PDF 确实被处理；
- 没有更早的包级、XML、路径、校验和或生命周期错误使目标规则未执行；
- 同一基线多次结果在规则身份、严重程度和定位语义上稳定。

否则观察可以记录，但不得用于评价 EZCTD detector 的灵敏度或特异度。

## 4. 环境分成两条线路

### 4.1 GitHub 托管 Windows：侦察线路

GitHub 托管 runner 是一次性环境，适合：

- 静态解包；
- 安装副作用侦察；
- 判断是否能无人工完成安装；
- 查找入口程序和报告；
- 尝试 UI Automation；
- 形成第一批非代表性运行证据。

但当前 runner 为 Windows Server，而操作手册推荐 Windows 7/10。由此产生的运行结果必须标记：

```text
environment_representativeness = exploratory_outside_manual_recommendation
```

它不能单独成为最终兼容性结论。

### 4.2 隔离 Windows 10/11 虚拟机：复核线路

最终校准至少需要一台：

- 无真实申报资料；
- 无业务账号和密钥；
- 快照可恢复；
- 安装前状态固定；
- Windows 10，或将 Windows 11 明确标为超出手册但接近实际使用环境；
- 分辨率、缩放、区域、语言和时区固定；
- 能运行交互式桌面和 UI Automation；
- 每次批次前恢复快照或执行可证明的卸载/清理。

两条线路结果不一致时，不得取有利结果；需先定位操作系统、权限、字体、路径编码、区域设置、缓存或软件状态差异。

## 5. 第一个真正困难不是 PDF，而是基线序列

验证器接受的是“序列文件夹”，不是孤立 PDF。因此，在判断第 6 章 PDF 规则前，必须先得到一个可重复的 V3.2.2/V1.1 候选基线。

基线达到以下条件前，不称为 `known_good_baseline`：

1. XML/DTD/XSD 可解析；
2. 路径、文件名、引用、校验和和生命周期关系可遍历；
3. 目标叶节点确实被验证器访问；
4. 三次独立运行的包级结果稳定；
5. 第 6 章没有与目标变异无关的噪声；
6. 输入目录在每次运行前后逐文件哈希不变。

第一次运行很可能暴露包级错误。该结果仍可成为可采信观察，但不能直接解释为“目标 PDF 规则未触发”。应按报告逐项修正候选基线，并为每次修正建立新的 `baseline_id` 和目录树哈希。

## 6. 一次观察的最低证据

只有下列项目全部满足，才允许 `official_black_box_observations += 1`：

### 6.1 软件身份

- 官方外层 ZIP 哈希；
- 安装程序哈希；
- 实际主程序哈希；
- 安装后入口路径；
- Authenticode、版本资源和架构，即使结果是未签名或空；
- 安装和启动方式。

### 6.2 环境

- runner/虚拟机类型；
- Windows 版本和构建号；
- 系统区域、显示语言、时区、DPI/缩放和分辨率；
- 管理员权限状态；
- 网络策略；
- 是否由干净快照开始；
- 软件运行前的相关进程和目录状态。

### 6.3 输入

- 输入类型；
- `baseline_id`、`case_id`；
- 完整文件 inventory；
- 每个文件 SHA-256；
- 目录树摘要哈希；
- 输入根目录；
- 运行前、运行后摘要一致；
- 变异相对基线的精确 diff。

### 6.4 执行

- 开始和结束时间；
- 安装/主程序/子进程树；
- 验证动作确实被调用的证据；
- 最终状态；
- 退出码（若适用）；
- UI Automation 轨迹或人工操作记录；
- 超时、崩溃、弹窗和重试记录。

### 6.5 原始结果

优先保留验证器原生报告。至少包括：

- 原生验证报告文件及哈希；
- 完成或失败终态截图；
- 主窗口结果页截图；
- 输出目录完整 inventory；
- 软件日志和标准输出/错误输出（如有）；
- 未经人工修改的原始文件。

如果软件只能显示而不能导出，则需同时保留连续截图、UI Automation 控件树和输出目录快照，并把证据质量标记为 `ui_only`。`ui_only` 可作为探索观察，但默认不得用于最终批量校准，直至独立人工复核。

### 6.6 复核

- 机器合同校验通过；
- 人工复核人和时间；
- 原始消息到标准化消息的映射；
- 任何无法判断的规则明确标为 `INCONCLUSIVE`；
- 不因“没有目标消息”自动判定 detector 假阳性。

## 7. 第一批运行顺序

### 阶段 A：静态深挖

1. 递归解开 NSIS payload；
2. 固定实际入口程序、运行时和配置文件；
3. 查找可能的 CLI 参数、日志配置和报告格式；
4. 不执行任何安装程序或主程序。

### 阶段 B：安装与启动侦察

1. 一次性 Windows runner；
2. 固定安装前快照；
3. 使用官方安装程序；
4. 优先依据手册完成 GUI 安装；若使用 NSIS `/S`，必须单独记录其并非手册明示方式；
5. 固定安装后快照；
6. 启动主程序但不选择任何真实资料；
7. 捕获主窗口、控件树、进程树和默认目录；
8. 结束并清理。

该阶段预期结果：

```text
launch_reconnaissance_runs >= 1
official_black_box_observations = 0
```

### 阶段 C：首次完整验证

1. 使用候选最小序列；
2. 选择独立输出目录；
3. 启动验证；
4. 等待明确终态；
5. 保存原生报告、截图和日志；
6. 验证输入未被改写；
7. 通过观察合同后，将计数从 0 增至 1。

这个“1”只证明：官方软件对该输入完成了一次可复核运行。它不证明基线合格，也不证明任一 PDF 规则正确。

### 阶段 D：基线迭代

按官方报告修复最小序列，每次只改变一类上游问题。禁止同时大面积修改后宣称原因已确定。

### 阶段 E：稳定性和差分校准

在基线达到可解释状态后执行：

```text
baseline-pre
6.8
baseline-mid
6.22
6.26
6.19
6.21
6.1
baseline-post
```

对每个变异记录目标规则、伴随规则、短路关系、定位信息和严重程度。三次基线必须语义稳定。

## 8. 计数算法

伪代码：

```text
completed_validation_runs += validation_reached_terminal_state

admissible =
  schema_valid
  AND official_asset_chain_matches
  AND actual_executable_hash_present
  AND validation_was_invoked
  AND terminal_state_recorded
  AND complete_input_inventory_present
  AND pre_post_input_hash_equal
  AND raw_result_present
  AND screenshot_present
  AND process_or_ui_trace_present
  AND every_evidence_hash_verified
  AND human_review_complete

if admissible:
    admissible_black_box_observations += 1
    official_black_box_observations += 1

calibration_informative =
  admissible
  AND target_leaf_was_processed
  AND no_upstream_short_circuit
  AND baseline_state_interpretable

if calibration_informative:
    calibration_informative_observations += 1
```

计数来自逐运行 `result.json` 的重新计算，不允许人工直接编辑总数。

## 9. 强制反证检查

每次 Agent Loop 完成后必须主动检查：

1. 是否把静态解包误称为执行；
2. 是否把安装或启动误称为验证；
3. 是否把输出文件存在误称为运行完成；
4. 是否把报告中没有目标规则误称为官方不检查；
5. 是否存在包级错误导致 PDF 检查短路；
6. 是否改变了多个变量而仍作单因果解释；
7. 是否用了不同安装程序、入口程序或基线哈希；
8. 是否输入被验证器写回；
9. 是否 UI 自动化点击了错误窗口或旧结果；
10. 是否因 Windows Server 侦察成功而外推到 Windows 10；
11. 是否仅保留标准化 JSON而丢失原生报告；
12. 是否将失败工作流隐藏或改写为成功。

任一项无法排除时，结论降级为 `INCONCLUSIVE`，但原始观察仍保留。

## 10. 阶段状态

| Gate | 当前状态 | 下一证据 |
|---|---|---|
| G0 官方下载路径 | PASS | 当前 `common.js` 和控件证据 |
| G1 外层 ZIP 字节身份 | PASS | 已固定 SHA-256 |
| G2 内层安装程序身份 | PASS WITH WARNING | 未签名；依赖来源链和哈希 |
| G3 递归 payload 静态识别 | IN PROGRESS | 入口程序、运行时和配置 inventory |
| G4 隔离安装/启动侦察 | NOT RUN | 安装前后差异、窗口和进程 |
| G5 首次完整验证 | NOT RUN | 输入、原生报告、截图和完整性 |
| G6 基线三次稳定 | NOT RUN | 三次独立观察 |
| G7 六个目标变异 | NOT RUN | 差分结果 |

在 G5 的证据合同通过前，`official_black_box_observations` 保持 0 是正确行为，而不是待粉饰的缺陷。
