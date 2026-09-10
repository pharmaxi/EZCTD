# EZCTD · 临床 CRO PDF 工作台

**把实际持有的临床 PDF 做好：能看、能解析、能定位、能批量修改，并保留没有误改的证据。**

重点是模块 **5、2.5、2.7**，可附带 CRO 实际提供的证明材料。无需完整申报资料、`index.xml`、`cn-regional.xml` 或有效 `0000` 序列。完整 eCTD 组装、生命周期和其他模块不再是本产品的开发前置条件。

> 当前版本：`0.3.0.dev0`，原型开发中。当前工程分支：`main`。
> 已有：本机浏览器阅读、检索、批量扫描、报告导入，以及经确认生成并复验快速 Web 查看副本。
> 未完成：Windows/NAS 产品环境验收、安装包、通用 PDF 编辑及官方规则等价校准。

## 从实际工作开始

```text
临床 PDF 文件夹
→ 可选导入官方 HTML 第 6 章
→ 当前 PDF 重新扫描与页面定位
→ 资料角色/适用性确认
→ 批量修改计划
→ 独立 PDF 副本及结构/视觉复验
→ 交付申办方或资料整合方
```

旧报告观察、当前文件检查、实际修改结果是三个不同对象。旧报告没有 PDF 哈希时，路径匹配只能视为候选。未提供的引用目标，不直接当作损坏；只有明确选择的读取目录才可以被访问。

## 安装与现有命令

在 main 分支的源码根目录，使用 Python 3.12 或 3.13：

```bash
python -m pip install -e ".[test]"
python -m pytest -q tests/cro_pdf

# 启动本机工作台，选择相互独立的输入与工作目录
python -m ezctd.workbench

# 独立于 PDF 引擎，静态导入报告；不执行报告脚本或打开报告链接
python -m ezctd import-cde-report /work/report.html --output /results/import.json

# 不需要 XML；JSON 与 HTML 必须放在输入目录之外
python -m ezctd scan-directory /work/clinical --output /results/scan.json --html /results/scan.html

# 正式节点、角色和语言由用户确认；不从文件名静默推定
python -m ezctd scan-pdf /work/clinical/report.pdf --node-id 5.3.1.2 --document-role clinical-report --language zh --output /results/one.json

# 物理页码从 1 开始，搜索结果返回 PDF 字符坐标
python -m ezctd inspect-page /work/clinical/report.pdf --page 2 --query 12.50 --output /results/page.json
python -m ezctd render-page /work/clinical/report.pdf --page 2 --dpi 120 --output /results/page.png
```

Windows 使用自己的盘符路径替换示例路径。命令显示的 `0` 只代表该项操作或有限检查成功，不代表申报合格；`1` 为存在明确本地问题，`2` 为入口/任务失败，`3` 为仍有未判定项，`130` 为取消。

默认每个 PDF 独立进程，超时 60 秒，可通过 `--timeout` 设置为不超过 600 秒。当前不提供 OS 级内存/网络沙箱；扫描器的应用读取边界不等于抵御未知原生库漏洞。首次使用只处理合成或可丢弃副本。

## 部分资料上下文

`scan-directory --context-map map.json` 使用**精确相对路径**，不是仅文件名：

```json
{
  "fasting/report.pdf": {"node_id": "5.3.1.2", "document_role": "clinical-report", "language": "zh"},
  "fed/report.pdf": {"node_id": "5.3.1.2", "document_role": "clinical-report", "language": "zh"}
}
```

`--reference-root` 可重复指定用户明确提供的只读依赖目录。它是读取授权，不证明完整申报范围。绝对路径、UNC 与 URI 不自动访问；链接路径未提供时单独报告。

## 结果边界

每个文件为 26 条规则分别保存 `PASS / FAIL / NOT_APPLICABLE / INDETERMINATE / NOT_RUN`。这里的 PASS 是本地有限条件完成，不是 CDE 官方通过。未证明穷尽的字体、可搜索性、动作链等检查保留未决状态，不再把无发现当作全部合格。

页面预览和搜索是实际 PDFium 引擎能力，并已接入本机浏览器阅读界面。坐标属于 PDF 页面空间，不是屏幕像素；物理页、页面标签和正文页码不能混用。当前没有修改任何用户真实临床 PDF。

## 当前文档入口

- [工作台使用说明](docs/development/WORKBENCH_0_3.md)：安装、阅读和安全副本流程。
- [当前状态](PROJECT_STATUS.md)：事实、验证范围和未完成项。
- [产品规格](docs/product/CRO_PDF_WORKBENCH_V0_2.md)：功能全景和 CRO 数据边界。
- [交付路线](docs/roadmap/CRO_DELIVERY.md)：目录扫描 → 页面工作台 → 安全副本批处理。
- [开发约束](AGENTS.md)：安全、测试和不得扩大的范围。
- [阶段复盘](docs/reviews/2026-09-07-stage-retrospective.md)：此前发现及纠偏依据。

历史 eCTD 研究、官方原始结果与技术包哈希保留，不改写为产品通过证据。真实报告、受试者标识、真实 PDF、证书私钥和密码不进入仓库；`.gitignore` 不是访问控制。
