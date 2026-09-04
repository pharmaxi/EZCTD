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
        report.get("run_type") == "installed_layout_and_launch_forensics",
        "unexpected run_type",
    )
    counters = report.get("observation_counters", {})
    assertions = report.get("assertions", {})
    require(counters.get("completed_validation_runs") == 0, "forensics cannot count as validation")
    require(
        counters.get("official_black_box_observations") == 0,
        "forensics cannot count as official observation",
    )
    require(assertions.get("validation_invoked") is False, "forensics must not invoke validation")
    require(
        assertions.get("native_validation_report_present") is False,
        "forensics must not claim native validation output",
    )

    identity = report.get("identity", {})
    installation = report.get("installation", {})
    wrapped = report.get("wrapped_application", {})
    wrapper = report.get("official_wrapper_probe", {})
    diagnostic = report.get("diagnostic_java_adapter_probe", {})
    safety = report.get("safety", {})

    return {
        "schema_version": "0.1.0",
        "run_id": report.get("run_id"),
        "run_type": report.get("run_type"),
        "status": report.get("status"),
        "started_at": report.get("started_at"),
        "finished_at": report.get("finished_at"),
        "identity": {
            "installer_sha256": identity.get("installer_sha256"),
            "static_application_sha256": identity.get("static_application_sha256"),
            "installed_application": identity.get("installed_application"),
            "installed_application_sha256": identity.get("installed_application_sha256"),
            "installed_matches_static": identity.get("installed_matches_static"),
            "static_payload_digest_before": identity.get("static_payload_digest_before"),
            "static_payload_digest_after": identity.get("static_payload_digest_after"),
            "static_payload_unchanged": identity.get("static_payload_unchanged"),
        },
        "installation": {
            "executed": installation.get("executed"),
            "return_code": installation.get("return_code"),
            "requested_directory_exists": installation.get("requested_directory_exists"),
            "installed_file_count": installation.get("installed_file_count"),
            "installed_tree_digest": installation.get("installed_tree_digest"),
            "registry_delta": installation.get("registry_delta", []),
            "application_candidates": installation.get("application_candidates", []),
        },
        "wrapped_application": {
            "zip_readable": wrapped.get("zip_readable"),
            "entry_count": wrapped.get("entry_count"),
            "main_class_entries": wrapped.get("main_class_entries", []),
            "manifest": wrapped.get("manifest"),
            "rebuilt_jar": wrapped.get("rebuilt_jar"),
            "rebuilt_jar_sha256": wrapped.get("rebuilt_jar_sha256"),
            "error": wrapped.get("error"),
        },
        "official_wrapper": {
            "start_succeeded": wrapper.get("start_succeeded"),
            "root_pid": wrapper.get("root_pid"),
            "root_return_code": wrapper.get("root_return_code"),
            "processes": wrapper.get("processes", []),
            "windows": wrapper.get("windows", []),
            "visible_window_count": wrapper.get("visible_window_count", 0),
            "uia_status": wrapper.get("uia", {}).get("status"),
            "uia_windows": wrapper.get("uia", {}).get("windows", []),
            "uia_descendant_count": wrapper.get("uia_descendant_count", 0),
            "ui_reachable": wrapper.get("ui_reachable"),
            "class_not_found_main": wrapper.get("class_not_found_main"),
            "screenshot": wrapper.get("screenshot"),
            "captured_files": wrapper.get("captured_files", []),
            "error": wrapper.get("error"),
        },
        "diagnostic_java_adapter": {
            "executed": bool(diagnostic),
            "start_succeeded": diagnostic.get("start_succeeded"),
            "root_return_code": diagnostic.get("root_return_code"),
            "processes": diagnostic.get("processes", []),
            "windows": diagnostic.get("windows", []),
            "visible_window_count": diagnostic.get("visible_window_count", 0),
            "uia_status": diagnostic.get("uia", {}).get("status"),
            "uia_windows": diagnostic.get("uia", {}).get("windows", []),
            "uia_descendant_count": diagnostic.get("uia_descendant_count", 0),
            "ui_reachable": diagnostic.get("ui_reachable"),
            "screenshot": diagnostic.get("screenshot"),
            "captured_files": diagnostic.get("captured_files", []),
            "error": diagnostic.get("error"),
            "eligibility": diagnostic.get("eligibility"),
        },
        "safety": {
            "credentials_exposed_to_child": safety.get("credentials_exposed_to_child"),
            "removed_environment_names": safety.get("removed_environment_names", []),
            "firewall_ready_before_install": safety.get("firewall_ready_before_install"),
            "firewall_ready_for_launch": safety.get("firewall_ready_for_launch"),
            "official_wrapper_process_started": safety.get("official_wrapper_process_started"),
            "official_wrapper_ui_reached": safety.get("official_wrapper_ui_reached"),
            "validation_invoked": safety.get("validation_invoked"),
            "native_validation_report_present": safety.get("native_validation_report_present"),
        },
        "observation_counters": counters,
        "assertions": assertions,
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
            "Installation and launch forensics do not constitute a validation transaction. "
            "The official observation count remains zero until a deterministic synthetic input is selected, "
            "validation is invoked, a terminal native result is captured and input integrity is conserved."
        ),
    }


def render_summary(summary: dict[str, Any]) -> str:
    installation = summary["installation"]
    wrapped = summary["wrapped_application"]
    wrapper = summary["official_wrapper"]
    diagnostic = summary["diagnostic_java_adapter"]
    counters = summary["observation_counters"]
    lines = [
        "# CDE eCTD 验证器：安装布局与启动取证",
        "",
        f"- 运行：`{summary['run_id']}`",
        f"- 状态：**{summary['status']}**",
        f"- 安装器执行：**{installation.get('executed')}**",
        f"- 安装器退出码：**{installation.get('return_code')}**",
        f"- 已安装文件：**{installation.get('installed_file_count')}**",
        f"- 安装后应用与静态应用字节一致：**{summary['identity'].get('installed_matches_static')}**",
        f"- EXE 可按附加 ZIP/JAR 读取：**{wrapped.get('zip_readable')}**",
        f"- `Main.class`：**{wrapped.get('main_class_entries')}**",
        f"- 官方包装器进程启动：**{wrapper.get('start_succeeded')}**",
        f"- 官方包装器 UI 可达：**{wrapper.get('ui_reachable')}**",
        f"- `Main` 类缺失错误：**{wrapper.get('class_not_found_main')}**",
        f"- 诊断 Java 适配器 UI 可达：**{diagnostic.get('ui_reachable')}**",
        f"- 完整验证运行：**{counters.get('completed_validation_runs')}**",
        f"- `official_black_box_observations`：**{counters.get('official_black_box_observations')}**",
        "",
        "## 官方包装器窗口",
        "",
        "| PID | Visible | Class | Title |",
        "|---:|---:|---|---|",
    ]
    for window in wrapper.get("windows", []):
        title = str(window.get("title") or "").replace("|", "\\|")
        class_name = str(window.get("class_name") or "").replace("|", "\\|")
        lines.append(
            f"| {window.get('pid')} | {window.get('visible')} | {class_name} | {title} |"
        )
    if not wrapper.get("windows"):
        lines.append("|  |  |  | 未观察到窗口 |")

    lines += [
        "",
        "## 诊断适配器边界",
        "",
        "直接 Java 适配器只用于理解官方包内的入口类和 UI；即使它成功打开界面，也不能替代官方 EXE 入口，不能计入官方黑盒观察。",
        "",
        "## 下一门槛",
        "",
        str(summary.get("next_gate") or "复核原始证据后决定下一步。"),
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


def update_status(status: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    wrapper = summary["official_wrapper"]
    diagnostic = summary["diagnostic_java_adapter"]
    counters = summary["observation_counters"]
    status.update(
        {
            "schema_version": "0.5.0",
            "status": summary["status"],
            "software_executed": bool(wrapper.get("start_succeeded")),
            "official_wrapper_ui_reached": bool(wrapper.get("ui_reachable")),
            "diagnostic_java_adapter_ui_reached": bool(diagnostic.get("ui_reachable")),
            "completed_validation_runs": counters.get("completed_validation_runs", 0),
            "admissible_black_box_observations": counters.get(
                "admissible_black_box_observations", 0
            ),
            "calibration_informative_observations": counters.get(
                "calibration_informative_observations", 0
            ),
            "official_black_box_observations": counters.get(
                "official_black_box_observations", 0
            ),
            "latest_launch_forensics": {
                "run_id": summary["run_id"],
                "status": summary["status"],
                "installation": summary["installation"],
                "identity": summary["identity"],
                "wrapped_application": summary["wrapped_application"],
                "official_wrapper": {
                    key: wrapper.get(key)
                    for key in (
                        "start_succeeded",
                        "root_return_code",
                        "visible_window_count",
                        "uia_status",
                        "uia_descendant_count",
                        "ui_reachable",
                        "class_not_found_main",
                        "error",
                    )
                },
                "diagnostic_java_adapter": {
                    key: diagnostic.get(key)
                    for key in (
                        "executed",
                        "start_succeeded",
                        "root_return_code",
                        "visible_window_count",
                        "uia_status",
                        "uia_descendant_count",
                        "ui_reachable",
                        "error",
                        "eligibility",
                    )
                },
                "raw_evidence": summary["raw_evidence"],
            },
            "next_gate": summary.get("next_gate"),
            "boundary": summary["boundary"],
        }
    )
    return status


def render_status(status: dict[str, Any]) -> str:
    latest = status.get("latest_launch_forensics", {})
    wrapper = latest.get("official_wrapper", {})
    diagnostic = latest.get("diagnostic_java_adapter", {})
    return "\n".join(
        [
            "# CDE eCTD 官方验证器黑盒状态",
            "",
            f"- 当前状态：**{status.get('status')}**",
            f"- 官方包装器进程曾启动：**{status.get('software_executed')}**",
            f"- 官方包装器 UI 可达：**{status.get('official_wrapper_ui_reached')}**",
            f"- 诊断 Java 适配器 UI 可达：**{status.get('diagnostic_java_adapter_ui_reached')}**",
            f"- 完整验证运行：**{status.get('completed_validation_runs', 0)}**",
            f"- 可采信黑盒观察：**{status.get('admissible_black_box_observations', 0)}**",
            f"- 可用于规则校准的观察：**{status.get('calibration_informative_observations', 0)}**",
            f"- `official_black_box_observations`：**{status.get('official_black_box_observations', 0)}**",
            "",
            "## 最近一次启动取证",
            "",
            f"- 运行：`{latest.get('run_id')}`",
            f"- 安装器退出码：`{latest.get('installation', {}).get('return_code')}`",
            f"- 安装后应用字节一致：`{latest.get('identity', {}).get('installed_matches_static')}`",
            f"- 官方包装器启动：`{wrapper.get('start_succeeded')}`",
            f"- 官方包装器 UI：`{wrapper.get('ui_reachable')}`",
            f"- `Main` 类缺失：`{wrapper.get('class_not_found_main')}`",
            f"- 诊断适配器 UI：`{diagnostic.get('ui_reachable')}`",
            "",
            "## 计数边界",
            "",
            "安装、进程启动、窗口出现和直接 Java 诊断都不是完整验证事务。只有实际选择固定合成输入、触发验证、达到终态并保存原生结果后，正式观察计数才能增加。",
            "",
            "## 下一门槛",
            "",
            str(status.get("next_gate") or "复核原始证据后决定下一步。"),
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
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

    report = read_json(args.report)
    summary = bounded_summary(
        report,
        workflow_run_id=args.workflow_run_id,
        workflow_run_attempt=args.workflow_run_attempt,
        artifact_id=args.artifact_id,
        artifact_url=args.artifact_url,
        artifact_digest=args.artifact_digest,
    )

    evidence_dir = args.evidence_root / "launch-forensics"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    run_id = summary.get("run_id") or f"workflow-{args.workflow_run_id}"
    write_json(evidence_dir / f"{run_id}.summary.json", summary)
    (evidence_dir / f"{run_id}.md").write_text(render_summary(summary), encoding="utf-8")

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
