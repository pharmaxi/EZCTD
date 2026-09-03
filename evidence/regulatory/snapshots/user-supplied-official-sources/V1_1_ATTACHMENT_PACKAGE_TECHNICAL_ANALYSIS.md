# eCTD技术规范V1.1附件包：技术解析

> Source class: official effective technical package. Generated from frozen bytes; it does not replace the effective validation standard or the official validator.

## Byte identity

- Package source SHA-256: `0dbfd2ffb8969731deef3a1dd446da6b48511b2d537c5946eb9498a0b5992eea`
- Members: **23**
- Aggregate member bytes: **659173**

## Composition

- XSD: 6
- XML: 9
- XSL: 4
- DTD: 2
- PDF: 2

## Schema findings

- Target namespace: `cn_ectd`.
- Root schema-version enumeration: `['1.0']`.
- Top-level regional chapters: 13; structurally required: `['cn-1-0']`.
- `cn-leaf-ext` permits an empty sequence: `True`.
- Required `cn-leaf` attributes: `['ID', 'operation']`.
- Leaf operations: `['new', 'append', 'replace', 'delete']`.
- Checksum types: `['MD5', 'md5']`.

**Consequence:** XSD-valid is not equivalent to submission-valid. Controlled vocabulary, dependency, applicability, lifecycle, path, file and checksum rules remain separate.

## Controlled vocabularies

| Vocabulary | Version | Valid from | Codes |
|---|---:|---:|---:|
| `application-type` | 1.1 | 2026-3-1 | 4 |
| `product-type` | 1.0 | 2021-9-1 | 2 |
| `regulatory-activity-type` | 1.0 | 2021-9-1 | 9 |
| `sequence-type` | 1.0 | 2021-9-1 | 4 |

- Dependency matrix: version **1.1**, valid from **2026-3-1**, **75** valid triples.
- V1.1 application/dependency assets add drug-substance support while several companion assets retain V1.0 declarations.

## Element metadata

- China Module 1 elements: **70**.
- ICH elements: **159**.
- China 3.2.R node extensions: **6**.

## Engineering decisions

1. Pin the entire attachment package by package hash and member hashes.
2. Validate in layers: well-formedness → XSD/DTD → vocabulary → dependency → path/reference/checksum/lifecycle → official validator.
3. Keep schema cardinality separate from application/sequence applicability.
4. Treat `append` as syntactically allowed, not automatically recommended for every China lifecycle scenario.
5. Use XML vocabulary/dependency files as machine-readable authority; do not derive permitted values from XSL display labels.
6. Preserve submitted codes separately from bilingual UI labels.
7. Retain official-validator comparison for interactions not fully encoded by schemas.

## Version-coordination warning

The distributed V1.1 package is observably mixed-version: regional schema and several metadata files retain V1.0 declarations while application, dependency and regional style assets contain V1.1 changes. EZCTD must model one coordinated release package rather than independently selecting the numerically newest member of each family.
