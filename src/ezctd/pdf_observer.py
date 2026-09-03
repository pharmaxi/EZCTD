from __future__ import annotations

import json
import os
import re
import subprocess
from collections import defaultdict, deque
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Iterator
from urllib.parse import urlparse

import pikepdf
import pypdfium2 as pdfium

from .applicability import resolve as resolve_applicability
from .catalog import RuleCatalog
from .models import Evidence, Finding, PdfContext, ScanDiagnostics, ScanResult

ALLOWED_ACTIONS = {"/GoTo", "/GoToR", "/Launch"}
BASE14_FONTS = {
    "Courier",
    "Courier-Bold",
    "Courier-Oblique",
    "Courier-BoldOblique",
    "Helvetica",
    "Helvetica-Bold",
    "Helvetica-Oblique",
    "Helvetica-BoldOblique",
    "Times-Roman",
    "Times-Bold",
    "Times-Italic",
    "Times-BoldItalic",
    "Symbol",
    "ZapfDingbats",
}
URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]|^[\\/]{2}")
FONT_OPERATOR = re.compile(rb"/([^\s<>\[\]()/%]+)\s+[-+]?(?:\d+(?:\.\d*)?|\.\d+)\s+Tf\b")
PDF_HEADER = re.compile(br"%PDF-(\d\.\d)")


def _name(value: Any) -> str | None:
    if value is None:
        return None
    try:
        text = str(value)
    except Exception:
        return None
    return text if text.startswith("/") else text


def _object_ref(value: Any) -> str | None:
    try:
        objgen = value.objgen
    except Exception:
        return None
    if objgen == (0, 0):
        return None
    return f"{objgen[0]} {objgen[1]} R"


def _dict_get(obj: Any, key: str, default: Any = None) -> Any:
    try:
        return obj.get(key, default)
    except Exception:
        return default


def _array(value: Any) -> list[Any]:
    if isinstance(value, pikepdf.Array):
        return list(value)
    return []


def _stream_bytes(value: Any) -> bytes:
    try:
        return value.read_bytes()
    except Exception:
        return b""


def _page_content_bytes(page: pikepdf.Page) -> bytes:
    contents = _dict_get(page.obj, "/Contents")
    if isinstance(contents, pikepdf.Array):
        return b"\n".join(_stream_bytes(item) for item in contents)
    return _stream_bytes(contents)


def _iter_annotations(pdf: pikepdf.Pdf) -> Iterator[tuple[int, Any]]:
    for page_number, page in enumerate(pdf.pages, 1):
        annots = _dict_get(page.obj, "/Annots")
        for annot in _array(annots):
            yield page_number, annot


def _iter_outline_items(pdf: pikepdf.Pdf) -> Iterator[Any]:
    outlines = _dict_get(pdf.Root, "/Outlines")
    first = _dict_get(outlines, "/First")
    if first is None:
        return
    queue: deque[Any] = deque([first])
    seen: set[tuple[int, int] | int] = set()
    while queue:
        item = queue.popleft()
        try:
            identity: tuple[int, int] | int = item.objgen if item.objgen != (0, 0) else id(item)
        except Exception:
            identity = id(item)
        if identity in seen:
            continue
        seen.add(identity)
        yield item
        child = _dict_get(item, "/First")
        sibling = _dict_get(item, "/Next")
        if child is not None:
            queue.append(child)
        if sibling is not None:
            queue.append(sibling)


def _outline_count(pdf: pikepdf.Pdf) -> int:
    return sum(1 for _ in _iter_outline_items(pdf))


def _action_type(action: Any) -> str | None:
    return _name(_dict_get(action, "/S"))


def _filespec_path(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (pikepdf.String, str)):
        return str(value)
    for key in ("/UF", "/F", "/DOS", "/Unix", "/Mac"):
        candidate = _dict_get(value, key)
        if candidate is not None:
            return str(candidate)
    return None


def _action_filespec(action: Any) -> str | None:
    return _filespec_path(_dict_get(action, "/F"))


def _action_count(item: Any) -> int:
    count = 0
    if _dict_get(item, "/Dest") is not None:
        count += 1
    action = _dict_get(item, "/A")
    if action is not None:
        count += _action_chain_count(action)
    additional = _dict_get(item, "/AA")
    if additional is not None:
        try:
            for key in additional.keys():
                if _dict_get(additional, str(key)) is not None:
                    count += _action_chain_count(_dict_get(additional, str(key)))
        except Exception:
            count += 1
    return count


def _action_chain_count(action: Any, seen: set[tuple[int, int] | int] | None = None) -> int:
    if action is None:
        return 0
    seen = set() if seen is None else seen
    try:
        identity: tuple[int, int] | int = action.objgen if action.objgen != (0, 0) else id(action)
    except Exception:
        identity = id(action)
    if identity in seen:
        return 0
    seen.add(identity)
    count = 1
    next_action = _dict_get(action, "/Next")
    if isinstance(next_action, pikepdf.Array):
        count += sum(_action_chain_count(item, seen) for item in next_action)
    elif next_action is not None:
        count += _action_chain_count(next_action, seen)
    return count


def _destination_for(item: Any) -> Any:
    direct = _dict_get(item, "/Dest")
    if direct is not None:
        return direct
    action = _dict_get(item, "/A")
    if action is not None and _action_type(action) in {"/GoTo", "/GoToR"}:
        return _dict_get(action, "/D")
    return None


def _named_destinations(pdf: pikepdf.Pdf) -> dict[str, Any]:
    destinations: dict[str, Any] = {}
    legacy = _dict_get(pdf.Root, "/Dests")
    if legacy is not None:
        try:
            for key in legacy.keys():
                destinations[str(key).lstrip("/")] = _dict_get(legacy, str(key))
        except Exception:
            pass

    names_root = _dict_get(pdf.Root, "/Names")
    dest_tree = _dict_get(names_root, "/Dests")
    if dest_tree is None:
        return destinations
    queue: deque[Any] = deque([dest_tree])
    seen: set[tuple[int, int] | int] = set()
    while queue:
        node = queue.popleft()
        try:
            identity: tuple[int, int] | int = node.objgen if node.objgen != (0, 0) else id(node)
        except Exception:
            identity = id(node)
        if identity in seen:
            continue
        seen.add(identity)
        values = _array(_dict_get(node, "/Names"))
        for index in range(0, len(values) - 1, 2):
            destinations[str(values[index])] = values[index + 1]
        for child in _array(_dict_get(node, "/Kids")):
            queue.append(child)
    return destinations


def _resolve_named_destination(pdf: pikepdf.Pdf, destination: Any) -> Any:
    if isinstance(destination, pikepdf.Array):
        return destination
    if isinstance(destination, (pikepdf.String, pikepdf.Name, str)):
        key = str(destination).lstrip("/")
        candidate = _named_destinations(pdf).get(key)
        if candidate is None:
            return None
        return _dict_get(candidate, "/D", candidate)
    return destination


def _destination_zoom(pdf: pikepdf.Pdf, destination: Any) -> tuple[str | None, Any, str]:
    resolved = _resolve_named_destination(pdf, destination)
    if not isinstance(resolved, pikepdf.Array) or len(resolved) < 2:
        return None, None, "unresolved"
    mode = _name(resolved[1])
    if mode == "/XYZ":
        zoom = resolved[4] if len(resolved) > 4 else None
        return mode, zoom, "inherit" if zoom is None else "explicit"
    if mode is not None:
        return mode, None, "fit-mode"
    return None, None, "unknown"


def _destination_valid(pdf: pikepdf.Pdf, destination: Any, external_file: Path | None = None) -> tuple[bool, str]:
    resolved = _resolve_named_destination(pdf, destination)
    if resolved is None:
        return False, "named destination not found or destination missing"
    if not isinstance(resolved, pikepdf.Array) or len(resolved) < 2:
        return False, "destination is not an explicit destination array"
    first = resolved[0]
    if external_file is not None:
        if not external_file.exists():
            return False, "target file does not exist"
        if isinstance(first, int):
            try:
                with pikepdf.open(external_file) as target:
                    if first < 0 or first >= len(target.pages):
                        return False, "target page index is out of range"
            except Exception as exc:
                return False, f"target file cannot be opened: {type(exc).__name__}"
        return True, "external target exists"
    page_refs = {_object_ref(page.obj) for page in pdf.pages}
    if isinstance(first, int):
        return (0 <= first < len(pdf.pages), "numeric page index")
    if _object_ref(first) in page_refs:
        return True, "page object exists"
    return False, "target page object is not in the page tree"


def _path_kind(raw: str | None) -> str:
    if not raw:
        return "missing"
    value = raw.strip()
    if URI_SCHEME.match(value):
        scheme = urlparse(value).scheme.lower()
        return "file-uri" if scheme == "file" else "uri"
    if WINDOWS_ABSOLUTE.match(value):
        return "windows-absolute"
    if value.startswith("/"):
        return "posix-absolute"
    return "relative"


def _relative_target(context: PdfContext, raw: str) -> tuple[Path, bool]:
    normalized = raw.replace("\\", "/")
    pure = PurePosixPath(normalized)
    target = (context.file_path.parent / Path(*pure.parts)).resolve()
    try:
        target.relative_to(context.submission_root.resolve())
        inside = True
    except ValueError:
        inside = False
    return target, inside


def _external_target(context: PdfContext, action: Any) -> tuple[bool, str, str | None]:
    action_type = _action_type(action)
    if action_type == "/URI":
        uri = str(_dict_get(action, "/URI") or "")
        return True, f"URI action: {uri}", uri
    if action_type in {"/GoToR", "/Launch"}:
        raw = _action_filespec(action)
        kind = _path_kind(raw)
        if kind in {"uri", "file-uri", "windows-absolute", "posix-absolute"}:
            return True, f"{action_type} {kind}", raw
        if raw:
            _, inside = _relative_target(context, raw)
            if not inside:
                return True, f"{action_type} path escapes submission root", raw
    return False, "not identified as external", _action_filespec(action)


def _font_descriptor(font: Any) -> Any:
    descriptor = _dict_get(font, "/FontDescriptor")
    if descriptor is not None:
        return descriptor
    descendants = _array(_dict_get(font, "/DescendantFonts"))
    if descendants:
        return _dict_get(descendants[0], "/FontDescriptor")
    return None


def _font_embedded(font: Any) -> bool:
    descriptor = _font_descriptor(font)
    if descriptor is None:
        return False
    return any(_dict_get(descriptor, key) is not None for key in ("/FontFile", "/FontFile2", "/FontFile3"))


def _base_font_name(font: Any) -> str:
    raw = str(_dict_get(font, "/BaseFont") or "").lstrip("/")
    return re.sub(r"^[A-Z]{6}\+", "", raw)


def _image_count(page: pikepdf.Page) -> int:
    resources = _dict_get(page.obj, "/Resources")
    xobjects = _dict_get(resources, "/XObject")
    count = 0
    if xobjects is not None:
        try:
            for key in xobjects.keys():
                obj = _dict_get(xobjects, str(key))
                if _name(_dict_get(obj, "/Subtype")) == "/Image":
                    count += 1
        except Exception:
            pass
    return count


def _qpdf_check(path: Path) -> tuple[str, str]:
    try:
        result = subprocess.run(["qpdf", "--check", str(path)], capture_output=True, text=True, errors="replace", timeout=60)
    except FileNotFoundError:
        return "UNAVAILABLE", "qpdf executable not found"
    except Exception as exc:
        return "ERROR", f"{type(exc).__name__}: {exc}"
    detail = (result.stdout + "\n" + result.stderr).strip()[-4000:]
    if result.returncode == 0:
        return "PASS", detail
    if result.returncode == 3:
        return "WARN", detail
    return "FAIL", detail


def _pdfium_probe(path: Path, password: str | None = None) -> tuple[str, str]:
    try:
        kwargs: dict[str, Any] = {}
        if password is not None:
            kwargs["password"] = password
        document = pdfium.PdfDocument(str(path), **kwargs)
        if len(document) == 0:
            document.close()
            return "FAIL", "PDFium reports zero pages"
        for index in sorted({0, len(document) - 1}):
            page = document[index]
            bitmap = page.render(scale=0.25)
            image = bitmap.to_pil()
            image.load()
            page.close()
        document.close()
        return "PASS", "first/last pages rendered"
    except Exception as exc:
        return "FAIL", f"{type(exc).__name__}: {exc}"


def _text_by_page(path: Path, password: str | None = None) -> list[str]:
    kwargs: dict[str, Any] = {}
    if password is not None:
        kwargs["password"] = password
    document = pdfium.PdfDocument(str(path), **kwargs)
    texts: list[str] = []
    try:
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            try:
                texts.append(textpage.get_text_range())
            finally:
                textpage.close()
                page.close()
    finally:
        document.close()
    return texts


class ExperimentalPdfObserver:
    """Read-only rule-contract observer.

    This class implements the current EZCTD interpretation of CDE rules 6.1–6.26.
    Results are experimental until calibrated against CDE validation software V1.1.0.
    """

    def __init__(self, catalog: RuleCatalog) -> None:
        self.catalog = catalog

    def scan(self, context: PdfContext) -> ScanResult:
        findings: dict[str, Finding] = {}
        observations: dict[str, Any] = {
            "file_size": context.file_path.stat().st_size,
            "relative_path": context.relative_path,
            "rules_evaluated": [],
            "rules_not_applicable": [],
        }
        warnings: list[str] = []

        def add(
            rule_id: str,
            message: str,
            evidence: Iterable[Evidence],
            *,
            confidence: str = "high",
        ) -> None:
            applicability = resolve_applicability(rule_id, context)
            if not applicability.applicable:
                observations["rules_not_applicable"].append({"rule_id": rule_id, "reason": applicability.reason})
                return
            metadata = self.catalog.get(rule_id)
            if rule_id not in findings:
                findings[rule_id] = Finding(
                    rule_id=rule_id,
                    title=metadata.title,
                    severity=metadata.severity,
                    message=message,
                    evidence=list(evidence),
                    confidence=confidence,  # type: ignore[arg-type]
                    applicability_reason=applicability.reason,
                )
            else:
                findings[rule_id].evidence.extend(evidence)

        header = context.file_path.read_bytes()[:32]
        match = PDF_HEADER.search(header)
        observations["header_version"] = match.group(1).decode("ascii") if match else None
        qpdf_status, qpdf_detail = _qpdf_check(context.file_path)
        observations["qpdf_detail"] = qpdf_detail

        pdf: pikepdf.Pdf | None = None
        password_required = False
        encrypted: bool | None = None
        try:
            pdf = pikepdf.open(context.file_path)
            encrypted = bool(pdf.is_encrypted)
        except pikepdf.PasswordError as exc:
            password_required = True
            encrypted = True
            add("6.21", "PDF cannot be opened without a password.", [Evidence("exception", type(exc).__name__)])
            add(
                "6.19",
                "Password protection is also an effective PDF security setting.",
                [Evidence("encryption", "password-required")],
                confidence="high",
            )
        except Exception as exc:
            add(
                "6.1",
                "PDF cannot be parsed by pikepdf/qpdf-backed inspection.",
                [Evidence("exception", f"{type(exc).__name__}: {exc}"), Evidence("qpdf", qpdf_status, note=qpdf_detail)],
            )

        if password_required:
            pdfium_status, pdfium_detail = _pdfium_probe(context.file_path)
            diagnostics = ScanDiagnostics("PASSWORD_REQUIRED", qpdf_status, pdfium_status, encrypted, True, warnings)
            observations["pdfium_detail"] = pdfium_detail
            return ScanResult(
                self.catalog.profile_id,
                context.relative_path,
                {
                    "node_id": context.node_id,
                    "document_role": context.document_role,
                    "language": context.language,
                    "submission_root": str(context.submission_root),
                },
                diagnostics,
                sorted(findings.values(), key=lambda item: int(item.rule_id.split(".")[1])),
                observations,
            )

        if pdf is None:
            pdfium_status, pdfium_detail = _pdfium_probe(context.file_path)
            diagnostics = ScanDiagnostics("FAIL", qpdf_status, pdfium_status, encrypted, False, warnings)
            observations["pdfium_detail"] = pdfium_detail
            return ScanResult(
                self.catalog.profile_id,
                context.relative_path,
                {
                    "node_id": context.node_id,
                    "document_role": context.document_role,
                    "language": context.language,
                    "submission_root": str(context.submission_root),
                },
                diagnostics,
                sorted(findings.values(), key=lambda item: int(item.rule_id.split(".")[1])),
                observations,
            )

        try:
            page_count = len(pdf.pages)
            observations["page_count"] = page_count
            if page_count == 0:
                add("6.1", "PDF has zero pages.", [Evidence("page_count", 0)])

            pdfium_status, pdfium_detail = _pdfium_probe(context.file_path, password="" if encrypted else None)
            observations["pdfium_detail"] = pdfium_detail
            if pdfium_status != "PASS" and page_count > 0:
                add(
                    "6.1",
                    "PDF parses structurally but cannot be rendered by the independent PDFium probe.",
                    [Evidence("pdfium", pdfium_status, note=pdfium_detail)],
                    confidence="medium",
                )

            if qpdf_status == "FAIL" and page_count > 0:
                add(
                    "6.1",
                    "qpdf reports a structural failure although pikepdf opened the file.",
                    [Evidence("qpdf", qpdf_status, note=qpdf_detail)],
                    confidence="medium",
                )

            if encrypted:
                add("6.19", "PDF contains an encryption/security dictionary.", [Evidence("encrypted", True)])

            outline_items = list(_iter_outline_items(pdf))
            observations["outline_count"] = len(outline_items)
            for item in outline_items:
                object_ref = _object_ref(item)
                action = _dict_get(item, "/A")
                action_type = _action_type(action)
                filespec = _action_filespec(action)
                path_kind = _path_kind(filespec)

                if action_type in {"/GoToR", "/Launch"} and path_kind != "relative":
                    add(
                        "6.2",
                        "Bookmark file target is not a relative path.",
                        [Evidence("bookmark-path", {"path": filespec, "kind": path_kind}, object_ref=object_ref)],
                    )
                elif action_type in {"/GoToR", "/Launch"} and filespec:
                    _, inside = _relative_target(context, filespec)
                    if not inside:
                        add(
                            "6.2",
                            "Bookmark relative path escapes the submission root.",
                            [Evidence("bookmark-path", filespec, object_ref=object_ref)],
                            confidence="medium",
                        )

                is_external, reason, raw_target = _external_target(context, action)
                if is_external:
                    add(
                        "6.3",
                        "Bookmark contains a webpage, email, or other target external to the submission package.",
                        [Evidence("bookmark-external", {"reason": reason, "target": raw_target}, object_ref=object_ref)],
                    )

                if action is not None and action_type not in ALLOWED_ACTIONS:
                    add(
                        "6.4",
                        "Bookmark action is outside GoTo, GoToR, and Launch.",
                        [Evidence("bookmark-action", action_type, object_ref=object_ref)],
                    )

                if _dict_get(item, "/Dest") is None and action is None:
                    add("6.5", "Bookmark has no destination or action.", [Evidence("bookmark", "no action", object_ref=object_ref)])

                destination = _destination_for(item)
                if destination is not None:
                    external_file: Path | None = None
                    if action_type == "/GoToR" and filespec:
                        if _path_kind(filespec) == "relative":
                            external_file, _ = _relative_target(context, filespec)
                        else:
                            external_file = Path(PureWindowsPath(filespec)) if WINDOWS_ABSOLUTE.match(filespec) else Path(filespec)
                    valid, reason = _destination_valid(pdf, destination, external_file)
                    if not valid:
                        add(
                            "6.6",
                            "Bookmark target is missing or damaged.",
                            [Evidence("bookmark-destination", reason, object_ref=object_ref)],
                        )

                    mode, zoom, zoom_state = _destination_zoom(pdf, destination)
                    if zoom_state != "inherit":
                        add(
                            "6.8",
                            "Bookmark destination does not use Inherit Zoom.",
                            [Evidence("bookmark-zoom", {"mode": mode, "zoom": str(zoom), "state": zoom_state}, object_ref=object_ref)],
                            confidence="high" if zoom_state == "explicit" else "medium",
                        )

                count = _action_count(item)
                if count > 1:
                    add(
                        "6.7",
                        "Bookmark has multiple effective actions or destinations.",
                        [Evidence("bookmark-action-count", count, object_ref=object_ref)],
                    )

            annotation_summary: dict[str, int] = defaultdict(int)
            for page_number, annot in _iter_annotations(pdf):
                subtype = _name(_dict_get(annot, "/Subtype"))
                annotation_summary[subtype or "unknown"] += 1
                object_ref = _object_ref(annot)
                if subtype != "/Link":
                    add(
                        "6.18",
                        "PDF contains an annotation other than a hyperlink.",
                        [Evidence("annotation-subtype", subtype, object_ref=object_ref, page=page_number)],
                        confidence="medium" if subtype == "/Widget" else "high",
                    )
                    continue

                action = _dict_get(annot, "/A")
                action_type = _action_type(action)
                filespec = _action_filespec(action)
                path_kind = _path_kind(filespec)
                if action_type in {"/GoToR", "/Launch"} and path_kind != "relative":
                    add(
                        "6.9",
                        "Hyperlink file target is not a relative path.",
                        [Evidence("link-path", {"path": filespec, "kind": path_kind}, object_ref=object_ref, page=page_number)],
                    )
                elif action_type in {"/GoToR", "/Launch"} and filespec:
                    _, inside = _relative_target(context, filespec)
                    if not inside:
                        add(
                            "6.9",
                            "Hyperlink relative path escapes the submission root.",
                            [Evidence("link-path", filespec, object_ref=object_ref, page=page_number)],
                            confidence="medium",
                        )

                is_external, reason, raw_target = _external_target(context, action)
                if is_external:
                    add(
                        "6.10",
                        "Hyperlink contains a webpage, email, or other target external to the submission package.",
                        [Evidence("link-external", {"reason": reason, "target": raw_target}, object_ref=object_ref, page=page_number)],
                    )

                if action is not None and action_type not in ALLOWED_ACTIONS:
                    add(
                        "6.11",
                        "Hyperlink action is outside GoTo, GoToR, and Launch.",
                        [Evidence("link-action", action_type, object_ref=object_ref, page=page_number)],
                    )

                if _dict_get(annot, "/Dest") is None and action is None:
                    add(
                        "6.12",
                        "Hyperlink has no destination or action.",
                        [Evidence("link", "no action", object_ref=object_ref, page=page_number)],
                    )

                destination = _destination_for(annot)
                if destination is not None:
                    external_file = None
                    if action_type == "/GoToR" and filespec:
                        if _path_kind(filespec) == "relative":
                            external_file, _ = _relative_target(context, filespec)
                        else:
                            external_file = Path(PureWindowsPath(filespec)) if WINDOWS_ABSOLUTE.match(filespec) else Path(filespec)
                    valid, reason = _destination_valid(pdf, destination, external_file)
                    if not valid:
                        add(
                            "6.13",
                            "Hyperlink target is missing or damaged.",
                            [Evidence("link-destination", reason, object_ref=object_ref, page=page_number)],
                        )
                    mode, zoom, zoom_state = _destination_zoom(pdf, destination)
                    if zoom_state != "inherit":
                        add(
                            "6.15",
                            "Hyperlink destination does not use Inherit Zoom.",
                            [Evidence("link-zoom", {"mode": mode, "zoom": str(zoom), "state": zoom_state}, object_ref=object_ref, page=page_number)],
                            confidence="high" if zoom_state == "explicit" else "medium",
                        )

                count = _action_count(annot)
                if count > 1:
                    add(
                        "6.14",
                        "Hyperlink has multiple effective actions or destinations.",
                        [Evidence("link-action-count", count, object_ref=object_ref, page=page_number)],
                    )
            observations["annotations"] = dict(annotation_summary)

            header_version = observations["header_version"]
            catalog_version = _name(_dict_get(pdf.Root, "/Version"))
            observations["catalog_version"] = catalog_version
            effective_version = catalog_version.lstrip("/") if catalog_version else header_version
            if effective_version not in {"1.4", "1.5", "1.6", "1.7"}:
                add(
                    "6.16",
                    "PDF version is outside the officially listed 1.4–1.7 range; PDF/A claims require separate conformance evidence.",
                    [Evidence("pdf-version", {"header": header_version, "catalog": catalog_version})],
                )

            names = _dict_get(pdf.Root, "/Names")
            has_embedded_names = _dict_get(names, "/EmbeddedFiles") is not None
            has_associated_files = _dict_get(pdf.Root, "/AF") is not None
            file_attachment_annots = annotation_summary.get("/FileAttachment", 0)
            if has_embedded_names or has_associated_files or file_attachment_annots:
                add(
                    "6.17",
                    "PDF contains an embedded or associated file.",
                    [
                        Evidence(
                            "attachment-signals",
                            {"EmbeddedFiles": has_embedded_names, "AF": has_associated_files, "FileAttachment": file_attachment_annots},
                        )
                    ],
                )

            initial_view_evidence: list[Evidence] = []
            page_mode = _name(_dict_get(pdf.Root, "/PageMode"))
            page_layout = _name(_dict_get(pdf.Root, "/PageLayout"))
            open_action = _dict_get(pdf.Root, "/OpenAction")
            if outline_items and page_mode != "/UseOutlines":
                initial_view_evidence.append(Evidence("PageMode", page_mode or "absent"))
            if page_layout not in {None, "/SinglePage"}:
                initial_view_evidence.append(Evidence("PageLayout", page_layout))
            if open_action is not None:
                mode, zoom, zoom_state = _destination_zoom(pdf, open_action)
                if zoom_state in {"explicit", "fit-mode"}:
                    initial_view_evidence.append(Evidence("OpenAction", {"mode": mode, "zoom": str(zoom), "state": zoom_state}))
            if initial_view_evidence:
                add(
                    "6.20",
                    "PDF initial view is inconsistent with the current experimental interpretation of bookmark visibility/default magnification/layout.",
                    initial_view_evidence,
                    confidence="medium",
                )
            observations["initial_view"] = {"PageMode": page_mode, "PageLayout": page_layout, "OpenAction": str(open_action) if open_action is not None else None}

            if not pdf.is_linearized:
                add("6.22", "PDF is not linearized for Fast Web View.", [Evidence("linearized", False)])
            observations["linearized"] = bool(pdf.is_linearized)

            if page_count > 5 and not outline_items:
                add("6.23", "Non-exempt PDF has more than five pages and no bookmarks.", [Evidence("page_count", page_count), Evidence("outline_count", 0)])

            dynamic_evidence: list[Evidence] = []
            for obj in pdf.objects:
                if not hasattr(obj, "keys"):
                    continue
                object_ref = _object_ref(obj)
                action_type = _name(_dict_get(obj, "/S"))
                subtype = _name(_dict_get(obj, "/Subtype"))
                if action_type == "/JavaScript":
                    dynamic_evidence.append(Evidence("dynamic-action", action_type, object_ref=object_ref))
                if subtype in {"/3D", "/RichMedia", "/Movie", "/Sound"}:
                    dynamic_evidence.append(Evidence("dynamic-subtype", subtype, object_ref=object_ref))
                for key in ("/JavaScript", "/JS", "/3DD", "/RichMediaContent", "/Movie", "/Sound"):
                    if _dict_get(obj, key) is not None:
                        dynamic_evidence.append(Evidence("dynamic-key", key, object_ref=object_ref))
            if dynamic_evidence:
                add("6.24", "PDF contains JavaScript, 3D, audio, video, or other dynamic content signals.", dynamic_evidence)

            try:
                texts = _text_by_page(context.file_path, password="" if encrypted else None)
            except Exception as exc:
                texts = []
                warnings.append(f"text extraction failed: {type(exc).__name__}: {exc}")
            observations["text_characters_by_page"] = [len(text.strip()) for text in texts]
            search_evidence: list[Evidence] = []
            if len(texts) == page_count:
                for index, (page, text) in enumerate(zip(pdf.pages, texts, strict=True), 1):
                    if not text.strip() and _image_count(page) > 0:
                        search_evidence.append(Evidence("image-page-without-searchable-text", True, page=index))
            if search_evidence:
                add(
                    "6.25",
                    "One or more image-bearing pages have no searchable text layer.",
                    search_evidence,
                    confidence="high",
                )

            font_evidence: list[Evidence] = []
            for page_number, page in enumerate(pdf.pages, 1):
                used_names = {name.decode("latin-1") for name in FONT_OPERATOR.findall(_page_content_bytes(page))}
                resources = _dict_get(page.obj, "/Resources")
                fonts = _dict_get(resources, "/Font")
                if fonts is None:
                    continue
                for resource_name in sorted(used_names):
                    font = _dict_get(fonts, f"/{resource_name}")
                    if font is None:
                        continue
                    base_font = _base_font_name(font)
                    if base_font in BASE14_FONTS:
                        continue
                    if not _font_embedded(font):
                        font_evidence.append(
                            Evidence(
                                "unembedded-nonstandard-font",
                                {"resource": resource_name, "base_font": base_font, "subtype": _name(_dict_get(font, "/Subtype"))},
                                object_ref=_object_ref(font),
                                page=page_number,
                            )
                        )
            if font_evidence:
                add("6.26", "A used non-standard font lacks an embedded font program.", font_evidence)

            diagnostics = ScanDiagnostics("PASS", qpdf_status, pdfium_status, encrypted, False, warnings)
        finally:
            pdf.close()

        observations["rules_evaluated"] = [f"6.{number}" for number in range(1, 27)]
        return ScanResult(
            self.catalog.profile_id,
            context.relative_path,
            {
                "node_id": context.node_id,
                "document_role": context.document_role,
                "language": context.language,
                "submission_root": str(context.submission_root),
            },
            diagnostics,
            sorted(findings.values(), key=lambda item: int(item.rule_id.split(".")[1])),
            observations,
        )


def scan_to_json(observer: ExperimentalPdfObserver, context: PdfContext) -> str:
    return json.dumps(observer.scan(context).to_dict(), ensure_ascii=False, indent=2) + "\n"
