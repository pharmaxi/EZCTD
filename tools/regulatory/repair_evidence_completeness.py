from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "tools" / "regulatory" / "build_evidence_completeness.py"

text = TARGET.read_text(encoding="utf-8")
old = '''        official_matches = [record for record in matched if provenance(record.get("final_url") or record.get("url") or record.get("requested_url")) == "official"]
        secondary_binaries = [record for record in binaries if provenance(record.get("final_url") or record.get("requested_url")) == "secondary_mirror"]
        status = "NOT_DISCOVERED"
        if binaries and official_matches:
            status = "OFFICIAL_BINARY_HASHED"
        elif secondary_binaries:
            status = "SECONDARY_MIRROR_BINARY_HASHED"
        elif official_matches or page_candidates:
'''
new = '''        official_matches = [record for record in matched if provenance(record.get("final_url") or record.get("url") or record.get("requested_url")) == "official"]
        official_binaries = [
            record
            for record in binaries
            if provenance(record.get("final_url") or record.get("requested_url") or record.get("url")) == "official"
        ]
        secondary_binaries = [
            record
            for record in binaries
            if provenance(record.get("final_url") or record.get("requested_url") or record.get("url")) == "secondary_mirror"
        ]
        status = "NOT_DISCOVERED"
        if official_binaries:
            status = "OFFICIAL_BINARY_HASHED"
        elif secondary_binaries:
            status = "SECONDARY_MIRROR_BINARY_HASHED"
        elif official_matches or page_candidates:
'''
if new not in text:
    if old not in text:
        raise RuntimeError("official-binary classification patch point not found")
    text = text.replace(old, new, 1)

old_fields = '''            "binary_candidates": len(binaries),
            "official_candidates": len(official_matches),
'''
new_fields = '''            "binary_candidates": len(binaries),
            "official_binary_candidates": len(official_binaries),
            "secondary_binary_candidates": len(secondary_binaries),
            "official_candidates": len(official_matches),
'''
if new_fields not in text:
    if old_fields not in text:
        raise RuntimeError("ledger count patch point not found")
    text = text.replace(old_fields, new_fields, 1)

old_table = '''        "| ID | Required asset | Status | Binary candidates | Official candidates | Used for |",
        "|---|---|---|---:|---:|---|",
'''
new_table = '''        "| ID | Required asset | Status | Official binaries | Secondary binaries | Official page/link candidates | Used for |",
        "|---|---|---|---:|---:|---:|---|",
'''
if new_table not in text:
    if old_table not in text:
        raise RuntimeError("ledger table header patch point not found")
    text = text.replace(old_table, new_table, 1)

old_row = '''            f"| `{item['id']}` | {item['title']} | `{item['status']}` | {item['binary_candidates']} | {item['official_candidates']} | {', '.join(item['required_for'])} |"
'''
new_row = '''            f"| `{item['id']}` | {item['title']} | `{item['status']}` | {item['official_binary_candidates']} | {item['secondary_binary_candidates']} | {item['official_candidates']} | {', '.join(item['required_for'])} |"
'''
if new_row not in text:
    if old_row not in text:
        raise RuntimeError("ledger table row patch point not found")
    text = text.replace(old_row, new_row, 1)

TARGET.write_text(text, encoding="utf-8", newline="\n")
print("regulatory evidence ledger classification repaired")
