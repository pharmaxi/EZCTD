# CDE eCTD 官方验证器：合成输入事务

- 运行：`cn-v11-probe-000-invalid-empty-root-20260904T021541Z`
- Case：`cn-v11-probe-000-invalid-empty-root`
- 状态：**SYNTHETIC_TRANSACTION_NOT_ADMISSIBLE_AFTER_EVIDENCE_FINALIZATION**
- 分类：`non_admissible_official_validator_transaction_attempt`
- 实际点击“启动验证”：**False**
- 原生终态：`None`
- 原生报告：**False**
- 输入未变化：**None**
- 证据已保存：**False**
- 本次可采信：**False**
- `official_black_box_observations`：**0**
- `calibration_informative_observations`：**0**

## 原生消息

- 未捕获可解释的原生结果。

## 适用边界

该运行使用与官方应用同一 NTFS 文件、同一 SHA-256 的 ASCII 别名，以规避非中文 Windows runner 对 Launch4j 中文文件名的编码破坏。它不证明未经适配的默认环境可正常运行，也不构成具体 6.x 规则校准。

## 下一门槛

Repair only the failed admissibility gates using the preserved raw evidence; do not increment counters.

## 原始证据

- Workflow run：`33828799828`
- Artifact ID：`9920921926`
- Artifact digest：`4aa29661aafce46a27b729c9adcfbd17345982177407198417a2102954bda043`
- Retention：90 days
