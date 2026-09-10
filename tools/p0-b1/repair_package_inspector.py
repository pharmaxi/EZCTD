from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "tools" / "ectd" / "inspect_baseline_candidate.py"
TEST = ROOT / "tests" / "p0_b1" / "test_baseline_candidate_inspector.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"patch point not found: {label}")
    return text.replace(old, new, 1)


text = TARGET.read_text(encoding="utf-8")
text = replace_once(
    text,
    '''def inventory(root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        records.append(
''',
    '''def inventory(root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        records.append(
''',
    "exclude symlink targets from inventory",
)

text = replace_once(
    text,
    '''    package_root = args.package_root.resolve()
    if not package_root.is_dir():
        raise SystemExit(f"package root not found: {package_root}")
    context_map = load_context_map(args.context_map)
    sequence_root, index_xml, structural_errors = find_sequence(package_root)
    records = inventory(package_root)
    hidden_files = [record["path"] for record in records if record["hidden"]]
''',
    '''    package_root = args.package_root.resolve()
    if not package_root.is_dir():
        raise SystemExit(f"package root not found: {package_root}")
    output_path = args.output.resolve()
    output_markdown = output_path.with_suffix(".md")
    for candidate in (output_path, output_markdown):
        try:
            candidate.relative_to(package_root)
        except ValueError:
            pass
        else:
            raise SystemExit(f"output must be outside the inspected package root: {candidate}")
    context_map = load_context_map(args.context_map)
    sequence_root, index_xml, structural_errors = find_sequence(package_root)
    symlinks = sorted(path.relative_to(package_root).as_posix() for path in package_root.rglob("*") if path.is_symlink())
    if symlinks:
        structural_errors.append({"kind": "symbolic-links-not-allowed", "paths": symlinks})
    records = inventory(package_root)
    before_hashes = {record["path"]: record["sha256"] for record in records}
    hidden_files = [record["path"] for record in records if record["hidden"]]
''',
    "output and symlink boundary",
)

text = replace_once(
    text,
    '''        payload = {
            "schema_version": "0.1.0",
            "status": "INVALID_CANDIDATE",
            "package_root_name": package_root.name,
            "inventory": records,
            "structural_errors": structural_errors,
            "official_validator": {"status": "NOT_RUN", "version": "1.1.0", "observations": 0},
        }
''',
    '''        after_records = inventory(package_root)
        after_hashes = {record["path"]: record["sha256"] for record in after_records}
        changed_paths = sorted(set(before_hashes) ^ set(after_hashes) | {path for path in before_hashes.keys() & after_hashes.keys() if before_hashes[path] != after_hashes[path]})
        payload = {
            "schema_version": "0.1.0",
            "status": "INVALID_CANDIDATE",
            "package_root_name": package_root.name,
            "inventory": records,
            "structural_errors": structural_errors,
            "read_only_integrity": {"status": "PASS" if not changed_paths else "FAIL", "changed_paths": changed_paths},
            "official_validator": {"status": "NOT_RUN", "version": "1.1.0", "observations": 0},
        }
''',
    "early read-only integrity",
)

text = replace_once(
    text,
    '''    all_pdf_findings = [finding for result in pdf_results for finding in result["findings"]]
    status = "CANDIDATE_READY_FOR_OFFICIAL_VALIDATOR"
    if structural_errors:
''',
    '''    all_pdf_findings = [finding for result in pdf_results for finding in result["findings"]]
    after_records = inventory(package_root)
    after_hashes = {record["path"]: record["sha256"] for record in after_records}
    changed_paths = sorted(set(before_hashes) ^ set(after_hashes) | {path for path in before_hashes.keys() & after_hashes.keys() if before_hashes[path] != after_hashes[path]})
    if changed_paths:
        structural_errors.append({"kind": "input-mutated-during-inspection", "paths": changed_paths})
    status = "CANDIDATE_READY_FOR_OFFICIAL_VALIDATOR"
    if structural_errors:
''',
    "final read-only integrity comparison",
)

text = replace_once(
    text,
    '''        "inventory": records,
        "index_md5": index_md5,
''',
    '''        "inventory": records,
        "read_only_integrity": {"status": "PASS" if not changed_paths else "FAIL", "changed_paths": changed_paths},
        "index_md5": index_md5,
''',
    "payload read-only integrity",
)

text = replace_once(
    text,
    '''        f"- Unmapped PDF contexts: {len(missing_context)}",
        "- CDE validator V1.1.0: **NOT_RUN**",
''',
    '''        f"- Unmapped PDF contexts: {len(missing_context)}",
        f"- Input files unchanged during inspection: {payload['read_only_integrity']['status']}",
        "- CDE validator V1.1.0: **NOT_RUN**",
''',
    "markdown read-only result",
)
TARGET.write_text(text, encoding="utf-8", newline="\n")

# Extend the package inspector self-test with explicit output-inside and symlink rejection.
test = TEST.read_text(encoding="utf-8")
anchor = '''        results.append({"case": "strict-context-missing", "status": no_context_payload["status"]})

    report = {"schema_version": "0.1.0", "status": "PASS", "tests": results}
'''
replacement = '''        results.append({"case": "strict-context-missing", "status": no_context_payload["status"]})

        output_inside_root = temp / "output-inside"
        package, context = make_package(output_inside_root, source_pdf, correct_leaf_checksum=True, context=True)
        forbidden_output = package / "inspection.json"
        forbidden_run = run_inspector(package, forbidden_output, context, strict=True)
        assert forbidden_run.returncode != 0
        assert not forbidden_output.exists()
        results.append({"case": "output-inside-package-rejected", "status": "PASS"})

        if hasattr(Path, "symlink_to"):
            symlink_root = temp / "symlink"
            package, context = make_package(symlink_root, source_pdf, correct_leaf_checksum=True, context=True)
            outside = symlink_root / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            link = package / "0000" / "linked.txt"
            try:
                link.symlink_to(outside)
            except OSError:
                results.append({"case": "symbolic-link-rejection", "status": "SKIPPED_PLATFORM"})
            else:
                symlink_output = symlink_root / "inspection.json"
                symlink_run = run_inspector(package, symlink_output, context, strict=True)
                assert symlink_run.returncode == 1
                symlink_payload = json.loads(symlink_output.read_text(encoding="utf-8"))
                assert any(error["kind"] == "symbolic-links-not-allowed" for error in symlink_payload["structural_errors"])
                results.append({"case": "symbolic-link-rejection", "status": "PASS"})

    report = {"schema_version": "0.1.0", "status": "PASS", "tests": results}
'''
if replacement not in test:
    if anchor not in test:
        raise RuntimeError("package inspector self-test extension point not found")
    test = test.replace(anchor, replacement, 1)
TEST.write_text(test, encoding="utf-8", newline="\n")

print("P0-B1 package inspector read-only repairs applied")
