# CDE eCTD 验证器：中文路径编码与 ASCII 别名探针

- 状态：**BYTE_IDENTICAL_ASCII_ALIAS_UI_REACHED**
- 别名方式：`ntfs_hardlink`
- 与原文件为同一 NTFS 文件：`True`
- SHA-256 字节一致：`True`
- ASCII 别名 UI 可达：`True`
- ASCII 别名仍报 `Main` 缺失：`False`
- Launch4j 日志使用 ASCII 别名：`True`
- 修正绝对 classpath 的 Java 诊断 UI 可达：`None`
- 实际验证已触发：`False`
- `official_black_box_observations`：`0`

## 解释

原始中文文件名在当前非中文 Windows runner 中被 Launch4j 写成问号路径；本探针只改变文件名入口，不改变可执行文件字节。该适配用于确认环境编码故障和恢复 UI，不等同于未经适配的原始安装行为。

## 下一门槛

Use the recorded UI Automation model to select the frozen synthetic input and invoke one real validation transaction.

## 原始证据

- Workflow run: `33827971556`
- Artifact ID: `9920675156`
- Artifact digest: `4a3a0a7b3bb489e4b22a259ba37e41b2490a05358ee394510fdf886655d527c0`
