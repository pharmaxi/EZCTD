from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATERIALIZER = ROOT / "tools" / "p0-b0" / "materialize_p0_b0.py"

text = MATERIALIZER.read_text(encoding="utf-8")

old_requirements = '''    pypdfium2>=4,<6
    """)'''
new_requirements = '''    pypdfium2>=4,<6
    lxml>=5,<7
    """)'''
if old_requirements not in text and "lxml>=5,<7" not in text:
    raise RuntimeError("requirements insertion point not found")
text = text.replace(old_requirements, new_requirements)

old_searchability = '''            elif rule_id == "6.25": assert all(not page.extract_text().strip() for page in pdf.pages)
'''
new_searchability = '''            elif rule_id == "6.25":
                for page in pdf.pages:
                    contents = page.obj.get("/Contents")
                    streams = list(contents) if isinstance(contents, pikepdf.Array) else ([contents] if contents is not None else [])
                    decoded = b"\\n".join(stream.read_bytes() for stream in streams if hasattr(stream, "read_bytes"))
                    assert b" Tj" not in decoded and b" TJ" not in decoded and b"'" not in decoded and b'"' not in decoded
'''
if old_searchability not in text and new_searchability.strip() not in text:
    raise RuntimeError("6.25 self-check replacement point not found")
text = text.replace(old_searchability, new_searchability)

MATERIALIZER.write_text(text, encoding="utf-8", newline="\n")
print("materializer repaired")
