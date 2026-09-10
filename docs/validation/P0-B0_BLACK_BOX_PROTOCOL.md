# CDE eCTD验证软件V1.1.0黑盒验证协议

## 1. 目的

测量官方验证器对26条PDF规则的真实输入—输出行为，包括：规则触发、严重程度、定位粒度、规则联动、抑制顺序、豁免和边界值。

## 2. 受控环境

每次运行记录：

```json
{
  "validator_name": "CDE eCTD验证软件",
  "validator_version": "1.1.0",
  "installer_sha256": null,
  "manual_sha256": null,
  "os_edition": null,
  "os_build": null,
  "locale": "zh-CN",
  "timezone": "Asia/Shanghai",
  "run_started_at": null,
  "operator": null
}
```

安装包哈希或版本无法确认时，运行结果只能标记`PROVISIONAL`。

## 3. 测试包分层

### Layer 0：PDF对象自检

确认fixture确实含目标对象，且除预定变量外与基线一致。

### Layer 1：最小有效eCTD序列

使用同一有效中国序列骨架，仅替换一个叶文件。XML、DTD/XSD、MD5和路径必须通过基线验证。

### Layer 2：节点豁免对照

同一PDF分别放入普通节点与规则规定的豁免节点。文件字节保持不变，只改变叶节点上下文。

### Layer 3：交互探针

只用于规则重叠，例如JavaScript书签、打开密码+权限限制、失效书签+6页文档。必须声明允许出现的关联规则。

## 4. 基线门槛

任何变异测试前，基线序列必须：

- 官方验证器PDF第6章无错误/警告/提示，或所有固有finding已冻结为baseline noise；
- 目录、XML、DTD/XSD、MD5和生命周期规则通过；
- 基线报告和序列全量哈希已保存；
- 每次变异只替换目标PDF及必需的MD5/XML引用。

## 5. 单案例运行步骤

1. 从只读基线复制工作目录。
2. 放入fixture，重新计算必要哈希，不修改其他业务内容。
3. 计算完整输入清单和SHA-256。
4. 运行官方验证器，不在运行中手工修复。
5. 导出原始报告；若软件只能显示界面，则保存全屏截图和逐条导出。
6. 将官方消息原文解析到`observations/*.json`，但原报告保持不变。
7. 将结果与预期比较，写差异分类。
8. 重新运行一次验证幂等性；结果不同则标记`NONDETERMINISTIC`。

## 6. 观察结果结构

```json
{
  "case_id": "CN-PDF-6_8-xyz-zero",
  "input_sha256": "...",
  "sequence_manifest_sha256": "...",
  "validator": {"version":"1.1.0","installer_sha256":"..."},
  "official_findings": [
    {"rule_id":"6.8","severity":"警告","message_raw":"...","file_path":"...","page":null}
  ],
  "target_rule_observed_state": "FINDING",
  "unexpected_rule_ids": [],
  "repeat_run_equal": true,
  "evidence_files": ["raw-report/...", "screenshots/..."],
  "review_status": "REVIEWED"
}
```

## 7. 判定

- `CONFIRMED`：目标规则、严重程度及关键上下文与预期一致，且两次运行一致。
- `PARTIAL`：触发规则正确，但消息、定位或联动与预期不同。
- `CONTRADICTED`：官方结果与预期相反。
- `UNUSABLE`：基线无效、样本损坏或软件版本不明。

## 8. 高优先级实验顺序

1. 6.8/6.15：`null`与`0`的承前缩放语义。
2. 6.18：Link、普通注释、签名Widget和官方签章文件。
3. 6.19/6.21：打开密码与权限限制拆分。
4. 6.23：5页边界、无效书签和豁免。
5. 6.4/6.11/6.24：JavaScript规则联动。
6. 6.16：Header、Catalog和真实PDF/A。
7. 其余书签/链接完整性规则。

## 9. 禁止事项

- 不得用第三方验证器结果冒充CDE结果。
- 不得手抄官方报告后删除原始报告。
- 不得在同一个样本中无记录地修复多个问题。
- 不得因为商业软件不报错就更改CDE规则。
- 不得把“未触发”直接解释成“官方允许”；应先排除上下文和样本无效。
