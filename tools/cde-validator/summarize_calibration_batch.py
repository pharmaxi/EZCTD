from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def evidence_file_ok(run_dir: Path, item: Any) -> tuple[bool, str]:
    if isinstance(item, str):
        path = run_dir / item
        return path.is_file(), f"missing: {item}"
    if not isinstance(item, dict) or not item.get("name"):
        return False, "evidence item lacks name"
    path = run_dir / item["name"]
    if not path.is_file():
        # Finalize-OfficialRun stores bare names while files reside in reports/ or screenshots/.
        for folder in ("reports", "screenshots"):
            candidate = run_dir / folder / item["name"]
            if candidate.is_file():
                path = candidate
                break
    if not path.is_file():
        return False, f"missing: {item['name']}"
    expected = item.get("sha256")
    if expected and sha256(path) != expected.lower():
        return False, f"hash mismatch: {item['name']}"
    return True, "ok"


def normalize_rule_id(message: dict[str, Any]) -> str | None:
    raw = message.get("rule_id") or message.get("ruleId") or message.get("code")
    if raw is None:
        return None
    text = str(raw).strip()
    if text.startswith("PDF-"):
        text = text[4:]
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=Path("tests/p0_b0/official-validator/calibration_run_plan.json"))
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    plan = load_json(args.plan)
    planned = {item["run_id"]: item for item in plan["runs"]}
    errors: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    binary_hashes: set[str] = set()
    baseline_ids: set[str] = set()
    message_counts: Counter[str] = Counter()
    severity_counts: Counter[str] = Counter()
    target_outcomes: dict[str, dict[str, Any]] = {}

    for run_id, planned_run in planned.items():
        run_dir = args.evidence_root / run_id
        result_path = run_dir / "result.json"
        if not result_path.is_file():
            errors.append({"run_id": run_id, "error": "result.json missing"})
            continue
        result = load_json(result_path)
        if result.get("case_id") != run_id:
            errors.append({"run_id": run_id, "error": "case_id does not match run_id"})
        if result.get("source_case_id") != planned_run["case_id"]:
            errors.append({"run_id": run_id, "error": "source_case_id does not match plan"})
        validator = result.get("validator") or {}
        if validator.get("version") != "1.1.0":
            errors.append({"run_id": run_id, "error": f"unexpected validator version: {validator.get('version')}"})
        binary_hash = validator.get("binary_sha256")
        if not binary_hash:
            errors.append({"run_id": run_id, "error": "validator binary SHA-256 missing"})
        else:
            binary_hashes.add(binary_hash.lower())
        input_info = result.get("input") or {}
        if not input_info.get("package_inventory_sha256"):
            errors.append({"run_id": run_id, "error": "package inventory SHA-256 missing"})
        baseline_id = input_info.get("baseline_id")
        if not baseline_id:
            errors.append({"run_id": run_id, "error": "baseline_id missing"})
        else:
            baseline_ids.add(str(baseline_id))
        observation = result.get("observation") or {}
        if observation.get("run_status") not in {"COMPLETED", "COMPLETED_WITH_APPLICATION_ERROR"}:
            errors.append({"run_id": run_id, "error": f"run_status not final: {observation.get('run_status')}"})
        if not observation.get("started_at") or not observation.get("finished_at"):
            errors.append({"run_id": run_id, "error": "run timestamps incomplete"})
        review = result.get("review") or {}
        if review.get("classification") not in {"MATCH", "PARTIAL", "OFFICIAL_ONLY", "EZCTD_ONLY", "INCONCLUSIVE", "CONTROL_PASS", "CONTROL_FAIL"}:
            errors.append({"run_id": run_id, "error": f"invalid review classification: {review.get('classification')}"})
        if not review.get("reviewer") or not review.get("reviewed_at"):
            errors.append({"run_id": run_id, "error": "reviewer or reviewed_at missing"})

        reports = (result.get("evidence") or {}).get("report_files") or []
        screenshots = (result.get("evidence") or {}).get("screenshots") or []
        if not reports:
            errors.append({"run_id": run_id, "error": "no original report evidence"})
        if not screenshots:
            errors.append({"run_id": run_id, "error": "no screenshot evidence"})
        for kind, items in (("report", reports), ("screenshot", screenshots)):
            for item in items:
                ok, detail = evidence_file_ok(run_dir, item)
                if not ok:
                    errors.append({"run_id": run_id, "error": f"{kind} evidence {detail}"})

        messages = observation.get("messages") or []
        normalized_messages = []
        for message in messages:
            if not isinstance(message, dict):
                errors.append({"run_id": run_id, "error": "message is not an object"})
                continue
            rule_id = normalize_rule_id(message)
            severity = str(message.get("severity") or message.get("level") or "UNSPECIFIED")
            if rule_id:
                message_counts[rule_id] += 1
            severity_counts[severity] += 1
            normalized_messages.append({
                "rule_id": rule_id,
                "severity": severity,
                "message": message.get("message") or message.get("text"),
                "path": message.get("path") or message.get("file"),
                "object": message.get("object") or message.get("location"),
                "blocking": message.get("blocking"),
                "raw": message,
            })

        target_rule = None
        source_case_id = planned_run["case_id"]
        if source_case_id.startswith("CDE-PDF-6-"):
            parts = source_case_id.split("-")
            target_rule = f"6.{parts[3]}"
        target_present = target_rule in {item["rule_id"] for item in normalized_messages} if target_rule else None
        if target_rule:
            target_outcomes[run_id] = {"target_rule": target_rule, "target_present": target_present, "messages": normalized_messages}
        runs.append({
            "run_id": run_id,
            "case_id": source_case_id,
            "role": planned_run["role"],
            "restart_before": planned_run["restart_before"],
            "run_status": observation.get("run_status"),
            "review_classification": review.get("classification"),
            "target_rule": target_rule,
            "target_present": target_present,
            "messages": normalized_messages,
            "result_sha256": sha256(result_path),
        })

    if len(runs) != plan["expected_run_count"]:
        errors.append({"error": f"expected {plan['expected_run_count']} complete result files, loaded {len(runs)}"})
    if len(binary_hashes) > 1:
        errors.append({"error": f"multiple validator binary hashes used: {sorted(binary_hashes)}"})
    if len(baseline_ids) > 1:
        errors.append({"error": f"multiple baseline IDs used: {sorted(baseline_ids)}"})

    baseline_runs = [run for run in runs if run["case_id"] == "CDE-PDF-BASELINE"]
    if len(baseline_runs) != 3:
        errors.append({"error": f"expected three baseline controls, got {len(baseline_runs)}"})
    baseline_rule6_messages = {
        run["run_id"]: [message for message in run["messages"] if (message.get("rule_id") or "").startswith("6.")]
        for run in baseline_runs
    }
    for run_id, messages in baseline_rule6_messages.items():
        if messages:
            errors.append({"run_id": run_id, "error": "baseline control emitted one or more section-6 messages", "messages": messages})

    missing_targets = [run_id for run_id, outcome in target_outcomes.items() if not outcome["target_present"]]
    for run_id in missing_targets:
        errors.append({"run_id": run_id, "error": f"target rule {target_outcomes[run_id]['target_rule']} not observed"})

    security_relationship = None
    by_case = {run["case_id"]: run for run in runs}
    if "CDE-PDF-6-19-POS" in by_case and "CDE-PDF-6-21-POS" in by_case:
        r19 = {message["rule_id"] for message in by_case["CDE-PDF-6-19-POS"]["messages"]}
        r21 = {message["rule_id"] for message in by_case["CDE-PDF-6-21-POS"]["messages"]}
        security_relationship = {
            "empty_user_password_restricted_permissions": sorted(rule for rule in r19 if rule),
            "non_empty_user_password": sorted(rule for rule in r21 if rule),
            "observed_6_19_without_6_21": "6.19" in r19 and "6.21" not in r19,
            "observed_6_19_and_6_21_together": "6.19" in r21 and "6.21" in r21,
        }

    status = "COMPLETE" if not errors else "INCOMPLETE_OR_INVALID"
    payload = {
        "schema_version": "0.1.0",
        "batch_id": plan["batch_id"],
        "status": status,
        "validator_version": "1.1.0",
        "validator_binary_sha256": next(iter(binary_hashes)) if len(binary_hashes) == 1 else None,
        "baseline_id": next(iter(baseline_ids)) if len(baseline_ids) == 1 else None,
        "run_count": len(runs),
        "target_positive_runs": len(target_outcomes),
        "target_rules_observed": sum(bool(value["target_present"]) for value in target_outcomes.values()),
        "baseline_controls": len(baseline_runs),
        "baseline_section6_messages": baseline_rule6_messages,
        "security_relationship": security_relationship,
        "message_counts_by_rule": dict(sorted(message_counts.items())),
        "severity_counts": dict(severity_counts),
        "errors": errors,
        "runs": runs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# CDE V1.1.0 calibration batch 01 summary",
        "",
        f"- Status: **{status}**",
        f"- Runs loaded: {len(runs)}/{plan['expected_run_count']}",
        f"- Target rules observed: {payload['target_rules_observed']}/{len(target_outcomes)}",
        f"- Baseline controls: {len(baseline_runs)}/3",
        f"- Validator binary SHA-256: `{payload['validator_binary_sha256'] or 'unresolved'}`",
        f"- Baseline ID: `{payload['baseline_id'] or 'unresolved'}`",
        "",
        "## Run outcomes",
        "",
        "| Run | Source case | Role | Target | Observed | Review |",
        "|---|---|---|---|---:|---|",
    ]
    for run in runs:
        lines.append(
            f"| `{run['run_id']}` | `{run['case_id']}` | {run['role']} | {run['target_rule'] or 'control'} | "
            f"{run['target_present'] if run['target_present'] is not None else 'n/a'} | {run['review_classification']} |"
        )
    lines += ["", "## Validation errors", ""]
    if errors:
        for error in errors:
            lines.append(f"- `{error.get('run_id', 'batch')}`: {error['error']}")
    else:
        lines.append("- None.")
    lines += [
        "",
        "A `COMPLETE` result means the evidence package is internally complete and all six target rules were observed while three baseline controls remained free of section-6 findings. It does not by itself prove the remaining 20 rules or all boundary conditions.",
        "",
    ]
    args.output.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": status, "errors": len(errors), "runs": len(runs), "targets_observed": payload["target_rules_observed"]}, ensure_ascii=False))
    return 0 if status == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
