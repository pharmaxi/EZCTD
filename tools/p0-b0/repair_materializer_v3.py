from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATERIALIZER = ROOT / "tools" / "p0-b0" / "materialize_p0_b0.py"

text = MATERIALIZER.read_text(encoding="utf-8")

replacements = {
    'D=A([0, N.Fit]))': 'D=A([0, N.XYZ, None, None, None]))',
    'D=A([pdf.pages[0].obj, N.Fit]), Next=D(S=N.GoTo, D=A([pdf.pages[0].obj, N.FitH, 700])))':
        'D=A([pdf.pages[0].obj, N.XYZ, 0, 780, None]), Next=D(S=N.GoTo, D=A([pdf.pages[0].obj, N.XYZ, 0, 700, None])))',
    'save_pdf(pdf, output, linearize=False, encryption=encryption)':
        'save_pdf(pdf, output, linearize=True, encryption=encryption)',
}

for old, new in replacements.items():
    if new in text:
        continue
    occurrences = text.count(old)
    if occurrences == 0:
        raise RuntimeError(f"patch point not found: {old}")
    text = text.replace(old, new)

MATERIALIZER.write_text(text, encoding="utf-8", newline="\n")
print("P0-B0 materializer v3 repairs applied")
