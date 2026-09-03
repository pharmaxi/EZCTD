# Regulatory evidence

本目录用于保存规则来源登记和允许纳入仓库的公开监管证据。

推荐结构：

```text
evidence/
├─ source-register.yaml
├─ cde/
│  └─ YYYY-MM-DD-document-name/
│     ├─ metadata.yaml
│     ├─ sha256.txt
│     └─ source-file.ext
└─ compatibility/
   └─ README.md
```

要求：

- 优先保存 CDE/NMPA 正式原始文件；
- 记录原始 URL、发布日期、生效日期、下载日期和哈希；
- 正式文件、征求意见稿和行业解读分开；
- 真实申报资料及包含个人信息、商业秘密的验证报告不得进入仓库；
- 若公开文件的再分发条件不明确，可只保存来源登记、哈希和本地获取说明。
