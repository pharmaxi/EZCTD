# EZCTD 项目状态

> 更新日期：2026-09-03  
> 当前阶段：P0-A 已完成 / P0-B 前置验证  
> 当前里程碑：规则二级证据映射 + CDE 验证器黑盒语料设计

## 已完成

- 确定项目总名：`EZCTD`。
- 形成 PDF 批量预检与修复工具的初步完整 PRD。
- 形成 CDE/eCTD PDF 26 条规则的机器可读草案。
- 完成开源技术资源初筛。
- 明确普通电子申报、PDF Fixer、PDF Sharper 与完整 eCTD Publisher 的产品边界。
- 建立成果一致性校验脚本。
- **完成 P0-A 监管证据包。**
- **确认当前生效基线为 eCTD V3.2.2 / 中国区域技术文件 V1.1，自 2026-03-01 起施行。**
- **26/26 条 PDF 分析规则已逐条回源至《eCTD验证标准V1.1》第 6 章。**
- 固化 26 条官方标题、严重程度、主要说明和适用例外。
- 新增 `cde_ectd_pdf_rules_v1.1_verified.json` 作为实现权威规则源；原 `draft.json` 仅保留为历史基线。
- 与《eCTD实施指南V1.1》7.1、7.2、7.4、7.5 等章节完成交叉核对。
- 明确官方严重程度统计：错误 16 条、警告 8 条、提示信息 2 条。

## 当前事实状态

- PRD 是立项基线，不是冻结版软件规格。
- 26 条 PDF 规则的**官方存在性、编号、标题和严重程度已经核实**。
- 《eCTD技术规范V1.1及附件包》已定位，但 RAR 内部 3.3/3.4 等技术章节尚未建立段落级二级证据映射。
- 尚未建立 26 条规则对应的合成 PDF 正例/反例/边界例测试语料。
- 尚未使用 CDE eCTD 验证软件 V1.1.0 做黑盒结果映射。
- 尚未实现扫描器、修复器、GUI 或 Publisher。

## P0-A 监管证据包

证据输出：

- `evidence/regulatory/P0-A_SOURCE_REGISTER.md`
- `evidence/regulatory/P0-A_PDF_RULES_SOURCE_VERIFICATION.md`
- `rulepacks/cn-cde-ectd/v1.1/cde_ectd_pdf_rules_v1.1_verified.json`

结论：P0-A 的“26 条规则逐条回源核验”已完成。

## 下一里程碑：P0-B 前置验证

按以下顺序推进：

1. 解包《eCTD技术规范V1.1及附件包》，对 3.3/3.4 等相关章节建立段落级引用；
2. 将 `official_*` 监管字段与 `detector/remediation` 工程字段彻底分离；
3. 为 26 条规则建立最小合成 PDF 正例、反例和边界例；
4. 对含参考文献、外文参考资料、申请表等例外规则建立节点上下文测试；
5. 使用 CDE eCTD 验证软件 V1.1.0 对测试样本进行黑盒验证；
6. 建立 `CDE result ↔ EZCTD finding` 映射矩阵；
7. 通过后再实现只读 CLI Scanner。

## P0-B 只读 CLI Scanner 技术基线

- Python；
- qpdf + pikepdf；
- pypdfium2/PDFium；
- pyHanko，仅用于签名发现与验证；
- SQLite/JSONL；
- lxml；
- 进程隔离 worker。

退出条件：

- 扫描过程不修改输入文件；
- 单文件崩溃不终止批次；
- 签名和加密文件能被准确识别；
- 已实现规则均具备可复现测试；
- 输出 finding 可定位到文件、页码和 PDF 对象；
- 与 CDE 官方验证结果建立首批映射。

## 暂不进入

- 完整 eCTD Publisher；
- 生命周期 `new/replace/append/delete`；
- Word 自动排版修复；
- 自研电子签章；
- 云端上传；
- 自动删除所有外部链接、注释、标签或未知对象；
- 缺失字体的一键通用嵌入。
