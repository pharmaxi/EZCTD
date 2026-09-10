# CDE eCTD validation software V1.1.0 — portal acquisition v3

- Status: **COMPLETE_OFFICIAL_PORTAL_ACQUISITION**
- Portal: https://www.cde.org.cn/ectd/index
- Common JavaScript: `https://www.cde.org.cn/ectd/js/common.js?v=20260817`
- Common JavaScript SHA-256: `ebd564a8c9c188eae38f09cf22336f968421d1997cf2ed823ff5c48221b25de5`
- Validator executed: **false**
- Official black-box observations: **0**

## Root-cause correction

`downloadFiles(4/5)` opens a LayUI attachment dialog. It does not initiate the file transfer. The v2 collector waited for a download that could never start and therefore returned `candidates=[]`. V3 verifies the exact direct URLs inside the currently served official `common.js`, then downloads those bytes with the same browser session.

| Role | Official control | Kind | Bytes | SHA-256 |
|---|---|---:|---:|---|
| `validator_software_v1_1_0` | `downloadFiles(4)` | zip | 162000248 | `d3f143873fb37b78dbc952c8d8d6db5a13a82c5ba5a77798b8319852b9ed2b36` |
| `validator_manual_v1_1_0` | `downloadFiles(5)` | pdf | 1124051 | `30eef1b42d6fc980b243bcc667291eb7abc9ddc2c4dc33a5c8a67cb1368f583b` |

## Boundary

This evidence proves official-portal provenance and byte-valid acquisition only. Static identity inspection and controlled execution remain separate gates; no CDE compatibility claim is made here.
