from pathlib import Path
import pikepdf
import pytest


@pytest.fixture
def pdf_factory():
    def make(path: Path, *, pages=1, text='Clinical Cmax 12.50 ng/mL', font='Helvetica',
             linearize=False, password=None, bookmark=False):
        path.parent.mkdir(parents=True, exist_ok=True)
        pdf = pikepdf.Pdf.new()
        font_obj = pdf.make_indirect(pikepdf.Dictionary(Type=pikepdf.Name.Font,
                         Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name('/' + font)))
        for _ in range(pages):
            page = pdf.add_blank_page(page_size=(300, 400))
            page.obj.Resources = pikepdf.Dictionary(Font=pikepdf.Dictionary(F1=font_obj))
            page.obj.Contents = pdf.make_stream(('BT /F1 12 Tf 30 320 Td (' + text + ') Tj ET').encode('ascii'))
        if bookmark:
            with pdf.open_outline() as outlines:
                outlines.root.append(pikepdf.OutlineItem('Clinical section', 0))
        kwargs = {'min_version': '1.7', 'linearize': linearize}
        if password is not None:
            kwargs['encryption'] = pikepdf.Encryption(user=password, owner='synthetic-owner')
        pdf.save(path, **kwargs)
        pdf.close()
        return path
    return make
