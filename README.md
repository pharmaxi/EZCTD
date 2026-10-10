# EZCTD · 临床 CRO PDF 工作台

**把实际持有的临床 PDF 做好：能看、能解析、能定位、能批量修改，并保留没有误改的证据。**

重点是模块 **5、2.5、2.7**，可附带 CRO 实际提供的证明材料。无需完整申报资料、`index.xml`、`cn-regional.xml` 或有效 `0000` 序列。完整 eCTD 组装、生命周期和其他模块不再是本产品的开发前置条件。

> 本分支版本：`0.4.0.dev0`，原型开发中。整合分支：`main`；开发在独立任务分支完成，通过 PR 合入。
> 已有：本机阅读、分段全文检索、缩略图和书签导航、选择扫描、任务历史与未完成项重试，以及经确认生成并复验快速 Web 查看副本。本轮新增页面多选、重排、持久旋转、撤销/重做、真实草稿预览和保存副本后重新打开。
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

## 0.4 页面组织工作台

打开 PDF 后选择 **组织页面**，可按当前页位多选，移动所选页组，顺/逆时针旋转，查看实际编辑后的页面；支持撤销、重做和还原。**保存副本**先执行页面与导航复验，完成后可从任务结果或 **已保存副本** 重新打开实际输出。切换文件会保留当前服务会话内的草稿。

| 操作 | 保存结果如何核对 |
| --- | --- |
| 重排页面 | 每个来源页恰好出现一次；输出顺序与操作一致；书签、内部链接和命名目的地继续指向相同内容 |
| 持久旋转 | 方向实际写入 PDF，按来源页及声明角度逐页比较显示；保留非目标内容和对象 |
| 页标签 | 原来存在的标签随来源页保持；物理页位置、来源页号和标签分别显示 |
| 保存与重开 | 冻结来源 SHA 与草稿修订；生成独立 PDF 和证明；重开时核对登记的输出 SHA |

首条操作流程：**选第 2–3 页 → 移到新的页位 → 旋转 90° → 撤销/重做 → 保存副本 → 重新打开检查**。真实合成样例与试用步骤见 [0.4 使用说明](docs/development/WORKBENCH_0_4.md)。

当前页面组织保留完整页集，只改变顺序和方向。提取、拆分、合并、插入、删除、书签编辑和批量初始视图仍待后续实现；签名、加密及暂不支持的复杂文档继续明确阻断重写。

## 阅读与批次工作流

| 工作环节 | 本分支的改进 |
| --- | --- |
| 找到资料 | 文件名/目录和扫描状态一起筛选；只扫描勾选文件；明确提示筛选结果外仍选中的文件 |
| 连续阅读 | 按需缩略图、保留祖先层级的书签筛选、物理页与页标签、专注阅读及窄屏布局 |
| 搜索长报告 | 每批 200 页，可继续后续页；片段围绕实际命中；无文本、未读完和计数上限分别说明 |
| 检查证据 | 完整保留 26 条规则，按状态/内容筛选；呈现对象证据和物理页定位，原报告保持独立 |
| 处理混合批次 | 失败文件与合格文件分别记录；已核实的合格子集仍可确认生成副本 |
| 接续工作 | 当前服务会话的任务历史、断线后重新连接、仅重试未完成项；副本失败后先重新生成计划 |
| 读取可靠性 | 有界来源身份缓存、超大页完整降分辨率预览、取消复核、已变化文件的缓存/计划/界面证据失效 |

设计深入参考了固定版本的 [PDFCraft](https://github.com/storytold/pdfcraft/tree/306bbcedf98b3a22f276e333d70688c776897154)，继续使用现有 Python、PDFium 与 pikepdf。具体取舍、页面编辑命令和复验合同见 [设计记录](docs/specs/pdfcraft-workbench/design.md)。副本操作包括受控线性化及页面重排/旋转；不默认进行有损压缩、删除命名目的地或 OCR。

## 安装与现有命令

安装已整合版本时，在 `main` 的源码根目录使用 Python 3.12 或 3.13；开发和试用 PR 时，在对应任务分支执行同样的命令：

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

## 两人使用 AI 协作开发

`main` 是两人共用的整合版本；分支是各自的工作副本；PR 是请对方检查这次修改；Merge 才是把修改合入 `main`。**推送到任务分支，不会自动改动 `main`。**

两位开发者各用自己的 GitHub 账号和 AI 会话，按以下顺序操作：

1. **先分任务。** 说明要解决什么、谁负责、怎样算完成。每个任务只处理一件事，开始前查看已有 PR，避免同时修改同一块。
2. **让 AI 先读 [AGENTS.md](AGENTS.md)。** 检查工作区和最新远程 `main`，再创建任务分支；同时开发的 AI 使用各自的工作目录或 worktree。不要直接在 `main` 修改或推送。
3. **边做边保存。** 在任务分支 Commit（保存修改记录）、Push（上传）；未完成可开 Draft PR（草稿），目标选 `main`。继续修改时推送到同一分支即可。
4. **准备给对方看。** PR 写清改了什么、为什么改、实际运行的检查及结果、没验证的地方和风险，并给出能照做的试用步骤。界面变化附截图。
5. **对方试用，再由 AI 复核。** 对方用自己的账号看 PR，用合成或可丢弃 PDF 验证结果，并确认原文件未改变；再让自己的 AI 看实际代码差异和测试。两个 AI 都说“通过”不能代替人的试用。
6. **确认后合并。** 最新提交的检查通过、对方确认后，再明确指示 AI“合并这个 PR”。日常任务优先 `Squash and merge`，将一次任务整理成一条提交；需要保留历史的任务单独说明。
7. **下一次从最新版本开始。** 合并后两人更新 `main`，再开新任务分支。冲突先检查双方修改，不强推覆盖、不丢弃对方工作，也不通过删除失败测试让检查变绿。

### 到哪里看自动检查

[Artifact integrity 工作流](.github/workflows/artifact-integrity.yml) 会在目标为 `main` 的 PR 创建、更新、重新打开、转为待审核时运行，也会在提交进入 `main` 时运行。Draft PR 同样检查；同一 PR 有新提交时，旧运行会取消。

| Checks 中的名称 | 检查什么 |
| --- | --- |
| `validate` | 规划文件、26 条规则矩阵、合成 PDF 生成及结构 |
| `cro-core (ubuntu-latest)` | Linux 上的 PDF 核心、安全边界、阅读及副本测试 |
| `cro-core (windows-latest)` | GitHub Windows 环境下的同套核心测试 |
| `cro-browser` | 真实 Chromium 中的阅读、搜索、扫描、页面编辑、副本保存与重开 |
| `PR checks` | 汇总以上任务；任一任务失败、取消或跳过，都不能汇总通过 |

打开 **PR → Checks**，确认查看的是最新提交。先看 `PR checks`，有红色失败再打开具体任务的日志；黄色表示尚未完成，取消或未运行也不是通过。测试中的单项跳过需查看报告，不能当成已验证。

需要查看结果文件时，进入 [Actions](https://github.com/pharmaxi/EZCTD/actions/workflows/artifact-integrity.yml)，打开对应运行，在 **Artifacts** 下载测试报告、依赖版本或浏览器截图。检查使用合成数据，不需要上传真实临床文件，也不需要付费 AI API。

**自动检查不会自动审核、合并或部署。** CI 通过不代表 Windows 10/11、NAS 或官方合规验收完成。禁止直推 `main`、强制另一人批准等限制，仍需 GitHub 上实际生效的分支保护规则；本协作约定和绿色检查本身不提供这项保护。

## 当前文档入口

- [0.4 工作台使用与试用说明](docs/development/WORKBENCH_0_4.md)：页面组织、真实预览、保存重开，以及阅读、检索和批次恢复流程。
- [本轮需求、设计和验收](docs/specs/pdfcraft-workbench/tasks.md)：固定参考版本、验证证据与未完成项。
- [0.3 交付记录](docs/development/WORKBENCH_0_3.md)：原有受控副本流程及当时的环境记录。
- [当前状态](PROJECT_STATUS.md)：事实、验证范围和未完成项。
- [产品规格](docs/product/CRO_PDF_WORKBENCH_V0_2.md)：功能全景和 CRO 数据边界。
- [交付路线](docs/roadmap/CRO_DELIVERY.md)：目录扫描 → 页面工作台 → 安全副本批处理。
- [开发约束](AGENTS.md)：安全、测试和不得扩大的范围。
- [阶段复盘](docs/reviews/2026-09-07-stage-retrospective.md)：此前发现及纠偏依据。

历史 eCTD 研究、官方原始结果与技术包哈希保留，不改写为产品通过证据。真实报告、受试者标识、真实 PDF、证书私钥和密码不进入仓库；`.gitignore` 不是访问控制。
