# Minimal China eCTD baseline sequence — evidence-constrained specification

> Status: **NOT YET OFFICIAL-VALIDATOR-CLEAN**. This document separates official facts, package observations and implementation hypotheses. It must not be presented as a certified China sequence template.

## Target

Create the smallest reproducible China eCTD V3.2.2 sequence that passes CDE eCTD validation software V1.1.0 before any PDF mutation is introduced.

## Officially controlled facts already fixed

- China effective baseline: CDE eCTD V3.2.2 related technical files V1.1, effective 2026-03-01.
- PDF rules: validation standard V1.1 section 6, rules 6.1–6.26.
- The official validator target is V1.1.0. A baseline is not accepted merely because XML is well-formed or an ICH DTD validates.
- ICH eCTD 3.2.2 supplies the international backbone; China regional Module 1 requirements and CDE validation behavior remain controlling.

## Observed technical-package evidence

- Packages/trees analyzed: 1
- Candidate complete sample sequences: 0
- Observed regional backbone files: 0
- Observed DTD/XSD/XSL files: 1

### Regional backbone candidates

No `cn-regional.xml` or other regional backbone was observed in the automatically retrieved asset set.

### Utility files observed

- `001-xhtml1-transitional.dtd`

## Candidate directory model — hypothesis only until validated

```text
<application-root>/
└─ 0000/
   ├─ index.xml
   ├─ index-md5.txt
   ├─ m1/
   │  └─ <China regional subtree and regional backbone>
   ├─ m2/ ... m5/ as required by the chosen minimal submission context
   └─ util/
      ├─ dtd-or-schema/
      └─ style/
```

The exact application-root naming, China Module 1 path, regional XML filename, metadata fields and utility filenames must be populated from the effective official package—not from this schematic.

## Baseline construction gates

1. Freeze official utility package files byte-for-byte and record hashes.
2. Select one minimal allowed submission context; list every required China regional metadata field.
3. Generate backbone XML from typed metadata and validate with the shipped DTD/XSD without network resolution.
4. Include one searchable, linearized, bookmarked PDF leaf that passes all applicable 6.1–6.26 rules.
5. Compute leaf MD5 over final bytes, serialize XML once, then compute the required index MD5 over those final XML bytes.
6. Run CDE V1.1.0 and preserve the full report. Iterate until the package is clean without suppressing messages.
7. Freeze the clean package as a read-only baseline, record a complete SHA-256 inventory and never mutate it in place.
8. Run a negative control by changing one byte without updating checksums; confirm package validation catches it.

## Current blockers

- No official-validator-clean China baseline has been demonstrated.
- China regional XML metadata requirements remain unresolved unless observed in an official package extracted by this analysis.
- Official V1.1.0 report output format and stable message identifiers are not yet captured.
