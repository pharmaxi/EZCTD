# P0 regulatory evidence completeness ledger

> A discovered page, a downloaded binary, parsed content, and an official black-box observation are different evidence states. This ledger does not collapse them into a single percentage.

## Status counts

- `NOT_DISCOVERED`: 10
- `PAGE_OR_LINK_CONFIRMED_BINARY_UNRESOLVED`: 3

## Asset ledger

| ID | Required asset | Status | Binary candidates | Official candidates | Used for |
|---|---|---|---:|---:|---|
| `NMPA-2026-08` | 国家药监局关于化学药品和生物制品全面实施药品电子通用技术文档申报的公告（2026年第8号） | `NOT_DISCOVERED` | 0 | 0 | effective_scope, transition_date |
| `CDE-2026-04` | CDE eCTD V3.2.2相关技术文件通告（2026年第4号） | `NOT_DISCOVERED` | 0 | 0 | effective_technical_baseline |
| `CDE-MAPPING-TABLE-V1.1` | 现行申报资料要求与eCTD目录元素、CTD目录层级对应表 | `NOT_DISCOVERED` | 0 | 0 | context_resolver, node_mapping |
| `CDE-TECH-SPEC-V1.1` | eCTD技术规范V1.1 | `NOT_DISCOVERED` | 0 | 0 | china_regional_structure, pdf_semantics_cross_reference |
| `CDE-TECH-ANNEX-V1.1` | eCTD技术规范V1.1附件/实用文件包 | `PAGE_OR_LINK_CONFIRMED_BINARY_UNRESOLVED` | 1 | 0 | xml_validation, utility_files, publisher_prototype |
| `CDE-IMPLEMENTATION-GUIDE-V1.1` | eCTD实施指南V1.1 | `NOT_DISCOVERED` | 0 | 0 | submission_practice, pdf_generation_guidance |
| `CDE-VALIDATION-STANDARD-V1.1` | eCTD验证标准V1.1 | `NOT_DISCOVERED` | 0 | 0 | official_rule_catalog, severity, exceptions |
| `CDE-VALIDATOR-V1.1.0` | CDE eCTD验证软件V1.1.0安装包 | `PAGE_OR_LINK_CONFIRMED_BINARY_UNRESOLVED` | 0 | 2 | official_black_box |
| `CDE-VALIDATOR-MANUAL-V1.1.0` | CDE eCTD验证软件V1.1.0操作手册 | `NOT_DISCOVERED` | 0 | 0 | official_black_box_protocol, report_export |
| `ICH-ECTD-3.2.2-SPEC` | ICH eCTD v3.2.2 specification | `NOT_DISCOVERED` | 0 | 0 | international_backbone |
| `ICH-ECTD-3.2.2-UTIL` | ICH eCTD v3.2.2 DTD/XSL utility package | `PAGE_OR_LINK_CONFIRMED_BINARY_UNRESOLVED` | 1 | 0 | international_xml_validation |
| `CN-CLEAN-BASELINE-SEQUENCE` | 经CDE V1.1.0验证无阻断问题的最小中国eCTD序列 | `NOT_DISCOVERED` | 0 | 0 | differential_black_box_cases |
| `CDE-OFFICIAL-TRAINING` | CDE官方eCTD V1.1培训材料、演示或操作视频 | `NOT_DISCOVERED` | 0 | 0 | operational_interpretation |

## Exit interpretation

P0-B0-A can pass with structured official rule excerpts and synthetic tests. P0-B0-B cannot pass until the V1.1.0 software/manual are hashed, a baseline sequence is proven clean by that software, and case reports are preserved. A secondary mirror can support continuity but never replaces official provenance where an official binary is required.
