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


def render(summary: dict[str, Any]) -> str:
    alias = summary["alias_identity"]
    probe = summary["ascii_alias_probe"]
    direct = summary.get("diagnostic_java_absolute_classpath_probe", {})
    return "\n".join(
        [
            "# CDE eCTD 验证器：中文路径编码与 ASCII 别名探针",
            "",
            f"- 状态：**{summary['status']}**",
            f"- 别名方式：`{alias.get('method')}`",
            f"- 与原文件为同一 NTFS 文件：`{alias.get('samefile')}`",
            f"- SHA-256 字节一致：`{alias.get('byte_identical')}`",
            f"- ASCII 别名 UI 可达：`{probe.get('ui_reachable')}`",
            f"- ASCII 别名仍报 `Main` 缺失：`{probe.get('class_not_found_main')}`",
            f"- Launch4j 日志使用 ASCII 别名：`{probe.get('launch4j_log_mentions_ascii_alias')}`",
            f"- 修正绝对 classpath 的 Java 诊断 UI 可达：`{direct.get('ui_reachable')}`",
            "- 实际验证已触发：`False`",
            "- `official_black_box_observations`：`0`",
            "",
            "## 解释",
            "",
            "原始中文文件名在当前非中文 Windows runner 中被 Launch4j 写成问号路径；本探针只改变文件名入口，不改变可执行文件字节。该适配用于确认环境编码故障和恢复 UI，不等同于未经适配的原始安装行为。",
            "",
            "## 下一门槛",
            "",
            str(summary.get("next_gate") or "复核原始证据。"),
            "",
            "## 原始证据",
            "",
            f"- Workflow run: `{summary['raw_evidence']['workflow_run_id']}`",
            f"- Artifact ID: `{summary['raw_evidence']['artifact_id']}`",
            f"- Artifact digest: `{summary['raw_evidence']['artifact_digest']}`",
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
    result = report.get("ascii_alias_probe")
    require(isinstance(result, dict), "ascii alias result missing")
    require(result.get("validation_invoked") is False, "alias probe must not invoke validation")
    require(
        result.get("native_validation_report_present") is False,
        "alias probe must not claim native validation output",
    )
    require(
        result.get("official_black_box_observations") == 0,
        "alias probe cannot count as official observation",
    )
    alias = result.get("alias_identity", {})
    require(alias.get("byte_identical") is True, "ASCII alias is not byte-identical")

    summary = {
        "schema_version": "0.1.0",
        "run_id": report.get("run_id"),
        "status": result.get("status"),
        "alias_identity": alias,
        "ascii_alias_probe": {
            key: result.get("ascii_alias_probe", {}).get(key)
            for key in (
                "start_succeeded",
                "root_pid",
                "root_return_code",
                "processes",
                "windows",
                "visible_window_count",
                "uia",
                "uia_descendant_count",
                "ui_reachable",
                "class_not_found_main",
                "launch4j_log_mentions_ascii_alias",
                "launch4j_log_contains_question_mark_executable",
                "screenshot",
                "captured_files",
                "error",
            )
        },
        "diagnostic_java_absolute_classpath_probe": {
            key: result.get("diagnostic_java_absolute_classpath_probe", {}).get(key)
            for key in (
                "start_succeeded",
                "root_pid",
                "root_return_code",
                "processes",
                "windows",
                "visible_window_count",
                "uia",
                "uia_descendant_count",
                "ui_reachable",
                "screenshot",
                "captured_files",
                "error",
                "eligibility",
            )
        },
        "firewall_ready": result.get("firewall_ready"),
        "validation_invoked": False,
        "native_validation_report_present": False,
        "official_black_box_observations": 0,
        "next_gate": result.get("next_gate"),
        "raw_evidence": {
            "workflow_run_id": args.workflow_run_id,
            "workflow_run_attempt": args.workflow_run_attempt,
            "artifact_id": args.artifact_id,
            "artifact_url": args.artifact_url,
            "artifact_digest": args.artifact_digest,
            "retention_days": 90,
        },
        "boundary": (
            "A byte-identical ASCII hardlink or copy is an environment adaptation. It may establish UI reachability, "
            "but no observation is countable until validation is actually invoked and native terminal evidence is captured."
        ),
    }

    evidence_dir = args.evidence_root / "launch-forensics"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    run_id = summary.get("run_id") or f"workflow-{args.workflow_run_id}"
    write_json(evidence_dir / f"{run_id}.ascii-alias.summary.json", summary)
    (evidence_dir / f"{run_id}.ascii-alias.md").write_text(render(summary), encoding="utf-8")

    status_path = args.evidence_root / "STATUS.json"
    status = read_json(status_path) if status_path.exists() else {}
    alias_probe = summary["ascii_alias_probe"]
    direct_probe = summary["diagnostic_java_absolute_classpath_probe"]
    status.update(
        {
            "schema_version": "0.6.0",
            "status": summary["status"],
            "byte_identical_ascii_alias_ui_reached": bool(alias_probe.get("ui_reachable")),
            "diagnostic_java_absolute_classpath_ui_reached": bool(
                direct_probe.get("ui_reachable")
            ),
            "completed_validation_runs": 0,
            "admissible_black_box_observations": 0,
            "calibration_informative_observations": 0,
            "official_black_box_observations": 0,
            "ascii_alias_adaptation": summary,
            "next_gate": summary.get("next_gate"),
            "boundary": summary["boundary"],
        }
    )
    write_json(status_path, status)
    write_json(args.status_root / "OFFICIAL_VALIDATOR_BLACK_BOX_STATUS.json", status)

    status_lines = [
        "# CDE eCTD 官方验证器黑盒状态",
        "",
        f"- 当前状态：**{status.get('status')}**",
        f"- 原始中文入口 UI 可达：**{status.get('official_wrapper_ui_reached')}**",
        f"- 字节一致的 ASCII 别名 UI 可达：**{status.get('byte_identical_ascii_alias_ui_reached')}**",
        f"- 修正绝对 classpath 的 Java 诊断 UI 可达：**{status.get('diagnostic_java_absolute_classpath_ui_reached')}**",
        "- 完整验证运行：**0**",
        "- 可采信黑盒观察：**0**",
        "- `official_black_box_observations`：**0**",
        "",
        "路径适配或界面打开都不是验证事务。只有选择固定合成输入、触发验证、达到终态并保存原生结果后，观察计数才能增加。",
        "",
        "## 下一门槛",
        "",
        str(status.get("next_gate") or "复核原始证据。"),
        "",
    ]
    (args.status_root / "OFFICIAL_VALIDATOR_BLACK_BOX_STATUS.md").write_text(
        "\n".join(status_lines), encoding="utf-8"
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
