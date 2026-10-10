# PDFCraft 参考优化 · 设计

## 参考与取舍

PDFCraft [固定版本 `306bbcedf98b3a22f276e333d70688c776897154`](https://github.com/storytold/pdfcraft/tree/306bbcedf98b3a22f276e333d70688c776897154) 的 engine、render、optimize、actions、staging 和 corpus 等 40 余份源码、测试与文档的阅读支持下列设计选择；本轮未编译或运行 PDFCraft，不能把其 README 的质量数字写为独立验证。没有复制其品牌、界面资源或引入其运行时依赖。

| 参考代码 | 吸收的机制 | EZCTD 适配 |
| --- | --- | --- |
| [render/raster.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/render/src/raster.rs) | 请求代际、像素预算、实际缩放、可观察降级 | 全页预算缩放；来源身份绑定的缓存；前端代际隔离过期异步响应 |
| [engine/commands.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/engine/src/commands.rs)、[catalog.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/engine/src/catalog.rs) | 稳定操作身份与当前可用性 | 沿用 scan/plan/apply；新增 history/retry；可执行状态由服务端计划身份决定 |
| [engine/optimizer.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/engine/src/optimizer.rs)、[lib.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/engine/src/lib.rs) | 独立快照、后台阶段、失败取消、重新打开验证 | 不替换已有独立 worker 和线性化候选复验；扩展批次结果和安全重试 |
| [platform/staging.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/platform/src/staging.rs) | 先暂存、再发布 | 保留现有禁止覆盖及 PDF+proof 发布事务，禁止照搬覆盖原路径语义 |
| [xtask/corpus.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/xtask/src/corpus.rs)、[gates.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/xtask/src/gates.rs) | 固定版本和输入身份 | 合成测试保留输入哈希；源码比较固定 Git blob；CI 结果指向实际最终提交 |

### 不直接采用的默认行为

| 固定版本中的行为 | 对本项目的判断 |
| --- | --- |
| [optimize/lib.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/optimize/src/lib.rs) 默认启用未引用目的地删除，[links.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/optimize/src/links.rs) 只收集本文件内引用 | 推断：其他临床 PDF 可能有入链，不能据此删除命名目的地；当前继续完整保留 |
| Reduce 设置把高于 225 ppi 的图像降至 150 ppi，并用 JPEG quality 60 | 推断：可能改变图表、扫描印章或细线；本轮未建立这种内容变化的验收，不采用有损图像压缩 |
| [engine/actions.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/engine/src/actions.rs) 部分步骤失败仅记日志后返回文件结果 | 不作为成功模型；每份 EZCTD 输入保留明确完成、失败、取消或未开始状态 |
| [engine/ocr.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/engine/src/ocr.rs) 的语言字段与实际 Latin-only 识别范围不同，取消可保留部分完成进度 | 不推定中文 OCR 或全页完成；EZCTD 明确无文本层的覆盖缺口，本轮没有增加 OCR |
| [engine/export.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/engine/src/export.rs) 没有贯通全部渲染 warning；[preflight/lib.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/preflight/src/lib.rs) 是有限对象规则 | 不把 PNG 成功、预检无发现或上游自检写成完整 PDF/A/CDE 合格结论 |

以上是对指定源码版本的检查及项目适配判断，不是 PDFCraft 的独立运行评测。已有 EZCTD 副本事务及结构/文本/像素复验在本次之前已存在，本轮不将它们记作新增能力。

## 第二阶段：页面组织工作台

本阶段继续参考相同固定版本，重点转向 [ui-egui/panels.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/ui-egui/src/panels.rs)、[editing.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/ui-egui/src/editing.rs)、[engine/lib.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/engine/src/lib.rs) 和 [organize/lib.rs](https://github.com/storytold/pdfcraft/blob/306bbcedf98b3a22f276e333d70688c776897154/crates/organize/src/lib.rs)。这些源码将页面选择转换为编辑命令，再刷新文档视图、保留选择、加入撤销历史并保存。EZCTD 吸收该操作模型，保存继续使用独立副本。

### 草稿与身份

父进程只持有来源文档 ID/SHA、完整来源页排列、按来源页索引的旋转增量、修订号和有界历史，不持有原生 PDF 对象。来源页是稳定身份，输出物理页是当前位置；两者在界面及证明中分别显示。旋转增量只允许 0/90/180/270，页排列必须恰好覆盖全部来源页。编辑 API 对 revision 做并发检查，有效操作推进修订号；撤销/重做也生成新的修订身份。

草稿预览由一次性 worker 从冻结原件和当前操作参数生成真实修改后的 PDF 字节，再用 PDFium 渲染。页面/缩略图响应带修订身份，晚到响应不能替换当前草稿。预览不冒充完整保存复验。切回原件时，阅读检索与检查仍明确基于原件。

### 操作与保存

`inspect-organize` 检查是否支持修改并返回来源页信息；`organize-preview` 返回当前修订的真实页面显示；`organize-stage` 执行最终修改、重新打开和完整复验后才写 parent 指定的暂存文件。所有入口保留原件身份与改写守卫，父进程通过共同的禁止覆盖事务发布 PDF 和证明。

保存使用现有任务/history/cancel 基础设施，以 `organize` 区分线性化任务；保存冻结草稿修订，执行中不可编辑。相同修订的重复保存请求返回同一任务；取消/失败后的再次保存需要明确重试，使用新输出目录。已保存副本可由登记的任务身份只读重新打开，输出路径和 SHA 来自服务端记录；浏览器不传任意路径。

PDF 与证明的回滚所有权来自写入句柄的 device/inode 回执，成功返回与临时文件清理异常使用同一身份；事后路径检查只用于比较，不能据此取得删除第三方替换文件的权限。观察到来源或输出变化后，失效状态不会因字节随后恢复而自动解除；在途读取在最终持锁边界再次检查登记身份。

### 操作专属不变量

完整页序变更保持每个来源页恰好一次、页对象目标指向相同内容；持久旋转只改变所选页的有效方向。页面标签若原来存在则随来源页保留，原来没有标签不人为生成标签。允许调整的页树、方向与标签关系必须显式核验，其余可达语义继续检查。逐页渲染按来源映射和预期旋转比较；导航、文本、页几何和原件哈希单列证据。非标准或未支持的目标形式需明确阻断，不能悄悄改到另一页。

重排直接移动既有间接页对象的页树叶引用，保留嵌套树；不使用会复制页字典的页序列切片赋值。原生输出反向归一化只逆置已声明变化，不把源内容复制回输出后比较。既有旋转的预期显示通过独立来源 PDFium 页设置绝对目标方向取得，避免把查看器额外旋转误当作持久 `/Rotate`。合法非 UTF-8 PDF Name 以原始字节保真编码参与名称解析和语义比较。

### 工作台界面

现有三栏阅读界面增加“组织页面”模式，提供页面网格、多选/范围选择、拖动与按钮移动、旋转、撤销/重做、还原和保存。真实页预览保持足够面积；组织模式收起原件检查工具，防止把旧扫描证据解释为修改后检查。已保存副本是独立只读模式，可回到仍保留历史的草稿。

## 第一阶段调用边界

浏览器只接触会话文档 ID；本机 HTTP 服务验证 Host/Origin/令牌和 JSON；Workspace 负责来源授权、冻结身份、缓存、任务状态；原生 worker 负责 PDF 读取。父进程不导入原生引擎，所有输出仍经原 no-clobber I/O。新 thumbnail 只能读已选根内文档，禁止输入任意路径。

### 阅读

- 搜索接受 1 起始的 start_page 和有界 page_limit；返回本批遍历/读取覆盖、后继页、无文本页、未搜索页及命中是否精确。前端累计不重叠区间，保留所有未决项；改文档/改查询递增代际，旧响应不得覆盖新页面。
- 页预览默认 16M 像素，缩略图 180k 像素。按完整页面尺寸共同缩放两个方向，返回实际 DPI 和分辨率状态。副本复验的固定 150 DPI 逻辑不受本次预览缩放影响。
- 缓存只存已经来源核验的成功数据；键含 SHA、操作及参数，至多 32 项和 32 MiB 序列化数据，返回深拷贝。每次命中之前和取得缓存之后重新授权与校验哈希，关会话/发现改源时清除。这个预算不是整个进程的内存限制；每次校验仍有文件读取成本，不宣称未经测量的加速倍数。
- 缩略图按需分组加载且限制并发；书签按层级筛选，匹配项的祖先保持可见。物理页、PDF 页标签、正文页码始终区分。

### 批任务

单会话仍只允许一个批任务。每个任务记录 requested_ids、retry_of 和每文件结果。终止后没开始的文件记 NOT_STARTED，done 仍表示尝试数；counts 分列成功、错误、取消、未开始、阻断、无需处理。

完成且已保存任务证据后，混合计划中身份在完成时未改变的 ELIGIBLE 行可建立可用子集。can_apply 由服务端当前计划使用/上下文状态计算。应用前重新确认哈希和签名等限制，原计划不可复用。

retry 只选择 ERROR/CANCELLED/NOT_STARTED 或缺失的任务项；scan→scan、plan→plan、apply→plan。新的副本写入仍须计划预览和明确确认，不自动重放原修改。任务历史为当前进程内只读摘要，不恢复历史 JSON 中的写入权限。

### 界面

保留文件/阅读/检查三栏：增加文件状态筛选与选择扫描、可折叠上下文、问题筛选、可理解的对象证据和页定位、导航缩略图及书签过滤。主工具条保留真实操作，专注模式给正文更大面积。任务历史使用独立对话框，明确本次会话、排除项和重试动作。

## 验证与限制

实际 PDFium 的页标签、旋转/裁剪坐标、命中片段、超大页面和分段查询必须有原生测试。缓存/调度的控制测试不得冒充原生文件测试。混合批次用可丢弃合成文档，检查源 SHA 和成功输出证明。浏览器插件未列出，采用仓库已有 Playwright 路径与 Chromium；界面错误、窄屏溢出、外部请求和取消后状态均检查。Windows CI 与真实 Windows 10/11、NAS 和人工试用分别记录。
