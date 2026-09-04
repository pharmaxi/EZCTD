from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_cde_validator_install_and_launch as base  # noqa: E402


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    base.write_json(path, value)


def uia_snapshot(wrapper: Any) -> dict[str, Any]:
    try:
        info = wrapper.element_info
        descendants: list[dict[str, Any]] = []
        for child in wrapper.descendants()[:1800]:
            try:
                child_info = child.element_info
                rectangle = child.rectangle()
                descendants.append(
                    {
                        "name": child_info.name,
                        "automation_id": child_info.automation_id,
                        "control_type": child_info.control_type,
                        "class_name": child_info.class_name,
                        "enabled": child.is_enabled(),
                        "visible": child.is_visible(),
                        "rectangle": {
                            "left": rectangle.left,
                            "top": rectangle.top,
                            "right": rectangle.right,
                            "bottom": rectangle.bottom,
                        },
                    }
                )
            except Exception:
                continue
        return {
            "handle": int(wrapper.handle),
            "pid": int(wrapper.process_id()),
            "name": info.name,
            "automation_id": info.automation_id,
            "control_type": info.control_type,
            "class_name": info.class_name,
            "visible": wrapper.is_visible(),
            "enabled": wrapper.is_enabled(),
            "descendant_count": len(descendants),
            "descendants": descendants,
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def visible_windows_snapshot() -> list[dict[str, Any]]:
    from pywinauto import Desktop

    records: list[dict[str, Any]] = []
    for wrapper in Desktop(backend="uia").windows():
        try:
            if not wrapper.is_visible():
                continue
            records.append(uia_snapshot(wrapper))
        except Exception:
            continue
    return records


def capture_stage(output: Path, name: str, main_window: Any | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "at": utc_now(),
        "windows": visible_windows_snapshot(),
        "main_window": uia_snapshot(main_window) if main_window is not None else None,
        "screenshot": base.save_screenshot(output / f"{name}.png"),
    }
    write_json(output / f"{name}.json", record)
    return record


def wait_main_window(timeout: int = 75) -> Any:
    from pywinauto import Desktop

    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            for window in Desktop(backend="uia").windows():
                try:
                    if window.window_text() == "验证标准校验" and window.is_visible():
                        return window
                except Exception:
                    continue
        except Exception as exc:
            last_error = exc
        time.sleep(1)
    raise TimeoutError(f"main validator window not found; last_error={last_error}")


def invoke_control(control: Any) -> str:
    try:
        control.invoke()
        return "invoke"
    except Exception:
        control.click_input()
        return "click_input"


def window_handles() -> set[int]:
    from pywinauto import Desktop

    handles: set[int] = set()
    for window in Desktop(backend="uia").windows():
        try:
            if window.is_visible():
                handles.add(int(window.handle))
        except Exception:
            continue
    return handles


def wait_new_visible_window(before: set[int], timeout: int = 20) -> Any:
    from pywinauto import Desktop

    deadline = time.time() + timeout
    while time.time() < deadline:
        for window in Desktop(backend="uia").windows():
            try:
                handle = int(window.handle)
                if handle not in before and window.is_visible():
                    return window
            except Exception:
                continue
        time.sleep(0.5)
    raise TimeoutError("no new visible window appeared")


def find_positive_button(dialog: Any) -> Any | None:
    candidates = [
        "选择文件夹",
        "Select Folder",
        "确定",
        "OK",
        "打开",
        "Open",
        "是",
        "Yes",
        "继续",
        "Continue",
    ]
    for title in candidates:
        try:
            button = dialog.child_window(title=title, control_type="Button").wrapper_object()
            if button.is_visible() and button.is_enabled():
                return button
        except Exception:
            continue
    try:
        for button in dialog.descendants(control_type="Button"):
            title = button.window_text().strip()
            if title.lower() not in {"cancel", "取消", "close", "关闭"} and button.is_enabled():
                return button
    except Exception:
        pass
    return None


def choose_directory(
    main_window: Any,
    *,
    button_title: str,
    directory: Path,
    output: Path,
    label: str,
    action_trace: list[dict[str, Any]],
) -> dict[str, Any]:
    from pywinauto import keyboard

    result: dict[str, Any] = {
        "button_title": button_title,
        "directory": base.canonical_path(directory),
        "started_at": utc_now(),
        "success": False,
        "attempts": [],
        "error": None,
    }
    try:
        before = window_handles()
        button = main_window.child_window(
            title=button_title, control_type="Button"
        ).wrapper_object()
        method = invoke_control(button)
        action_trace.append(
            {
                "at": utc_now(),
                "action": "open_directory_chooser",
                "button": button_title,
                "method": method,
            }
        )
        dialog = wait_new_visible_window(before, timeout=25)
        result["dialog_initial"] = uia_snapshot(dialog)
        capture_stage(output, f"{label}-dialog-initial", main_window)

        dialog.set_focus()
        keyboard.send_keys("^l")
        time.sleep(0.8)
        keyboard.send_keys(str(directory), with_spaces=True, pause=0.02)
        keyboard.send_keys("{ENTER}")
        result["attempts"].append("ctrl_l_address_navigation")
        time.sleep(2)

        try:
            if dialog.is_visible():
                positive = find_positive_button(dialog)
                if positive is not None:
                    result["positive_button"] = positive.window_text()
                    result["positive_method"] = invoke_control(positive)
                    result["attempts"].append("positive_button")
                    time.sleep(2)
        except Exception:
            pass

        if int(dialog.handle) in window_handles():
            try:
                edits = [
                    item
                    for item in dialog.descendants(control_type="Edit")
                    if item.is_visible() and item.is_enabled()
                ]
                result["visible_edit_count"] = len(edits)
                if edits:
                    edits[0].set_edit_text(str(directory))
                    keyboard.send_keys("{ENTER}")
                    result["attempts"].append("visible_edit_set_text")
                    time.sleep(1)
                    positive = find_positive_button(dialog)
                    if positive is not None:
                        result["positive_button_second"] = positive.window_text()
                        result["positive_method_second"] = invoke_control(positive)
                        time.sleep(2)
            except Exception as exc:
                result["edit_attempt_error"] = f"{type(exc).__name__}: {exc}"

        result["dialog_final_visible"] = int(dialog.handle) in window_handles()
        result["success"] = not result["dialog_final_visible"]
        result["dialog_final"] = uia_snapshot(dialog)
        capture_stage(output, f"{label}-dialog-final", main_window)
        action_trace.append(
            {
                "at": utc_now(),
                "action": "directory_chooser_result",
                "button": button_title,
                "directory": base.canonical_path(directory),
                "success": result["success"],
                "attempts": result["attempts"],
            }
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()
    finally:
        result["finished_at"] = utc_now()
        write_json(output / f"{label}-directory-selection.json", result)
    return result


def unique_texts(snapshot: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for item in snapshot.get("descendants", []):
        text = str(item.get("name") or "").strip()
        if text and text not in values:
            values.append(text)
    name = str(snapshot.get("name") or "").strip()
    if name and name not in values:
        values.insert(0, name)
    return values


def app_windows(main_handle: int, app_pids: set[int]) -> list[Any]:
    from pywinauto import Desktop

    windows = []
    for window in Desktop(backend="uia").windows():
        try:
            if not window.is_visible() or int(window.handle) == main_handle:
                continue
            if int(window.process_id()) in app_pids:
                windows.append(window)
        except Exception:
            continue
    return windows


def handle_confirmation(dialog: Any, texts: list[str]) -> dict[str, Any]:
    joined = "\n".join(texts)
    confirmation_terms = [
        "仍要使用",
        "是否继续",
        "继续使用",
        "Do you want to continue",
    ]
    record = {
        "texts": texts,
        "is_confirmation": any(term in joined for term in confirmation_terms),
        "clicked": False,
        "button": None,
    }
    if record["is_confirmation"]:
        positive = find_positive_button(dialog)
        if positive is not None:
            record["button"] = positive.window_text()
            record["method"] = invoke_control(positive)
            record["clicked"] = True
    return record


def table_native_texts(main_window: Any) -> list[str]:
    initial_noise = {
        "编号",
        "验证结果",
        "严重程度",
        "描述",
        "说明",
        "No content in table",
    }
    values: list[str] = []
    try:
        table = main_window.child_window(control_type="Table").wrapper_object()
        for item in table.descendants():
            text = item.window_text().strip()
            if text and text not in initial_noise and text not in values:
                values.append(text)
    except Exception:
        pass
    return values


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--application", type=Path, required=True)
    parser.add_argument("--original-application", type=Path, required=True)
    parser.add_argument("--expected-app-sha256", required=True)
    parser.add_argument("--case-definition", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, default=Path(r"C:\EZCTDProbeInput\0000"))
    parser.add_argument("--report-root", type=Path, default=Path(r"C:\EZCTDProbeReports"))
    parser.add_argument("--terminal-timeout", type=int, default=180)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    case = read_json(args.case_definition)
    report: dict[str, Any] = {
        "schema_version": "0.1.0",
        "run_id": f"{case['case_id']}-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "run_type": "official_validator_synthetic_transaction",
        "case_id": case["case_id"],
        "profile": case["profile"],
        "status": "STARTED",
        "started_at": utc_now(),
        "environment_adaptation": {
            "type": "byte_identical_ascii_ntfs_alias",
            "reason": "Launch4j corrupts the Chinese executable name in the JVM classpath on the non-Chinese hosted Windows runner.",
            "stock_environment_equivalent": False,
        },
        "action_trace": [],
        "native_alerts": [],
        "errors": [],
        "observation_counters": {
            "completed_validation_runs": 0,
            "admissible_black_box_observations": 0,
            "environment_adapted_official_observations": 0,
            "stock_environment_official_observations": 0,
            "calibration_informative_observations": 0,
            "official_black_box_observations": 0,
        },
    }
    process: subprocess.Popen[bytes] | None = None
    known_pids: set[int] = set()
    firewall_rules: list[dict[str, Any]] = []
    stdout_path = args.output / "validator.stdout.bin"
    stderr_path = args.output / "validator.stderr.bin"

    try:
        application = args.application.resolve()
        original_application = args.original_application.resolve()
        expected_hash = args.expected_app_sha256.lower()
        alias_hash = base.sha256_file(application)
        original_hash = base.sha256_file(original_application)
        report["identity"] = {
            "application": base.canonical_path(application),
            "original_application": base.canonical_path(original_application),
            "alias_sha256": alias_hash,
            "original_sha256": original_hash,
            "expected_sha256": expected_hash,
            "byte_identical": alias_hash == original_hash == expected_hash,
            "samefile": os.path.samefile(application, original_application),
        }
        if not report["identity"]["byte_identical"]:
            raise ValueError("official application identity mismatch")

        if args.input_root.exists():
            shutil.rmtree(args.input_root)
        args.input_root.mkdir(parents=True, exist_ok=True)
        if args.report_root.exists():
            shutil.rmtree(args.report_root)
        args.report_root.mkdir(parents=True, exist_ok=True)

        input_before = base.inventory(args.input_root)
        input_digest_before = base.inventory_digest(input_before)
        expected_digest = case["input"]["inventory_digest"]
        if input_before or input_digest_before != expected_digest:
            raise ValueError("runtime fixture is not the frozen empty-root case")
        report["input"] = {
            "directory": base.canonical_path(args.input_root),
            "inventory_before": input_before,
            "inventory_digest_before": input_digest_before,
            "expected_inventory_digest": expected_digest,
        }
        write_json(args.output / "input-before.json", report["input"])

        environment, removed_names = base.scrubbed_environment()
        environment["Launch4j"] = "debug-all"
        report["safety"] = {
            "removed_environment_names": removed_names,
            "credentials_exposed_to_child": False,
        }
        java = base.find_bundled_java(application.parent)
        javaw = application.parent / "jre" / "jre1.8.0_202" / "bin" / "javaw.exe"
        for program, label in [
            (application, "transaction-alias-wrapper"),
            (java, "transaction-java"),
            (javaw, "transaction-javaw"),
        ]:
            if program is not None:
                firewall_rules.append(base.add_firewall_rule(program, label))
        report["safety"]["firewall_rules"] = firewall_rules
        report["safety"]["firewall_ready"] = all(
            item.get("status") == "BLOCKED_OUTBOUND"
            for item in firewall_rules
            if item.get("status") != "PROGRAM_MISSING"
        )
        if not report["safety"]["firewall_ready"]:
            raise RuntimeError("outbound firewall safety gate failed")

        with stdout_path.open("wb") as stdout_stream, stderr_path.open("wb") as stderr_stream:
            process = subprocess.Popen(
                [str(application), "--l4j-debug"],
                cwd=str(application.parent),
                env=environment,
                stdout=stdout_stream,
                stderr=stderr_stream,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            known_pids.add(process.pid)
            report["action_trace"].append(
                {
                    "at": utc_now(),
                    "action": "launch_official_byte_identical_alias",
                    "pid": process.pid,
                }
            )

            main_window = wait_main_window(timeout=75)
            report["main_window_pid"] = int(main_window.process_id())
            known_pids.add(report["main_window_pid"])
            capture_stage(args.output, "00-main-ready", main_window)

            input_selection = choose_directory(
                main_window,
                button_title="选择申报资料",
                directory=args.input_root,
                output=args.output,
                label="01-input",
                action_trace=report["action_trace"],
            )
            report["input_selection"] = input_selection
            if not input_selection["success"]:
                raise RuntimeError("input directory chooser did not close successfully")

            report_selection = choose_directory(
                main_window,
                button_title="报告输出路径",
                directory=args.report_root,
                output=args.output,
                label="02-report",
                action_trace=report["action_trace"],
            )
            report["report_selection"] = report_selection
            if not report_selection["success"]:
                raise RuntimeError("report directory chooser did not close successfully")

            capture_stage(args.output, "03-paths-selected", main_window)
            app_process_records = base.process_records(
                process.pid, application.parent, known_pids
            )
            app_pids = {item["pid"] for item in app_process_records}
            app_pids.add(int(main_window.process_id()))

            start_button = main_window.child_window(
                title="启动验证", control_type="Button"
            ).wrapper_object()
            start_method = invoke_control(start_button)
            validation_click_at = utc_now()
            report["action_trace"].append(
                {
                    "at": validation_click_at,
                    "action": "invoke_validation",
                    "control": "启动验证",
                    "method": start_method,
                }
            )
            report["validation_invoked"] = True
            report["validation_click_at"] = validation_click_at
            capture_stage(args.output, "04-validation-clicked", main_window)

            output_stable_ticks = 0
            previous_output_digest: str | None = None
            terminal_alert: dict[str, Any] | None = None
            table_texts: list[str] = []
            deadline = time.time() + args.terminal_timeout
            sample_number = 0
            while time.time() < deadline:
                time.sleep(2)
                sample_number += 1
                app_process_records = base.process_records(
                    process.pid, application.parent, known_pids
                )
                app_pids = {item["pid"] for item in app_process_records} | {
                    int(main_window.process_id())
                }
                output_inventory = base.inventory(args.report_root)
                output_digest = base.inventory_digest(output_inventory)
                if output_inventory and output_digest == previous_output_digest:
                    output_stable_ticks += 1
                elif output_inventory:
                    output_stable_ticks = 0
                previous_output_digest = output_digest

                alert_records = []
                for dialog in app_windows(int(main_window.handle), app_pids):
                    snapshot = uia_snapshot(dialog)
                    texts = unique_texts(snapshot)
                    handling = handle_confirmation(dialog, texts)
                    alert_record = {
                        "at": utc_now(),
                        "sample": sample_number,
                        "snapshot": snapshot,
                        "texts": texts,
                        "handling": handling,
                    }
                    alert_records.append(alert_record)
                    if handling["clicked"]:
                        report["action_trace"].append(
                            {
                                "at": utc_now(),
                                "action": "confirm_native_dialog",
                                "button": handling.get("button"),
                                "texts": texts,
                            }
                        )
                        time.sleep(1)
                    elif texts:
                        terminal_alert = alert_record
                report["native_alerts"].extend(alert_records)

                table_texts = table_native_texts(main_window)
                sample = {
                    "sample": sample_number,
                    "at": utc_now(),
                    "processes": app_process_records,
                    "output_file_count": len(output_inventory),
                    "output_digest": output_digest,
                    "output_stable_ticks": output_stable_ticks,
                    "table_native_texts": table_texts,
                    "alert_count": len(alert_records),
                }
                report.setdefault("terminal_samples", []).append(sample)
                if output_inventory and output_stable_ticks >= 2:
                    report["terminal_reason"] = "native_output_files_stable"
                    break
                if terminal_alert is not None:
                    report["terminal_reason"] = "native_terminal_dialog"
                    break
                if table_texts:
                    report["terminal_reason"] = "native_table_results_present"
                    break

            capture_stage(args.output, "05-terminal", main_window)

        output_inventory = base.inventory(args.report_root)
        input_after = base.inventory(args.input_root)
        input_digest_after = base.inventory_digest(input_after)
        report["input"].update(
            {
                "inventory_after": input_after,
                "inventory_digest_after": input_digest_after,
                "unchanged": input_digest_after == input_digest_before,
            }
        )
        report["native_result"] = {
            "terminal_reason": report.get("terminal_reason"),
            "terminal_alert": terminal_alert,
            "table_native_texts": table_texts,
            "output_directory": base.canonical_path(args.report_root),
            "output_inventory": output_inventory,
            "output_digest": base.inventory_digest(output_inventory),
            "native_report_present": bool(output_inventory),
        }
        write_json(args.output / "input-after.json", report["input"])
        write_json(args.output / "native-result.json", report["native_result"])

        native_terminal = bool(
            report["native_result"]["native_report_present"]
            or report["native_result"]["terminal_alert"]
            or report["native_result"]["table_native_texts"]
        )
        precondition_text = "\n".join(
            report["native_result"].get("terminal_alert", {}).get("texts", [])
            if report["native_result"].get("terminal_alert")
            else []
        )
        precondition_only = any(
            term in precondition_text
            for term in (
                "请选择申报资料",
                "请选择报告输出路径",
                "不规范的资料路径",
                "序列文件夹不是数字",
            )
        ) and not report["native_result"]["native_report_present"]

        admissibility = {
            "official_binary_identity_fixed": report["identity"]["byte_identical"],
            "input_identity_fixed": input_digest_before == expected_digest,
            "validation_control_invoked": bool(report.get("validation_invoked")),
            "native_terminal_result_captured": native_terminal,
            "precondition_only_result": precondition_only,
            "input_unchanged": report["input"]["unchanged"],
            "outbound_firewall_ready": report["safety"]["firewall_ready"],
            "raw_evidence_written": True,
        }
        admissible = all(
            [
                admissibility["official_binary_identity_fixed"],
                admissibility["input_identity_fixed"],
                admissibility["validation_control_invoked"],
                admissibility["native_terminal_result_captured"],
                not admissibility["precondition_only_result"],
                admissibility["input_unchanged"],
                admissibility["outbound_firewall_ready"],
            ]
        )
        report["admissibility"] = admissibility
        report["admissible_official_black_box_observation"] = admissible
        if admissible:
            report["status"] = "ADMISSIBLE_ENVIRONMENT_ADAPTED_OFFICIAL_OBSERVATION"
            report["observation_counters"].update(
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
                "Repeat the same case for stability, then construct a minimal sequence baseline before rule-specific mutations."
            )
        else:
            report["status"] = "SYNTHETIC_TRANSACTION_NOT_ADMISSIBLE"
            report["next_gate"] = (
                "Use the preserved dialog and UI Automation evidence to repair the failed transaction stage without changing counters."
            )
    except Exception as exc:
        report["status"] = "SYNTHETIC_TRANSACTION_FAILED_CLOSED"
        report["errors"].append(
            {
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        )
        report["validation_invoked"] = bool(report.get("validation_invoked", False))
        report["admissible_official_black_box_observation"] = False
        report["next_gate"] = (
            "Repair the failed UI or evidence precondition using the uploaded raw trace; keep all observation counters at zero."
        )
    finally:
        if process is not None:
            try:
                base.process_records(process.pid, args.application.parent, known_pids)
            except Exception:
                pass
        base.terminate_scope(known_pids)
        for record in reversed(firewall_rules):
            base.remove_firewall_rule(record)
        report["finished_at"] = utc_now()
        report["assertions"] = {
            "validation_invoked": bool(report.get("validation_invoked", False)),
            "native_validation_report_present": bool(
                report.get("native_result", {}).get("native_report_present", False)
            ),
            "input_unchanged": bool(report.get("input", {}).get("unchanged", False)),
            "official_black_box_observation_count": report["observation_counters"][
                "official_black_box_observations"
            ],
        }
        write_json(args.output / "synthetic-transaction.json", report)
        summary = {
            "run_id": report["run_id"],
            "case_id": report["case_id"],
            "status": report["status"],
            "validation_invoked": report["assertions"]["validation_invoked"],
            "native_report_present": report["assertions"]["native_validation_report_present"],
            "terminal_reason": report.get("native_result", {}).get("terminal_reason"),
            "table_native_text_count": len(
                report.get("native_result", {}).get("table_native_texts", [])
            ),
            "input_unchanged": report["assertions"]["input_unchanged"],
            "admissible": report.get("admissible_official_black_box_observation", False),
            "observation_counters": report["observation_counters"],
            "next_gate": report.get("next_gate"),
            "errors": report.get("errors", []),
        }
        write_json(args.output / "SYNTHETIC_TRANSACTION_SUMMARY.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
