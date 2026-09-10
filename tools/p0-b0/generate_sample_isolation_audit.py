from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests" / "p0_b0" / "smoke_manifest.json"
OUT_JSON = ROOT / "tests" / "p0_b0" / "smoke_expectations.json"
OUT_MD = ROOT / "docs" / "validation" / "p0-b0" / "SAMPLE_ISOLATION_AUDIT.md"

POLICY = {
    "6.1": ("ISOLATED", [], "Malformed minimal PDF should stop PDF-level inspection; boundary recovery cases are separate."),
    "6.2": ("NEEDS_DYNAMIC_ENVIRONMENT", ["6.6"], "The fixed absolute-path target is intentionally absent. A true isolated experiment must create an existing absolute target on the Windows validation host."),
    "6.3": ("CORRELATED_BY_CURRENT_ENCODING", ["6.4"], "The smoke fixture uses a URI action. URI is both external and outside the official allowed action set GoTo/GoToR/Launch."),
    "6.4": ("CORRELATED_BY_DEFINITION", ["6.24"], "The fixture uses JavaScript; JavaScript is also prohibited dynamic content under 6.24."),
    "6.5": ("ISOLATED", [], "Bookmark exists but has neither destination nor action."),
    "6.6": ("ISOLATED", [], "A syntactically valid relative GoToR target is missing."),
    "6.7": ("ISOLATED", [], "Both actions are allowed GoTo actions; the target defect is the /Next chain."),
    "6.8": ("ISOLATED", [], "Valid internal bookmark target with numeric /XYZ zoom."),
    "6.9": ("NEEDS_DYNAMIC_ENVIRONMENT", ["6.13"], "The fixed absolute-path target is intentionally absent. Isolated testing requires an existing absolute target on the validation host."),
    "6.10": ("CORRELATED_BY_CURRENT_ENCODING", ["6.11"], "The smoke fixture uses a URI action, which is both external and outside GoTo/GoToR/Launch."),
    "6.11": ("CORRELATED_BY_DEFINITION", ["6.24"], "The fixture uses JavaScript; JavaScript is also dynamic content under 6.24."),
    "6.12": ("ISOLATED", [], "Link annotation exists but has neither destination nor action."),
    "6.13": ("ISOLATED", [], "A syntactically valid relative GoToR target is missing."),
    "6.14": ("ISOLATED", [], "Both actions are allowed GoTo actions; the target defect is the /Next chain."),
    "6.15": ("ISOLATED", [], "Valid internal link target with numeric /XYZ zoom."),
    "6.16": ("ISOLATED", [], "Readable searchable PDF using disallowed PDF 1.3 header/version."),
    "6.17": ("ISOLATED", [], "EmbeddedFiles name tree is used without a FileAttachment annotation."),
    "6.18": ("ISOLATED", [], "Text annotation is present without an embedded file or dynamic action."),
    "6.19": ("ISOLATED_WITHIN_CURRENT_HYPOTHESIS", [], "Encrypted with empty user password and restricted permissions; expected to open without triggering 6.21, subject to official observation."),
    "6.20": ("ISOLATED", [], "Bookmark is valid; only PageMode, PageLayout and OpenAction are non-default."),
    "6.21": ("CORRELATED_BY_DEFINITION", ["6.19"], "A non-empty user password is also a security setting. Official software may emit both rules or suppress one."),
    "6.22": ("ISOLATED", [], "Valid final PDF bytes are intentionally not linearized."),
    "6.23": ("ISOLATED", [], "Six-page non-exempt PDF has no outline tree."),
    "6.24": ("ISOLATED", [], "Document-level JavaScript name tree is used; no bookmark or link action refers to it."),
    "6.25": ("ISOLATED", [], "One-page image-only PDF contains no PDF text object."),
    "6.26": ("ISOLATED", [], "A used non-Base-14 Type1 font has no embedded font program."),
}


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    cases = []
    for case in manifest["cases"]:
        rule_id = case.get("rule_id")
        if rule_id is None:
            classification, correlated, rationale = "CONTROL", [], "Known-good synthetic PDF control for the implemented smoke predicates."
        elif case["case_id"] == "CDE-PDF-6-23-EXM-REFERENCE":
            classification, correlated, rationale = "CONTEXT_DIFFERENTIAL", [], "Same structural condition as 6.23 positive, placed in a declared reference-document exemption context."
        else:
            classification, correlated, rationale = POLICY[rule_id]
        cases.append({
            "case_id": case["case_id"],
            "rule_id": rule_id,
            "fixture_role": "target-positive" if case.get("variant") == "violation" else case.get("variant"),
            "isolation_class": classification,
            "expected_correlated_rules": correlated,
            "rationale": rationale,
            "official_observation": "NOT_RUN",
            "may_emit_additional_unknown_rules": True,
        })

    counts: dict[str, int] = {}
    for case in cases:
        counts[case["isolation_class"]] = counts.get(case["isolation_class"], 0) + 1
    payload = {
        "schema_version": "0.1.0",
        "purpose": "Distinguish target-rule coverage from single-rule isolation before CDE V1.1.0 black-box testing.",
        "terminology": {
            "target_positive": "The target rule condition is deliberately present.",
            "isolated": "No other official rule is expected from the same mutation under the current interpretation.",
            "correlated": "The same PDF object or security state legitimately satisfies more than one official rule predicate.",
        },
        "counts": counts,
        "cases": cases,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# P0-B0 smoke sample isolation audit",
        "",
        "> The 26 positive PDFs are **target-rule-positive smoke fixtures**, not a promise of one-and-only-one official finding. CDE V1.1.0 observations remain `NOT_RUN`.",
        "",
        "## Why this distinction matters",
        "",
        "PDF rules overlap at the object and security layers. A URI bookmark is an external link and an action outside GoTo/GoToR/Launch; JavaScript in a bookmark is also dynamic content; password protection is also a security setting. Treating these as single-rule expected outputs would create false failures or encourage artificial samples that no longer represent the official wording.",
        "",
        "## Counts",
        "",
    ]
    for key, value in sorted(counts.items()):
        lines.append(f"- `{key}`: {value}")
    lines += [
        "",
        "## Case-level audit",
        "",
        "| Case | Target | Isolation | Expected correlated rules | Reason |",
        "|---|---|---|---|---|",
    ]
    for case in cases:
        correlated = ", ".join(case["expected_correlated_rules"]) or "—"
        reason = case["rationale"].replace("|", "\\|")
        lines.append(f"| `{case['case_id']}` | {case['rule_id'] or 'control'} | `{case['isolation_class']}` | {correlated} | {reason} |")
    lines += [
        "",
        "## Required isolated follow-up experiments",
        "",
        "1. **6.2/6.9 absolute path:** create an existing target at a controlled absolute Windows path, inject that path at run time, and prove that only path relativity—not target damage—is under test.",
        "2. **6.3/6.10 external link:** compare URI, mailto, Launch and GoToR encodings to observe whether official software emits both external-link and unknown-action messages.",
        "3. **6.4/6.11 vs 6.24:** compare JavaScript in outline/link action, document name tree, OpenAction and field additional actions.",
        "4. **6.19/6.21:** test unencrypted, empty-user-password encrypted, non-empty-user-password encrypted and owner-password-only states to map message coexistence and precedence.",
        "",
    ]
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    if len(cases) != 28:
        raise SystemExit(f"expected 28 audited fixtures, got {len(cases)}")
    if set(POLICY) != {f"6.{i}" for i in range(1, 27)}:
        raise SystemExit("isolation policy does not cover all 26 rules")
    print(json.dumps({"status": "PASS", "cases": 28, "counts": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
