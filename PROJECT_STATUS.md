# EZCTD 项目状态

> 更新日期：2026-09-03  
> 当前阶段：P0-B0a specification ready / official black-box pending  
> 当前里程碑：26条PDF规则测试语料与CDE验证器黑盒矩阵

## 已完成

- 建立EZCTD私有仓库与规划基线。
- 完成CDE eCTD V3.2.2 / V1.1 PDF 26条规则表的正式原文核验。
- 建立26条规则的机器可读detector contract。
- 建立 **163个** 合规、违规、边界、豁免和交互测试案例规范。
- 建立fixture生成器、manifest格式和矩阵CI校验脚本。
- 建立CDE验证软件V1.1.0黑盒验证协议。
- 建立来源台账、缺口清单和第一次阶段复盘。

## 当前事实状态

- `expected_cde`仍是假设；尚未运行CDE官方验证器，`observed_cde`全部为空。
- 正式技术规范RAR与目录映射XLSX尚未在仓库中固化、解包和计算哈希。
- 官方验证器V1.1.0安装包和操作手册尚未固化。
- 已能开始只读对象采集层，但高争议规则finding语义尚不能冻结。

## 当前目标

为26条规则完成：

```text
官方来源 → detector contract → 最小fixture → CDE V1.1.0实测 → 差异复盘
```

P0-B0退出条件详见`docs/validation/P0-B0_GOAL_AND_EXIT_CRITERIA.md`。

## 下一步执行顺序

1. 取得并固化技术规范RAR、映射XLSX、官方验证器和手册，记录SHA-256。
2. 建立能通过官方验证器的最小中国eCTD序列骨架。
3. 优先运行6.8/6.15、6.18、6.19/6.21和6.23四组高信息量探针。
4. 根据官方结果修订矩阵和finding去重策略。
5. 批量运行其余规则，再进入P0-B只读CLI Scanner。

## 暂不进入

- 自动修复器；
- 完整eCTD Publisher；
- 生命周期操作；
- 自研电子签章；
- 未经官方实测的“100%兼容”声明。
