# EZCTD · 临床 CRO PDF 工作台

**把实际持有的临床 PDF 做好：能看、能解析、能定位、能批量修改，并保留没有误改的证据。**

重点是模块 **5、2.5、2.7**，可附带 CRO 实际提供的证明文件。无需完整申报资料、XML 骨架或完整 eCTD 序列；完整组装不是 PDF 工具的开发前置条件。

## 当前工程入口

当前可运行原型在 [`agent/cro-pdf-safety-intake`](https://github.com/laojia-a/EZCTD/tree/agent/cro-pdf-safety-intake)，版本 `0.2.1.dev0`。

**本次 main 仅更新文档入口，没有合并研究分支的应用代码。直接在 main 运行新命令不会得到当前实现。**

- [当前产品规格](https://github.com/laojia-a/EZCTD/blob/agent/cro-pdf-safety-intake/docs/product/CRO_PDF_WORKBENCH_V0_2.md)
- [当前实现与限制](https://github.com/laojia-a/EZCTD/blob/agent/cro-pdf-safety-intake/PROJECT_STATUS.md)
- [交付顺序](https://github.com/laojia-a/EZCTD/blob/agent/cro-pdf-safety-intake/docs/roadmap/CRO_DELIVERY.md)
- [开发约束](https://github.com/laojia-a/EZCTD/blob/agent/cro-pdf-safety-intake/AGENTS.md)
- [已核验的 Linux/Windows 测试运行](https://github.com/laojia-a/EZCTD/actions/runs/34090491339)

```bash
git fetch origin
git switch --track origin/agent/cro-pdf-safety-intake
python -m pip install -e ".[test]"
python -m pytest -q tests/cro_pdf
```

分支已存在时使用 `git switch agent/cro-pdf-safety-intake`。切换前检查并保存本地未提交修改，不使用强制覆盖。

## 已形成的能力

安全报告导入、目录级独立进程只读扫描、逐规则执行状态、PDF 页面文本与搜索坐标、实际 PNG 页面预览、输入哈希核对和中文 HTML/JSON。固定代码 `95f197c097119fbc2c3620cb24cec442aed26b7f` 在 Linux 和 Windows CI 各通过 54 项针对性测试，无跳过项；完整文档提交为 `f815ab1fbffb66c7e114ffcb6468b230de81cc83`。

## 尚未完成

完整桌面阅读界面、批量 PDF 修改器、官方规则等价校准、Windows 10/11 与 NAS 产品环境验收。当前仍是原型，先使用合成或可丢弃副本，不将 CI 通过写成申报合格。

## 产品原则

不覆盖原件；不自动访问未授权路径；不执行 PDF/HTML 脚本；不把缺少其他模块当成 CRO PDF 整理失败；不把旧报告路径匹配当成当前文件身份；无法判定不显示为通过。

真实临床 PDF、原始验证报告、受试者标识、密码和私钥不提交 Git。历史 PRD 与监管研究保留供追溯，其中旧的最小序列门槛不再控制当前交付。
