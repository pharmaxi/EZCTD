# Rulepacks

规则包是 EZCTD 的核心输入，不应散落为界面或代码中的硬编码常量。

当前目录：

```text
cn-cde-ectd/v1.1/
└─ cde_ectd_pdf_rules_v1.1_draft.json
```

## 当前规则状态

现有 JSON 是研究草案：

- 包含 26 条 PDF 规则；
- 适合作为数据模型和开发任务输入；
- 尚未完成逐条官方原文核对；
- 尚未建立完整正反例测试；
- 不得据此宣称覆盖现行 CDE 全部验证要求。

## 正式规则至少需要的字段

- 规则 ID；
- 规则包 ID 和版本；
- 状态：effective / superseded / draft / research；
- 适用范围和例外；
- 官方严重程度；
- EZCTD 修改风险；
- 来源引用和来源哈希；
- 检测器；
- 修复方式；
- 执行前 guard；
- 修复后 postcondition；
- 正例、反例和边界测试。
