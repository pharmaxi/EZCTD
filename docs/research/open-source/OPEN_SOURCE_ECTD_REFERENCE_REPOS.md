# Open-source PDF/eCTD reference inventory

> Generated from GitHub API metadata and code/repository search. Every repository is a non-authoritative implementation reference; CDE effective technical files remain controlling.

Generated: 2026-09-03T10:43:07.578451+00:00

## Decision summary

| Repository | Category | License | Last push | Recommendation | Assessment |
|---|---|---|---|---|---|
| [`qpdf/qpdf`](https://github.com/qpdf/qpdf) | PDF structural engine | Apache-2.0 | 2026-08-30T14:50:50Z | `ADOPT_CORE` | Mature low-level structural inspection, repair, rewrite and linearization; not a renderer or CDE rules engine. |
| [`pikepdf/pikepdf`](https://github.com/pikepdf/pikepdf) | Python PDF object layer | MPL-2.0 | 2026-08-18T07:46:48Z | `ADOPT_CORE` | Python interface backed by qpdf; suitable for object-level inspection and controlled writing. |
| [`py-pdf/pypdf`](https://github.com/py-pdf/pypdf) | Python high-level PDF API | NOASSERTION | 2026-09-02T18:04:47Z | `ADOPT_AUXILIARY` | Convenient outlines, destinations and annotations API; cross-check complex or malformed files with qpdf/PDFium. |
| [`pypdfium2-team/pypdfium2`](https://github.com/pypdfium2-team/pypdfium2) | PDF renderer | NOASSERTION | 2026-09-03T10:39:53Z | `ADOPT_CORE` | Independent rendering and page probe based on PDFium; isolate native parsing in worker processes. |
| [`MatthiasValvekens/pyHanko`](https://github.com/MatthiasValvekens/pyHanko) | PDF signature inspection | MIT | 2026-08-31T22:40:44Z | `ADOPT_INSPECTION_ONLY_INITIAL` | Useful for signature discovery, validation and incremental-update analysis; official CDE signing remains out of scope. |
| [`ocrmypdf/OCRmyPDF`](https://github.com/ocrmypdf/OCRmyPDF) | OCR PDF pipeline | MPL-2.0 | 2026-09-01T21:33:13Z | `ADOPT_OPTIONAL` | Strong searchable-text-layer pipeline; OCR is high-risk and must stay opt-in with visual verification. |
| [`tesseract-ocr/tesseract`](https://github.com/tesseract-ocr/tesseract) | OCR engine | Apache-2.0 | 2026-09-02T12:00:26Z | `ADOPT_OPTIONAL` | Widely used OCR engine; pin language data and versions, and benchmark Chinese regulatory documents. |
| [`PaddlePaddle/PaddleOCR`](https://github.com/PaddlePaddle/PaddleOCR) | Chinese document OCR | Apache-2.0 | 2026-07-22T11:59:34Z | `EVALUATE_PLUGIN` | Potentially stronger Chinese/layout recognition; heavier runtime and output must not be treated as original content. |
| [`veraPDF/veraPDF-apps`](https://github.com/veraPDF/veraPDF-apps) | PDF/A and PDF/UA validator | GPL-3.0 | 2026-08-31T10:29:47Z | `ADOPT_INDEPENDENT_QA` | Useful for genuine PDF/A conformance checks; not a substitute for CDE validation rules. |
| [`apache/pdfbox`](https://github.com/apache/pdfbox) | Independent Java PDF parser | Apache-2.0 | 2026-09-03T08:21:52Z | `ADOPT_SECONDARY_VALIDATOR` | Mature independent parser and CLI; useful for differential interpretation and PDF/A-related checks. |
| [`pdfcpu/pdfcpu`](https://github.com/pdfcpu/pdfcpu) | Go PDF processor | Apache-2.0 | 2026-08-24T10:03:29Z | `EVALUATE_CROSS_CHECK` | Broad CLI and validation surface; do not make it the sole compliance engine without corpus evidence. |
| [`pymupdf/PyMuPDF`](https://github.com/pymupdf/PyMuPDF) | High-performance PDF toolkit | AGPL-3.0 | 2026-08-27T08:31:13Z | `LICENSE_GATED` | Technically capable, but AGPL/commercial licensing should remain isolated from a future closed distribution. |
| [`mozilla/pdf.js`](https://github.com/mozilla/pdf.js) | Web PDF viewer | Apache-2.0 | 2026-09-03T00:11:09Z | `ADOPT_UI` | Strong viewer and debugger for a Tauri/web UI; backend compliance decisions must not depend on browser rendering alone. |
| [`Stirling-Tools/Stirling-PDF`](https://github.com/Stirling-Tools/Stirling-PDF) | PDF workflow UI reference | NOASSERTION | 2026-09-03T10:35:48Z | `REFERENCE_ONLY` | Useful interaction and job-flow reference; its broad generic PDF scope is not an eCTD compliance model. |
| [`sebsca/ectd-tool`](https://github.com/sebsca/ectd-tool) | eCTD XML generator/viewer | NOASSERTION | 2026-02-07T13:41:49Z | `REFERENCE_PROTOTYPE` | Useful for ICH 3.2 index.xml and EU regional mapping concepts; not validated for current China V1.1 production submissions. |
| [`Lewis-Teoh/dotnet-ectd-validator`](https://github.com/Lewis-Teoh/dotnet-ectd-validator) | Regional eCTD package validator | NOASSERTION | 2026-07-16T07:53:38Z | `REFERENCE_ARCHITECTURE` | Useful package security, hierarchy and checksum architecture for Singapore; regional rules cannot be transplanted to China. |
| [`RegHubAI/Auto-publisher-for-eCTD`](https://github.com/RegHubAI/Auto-publisher-for-eCTD) | FDA PDF compliance prototype | NOASSERTION | 2026-02-15T17:07:36Z | `REFERENCE_TEST_IDEAS` | Contains DOCX-to-PDF, bookmarks and links ideas; new/small and FDA-specific, not evidence of CDE compliance. |
| [`SandipKurmi/ectd-pdf-validator`](https://github.com/SandipKurmi/ectd-pdf-validator) | FDA-style PDF validator prototype | NOASSERTION | 2026-07-10T14:18:51Z | `REFERENCE_WITH_CAUTION` | Rule service shape is instructive, but broad compliance claims and simplified predicates require independent verification. |
| [`fragkopoulos/ectd-validator`](https://github.com/fragkopoulos/ectd-validator) | eCTD placeholder | GPL-3.0 | 2017-12-12T08:36:37Z | `DO_NOT_USE` | Repository is effectively a placeholder and supplies no usable validation implementation. |
| [`AymenZelaiti/eCTD-Pharmacology`](https://github.com/AymenZelaiti/eCTD-Pharmacology) | Unclassified search result | NOASSERTION | 2021-09-21T11:44:30Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`Cynthia-0101/paper`](https://github.com/Cynthia-0101/paper) | Unclassified search result | NOASSERTION | 2025-07-19T02:50:20Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`Dj091003/Mock-CTD-eCTD-Dossier-Preparation`](https://github.com/Dj091003/Mock-CTD-eCTD-Dossier-Preparation) | Unclassified search result | NOASSERTION | 2025-12-16T14:22:11Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`Jonmichaelpsmith/ClinicalSageAI`](https://github.com/Jonmichaelpsmith/ClinicalSageAI) | Unclassified search result | NOASSERTION | 2025-05-19T17:52:04Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`KshitizKoirala/PDF-Preflight-Checker`](https://github.com/KshitizKoirala/PDF-Preflight-Checker) | Unclassified search result | NOASSERTION | 2026-02-28T15:48:09Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`LucisZhang/privacy-preflight`](https://github.com/LucisZhang/privacy-preflight) | Unclassified search result | MIT | 2026-09-02T09:47:20Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`Mogilenko-Lab/Gama_Vivian_DRP1_bulkRNAseq`](https://github.com/Mogilenko-Lab/Gama_Vivian_DRP1_bulkRNAseq) | Unclassified search result | MIT | 2026-07-01T06:57:09Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`Padam87/pdfbox-preflight`](https://github.com/Padam87/pdfbox-preflight) | Unclassified search result | NOASSERTION | 2018-06-21T11:53:37Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`QunATCG/SARSCoV2`](https://github.com/QunATCG/SARSCoV2) | Unclassified search result | MIT | 2024-01-26T08:45:19Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`Rastaman4e/-1`](https://github.com/Rastaman4e/-1) | Unclassified search result | NOASSERTION | 2021-04-16T17:49:49Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`Veerendra-KM/eCTD-Initial-Submission-Analytics-Dashboard`](https://github.com/Veerendra-KM/eCTD-Initial-Submission-Analytics-Dashboard) | Unclassified search result | NOASSERTION | 2026-07-02T13:35:25Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`ZanderOperator/eCTD_File_Validator`](https://github.com/ZanderOperator/eCTD_File_Validator) | Unclassified search result | MIT | 2023-07-28T08:04:44Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`aipoch/medical-research-skills`](https://github.com/aipoch/medical-research-skills) | Unclassified search result | MIT | 2026-07-15T12:42:34Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`aishwaryaSudhakar01/pdf-edits`](https://github.com/aishwaryaSudhakar01/pdf-edits) | Unclassified search result | NOASSERTION | 2026-06-05T15:34:38Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`aliibarry/turboID`](https://github.com/aliibarry/turboID) | Unclassified search result | NOASSERTION | 2026-05-09T14:43:51Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`berezine81/validation-service`](https://github.com/berezine81/validation-service) | Unclassified search result | MIT | 2024-05-23T18:11:50Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`bitorepos/ActuaryPOS`](https://github.com/bitorepos/ActuaryPOS) | Unclassified search result | NOASSERTION | 2026-09-03T10:22:20Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`bitsgalore/pftree`](https://github.com/bitsgalore/pftree) | Unclassified search result | NOASSERTION | 2012-11-21T15:46:09Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`caffeinepub/ectd-gateway`](https://github.com/caffeinepub/ectd-gateway) | Unclassified search result | NOASSERTION | 2026-02-26T16:54:20Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`concept2cure/ClinicalSageAI-2-replit`](https://github.com/concept2cure/ClinicalSageAI-2-replit) | Unclassified search result | MIT | 2026-09-03T03:34:28Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`dayzero/ectd_indexer`](https://github.com/dayzero/ectd_indexer) | Unclassified search result | GPL-3.0 | 2025-09-01T23:06:18Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`dhirajtiwari/eCTD`](https://github.com/dhirajtiwari/eCTD) | Unclassified search result | NOASSERTION | 2026-08-30T11:03:46Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`gabrielmoreira/agent-skills-mirror`](https://github.com/gabrielmoreira/agent-skills-mirror) | Unclassified search result | MIT | 2026-09-03T04:50:14Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`gvavou5/PAT-REC-NTUA`](https://github.com/gvavou5/PAT-REC-NTUA) | Unclassified search result | NOASSERTION | 2019-09-07T08:38:57Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`hjn0415a/Streamlit-R`](https://github.com/hjn0415a/Streamlit-R) | Unclassified search result | NOASSERTION | 2025-10-15T06:25:40Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`kotarokikuchi/pdflang`](https://github.com/kotarokikuchi/pdflang) | Unclassified search result | MIT | 2026-08-15T14:44:16Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`lfq0921/NJU-DLCOE`](https://github.com/lfq0921/NJU-DLCOE) | Unclassified search result | NOASSERTION | 2024-04-23T09:07:20Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`mdanny2785-sketch/CMYK-Color-Suite-v2.4-Print-SVG-PSVG`](https://github.com/mdanny2785-sketch/CMYK-Color-Suite-v2.4-Print-SVG-PSVG) | Unclassified search result | MIT | 2026-04-07T09:40:14Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`mika-lia/spherehosting`](https://github.com/mika-lia/spherehosting) | Unclassified search result | NOASSERTION | 2023-09-19T16:26:47Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`mmoideen/reguflow`](https://github.com/mmoideen/reguflow) | Unclassified search result | NOASSERTION | 2026-08-29T17:04:29Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`musejack888/ICH-electronic-Common-Technical-Document---eCTD-v4.0`](https://github.com/musejack888/ICH-electronic-Common-Technical-Document---eCTD-v4.0) | Unclassified search result | NOASSERTION | 2026-02-25T01:28:52Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`ocowala/ectd_saas`](https://github.com/ocowala/ectd_saas) | Unclassified search result | NOASSERTION | 2026-01-25T20:54:00Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`rposborne/ectd_check`](https://github.com/rposborne/ectd_check) | Unclassified search result | MIT | 2015-04-02T19:32:26Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`serigne007mor/PRED`](https://github.com/serigne007mor/PRED) | Unclassified search result | NOASSERTION | 2024-02-25T19:19:23Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |
| [`sherozshaikh/paperflight`](https://github.com/sherozshaikh/paperflight) | Unclassified search result | MIT | 2026-04-13T01:41:55Z | `REVIEW_REQUIRED` | Discovered by search; code and licensing require manual review. |

## Reuse rules

1. Official CDE/NMPA effective files control regulatory semantics and severity.
2. GitHub projects may supply parsers, test ideas, data models or UI patterns; none is accepted as proof of CDE compatibility.
3. AGPL/commercial dual-license components remain isolated behind adapters unless the distribution model explicitly accepts those obligations.
4. Regional eCTD validators demonstrate architecture only; Singapore, FDA, EU and China rules are not interchangeable.
5. Any copied code must retain its license and notices; behavioral ideas should be independently implemented and tested against official sources.

## Search coverage

- Repository queries: 6
- Code queries: 6
- Unique repositories inventoried: 54
- Search errors: 0

Raw API-normalized search results are stored in `raw/search-results.json`.
