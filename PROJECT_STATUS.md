# EZCTD 项目状态

> 更新日期：2026-09-03  
> 当前阶段：Planning baseline complete / P0 尚未开始  
> 当前里程碑：建立监管证据包与只读扫描器技术验证

## 已完成

- 确定项目总名：`EZCTD`。
- 形成 PDF 批量预检与修复工具的初步完整 PRD。
- 形成 CDE/eCTD PDF 26 条规则的机器可读草案。
- 完成开源技术资源初筛。
- 明确普通电子申报、PDF Fixer、PDF Sharper 与完整 eCTD Publisher 的产品边界。
- 建立成果一致性校验脚本。

## 当前事实状态

- PRD 是立项基线，不是冻结版软件规格。
- 26 条规则仍需逐条回到正式 CDE 原始文件，确认原文、严重程度、适用范围和例外。
- 尚未建立真实或合成 PDF 测试语料。
- 尚未实现扫描器、修复器、GUI 或 Publisher。
- 尚未形成与 CDE 官方验证软件的黑盒兼容性证据。

## 下一里程碑：P0-A 监管证据包

必须先完成：

1. 固化当前适用的 CDE/eCTD 正式技术文件及附件；
2. 为每条规则登记来源、发布日期、生效日期、状态和文件哈希；
3. 区分正式规则、征求意见稿、行业偏好和 EZCTD 产品护栏；
4. 逐条修订 `cde_ectd_pdf_rules_v1.1_draft.json`；
5. 为首批 15–20 条规则建立正例、反例、边界例、签名例和异常 PDF 例。

## P0-B 只读 CLI Scanner

建议技术基线：

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
