# P0-B0 Agent Loop

## 循环定义

每轮只推进一个可验证假设：

```text
OBSERVE → SOURCE → HYPOTHESIZE → SPECIFY → GENERATE → LOCAL-CHECK
        → OFFICIAL-RUN → COMPARE → REVIEW → COMMIT
```

### 1. OBSERVE

读取当前规则矩阵、未决问题、失败样本和官方输出。禁止仅凭记忆修改规则。

### 2. SOURCE

优先读取当前生效的CDE/NMPA正式文件；ICH用于全局语义；PDF规范和官方库文档用于对象实现。商业软件行为仅作对照。

### 3. HYPOTHESIZE

把一个模糊规则转成可证伪假设。例如：

> 对`/XYZ`目的地，zoom=`0`是否被CDE V1.1.0视为Inherit Zoom？

### 4. SPECIFY

在矩阵中写清：主变量、控制变量、eCTD节点、预期规则、允许联动规则、禁止出现的额外变化。

### 5. GENERATE

从同一基线生成最小变异样本。一次只改一个主变量；交互探针必须显式命名。

### 6. LOCAL-CHECK

至少执行：

- SHA-256；
- pypdf/qpdf结构检查之一；
- 独立页面渲染；
- 目标PDF对象断言；
- 非目标对象差异摘要。

### 7. OFFICIAL-RUN

仅在Windows受控环境中运行CDE验证软件V1.1.0。保存原始输出，不手工改写。

### 8. COMPARE

比较`expected_state`和`observed_state`。差异分类：

- `SOURCE_INTERPRETATION`
- `FIXTURE_INVALID`
- `CONTEXT_MISMATCH`
- `VALIDATOR_BEHAVIOR`
- `EZCTD_DEFECT`
- `UNRESOLVED`

### 9. REVIEW

每完成一个规则簇或出现3个以上差异，写一次复盘。复盘必须包含反证、漏报风险和是否回退。

### 10. COMMIT

一次提交只承载一组可解释变化。提交信息至少指出规则号或证据范围。

## 停止条件

出现以下情况时不得继续自动扩展：

- 正式规则原文与当前矩阵冲突；
- 测试样本引入多个未受控变量；
- 官方验证器版本或安装包哈希不明；
- 电子签章、加密、XFA等高风险对象可能被破坏；
- 尚未取得eCTD节点上下文，却试图套用豁免；
- 本地解析器之间结果不一致且未定位原因。

## 当前循环队列

1. 锁定官方软件和手册字节文件及哈希。
2. 解包技术规范RAR，定位3.3/3.4和区域附件。
3. 建立最小有效eCTD序列骨架。
4. 先跑6.8/6.15、6.18、6.19/6.21、6.23四组高信息量探针。
5. 根据官方输出修订矩阵，再批量扩展其余规则。
