# EZCTD development instructions

## Product scope

Build a local clinical CRO PDF workbench for Module 5, 2.5 and 2.7 with optional CRO-provided certificates. Partial clinical folders are first-class input. Do not require XML backbones, full Module 1–5, a clean submission sequence or whole-submission validation before delivering PDF functions. Keep historical research intact; current scope is `docs/product/CRO_PDF_WORKBENCH_V0_2.md` and current delivery order is `docs/roadmap/CRO_DELIVERY.md`.

## Non-negotiable boundaries

- Never overwrite input or existing output files. All command and future UI paths use shared no-clobber I/O.
- Reports, previews, cache and future repaired PDFs are outside selected input/reference trees.
- Never open links beyond explicitly selected roots. A missing partial-delivery target is NOT proof of a broken submission.
- Never execute PDF/HTML JavaScript, URI, Launch or embedded attachments. Report import is inert data parsing.
- Parent orchestration and report import must not load native PDF engines; run them in bounded disposable workers.
- Native worker isolation is not an OS security sandbox. Do not claim memory/network containment without evidence.
- Keep official report observations, current PDF identities, local checks, applicability and future changes separate.
- Every rule needs an explicit execution status. Failure or missing context is never silently PASS.
- Signature signals block future rewrite operations; cryptographic validation is a separate capability.
- Do not substitute PDF Base-14 for CDE's exact font list. Do not silently normalize aliases into regulatory equivalence.
- Do not upload real clinical reports, paths, subject identifiers, PDFs, credentials or font files. Use synthetic fixtures. `.gitignore` is not permission to read private folders.

## Implementation and testing

Use main, inspect its actual HEAD and working tree before editing. Do not force-push, rewrite research history, or claim a PR exists without checking.

```bash
python -m pip install -e ".[test]"
python -m pytest -q tests/cro_pdf
python scripts/validate_artifacts.py
python scripts/validate_p0b0_matrix.py
python tools/corpus/build_pdf_fixtures.py --output tests/corpus/generated-smoke --mode smoke
python scripts/inspect_p0b0_smoke.py
```

Run Windows regression for pathname, UTF-8, hardlink/reparse handling and native workers. A hosted Windows Server result is not Windows 10/11 or NAS certification. Retain skips and failures. Use explicit UTF-8 for JSON/HTML.

The standard CI entry is `artifact-integrity.yml`; do not create a new v2/v3 workflow per fix. Malformed superseded workflows are retained byte-for-byte under `.github/archived-workflows/`, not active CI.

## Small delivery loop

One concrete task → smallest implementation → positive and negative tests → actual result → commit with scope and limitations. Repeating a failed experiment without new information is not progress. Do not change expected results just to get green checks. Preserve source hashes and fixed test inputs; do not represent a stubbed unit test as a native integration test.

Next priority: verify the existing 0.3 reader and linearization flow on local Windows, then improve readability and issue ordering. Full Publisher, v4.0 runtime, generic reflow, OCR-by-default and automatic font substitution remain out of scope.
