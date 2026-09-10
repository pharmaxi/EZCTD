"""Generate only synthetic CRO PDFs. No real identifiers or external font files."""
from pathlib import Path
import json
import pikepdf


def make_pdf(path: Path, *, pages=2, title='SYNTHETIC CLINICAL REPORT', linearized=False,
             bookmarks=True, signature_signal=False, password=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pikepdf.Pdf.new() as pdf:
        font = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,
                              Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica))
        for index in range(pages):
            page = pdf.add_blank_page(page_size=(595, 842))
            page.obj.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font))
            lines = [title, 'EZCTD - SYNTHETIC TEST DATA ONLY', '',
                     f'Physical page {index + 1} / {pages}', 'No patient, sponsor or site data', '',
                     '1. Clinical pharmacokinetic results', '',
                     'Endpoint                 Test              Reference',
                     'Cmax                     12.50             12.31 ng/mL',
                     'AUC0-t                   142.80            139.60 ng*h/mL', '',
                     '2. Document processing controls', '',
                     'Keep original source files unchanged.',
                     'Preserve searchable text and navigation.',
                     'Compare every page before publishing a copy.', '',
                     'This file is not a clinical study result or submission.']
            instructions = ['BT /F1 14 Tf 48 782 Td']
            for line in lines:
                safe = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
                instructions.extend([f'({safe}) Tj', '0 -27 Td'])
            instructions.append('ET')
            page.obj.Contents = pdf.make_stream('\n'.join(instructions).encode('ascii'))
        if bookmarks:
            with pdf.open_outline() as outline:
                outline.root.append(pikepdf.OutlineItem('1. Pharmacokinetic results', 0))
                if pages > 1:
                    outline.root.append(pikepdf.OutlineItem('2. Review notes', 1))
        if signature_signal:
            # Deliberate synthetic structural signal, NOT a valid digital signature.
            pdf.Root.SyntheticSignatureSignal = pikepdf.Dictionary(FT=pikepdf.Name.Sig)
        kwargs = {'min_version': '1.7', 'linearize': linearized}
        if password is not None:
            kwargs['encryption'] = pikepdf.Encryption(user=password, owner='synthetic-owner')
        pdf.save(path, **kwargs)


def build(root: Path) -> dict:
    if root.exists():
        raise ValueError('Demo root must not exist')
    inputs = root / 'input'
    make_pdf(inputs/'m5/5.3.1.2/fasting/clinical-report.pdf', pages=3)
    make_pdf(inputs/'m5/5.3.1.2/fed/clinical-report.pdf', pages=6, bookmarks=False)
    make_pdf(inputs/'m2/2.5/clinical-overview.pdf', pages=2, title='SYNTHETIC CLINICAL OVERVIEW')
    make_pdf(inputs/'m5/5.3.1.4/bioanalytical-report.pdf', pages=2, title='SYNTHETIC BIOANALYTICAL REPORT')
    make_pdf(inputs/'references/already-linearized.pdf', pages=1, linearized=True)
    make_pdf(inputs/'certificates/signature-signal.pdf', pages=1, signature_signal=True)
    make_pdf(inputs/'blocked/password.pdf', pages=1, password='synthetic')
    (inputs/'blocked/corrupt.pdf').write_bytes(b'%PDF-1.7\nDeliberate synthetic malformed input\n')
    (root/'README.txt').write_text('Synthetic files only. The signature-signal fixture is NOT a valid digital signature.\nNo originals should be used for development.\n',encoding='utf-8')
    return {'input': str(inputs), 'workspace': str(root/'workspace'), 'pdf_count': 8}


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('new_output',type=Path)
    print(json.dumps(build(parser.parse_args().new_output),indent=2))
