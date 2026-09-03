# ADR-0001：项目名称与第一阶段边界

- 状态：Accepted
- 日期：2026-09-03

## 决策

项目总名确定为 **EZCTD**。

第一阶段产品不是完整 eCTD Publisher，而是：

> 面向 CDE/eCTD 申报资料的本地 PDF 预检、分级修复、复验和审计工作台。

现有 PRD 保留早期工作名 `RegPDF Workbench`，避免修改已经形成的原始基线；后续正式规格冻结时统一产品内命名。

## 原因

- PDF 批量预检和安全修复具有明确、直接的个人使用价值；
- qpdf、pikepdf、PDFium 等开源能力足以支持技术验证；
- 完整 Publisher 还涉及 XML backbone、区域元数据、STF、序列和生命周期，复杂度远高于 PDF 修复；
- 一次性仿做 PDF Fixer、PDF Sharper、Word Sharper、Publisher 和 Docmas 会导致项目失焦。

## 后果

- 仓库先建立规则包、扫描器和修复器的边界；
- `publisher/`、`word/` 和协作文档管理功能暂不建模块；
- 所有自动修复必须通过 guard、postcondition 和独立复验；
- 已签名 PDF 默认禁止重写；
- 官方验证软件继续作为最终交叉验证对象。
