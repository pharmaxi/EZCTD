from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe_cde_validator_install_and_launch as base  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_captured_text(probe_dir: Path, probe: dict[str, Any]) -> str:
    parts = [
        base.read_text_safely(probe_dir / "ascii-alias.stdout.txt"),
        base.read_text_safely(probe_dir / "ascii-alias.stderr.txt"),
    ]
    for item in probe.get("captured_files", []):
        relative = item.get("captured_as")
        if relative:
            parts.append(base.read_text_safely(probe_dir / str(relative)))
    return "\n".join(parts)


def create_ascii_alias(application: Path, alias: Path) -> dict[str, Any]:
    if alias.exists() or alias.is_symlink():
        alias.unlink()
    record: dict[str, Any] = {
        "source": base.canonical_path(application),
        "alias": base.canonical_path(alias),
        "method": None,
        "source_sha256": base.sha256_file(application),
        "alias_sha256": None,
        "samefile": False,
        "byte_identical": False,
    }
    try:
        os.link(application, alias)
        record["method"] = "ntfs_hardlink"
    except OSError as exc:
        record["hardlink_error"] = f"{type(exc).__name__}: {exc}"
        shutil.copy2(application, alias)
        record["method"] = "byte_for_byte_copy"
    record["alias_sha256"] = base.sha256_file(alias)
    try:
        record["samefile"] = os.path.samefile(application, alias)
    except OSError:
        record["samefile"] = False
    record["byte_identical"] = record["source_sha256"] == record["alias_sha256"]
    return record


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-app-sha256", required=True)
    parser.add_argument("--observation-seconds", type=int, default=45)
    args = parser.parse_args()

    report = read_json(args.report)
    args.output.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "schema_version": "0.1.0",
        "run_type": "byte_identical_ascii_alias_launch_probe",
        "status": "STARTED",
        "validation_invoked": False,
        "native_validation_report_present": False,
        "official_black_box_observations": 0,
        "errors": [],
    }
    firewall_rules: list[dict[str, Any]] = []

    try:
        installed_value = report.get("identity", {}).get("installed_application")
        if not installed_value:
            raise ValueError("installed application path missing from base report")
        application = Path(str(installed_value))
        if not application.exists():
            raise FileNotFoundError(application)
        actual_hash = base.sha256_file(application)
        if actual_hash != args.expected_app_sha256.lower():
            raise ValueError(f"installed application hash mismatch: {actual_hash}")

        alias = application.parent / "CDEValidator.exe"
        alias_record = create_ascii_alias(application, alias)
        result["alias_identity"] = alias_record
        if not alias_record["byte_identical"]:
            raise ValueError("ASCII alias bytes differ from official application")

        environment, removed_names = base.scrubbed_environment()
        environment["Launch4j"] = "debug-all"
        result["removed_environment_names"] = removed_names

        java = base.find_bundled_java(application.parent)
        javaw = application.parent / "jre" / "jre1.8.0_202" / "bin" / "javaw.exe"
        for program, label in [
            (alias, "ascii-alias-wrapper"),
            (java, "ascii-alias-java"),
            (javaw, "ascii-alias-javaw"),
        ]:
            if program is None:
                continue
            firewall_rules.append(base.add_firewall_rule(program, label))
        result["firewall_rules"] = firewall_rules
        result["firewall_ready"] = all(
            item.get("status") == "BLOCKED_OUTBOUND"
            for item in firewall_rules
            if item.get("status") != "PROGRAM_MISSING"
        )
        if not result["firewall_ready"]:
            raise RuntimeError("outbound firewall safety gate failed")

        alias_probe_dir = args.output / "ascii-alias"
        alias_probe = base.probe_process(
            [str(alias), "--l4j-debug"],
            cwd=application.parent,
            environment=environment,
            output_dir=alias_probe_dir,
            label="ascii-alias",
            observation_seconds=args.observation_seconds,
        )
        alias_text = read_captured_text(alias_probe_dir, alias_probe)
        alias_probe["class_not_found_main"] = "Could not find or load main class Main" in alias_text
        alias_probe["launch4j_log_mentions_ascii_alias"] = "CDEValidator.exe" in alias_text
        alias_probe["launch4j_log_contains_question_mark_executable"] = "eCTD????.exe" in alias_text
        result["ascii_alias_probe"] = alias_probe

        corrected_java_probe: dict[str, Any] | None = None
        wrapped = report.get("wrapped_application", {})
        rebuilt_name = wrapped.get("rebuilt_jar")
        main_entries = wrapped.get("main_class_entries") or []
        if not alias_probe.get("ui_reachable") and java and rebuilt_name and main_entries:
            rebuilt_jar = (
                args.report.parent / "wrapped-application" / str(rebuilt_name)
            ).resolve()
            if not rebuilt_jar.exists():
                raise FileNotFoundError(f"rebuilt wrapped JAR missing: {rebuilt_jar}")
            classpath = [rebuilt_jar] + sorted(application.parent.glob("*.jar"))
            direct_environment = dict(environment)
            direct_environment["JAVA_TOOL_OPTIONS"] = (
                "-Djava.net.useSystemProxies=true "
                "-Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=9 "
                "-Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=9"
            )
            corrected_java_probe = base.probe_process(
                [
                    str(java),
                    "-Dfile.encoding=UTF-8",
                    "-cp",
                    os.pathsep.join(str(path.resolve()) for path in classpath),
                    "Main",
                ],
                cwd=application.parent,
                environment=direct_environment,
                output_dir=args.output / "diagnostic-java-absolute-classpath",
                label="diagnostic-java-absolute-classpath",
                observation_seconds=args.observation_seconds,
            )
            corrected_java_probe["eligibility"] = (
                "diagnostic_only_not_an_official_black_box_observation"
            )
            result["diagnostic_java_absolute_classpath_probe"] = corrected_java_probe

        if alias_probe.get("ui_reachable"):
            result["status"] = "BYTE_IDENTICAL_ASCII_ALIAS_UI_REACHED"
            result["next_gate"] = (
                "Use the recorded UI Automation model to select the frozen synthetic input and invoke one real validation transaction."
            )
        elif corrected_java_probe and corrected_java_probe.get("ui_reachable"):
            result["status"] = "DIRECT_JAVA_DIAGNOSTIC_UI_REACHED_ALIAS_WRAPPER_UNRESOLVED"
            result["next_gate"] = (
                "Compare the successful direct-Java command with Launch4j arguments and restore the official wrapper path before counting observations."
            )
        else:
            result["status"] = "ASCII_ALIAS_AND_CORRECTED_JAVA_UI_NOT_REACHED"
            result["next_gate"] = (
                "Inspect the preserved stderr, Launch4j log, process timeline and UI Automation output; do not increment observation counters."
            )
    except Exception as exc:
        result["status"] = "ASCII_ALIAS_PROBE_FAILED_CLOSED"
        result["errors"].append(
            {
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": base.traceback.format_exc(),
            }
        )
        result["next_gate"] = (
            "Repair the failed precondition using raw evidence; do not increment observation counters."
        )
    finally:
        for record in reversed(firewall_rules):
            base.remove_firewall_rule(record)
        base.write_json(args.output / "ascii-alias-probe.json", result)

        report["ascii_alias_probe"] = result
        report["status"] = result["status"]
        report["next_gate"] = result["next_gate"]
        report.setdefault("observation_counters", {})[
            "official_black_box_observations"
        ] = 0
        report.setdefault("assertions", {})["validation_invoked"] = False
        report["assertions"]["native_validation_report_present"] = False
        base.write_json(args.report, report)

        summary = {
            "status": result["status"],
            "alias_method": result.get("alias_identity", {}).get("method"),
            "alias_samefile": result.get("alias_identity", {}).get("samefile"),
            "alias_byte_identical": result.get("alias_identity", {}).get("byte_identical"),
            "alias_ui_reached": result.get("ascii_alias_probe", {}).get("ui_reachable"),
            "alias_class_not_found_main": result.get("ascii_alias_probe", {}).get("class_not_found_main"),
            "launch4j_log_mentions_ascii_alias": result.get("ascii_alias_probe", {}).get("launch4j_log_mentions_ascii_alias"),
            "corrected_java_ui_reached": result.get(
                "diagnostic_java_absolute_classpath_probe", {}
            ).get("ui_reachable"),
            "official_black_box_observations": 0,
            "next_gate": result.get("next_gate"),
        }
        base.write_json(args.output / "ASCII_ALIAS_SUMMARY.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
