# CDE eCTD 验证器：安装布局与启动取证

- 运行：`cde-validator-forensics-20260904T020228Z`
- 状态：**BYTE_IDENTICAL_ASCII_ALIAS_UI_REACHED**
- 安装器执行：**True**
- 安装器退出码：**0**
- 已安装文件：**313**
- 安装后应用与静态应用字节一致：**True**
- EXE 可按附加 ZIP/JAR 读取：**True**
- `Main.class`：**['Main.class']**
- 官方包装器进程启动：**True**
- 官方包装器 UI 可达：**False**
- `Main` 类缺失错误：**True**
- 诊断 Java 适配器 UI 可达：**False**
- 完整验证运行：**0**
- `official_black_box_observations`：**0**

## 官方包装器窗口

| PID | Visible | Class | Title |
|---:|---:|---|---|
|  |  |  | 未观察到窗口 |

## 诊断适配器边界

直接 Java 适配器只用于理解官方包内的入口类和 UI；即使它成功打开界面，也不能替代官方 EXE 入口，不能计入官方黑盒观察。

## 下一门槛

Use the recorded UI Automation model to select the frozen synthetic input and invoke one real validation transaction.

## 原始证据

- Workflow run: `33827971556`
- Artifact ID: `9920675156`
- Artifact digest: `4a3a0a7b3bb489e4b22a259ba37e41b2490a05358ee394510fdf886655d527c0`
- Retention: 90 days
