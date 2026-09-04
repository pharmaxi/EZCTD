from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inventory(root: Path) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix().lower()):
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


def inventory_digest(records: list[dict[str, Any]]) -> str:
    canonical = "\n".join(
        f"{item['path']}\t{item['size']}\t{item['sha256']}" for item in records
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def replace_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        return
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def copy_selected_logs(application_dir: Path, destination: Path) -> list[dict[str, Any]]:
    destination.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    if not application_dir.exists():
        return records
    candidates = []
    for path in application_dir.rglob("*"):
        if not path.is_file():
            continue
        lower = path.name.lower()
        if lower == "launch4j.log" or lower.endswith((".log", ".txt", ".xml", ".json", ".html")):
            candidates.append(path)
    for path in sorted(candidates, key=lambda item: item.as_posix().lower()):
        relative = path.relative_to(application_dir)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, target)
            records.append(
                {
                    "source": str(path.resolve()),
                    "captured_as": target.relative_to(destination.parent).as_posix(),
                    "size": target.stat().st_size,
                    "sha256": sha256_file(target),
                }
            )
        except OSError as exc:
            records.append(
                {
                    "source": str(path.resolve()),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return records


def normalize_inventory(records: Any) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    normalized = []
    for item in records:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "path": item.get("path"),
                "size": item.get("size"),
                "sha256": item.get("sha256"),
            }
        )
    return sorted(normalized, key=lambda item: str(item.get("path") or "").lower())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transaction", type=Path, required=True)
    parser.add_argument("--report-root", type=Path, required=True)
    parser.add_argument("--application-dir", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    report = read_json(args.transaction)
    if report.get("run_type") != "official_validator_synthetic_transaction":
        raise ValueError("unexpected transaction run_type")

    native_output_dir = args.output_root / "native-output"
    replace_tree(args.report_root, native_output_dir)
    source_inventory = inventory(args.report_root)
    copied_inventory = inventory(native_output_dir)
    source_digest = inventory_digest(source_inventory)
    copied_digest = inventory_digest(copied_inventory)

    application_logs = copy_selected_logs(
        args.application_dir, args.output_root / "application-logs"
    )

    runtime_inventory = normalize_inventory(
        report.get("native_result", {}).get("output_inventory", [])
    )
    copied_matches_runtime = copied_inventory == runtime_inventory
    copied_matches_source = copied_inventory == source_inventory
    copied_native_output_present = bool(copied_inventory)

    terminal_alert = report.get("native_result", {}).get("terminal_alert")
    table_texts = report.get("native_result", {}).get("table_native_texts", [])
    terminal_ui_evidence_present = bool(terminal_alert or table_texts)

    evidence = {
        "schema_version": "0.1.0",
        "source_report_directory": str(args.report_root.resolve()),
        "copied_report_directory": native_output_dir.relative_to(args.output_root).as_posix(),
        "source_inventory": source_inventory,
        "source_inventory_digest": source_digest,
        "copied_inventory": copied_inventory,
        "copied_inventory_digest": copied_digest,
        "copied_matches_source": copied_matches_source,
        "copied_matches_runtime_inventory": copied_matches_runtime,
        "copied_native_output_present": copied_native_output_present,
        "terminal_ui_evidence_present": terminal_ui_evidence_present,
        "application_logs": application_logs,
    }
    write_json(args.output_root / "native-evidence-finalization.json", evidence)

    admissibility = report.setdefault("admissibility", {})
    admissibility["native_output_conserved_in_artifact"] = (
        copied_native_output_present
        and copied_matches_source
        and copied_matches_runtime
    )
    admissibility["terminal_ui_evidence_conserved_in_artifact"] = (
        terminal_ui_evidence_present
        and (args.output_root / "05-terminal.json").exists()
        and (args.output_root / "05-terminal.png").exists()
    )
    admissibility["native_evidence_conserved"] = bool(
        admissibility["native_output_conserved_in_artifact"]
        or admissibility["terminal_ui_evidence_conserved_in_artifact"]
    )

    prerequisites = [
        bool(admissibility.get("official_binary_identity_fixed")),
        bool(admissibility.get("input_identity_fixed")),
        bool(admissibility.get("validation_control_invoked")),
        bool(admissibility.get("native_terminal_result_captured")),
        not bool(admissibility.get("precondition_only_result")),
        bool(admissibility.get("input_unchanged")),
        bool(admissibility.get("outbound_firewall_ready")),
        bool(admissibility.get("native_evidence_conserved")),
    ]
    admissible = all(prerequisites)
    report["native_evidence"] = evidence
    report["admissible_official_black_box_observation"] = admissible

    counters = report.setdefault("observation_counters", {})
    if admissible:
        report["status"] = "ADMISSIBLE_ENVIRONMENT_ADAPTED_OFFICIAL_OBSERVATION"
        counters.update(
            {
                "completed_validation_runs": 1,
                "admissible_black_box_observations": 1,
                "environment_adapted_official_observations": 1,
                "stock_environment_official_observations": 0,
                "calibration_informative_observations": 0,
                "official_black_box_observations": 1,
            }
        )
        report["next_gate"] = (
            "Repeat the same frozen case to test stability, then build a minimal sequence baseline before rule-specific mutations."
        )
    else:
        report["status"] = "SYNTHETIC_TRANSACTION_NOT_ADMISSIBLE_AFTER_EVIDENCE_FINALIZATION"
        counters.update(
            {
                "completed_validation_runs": 0,
                "admissible_black_box_observations": 0,
                "environment_adapted_official_observations": 0,
                "stock_environment_official_observations": 0,
                "calibration_informative_observations": 0,
                "official_black_box_observations": 0,
            }
        )
        failed = [
            key
            for key, value in (
                ("official_binary_identity_fixed", admissibility.get("official_binary_identity_fixed")),
                ("input_identity_fixed", admissibility.get("input_identity_fixed")),
                ("validation_control_invoked", admissibility.get("validation_control_invoked")),
                ("native_terminal_result_captured", admissibility.get("native_terminal_result_captured")),
                ("not_precondition_only", not admissibility.get("precondition_only_result")),
                ("input_unchanged", admissibility.get("input_unchanged")),
                ("outbound_firewall_ready", admissibility.get("outbound_firewall_ready")),
                ("native_evidence_conserved", admissibility.get("native_evidence_conserved")),
            )
            if not bool(value)
        ]
        report["failed_admissibility_gates"] = failed
        report["next_gate"] = (
            "Repair only the failed admissibility gates using the preserved raw evidence; do not increment counters."
        )

    report.setdefault("assertions", {})[
        "official_black_box_observation_count"
    ] = counters["official_black_box_observations"]
    write_json(args.transaction, report)

    summary = {
        "run_id": report.get("run_id"),
        "case_id": report.get("case_id"),
        "status": report.get("status"),
        "validation_invoked": report.get("validation_invoked", False),
        "terminal_reason": report.get("native_result", {}).get("terminal_reason"),
        "native_report_present": report.get("native_result", {}).get("native_report_present", False),
        "native_output_conserved": admissibility.get("native_output_conserved_in_artifact"),
        "terminal_ui_evidence_conserved": admissibility.get("terminal_ui_evidence_conserved_in_artifact"),
        "input_unchanged": report.get("input", {}).get("unchanged", False),
        "admissible": admissible,
        "failed_admissibility_gates": report.get("failed_admissibility_gates", []),
        "observation_counters": counters,
        "next_gate": report.get("next_gate"),
    }
    write_json(args.output_root / "FINALIZED_TRANSACTION_SUMMARY.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
