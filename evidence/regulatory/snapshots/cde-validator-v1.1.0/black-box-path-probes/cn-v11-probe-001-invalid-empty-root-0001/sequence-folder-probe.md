# CDE 验证器序列目录名隔离试验：0000 → 0001

- Case：`cn-v11-probe-001-invalid-empty-root-0001`
- 事务：`cn-v11-probe-001-invalid-empty-root-0001-20260904T040147Z`
- 事务状态：**ADMISSIBLE_ENVIRONMENT_ADAPTED_OFFICIAL_OBSERVATION**
- 官方黑盒观察可采信：**True**
- 目录：`C:\EZCTDProbeInput\0001`
- 仍出现“序列文件夹不是数字”：**True**
- 原生报告规则条目：151
- 提示 / 警告 / 错误：5 / 22 / 97

## 与三次 0000 控制结果比较

- 严重度总数相同：**False**
- 可见规则条目相同：**True**
- 路径警告在 0001 中持续：**True**
- 结论：**WARNING_PERSISTS_WITH_0001**

## 解释边界

该试验只改变所选空目录的末级名称。若 0001 仍出现同一提示，则不能把提示简单解释为 0000 的保留序列号；还需检查官方程序对“选择目录层级”的预期、父目录结构和空目录前置条件。该结果仍不是 PDF 规则校准。
