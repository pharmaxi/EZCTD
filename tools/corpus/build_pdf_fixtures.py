from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter
from pypdf.constants import UserAccessPermissions
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    ByteStringObject,
    DictionaryObject,
    Fit,
    FloatObject,
    NameObject,
    NullObject,
    NumberObject,
    RectangleObject,
    TextStringObject,
)

ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = ROOT / "tests/corpus/specs/cn-cde-ectd-v1.1/pdf-rules.json"


@dataclass(frozen=True)
class RecipeResult:
    files: list[Path]
    assertions: list[str]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def make_text_pdf(path: Path, pages: int = 1, title: str = "EZCTD synthetic fixture") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4, pageCompression=0, pdfVersion=(1, 7), invariant=1)
    c.setTitle(title)
    for i in range(pages):
        c.setFont("Helvetica", 12)
        c.drawString(72, 790, title)
        c.drawString(72, 760, f"Synthetic page {i + 1} of {pages}")
        c.drawString(72, 730, "Searchable baseline text. Not a real submission document.")
        c.showPage()
    c.save()


def make_image_only_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img_path = path.with_suffix(".png")
    img = Image.new("RGB", (1240, 1754), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((80, 80, 1160, 1670), outline="black", width=4)
    d.text((140, 180), "IMAGE ONLY - NO PDF TEXT LAYER", fill="black")
    img.save(img_path)
    c = canvas.Canvas(str(path), pagesize=A4, pageCompression=0, pdfVersion=(1, 7), invariant=1)
    c.drawImage(str(img_path), 0, 0, width=A4[0], height=A4[1])
    c.showPage()
    c.save()
    img_path.unlink()


def clone_writer(source: Path) -> PdfWriter:
    reader = PdfReader(str(source), strict=False)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.pdf_header = "%PDF-1.7"
    return writer


def write(writer: PdfWriter, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        writer.write(f)


def action_goto(writer: PdfWriter, fit: Fit | None = None) -> DictionaryObject:
    page_ref = writer.pages[0].indirect_reference
    if fit is None:
        fit = Fit.xyz(None, None, None)
    return DictionaryObject({
        NameObject("/S"): NameObject("/GoTo"),
        NameObject("/D"): ArrayObject([page_ref, NameObject(fit.fit_type), *fit.fit_args]),
    })


def action_gotor(path: str) -> DictionaryObject:
    return DictionaryObject({
        NameObject("/S"): NameObject("/GoToR"),
        NameObject("/F"): TextStringObject(path),
        NameObject("/D"): ArrayObject([NumberObject(0), NameObject("/Fit")]),
    })


def action_uri(uri: str) -> DictionaryObject:
    return DictionaryObject({
        NameObject("/S"): NameObject("/URI"),
        NameObject("/URI"): TextStringObject(uri),
    })


def action_js(code: str = "app.alert('synthetic')") -> DictionaryObject:
    return DictionaryObject({
        NameObject("/S"): NameObject("/JavaScript"),
        NameObject("/JS"): TextStringObject(code),
    })


def action_named() -> DictionaryObject:
    return DictionaryObject({
        NameObject("/S"): NameObject("/Named"),
        NameObject("/N"): NameObject("/NextPage"),
    })


def action_launch(path: str) -> DictionaryObject:
    return DictionaryObject({
        NameObject("/S"): NameObject("/Launch"),
        NameObject("/F"): TextStringObject(path),
    })


def add_outline_with_action(writer: PdfWriter, title: str, action: DictionaryObject | None, *, direct_dest: ArrayObject | TextStringObject | None = None) -> DictionaryObject:
    writer.root_object[NameObject("/PageMode")] = NameObject("/UseOutlines")
    ref = writer.add_outline_item(title, 0, fit=Fit.xyz(None, None, None))
    obj = ref.get_object()
    obj.pop(NameObject("/%is_open%"), None)
    obj.pop(NameObject("/A"), None)
    obj.pop(NameObject("/Dest"), None)
    if action is not None:
        obj[NameObject("/A")] = writer._add_object(action)
    if direct_dest is not None:
        obj[NameObject("/Dest")] = direct_dest
    return obj


def add_link(writer: PdfWriter, action: DictionaryObject | None, *, direct_dest: ArrayObject | TextStringObject | None = None, rect=(72, 680, 320, 705)) -> DictionaryObject:
    annot = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Link"),
        NameObject("/Rect"): RectangleObject(rect),
        NameObject("/Border"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)]),
    })
    if action is not None:
        annot[NameObject("/A")] = writer._add_object(action)
    if direct_dest is not None:
        annot[NameObject("/Dest")] = direct_dest
    page = writer.pages[0]
    annot[NameObject("/P")] = page.indirect_reference
    annot_ref = writer._add_object(annot)
    annots = page.get(NameObject("/Annots"))
    if annots is None:
        annots = ArrayObject()
        page[NameObject("/Annots")] = annots
    else:
        annots = annots.get_object() if hasattr(annots, "get_object") else annots
    annots.append(annot_ref)
    return annot


def base_for(case_dir: Path, pages: int = 1) -> tuple[Path, PdfWriter]:
    base = case_dir / "_base.pdf"
    make_text_pdf(base, pages=pages)
    return base, clone_writer(base)


def finalize_base(base: Path, result: Path) -> None:
    base.unlink(missing_ok=True)


def r_valid_text_1p(case_dir: Path) -> RecipeResult:
    out = case_dir / "document.pdf"; make_text_pdf(out, 1); return RecipeResult([out],["page_count=1","extractable_text>0"])


def r_text_searchable(case_dir: Path) -> RecipeResult:
    return r_valid_text_1p(case_dir)


def r_zero_page(case_dir: Path) -> RecipeResult:
    out=case_dir/'document.pdf'; w=PdfWriter(); w.pdf_header='%PDF-1.7'; write(w,out); return RecipeResult([out],["page_count=0"])


def r_truncated_xref(case_dir: Path) -> RecipeResult:
    out=case_dir/'document.pdf'; make_text_pdf(out,1); data=out.read_bytes(); out.write_bytes(data[:-45]); return RecipeResult([out],["tail_truncated=true"])


def r_encrypted_truncated(case_dir: Path) -> RecipeResult:
    rr=r_encrypted_open_password(case_dir); p=rr.files[0]; p.write_bytes(p.read_bytes()[:-45]); return RecipeResult(rr.files,rr.assertions+["tail_truncated=true"])


def r_bookmark(case_dir: Path, action: DictionaryObject | None, *, direct_dest=None, pages=1, mutate=None) -> RecipeResult:
    base,w=base_for(case_dir,pages)
    obj=add_outline_with_action(w,"Synthetic bookmark",action, direct_dest=direct_dest)
    if mutate: mutate(w,obj)
    out=case_dir/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["outline_count>=1"])


def r_link(case_dir: Path, action: DictionaryObject | None, *, direct_dest=None, pages=1, rect=(72,680,320,705), mutate=None) -> RecipeResult:
    base,w=base_for(case_dir,pages)
    obj=add_link(w,action,direct_dest=direct_dest,rect=rect)
    if mutate: mutate(w,obj)
    out=case_dir/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["link_annotation_count>=1"])


def target_pdf(case_dir: Path) -> Path:
    p=case_dir/'target.pdf';make_text_pdf(p,2,title='Remote target');return p


def r_bookmark_internal_xyz_null(case_dir):
    base,w=base_for(case_dir); a=action_goto(w,Fit.xyz(None,None,None)); obj=add_outline_with_action(w,'Synthetic bookmark',a);out=case_dir/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["bookmark.zoom=null"])

def r_bookmark_internal_xyz_zero(case_dir):
    base,w=base_for(case_dir); a=action_goto(w,Fit.xyz(None,None,0));add_outline_with_action(w,'Synthetic bookmark',a);out=case_dir/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["bookmark.zoom=0"])

def r_bookmark_fit(case_dir):
    base,w=base_for(case_dir);a=action_goto(w,Fit.fit());add_outline_with_action(w,'Synthetic bookmark',a);out=case_dir/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["bookmark.destination=/Fit"])

def r_bookmark_xyz_one(case_dir):
    base,w=base_for(case_dir);a=action_goto(w,Fit.xyz(None,None,1.0));add_outline_with_action(w,'Synthetic bookmark',a);out=case_dir/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["bookmark.zoom=1.0"])

def r_bookmark_gotor(case_dir,path):
    tgt=target_pdf(case_dir) if path=='target.pdf' else None
    rr=r_bookmark(case_dir,action_gotor(path));files=rr.files+([tgt] if tgt else []);return RecipeResult([p for p in files if p],rr.assertions+[f"bookmark.filespec={path}"])

def r_bookmark_gotor_relative(c): return r_bookmark_gotor(c,'target.pdf')

def r_bookmark_gotor_absolute_drive(c): return r_bookmark_gotor(c,r'C:\\submission\\target.pdf')

def r_bookmark_gotor_unc(c): return r_bookmark_gotor(c,r'\\\\server\\share\\target.pdf')

def r_bookmark_gotor_escape(c): return r_bookmark_gotor(c,'../../outside.pdf')

def r_bookmark_missing_remote_file(c): return r_bookmark_gotor(c,'missing.pdf')

def r_bookmark_file_uri(c): return r_bookmark(c,action_uri('file:///C:/submission/target.pdf'))

def r_bookmark_external_https(c): return r_bookmark(c,action_uri('https://example.invalid/reference'))

def r_bookmark_external_mailto(c): return r_bookmark(c,action_uri('mailto:test@example.invalid'))

def r_bookmark_launch_external(c): return r_bookmark(c,action_launch(r'C:\\Windows\\notepad.exe'))

def r_bookmark_unknown_named(c): return r_bookmark(c,action_named())

def r_bookmark_javascript(c): return r_bookmark(c,action_js())

def r_bookmark_direct_dest(c):
    base,w=base_for(c);dest=ArrayObject([w.pages[0].indirect_reference,NameObject('/XYZ'),NullObject(),NullObject(),NullObject()]);add_outline_with_action(w,'Synthetic bookmark',None,direct_dest=dest);out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["outline./Dest=direct"])

def r_bookmark_no_action(c): return r_bookmark(c,None)

def r_bookmark_empty_action(c): return r_bookmark(c,DictionaryObject())

def r_bookmark_missing_named_dest(c): return r_bookmark(c,None,direct_dest=TextStringObject('MISSING_DEST'))

def r_bookmark_dest_and_action(c):
    base,w=base_for(c);dest=ArrayObject([w.pages[0].indirect_reference,NameObject('/Fit')]);obj=add_outline_with_action(w,'Synthetic bookmark',action_goto(w),direct_dest=dest);out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["outline has /Dest and /A"])

def r_bookmark_multiple_next(c):
    def mut(w,obj):
        a=obj['/A'].get_object();a[NameObject('/Next')]=w._add_object(action_uri('https://example.invalid/second'))
    return r_bookmark(c,action_goto_placeholder(c),mutate=mut)

def action_goto_placeholder(case_dir):
    # replaced by r_bookmark/r_link after writer exists through mutate helper; use Named then mutate /S and /D in caller if needed
    return action_named()

def r_bookmark_multiple_next(c):
    base,w=base_for(c);a=action_goto(w);a[NameObject('/Next')]=w._add_object(action_uri('https://example.invalid/second'));add_outline_with_action(w,'Synthetic bookmark',a);out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["bookmark action /Next present"])

def r_bookmark_a_plus_aa(c):
    def mut(w,obj): obj[NameObject('/AA')]=w._add_object(DictionaryObject({NameObject('/O'):w._add_object(action_uri('https://example.invalid/aa'))}))
    base,w=base_for(c);obj=add_outline_with_action(w,'Synthetic bookmark',action_goto(w));mut(w,obj);out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["outline has /A and /AA"])

def r_invalid_bookmark_6p(c): return r_bookmark(c,None,pages=6)


def r_link_internal_xyz_null(c):
    base,w=base_for(c);rr=add_link(w,action_goto(w,Fit.xyz(None,None,None)));out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["link.zoom=null"])

def r_link_internal_xyz_zero(c):
    base,w=base_for(c);add_link(w,action_goto(w,Fit.xyz(None,None,0)));out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["link.zoom=0"])

def r_link_fit(c):
    base,w=base_for(c);add_link(w,action_goto(w,Fit.fit()));out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["link.destination=/Fit"])

def r_link_xyz_one(c):
    base,w=base_for(c);add_link(w,action_goto(w,Fit.xyz(None,None,1.0)));out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["link.zoom=1.0"])

def r_link_gotor(c,path):
    tgt=target_pdf(c) if path=='target.pdf' else None
    rr=r_link(c,action_gotor(path));files=rr.files+([tgt] if tgt else []);return RecipeResult([p for p in files if p],rr.assertions+[f"link.filespec={path}"])

def r_link_gotor_relative(c): return r_link_gotor(c,'target.pdf')

def r_link_gotor_absolute_drive(c): return r_link_gotor(c,r'C:\\submission\\target.pdf')

def r_link_gotor_unc(c): return r_link_gotor(c,r'\\\\server\\share\\target.pdf')

def r_link_gotor_escape(c): return r_link_gotor(c,'../../outside.pdf')

def r_link_missing_remote_file(c): return r_link_gotor(c,'missing.pdf')

def r_link_file_uri(c): return r_link(c,action_uri('file:///C:/submission/target.pdf'))

def r_link_external_https(c): return r_link(c,action_uri('https://example.invalid/reference'))

def r_link_external_mailto(c): return r_link(c,action_uri('mailto:test@example.invalid'))

def r_link_launch_external(c): return r_link(c,action_launch(r'C:\\Windows\\notepad.exe'))

def r_link_unknown_named(c): return r_link(c,action_named())

def r_link_javascript(c): return r_link(c,action_js())

def r_link_direct_dest(c):
    base,w=base_for(c);dest=ArrayObject([w.pages[0].indirect_reference,NameObject('/XYZ'),NullObject(),NullObject(),NullObject()]);add_link(w,None,direct_dest=dest);out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["link /Dest direct"])

def r_link_no_action(c): return r_link(c,None)

def r_link_empty_action(c): return r_link(c,DictionaryObject())

def r_link_missing_named_dest(c): return r_link(c,None,direct_dest=TextStringObject('MISSING_DEST'))

def r_link_zero_area(c): return r_link(c,action_named(),rect=(72,680,72,680))

def r_link_dest_and_action(c):
    base,w=base_for(c);dest=ArrayObject([w.pages[0].indirect_reference,NameObject('/Fit')]);add_link(w,action_goto(w),direct_dest=dest);out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["link has /Dest and /A"])

def r_link_multiple_next(c):
    base,w=base_for(c);a=action_goto(w);a[NameObject('/Next')]=w._add_object(action_uri('https://example.invalid/second'));add_link(w,a);out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["link action /Next present"])

def r_link_a_plus_aa(c):
    def mut(w,obj): obj[NameObject('/AA')]=w._add_object(DictionaryObject({NameObject('/E'):w._add_object(action_uri('https://example.invalid/aa'))}))
    base,w=base_for(c);obj=add_link(w,action_goto(w));mut(w,obj);out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["link has /A and /AA"])


def r_pdf_version(c,version):
    base,w=base_for(c);w.pdf_header=f'%PDF-{version}';out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],[f"header=%PDF-{version}"])

def r_pdf_version_13(c): return r_pdf_version(c,'1.3')

def r_pdf_version_14(c): return r_pdf_version(c,'1.4')

def r_pdf_version_17(c): return r_pdf_version(c,'1.7')

def r_pdf_version_20(c): return r_pdf_version(c,'2.0')

def r_pdf_version_header_catalog_mismatch(c):
    base,w=base_for(c);w.pdf_header='%PDF-1.4';w.root_object[NameObject('/Version')]=NameObject('/1.7');out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["header=1.4","catalog.Version=1.7"])


def r_attachment_embedded(c):
    base,w=base_for(c);w.add_attachment('evidence.txt',b'synthetic attachment');out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["EmbeddedFiles count>=1"])

def r_attachment_annotation(c):
    base,w=base_for(c);w.add_attachment('evidence.txt',b'synthetic attachment')
    # Reuse an embedded file spec from the name tree if available; otherwise annotation alone still exercises subtype.
    annot=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/FileAttachment'),NameObject('/Rect'):RectangleObject((72,650,92,670)),NameObject('/Contents'):TextStringObject('synthetic attachment annotation')})
    w.add_annotation(0,annot);out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["annotation subtype=/FileAttachment"])


def r_annotation_text(c):
    base,w=base_for(c);annot=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Text'),NameObject('/Rect'):RectangleObject((72,650,92,670)),NameObject('/Contents'):TextStringObject('synthetic note'),NameObject('/Open'):BooleanObject(False)})
    w.add_annotation(0,annot);out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["annotation subtype=/Text"])

def r_annotation_highlight(c):
    base,w=base_for(c);rect=(72,650,250,670);annot=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Highlight'),NameObject('/Rect'):RectangleObject(rect),NameObject('/QuadPoints'):ArrayObject([FloatObject(72),FloatObject(670),FloatObject(250),FloatObject(670),FloatObject(72),FloatObject(650),FloatObject(250),FloatObject(650)])})
    w.add_annotation(0,annot);out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["annotation subtype=/Highlight"])


def encrypt_case(c,user,owner,permissions):
    base,w=base_for(c);w._ID=None;w.generate_file_identifiers();w.encrypt(user_password=user,owner_password=owner,permissions_flag=permissions,algorithm='AES-128');out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],[f"encrypted=true",f"user_password_empty={not bool(user)}"])

def r_encrypted_open_password(c): return encrypt_case(c,'open-me','owner-secret',UserAccessPermissions.PRINT)

def r_encrypted_restricted_empty_user(c): return encrypt_case(c,'','owner-secret',UserAccessPermissions.PRINT)

def r_encrypted_all_permissions_empty_user(c): return encrypt_case(c,'','owner-secret',UserAccessPermissions(-1))


def r_initial_view(c,*,pages=1,outline=False,page_mode=None,page_layout=None,open_zoom=None):
    base,w=base_for(c,pages)
    if outline: add_outline_with_action(w,'Synthetic bookmark',action_goto(w))
    if page_mode: w.root_object[NameObject('/PageMode')]=NameObject(page_mode)
    if page_layout: w.root_object[NameObject('/PageLayout')]=NameObject(page_layout)
    if open_zoom is not None:
        w.root_object[NameObject('/OpenAction')]=ArrayObject([w.pages[0].indirect_reference,NameObject('/XYZ'),NullObject(),NullObject(),FloatObject(open_zoom)])
    out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],[f"PageMode={page_mode}",f"PageLayout={page_layout}"])

def r_initial_view_outlines_default(c): return r_initial_view(c,outline=True,page_mode='/UseOutlines')

def r_initial_view_outlines_hidden(c): return r_initial_view(c,outline=True,page_mode='/UseNone')

def r_initial_view_nondefault_layout(c): return r_initial_view(c,outline=True,page_mode='/UseOutlines',page_layout='/TwoColumnLeft')

def r_initial_view_explicit_zoom(c): return r_initial_view(c,outline=True,page_mode='/UseOutlines',open_zoom=1.0)

def r_initial_view_no_outlines_default(c): return r_initial_view(c,page_mode='/UseNone')

def r_initial_view_explicit_defaults(c): return r_initial_view(c,page_mode='/UseNone',page_layout='/SinglePage')


def r_no_bookmark_5p(c): out=c/'document.pdf';make_text_pdf(out,5);return RecipeResult([out],["page_count=5","outline_count=0"])

def r_no_bookmark_6p(c): out=c/'document.pdf';make_text_pdf(out,6);return RecipeResult([out],["page_count=6","outline_count=0"])

def r_valid_text_6p_bookmark(c):
    base,w=base_for(c,6);add_outline_with_action(w,'Synthetic bookmark',action_goto(w));out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["page_count=6","valid_outline_count>=1"])


def r_javascript_document(c):
    base,w=base_for(c);w.add_js("app.alert('synthetic document javascript')");out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["document_javascript=true"])

def r_javascript_openaction(c):
    base,w=base_for(c);w.root_object[NameObject('/OpenAction')]=w._add_object(action_js());out=c/'document.pdf';write(w,out);finalize_base(base,out);return RecipeResult([out],["OpenAction.S=/JavaScript"])


def r_image_only(c): out=c/'document.pdf';make_image_only_pdf(out);return RecipeResult([out],["extractable_text=0","dominant_image=true"])

def r_font_standard_unembedded(c):
    out=c/'document.pdf';make_text_pdf(out,1);return RecipeResult([out],["font=/Helvetica","font_stream_absent=true"])


RECIPES: dict[str, Callable[[Path], RecipeResult]] = {
    name.removeprefix('r_'): obj for name,obj in list(globals().items()) if name.startswith('r_') and callable(obj)
}


def load_matrix() -> dict:
    return json.loads(MATRIX_PATH.read_text(encoding='utf-8'))


def select_cases(matrix: dict, mode: str) -> list[dict]:
    all_cases=[]
    for rule in matrix['rules']:
        for case in rule['test_cases']:
            row=dict(case);row['rule_id']=rule['id'];row['rule_title']=rule['official_title'];row['severity']=rule['official_severity'];row['scope_exemptions']=rule['scope_exemptions'];all_cases.append(row)
    if mode=='smoke':
        preferred={
            'CN-PDF-6_1-valid-one-page','CN-PDF-6_1-zero-page','CN-PDF-6_1-truncated-xref',
            'CN-PDF-6_8-xyz-null','CN-PDF-6_8-xyz-zero','CN-PDF-6_8-fit',
            'CN-PDF-6_15-xyz-null','CN-PDF-6_15-xyz-zero','CN-PDF-6_15-fit',
            'CN-PDF-6_16-pdf-13','CN-PDF-6_16-pdf-17','CN-PDF-6_16-header-catalog-mismatch',
            'CN-PDF-6_17-embedded-name-tree','CN-PDF-6_18-text-note','CN-PDF-6_18-highlight',
            'CN-PDF-6_19-owner-restrictions','CN-PDF-6_19-encrypted-all-permissions',
            'CN-PDF-6_20-outlines-correct','CN-PDF-6_20-outlines-use-none',
            'CN-PDF-6_21-user-password','CN-PDF-6_23-five-pages-none','CN-PDF-6_23-six-pages-none','CN-PDF-6_23-six-pages-valid',
            'CN-PDF-6_24-document-js','CN-PDF-6_24-openaction-js','CN-PDF-6_25-born-digital','CN-PDF-6_25-image-only','CN-PDF-6_26-standard-unembedded'
        }
        return [c for c in all_cases if c['case_id'] in preferred]
    return all_cases


def build(output: Path, mode: str, clean: bool) -> dict:
    if clean and output.exists(): shutil.rmtree(output)
    output.mkdir(parents=True,exist_ok=True)
    matrix=load_matrix();selected=select_cases(matrix,mode)
    manifest={"schema_version":"0.2.0","matrix_sha256":sha256(MATRIX_PATH),"mode":mode,"cases":[],"summary":{}}
    status_counts={}
    for case in selected:
        cid=case['case_id'];case_dir=output/cid;case_dir.mkdir(parents=True,exist_ok=True)
        recipe_name=case['fixture_recipe'];recipe=RECIPES.get(recipe_name)
        if case['generator_status']!='implemented' or recipe is None:
            status='SKIPPED_'+case['generator_status'].upper()
            entry={"case_id":cid,"rule_id":case['rule_id'],"recipe":recipe_name,"status":status,"files":[],"reason":"recipe not executable in current builder"}
        else:
            try:
                rr=recipe(case_dir)
                files=[]
                for p in rr.files:
                    if p is None or not p.exists(): continue
                    files.append({"path":str(p.relative_to(output)).replace('\\','/'),"size":p.stat().st_size,"sha256":sha256(p)})
                entry={"case_id":cid,"rule_id":case['rule_id'],"recipe":recipe_name,"status":"GENERATED","context_profile":case['context_profile'],"expected_cde":case['expected_cde'],"assertions":rr.assertions,"files":files}
                (case_dir/'case.json').write_text(json.dumps(entry,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                files.append({"path":str((case_dir/'case.json').relative_to(output)).replace('\\','/'),"size":(case_dir/'case.json').stat().st_size,"sha256":sha256(case_dir/'case.json')})
            except Exception as exc:
                entry={"case_id":cid,"rule_id":case['rule_id'],"recipe":recipe_name,"status":"GENERATION_FAILED","files":[],"error":f"{type(exc).__name__}: {exc}"}
        status_counts[entry['status']]=status_counts.get(entry['status'],0)+1
        manifest['cases'].append(entry)
    manifest['summary']={"selected":len(selected),"status_counts":status_counts,"generated_files":sum(len(c.get('files',[])) for c in manifest['cases'])}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'tests/corpus/generated')
    parser.add_argument('--mode',choices=['smoke','all'],default='smoke')
    parser.add_argument('--no-clean',action='store_true')
    args=parser.parse_args()
    manifest=build(args.output,args.mode,not args.no_clean)
    print(json.dumps(manifest['summary'],ensure_ascii=False,indent=2))
    if manifest['summary']['status_counts'].get('GENERATION_FAILED'):
        raise SystemExit(1)


if __name__=='__main__':
    main()
