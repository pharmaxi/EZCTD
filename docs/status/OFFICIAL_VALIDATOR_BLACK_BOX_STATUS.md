# CDE eCTD 官方验证器黑盒状态

- 当前状态：**SYNTHETIC_TRANSACTION_NOT_ADMISSIBLE_AFTER_EVIDENCE_FINALIZATION**
- 验证事务尝试：**2**
- 完整验证运行：**0**
- 可采信黑盒观察：**0**
- 环境适配的官方二进制观察：**0**
- 默认环境观察：**0**
- 规则校准观察：**0**
- `official_black_box_observations`：**0**

## 最近一次事务

- 运行：`cn-v11-probe-000-invalid-empty-root-20260904T022107Z`
- Case：`cn-v11-probe-000-invalid-empty-root`
- 分类：`non_admissible_official_validator_transaction_attempt`
- 可采信：`False`
- 原生终态：`None`
- 原生报告：`False`
- 输入未变化：`None`

## 当前解释

`official_black_box_observations` 只统计满足证据合同的完整事务。环境适配观察使用官方原始字节，但通过 ASCII NTFS 别名规避 runner 编码缺陷；因此单独统计，不能冒充默认环境兼容性，也不能直接当作具体规则校准结果。

## 下一门槛

Repair only the failed admissibility gates using the preserved raw evidence; do not increment counters.
