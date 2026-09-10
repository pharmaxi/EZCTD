# 本机运行基线

日期：2026-09-11。基于本地合并提交 `8520e67`，本轮额外变更限于界面可读性、结果展示与浏览器回归断言。

## 环境与复现

Windows，Python 3.13.5，项目内 `.venv`；`pip check` 无依赖冲突。
使用 `.venv/Scripts/python.exe`，避免系统 Python 与测试环境混用。双击 `Start-EZCTD.bat` 可启动目录选择器；输入和工作目录必须分离。

核心测试的默认系统临时目录曾因权限拒绝失败。当前使用明确、全新且可写的 `--basetemp` 路径。不要复用已有 basetemp：pytest 可能清理该目录。

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/cro_pdf --basetemp="<全新测试目录>" --junitxml="<证据目录>/core.xml"
.\.venv\Scripts\python.exe scripts/validate_artifacts.py
.\.venv\Scripts\python.exe scripts/validate_p0b0_matrix.py
.\.venv\Scripts\python.exe scripts/inspect_p0b0_smoke.py
```

Smoke corpus 已通过 `tools/corpus/build_pdf_fixtures.py --output tests/corpus/generated-smoke --mode smoke` 生成，28 份 PDF 结构检查通过。规划与 26 规则/163 案例矩阵校验通过；矩阵通过不表示所有规则均已实现或官方校准。

## 实际验证

- 核心回归：100 passed、4 skipped，116.05 秒；跳过项均为 Windows 缺少创建符号链接权限。中文文件名、空格路径、原生工作进程、硬链接边界由实际核心测试覆盖。
- 通过宿主 CUA Browser 在本机 Edge 操作真实 HTTP 页面，无 Playwright 替代浏览器路径。页面标题、真实渲染、数值搜索一处高亮、三页全文检索、翻页、书签和报告定位均验证。
- 扫描 8 份合成 PDF；包含损坏、加密和签名信号样本。计划选择四份：两份可处理、一份签名信号阻断、一份已线性化无需处理。
- 实际生成两份副本（3 页及 2 页）。证据包含全页 150 DPI 像素、文本、几何、语义图和线性化复验；独立核对输出 SHA-256 与证据匹配。8 份输入前后 SHA-256 相同。
- 合成 HTML 经浏览器上传，显示一条完整相对路径候选和未证明历史文件身份提示；原报告页签独立于本地检查。上传最初被扩展权限拒绝，用户手动开启允许访问文件 URL 后恢复。报告观察目前保留在会话内，不宣称跨重启持久化。
- 桌面及 1000×800 窗口截图已人工查看。1000 宽视口的文档 scrollWidth 为 1000，页脚位于 800；150% PDF 缩放在阅读区内滚动。浏览器可见错误/警告日志为空。

## 本轮修整

- 本地明确问题优先，其次未执行、待复核发现、其余状态；全部 26 条仍保留，不改变扫描结论。
- 常见检查说明中文显示；未知说明保留原文。增加签名历史字节信号的中文说明。
- 原报告独立页签，导入成功自动切换；避免被长规则列表压在底部。
- 桌面高度随实际工具栏分配；页脚留在视口内。结果表状态列不再逐字换行。
- 既有浏览器脚本加入排序、报告页签和页脚断言；本轮同等交互通过 CUA 验证，未运行该 Playwright 脚本或远端 CI。

## 保留限制

本次只覆盖合成数据和本机 Edge。未完成真实临床资料验收、NAS、Windows 安装包、手机布局、密码学签名或官方验证器等价校准。四项符号链接测试仍未执行。

下一候选：指定页面旋转副本。需要明确页范围和角度的计划，继续阻断签名/加密等不适用输入，并验证非目标页及文本、导航等非目标属性；尚未实现。
