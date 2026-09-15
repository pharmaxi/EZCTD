# EZCTD development instructions

## Product scope

Build a local clinical CRO PDF workbench for Module 5, 2.5 and 2.7 with optional CRO-provided certificates. Partial clinical folders are first-class input. Do not require XML backbones, full Module 1–5, a clean submission sequence or whole-submission validation before delivering PDF functions. Keep historical research intact; current scope is `docs/product/CRO_PDF_WORKBENCH_V0_2.md` and current delivery order is `docs/roadmap/CRO_DELIVERY.md`.

## Non-negotiable boundaries

- Never overwrite input or existing output files. All command and future UI paths use shared no-clobber I/O.
- Reports, previews, cache and future repaired PDFs are outside selected input/reference trees.
- Never open links beyond explicitly selected roots. A missing partial-delivery target is NOT proof of a broken submission.
- Never execute PDF/HTML JavaScript, URI, Launch or embedded attachments. Report import is inert data parsing.
- Parent orchestration and report import must not load native PDF engines; run them in bounded disposable workers.
- Native worker isolation is not an OS security sandbox. Do not claim memory/network containment without evidence.
- Keep official report observations, current PDF identities, local checks, applicability and future changes separate.
- Every rule needs an explicit execution status. Failure or missing context is never silently PASS.
- Signature signals block future rewrite operations; cryptographic validation is a separate capability.
- Do not substitute PDF Base-14 for CDE's exact font list. Do not silently normalize aliases into regulatory equivalence.
- Do not upload real clinical reports, paths, subject identifiers, PDFs, credentials or font files. Use synthetic fixtures. `.gitignore` is not permission to read private folders.

## 两人使用 AI 开发的协作约定

1. 两位开发者分别使用自己的 GitHub 账号和 AI 会话；发起任务的人对本次修改负责。先说清要解决的问题、负责人和完成标准，小改动可直接写在 PR 中。
2. 开始前读取本文件、相关目录说明和任务资料，检查当前工作区、远程 `main` 的最新提交及开放 PR。一件事一个分支，从最新 `main` 新建；继续既有任务时使用原分支。不要直接在 `main` 开发或推送。
3. 修改前列出主要涉及的文件，发现与对方正在做的任务重叠时先协调顺序。保留他人的未提交修改；需要隔离时另建工作目录或 worktree。遇到冲突检查双方意图，不得整片覆盖或简单选择“全部保留我的”。不得强推、改写研究历史或清理历史归档分支。
4. 一次 PR 只解决一件事。按有意义的阶段提交并推送本任务分支；未完成可建 Draft PR，目标为 `main`。后续修改继续推送同一分支，PR 会更新。
5. AI 完成相关测试并如实记录命令、提交版本、结果和未运行项；测试失败、跳过或没有环境不能写成通过。不得为绿灯删除测试、放宽断言、修改固定样例或把模拟测试说成真实集成测试。
6. PR 说明为什么改、改了什么、验证结果、未验证项、风险和剩余问题，以及对方可以照做的试用步骤；界面修改附截图。由另一人使用自己的账号审核，实际试用关键流程，并让其 AI 检查实际差异、调用关系与测试，不只复述 PR 描述。PDF 测试使用合成或可丢弃副本，核对结果并确认原文件未被修改；两个 AI 都表示通过不代替人工试用。
7. CI 通过后仍需对方审核和明确的合并指令。AI 不得自行批准自己的 PR、自动合并或绕过失败检查。收到明确指令后再合并，日常任务优先 Squash and merge；新任务重新同步 `main`。已合并的普通任务分支可在确认无后续工作后清理。
8. 本文件是协作约定，不是 GitHub 权限控制。不能因为 CI 绿灯或规则显示 Active 就宣称 `main` 已受保护；强制审批和禁止直推是否生效，须另外核实仓库套餐与分支规则。

## Implementation and testing

Inspect the actual remote `main` HEAD and working tree before creating the task branch. Do not claim a PR or a successful check exists without checking its actual result.

```bash
python -m pip install -e ".[test]"
python -m pytest -q tests/cro_pdf
python scripts/validate_artifacts.py
python scripts/validate_p0b0_matrix.py
python tools/corpus/build_pdf_fixtures.py --output tests/corpus/generated-smoke --mode smoke
python scripts/inspect_p0b0_smoke.py
```

Run Windows regression for pathname, UTF-8, hardlink/reparse handling and native workers. A hosted Windows Server result is not Windows 10/11 or NAS certification. Retain skips and failures. Use explicit UTF-8 for JSON/HTML.

The standard CI entry is `artifact-integrity.yml`; do not create a new v2/v3 workflow per fix. Malformed superseded workflows are retained byte-for-byte under `.github/archived-workflows/`, not active CI.

### PR 自动检查

每个目标为 `main` 的 PR（包括 Draft 和后续提交）以及合入 `main` 的提交都运行现有 `Artifact integrity` 工作流。同一 PR 的新提交会取消旧运行，其他 PR 不受影响。

| 检查 | 内容 |
| --- | --- |
| `validate` | 规划文件、26 条规则矩阵、合成 PDF 生成与结构检查 |
| `cro-core`（Linux / Windows） | `tests/cro_pdf` 的安全边界、PDF 核心、阅读与副本测试 |
| `cro-browser` | 真实 Chromium、本机 HTTP 工作台、阅读检索、扫描和副本复验 |
| `PR checks` | 汇总上述检查；失败、取消或跳过均不能汇总为通过 |

在 PR 的 **Checks** 页查看当前提交的结果；失败时打开对应任务的日志。核心测试的 JUnit、依赖版本和浏览器证据保存在该次 Actions 的 artifacts 中。只使用合成数据，不需要临床文件、密钥或付费 AI API。CI 不会自动审核、合并或部署；也不代表 Windows 10/11、NAS 环境或官方合规验收已经完成。

## Small delivery loop

One concrete task → smallest implementation → positive and negative tests → actual result → commit with scope and limitations. Repeating a failed experiment without new information is not progress. Do not change expected results just to get green checks. Preserve source hashes and fixed test inputs; do not represent a stubbed unit test as a native integration test.

Next priority: verify the existing 0.3 reader and linearization flow on local Windows, then improve readability and issue ordering. Full Publisher, v4.0 runtime, generic reflow, OCR-by-default and automatic font substitution remain out of scope.
