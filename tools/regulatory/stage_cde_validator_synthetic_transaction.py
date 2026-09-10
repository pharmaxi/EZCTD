from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def bounded_summary(
    report: dict[str, Any],
    *,
    workflow_run_id: int,
    workflow_run_attempt: int,
    artifact_id: str,
    artifact_url: str,
    artifact_digest: str,
) -> dict[str, Any]:
    require(
        report.get("run_type") == "official_validator_synthetic_transaction",
        "unexpected run_type",
    )
    counters = report.get("observation_counters", {})
    admissible = bool(report.get("admissible_official_black_box_observation"))
    admissibility = report.get("admissibility", {})
    native_evidence = report.get("native_evidence", {})
    identity = report.get("identity", {})
    adaptation = report.get("environment_adaptation", {})

    expected_count = 1 if admissible else 0
    require(
        counters.get("official_black_box_observations") == expected_count,
        "official observation counter is inconsistent with admissibility",
    )
    require(
        counters.get("admissible_black_box_observations") == expected_count,
        "admissible counter is inconsistent with admissibility",
    )
    require(
        counters.get("completed_validation_runs") == expected_count,
        "completed-validation counter is inconsistent with admissibility",
    )
    require(
        counters.get("stock_environment_official_observations") == 0,
        "this workflow must not claim stock-environment equivalence",
    )
    require(
        counters.get("calibration_informative_observations") == 0,
        "the empty-root transaction cannot count as rule calibration",
    )

    if admissible:
        required_gates = [
            "official_binary_identity_fixed",
            "input_identity_fixed",
            "validation_control_invoked",
            "native_terminal_result_captured",
            "input_unchanged",
            "outbound_firewall_ready",
            "native_evidence_conserved",
        ]
        for gate in required_gates:
            require(admissibility.get(gate) is True, f"admissible run missing gate: {gate}")
        require(
            admissibility.get("precondition_only_result") is False,
            "precondition-only UI response cannot count as validation",
        )
        require(
            adaptation.get("type") == "byte_identical_ascii_ntfs_alias",
            "unexpected environment adaptation",
        )
        require(
            adaptation.get("stock_environment_equivalent") is False,
            "ASCII alias run must remain explicitly non-equivalent to stock environment",
        )
        require(identity.get("byte_identical") is True, "official binary bytes not conserved")
        require(
            native_evidence.get("copied_matches_source") is True
            or native_evidence.get("terminal_ui_evidence_present") is True,
            "native evidence was not conserved",
        )

    native_result = report.get("native_result", {})
    input_record = report.get("input", {})
    terminal_alert = native_result.get("terminal_alert")
    terminal_alert_summary = None
    if isinstance(terminal_alert, dict):
        terminal_alert_summary = {
            "at": terminal_alert.get("at"),
            "sample": terminal_alert.get("sample"),
            "texts": terminal_alert.get("texts", []),
            "handling": terminal_alert.get("handling"),
            "window": {
                key: terminal_alert.get("snapshot", {}).get(key)
                for key in (
                    "handle",
                    "pid",
                    "name",
                    "automation_id",
                    "control_type",
                    "class_name",
                    "visible",
                    "enabled",
                    "descendant_count",
                )
            },
        }

    return {
        "schema_version": "0.1.0",
        "run_id": report.get("run_id"),
        "case_id": report.get("case_id"),
        "profile": report.get("profile"),
        "status": report.get("status"),
        "started_at": report.get("started_at"),
        "finished_at": report.get("finished_at"),
        "admissible": admissible,
        "classification": (
            "environment_adapted_official_binary_black_box_observation"
            if admissible
            else "non_admissible_official_validator_transaction_attempt"
        ),
        "environment_adaptation": adaptation,
        "identity": identity,
        "input": {
            "directory": input_record.get("directory"),
            "inventory_digest_before": input_record.get("inventory_digest_before"),
            "inventory_digest_after": input_record.get("inventory_digest_after"),
            "expected_inventory_digest": input_record.get("expected_inventory_digest"),
            "file_count_before": len(input_record.get("inventory_before", [])),
            "file_count_after": len(input_record.get("inventory_after", [])),
            "unchanged": input_record.get("unchanged"),
        },
        "ui_transaction": {
            "validation_invoked": report.get("validation_invoked", False),
            "validation_click_at": report.get("validation_click_at"),
            "input_selection": report.get("input_selection"),
            "report_selection": report.get("report_selection"),
            "action_trace": report.get("action_trace", []),
        },
        "native_result": {
            "terminal_reason": native_result.get("terminal_reason"),
            "terminal_alert": terminal_alert_summary,
            "table_native_texts": native_result.get("table_native_texts", []),
            "native_report_present": native_result.get("native_report_present", False),
            "output_inventory": native_result.get("output_inventory", []),
            "output_digest": native_result.get("output_digest"),
        },
        "native_evidence": native_evidence,
        "admissibility": admissibility,
        "failed_admissibility_gates": report.get("failed_admissibility_gates", []),
        "observation_counters": counters,
        "errors": report.get("errors", []),
        "next_gate": report.get("next_gate"),
        "raw_evidence": {
            "workflow_run_id": workflow_run_id,
            "workflow_run_attempt": workflow_run_attempt,
            "artifact_id": artifact_id,
            "artifact_url": artifact_url,
            "artifact_digest": artifact_digest,
            "retention_days": 90,
        },
        "boundary": (
            "This result uses byte-identical official application bytes through an ASCII NTFS alias to work around "
            "Launch4j filename encoding on the hosted non-Chinese Windows runner. It is an official-binary black-box "
            "observation when admissible, but it is not evidence of stock-environment parity and is not yet a rule-calibration observation."
        ),
    }


def render_observation(summary: dict[str, Any]) -> str:
    counters = summary["observation_counters"]
    native = summary["native_result"]
    lines = [
        "# CDE eCTD 官方验证器：合成输入事务",
        "",
        f"- 运行：`{summary['run_id']}`",
        f"- Case：`{summary['case_id']}`",
        f"- 状态：**{summary['status']}**",
        f"- 分类：`{summary['classification']}`",
        f"- 实际点击“启动验证”：**{summary['ui_transaction']['validation_invoked']}**",
        f"- 原生终态：`{native.get('terminal_reason')}`",
        f"- 原生报告：**{native.get('native_report_present')}**",
        f"- 输入未变化：**{summary['input'].get('unchanged')}**",
        f"- 证据已保存：**{summary['admissibility'].get('native_evidence_conserved')}**",
        f"- 本次可采信：**{summary['admissible']}**",
        f"- `official_black_box_observations`：**{counters.get('official_black_box_observations')}**",
        f"- `calibration_informative_observations`：**{counters.get('calibration_informative_observations')}**",
        "",
        "## 原生消息",
        "",
    ]
    alert = native.get("terminal_alert")
    if alert and alert.get("texts"):
        for text in alert["texts"]:
            lines.append(f"- {text}")
    elif native.get("table_native_texts"):
        for text in native["table_native_texts"]:
            lines.append(f"- {text}")
    elif native.get("output_inventory"):
        lines.append("- 原生输出文件已生成，详见 Actions artifact 中 `native-output/`。")
    else:
        lines.append("- 未捕获可解释的原生结果。")

    lines += [
        "",
        "## 适用边界",
        "",
        "该运行使用与官方应用同一 NTFS 文件、同一 SHA-256 的 ASCII 别名，以规避非中文 Windows runner 对 Launch4j 中文文件名的编码破坏。它不证明未经适配的默认环境可正常运行，也不构成具体 6.x 规则校准。",
        "",
        "## 下一门槛",
        "",
        str(summary.get("next_gate") or "复核原始证据。"),
        "",
        "## 原始证据",
        "",
        f"- Workflow run：`{summary['raw_evidence']['workflow_run_id']}`",
        f"- Artifact ID：`{summary['raw_evidence']['artifact_id']}`",
        f"- Artifact digest：`{summary['raw_evidence']['artifact_digest']}`",
        "- Retention：90 days",
        "",
    ]
    return "\n".join(lines)


def normalized_attempt(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": summary.get("run_id"),
        "case_id": summary.get("case_id"),
        "status": summary.get("status"),
        "classification": summary.get("classification"),
        "admissible": summary.get("admissible"),
        "completed_validation_runs": summary.get("observation_counters", {}).get(
            "completed_validation_runs", 0
        ),
        "official_black_box_observations": summary.get("observation_counters", {}).get(
            "official_black_box_observations", 0
        ),
        "environment_adapted_official_observations": summary.get(
            "observation_counters", {}
        ).get("environment_adapted_official_observations", 0),
        "stock_environment_official_observations": summary.get(
            "observation_counters", {}
        ).get("stock_environment_official_observations", 0),
        "calibration_informative_observations": summary.get(
            "observation_counters", {}
        ).get("calibration_informative_observations", 0),
        "terminal_reason": summary.get("native_result", {}).get("terminal_reason"),
        "native_report_present": summary.get("native_result", {}).get(
            "native_report_present", False
        ),
        "input_unchanged": summary.get("input", {}).get("unchanged"),
        "failed_admissibility_gates": summary.get("failed_admissibility_gates", []),
        "raw_evidence": summary.get("raw_evidence"),
    }


def update_status(status: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    attempts = status.get("official_validator_transaction_attempts", [])
    if not isinstance(attempts, list):
        attempts = []
    attempt = normalized_attempt(summary)
    by_run_id = {
        str(item.get("run_id")): item
        for item in attempts
        if isinstance(item, dict) and item.get("run_id")
    }
    by_run_id[str(attempt["run_id"])] = attempt
    attempts = sorted(by_run_id.values(), key=lambda item: str(item.get("run_id")))

    status.update(
        {
            "schema_version": "0.7.0",
            "status": summary.get("status"),
            "official_validator_transaction_attempts": attempts,
            "transaction_attempt_count": len(attempts),
            "completed_validation_runs": sum(
                int(item.get("completed_validation_runs") or 0) for item in attempts
            ),
            "admissible_black_box_observations": sum(
                1 for item in attempts if item.get("admissible") is True
            ),
            "environment_adapted_official_observations": sum(
                int(item.get("environment_adapted_official_observations") or 0)
                for item in attempts
            ),
            "stock_environment_official_observations": sum(
                int(item.get("stock_environment_official_observations") or 0)
                for item in attempts
            ),
            "calibration_informative_observations": sum(
                int(item.get("calibration_informative_observations") or 0)
                for item in attempts
            ),
            "official_black_box_observations": sum(
                int(item.get("official_black_box_observations") or 0)
                for item in attempts
            ),
            "latest_official_validator_transaction": attempt,
            "next_gate": summary.get("next_gate"),
            "boundary": summary.get("boundary"),
        }
    )
    return status


def render_status(status: dict[str, Any]) -> str:
    latest = status.get("latest_official_validator_transaction", {})
    lines = [
        "# CDE eCTD 官方验证器黑盒状态",
        "",
        f"- 当前状态：**{status.get('status')}**",
        f"- 验证事务尝试：**{status.get('transaction_attempt_count', 0)}**",
        f"- 完整验证运行：**{status.get('completed_validation_runs', 0)}**",
        f"- 可采信黑盒观察：**{status.get('admissible_black_box_observations', 0)}**",
        f"- 环境适配的官方二进制观察：**{status.get('environment_adapted_official_observations', 0)}**",
        f"- 默认环境观察：**{status.get('stock_environment_official_observations', 0)}**",
        f"- 规则校准观察：**{status.get('calibration_informative_observations', 0)}**",
        f"- `official_black_box_observations`：**{status.get('official_black_box_observations', 0)}**",
        "",
        "## 最近一次事务",
        "",
        f"- 运行：`{latest.get('run_id')}`",
        f"- Case：`{latest.get('case_id')}`",
        f"- 分类：`{latest.get('classification')}`",
        f"- 可采信：`{latest.get('admissible')}`",
        f"- 原生终态：`{latest.get('terminal_reason')}`",
        f"- 原生报告：`{latest.get('native_report_present')}`",
        f"- 输入未变化：`{latest.get('input_unchanged')}`",
        "",
        "## 当前解释",
        "",
        "`official_black_box_observations` 只统计满足证据合同的完整事务。环境适配观察使用官方原始字节，但通过 ASCII NTFS 别名规避 runner 编码缺陷；因此单独统计，不能冒充默认环境兼容性，也不能直接当作具体规则校准结果。",
        "",
        "## 下一门槛",
        "",
        str(status.get("next_gate") or "复核原始证据。"),
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transaction", type=Path, required=True)
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--workflow-run-attempt", type=int, required=True)
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--artifact-url", required=True)
    parser.add_argument("--artifact-digest", required=True)
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path("evidence/regulatory/snapshots/cde-validator-v1.1.0"),
    )
    parser.add_argument("--status-root", type=Path, default=Path("docs/status"))
    args = parser.parse_args()

    report = read_json(args.transaction)
    summary = bounded_summary(
        report,
        workflow_run_id=args.workflow_run_id,
        workflow_run_attempt=args.workflow_run_attempt,
        artifact_id=args.artifact_id,
        artifact_url=args.artifact_url,
        artifact_digest=args.artifact_digest,
    )

    evidence_dir = args.evidence_root / "black-box-observations"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    run_id = summary.get("run_id") or f"workflow-{args.workflow_run_id}"
    write_json(evidence_dir / f"{run_id}.summary.json", summary)
    (evidence_dir / f"{run_id}.md").write_text(
        render_observation(summary), encoding="utf-8"
    )

    status_path = args.evidence_root / "STATUS.json"
    status = read_json(status_path) if status_path.exists() else {}
    status = update_status(status, summary)
    write_json(status_path, status)
    write_json(args.status_root / "OFFICIAL_VALIDATOR_BLACK_BOX_STATUS.json", status)
    (args.status_root / "OFFICIAL_VALIDATOR_BLACK_BOX_STATUS.md").write_text(
        render_status(status), encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
