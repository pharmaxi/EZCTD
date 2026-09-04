# CDE eCTD 官方验证器：合成输入事务

- 运行：`cn-v11-probe-000-invalid-empty-root-20260904T024047Z`
- Case：`cn-v11-probe-000-invalid-empty-root`
- 状态：**ADMISSIBLE_ENVIRONMENT_ADAPTED_OFFICIAL_OBSERVATION**
- 分类：`environment_adapted_official_binary_black_box_observation`
- 实际点击“启动验证”：**True**
- 原生终态：`native_terminal_dialog`
- 原生报告：**True**
- 输入未变化：**True**
- 证据已保存：**True**
- 本次可采信：**True**
- `official_black_box_observations`：**1**
- `calibration_informative_observations`：**0**

## 原生消息

- 提示
- System
- Close
- 执行成功
- OK

## 适用边界

该运行使用与官方应用同一 NTFS 文件、同一 SHA-256 的 ASCII 别名，以规避非中文 Windows runner 对 Launch4j 中文文件名的编码破坏。它不证明未经适配的默认环境可正常运行，也不构成具体 6.x 规则校准。

## 下一门槛

Repeat the same frozen case to test stability, then build a minimal sequence baseline before rule-specific mutations.

## 原始证据

- Workflow run：`33830318274`
- Artifact ID：`9921489607`
- Artifact digest：`115e123c8b0e55fb819ca2fbbc80aa4b14cece4ea59913a2e104aebdcf265295`
- Retention：90 days
