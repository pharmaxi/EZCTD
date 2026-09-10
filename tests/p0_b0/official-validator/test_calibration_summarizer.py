from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PLAN = ROOT / "tests" / "p0_b0" / "official-validator" / "calibration_run_plan.json"
SUMMARIZER = ROOT / "tools" / "cde-validator" / "summarize_calibration_batch.py"
VALIDATOR_HASH = "1" * 64
BASELINE_ID = "baseline-clean-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def target_rule(case_id: str) -> str | None:
    if not case_id.startswith("CDE-PDF-6-"):
        return None
    return f"6.{case_id.split('-')[3]}"


def build_evidence(root: Path) -> None:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    for run in plan["runs"]:
        run_dir = root / run["run_id"]
        reports = run_dir / "reports"
        screenshots = run_dir / "screenshots"
        reports.mkdir(parents=True)
        screenshots.mkdir(parents=True)
        report = reports / "validator-report.txt"
        screenshot = screenshots / "result.png"
        report.write_text(f"synthetic evidence for {run['run_id']}\n", encoding="utf-8")
        screenshot.write_bytes(b"\x89PNG\r\n\x1a\nsynthetic-placeholder")
        rule = target_rule(run["case_id"])
        messages = [] if rule is None else [{"rule_id": rule, "severity": "synthetic", "message": "target observed", "path": "0000/m5/leaf.pdf"}]
        result = {
            "schema_version": "0.1.0",
            "case_id": run["run_id"],
            "source_case_id": run["case_id"],
            "run_role": run["role"],
            "restart_before": run["restart_before"],
            "validator": {"name": "CDE eCTD validation software", "version": "1.1.0", "binary_sha256": VALIDATOR_HASH},
            "input": {"package_inventory_sha256": "2" * 64, "baseline_id": BASELINE_ID},
            "observation": {
                "run_status": "COMPLETED",
                "started_at": "2026-09-03T00:00:00Z",
                "finished_at": "2026-09-03T00:01:00Z",
                "messages": messages,
            },
            "evidence": {
                "report_files": [{"name": report.name, "sha256": sha256(report)}],
                "screenshots": [{"name": screenshot.name, "sha256": sha256(screenshot)}],
            },
            "review": {
                "classification": "CONTROL_PASS" if rule is None else "MATCH",
                "reviewer": "synthetic-self-test",
                "reviewed_at": "2026-09-03T00:02:00Z",
            },
        }
        (run_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_summary(evidence: Path, output: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SUMMARIZER), "--plan", str(PLAN), "--evidence-root", str(evidence), "--output", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def main() -> int:
    results = []
    with tempfile.TemporaryDirectory(prefix="ezctd-calibration-summary-") as td:
        temp = Path(td)
        complete = temp / "complete"
        build_evidence(complete)
        complete_output = temp / "complete-summary.json"
        complete_run = run_summary(complete, complete_output)
        assert complete_run.returncode == 0, complete_run.stderr + complete_run.stdout
        complete_payload = json.loads(complete_output.read_text(encoding="utf-8"))
        assert complete_payload["status"] == "COMPLETE"
        assert complete_payload["run_count"] == 9
        assert complete_payload["target_rules_observed"] == 6
        assert complete_payload["baseline_controls"] == 3
        assert complete_payload["errors"] == []
        results.append({"case": "complete-evidence", "status": complete_payload["status"]})

        missing = temp / "missing-screenshot"
        shutil.copytree(complete, missing)
        missing_file = missing / "CAL01-05-RULE-6-26" / "screenshots" / "result.png"
        missing_file.unlink()
        missing_output = temp / "missing-summary.json"
        missing_run = run_summary(missing, missing_output)
        assert missing_run.returncode == 1
        missing_payload = json.loads(missing_output.read_text(encoding="utf-8"))
        assert missing_payload["status"] == "INCOMPLETE_OR_INVALID"
        assert any("screenshot evidence missing" in error["error"] for error in missing_payload["errors"])
        results.append({"case": "missing-screenshot", "status": missing_payload["status"]})

        contaminated = temp / "baseline-contamination"
        shutil.copytree(complete, contaminated)
        result_path = contaminated / "CAL01-03-BASELINE-MID" / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["observation"]["messages"] = [{"rule_id": "6.22", "severity": "synthetic", "message": "unexpected baseline finding"}]
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        contaminated_output = temp / "contaminated-summary.json"
        contaminated_run = run_summary(contaminated, contaminated_output)
        assert contaminated_run.returncode == 1
        contaminated_payload = json.loads(contaminated_output.read_text(encoding="utf-8"))
        assert any("baseline control emitted" in error["error"] for error in contaminated_payload["errors"])
        results.append({"case": "baseline-contamination", "status": contaminated_payload["status"]})

    report = {"schema_version": "0.1.0", "status": "PASS", "tests": results, "official_observations": 0}
    output = ROOT / "build" / "calibration-summarizer-self-test.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
