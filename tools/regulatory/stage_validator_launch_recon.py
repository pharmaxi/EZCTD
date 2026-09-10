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
    data: dict[str, Any],
    *,
    workflow_run_id: int,
    workflow_run_attempt: int,
    artifact_id: str,
    artifact_url: str,
    artifact_digest: str,
) -> dict[str, Any]:
    require(data.get("run_type") == "launch_reconnaissance", "unexpected run_type")
    require(data.get("execution_mode") == "direct_static_payload_no_installer", "unexpected execution_mode")

    assertions = data.get("assertions", {})
    counters = data.get("observation_counters", {})
    require(assertions.get("validation_invoked") is False, "launch recon must not invoke validation")
    require(assertions.get("native_validation_report_present") is False, "launch recon must not claim native report")
    require(counters.get("completed_validation_runs") == 0, "launch recon cannot count as completed validation")
    require(counters.get("official_black_box_observations") == 0, "launch recon cannot count as black-box observation")

    execution = data.get("execution", {})
    side_effects = data.get("side_effects", {})
    environment = data.get("environment", {})
    raw_evidence = {
        "workflow_run_id": workflow_run_id,
        "workflow_run_attempt": workflow_run_attempt,
        "artifact_id": artifact_id,
        "artifact_url": artifact_url,
        "artifact_digest": artifact_digest,
        "retention_days": 90,
    }

    return {
        "schema_version": "0.3.0",
        "run_id": data.get("run_id"),
        "run_type": data.get("run_type"),
        "classification": data.get("classification"),
        "execution_mode": data.get("execution_mode"),
        "environment": environment,
        "validator": data.get("validator", {}),
        "safety": data.get("safety", {}),
        "execution_summary": {
            "start_succeeded": execution.get("start_succeeded"),
            "start_error": execution.get("start_error"),
            "root_process_id": execution.get("root_process_id"),
            "observed_process_count": len(execution.get("observed_processes", [])),
            "observed_processes": execution.get("observed_processes", []),
            "observed_window_count": len(execution.get("observed_windows", [])),
            "observed_windows": execution.get("observed_windows", []),
            "observed_visible_window_count": execution.get("observed_visible_window_count", 0),
            "final_windows": execution.get("final_windows", []),
            "ui_automation_status": execution.get("ui_automation", {}).get("status"),
            "ui_automation_windows": execution.get("ui_automation", {}).get("windows", []),
            "screenshot": execution.get("screenshot"),
            "started_at": execution.get("started_at"),
            "finished_at": execution.get("finished_at"),
        },
        "side_effect_summary": {
            "payload_inventory_sha256_before": side_effects.get("payload_inventory_sha256_before"),
            "payload_inventory_sha256_after": side_effects.get("payload_inventory_sha256_after"),
            "payload_unchanged": side_effects.get("payload_unchanged"),
            "added_files": side_effects.get("added_files", []),
            "removed_files": side_effects.get("removed_files", []),
            "modified_files": side_effects.get("modified_files", []),
            "recent_file_count": side_effects.get("recent_file_count", 0),
        },
        "assertions": assertions,
        "observation_counters": counters,
        "interpretation": data.get("interpretation", {}),
        "raw_evidence": raw_evidence,
    }


def render_summary(summary: dict[str, Any]) -> str:
    execution = summary["execution_summary"]
    counters = summary["observation_counters"]
    lines = [
        "# CDE eCTD 验证软件 V1.1.0：启动侦察",
        "",
        f"- 运行编号：`{summary['run_id']}`",
        f"- 分类：**{summary['classification']}**",
        f"- 软件启动：**{execution['start_succeeded']}**",
        f"- 相关进程：**{execution['observed_process_count']}**",
        f"- 窗口：**{execution['observed_window_count']}**",
        f"- 可见窗口：**{execution['observed_visible_window_count']}**",
        f"- UI Automation：**{execution['ui_automation_status']}**",
        f"- payload 未变化：**{summary['side_effect_summary']['payload_unchanged']}**",
        f"- 完整验证运行：**{counters['completed_validation_runs']}**",
        f"- 可采信黑盒观察：**{counters['admissible_black_box_observations']}**",
        f"- `official_black_box_observations`：**{counters['official_black_box_observations']}**",
        "",
        "## 观察到的窗口",
        "",
        "| PID | Visible | Class | Title |",
        "|---:|---:|---|---|",
    ]
    for window in execution["observed_windows"]:
        title = str(window.get("title") or "").replace("|", "\\|")
        class_name = str(window.get("class_name") or "").replace("|", "\\|")
        lines.append(
            f"| {window.get('process_id')} | {window.get('visible')} | {class_name} | {title} |"
        )
    if not execution["observed_windows"]:
        lines.append("|  |  |  | 未观察到窗口 |")

    lines += [
        "",
        "## 结论边界",
        "",
        "这次运行只验证官方应用能否在隔离环境中启动并暴露可自动化界面。未选择序列、未触发验证、未生成原生验证报告，因此正式黑盒观察仍必须为 0。",
        "",
        "## 下一门槛",
        "",
        summary.get("interpretation", {}).get("next_gate", "构建首个合成序列验证适配器。"),
        "",
        "## 原始证据",
        "",
        f"- Workflow run: `{summary['raw_evidence']['workflow_run_id']}`",
        f"- Artifact ID: `{summary['raw_evidence']['artifact_id']}`",
        f"- Artifact digest: `{summary['raw_evidence']['artifact_digest']}`",
        "- Retention: 90 days",
        "",
    ]
    return "\n".join(lines)


def update_status(status_path: Path, summary: dict[str, Any]) -> dict[str, Any]:
    status = read_json(status_path) if status_path.exists() else {}
    execution = summary["execution_summary"]
    counters = summary["observation_counters"]
    status.update(
        {
            "schema_version": "0.4.0",
            "status": (
                "OFFICIAL_APPLICATION_LAUNCH_RECONNAISSANCE_COMPLETED"
                if execution.get("start_succeeded")
                else "OFFICIAL_APPLICATION_LAUNCH_RECONNAISSANCE_ATTEMPTED"
            ),
            "software_executed": bool(summary["assertions"].get("software_executed")),
            "launch_reconnaissance_runs": counters.get("launch_reconnaissance_runs", 1),
            "completed_validation_runs": counters.get("completed_validation_runs", 0),
            "admissible_black_box_observations": counters.get("admissible_black_box_observations", 0),
            "calibration_informative_observations": counters.get("calibration_informative_observations", 0),
            "repeated_baseline_controls": counters.get("repeated_baseline_controls", 0),
            "official_black_box_observations": counters.get("official_black_box_observations", 0),
            "launch_reconnaissance": {
                "run_id": summary["run_id"],
                "classification": summary["classification"],
                "start_succeeded": execution.get("start_succeeded"),
                "start_error": execution.get("start_error"),
                "observed_process_count": execution.get("observed_process_count"),
                "observed_window_count": execution.get("observed_window_count"),
                "observed_visible_window_count": execution.get("observed_visible_window_count"),
                "ui_automation_status": execution.get("ui_automation_status"),
                "payload_unchanged": summary["side_effect_summary"].get("payload_unchanged"),
                "environment_representativeness": summary.get("environment", {}).get(
                    "environment_representativeness"
                ),
                "raw_evidence": summary["raw_evidence"],
            },
            "next_gate": summary.get("interpretation", {}).get("next_gate"),
            "boundary": (
                "Launch reconnaissance is not a validation observation. A count may increase only after a "
                "synthetic input is selected, validation is actually invoked, a terminal state is observed, "
                "and native output plus complete input/output provenance are preserved."
            ),
        }
    )
    return status


def render_status(status: dict[str, Any]) -> str:
    launch = status.get("launch_reconnaissance", {})
    return "\n".join(
        [
            "# CDE eCTD 验证软件黑盒状态",
            "",
            f"- 当前状态：**{status.get('status')}**",
            f"- 软件曾启动：**{status.get('software_executed')}**",
            f"- 启动侦察：**{status.get('launch_reconnaissance_runs', 0)}**",
            f"- 完整验证运行：**{status.get('completed_validation_runs', 0)}**",
            f"- 可采信黑盒观察：**{status.get('admissible_black_box_observations', 0)}**",
            f"- 可用于规则校准的观察：**{status.get('calibration_informative_observations', 0)}**",
            f"- 重复基线对照：**{status.get('repeated_baseline_controls', 0)}**",
            f"- `official_black_box_observations`：**{status.get('official_black_box_observations', 0)}**",
            "",
            "## 最近一次启动侦察",
            "",
            f"- 分类：`{launch.get('classification')}`",
            f"- 启动成功：`{launch.get('start_succeeded')}`",
            f"- 进程：`{launch.get('observed_process_count')}`",
            f"- 窗口：`{launch.get('observed_window_count')}`",
            f"- 可见窗口：`{launch.get('observed_visible_window_count')}`",
            f"- UI Automation：`{launch.get('ui_automation_status')}`",
            f"- payload 未变化：`{launch.get('payload_unchanged')}`",
            "",
            "## 为什么正式观察仍可能为 0",
            "",
            "启动应用只证明入口可以执行。只有真正选择合成输入、触发验证、观察到终态，并保存原生报告或同等强度的原生输出，才是一条可采信黑盒观察。",
            "",
            "## 下一门槛",
            "",
            str(status.get("next_gate") or "构建首个合成序列验证适配器。"),
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=Path, required=True)
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

    data = read_json(args.result)
    summary = bounded_summary(
        data,
        workflow_run_id=args.workflow_run_id,
        workflow_run_attempt=args.workflow_run_attempt,
        artifact_id=args.artifact_id,
        artifact_url=args.artifact_url,
        artifact_digest=args.artifact_digest,
    )

    evidence_dir = args.evidence_root / "launch-reconnaissance"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    run_id = summary.get("run_id") or f"workflow-{args.workflow_run_id}"
    write_json(evidence_dir / f"{run_id}.summary.json", summary)
    (evidence_dir / f"{run_id}.md").write_text(render_summary(summary), encoding="utf-8")

    status_path = args.evidence_root / "STATUS.json"
    status = update_status(status_path, summary)
    write_json(status_path, status)
    write_json(args.status_root / "OFFICIAL_VALIDATOR_BLACK_BOX_STATUS.json", status)
    (args.status_root / "OFFICIAL_VALIDATOR_BLACK_BOX_STATUS.md").write_text(
        render_status(status), encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
