from __future__ import annotations

import hashlib
import json
import warnings
from pathlib import Path
from typing import Any

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pypdf.generic import NullObject

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests/corpus/generated-smoke"
MANIFEST = CORPUS / "manifest.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def deref(obj: Any) -> Any:
    return obj.get_object() if hasattr(obj, "get_object") else obj


def first_outline(reader: PdfReader) -> dict:
    root = reader.root_object
    outlines = deref(root["/Outlines"])
    return deref(outlines["/First"])


def first_link(reader: PdfReader) -> dict:
    annots = deref(reader.pages[0]["/Annots"])
    for ref in annots:
        obj = deref(ref)
        if str(obj.get("/Subtype")) == "/Link":
            return obj
    raise AssertionError("no Link annotation")


def destination_from(container: dict) -> list:
    if "/Dest" in container:
        return deref(container["/Dest"])
    action = deref(container["/A"])
    return deref(action["/D"])


def text_chars(reader: PdfReader) -> int:
    total = 0
    for page in reader.pages:
        try:
            total += len(page.extract_text() or "")
        except Exception:
            pass
    return total


def inspect_case(entry: dict) -> dict:
    case_id = entry["case_id"]
    recipe = entry["recipe"]
    case_dir = CORPUS / case_id
    pdf = case_dir / "document.pdf"
    result = {
        "case_id": case_id,
        "recipe": recipe,
        "pdf_sha256": sha256(pdf),
        "checks": [],
        "status": "PASS",
    }

    if recipe == "truncated_xref":
        try:
            PdfReader(str(pdf), strict=True)
        except PdfReadError:
            result["checks"].append("strict_parser_rejected_truncated_pdf")
            return result
        raise AssertionError("truncated_xref unexpectedly passed strict parser")

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        reader = PdfReader(str(pdf), strict=True)

    result["header"] = reader.pdf_header
    result["encrypted"] = reader.is_encrypted

    if reader.is_encrypted:
        password = "open-me" if recipe == "encrypted_open_password" else ""
        decrypt_result = reader.decrypt(password)
        if not decrypt_result:
            raise AssertionError(f"unable to decrypt fixture with expected password: {recipe}")
        result["checks"].append("encrypted_and_decryptable_with_expected_test_password")
    else:
        result["page_count"] = len(reader.pages)

    if not recipe.startswith("pdf_version_") and recipe != "zero_page":
        if reader.pdf_header != "%PDF-1.7":
            raise AssertionError(f"unexpected baseline version {reader.pdf_header}")
        result["checks"].append("baseline_version_1_7")

    if recipe == "valid_text_1p" or recipe == "text_searchable":
        assert len(reader.pages) == 1 and text_chars(reader) > 0
        result["checks"].append("one_searchable_page")
    elif recipe == "zero_page":
        assert len(reader.pages) == 0
        result["checks"].append("zero_pages")
    elif recipe in {"bookmark_internal_xyz_null", "bookmark_internal_xyz_zero", "bookmark_fit"}:
        outline = first_outline(reader)
        dest = destination_from(outline)
        assert str(reader.root_object.get("/PageMode")) == "/UseOutlines"
        if recipe.endswith("xyz_null"):
            assert str(dest[1]) == "/XYZ" and isinstance(dest[-1], NullObject)
            result["checks"].append("bookmark_xyz_zoom_null")
        elif recipe.endswith("xyz_zero"):
            assert str(dest[1]) == "/XYZ" and float(dest[-1]) == 0.0
            result["checks"].append("bookmark_xyz_zoom_zero")
        else:
            assert str(dest[1]) == "/Fit"
            result["checks"].append("bookmark_fit")
    elif recipe in {"link_internal_xyz_null", "link_internal_xyz_zero", "link_fit"}:
        link = first_link(reader)
        dest = destination_from(link)
        if recipe.endswith("xyz_null"):
            assert str(dest[1]) == "/XYZ" and isinstance(dest[-1], NullObject)
            result["checks"].append("link_xyz_zoom_null")
        elif recipe.endswith("xyz_zero"):
            assert str(dest[1]) == "/XYZ" and float(dest[-1]) == 0.0
            result["checks"].append("link_xyz_zoom_zero")
        else:
            assert str(dest[1]) == "/Fit"
            result["checks"].append("link_fit")
    elif recipe == "pdf_version_13":
        assert reader.pdf_header == "%PDF-1.3"
        result["checks"].append("header_1_3")
    elif recipe == "pdf_version_17":
        assert reader.pdf_header == "%PDF-1.7"
        result["checks"].append("header_1_7")
    elif recipe == "pdf_version_header_catalog_mismatch":
        assert reader.pdf_header == "%PDF-1.4"
        assert str(reader.root_object["/Version"]) == "/1.7"
        result["checks"].append("header_catalog_version_mismatch")
    elif recipe == "attachment_embedded":
        assert list(reader.attachments) == ["evidence.txt"]
        result["checks"].append("embedded_file_present")
    elif recipe in {"annotation_text", "annotation_highlight"}:
        subtype = "/Text" if recipe == "annotation_text" else "/Highlight"
        annots = [deref(x) for x in reader.pages[0]["/Annots"]]
        assert any(str(a.get("/Subtype")) == subtype for a in annots)
        result["checks"].append(f"annotation_{subtype[1:].lower()}_present")
    elif recipe in {"encrypted_restricted_empty_user", "encrypted_all_permissions_empty_user", "encrypted_open_password"}:
        assert reader.is_encrypted
        enc = deref(reader.trailer["/Encrypt"])
        result["permission_bits"] = int(enc.get("/P", 0))
        result["checks"].append("encrypt_dictionary_present")
    elif recipe == "initial_view_outlines_default":
        assert str(reader.root_object.get("/PageMode")) == "/UseOutlines"
        assert "/Outlines" in reader.root_object
        result["checks"].append("outlines_visible_initially")
    elif recipe == "initial_view_outlines_hidden":
        assert str(reader.root_object.get("/PageMode")) == "/UseNone"
        assert "/Outlines" in reader.root_object
        result["checks"].append("outlines_exist_but_hidden")
    elif recipe == "no_bookmark_5p":
        assert len(reader.pages) == 5 and "/Outlines" not in reader.root_object
        result["checks"].append("five_pages_without_outlines")
    elif recipe == "no_bookmark_6p":
        assert len(reader.pages) == 6 and "/Outlines" not in reader.root_object
        result["checks"].append("six_pages_without_outlines")
    elif recipe == "valid_text_6p_bookmark":
        assert len(reader.pages) == 6 and "/Outlines" in reader.root_object
        result["checks"].append("six_pages_with_outline")
    elif recipe == "javascript_document":
        names = deref(reader.root_object["/Names"])
        assert "/JavaScript" in names
        result["checks"].append("document_javascript_name_tree_present")
    elif recipe == "javascript_openaction":
        oa = deref(reader.root_object["/OpenAction"])
        assert str(oa.get("/S")) == "/JavaScript"
        result["checks"].append("openaction_javascript_present")
    elif recipe == "image_only":
        assert len(reader.pages) == 1 and text_chars(reader) == 0
        result["checks"].append("image_page_without_text_layer")
    elif recipe == "font_standard_unembedded":
        resources = deref(reader.pages[0]["/Resources"])
        fonts = deref(resources["/Font"])
        font = deref(next(iter(fonts.values())))
        assert str(font.get("/BaseFont")) == "/Helvetica"
        assert "/FontDescriptor" not in font
        result["checks"].append("standard_helvetica_without_embedding")
    else:
        result["checks"].append("generic_parse_only")

    return result


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    reports = []
    failures = []
    for entry in manifest["cases"]:
        if entry["status"] != "GENERATED":
            continue
        try:
            reports.append(inspect_case(entry))
        except Exception as exc:
            failures.append({"case_id": entry["case_id"], "recipe": entry["recipe"], "error": f"{type(exc).__name__}: {exc}"})
    output = {
        "schema_version": "0.1.0",
        "status": "PASS" if not failures else "FAIL",
        "inspected": len(reports) + len(failures),
        "passed": len(reports),
        "failed": len(failures),
        "failures": failures,
        "cases": reports,
    }
    out = CORPUS / "local-inspection.json"
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: output[k] for k in ("status", "inspected", "passed", "failed", "failures")}, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
