# RegPDF Workbench：CDE/eCTD PDF 批量预检与修复工具 PRD v0.1

> 文档状态：初步完整稿（EZCTD planning baseline）  
> 日期：2026-09-03  
> 首要平台：Windows 10/11，本地离线桌面应用  
> 首要用户：个人学习、个人/小团队注册申报资料制作  
> 当前规则 profile：`cde-ectd-v3.2.2-cn-v1.1`  
> 项目总名：**EZCTD**；`RegPDF Workbench` 为首阶段工作台工作名。

## 1. 产品结论

EZCTD 第一阶段不做完整 eCTD Publisher，也不做 Collie 全家桶。首个产品是一个**规则驱动、本地离线、原件不覆盖的 PDF Preflight + Safe Batch Fixer**：

```text
导入资料目录
→ 建立输入快照和申报上下文
→ 按规则包扫描
→ 输出文件/页/对象级 Finding
→ 生成 A/B/C 分级修复计划
→ 用户确认高风险项
→ 写入独立输出目录
→ 结构复验 + 页面渲染复验
→ 输出 JSON/HTML/CSV 报告
→ 使用 CDE 官方验证软件最终交叉验证
```

后续再扩展 CDE Package Validator、交互式 PDF Sharper、Word 源文件质量模块以及完整 eCTD Publisher。

## 2. 产品边界

### P0/P1：PDF Preflight + Batch Fixer

必须实现：

- 批量递归导入；
- PDF 可读性、版本、书签、链接、注释、附件、动态内容、安全设置、初始视图、Fast Web View、可搜索性、字体等检查；
- CDE PDF 6.1–6.26 规则 profile；
- 规则例外和 CTD 上下文；
- A/B/C 修复分级；
- 原件只读、staging 输出、失败回滚；
- 签名文件默认只读；
- 修复前后结构差异和 PDFium 渲染差异；
- JSON/HTML/CSV 报告；
- CLI 与桌面端共用核心引擎。

### P2：CDE eCTD Package Validator

增加：

- m1–m5、util、序列和申请根目录识别；
- `index.xml`、`cn-regional.xml`、DTD/XSD；
- 文件名、路径、大小、MD5；
- 跨文件链接图；
- CTD 章节、语言和资料类型上下文；
- 前序列读取和关键生命周期校验。

### P3：受控 eCTD Publisher

后置实现：

- 序列；
- XML backbone；
- leaf metadata；
- `new/replace/append/delete`；
- STF；
- 区域元数据；
- 生命周期视图；
- 导出和官方验证。

### 暂不做

- 通用 Acrobat 替代；
- 云端上传；
- 自动重写科学内容；
- 未知密码绕过；
- 通用字体自动补嵌；
- 自研正式电子签章；
- Docmas 式多人协作和企业 eDMS。

## 3. 产品原则

1. **原件永不默认覆盖。** 修改写入独立 staging/output。
2. **SCAN → PLAN → APPROVE → EXECUTE → VERIFY → REPORT。** 扫描时禁止直接修改。
3. **签名后只检查。** 已签 PDF 默认禁止重写。
4. **官方严重程度与产品修改风险分离。** 官方“提示”也可能对应高风险修改。
5. **规则版本化。** 正式规则、草案、行业偏好和 EZCTD 产品护栏不能混称。
6. **不为了全绿删除语义不明内容。** 无法确定正确目标时只报告或给候选。
7. **最终以适用的 CDE 官方工具和正式要求为准。** EZCTD 是预检和修复辅助工具。

## 4. 用户旅程

### 4.1 散 PDF 批量预检

用户选择文件夹后：

1. 递归发现 PDF；
2. 建立 SHA-256、页数、版本、签名、加密等快照；
3. 执行规则；
4. 按错误/警告/提示和 A/B/C 风险展示；
5. 导出报告或生成修复计划。

散文件模式必须显示“上下文未知”，不能错误应用章节例外。

### 4.2 完整 eCTD 序列预检

用户选择申请根目录或序列目录后：

1. 识别 m1–m5、util 和 XML；
2. 映射 PDF 至 CTD 节点、语言和资料类型；
3. 正确应用章节例外；
4. 验证跨文件书签和链接；
5. 输出 profile 级报告。

### 4.3 批量修复

修复计划按操作分组，例如：

- 书签 Inherit Zoom；
- 链接 Inherit Zoom；
- 初始视图；
- PDF 版本；
- Fast Web View；
- 外部/无效目标；
- 附件/注释/动态内容；
- OCR 候选。

每组必须显示影响文件数、是否删除信息、是否改变视觉内容、是否涉及签名以及复验方式。

## 5. 修复风险分级

### A：确定性、低风险

可默认选中，但仍记录变更：

- 书签/链接 Inherit Zoom；
- 初始视图；
- 页面布局和默认缩放；
- 普通 PDF 在条件满足时规范重写到目标版本；
- Fast Web View（仅适用节点，且作为最后写入步骤）。

### B：必须预览确认

- 删除网页、邮箱、外部链接；
- 删除无效书签/链接；
- 附件先导出再删除；
- 非 Link 注释；
- JavaScript、3D、音视频和其他动态内容；
- 已知凭据条件下去除安全设置；
- OCR；
- 跨文件路径改写；
- 多动作裁决。

### C：不自动修复

- 缺失或语义不明的目标；
- 自动猜测完整书签结构；
- 缺失字体的通用嵌入；
- 未知密码；
- 已签名 PDF 的结构修改；
- 生命周期 `replace/append/delete` 自动决策。

## 6. 核心功能需求

### 6.1 导入与快照

记录：

- 相对路径；
- 文件大小、修改时间；
- SHA-256；
- eCTD 场景需要时计算 MD5；
- PDF 版本、页数；
- 加密/签名状态；
- CTD 上下文和 profile。

### 6.2 多引擎预检

至少使用：

- qpdf：结构检查、恢复诊断、线性化；
- pikepdf：对象级解析和写入；
- PDFium/pypdfium2：页面渲染和视觉复核；
- pyHanko：签名发现与验证；
- 可选 PDFBox/veraPDF：独立交叉验证。

单个解析器“能打开”不能作为可靠性充分条件。

### 6.3 Finding 数据模型

每条 Finding 至少包含：

```text
finding_id
rule_id
profile_id
official_severity
product_risk
file_path
page_number
object_reference
message
evidence
suggested_action
autofix_level
status
```

### 6.4 书签与链接

检测：

- 内部目的地；
- Named Destination；
- GoTo / GoToR / Launch / URI / JavaScript；
- 绝对路径和相对路径；
- 包外目标；
- 目标页不存在；
- 多动作；
- 无效对象；
- Inherit Zoom；
- 链接矩形越界/零面积。

改名必须视为包级事务，同时更新跨文件引用和后续索引/哈希。

### 6.5 字体与 OCR

字体首版以**检测和定位**为主。无法获得准确字体程序、许可和字符映射时，应返回源 Word/PDF 重新生成，不得声称可通用补嵌。

OCR 只对疑似无文本层页面执行；默认保留原页面图像，只添加检索文本层，并进行页面差异和搜索抽样。

### 6.6 数字签名

- 识别签名字段和 ByteRange；
- 已签文件默认只读；
- 修改完成后再使用官方/认可签章工具；
- 签后仅执行无写入终检。

### 6.7 输出和报告

- 永不原地覆盖；
- 单文件失败不影响批次；
- 成功输出需重新打开和复检；
- 记录输入/输出哈希；
- 记录所有实际操作；
- 输出 HTML、JSON、CSV；
- 报告明确“EZCTD 结果不等同于官方受理结论”。

## 7. CDE PDF 规则

机器可读规则基线位于：

`rulepacks/cn-cde-ectd/v1.1/cde_ectd_pdf_rules_v1.1_draft.json`

当前共 26 条（6.1–6.26），覆盖：

- PDF 可读性；
- 书签相对路径、外部目标、动作、失效、目标损坏、多动作、Inherit Zoom；
- 超链接相对路径、外部目标、动作、失效、目标损坏、多动作、Inherit Zoom；
- PDF 版本；
- 附件；
- 注释；
- 安全设置和密码；
- 初始视图；
- Fast Web View；
- >5 页书签要求；
- JavaScript/3D/音视频；
- 可搜索性；
- 非标准字体嵌入。

当前 JSON 是**研究草案**，必须逐条回源验证正式原文、严重程度、适用范围和例外后才能进入 `effective` 状态。

## 8. 技术架构

推荐第一阶段：

```text
Desktop UI (后续 Tauri + React + PDF.js)
        ↓
Application / Job Orchestrator
        ↓
Python Worker Pool
        ├─ qpdf / pikepdf
        ├─ PDFium renderer
        ├─ pyHanko signature inspector
        ├─ lxml / eCTD context
        └─ optional OCR adapter
        ↓
Normalized Document Model
        ↓
Versioned Rule Engine
        ↓
Findings → FixPlan → Executor → Verifier → Report
```

CLI 优先于 GUI：

```bash
ezctd scan <path> --profile cde-ectd-v3.2.2-cn-v1.1
ezctd plan <project> --safe-only
ezctd fix <plan> --out ./output
ezctd verify ./output --against ./source
ezctd report <run> --format html,json,csv
```

## 9. 推荐开源资源

核心优先：

- `qpdf/qpdf`：低层 PDF 结构、修复和线性化；
- `pikepdf/pikepdf`：Python 对象级读写；
- `pypdfium2-team/pypdfium2`：PDFium 渲染；
- `mozilla/pdf.js`：前端预览；
- `MatthiasValvekens/pyHanko`：签名检查；
- `ocrmypdf/OCRmyPDF` + Tesseract：可选 OCR；
- `PaddlePaddle/PaddleOCR`：中文复杂页面研究；
- `apache/pdfbox`、`veraPDF`：独立 QA；
- `lxml`：XML/XSD/Schematron；
- `tauri-apps/tauri`：后续桌面壳。

`PyMuPDF` 功能强，但许可证和未来分发策略需要单独评估，不作为默认不可替换核心。

GitHub 上的 eCTD validator/publisher 小型项目只作为架构和测试思路参考，不能作为 CDE 规则真值。

## 10. 关键技术难点

1. **畸形 PDF 的可读性没有单一标准。** 必须多引擎检查。
2. **规则依赖 CTD 上下文。** 单个 PDF 无法可靠判断全部章节例外。
3. **损坏链接是语义问题。** 正确目标往往不能自动猜测。
4. **字体不能凭名称补齐。** 字体文件、字符映射和许可缺一不可。
5. **OCR 可能改变页面和文件结构。** 必须显式高风险处理。
6. **页面和链接坐标存在耦合。** 页面尺寸转换会牵动注释、目的地和表单。
7. **签名和完整重写天然冲突。** 修复必须在签章前完成。
8. **完整 Publisher 的难点是生命周期，而不是生成目录。**
9. **官方验证器存在实现细节。** 必须建立 CDE 黑盒差分测试。

## 11. 测试策略

### Golden Corpus

每条首批规则至少建立：

- 正例；
- 反例；
- 边界/例外例；
- 签名例；
- 加密/损坏例；
- 修复后回归例。

真实项目使用脱敏副本且不进入公开 Git 仓库。

### 修复后验证

每个输出至少检查：

- qpdf 结构；
- pikepdf 重开；
- PDFium 渲染；
- 页数和页面尺寸；
- 文本提取异常下降；
- 书签/链接目标；
- 规则重跑；
- 视觉差异；
- 幂等性。

### 官方差分验证

固定测试包同时运行 EZCTD 与 CDE 官方验证软件，对差异分类：漏报、误报、上下文差异、规则实现差异或测试样本问题。

## 12. MVP 验收标准

MVP 必须满足：

- 导入散 PDF、文件夹和 eCTD 序列；
- 首批规则具有可复现测试，随后补齐 26 条；
- A 类修复不改变可见页面内容；
- 已签文件 100% 不被写入；
- 原件不覆盖；
- 单文件崩溃不终止批次；
- 修复可复验且幂等；
- 输出 Finding 能定位到证据；
- HTML/JSON/CSV 报告；
- 与 CDE 官方软件建立兼容性记录。

禁止用以下宣传性指标作为验收标准：

- “100% eCTD 合规”；
- “一键修复全部问题”；
- “完全替代 Acrobat”；
- “保证受理”。

## 13. 路线图

### P0-A：监管证据包

- 固化 CDE/NMPA 正式来源；
- source register；
- 26 条规则逐条回源；
- 区分 effective / superseded / draft / research / product_guardrail；
- 建立首批测试样本。

### P0-B：只读 CLI Scanner

- qpdf/pikepdf；
- PDFium；
- pyHanko；
- 15–20 条证据充分规则；
- JSON 报告；
- 不修改输入。

### P1：Safe Fixer + Desktop MVP

- FixPlan；
- guard / postcondition；
- A/B/C 操作；
- staging/rollback；
- PDF 预览和视觉差异；
- HTML 报告；
- Windows 桌面端。

### P2：Package Validator

- XML、DTD/XSD；
- MD5；
- 路径和包结构；
- CTD 上下文；
- 跨文件引用；
- 官方验证差分。

### P3：Publisher

在 Package Validator 稳定后独立立项。

## 14. 数据安全与仓库要求

- 默认完全离线；
- 不上传资料正文；
- worker 禁止执行 PDF JavaScript/Launch；
- 真实项目、证书私钥、密码和商业秘密不进入 Git；
- `evidence/` 只存公开来源登记、哈希和允许保存的公开文件；
- 依赖版本和规则包版本必须可追溯。

## 15. 外部参考

### 监管

- CDE：关于更新电子申报资料制作软件的通知（用户提供的 V1.0.1 通知）
- CDE/NMPA 当前 eCTD 技术文件及验证软件
- ICH eCTD V3.2.2 / V4.0 资料

### 竞品

- Collie PDF Fixer
- Collie PDF Sharper
- Collie eCTD Publisher
- Collie Word Sharper
- Collie Docmas

### 开源

- https://github.com/qpdf/qpdf
- https://github.com/pikepdf/pikepdf
- https://github.com/pypdfium2-team/pypdfium2
- https://github.com/mozilla/pdf.js
- https://github.com/apache/pdfbox
- https://github.com/veraPDF
- https://github.com/ocrmypdf/OCRmyPDF
- https://github.com/tesseract-ocr/tesseract
- https://github.com/PaddlePaddle/PaddleOCR
- https://github.com/MatthiasValvekens/pyHanko
- https://github.com/tauri-apps/tauri

## 16. 当前最优下一步

不要先做 GUI，也不要先做 Publisher。立即进入 P0：

```text
监管证据包
→ 规则逐条回源
→ 30+ 合成 PDF corpus
→ CLI scan
→ 首批 A 类 fix
→ verify
→ report
→ 与 CDE 官方验证软件差分
```

先证明“**规则正确、检测准确、修改安全、复验可信**”，再扩展功能。
