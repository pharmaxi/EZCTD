# EZCTD

**面向中国药品注册申报资料的本地、离线、规则驱动型 PDF 预检与安全批量修复工具。**

> 当前阶段：立项与规则研究（P0 前置）  
> 当前成果版本：v0.1 planning baseline  
> 仓库属性：Private  
> 当前不构成官方 CDE 验证器，也不保证资料通过受理或技术审评。

## 项目定位

EZCTD 首先解决申报 PDF 的实际批量处理问题：

```text
导入资料目录
→ 按指定规则包扫描
→ 定位 PDF、书签、链接、字体、OCR、签名及页面问题
→ 生成分级修复计划
→ 在独立输出目录执行
→ 结构复验与页面渲染复验
→ 输出可追溯报告
→ 使用 CDE 官方软件最终交叉验证
```

完整 eCTD Publisher、生命周期管理、Word Sharper 和文档管理系统均不属于首个版本范围。

## 当前成果

| 路径 | 内容 | 状态 |
|---|---|---|
| `docs/prd/RegPDF_Workbench_CDE_eCTD_PRD_v0.1.md` | 初步完整 PRD：产品边界、监管基线、技术架构、难点、可行性、路线和测试策略 | Baseline |
| `rulepacks/cn-cde-ectd/v1.1/cde_ectd_pdf_rules_v1.1_draft.json` | CDE/eCTD PDF 规则草案，共 26 条 | Draft / 待逐条回源验证 |
| `PROJECT_STATUS.md` | 当前阶段、已完成事项和下一阶段入口 | Active |
| `scripts/validate_artifacts.py` | 校验 PRD 与规则 JSON 的结构和一致性 | Active |

## 核心原则

1. **原件默认不覆盖。** 所有修改写入独立输出目录。
2. **扫描、计划、批准、执行、复验分离。** 禁止扫描时直接修改。
3. **签名文件默认只读。** 修改完成后再签章。
4. **官方严重程度与产品修改风险分开。** “提示”不等于可以安全自动修改。
5. **规则必须版本化并保留来源。** 正式规则、草案、行业偏好和产品护栏不能混称。
6. **不能为追求“全绿”而删除语义不明的内容。**
7. **本工具用于预检查和修复，最终仍以当前适用的 CDE 官方工具及正式要求为准。**

## 第一开发目标

首个纵向切片：

```text
只读 CLI Scanner
→ 15–20 条证据充分的规则
→ qpdf/pikepdf 结构分析
→ PDFium 页面渲染
→ 签名与加密阻断
→ JSON/HTML 报告
→ 与 CDE 官方验证结果建立映射
```

达到检测稳定后，才进入 Safe Batch Fixer。

## 本地校验

```bash
python scripts/validate_artifacts.py
```

预期输出应确认：

- PRD 存在且非空；
- 规则 JSON 可解析；
- 规则数为 26 且 ID 唯一；
- 规则 profile 与当前研究基线一致。

## 仓库约束

- 不提交真实申报资料、受试者信息、未脱敏项目文件、证书私钥或密码。
- `evidence/` 仅存公开监管来源的登记信息、哈希和允许保存的公开文件。
- 真实兼容性测试资料放在本地受控目录，不进入 Git。
- 当前 PRD 中仍保留早期工作名 `RegPDF Workbench`；仓库与项目总名确定为 `EZCTD`，后续在正式规格冻结时统一命名。

## 状态入口

详见 [`PROJECT_STATUS.md`](PROJECT_STATUS.md) 和 [`docs/decisions/0001-project-scope-and-name.md`](docs/decisions/0001-project-scope-and-name.md)。
