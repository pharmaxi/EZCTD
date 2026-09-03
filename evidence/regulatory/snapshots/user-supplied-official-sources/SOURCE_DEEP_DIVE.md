# User-supplied official eCTD sources — deep-dive manifest

> Generated from the exact CDE URLs supplied by the project owner. Raw binaries are stored as a GitHub Actions artifact; the repository stores hashes, inventories, locators and analysis.

## Direct sources

| Source ID | Status | Kind | Bytes | SHA-256 |
|---|---|---:|---:|---|
| `CDE-ECTD-COLUMN` | SUCCESS | html | 25082 | `36bd27021e061542fb775fb4c7eecab5dcbd10021507c9c0e988cbc906e0b1f9` |
| `CDE-CN-V1.1-SPEC-PDF` | SUCCESS | pdf | 1742696 | `fbb193736108da6ca4d686d58f55469a0c00161f5db91c8e4fd30d8bf2b0ed7b` |
| `CDE-CN-V1.1-SPEC-ATTACHMENTS` | SUCCESS | zip | 494123 | `0dbfd2ffb8969731deef3a1dd446da6b48511b2d537c5946eb9498a0b5992eea` |
| `CDE-CN-V4-DRAFT-NOTICE` | SUCCESS | html | 25526 | `6db293ca4ce6d80b62eb21e40a3b13daddfc247d0c52212392f693da0a44738e` |

## Discovered official download candidates

| Source ID | Role | Kind | Bytes | SHA-256 |
|---|---|---:|---:|---|

## Interpretation controls

- V1.1 technical specification and attachment package are effective-source evidence for the current China eCTD V3.2.2 profile.
- Effective validation standard section 6 remains the primary source for PDF rule identity and severity.
- Technical specification is secondary normative context for detector semantics and applicability; it does not override the validation table.
- The 2026-05-27 China eCTD v4.0 documents are consultation drafts and remain isolated from the effective runtime profile.
- Validator software/manual candidates remain unconfirmed until filename, content and internal metadata support the role.
