from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OBSERVER = ROOT / "src" / "ezctd" / "pdf_observer.py"
ISOLATION = ROOT / "tools" / "p0-b0" / "generate_sample_isolation_audit.py"

observer = OBSERVER.read_text(encoding="utf-8")
old = '''    if URI_SCHEME.match(value):
        scheme = urlparse(value).scheme.lower()
        return "file-uri" if scheme == "file" else "uri"
    if WINDOWS_ABSOLUTE.match(value):
        return "windows-absolute"
'''
new = '''    # A Windows drive path such as C:\\target.pdf also matches the generic URI
    # scheme grammar. Classify Windows syntax first so evidence remains accurate.
    if WINDOWS_ABSOLUTE.match(value):
        return "windows-absolute"
    if URI_SCHEME.match(value):
        scheme = urlparse(value).scheme.lower()
        return "file-uri" if scheme == "file" else "uri"
'''
if new not in observer:
    if old not in observer:
        raise RuntimeError("observer path-classification patch point not found")
    observer = observer.replace(old, new, 1)
OBSERVER.write_text(observer, encoding="utf-8", newline="\n")

isolation = ISOLATION.read_text(encoding="utf-8")
isolation = isolation.replace(
    '"6.2": ("NEEDS_DYNAMIC_ENVIRONMENT", ["6.6"],',
    '"6.2": ("NEEDS_DYNAMIC_ENVIRONMENT", ["6.3", "6.6"],',
)
isolation = isolation.replace(
    '"6.9": ("NEEDS_DYNAMIC_ENVIRONMENT", ["6.13"],',
    '"6.9": ("NEEDS_DYNAMIC_ENVIRONMENT", ["6.10", "6.13"],',
)
ISOLATION.write_text(isolation, encoding="utf-8", newline="\n")
print("P0-B1 observer repairs applied")
