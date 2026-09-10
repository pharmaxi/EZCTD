"""Create synthetic PDFs and exercise the actual CRO commands, never real data.

Usage from an installed/editable project: python tools/demo/build_cro_demo.py OUTPUT
OUTPUT must not exist. The demo deliberately includes incomplete/bad inputs.
"""
from pathlib import Path
import json
import sys
import pikepdf
from ezctd.cli import main


def build(root: Path) -> dict:
    if root.exists():
        raise ValueError('Demo output must be a new directory')
    inputs = root / 'input'
    inputs.mkdir(parents=True)
    contexts = {}
    for n in range(18):
        folder = inputs / ('fasting' if n % 2 == 0 else 'fed')
        folder.mkdir(exist_ok=True)
        path = folder / f'synthetic-{n:02}.pdf'
        with pikepdf.Pdf.new() as pdf:
            for number in range(1, 3 if n == 0 else 2):
                page = pdf.add_blank_page(page_size=(420, 595))
                font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,
                    Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
                page.obj.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
                page.obj.Contents = pdf.make_stream(
                    f'BT /F1 16 Tf 30 525 Td (SYNTHETIC CLINICAL PDF - {n:02}) Tj '
                    f'0 -35 Td (Cmax = 12.50 ng/mL) Tj '
                    f'0 -35 Td (Page {number} - no patient data) Tj ET'.encode('ascii'))
            pdf.save(path, min_version='1.7', linearize=n % 3 == 0)
        contexts[path.relative_to(inputs).as_posix()] = {
            'node_id': '5.3.1.2', 'document_role': 'clinical-report', 'language': 'zh'}
    with pikepdf.Pdf.new() as pdf:
        pdf.add_blank_page()
        pdf.save(inputs / 'password-protected.pdf', encryption=pikepdf.Encryption(user='synthetic', owner='owner'))
    (inputs / 'corrupt.pdf').write_bytes(b'%PDF-1.7\nDeliberately corrupted SYNTHETIC input\n')
    (inputs / 'not-for-submission.html').write_text('Synthetic non-PDF discovery example', encoding='utf-8')
    mapping = root / 'contexts.json'
    mapping.write_text(json.dumps(contexts, indent=2), encoding='utf-8')
    out = root / 'results'
    scan_code = main(['scan-directory', str(inputs), '--context-map', str(mapping),
                      '--output', str(out / 'scan.json'), '--html', str(out / 'scan.html')])
    source = inputs / 'fasting' / 'synthetic-00.pdf'
    inspect_code = main(['inspect-page', str(source), '--query', '12.50', '--output', str(out / 'page.json')])
    render_code = main(['render-page', str(source), '--dpi', '120', '--output', str(out / 'page.png')])
    status = {'synthetic_only': True, 'scan_exit': scan_code, 'inspect_exit': inspect_code,
              'render_exit': render_code, 'pdf_modification_performed': False}
    (root / 'DEMO_STATUS.json').write_text(json.dumps(status, indent=2), encoding='utf-8')
    return status


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: build_cro_demo.py NEW_OUTPUT_DIRECTORY')
    print(json.dumps(build(Path(sys.argv[1])), indent=2))
