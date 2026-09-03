# Changelog

## [Unreleased]

### Added

- 建立 EZCTD 私有 GitHub 仓库基线。
- 纳入 PDF 批量预检与安全修复 PRD v0.1。
- 纳入 CDE/eCTD PDF 6.1–6.26 共 26 条规则研究草案及正式原文核验版。
- 增加项目状态、范围 ADR、规则包说明和监管证据目录说明。
- 增加规划成果结构校验脚本与 GitHub Actions 工作流。
- 建立 P0-B0 五联验证矩阵：正式来源、detector contract、最小fixture、官方验证器预期/实测、未决问题。
- 建立 26 条规则、163 个测试案例的机器可读规范。
- 增加合成 PDF fixture 生成器；当前 130 个配方可执行，22 个待实现，11 个依赖外部工具或正式材料。
- 增加 28 个案例的 smoke corpus、结构自检和可复现压缩包。
- 增加 CDE eCTD验证软件 V1.1.0 黑盒验证协议、PowerShell证据采集脚本和观察JSON Schema。
- 增加 P0-B0 Agent Loop 与第一次阶段复盘。

### Known gaps

- CDE技术规范V1.1 RAR、目录映射XLSX、官方验证器V1.1.0安装包及手册尚未固化哈希。
- 尚未完成官方验证器实测，所有`observed_cde`字段保持为空。

## [0.1.0-planning] - 2026-09-03

- Planning baseline established.
