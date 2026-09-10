# EZCTD P0 Decision Package

> Baseline date: 2026-09-03  
> Working branch: `agent/p0-b0-validation-matrix`  
> Official CDE eCTD validation software V1.1.0: `0 observations / NOT_RUN`

## 1. Decision requested

Approve P0 as an evidence-first, read-only technical baseline and keep all automatic PDF mutation disabled until official calibration is complete.

The P0 decision is not whether to build a complete eCTD publisher. It is whether the project has enough trustworthy regulatory evidence, test fixtures, independent probes and read-only behavior to begin official black-box calibration.

## 2. Machine status — read these first

The following files are authoritative for execution state:

1. `docs/status/P0_SENTINEL.txt` — fixed fields for local contracts, official status and draft PR;
2. `docs/status/P0_AUTOMATION_STATUS_V4.json` — workflow-level evidence;
3. `docs/status/P0_AGENT_LOOP_CONVERGENCE_V2.json` — all local/synthetic/read-only contract outputs;
4. `docs/status/LOCAL_VERIFICATION_RESULT.json` — independent isolated-environment result;
5. `docs/status/LOCAL_VERIFICATION_RESULT.md` — human-readable independent result.

A workflow file, a pushed commit, a generated fixture or a draft PR is not by itself proof that the corresponding gate passed. Success must be reflected in the generated result files above.

## 3. Regulatory baseline

Current implementation target:

- format family: eCTD V3.2.2;
- China technical files: V1.1;
- published: 2026-01-15;
- effective: 2026-03-01;
- PDF validation rules: section 6, rules 6.1–6.26;
- official severity distribution: 16 errors, 8 warnings, 2 information messages.

Source-verified rule metadata:

- `rulepacks/cn-cde-ectd/v1.1/cde_ectd_pdf_rules_v1.1_verified.json`
- `evidence/regulatory/P0-A_PDF_RULES_SOURCE_VERIFICATION.md`
- `evidence/regulatory/P0-A_SOURCE_REGISTER.md`

Remaining evidence work:

- official binaries and hashes for the technical specification, annex/util package, implementation guide, validation standard, directory mapping workbook, validator V1.1.0 and operation manual;
- static parsing of official DTD/XSD/XSL and China regional XML materials;
- one official-validator-proven clean baseline sequence.

Evidence ledger:

- `evidence/regulatory/P0_REGULATORY_EVIDENCE_COMPLETENESS.json`
- `evidence/regulatory/P0_REGULATORY_EVIDENCE_COMPLETENESS.md`

Direct CDE probe metadata:

- `evidence/regulatory/manual-probes/2026-09-03/probe.json`
- `evidence/regulatory/manual-probes/2026-09-03/classification.json`
- `evidence/regulatory/manual-probes/2026-09-03/static-inspection.json`

Every probe record remains a candidate until matched to the exact attachment label and, where applicable, signed/versioned executable metadata.

## 4. P0-B0 experimental evidence

Implemented artifacts:

- 26 detector contracts;
- 130 case recipes;
- 28 smoke fixtures:
  - one synthetic negative control;
  - 26 target-rule-positive PDFs;
  - one rule 6.23 reference-context differential;
- object-level self-checks;
- PDFium render/open probes;
- qpdf structural probes;
- fixture reproducibility checks;
- differential eCTD package rewriter;
- official-run input package generator.

Primary locations:

- `tests/p0_b0/`
- `tools/p0-b0/materialize_p0_b0.py`
- `docs/validation/p0-b0/RULE_VALIDATION_MATRIX.md`
- `docs/validation/p0-b0/SAMPLE_ISOLATION_AUDIT.md`

Interpretation:

- target-positive means the intended rule condition is deliberately present;
- it does not mean only one official message should be emitted;
- URI, JavaScript, absolute paths and password protection legitimately cross rule boundaries;
- official message coexistence and precedence remain unknown until V1.1.0 runs.

## 5. P0-B1 read-only implementation

Current package:

- `src/ezctd/catalog.py`
- `src/ezctd/applicability.py`
- `src/ezctd/models.py`
- `src/ezctd/pdf_observer.py`
- `src/ezctd/cli.py`

Read-only controls:

- no PDF save/write operation in the observer;
- before/after SHA-256 check over all 28 smoke PDFs;
- package inspector output must be outside the input package;
- symbolic links are rejected;
- package inventory is compared before and after inspection;
- findings are labelled experimental and evidence-backed.

Package/context components:

- `tools/ectd/inspect_baseline_candidate.py`
- `tests/p0_b1/context_map.schema.json`
- `tests/p0_b1/test_applicability_contract.py`
- `tests/p0_b1/test_baseline_candidate_inspector.py`

The package inspector may emit `CANDIDATE_READY_FOR_OFFICIAL_VALIDATOR`. It never certifies a China eCTD sequence.

## 6. Detector limitations

A 26/26 synthetic target hit is not a maturity claim.

Use:

- `docs/validation/p0-b1/DETECTOR_GAP_REGISTER.json`
- `docs/validation/p0-b1/DETECTOR_GAP_REGISTER.md`

Highest-priority technical gaps:

1. recursive `/A`, `/AA` and `/Next` action graph traversal;
2. nested platform-specific Launch/FileSpec handling;
3. inherited resources and Form XObject font/image traversal;
4. inline-image and rendered-nonblank searchability checks;
5. Windows casefold, Unicode and fragment-aware path normalization;
6. signature, DocMDP, AcroForm and XFA safety inventory;
7. per-file process isolation with CPU/memory/time limits.

## 7. Official calibration batch 01

The first official calibration is deliberately small and replicated:

- 7 unique packages: baseline, 6.1, 6.8, 6.19, 6.21, 6.22 and 6.26;
- 9 runs: baseline before, during and after the six target-positive runs;
- fixed restart points to reduce cache/application-state effects.

Files:

- `tests/p0_b0/official-validator/calibration_manifest.json`
- `tests/p0_b0/official-validator/calibration_run_plan.json`
- `docs/validation/p0-b0/OFFICIAL_VALIDATOR_CALIBRATION_BATCH_01.md`
- `tools/cde-validator/Prepare-CalibrationBatch.ps1`
- `tools/cde-validator/Prepare-CalibrationRunPlan.ps1`
- `tools/cde-validator/capture-validator-run.ps1`
- `tools/cde-validator/Finalize-OfficialRun.ps1`
- `tools/cde-validator/summarize_calibration_batch.py`

Evidence contract self-tests prove that the summarizer rejects missing screenshots and contaminated controls. They do not constitute a CDE run.

## 8. Official asset intake

Manual browser downloads are supported without committing raw binaries:

- intake template: `evidence/regulatory/manual-asset-intake.template.json`;
- importer: `tools/regulatory/import_official_assets.py`;
- default local store: `~/.ezctd/regulatory-assets`;
- Git stores only role, source URL status, hashes, magic and archive inventory.

Safety gates:

- size checked before reading or hashing;
- approved official host required in strict mode;
- extension and magic recorded separately;
- archives listed without execution;
- one exact binary cannot silently satisfy multiple evidence roles;
- oversized files are not hashed, inspected or copied;
- installers are never executed by the intake path.

## 9. Open-source component decisions

Preferred core:

- qpdf — structural check, rewrite and linearization;
- pikepdf — Python object access backed by qpdf;
- PDFium/pypdfium2 — independent rendering and text extraction;
- lxml — secure XML graph and future schema validation;
- pyHanko — future signature inspection only, after its limitations are explicitly tested;
- OCRmyPDF/Tesseract or PaddleOCR — optional high-risk OCR stage, not P0 core.

Independent/secondary validators:

- Apache PDFBox;
- veraPDF for PDF/A/UA questions;
- pdfcpu as an additional parser/CLI, not the sole authority.

License boundary:

- PyMuPDF/MuPDF and other AGPL components are not part of the default proprietary-capable core;
- open-source eCTD examples inform implementation structure only and are not regulatory evidence.

Inventory:

- `docs/research/open-source/inventory.json`
- `docs/research/open-source/OPEN_SOURCE_REFERENCE_INVENTORY.md`

## 10. Merge decision

The branch is eligible for a draft PR when all local contract gates pass. It is not eligible for a claim of regulatory compatibility.

Merge into `main` should require:

- machine status reports show local contracts PASS;
- independent environment report agrees;
- generated success markers are tied to actual run outputs;
- no raw regulatory binary, real dossier or secret is committed;
- official status remains explicitly `NOT_RUN` unless complete official evidence has been imported;
- detector gap register remains visible.

## 11. Current hard target

> Obtain and hash the official CDE eCTD validator V1.1.0 and operation manual, prove one clean China eCTD baseline sequence with that exact binary, then execute and preserve all nine calibration runs.

Tracking issue:

- `P0-B2：固化 CDE eCTD 验证软件 V1.1.0、clean baseline 与校准批次 01`

P0 cannot be completed by writing more source code around this missing official evidence.
