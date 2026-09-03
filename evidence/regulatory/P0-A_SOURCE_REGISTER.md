# Regulatory evidence register

| ID | 文件 | 发布者/来源 | 发布日期 | 生效日期 | 状态 | P0-A用途 | 可访问证据 |
|---|---|---|---|---|---|---|---|
| CDE-2026-04 | 关于发布eCTD V3.2.2相关技术文件的通告（2026年第4号） | 国家药监局药审中心 | 2026-01-15 | 2026-03-01 | effective | 确认 V1.1 文件监管状态 | https://www.cnpharm.com/c/2026-01-16/1088794.shtml |
| CDE-ECTD-V11-SPEC | eCTD技术规范V1.1及附件包 | 国家药品监督管理局 | 2026-01 | 2026-03-01 | effective | PDF技术细节、路径、文件格式等二级依据 | https://www.cnpharm.com/upload/resources/file/2026/01/16/183311.rar |
| CDE-ECTD-V11-GUIDE | eCTD实施指南V1.1 | 国家药品监督管理局 | 2026-01 | 2026-03-01 | effective | 规则交叉依据、适用范围、OCR、链接、安全设置 | https://www.cnpharm.com/upload/resources/file/2026/01/16/183312.pdf |
| CDE-ECTD-V11-VALIDATION | eCTD验证标准V1.1 | 国家药品监督管理局 | 2026-01 | 2026-03-01 | effective | **6.1–6.26 主规则源** | https://www.cnpharm.com/upload/resources/file/2026/01/16/183313.pdf |
| CDE-ECTD-V11-MAPPING | 现行申报资料要求与eCTD目录元素、CTD目录层级对应表 | 国家药监局药审中心 | 2026-01 | 2026-03-01 | effective | 后续节点上下文、例外识别 | https://www.cnpharm.com/upload/resources/file/2026/01/16/183309.xlsx |
| CDE-ECTD-VALIDATOR-110 | eCTD验证软件 V1.1.0 及操作手册 | 国家药监局药审中心 | 2026-01-15 | 2026-03-01 | effective | P0-B 黑盒兼容性验证 | CDE eCTD专栏“常用下载” |

## 证据使用原则

1. 正式规则优先于商业软件行为和行业文章。
2. 镜像仅解决可访问性，发布者与文件本体必须能够确认是 CDE/NMPA 正式文件。
3. 规则存在性、编号、标题、说明、严重程度以《eCTD验证标准V1.1》为准。
4. 工程 detector/fixer 不能反向修改监管字段。
5. 征求意见稿、ICH v4.0 中文翻译征求意见文件不得混入当前 `effective` V3.2.2 V1.1 profile。
6. 后续取得 CDE 原站附件 URL 时追加为 `canonical_url`，保留本次核验使用的 mirror URL 以保证复现。
