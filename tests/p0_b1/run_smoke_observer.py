from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from ezctd.catalog import RuleCatalog
from ezctd.models import PdfContext
from ezctd.pdf_observer import ExperimentalPdfObserver

RULEPACK = ROOT / "rulepacks" / "cn-cde-ectd" / "v1.1" / "cde_ectd_pdf_rules_v1.1_verified.json"
MANIFEST = ROOT / "tests" / "p0_b0" / "smoke_manifest.json"
EXPECTATIONS = ROOT / "tests" / "p0_b0" / "smoke_expectations.json"


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_smoke_observer.py <generated-smoke-directory>")
    smoke_dir = Path(sys.argv[1]).resolve()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expectations = {item["case_id"]: item for item in json.loads(EXPECTATIONS.read_text(encoding="utf-8"))["cases"]}
    observer = ExperimentalPdfObserver(RuleCatalog.from_json(RULEPACK))

    records = []
    failures = []
    target_hits = 0
    baseline_findings: list[str] = []
    exemption_findings: list[str] = []
    all_finding_counts: Counter[str] = Counter()

    for case in manifest["cases"]:
        path = smoke_dir / case["file_name"]
        raw_context = case["context"]
        context = PdfContext(
            file_path=path,
            submission_root=smoke_dir,
            node_id=raw_context.get("node_id"),
            document_role=raw_context.get("document_role"),
            language=raw_context.get("language"),
        )
        result = observer.scan(context)
        finding_ids = [finding.rule_id for finding in result.findings]
        all_finding_counts.update(finding_ids)
        expectation = expectations[case["case_id"]]

        if case["case_id"] == "CDE-PDF-BASELINE":
            baseline_findings = finding_ids
            if finding_ids:
                failures.append({"case_id": case["case_id"], "reason": "baseline has findings", "findings": finding_ids})
        elif case["case_id"] == "CDE-PDF-6-23-EXM-REFERENCE":
            exemption_findings = finding_ids
            if "6.23" in finding_ids:
                failures.append({"case_id": case["case_id"], "reason": "6.23 exemption was not applied", "findings": finding_ids})
        else:
            target = case["rule_id"]
            if target in finding_ids:
                target_hits += 1
            else:
                failures.append({"case_id": case["case_id"], "reason": "target rule not detected", "target": target, "findings": finding_ids})

        expected_correlated = set(expectation["expected_correlated_rules"])
        missing_correlated = sorted(expected_correlated - set(finding_ids))
        records.append(
            {
                "case_id": case["case_id"],
                "target_rule": case["rule_id"],
                "isolation_class": expectation["isolation_class"],
                "findings": finding_ids,
                "expected_correlated_missing": missing_correlated,
                "diagnostics": result.diagnostics.to_dict(),
            }
        )

    report = {
        "schema_version": "0.1.0",
        "engine_status": "EXPERIMENTAL_CONTRACT_NOT_CDE_EQUIVALENCE",
        "cases": len(records),
        "target_positive_cases": 26,
        "target_hits": target_hits,
        "baseline_findings": baseline_findings,
        "reference_exemption_findings": exemption_findings,
        "finding_frequency": dict(sorted(all_finding_counts.items(), key=lambda item: int(item[0].split(".")[1]))),
        "failures": failures,
        "records": records,
        "official_validator_observations": 0,
        "official_validator_status": "NOT_RUN",
    }
    output = ROOT / "build" / "p0-b1-observer-report.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ["cases", "target_hits", "baseline_findings", "reference_exemption_findings", "failures"]}, ensure_ascii=False))

    if failures or target_hits != 26 or baseline_findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
