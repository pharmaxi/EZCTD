# Official-source deep-dive review 001

- Date: 2026-09-04
- Branch: `agent/official-source-deep-dive`
- Parent baseline: `agent/p0-b0-validation-matrix`
- Review purpose: determine what the newly supplied CDE portal, V1.1 technical package and China eCTD v4.0 public-comment files prove, what they do not prove, and the next experiment that can materially reduce uncertainty.

## 1. Findings accepted

### 1.1 Current implementation baseline

The effective China runtime and official-validator calibration target remains **eCTD V3.2.2 with China technical files V1.1**. The 2026-05-27 China eCTD v4.0 package is a public-comment draft and is isolated as a research-only profile with `runtime_enabled=false`.

### 1.2 V1.1 technical package

The supplied official V1.1 attachment package is not merely reference documentation. It contains the China regional schema, controlled vocabularies, dependency tables, element-property definitions, stylesheet assets, ICH backbone definitions and STF resources needed to model a candidate sequence. The package inventory and derived machine-readable tables are retained with the source-package hash.

The package release label and member-internal comments are not interchangeable. Some member files retain older internal version annotations; runtime selection must be based on the released package identity and source provenance rather than a single embedded comment.

### 1.3 China eCTD v4.0 draft

The byte-validated draft package contains five assets: guidance, controlled vocabulary, validation standard, drafting rationale and feedback form. The validation standard has 165 machine-indexed rules: 145 errors, 14 warnings and 6 informational messages. The PDF section has 27 rules: 16 errors, 9 warnings and 2 informational messages.

The principal PDF delta is not a wholesale replacement of the current 26 rules. Current rule 6.23 is split: an ordinary document longer than five pages without bookmarks remains an error, while a baseline-type document is handled by a separate warning. Multiple bookmark/link rules also add baseline applicability exclusions. These draft exclusions must not leak into current V1.1 findings.

### 1.4 Official validator and manual

The validator software and operation manual were acquired through the rendered official CDE portal controls `downloadFiles(4)` and `downloadFiles(5)`. Static archive, file-version and Authenticode inspection was performed on a Windows runner. No executable, installer, DLL or bundled script was launched.

This evidence establishes provenance and static identity only. It does not establish that the software runs correctly in the intended environment, that a candidate sequence is valid, or that any EZCTD detector agrees with the official validator.

## 2. Claims rejected or deferred

The following claims remain unsupported and must not appear in product text or status dashboards:

1. “EZCTD covers all CDE validation rules.”
2. “The 26 PDF detectors are equivalent to the official validator.”
3. “The generated candidate package is a valid China eCTD sequence.”
4. “The v4.0 public-comment files are effective requirements.”
5. “Static signature/version inspection is an official-validator test.”
6. “A successful open-source PDF parse implies CDE acceptance.”

Official black-box observations remain **0**.

## 3. Architecture decisions after review

1. Keep one canonical source workflow: `.github/workflows/converge-official-regulatory-sources.yml`.
2. Keep raw regulatory binaries outside Git history as Actions artifacts; commit only provenance, hashes, inventories, extracted machine-readable facts and review conclusions.
3. Preserve independent profiles for V3.2.2/V1.1 and the v4.0 draft.
4. Use the official V1.1 package to build a candidate-sequence data model, but reserve the word “valid” for official-validator evidence.
5. Treat PDF rules as context-sensitive: node, document role, language and baseline status are explicit inputs.
6. Do not implement automatic repair until a detector has an official calibration result and a demonstrated no-change/no-new-finding postcondition.

## 4. Next hard target

> Build one minimal, reproducible China eCTD V3.2.2/V1.1 sequence that produces no blocking result in the acquired official validator, then execute the defined nine-run calibration batch.

### Required sequence evidence

- Exact V1.1 schema and controlled-vocabulary versions;
- deterministic file tree and XML serialization;
- `index.xml` and China regional XML references;
- correct lifecycle operation and leaf metadata;
- valid relative paths and MD5 values;
- one small searchable PDF with explicit document context;
- complete input SHA-256 inventory;
- official validator software hash, environment, run timestamp and raw report;
- screenshots sufficient to reproduce every reported message;
- confirmation that the sequence is unchanged before and after validation.

### Nine-run calibration order

1. clean baseline — pre;
2. rule 6.8 mutation;
3. clean baseline — mid;
4. rule 6.22 mutation;
5. rule 6.26 mutation;
6. rule 6.19 mutation;
7. rule 6.21 mutation;
8. rule 6.1 mutation;
9. clean baseline — post.

Three baseline runs are required to reveal cache, state or history effects in the official software.

### Exit criterion for the next loop

The next loop is not complete merely when a sequence opens. It is complete only when:

- all three baseline runs are stable and contain no chapter-6 finding;
- each mutation produces a captured and normalized official observation, or a documented negative result;
- raw reports and screenshots are hashed;
- software/environment identity is fixed;
- all discrepancies between expected and observed behavior are entered into the calibration matrix;
- no input file changed during any validator run.

## 5. Current disposition

The official-source branch is suitable for review and integration into the P0 research baseline. It is **not** a release candidate and does not close P0. The next source of truth must be an actual run of the acquired CDE validator against a controlled V1.1 sequence.
