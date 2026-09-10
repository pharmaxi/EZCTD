# CDE eCTD 验证软件 V1.1.0：校准批次 01

> 状态：`NOT_RUN`  
> 目标：在执行 130 个边界实验前，先确认官方软件的报告格式、消息共存、阻断顺序和几个关键技术判据。

## 一、为什么先做 7 案而不是直接跑 130 案

官方《eCTD验证标准V1.1》给出了规则标题、严重程度和解释，但没有公开每项底层对象遍历、阈值、消息合并和报告序列化细节。如果一开始批量跑大量案例，包级错误、样本交叉污染和软件状态可能掩盖真正差异。

首批 7 案覆盖互补的信息维度：

| 案例 | 作用 | 主要回答 |
|---|---|---|
| `CDE-PDF-BASELINE` | 阴性对照 | 差分包本身是否干净，报告是否稳定 |
| `CDE-PDF-6-1-POS` | 不可读文件 | PDF 解析失败与包级错误的顺序、后续规则是否短路 |
| `CDE-PDF-6-8-POS` | 书签显式缩放 | `/XYZ` 数值缩放是否命中 6.8，报告是否定位书签 |
| `CDE-PDF-6-19-POS` | 空用户密码、权限受限 | 6.19 与 6.21 的区分、权限信息粒度 |
| `CDE-PDF-6-21-POS` | 非空用户密码 | 6.21 与 6.19 是否共存、是否阻断其余 PDF 分析 |
| `CDE-PDF-6-22-POS` | 未线性化 | Fast Web View 的真实检查方式和提示等级 |
| `CDE-PDF-6-26-POS` | 使用中的非标准未嵌入字体 | 是否检查实际使用、是否报告字体名和页码 |

## 二、硬前提

开始前必须同时满足：

1. 官方 V1.1.0 安装包已经记录来源、文件名、SHA-256、数字签名和版本资源；
2. 操作手册已记录来源和 SHA-256；
3. 有一个经同一软件、同一环境验证无阻断问题的中国 eCTD baseline sequence；
4. baseline 的完整报告和全文件 SHA-256 inventory 已固化；
5. 已确定一个可被逐案替换的 PDF 叶节点；
6. 每次实验均从 baseline 只读副本重建，不连续累积修改；
7. 替换后更新叶文件 MD5、骨架 XML 和 `index-md5.txt`，并先做独立包级复核。

任一前提不满足时，状态保持 `NOT_RUN` 或 `PREPARED_NOT_RUN`，不能填写为官方已验证。

## 三、准备命令

在 Windows PowerShell 中，从仓库根目录执行：

```powershell
.\tools\cde-validator\Prepare-CalibrationBatch.ps1 `
  -BaselineSequence "C:\EZCTD\baseline\clean-sequence" `
  -SmokeDirectory "C:\EZCTD\p0-b0-smoke" `
  -LeafRelativePath "0000\m5\...\leaf.pdf" `
  -OutputRoot "C:\EZCTD\calibration-01\packages" `
  -EvidenceRoot "C:\EZCTD\calibration-01\evidence" `
  -ValidatorVersion "1.1.0" `
  -ValidatorBinary "C:\Program Files\...\validator.exe"
```

脚本只做：

- 核验输入是否存在；
- 从 baseline 为 7 案分别复制资料包；
- 替换同一个 PDF leaf；
- 更新 XML 中对应 leaf MD5；
- 更新 `index-md5.txt`；
- 生成包 inventory；
- 为每案建立报告、截图和结构化结果目录。

脚本**不会**自动启动或操纵 CDE 软件，也不会填写官方结果。

## 四、运行顺序

为降低软件缓存和状态影响，推荐：

1. baseline；
2. 6.8；
3. baseline 重跑；
4. 6.22；
5. 6.26；
6. 6.19；
7. 6.21；
8. 6.1；
9. baseline 末次重跑。

6.1 和 6.21 放在后部，是因为它们可能导致解析短路、弹窗或应用内部异常状态。每次运行后记录软件是否需要重启。

## 五、每案最低证据

- `result.json`；
- 软件版本界面截图；
- 输入资料包 inventory 与 SHA-256；
- 原始完整验证报告；
- 结果列表全屏截图；
- 展开目标消息后的细节截图；
- 开始和结束时间；
- 操作人；
- 是否重启软件；
- baseline ID；
- 实际 rule/message/severity/object/path；
- 非目标消息和包级消息；
- 复核结论：`MATCH`、`PARTIAL`、`OFFICIAL_ONLY`、`EZCTD_ONLY` 或 `INCONCLUSIVE`。

最后执行：

```powershell
.\tools\cde-validator\Finalize-OfficialRun.ps1 `
  -RunDirectory "C:\EZCTD\calibration-01\evidence\CDE-PDF-6-8-POS"
```

Finalizer 会拒绝：

- `NOT_RUN` 未改；
- 缺少 package inventory hash；
- 没有原始报告；
- 没有截图。

## 六、批次退出条件

只有在以下条件全部满足时，批次状态才能从 `NOT_RUN` 改为 `COMPLETE`：

- 7 个实验包均由同一 baseline 生成；
- baseline 首次、插入和末次对照均无新增阻断；
- 7 案均有完整原始证据；
- 对 6.19/6.21 的消息共存关系形成明确结论；
- 对 6.8 的 `/XYZ null` 对照和数值 zoom 阳性形成结论；
- 对 6.22 的检测对象是最终字节线性化状态还是仅标志形成结论；
- 对 6.26 的“使用中字体”与“仅资源存在字体”形成下一轮对照计划；
- 所有不一致都进入边界实验队列，没有被手工改成“通过”。

## 七、后续扩展顺序

校准批次通过后，按风险而不是规则编号扩展：

1. 动作与链接：6.2–6.15；
2. 安全、动态内容与注释：6.17–6.24；
3. 可搜索性与字体：6.25–6.26；
4. 包上下文例外：参考文献、外文参考资料、申请表、Fast Web View 特定节点；
5. 交互案例和解析器分歧；
6. 最后才跑完整 130 案。
