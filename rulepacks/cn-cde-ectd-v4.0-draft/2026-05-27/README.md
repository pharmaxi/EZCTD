# China eCTD v4.0 consultation package

> Status: **DRAFT / RESEARCH ONLY**. These files were published for public consultation on 2026-05-27 and are not activated in the effective China eCTD V3.2.2/V1.1 runtime profile.

## Official attachments

| Role | File | Pages | SHA-256 |
|---|---|---:|---|
| `controlled_vocabulary` | eCTD v4.0指导原则附件1-受控词汇文件（公开征求意见稿）.pdf |  | `3b5624de9f970c3c00d2d98f5ccfc1bb08062023932a145b8295cd6056647e27` |
| `guidance` | eCTD v4.0指导原则（公开征求意见稿）.pdf |  | `96d693a7a60a5dbd0fc1939e6d7ac96d47c40d5b197e107a4af0bc989b25662a` |
| `feedback_form` | 征求意见反馈表.docx |  | `95f0017d0f3d24c62511ffa9416dcb9ed0c3195f0d061b3b93a6ddcf2b5b0e6c` |
| `rationale` | 《eCTD v4.0指导原则》起草说明.pdf |  | `29c92a9f268cf85784d7f6544bc234d2738c044c6eaff6be65ecb3f04a963289` |
| `validation_standard` | eCTD v4.0指导原则附件2-eCTD v4.0 验证标准（公开征求意见稿）.pdf |  | `e3ff8b5367d17a3efd7fb87608c90e942a395d195fb1a85614449163a67749c9` |

## Isolation contract

- Profile ID: `cn-cde-ectd-v4.0-draft-2026-05-27`.
- `runtime_enabled=false`.
- No v4 rule, severity, controlled vocabulary or data model field may alter `cn-cde-ectd-v3.2.2-v1.1-pdf` behavior.
- Neutral infrastructure may be shared: source ledger, archive safety, XML parser, evidence reports, typed identifiers and worker isolation.
- Final China v4.0 documents will require a fresh source freeze and formal draft-to-final delta.

## Architectural consequences

- Preserve a profile boundary around XML/data models rather than treating v4 as a directory-template update.
- Prepare for UUID-based identifiers, document references/reuse, context-of-use metadata and larger controlled vocabularies, but keep these types dormant in the current runtime.
- Validator message identity and severity must remain versioned by profile and source hash.
