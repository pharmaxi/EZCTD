# China eCTD v4.0 consultation package

> Status: **DRAFT / RESEARCH ONLY**. Byte-valid official attachments retrieved from the CDE consultation notice dated 2026-05-27. This profile is not active in the effective China eCTD V3.2.2/V1.1 runtime.

## Official attachments

| Role | Displayed file | Kind | Pages | Bytes | SHA-256 |
|---|---|---:|---:|---:|---|
| `controlled_vocabulary` | eCTD v4.0指导原则附件1-受控词汇文件（公开征求意见稿）.pdf | pdf | 10 | 221237 | `bc8d57e1a988608d2afd1e4739f0a7446c97211bd8bf42b34189cae19a9e6461` |
| `guidance` | eCTD v4.0指导原则（公开征求意见稿）.pdf | pdf | 82 | 1613653 | `f24401043663bab609773defb3daaacad07febe62581108180a592dd23535d63` |
| `feedback_form` | 征求意见反馈表.docx | docx |  | 17058 | `e98e1478130cd2f7d90e16ba7ae043f5384aff5e3668cd51892afe2bd568e7dd` |
| `rationale` | 《eCTD v4.0指导原则》起草说明.pdf | pdf | 5 | 318423 | `f589fd7f2d68512658ea9a69b31394b1ab1538c5f01edd14461013630a5e5a82` |
| `validation_standard` | eCTD v4.0指导原则附件2-eCTD v4.0 验证标准（公开征求意见稿）.pdf | pdf | 10 | 309311 | `36f871b89a3292f97d2a865506aeed0e1418dde1767eea61d03c9a9cc86a0774` |

## Isolation contract

- Profile ID: `cn-cde-ectd-v4.0-draft-2026-05-27`.
- `runtime_enabled=false`.
- No draft rule, severity, controlled vocabulary or data-model field may alter the effective V3.2.2/V1.1 profiles.
- Neutral infrastructure may be shared: evidence ledger, archive safety, XML parsing, typed identifiers, dependency graph and worker isolation.
- Final China v4.0 documents require a fresh byte freeze and a formal draft-to-final delta before activation.

## Acquisition assurance

Each PDF was accepted only after `%PDF-` was found in the first 1024 bytes. The feedback DOCX was accepted only as an OOXML ZIP containing both `[Content_Types].xml` and `word/document.xml`. HTTP protection pages are retained only as rejected-payload metadata and never registered as official attachments.
