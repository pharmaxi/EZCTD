from __future__ import annotations

import argparse
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


def write_output(path: Path | None, key: str, value: str) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"{key}={value}\n")


def find_expected_application(root: Path, expected_sha256: str) -> Path:
    matches = []
    for path in root.rglob("*.exe"):
        try:
            if base.sha256_file(path) == expected_sha256:
                matches.append(path)
        except OSError:
            continue
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one installed application with SHA-256 {expected_sha256}, found {len(matches)}"
        )
    return matches[0]


def create_hardlink(source: Path, alias: Path) -> dict[str, Any]:
    if alias.exists() or alias.is_symlink():
        alias.unlink()
    os.link(source, alias)
    source_hash = base.sha256_file(source)
    alias_hash = base.sha256_file(alias)
    return {
        "source": base.canonical_path(source),
        "alias": base.canonical_path(alias),
        "method": "ntfs_hardlink",
        "samefile": os.path.samefile(source, alias),
        "source_sha256": source_hash,
        "alias_sha256": alias_hash,
        "byte_identical": source_hash == alias_hash,
    }


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--install-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-installer-sha256", required=True)
    parser.add_argument("--expected-app-sha256", required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "schema_version": "0.1.0",
        "run_type": "official_validator_transaction_runtime_preparation",
        "status": "STARTED",
        "application_executed": False,
        "validation_invoked": False,
        "official_black_box_observations": 0,
        "errors": [],
    }
    firewall_rule: dict[str, Any] | None = None

    try:
        installer = args.installer.resolve()
        install_dir = args.install_dir
        expected_installer = args.expected_installer_sha256.lower()
        expected_app = args.expected_app_sha256.lower()
        installer_hash = base.sha256_file(installer)
        report["identity"] = {
            "installer": base.canonical_path(installer),
            "installer_sha256": installer_hash,
            "expected_installer_sha256": expected_installer,
            "expected_application_sha256": expected_app,
        }
        if installer_hash != expected_installer:
            raise ValueError("installer SHA-256 mismatch")

        environment, removed_names = base.scrubbed_environment()
        report["safety"] = {
            "removed_environment_names": removed_names,
            "credentials_exposed_to_installer": False,
        }
        firewall_rule = base.add_firewall_rule(installer, "transaction-installer")
        report["safety"]["installer_firewall_rule"] = firewall_rule
        report["safety"]["installer_outbound_blocked"] = (
            firewall_rule.get("status") == "BLOCKED_OUTBOUND"
        )
        if not report["safety"]["installer_outbound_blocked"]:
            raise RuntimeError("installer outbound firewall safety gate failed")

        if install_dir.exists():
            shutil.rmtree(install_dir)
        install_dir.parent.mkdir(parents=True, exist_ok=True)
        command = [str(installer), "/S", f"/D={install_dir}"]
        started = time.time()
        completed = subprocess.run(
            command,
            cwd=str(installer.parent),
            env=environment,
            capture_output=True,
            timeout=420,
            check=False,
        )
        (args.output / "installer.stdout.bin").write_bytes(completed.stdout)
        (args.output / "installer.stderr.bin").write_bytes(completed.stderr)
        time.sleep(4)
        report["installation"] = {
            "command": command,
            "return_code": completed.returncode,
            "duration_seconds": round(time.time() - started, 3),
            "install_directory": base.canonical_path(install_dir),
            "install_directory_exists": install_dir.exists(),
        }
        if completed.returncode != 0 or not install_dir.exists():
            raise RuntimeError(
                f"silent installation failed: return_code={completed.returncode}, exists={install_dir.exists()}"
            )

        installed_app = find_expected_application(install_dir, expected_app)
        alias = installed_app.parent / "CDEValidator.exe"
        alias_record = create_hardlink(installed_app, alias)
        if not alias_record["samefile"] or not alias_record["byte_identical"]:
            raise RuntimeError("ASCII hardlink did not conserve official application bytes")
        if alias_record["alias_sha256"] != expected_app:
            raise RuntimeError("ASCII alias application SHA-256 mismatch")

        installed_inventory = base.inventory(install_dir)
        report["installation"].update(
            {
                "installed_file_count": len(installed_inventory),
                "installed_inventory_digest": base.inventory_digest(installed_inventory),
                "installed_application": base.canonical_path(installed_app),
                "ascii_alias": base.canonical_path(alias),
            }
        )
        report["alias_identity"] = alias_record
        base.write_json(args.output / "installed-inventory.json", installed_inventory)

        report["status"] = "CLEAN_TRANSACTION_RUNTIME_READY"
        report["outputs"] = {
            "application_alias": base.canonical_path(alias),
            "original_application": base.canonical_path(installed_app),
            "application_dir": base.canonical_path(installed_app.parent),
            "install_dir": base.canonical_path(install_dir),
        }
        for key, value in report["outputs"].items():
            write_output(args.github_output, key, value)
    except Exception as exc:
        report["status"] = "TRANSACTION_RUNTIME_PREPARATION_FAILED_CLOSED"
        report["errors"].append(
            {
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            }
        )
    finally:
        if firewall_rule is not None:
            base.remove_firewall_rule(firewall_rule)
        base.write_json(args.output / "runtime-preparation.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))

    return 0 if report["status"] == "CLEAN_TRANSACTION_RUNTIME_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
