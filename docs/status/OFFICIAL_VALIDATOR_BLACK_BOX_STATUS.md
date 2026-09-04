# CDE eCTD validation software black-box status

- Current state: **OFFICIAL_ASSETS_ACQUIRED_AND_STATICALLY_IDENTIFIED**
- Official black-box observations: **0**
- Software executed: **false**

The prior blocker was asset acquisition, not validator execution. `downloadFiles(4/5)` opens a second-stage attachment dialog; the v2 collector waited for a transfer that never began. V3 verifies the direct URLs in the current official `common.js`, downloads the bytes with the same browser session, and performs Windows static identity inspection.

The next admissible step is execution reconnaissance with an empty/synthetic workspace to determine installer/portable form, process tree, GUI or CLI entry point, required runtime, accepted input unit, output files, logs and exit behavior. It must not yet be counted as a PDF-rule calibration observation unless a complete input and raw validator result are preserved.

## Evidence boundary

Official provenance and static identity only. No official validator result and no CDE compatibility claim.
