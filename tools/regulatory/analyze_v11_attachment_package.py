from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

XS = "{http://www.w3.org/2001/XMLSchema}"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


def hash_file(path: Path, algorithm: str = "sha256") -> str | None:
    try:
        h = hashlib.new(algorithm)
    except ValueError:
        return None
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def magic(path: Path) -> str:
    data = path.read_bytes()[:16]
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        return "zip"
    if data.startswith(b"<?xml") or data.lstrip().startswith(b"<"):
        return "xml-like"
    return "text-or-binary"


def find_package_root(search_root: Path) -> Path:
    candidates = list(search_root.rglob("cn-regional-1-0.xsd"))
    if len(candidates) != 1:
        raise RuntimeError(f"expected one cn-regional-1-0.xsd, found {len(candidates)}")
    return candidates[0].parent.parent


def text_version(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    matches = re.findall(r"Version\s+([0-9.]+)\s*-\s*([^\r\n<]+)", text, flags=re.I)
    return {
        "declared_versions": [
            {"version": version.strip(), "date_text": date.strip()} for version, date in matches
        ],
        "comment_mentions": {
            "drug_substance": "原料药" in text,
            "baseline": "基线" in text,
            "version_1_1": "Version 1.1" in text,
        },
    }


def descriptions(node: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for child in node.findall("description"):
        result[child.attrib.get(XML_LANG, "und")] = "".join(child.itertext()).strip()
    return result


def parse_cv(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    version = root.find("version")
    if version is None:
        raise RuntimeError(f"missing version in {path}")
    codes = [
        {"code": code.attrib["name"], "descriptions": descriptions(code)}
        for code in version.findall("code")
    ]
    return {
        "name": root.attrib.get("name"),
        "descriptions": descriptions(root),
        "version": version.attrib.get("number"),
        "valid_from": version.attrib.get("valid-from"),
        "codes": codes,
        "count": len(codes),
        "source_sha256": hash_file(path),
        "source_path": path.name,
    }


def parse_elements(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    version = root.find("version")
    if version is None:
        raise RuntimeError(f"missing version in {path}")
    items = [
        {
            "name": element.attrib.get("name"),
            "structure_number": element.attrib.get("structureno"),
            "descriptions": descriptions(element),
        }
        for element in version.findall("element")
    ]
    return {
        "version": version.attrib.get("number"),
        "valid_from": version.attrib.get("valid-from"),
        "elements": items,
        "count": len(items),
        "source_sha256": hash_file(path),
        "source_path": path.name,
    }


def parse_dependencies(path: Path, cvs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    version = root.find("version")
    if version is None:
        raise RuntimeError(f"missing version in {path}")
    labels: dict[str, dict[str, str]] = {}
    for cv in cvs.values():
        for code in cv["codes"]:
            labels[code["code"]] = code["descriptions"]
    triples: list[dict[str, Any]] = []
    by_application: dict[str, set[str]] = defaultdict(set)
    by_activity: dict[str, set[str]] = defaultdict(set)
    for application in version.findall("code"):
        app = application.attrib["name"]
        for activity in application.findall("code"):
            act = activity.attrib["name"]
            by_application[app].add(act)
            for sequence in activity.findall("code"):
                seq = sequence.attrib["name"]
                by_activity[act].add(seq)
                triples.append({
                    "application_type": app,
                    "application_label": labels.get(app, {}),
                    "regulatory_activity_type": act,
                    "regulatory_activity_label": labels.get(act, {}),
                    "sequence_type": seq,
                    "sequence_label": labels.get(seq, {}),
                })
    return {
        "keys": [item.strip() for item in root.attrib.get("keys", "").split(",") if item.strip()],
        "version": version.attrib.get("number"),
        "valid_from": version.attrib.get("valid-from"),
        "triples": triples,
        "count": len(triples),
        "activity_sets_by_application": {key: sorted(values) for key, values in by_application.items()},
        "sequence_sets_by_activity": {key: sorted(values) for key, values in by_activity.items()},
        "source_sha256": hash_file(path),
        "source_path": path.name,
    }


def attr_info(node: ET.Element) -> dict[str, Any]:
    return {
        "name": node.attrib.get("name") or node.attrib.get("ref"),
        "type": node.attrib.get("type"),
        "use": node.attrib.get("use", "optional"),
        "ref": node.attrib.get("ref"),
    }


def element_info(node: ET.Element) -> dict[str, Any]:
    return {
        "name": node.attrib.get("name") or node.attrib.get("ref"),
        "type": node.attrib.get("type"),
        "min_occurs": node.attrib.get("minOccurs", "1"),
        "max_occurs": node.attrib.get("maxOccurs", "1"),
        "ref": node.attrib.get("ref"),
    }


def parse_schema(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    imports = [
        {"namespace": item.attrib.get("namespace"), "schema_location": item.attrib.get("schemaLocation")}
        for item in root.findall(f"{XS}import")
    ]
    complex_types = {
        item.attrib["name"]: item for item in root.findall(f"{XS}complexType") if item.attrib.get("name")
    }
    simple_types = {
        item.attrib["name"]: item for item in root.findall(f"{XS}simpleType") if item.attrib.get("name")
    }
    root_element = next(
        (item for item in root.findall(f"{XS}element") if item.attrib.get("name") == "cn_ectd"), None
    )
    root_contract: dict[str, Any] = {}
    if root_element is not None:
        complex_type = root_element.find(f"{XS}complexType")
        if complex_type is not None:
            root_contract["children"] = [
                element_info(item) for item in complex_type.findall(f"./{XS}sequence/{XS}element")
            ]
            root_contract["attributes"] = []
            for attribute in complex_type.findall(f"{XS}attribute"):
                info = attr_info(attribute)
                values = [item.attrib.get("value") for item in attribute.findall(f".//{XS}enumeration")]
                if values:
                    info["enumerations"] = values
                root_contract["attributes"].append(info)

    def type_contract(name: str) -> dict[str, Any]:
        node = complex_types.get(name)
        if node is None:
            return {}
        return {
            "children": [element_info(item) for item in node.findall(f".//{XS}sequence/{XS}element")],
            "attributes": [attr_info(item) for item in node.findall(f"./{XS}attribute")],
        }

    content = complex_types.get("cn-content")
    content_top = [
        element_info(item) for item in content.findall(f"./{XS}sequence/{XS}element")
    ] if content is not None else []
    enumerations = {
        name: [item.attrib.get("value") for item in node.findall(f".//{XS}enumeration")]
        for name, node in simple_types.items()
    }
    leaf_container = complex_types.get("cn-leaf-ext")
    sequence = leaf_container.find(f"{XS}sequence") if leaf_container is not None else None
    leaf_container_contract = {
        "sequence_min_occurs": sequence.attrib.get("minOccurs", "1") if sequence is not None else None,
        "sequence_max_occurs": sequence.attrib.get("maxOccurs", "1") if sequence is not None else None,
        "empty_container_schema_valid_possible": sequence is not None and sequence.attrib.get("minOccurs", "1") == "0",
    }
    return {
        "target_namespace": root.attrib.get("targetNamespace"),
        "element_form_default": root.attrib.get("elementFormDefault"),
        "attribute_form_default": root.attrib.get("attributeFormDefault"),
        "imports": imports,
        "global_elements": [element_info(item) for item in root.findall(f"{XS}element")],
        "global_complex_types": sorted(complex_types),
        "global_simple_types": sorted(simple_types),
        "root_contract": root_contract,
        "envelope_contract": type_contract("cn-envelope"),
        "content_top_level": content_top,
        "leaf_container_contract": leaf_container_contract,
        "leaf_contract": type_contract("cn-leaf"),
        "node_extension_contract": type_contract("cn-node-extension"),
        "simple_type_enumerations": enumerations,
        "source_sha256": hash_file(path),
        "source_path": path.name,
    }


def parse_stf_values(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    namespace = root.tag.split("}")[0].strip("{") if "}" in root.tag else None
    tags = Counter(item.tag.split("}")[-1] for item in root.iter())
    attributes = Counter(key.split("}")[-1] for item in root.iter() for key in item.attrib)
    samples: list[dict[str, Any]] = []
    for item in root.iter():
        if item.attrib or (item.text and item.text.strip()):
            samples.append({
                "tag": item.tag.split("}")[-1],
                "attributes": {key.split("}")[-1]: value for key, value in item.attrib.items()},
                "text": (item.text or "").strip()[:200],
            })
        if len(samples) >= 30:
            break
    return {
        "namespace": namespace,
        "root_tag": root.tag.split("}")[-1],
        "tag_counts": dict(tags),
        "attribute_counts": dict(attributes),
        "sample_nodes": samples,
        "source_sha256": hash_file(path),
        "source_path": path.name,
    }


def parse_dtd(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "element_declarations": re.findall(r"<!ELEMENT\s+([^\s>]+)", text),
        "attribute_list_declarations": re.findall(r"<!ATTLIST\s+([^\s>]+)", text),
        "entity_declarations": re.findall(r"<!ENTITY\s+(?:%\s+)?([^\s>]+)", text),
        "public_identifiers": re.findall(r'PUBLIC\s+"([^"]+)"', text),
        "system_identifiers": re.findall(r'SYSTEM\s+"([^"]+)"', text),
        "source_sha256": hash_file(path),
        "source_path": path.name,
    }


def parse_stylesheet(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        root = ET.parse(path).getroot()
        includes = [
            item.attrib.get("href") for item in root.iter()
            if item.tag.endswith("include") or item.tag.endswith("import")
        ]
    except ET.ParseError:
        includes = []
    labels = re.findall(r">\s*([^<>\n]{2,80})\s*<", text)
    return {
        "declared_versions": [
            {"version": version, "date_text": date.strip()}
            for version, date in re.findall(r"Version\s+([0-9.]+)\s*-\s*([^\r\n<]+)", text, re.I)
        ],
        "included_or_imported_stylesheets": includes,
        "hard_coded_cn_codes": sorted(set(re.findall(r"cn(?:apt|rat|sqt|pt)\d+", text))),
        "literal_label_sample": labels[:50],
        "source_sha256": hash_file(path),
        "source_path": path.name,
    }


def render_analysis(analysis: dict[str, Any]) -> str:
    manifest = analysis["manifest"]
    schema = analysis["schema_contract"]
    cvs = analysis["controlled_vocabularies"]
    dependencies = analysis["dependency_matrix"]
    lines = [
        "# eCTD技术规范V1.1附件包：技术解析", "",
        "> Source class: official effective technical package. Generated from frozen bytes; it does not replace the effective validation standard or the official validator.", "",
        "## Byte identity", "",
        f"- Package source SHA-256: `{analysis['package_source_sha256']}`",
        f"- Members: **{manifest['member_count']}**",
        f"- Aggregate member bytes: **{manifest['total_member_bytes']}**", "",
        "## Composition", "",
        f"- XSD: {manifest['counts_by_suffix'].get('.xsd', 0)}",
        f"- XML: {manifest['counts_by_suffix'].get('.xml', 0)}",
        f"- XSL: {manifest['counts_by_suffix'].get('.xsl', 0)}",
        f"- DTD: {manifest['counts_by_suffix'].get('.dtd', 0)}",
        f"- PDF: {manifest['counts_by_suffix'].get('.pdf', 0)}", "",
        "## Schema findings", "",
        f"- Target namespace: `{schema['target_namespace']}`.",
        f"- Root schema-version enumeration: `{schema['root_contract']['attributes'][0].get('enumerations') if schema['root_contract'].get('attributes') else []}`.",
        f"- Top-level regional chapters: {len(schema['content_top_level'])}; structurally required: `{[x['name'] for x in schema['content_top_level'] if x['min_occurs'] != '0']}`.",
        f"- `cn-leaf-ext` permits an empty sequence: `{schema['leaf_container_contract']['empty_container_schema_valid_possible']}`.",
        f"- Required `cn-leaf` attributes: `{[x['name'] for x in schema['leaf_contract']['attributes'] if x['use'] == 'required']}`.",
        f"- Leaf operations: `{schema['simple_type_enumerations'].get('ich-leaf-operations')}`.",
        f"- Checksum types: `{schema['simple_type_enumerations'].get('ich-checksum-type')}`.", "",
        "**Consequence:** XSD-valid is not equivalent to submission-valid. Controlled vocabulary, dependency, applicability, lifecycle, path, file and checksum rules remain separate.", "",
        "## Controlled vocabularies", "", "| Vocabulary | Version | Valid from | Codes |", "|---|---:|---:|---:|",
    ]
    for cv in cvs.values():
        lines.append(f"| `{cv['name']}` | {cv['version']} | {cv['valid_from']} | {cv['count']} |")
    lines += [
        "", f"- Dependency matrix: version **{dependencies['version']}**, valid from **{dependencies['valid_from']}**, **{dependencies['count']}** valid triples.",
        "- V1.1 application/dependency assets add drug-substance support while several companion assets retain V1.0 declarations.", "",
        "## Element metadata", "",
        f"- China Module 1 elements: **{analysis['module1_elements']['count']}**.",
        f"- ICH elements: **{analysis['ich_elements']['count']}**.",
        f"- China 3.2.R node extensions: **{analysis['node_extension_elements']['count']}**.", "",
        "## Engineering decisions", "",
        "1. Pin the entire attachment package by package hash and member hashes.",
        "2. Validate in layers: well-formedness → XSD/DTD → vocabulary → dependency → path/reference/checksum/lifecycle → official validator.",
        "3. Keep schema cardinality separate from application/sequence applicability.",
        "4. Treat `append` as syntactically allowed, not automatically recommended for every China lifecycle scenario.",
        "5. Use XML vocabulary/dependency files as machine-readable authority; do not derive permitted values from XSL display labels.",
        "6. Preserve submitted codes separately from bilingual UI labels.",
        "7. Retain official-validator comparison for interactions not fully encoded by schemas.", "",
        "## Version-coordination warning", "",
        "The distributed V1.1 package is observably mixed-version: regional schema and several metadata files retain V1.0 declarations while application, dependency and regional style assets contain V1.1 changes. EZCTD must model one coordinated release package rather than independently selecting the numerically newest member of each family.", "",
    ]
    return "\n".join(lines)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--search-root", type=Path, default=Path("build/official-source-deep-dive/extracted"))
    parser.add_argument("--source-ledger", type=Path, default=Path("evidence/regulatory/snapshots/user-supplied-official-sources/SOURCE_DEEP_DIVE.json"))
    parser.add_argument("--evidence", type=Path, default=Path("evidence/regulatory/snapshots/user-supplied-official-sources"))
    parser.add_argument("--output", type=Path, default=Path("rulepacks/cn-cde-ectd/v1.1/technical-package"))
    args = parser.parse_args()
    args.evidence.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)

    package_root = find_package_root(args.search_root)
    files = sorted(path for path in package_root.rglob("*") if path.is_file())
    members = []
    for path in files:
        details = text_version(path) if path.suffix.lower() in {".xml", ".xsd", ".xsl", ".dtd"} else {"declared_versions": [], "comment_mentions": {}}
        members.append({
            "relative_path": path.relative_to(package_root).as_posix(),
            "filename": path.name,
            "suffix": path.suffix.lower(),
            "size": path.stat().st_size,
            "kind": magic(path),
            "sha256": hash_file(path),
            "sm3": hash_file(path, "sm3"),
            **details,
        })
    suffix_counts = Counter(item["suffix"] for item in members)
    manifest = {
        "schema_version": "0.1.0",
        "release_profile": "cn-cde-ectd-v3.2.2-v1.1-technical-package",
        "package_root": package_root.name,
        "member_count": len(members),
        "total_member_bytes": sum(item["size"] for item in members),
        "counts_by_suffix": dict(sorted(suffix_counts.items())),
        "members": members,
    }

    by_name = {path.name: path for path in files}
    schema = parse_schema(by_name["cn-regional-1-0.xsd"])
    cvs = {
        name: parse_cv(by_name[name]) for name in [
            "cv-application-type.xml", "cv-product-type.xml",
            "cv-regulatory-activity-type.xml", "cv-sequence-type.xml",
        ]
    }
    dependencies = parse_dependencies(by_name["depend-apt-rat-sqt.xml"], cvs)
    module1 = parse_elements(by_name["element-property_CN.xml"])
    ich = parse_elements(by_name["element-property_ICH.xml"])
    node_ext = parse_elements(by_name["node-extension-property_CN.xml"])
    stf = parse_stf_values(by_name["valid-values.xml"])
    dtds = {name: parse_dtd(by_name[name]) for name in ["ich-ectd-3-2.dtd", "ich-stf-v2-2.dtd"]}
    styles = {name: parse_stylesheet(by_name[name]) for name in [
        "cn-regional-1-1.xsl", "ectd-2-0.xsl", "ich-stf-stylesheet-2-2a.xsl", "ich-stf-stylesheet-2-3.xsl"
    ]}

    source_sha = None
    if args.source_ledger.exists():
        ledger = json.loads(args.source_ledger.read_text(encoding="utf-8"))
        match = next((item for item in ledger.get("direct_sources", []) if item.get("source_id") == "CDE-CN-V1.1-SPEC-ATTACHMENTS"), None)
        source_sha = match.get("sha256") if match else None

    versions: dict[str, list[str]] = defaultdict(list)
    for item in members:
        for declared in item.get("declared_versions", []):
            versions[declared["version"]].append(item["relative_path"])
    observed_versions = sorted(versions)
    analysis = {
        "schema_version": "0.1.0",
        "status": "OFFICIAL_EFFECTIVE_PACKAGE_PARSED",
        "package_source_sha256": source_sha,
        "manifest": manifest,
        "schema_contract": schema,
        "controlled_vocabularies": cvs,
        "dependency_matrix": dependencies,
        "module1_elements": module1,
        "ich_elements": ich,
        "node_extension_elements": node_ext,
        "stf_valid_values_summary": stf,
        "dtd_summaries": dtds,
        "stylesheet_summaries": styles,
        "version_coordination": {
            "declared_versions_observed": observed_versions,
            "members_by_declared_version": dict(versions),
            "mixed_member_versions": len(observed_versions) > 1,
            "policy": "Pin the whole official package and all member hashes; do not compose releases by filename/version heuristics.",
        },
        "validation_layers": [
            "archive integrity and member identity", "XML well-formedness", "XSD/DTD validation",
            "controlled vocabulary membership", "application/activity/sequence dependency validation",
            "element/node-extension metadata and applicability", "file path/reference/checksum/lifecycle validation",
            "official validator black-box comparison",
        ],
        "non_equivalence_warning": "Schema-valid is not equivalent to CDE-valid or acceptable for submission.",
    }

    write_json(args.evidence / "V1_1_ATTACHMENT_PACKAGE_TECHNICAL_ANALYSIS.json", analysis)
    (args.evidence / "V1_1_ATTACHMENT_PACKAGE_TECHNICAL_ANALYSIS.md").write_text(render_analysis(analysis), encoding="utf-8")
    write_json(args.output / "manifest.json", manifest)
    write_json(args.output / "schema-contract.json", schema)
    write_json(args.output / "controlled-vocabularies.json", cvs)
    write_json(args.output / "dependency-matrix.json", dependencies)
    write_json(args.output / "module1-elements.json", module1)
    write_json(args.output / "ich-elements.json", ich)
    write_json(args.output / "node-extension-elements.json", node_ext)
    write_json(args.output / "stf-valid-values-summary.json", stf)
    write_json(args.output / "dtd-summaries.json", dtds)
    write_json(args.output / "stylesheet-summaries.json", styles)

    summary = {
        "members": len(members),
        "package_source_sha256": source_sha,
        "schema_target_namespace": schema["target_namespace"],
        "application_types": cvs["cv-application-type.xml"]["count"],
        "product_types": cvs["cv-product-type.xml"]["count"],
        "regulatory_activity_types": cvs["cv-regulatory-activity-type.xml"]["count"],
        "sequence_types": cvs["cv-sequence-type.xml"]["count"],
        "dependency_triples": dependencies["count"],
        "module1_elements": module1["count"],
        "ich_elements": ich["count"],
        "node_extensions": node_ext["count"],
        "declared_versions": observed_versions,
        "mixed_member_versions": len(observed_versions) > 1,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    assert len(members) == 23
    assert schema["target_namespace"] == "cn_ectd"
    assert cvs["cv-application-type.xml"]["count"] == 4
    assert dependencies["count"] == 75
    assert module1["count"] == 70
    assert ich["count"] == 159
    assert node_ext["count"] == 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
