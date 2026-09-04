from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
import uuid
import zipfile
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_path(path: Path) -> str:
    return str(path.resolve()).replace("/", "\\")


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def inventory(root: Path, *, hash_limit: int = 80 * 1024 * 1024) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda p: str(p).lower()):
        try:
            stat = path.stat()
            records.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": stat.st_size,
                    "last_write_utc": dt.datetime.fromtimestamp(
                        stat.st_mtime, tz=dt.timezone.utc
                    ).isoformat(),
                    "sha256": sha256_file(path) if stat.st_size <= hash_limit else None,
                }
            )
        except OSError as exc:
            records.append(
                {
                    "path": str(path),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return records


def inventory_digest(records: Iterable[dict[str, Any]]) -> str:
    canonical = "\n".join(
        f"{item.get('path')}\t{item.get('size')}\t{item.get('sha256')}"
        for item in records
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def scrubbed_environment() -> tuple[dict[str, str], list[str]]:
    environment = dict(os.environ)
    explicit = {
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
        "ACTIONS_ID_TOKEN_REQUEST_URL",
        "ACTIONS_RUNTIME_TOKEN",
        "ACTIONS_RESULTS_URL",
        "SYSTEM_ACCESSTOKEN",
    }
    removed: list[str] = []
    for key in list(environment):
        upper = key.upper()
        sensitive_suffix = upper.endswith(("_TOKEN", "_SECRET", "_PASSWORD", "_API_KEY"))
        if upper in explicit or sensitive_suffix:
            removed.append(key)
            environment.pop(key, None)
    environment.update(
        {
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "localhost,127.0.0.1",
        }
    )
    return environment, sorted(removed)


def powershell_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def run_powershell(command: str, *, timeout: int = 120) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return {
        "return_code": completed.returncode,
        "stdout": completed.stdout[-20000:],
        "stderr": completed.stderr[-20000:],
    }


def add_firewall_rule(program: Path, label: str) -> dict[str, Any]:
    name = f"EZCTD-Forensics-{label}-{uuid.uuid4().hex}"
    result: dict[str, Any] = {
        "name": name,
        "program": canonical_path(program),
        "status": "NOT_ATTEMPTED",
    }
    if not program.exists():
        result["status"] = "PROGRAM_MISSING"
        return result
    command = (
        f"New-NetFirewallRule -DisplayName {powershell_quote(name)} "
        f"-Direction Outbound -Program {powershell_quote(canonical_path(program))} "
        "-Action Block -Profile Any -ErrorAction Stop | Out-Null"
    )
    try:
        detail = run_powershell(command)
        result["detail"] = detail
        result["status"] = "BLOCKED_OUTBOUND" if detail["return_code"] == 0 else "RULE_FAILED"
    except Exception as exc:  # pragma: no cover - Windows integration
        result.update(
            {
                "status": "RULE_FAILED",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
    return result


def remove_firewall_rule(record: dict[str, Any]) -> None:
    if record.get("status") != "BLOCKED_OUTBOUND":
        return
    try:
        run_powershell(
            f"Remove-NetFirewallRule -DisplayName {powershell_quote(str(record['name']))} "
            "-ErrorAction SilentlyContinue",
            timeout=60,
        )
    except Exception:
        pass


def uninstall_registry_snapshot() -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    import winreg

    locations = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", winreg.KEY_WOW64_64KEY, "HKLM64"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", winreg.KEY_WOW64_32KEY, "HKLM32"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0, "HKCU"),
    ]
    value_names = [
        "DisplayName",
        "DisplayVersion",
        "Publisher",
        "InstallLocation",
        "UninstallString",
        "QuietUninstallString",
        "InstallDate",
    ]
    records: list[dict[str, Any]] = []
    for hive, key_path, view, hive_name in locations:
        try:
            root = winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            count = winreg.QueryInfoKey(root)[0]
            for index in range(count):
                try:
                    subkey_name = winreg.EnumKey(root, index)
                    with winreg.OpenKey(root, subkey_name) as subkey:
                        record: dict[str, Any] = {
                            "hive": hive_name,
                            "key": subkey_name,
                        }
                        for name in value_names:
                            try:
                                record[name] = winreg.QueryValueEx(subkey, name)[0]
                            except OSError:
                                record[name] = None
                        if record.get("DisplayName") or record.get("InstallLocation"):
                            records.append(record)
                except OSError:
                    continue
    return sorted(
        records,
        key=lambda item: (
            str(item.get("hive") or ""),
            str(item.get("DisplayName") or "").lower(),
            str(item.get("key") or "").lower(),
        ),
    )


def diff_registry(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def identity(item: dict[str, Any]) -> tuple[str, str]:
        return str(item.get("hive")), str(item.get("key"))

    before_map = {identity(item): item for item in before}
    return [item for item in after if identity(item) not in before_map or before_map[identity(item)] != item]


def executable_candidates(install_dir: Path, registry_delta: list[dict[str, Any]]) -> list[Path]:
    roots: list[Path] = []
    if install_dir.exists():
        roots.append(install_dir)
    for record in registry_delta:
        location = record.get("InstallLocation")
        if location:
            candidate = Path(str(location))
            if candidate.exists() and candidate not in roots:
                roots.append(candidate)
    candidates: list[Path] = []
    for root in roots:
        try:
            for path in root.rglob("*.exe"):
                if path.name.lower().startswith("ectd") and "uninst" not in path.name.lower():
                    candidates.append(path)
        except OSError:
            continue
    return sorted(set(candidates), key=lambda path: (len(str(path)), str(path).lower()))


def inspect_wrapped_application(application: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "application": canonical_path(application),
        "application_sha256": sha256_file(application),
        "zip_readable": False,
        "entry_count": 0,
        "main_class_entries": [],
        "manifest": None,
        "rebuilt_jar": None,
        "error": None,
    }
    try:
        with zipfile.ZipFile(application) as archive:
            infos = archive.infolist()
            result["zip_readable"] = True
            result["entry_count"] = len(infos)
            members: list[dict[str, Any]] = []
            main_entries: list[str] = []
            for info in infos:
                normalized = info.filename.replace("\\", "/")
                members.append(
                    {
                        "name": normalized,
                        "size": info.file_size,
                        "compressed_size": info.compress_size,
                        "crc": f"{info.CRC:08x}",
                    }
                )
                if normalized.lower().endswith("/main.class") or normalized.lower() == "main.class":
                    main_entries.append(normalized)
            result["main_class_entries"] = main_entries
            if "META-INF/MANIFEST.MF" in archive.namelist():
                result["manifest"] = archive.read("META-INF/MANIFEST.MF").decode(
                    "utf-8", errors="replace"
                )

            write_json(output_dir / "wrapped-members.json", members)
            jar_path = output_dir / "wrapped-application.jar"
            with zipfile.ZipFile(jar_path, "w") as rebuilt:
                for info in infos:
                    name = info.filename.replace("\\", "/")
                    destination = (output_dir / "safe-check" / name).resolve()
                    safe_root = (output_dir / "safe-check").resolve()
                    if destination != safe_root and safe_root not in destination.parents:
                        raise ValueError(f"unsafe wrapped archive path: {name}")
                    data = archive.read(info)
                    clone = zipfile.ZipInfo(filename=name, date_time=info.date_time)
                    clone.compress_type = info.compress_type
                    clone.external_attr = info.external_attr
                    clone.comment = info.comment
                    clone.extra = info.extra
                    rebuilt.writestr(clone, data)
            result["rebuilt_jar"] = jar_path.name
            result["rebuilt_jar_sha256"] = sha256_file(jar_path)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    write_json(output_dir / "wrapped-application-inspection.json", result)
    return result


def process_records(root_pid: int, scope_root: Path, known_pids: set[int]) -> list[dict[str, Any]]:
    import psutil

    scope = os.path.normcase(canonical_path(scope_root) + "\\")
    try:
        root = psutil.Process(root_pid)
        known_pids.add(root_pid)
        for child in root.children(recursive=True):
            known_pids.add(child.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass

    records: list[dict[str, Any]] = []
    for process in psutil.process_iter(
        ["pid", "ppid", "name", "exe", "cmdline", "create_time", "status"]
    ):
        try:
            info = process.info
            executable = str(info.get("exe") or "")
            in_scope = bool(executable) and os.path.normcase(executable).startswith(scope)
            if int(info["pid"]) not in known_pids and not in_scope:
                continue
            known_pids.add(int(info["pid"]))
            records.append(
                {
                    "pid": int(info["pid"]),
                    "ppid": int(info.get("ppid") or 0),
                    "name": info.get("name"),
                    "exe": executable or None,
                    "cmdline": info.get("cmdline") or [],
                    "create_time_utc": dt.datetime.fromtimestamp(
                        float(info.get("create_time") or 0), tz=dt.timezone.utc
                    ).isoformat()
                    if info.get("create_time")
                    else None,
                    "status": info.get("status"),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return sorted(records, key=lambda item: item["pid"])


def window_records(process_ids: set[int]) -> list[dict[str, Any]]:
    if os.name != "nt":
        return []
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    records: list[dict[str, Any]] = []

    def callback(handle: int, _lparam: int) -> bool:
        process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(process_id))
        if int(process_id.value) not in process_ids:
            return True
        title_length = user32.GetWindowTextLengthW(handle)
        title_buffer = ctypes.create_unicode_buffer(max(title_length + 1, 2))
        user32.GetWindowTextW(handle, title_buffer, len(title_buffer))
        class_buffer = ctypes.create_unicode_buffer(512)
        user32.GetClassNameW(handle, class_buffer, len(class_buffer))
        records.append(
            {
                "handle": int(handle),
                "pid": int(process_id.value),
                "visible": bool(user32.IsWindowVisible(handle)),
                "title": title_buffer.value,
                "class_name": class_buffer.value,
            }
        )
        return True

    callback_reference = enum_proc_type(callback)
    user32.EnumWindows(callback_reference, 0)
    return sorted(records, key=lambda item: (item["pid"], item["handle"]))


def uia_records(process_ids: set[int]) -> dict[str, Any]:
    try:
        from pywinauto import Desktop

        windows: list[dict[str, Any]] = []
        for wrapper in Desktop(backend="uia").windows():
            try:
                process_id = int(wrapper.process_id())
                if process_id not in process_ids:
                    continue
                descendants: list[dict[str, Any]] = []
                for child in wrapper.descendants()[:1200]:
                    try:
                        info = child.element_info
                        descendants.append(
                            {
                                "name": info.name,
                                "automation_id": info.automation_id,
                                "control_type": info.control_type,
                                "class_name": info.class_name,
                                "enabled": child.is_enabled(),
                                "visible": child.is_visible(),
                            }
                        )
                    except Exception:
                        continue
                info = wrapper.element_info
                windows.append(
                    {
                        "pid": process_id,
                        "name": info.name,
                        "automation_id": info.automation_id,
                        "control_type": info.control_type,
                        "class_name": info.class_name,
                        "descendant_count": len(descendants),
                        "descendants": descendants,
                    }
                )
            except Exception:
                continue
        return {"status": "CAPTURED", "windows": windows, "error": None}
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "windows": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def save_screenshot(path: Path) -> dict[str, Any]:
    try:
        from PIL import ImageGrab

        image = ImageGrab.grab(all_screens=True)
        image.save(path)
        return {
            "status": "CAPTURED",
            "path": path.name,
            "width": image.width,
            "height": image.height,
            "sha256": sha256_file(path),
            "error": None,
        }
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "path": None,
            "width": None,
            "height": None,
            "sha256": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


def terminate_scope(process_ids: set[int]) -> None:
    import psutil

    processes = []
    for process_id in sorted(process_ids, reverse=True):
        try:
            processes.append(psutil.Process(process_id))
        except psutil.NoSuchProcess:
            continue
    for process in processes:
        try:
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    _, alive = psutil.wait_procs(processes, timeout=8)
    for process in alive:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass


def find_recent_logs(root: Path, started_epoch: float, output_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not root.exists():
        return records
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        lower = path.name.lower()
        if stat.st_mtime < started_epoch - 2 and lower != "launch4j.log":
            continue
        if not (lower.endswith((".log", ".txt", ".xml", ".json", ".html")) or lower == "launch4j.log"):
            continue
        destination = output_dir / "captured-files" / path.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(path, destination)
            records.append(
                {
                    "source": canonical_path(path),
                    "captured_as": destination.relative_to(output_dir).as_posix(),
                    "size": stat.st_size,
                    "sha256": sha256_file(destination),
                }
            )
        except OSError as exc:
            records.append(
                {
                    "source": canonical_path(path),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return records


def probe_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    output_dir: Path,
    label: str,
    observation_seconds: int,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / f"{label}.stdout.txt"
    stderr_path = output_dir / f"{label}.stderr.txt"
    started_epoch = time.time()
    result: dict[str, Any] = {
        "label": label,
        "command": command,
        "cwd": canonical_path(cwd),
        "started_at": utc_now(),
        "start_succeeded": False,
        "root_pid": None,
        "samples": [],
        "windows": [],
        "uia": {"status": "NOT_RUN", "windows": []},
        "screenshot": None,
        "captured_files": [],
        "error": None,
    }
    known_pids: set[int] = set()
    process: subprocess.Popen[bytes] | None = None
    try:
        with stdout_path.open("wb") as stdout_stream, stderr_path.open("wb") as stderr_stream:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=environment,
                stdout=stdout_stream,
                stderr=stderr_stream,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            result["start_succeeded"] = True
            result["root_pid"] = process.pid
            known_pids.add(process.pid)
            deadline = time.time() + observation_seconds
            sample_number = 0
            while time.time() < deadline:
                time.sleep(2)
                sample_number += 1
                processes = process_records(process.pid, cwd, known_pids)
                windows = window_records({item["pid"] for item in processes})
                result["samples"].append(
                    {
                        "sample": sample_number,
                        "elapsed_seconds": round(time.time() - started_epoch, 3),
                        "processes": processes,
                        "windows": windows,
                        "root_return_code": process.poll(),
                    }
                )
                if process.poll() is not None and not processes:
                    break

        unique_processes: dict[int, dict[str, Any]] = {}
        unique_windows: dict[int, dict[str, Any]] = {}
        for sample in result["samples"]:
            for item in sample["processes"]:
                unique_processes[int(item["pid"])] = item
            for item in sample["windows"]:
                unique_windows[int(item["handle"])] = item
        result["processes"] = [unique_processes[key] for key in sorted(unique_processes)]
        result["windows"] = [
            unique_windows[key]
            for key in sorted(unique_windows, key=lambda value: (unique_windows[value]["pid"], value))
        ]
        final_ids = set(unique_processes) | known_pids
        result["uia"] = uia_records(final_ids)
        result["screenshot"] = save_screenshot(output_dir / f"{label}.png")
        result["captured_files"] = find_recent_logs(cwd, started_epoch, output_dir)
        result["root_return_code"] = process.poll() if process else None
        result["visible_window_count"] = len(
            [item for item in result["windows"] if item.get("visible") and item.get("title")]
        )
        result["uia_descendant_count"] = sum(
            int(window.get("descendant_count") or 0)
            for window in result["uia"].get("windows", [])
        )
        result["ui_reachable"] = bool(
            result["visible_window_count"] > 0 or result["uia_descendant_count"] > 0
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()
    finally:
        terminate_scope(known_pids)
        result["finished_at"] = utc_now()
        if stdout_path.exists():
            result["stdout_sha256"] = sha256_file(stdout_path)
        if stderr_path.exists():
            result["stderr_sha256"] = sha256_file(stderr_path)
        write_json(output_dir / f"{label}.json", result)
    return result


def find_bundled_java(root: Path) -> Path | None:
    preferred = root / "jre" / "jre1.8.0_202" / "bin" / "java.exe"
    if preferred.exists():
        return preferred
    candidates = sorted(root.rglob("java.exe"), key=lambda path: len(str(path)))
    return candidates[0] if candidates else None


def read_text_safely(path: Path, limit: int = 200000) -> str:
    if not path.exists():
        return ""
    data = path.read_bytes()[:limit]
    for encoding in ("utf-8-sig", "utf-16", "gb18030", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--static-payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--install-dir", type=Path, default=Path(r"C:\CDEValidatorForensics"))
    parser.add_argument("--expected-installer-sha256", required=True)
    parser.add_argument("--expected-app-sha256", required=True)
    parser.add_argument("--observation-seconds", type=int, default=45)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": "0.1.0",
        "run_id": f"cde-validator-forensics-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        "run_type": "installed_layout_and_launch_forensics",
        "status": "STARTED",
        "started_at": utc_now(),
        "safety": {
            "uses_synthetic_or_no_input_only": True,
            "validation_invoked": False,
            "native_validation_report_present": False,
            "credentials_exposed_to_child": False,
        },
        "observation_counters": {
            "launch_forensics_runs": 1,
            "completed_validation_runs": 0,
            "admissible_black_box_observations": 0,
            "calibration_informative_observations": 0,
            "official_black_box_observations": 0,
        },
        "errors": [],
    }
    firewall_rules: list[dict[str, Any]] = []

    try:
        installer = args.installer.resolve()
        static_payload = args.static_payload.resolve()
        install_dir = args.install_dir
        report["paths"] = {
            "installer": canonical_path(installer),
            "static_payload": canonical_path(static_payload),
            "requested_install_dir": canonical_path(install_dir),
        }
        report["identity"] = {
            "installer_sha256": sha256_file(installer),
            "expected_installer_sha256": args.expected_installer_sha256.lower(),
        }
        if report["identity"]["installer_sha256"] != report["identity"]["expected_installer_sha256"]:
            raise ValueError("installer SHA-256 mismatch")

        static_apps = sorted(
            path
            for path in static_payload.glob("eCTD*.exe")
            if "uninst" not in path.name.lower()
        )
        if len(static_apps) != 1:
            raise ValueError(f"expected one static application entry point, found {len(static_apps)}")
        static_app = static_apps[0]
        report["identity"].update(
            {
                "static_application": canonical_path(static_app),
                "static_application_sha256": sha256_file(static_app),
                "expected_application_sha256": args.expected_app_sha256.lower(),
            }
        )
        if report["identity"]["static_application_sha256"] != report["identity"]["expected_application_sha256"]:
            raise ValueError("static application SHA-256 mismatch")

        environment, removed_names = scrubbed_environment()
        report["safety"]["removed_environment_names"] = removed_names

        registry_before = uninstall_registry_snapshot()
        write_json(args.output / "uninstall-registry-before.json", registry_before)
        static_inventory_before = inventory(static_payload)
        write_json(args.output / "static-payload-before.json", static_inventory_before)
        report["identity"]["static_payload_digest_before"] = inventory_digest(static_inventory_before)

        for program, label in [
            (installer, "installer"),
            (static_app, "static-wrapper"),
            (find_bundled_java(static_payload), "static-java"),
            (
                static_payload / "jre" / "jre1.8.0_202" / "bin" / "javaw.exe",
                "static-javaw",
            ),
        ]:
            if program is None:
                continue
            firewall_rules.append(add_firewall_rule(program, label))
        report["safety"]["firewall_rules_before_install"] = firewall_rules.copy()
        firewall_ready = all(
            record.get("status") == "BLOCKED_OUTBOUND"
            for record in firewall_rules
            if record.get("status") != "PROGRAM_MISSING"
        )
        report["safety"]["firewall_ready_before_install"] = firewall_ready
        if not firewall_ready:
            raise RuntimeError("outbound firewall safety gate failed before installer execution")

        if install_dir.exists():
            shutil.rmtree(install_dir)
        install_dir.parent.mkdir(parents=True, exist_ok=True)
        install_started = time.time()
        install_command = [str(installer), "/S", f"/D={install_dir}"]
        report["installation"] = {
            "command": install_command,
            "started_at": utc_now(),
            "executed": True,
        }
        completed = subprocess.run(
            install_command,
            cwd=str(installer.parent),
            env=environment,
            capture_output=True,
            timeout=420,
            check=False,
        )
        (args.output / "installer.stdout.bin").write_bytes(completed.stdout)
        (args.output / "installer.stderr.bin").write_bytes(completed.stderr)
        report["installation"].update(
            {
                "return_code": completed.returncode,
                "finished_at": utc_now(),
                "requested_directory_exists": install_dir.exists(),
            }
        )
        time.sleep(5)

        registry_after = uninstall_registry_snapshot()
        registry_delta = diff_registry(registry_before, registry_after)
        write_json(args.output / "uninstall-registry-after.json", registry_after)
        write_json(args.output / "uninstall-registry-delta.json", registry_delta)
        report["installation"]["registry_delta"] = registry_delta

        install_inventory = inventory(install_dir)
        write_json(args.output / "installed-tree.json", install_inventory)
        report["installation"].update(
            {
                "installed_file_count": len(install_inventory),
                "installed_tree_digest": inventory_digest(install_inventory),
            }
        )

        candidates = executable_candidates(install_dir, registry_delta)
        candidate_records = []
        installed_app: Path | None = None
        for candidate in candidates:
            candidate_hash = sha256_file(candidate)
            record = {
                "path": canonical_path(candidate),
                "size": candidate.stat().st_size,
                "sha256": candidate_hash,
                "matches_expected_application": candidate_hash
                == args.expected_app_sha256.lower(),
            }
            candidate_records.append(record)
            if record["matches_expected_application"] and installed_app is None:
                installed_app = candidate
        report["installation"]["application_candidates"] = candidate_records
        if installed_app is None:
            raise RuntimeError("installed application with expected SHA-256 was not found")
        report["identity"]["installed_application"] = canonical_path(installed_app)
        report["identity"]["installed_application_sha256"] = sha256_file(installed_app)
        report["identity"]["installed_matches_static"] = (
            report["identity"]["installed_application_sha256"]
            == report["identity"]["static_application_sha256"]
        )

        wrapped = inspect_wrapped_application(installed_app, args.output / "wrapped-application")
        report["wrapped_application"] = wrapped

        installed_root = installed_app.parent
        installed_java = find_bundled_java(installed_root)
        installed_javaw = installed_root / "jre" / "jre1.8.0_202" / "bin" / "javaw.exe"
        for program, label in [
            (installed_app, "installed-wrapper"),
            (installed_java, "installed-java"),
            (installed_javaw, "installed-javaw"),
        ]:
            if program is None:
                continue
            firewall_rules.append(add_firewall_rule(program, label))
        report["safety"]["firewall_rules_all"] = firewall_rules
        launch_rules = [
            record
            for record in firewall_rules
            if record.get("name", "").find("installed-") >= 0
        ]
        report["safety"]["firewall_ready_for_launch"] = all(
            record.get("status") == "BLOCKED_OUTBOUND"
            for record in launch_rules
            if record.get("status") != "PROGRAM_MISSING"
        )
        if not report["safety"]["firewall_ready_for_launch"]:
            raise RuntimeError("outbound firewall safety gate failed before application launch")

        wrapper_environment = dict(environment)
        wrapper_environment["Launch4j"] = "debug-all"
        wrapper_probe = probe_process(
            [str(installed_app), "--l4j-debug"],
            cwd=installed_root,
            environment=wrapper_environment,
            output_dir=args.output / "official-wrapper",
            label="official-wrapper",
            observation_seconds=args.observation_seconds,
        )
        report["official_wrapper_probe"] = wrapper_probe
        report["safety"]["official_wrapper_process_started"] = bool(
            wrapper_probe.get("start_succeeded")
        )
        report["safety"]["official_wrapper_ui_reached"] = bool(
            wrapper_probe.get("ui_reachable")
        )

        wrapper_text = "\n".join(
            [
                read_text_safely(args.output / "official-wrapper" / "official-wrapper.stdout.txt"),
                read_text_safely(args.output / "official-wrapper" / "official-wrapper.stderr.txt"),
            ]
        )
        for captured in wrapper_probe.get("captured_files", []):
            captured_path = captured.get("captured_as")
            if captured_path:
                wrapper_text += "\n" + read_text_safely(
                    args.output / "official-wrapper" / captured_path
                )
        report["official_wrapper_probe"]["class_not_found_main"] = (
            "Could not find or load main class Main" in wrapper_text
        )

        direct_java_probe: dict[str, Any] | None = None
        rebuilt_name = wrapped.get("rebuilt_jar")
        main_entries = wrapped.get("main_class_entries") or []
        if not wrapper_probe.get("ui_reachable") and installed_java and rebuilt_name and main_entries:
            rebuilt_jar = args.output / "wrapped-application" / str(rebuilt_name)
            classpath = [rebuilt_jar] + sorted(installed_root.glob("*.jar"))
            direct_environment = dict(environment)
            direct_environment["JAVA_TOOL_OPTIONS"] = (
                "-Djava.net.useSystemProxies=true "
                "-Dhttp.proxyHost=127.0.0.1 -Dhttp.proxyPort=9 "
                "-Dhttps.proxyHost=127.0.0.1 -Dhttps.proxyPort=9"
            )
            direct_java_probe = probe_process(
                [
                    str(installed_java),
                    "-Dfile.encoding=UTF-8",
                    "-cp",
                    os.pathsep.join(str(path) for path in classpath),
                    "Main",
                ],
                cwd=installed_root,
                environment=direct_environment,
                output_dir=args.output / "diagnostic-java-adapter",
                label="diagnostic-java-adapter",
                observation_seconds=args.observation_seconds,
            )
            direct_java_probe["eligibility"] = (
                "diagnostic_only_not_an_official_black_box_observation"
            )
            report["diagnostic_java_adapter_probe"] = direct_java_probe

        static_inventory_after = inventory(static_payload)
        write_json(args.output / "static-payload-after.json", static_inventory_after)
        report["identity"]["static_payload_digest_after"] = inventory_digest(static_inventory_after)
        report["identity"]["static_payload_unchanged"] = (
            report["identity"]["static_payload_digest_before"]
            == report["identity"]["static_payload_digest_after"]
        )

        if wrapper_probe.get("ui_reachable"):
            report["status"] = "OFFICIAL_INSTALLED_WRAPPER_UI_REACHED"
            report["next_gate"] = (
                "Build a deterministic synthetic-input UI adapter and complete the first real validation transaction."
            )
        elif direct_java_probe and direct_java_probe.get("ui_reachable"):
            report["status"] = "DIAGNOSTIC_JAVA_ADAPTER_UI_REACHED_OFFICIAL_WRAPPER_UNRESOLVED"
            report["next_gate"] = (
                "Use the recovered UI model to repair the official wrapper launch, then invoke validation through the official entry point."
            )
        elif report["official_wrapper_probe"].get("class_not_found_main"):
            report["status"] = "OFFICIAL_WRAPPER_MAIN_CLASS_FAILURE_CONFIRMED_AFTER_INSTALL"
            report["next_gate"] = (
                "Use Launch4j debug output and wrapped-application inventory to resolve the missing Main class without claiming validation."
            )
        else:
            report["status"] = "INSTALLATION_COMPLETED_APPLICATION_UI_NOT_REACHED"
            report["next_gate"] = (
                "Review raw process, window, UI Automation and Launch4j logs before another execution attempt."
            )

        report["installation"]["files_modified_since_install_start"] = [
            item
            for item in install_inventory
            if item.get("last_write_utc")
            and dt.datetime.fromisoformat(str(item["last_write_utc"])).timestamp()
            >= install_started - 2
        ][:500]
    except Exception as exc:
        report["status"] = "FORENSICS_FAILED_CLOSED"
        report["errors"].append(
            {
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        )
        report.setdefault(
            "next_gate",
            "Repair the failed precondition using the preserved raw evidence; do not increment black-box counters.",
        )
    finally:
        for record in reversed(firewall_rules):
            remove_firewall_rule(record)
        report["finished_at"] = utc_now()
        report["assertions"] = {
            "validation_invoked": False,
            "native_validation_report_present": False,
            "completed_validation_runs": 0,
            "official_black_box_observations": 0,
        }
        write_json(args.output / "install-and-launch-forensics.json", report)
        summary = {
            "run_id": report["run_id"],
            "status": report["status"],
            "installation_return_code": report.get("installation", {}).get("return_code"),
            "installed_application": report.get("identity", {}).get("installed_application"),
            "installed_matches_static": report.get("identity", {}).get("installed_matches_static"),
            "wrapped_zip_readable": report.get("wrapped_application", {}).get("zip_readable"),
            "wrapped_main_entries": report.get("wrapped_application", {}).get("main_class_entries", []),
            "official_wrapper_started": report.get("official_wrapper_probe", {}).get("start_succeeded"),
            "official_wrapper_ui_reached": report.get("official_wrapper_probe", {}).get("ui_reachable"),
            "class_not_found_main": report.get("official_wrapper_probe", {}).get("class_not_found_main"),
            "diagnostic_java_ui_reached": report.get("diagnostic_java_adapter_probe", {}).get("ui_reachable"),
            "official_black_box_observations": 0,
            "next_gate": report.get("next_gate"),
        }
        write_json(args.output / "SUMMARY.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
