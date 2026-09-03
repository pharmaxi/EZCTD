# eCTD技术规范V1.1：PDF规则二级依据映射

> Status: source-derived secondary basis. The effective `eCTD验证标准V1.1` section 6 remains controlling for rule ID and severity.

- Source SHA-256: `fbb193736108da6ca4d686d58f55469a0c00161f5db91c8e4fd30d8bf2b0ed7b`
- Parsed PDF pages: 44

## Confirmed design implications

1. The specification delegates general PDF production recommendations to ICH eCTD File Format Specification V1.3 and adds China-specific requirements.
2. Files over five pages generally need a table of contents and bookmarks, subject to stated exceptions.
3. Cross-document links include M1 change/research items to detailed content, M2 summaries to M3–M5 details, CSRs to appendices, and PDF dataset descriptions to XPT files.
4. Cross-application hyperlinks should not be created; package context is therefore required before classifying a target.
5. Chinese narrative text is black; hyperlinks are recommended as blue text or black text with a blue border. This is a production recommendation, not a section-6 rule.
6. Foreign-language reference material is a separate leaf under the same directory element as the Chinese submission material.

## Page locators automatically found

- `pdf_file_format`: PDF pages [20, 24, 30, 40]
- `five_page_bookmark`: PDF pages [24]
- `cross_document_links`: PDF pages [24, 25]
- `cross_application_links`: PDF pages [23, 25]
- `chinese_font`: PDF pages [25]
- `link_appearance`: PDF pages [25]
- `foreign_reference`: PDF pages [3, 24, 25, 26, 28]
- `electronic_seal`: PDF pages [3, 31]
- `md5`: PDF pages [5, 21, 38, 43]

## Rule-to-secondary-basis map

| Rule | Secondary basis |
|---|---|
| 6.1 | technical-specification §5 PDF/document integrity context |
| 6.2 | technical-specification §3.4 document navigation and cross-document link portability |
| 6.3 | technical-specification §3.4 navigation boundaries; no cross-application links |
| 6.4 | technical-specification §3.4 navigation behavior; PDF action semantics remain implementation detail |
| 6.5 | technical-specification §3.4 usable document navigation |
| 6.6 | technical-specification §3.4 valid internal/cross-document destinations |
| 6.7 | technical-specification §3.4 deterministic navigation |
| 6.8 | technical-specification §5 incorporates ICH eCTD File Format Specification V1.3 navigation recommendations |
| 6.9 | technical-specification §3.4 cross-document link portability |
| 6.10 | technical-specification §3.4 navigation boundaries; no cross-application links |
| 6.11 | technical-specification §3.4 navigation behavior; PDF action semantics remain implementation detail |
| 6.12 | technical-specification §3.4 usable document navigation |
| 6.13 | technical-specification §3.4 valid internal/cross-document destinations |
| 6.14 | technical-specification §3.4 deterministic navigation |
| 6.15 | technical-specification §5 incorporates ICH eCTD File Format Specification V1.3 navigation recommendations |
| 6.16 | technical-specification §5 incorporates ICH eCTD File Format Specification V1.3 version guidance |
| 6.17 | technical-specification §5 PDF restrictions |
| 6.18 | technical-specification §5 PDF restrictions and navigation annotations |
| 6.19 | technical-specification §5 PDF security restrictions |
| 6.20 | technical-specification §5 initial-view recommendations |
| 6.21 | technical-specification §5 PDF security restrictions |
| 6.22 | technical-specification §5 optimization/Fast Web View recommendations |
| 6.23 | technical-specification §5 China-specific requirement: files over five pages need TOC/bookmarks, subject to exceptions |
| 6.24 | technical-specification §5 PDF restrictions on dynamic content |
| 6.25 | technical-specification §5 searchable text and OCR recommendations |
| 6.26 | technical-specification §5 font embedding recommendations |

## Detector consequences

- Package-relative path resolution and eCTD node context are required for 6.2–6.15, 6.22 and 6.23.
- Link appearance and Chinese typography belong to a separate production-quality profile unless later elevated by an effective validator rule.
- Cross-document link generation is not a safe default fixer because semantic relationships cannot be proven from the PDF object graph alone.
- Attachment-package members are immutable technical inputs identified by byte hash, not handwritten approximations.
