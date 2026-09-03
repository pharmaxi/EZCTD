# P0-B1 detector gap register

> 26/26 synthetic target-condition coverage is not equivalent to 26 mature detectors. This register records current evidence and known failure modes before CDE V1.1.0 calibration.

## Status distribution

- `BLOCKED_OFFICIAL_BEHAVIOR`: 8
- `IMPLEMENTED_CONTEXT_DEPENDENT`: 3
- `IMPLEMENTED_SYNTHETIC_UNCALIBRATED`: 3
- `PARTIAL_HEURISTIC`: 12

## Rule-level register

| Rule | Status | Implemented evidence | Main false-negative risks | Main official question | Next test |
|---|---|---|---|---|---|
| 6.1 | `BLOCKED_OFFICIAL_BEHAVIOR` | pikepdf/qpdf-backed parse; qpdf --check; PDFium first/last-page render; page count | damage on an unrendered middle page; recoverable cross-reference damage accepted by one engine; content-stream errors not reached during sampled rendering | whether one unreadable leaf short-circuits remaining PDF rules; whether recoverable files are error or accepted; reported path/object granularity | P0-B2 calibration case 6.1 plus recoverable-corruption boundary family |
| 6.2 | `IMPLEMENTED_CONTEXT_DEPENDENT` | GoToR/Launch FileSpec path classification; Windows/UNC/POSIX/file URI detection; submission-root escape check | platform-specific nested Launch dictionaries; unusual FileSpec encodings; percent-encoded paths | path base used by validator; message coexistence with 6.3 and 6.6 | controlled Windows existing-absolute-target experiment |
| 6.3 | `BLOCKED_OFFICIAL_BEHAVIOR` | URI/mailto/scheme classification; absolute and package-escape target classification | nested Launch platform dictionary; custom protocol hidden in FileSpec; external target represented through named action | whether URI also emits 6.4; treatment of http, https, mailto and file separately | URI/mailto/Launch/GoToR encoding matrix |
| 6.4 | `PARTIAL_HEURISTIC` | primary /A action type check against GoTo, GoToR and Launch | unknown action only in /AA; unknown action only in /Next chain; action arrays; field or page additional actions | whether JavaScript produces 6.4, 6.24 or both; action graph traversal depth | recursive action-graph detector before calibration expansion |
| 6.5 | `IMPLEMENTED_SYNTHETIC_UNCALIBRATED` | outline item lacks both /Dest and /A | operation supplied only through nonstandard additional-action structure | whether non-clickable parent bookmarks are allowed; treatment of empty-title nodes | parent-with-valid-children and empty-title boundaries |
| 6.6 | `PARTIAL_HEURISTIC` | internal page-object validation; numeric page index range; legacy/name-tree named destination resolution; external target existence | embedded-file destinations; GoToE; destination fragments; platform-specific FileSpec; damaged destination tolerated by pikepdf | distinction between invalid and damaged; target file versus target page error precedence | destination-type and named-destination boundary family |
| 6.7 | `PARTIAL_HEURISTIC` | /Dest plus /A count; /Next chain recursion; /AA key count | cyclic or malformed arrays; viewer-triggered actions outside inspected outline dictionary | which action containers contribute to the count; whether /Dest plus /A is always multiple | one-action-per-container factorial experiment |
| 6.8 | `BLOCKED_OFFICIAL_BEHAVIOR` | explicit destination resolution; /XYZ zoom null versus numeric; Fit-family classification | named destination indirection not resolved in malformed trees; remote destination semantics | exact handling of /XYZ null, omitted zoom, zero zoom and Fit/FitH/FitV/FitR | P0-B2 calibration case 6.8 followed by full destination matrix |
| 6.9 | `IMPLEMENTED_CONTEXT_DEPENDENT` | same path classification and package-root escape controls as 6.2 for Link annotations | nested platform FileSpec; URI-like path embedded in custom action | message coexistence with 6.10/6.13; case sensitivity and Unicode normalization | controlled Windows existing-absolute-target experiment |
| 6.10 | `BLOCKED_OFFICIAL_BEHAVIOR` | URI/mailto/absolute/package-escape detection on Link actions | nested Launch structures; custom schemes hidden in non-primary actions | whether URI also emits 6.11; whether visible URL text without a link annotation is relevant | URI/mailto/Launch/GoToR link matrix |
| 6.11 | `PARTIAL_HEURISTIC` | primary Link /A type check against GoTo, GoToR and Launch | unknown type in /AA or /Next; actions attached through form fields or page events | recursive action traversal; relationship to 6.24 | recursive action-graph detector |
| 6.12 | `IMPLEMENTED_SYNTHETIC_UNCALIBRATED` | Link annotation lacks both /Dest and /A | action supplied only through /AA or unusual structure | treatment of zero-area and invisible links; whether /AA alone counts | geometry and alternate-action boundary cases |
| 6.13 | `PARTIAL_HEURISTIC` | internal page and named destination validation; external file and numeric page checks | fragment syntax; embedded destinations; nested FileSpec; cross-platform filename normalization | distinction from 6.12; file versus page error precedence | destination-type and missing-file/page matrix |
| 6.14 | `PARTIAL_HEURISTIC` | /Dest, /A, /AA and /Next action counting | malformed arrays and cyclic action graphs | exact action containers counted | factorial action-container matrix |
| 6.15 | `BLOCKED_OFFICIAL_BEHAVIOR` | same explicit/named destination zoom classification as 6.8 for Link annotations | remote and malformed named destinations | same destination-mode matrix as 6.8 | post-6.8 calibration link matrix |
| 6.16 | `PARTIAL_HEURISTIC` | header version; Catalog /Version override; allowed ordinary PDF 1.4–1.7 range | false or inconsistent PDF/A claims; features incompatible with the declared version; header/catalog conflicts accepted by current logic | whether CDE validates PDF/A conformance or only version declaration; header versus Catalog precedence | veraPDF-assisted PDF/A and version-conflict matrix |
| 6.17 | `IMPLEMENTED_SYNTHETIC_UNCALIBRATED` | EmbeddedFiles name tree; Catalog /AF; FileAttachment annotations | embedded payload reachable only through RichMedia or unusual FileSpec graph | whether all associated files are treated identically; reported attachment name/path | name-tree, AF and FileAttachment variants |
| 6.18 | `PARTIAL_HEURISTIC` | page annotation subtype inventory; Link excluded | annotations hidden in malformed page trees | treatment of signature widgets and AcroForm fields; whether annotations are counted after flattening | signature, widget, stamp and highlight subtype matrix |
| 6.19 | `BLOCKED_OFFICIAL_BEHAVIOR` | Encrypt dictionary/pikepdf is_encrypted; empty-user-password encrypted sample | non-encryption document restrictions represented through signatures/DocMDP; permission details not fully decoded | whether encryption alone is sufficient; which permissions are named; relationship and precedence with 6.21 | P0-B2 calibration case 6.19 |
| 6.20 | `PARTIAL_HEURISTIC` | PageMode; PageLayout; OpenAction initial destination and zoom | viewer-preference combinations; named OpenAction; initial-page semantics; document-type-specific expectation | exact accepted value set and conditional logic | official-manual extraction then factorial initial-view matrix |
| 6.21 | `BLOCKED_OFFICIAL_BEHAVIOR` | pikepdf PasswordError on no-password open; PDFium/qpdf independent failure signals | nonstandard handlers accepted by one engine; credential cached externally | whether 6.19 is emitted together; whether subsequent rules are skipped | P0-B2 calibration case 6.21 |
| 6.22 | `BLOCKED_OFFICIAL_BEHAVIOR` | pikepdf/qpdf linearization status on final bytes; explicit node/reference exemptions | stale or partially damaged linearization accepted by library; incremental update after linearization | final structural validation versus marker check; handling of post-linearization incremental updates | P0-B2 calibration case 6.22 and stale-linearization boundary |
| 6.23 | `IMPLEMENTED_CONTEXT_DEPENDENT` | page count >5; outline-tree presence; application/reference/foreign-reference exemptions | empty or entirely invalid outline tree counted as present; node mapping unavailable | whether an invalid outline satisfies presence before other rules fail; exact application-form scope | official mapping workbook import and invalid-outline interaction |
| 6.24 | `PARTIAL_HEURISTIC` | object scan for JavaScript action/keys; 3D, RichMedia, Movie and Sound subtype/key scan | dynamic content hidden in compressed/embedded structures not exposed as inspected dictionaries; XFA events; page/field additional actions not recursively classified | reachability policy; coexistence with 6.4/6.11; XFA handling | reachable/orphaned and action-location matrix |
| 6.25 | `PARTIAL_HEURISTIC` | PDFium text extraction by page; image-XObject count; image page without text | inline images; vector-only scanned-equivalent pages; text that exists but is unusable, invisible or wrong; Form XObject images; partial page OCR gaps | threshold and page aggregation; whether any text is sufficient; OCR quality expectations | rendered nonblank/no-text detector and page-mixture matrix |
| 6.26 | `PARTIAL_HEURISTIC` | page content Tf operator scan; font resource lookup; Base-14 exclusion; FontFile/FontFile2/FontFile3 check | fonts used inside Form XObjects; inherited resources; Type3/internal resources; unusual content tokenization; font descriptor on descendant structures not reached | used resources versus all resources; font name/page reporting; subset and CIDFont handling | P0-B2 calibration case 6.26 then recursive resource/font traversal |

## Cross-cutting priorities

| Priority | Gap | Rules | Required change |
|---|---|---|---|
| `P0-B1-HIGH` | Recursive action graph | 6.3, 6.4, 6.7, 6.10, 6.11, 6.14, 6.24 | Walk /A, /AA, /Next arrays/chains and nested Launch platform dictionaries with cycle protection. |
| `P0-B1-HIGH` | Recursive page resources and Form XObjects | 6.25, 6.26 | Resolve inherited resources, recurse Form XObjects, detect inline images and track actually used fonts. |
| `P0-B1-HIGH` | Official path normalization | 6.2, 6.3, 6.6, 6.9, 6.10, 6.13 | Test URL decoding, fragments, Windows casefold, Unicode normalization, trailing dots/spaces and the official path base. |
| `P0-B1-MEDIUM` | Signature/form safety inventory | 6.18, 6.19, 6.24 | Record signature fields, ByteRange, DocMDP, AcroForm/XFA and prohibit future mutation without separate policy. |
| `P0-B1-MEDIUM` | Per-file worker isolation and resource ceilings | 6.1, 6.21, 6.24, 6.25, 6.26 | Move native parsing/rendering into cancellable worker processes with CPU, memory and file-size limits. |

## Interpretation boundary

- `IMPLEMENTED_SYNTHETIC_UNCALIBRATED` means the synthetic predicate is implemented, not that official behavior is known.
- `IMPLEMENTED_CONTEXT_DEPENDENT` requires a verified node/document-role mapping before a finding is reliable.
- `PARTIAL_HEURISTIC` is intentionally incomplete and must remain visible in reports.
- `BLOCKED_OFFICIAL_BEHAVIOR` requires real V1.1.0 observations before detector semantics can be frozen.
- Official observations remain `0 / NOT_RUN`.
