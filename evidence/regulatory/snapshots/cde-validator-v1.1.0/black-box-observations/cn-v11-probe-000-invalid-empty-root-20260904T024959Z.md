# CDE eCTD 官方验证器：合成输入事务

- 运行：`cn-v11-probe-000-invalid-empty-root-20260904T024959Z`
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
- Artifact ID：`9921682707`
- Artifact digest：`e192f292daa49b3047f06dd0ffb8e021ab552dd4e747e0b4ea7158ca872f0ca5`
- Retention：90 days
