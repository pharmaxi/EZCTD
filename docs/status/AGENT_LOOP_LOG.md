# EZCTD Agent Loop Log

> 规则：本文件只追加，不用后续判断覆盖早期事实。每条记录区分“源码已写入”“CI 已证明”“官方已观察”。

## 2026-09-03 — Loop 01：目标收敛

- 目标从“批量修改 PDF 软件”收敛为证据驱动的只读 PDF 预检基线。
- 明确普通 PDF Fixer、交互式 PDF Sharper、普通电子申报和完整 eCTD Publisher 的边界。
- 结论：P0 不实现修复器，不以功能数量衡量完成度。
- 源码/文档：已写入。
- CI：不适用。
- 官方观察：无。

## 2026-09-03 — Loop 02：规则回源

- 将正式实现基线固定为 CDE eCTD V3.2.2 / 中国技术文件 V1.1，自 2026-03-01 生效。
- 核对 PDF 规则 6.1–6.26，严重程度为错误 16、警告 8、提示信息 2。
- 将官方标题、严重程度和解释与工程检测/修复设想拆分。
- 源码/文档：`cde_ectd_pdf_rules_v1.1_verified.json` 已写入。
- CI：规则数和严重程度校验已设计；最新收敛状态以 `P0_SENTINEL.txt` 为准。
- 官方观察：仅公开规则文本；未运行官方软件。

## 2026-09-03 — Loop 03：规则实验矩阵

- 为 26 条规则建立 detector contract。
- 建立 130 个 case recipe 和 28 个 smoke fixture 定义。
- 增加 object self-check、PDFium、qpdf、可重复性和差分资料包探针。
- 纠正两个错误假设：可恢复截断不能稳定代表 6.1；加密 PDF 不能要求原始字节哈希恒定。
- 源码：已写入 materializer、generator、probe 和 repair scripts。
- CI：由 `finalize-p0-b0-v2.yml` 和收敛 workflow 执行；结果待机器哨兵确认。
- 官方观察：0。

## 2026-09-03 — Loop 04：规则交叉污染

- 明确“目标规则阳性”不等于“只产生一个官方 finding”。
- 记录 URI、JavaScript、绝对路径和密码状态导致的相关规则共存。
- 修正 `/Fit` 和未线性化等由生成器无意引入的额外条件。
- 源码/文档：`smoke_expectations.json` 与 `SAMPLE_ISOLATION_AUDIT.md` 已设计生成。
- CI：由 sample isolation workflow 验证。
- 官方观察：相关规则是否在官方软件中合并、并列或短路仍未知。

## 2026-09-03 — Loop 05：只读观察器

- 实现基于 qpdf/pikepdf/PDFium 的实验性只读 PDF 观察器。
- 覆盖书签、超链接、动作、目的地、缩放、版本、附件、注释、安全、初始视图、线性化、动态内容、可搜索性和字体嵌入。
- finding 携带规则、严重程度、对象、页码和证据。
- 加入扫描前后 SHA-256 比较，禁止仅靠代码约定宣称只读。
- 源码：`src/ezctd/`、CLI 和 P0-B1 测试已写入。
- CI：由 `p0-b1-readonly-observer-v2.yml` 与收敛 workflow 验证。
- 官方观察：0；观察器明确标记 `EXPERIMENTAL_CONTRACT_NOT_CDE_EQUIVALENCE`。

## 2026-09-03 — Loop 06：节点上下文与例外

- 将规则适用性从文件名猜测改为显式 `node_id / document_role / language` 上下文。
- 固定参考文献、外文参考资料、申请表和 Fast Web View 例外的可执行合同。
- 建立 context-map JSON schema。
- 源码：已写入。
- CI：由 `p0-b1-applicability-contract.yml` 验证。
- 官方观察：目录对应表原始工作簿尚未完整导入，因此路径→节点自动映射仍未完成。

## 2026-09-03 — Loop 07：候选资料包检查

- 实现只读候选 eCTD 包检查器：唯一 `index.xml`、XML 引用图、相对路径、文件存在性、叶 MD5、`index-md5.txt`、PDF 叶预检和节点上下文。
- 增加负对照：叶 MD5 错误、严格模式缺上下文、输出路径位于输入包内、符号链接越界。
- 检查前后比较完整文件 inventory，防止资料包被修改。
- 源码：已写入。
- CI：由 `p0-b1-package-inspector-v2.yml` 验证。
- 官方观察：通过本检查器只能标为 `CANDIDATE_READY_FOR_OFFICIAL_VALIDATOR`，不能标为 CDE 合规。

## 2026-09-03 — Loop 08：监管资产证据

- 建立 CDE/ICH 来源抓取、哈希、归档目录和未解决清单。
- 建立 Windows 静态资产检查：Authenticode、版本资源、归档内容；不执行、不反编译。
- 修正证据总账：官方页面与二级镜像二进制不得合并成“官方二进制已哈希”。
- 建立人工下载资产导入器，原始二进制保存在 Git 外。
- 增加超限前置拒绝、来源域名、扩展名、magic、哈希和同一二进制多角色冲突检查。
- 源码：已写入。
- CI：来源抓取属于外部证据链；人工导入器合同由独立 workflow 验证。
- 官方观察：V1.1.0 安装包和手册是否已取得，以证据总账为准，不能根据页面存在推断。

## 2026-09-03 — Loop 09：官方校准实验设计

- 首批校准选择 baseline、6.1、6.8、6.19、6.21、6.22、6.26。
- 为排除缓存和应用状态漂移，将 7 个唯一资料包扩展为 9 次运行：前、中、后 3 次 baseline。
- 建立 Windows 准备脚本、证据目录、result schema、finalizer 和 batch summarizer。
- summarizer 必须验证同一软件 SHA、同一 baseline ID、报告、截图、时间、复核、6 个目标规则和 3 个干净 baseline。
- 增加缺截图与 baseline 污染负对照。
- 源码/文档：已写入。
- CI：证据合同可测试；官方运行仍未开始。
- 官方观察：`0 / NOT_RUN`。

## 2026-09-03 — Loop 10：收敛与状态隔离

- 将本地/合成门槛、外部来源抓取、官方软件运行拆成三种独立状态。
- `converge-p0-agent-loop-v2.yml` 只在全部本地合同通过后写成功标记并建立 draft PR。
- `P0_AUTOMATION_STATUS_V4` 与 `P0_SENTINEL.txt` 固定输出本地合同、官方状态和 draft PR 状态。
- 源码：已写入。
- CI：等待远端机器结果；不根据 workflow 已触发推断通过。
- 官方观察：`0 / NOT_RUN`。

## 当前硬阻塞

1. CDE eCTD 验证软件 V1.1.0 安装包与操作手册需要正式来源和哈希证据；
2. 需要一个由同一版本软件证明干净的中国 eCTD baseline sequence；
3. 需要执行校准批次 01 的 9 次真实运行；
4. 目录对应表原始工作簿尚需导入，路径到节点的自动映射不能凭猜测实现；
5. 最新本地门槛是否全部通过，必须读取远端收敛报告和状态哨兵。

## 下一循环

- 读取 `P0_SENTINEL.txt` 和 `P0_AGENT_LOOP_CONVERGENCE_V2.json`；
- 若本地合同失败，只修第一项失败及其最小复现；
- 若本地合同通过，核验 draft PR 内容和提交 SHA；
- 同时继续官方资产获取；取得二进制后通过人工资产导入器固化，绝不直接放入 Git；
- 官方资产与 clean baseline 齐备后，执行 9 次校准运行。
