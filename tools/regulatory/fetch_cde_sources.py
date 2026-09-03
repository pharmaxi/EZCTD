from __future__ import annotations

import argparse
import hashlib
import html
import json
import mimetypes
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import deque
from dataclasses import dataclass, asdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

USER_AGENT = "EZCTD-regulatory-evidence/0.1 (+https://github.com/laojia-a/EZCTD)"
RELEVANT = re.compile(r"ectd|电子通用技术文档|验证软件|技术规范|验证标准|实施指南|目录层级|常用下载|现行申报资料", re.I)
DOWNLOAD_PATH = re.compile(r"/main/att/download/[0-9a-f]{16,}", re.I)
LIKELY_BINARY = re.compile(r"\.(pdf|zip|rar|7z|exe|msi|xlsx|xls|docx|doc|xml|xsd|dtd|xsl)(?:$|\?)", re.I)
MAX_HTML_PAGES = 40
MAX_BINARY_BYTES = 350 * 1024 * 1024

SEEDS = [
    {
        "url": "https://www.cde.org.cn/main/news/viewInfoCommon/454f7eb43d4eb4c42503d697784903db",
        "authority": "CDE/NMPA",
        "role": "effective_technical_files_notice",
        "status": "official_effective",
    },
    {
        "url": "https://www.cde.org.cn/main/news/viewInfoCommon/43ee306c48b514cb05fdbf6e6f873d67",
        "authority": "CDE/NMPA",
        "role": "validator_1_1_0_notice",
        "status": "official_effective",
    },
    {
        "url": "https://www.cde.org.cn/",
        "authority": "CDE/NMPA",
        "role": "common_download_discovery",
        "status": "official",
    },
    {
        "url": "https://www.ich.org/page/ich-electronic-common-technical-document-ectd-v322",
        "authority": "ICH",
        "role": "international_ectd_3_2_2_package_discovery",
        "status": "official",
    },
]

SECONDARY_MIRRORS = [
    {
        "url": "https://www.cnpharm.com/upload/resources/file/2026/01/16/183312.pdf",
        "authority": "China Pharmaceutical News mirror",
        "role": "eCTD_implementation_guide_v1_1_secondary_mirror",
        "status": "secondary_mirror",
    },
    {
        "url": "https://www.cnpharm.com/upload/resources/file/2026/01/16/183313.pdf",
        "authority": "China Pharmaceutical News mirror",
        "role": "eCTD_validation_standard_v1_1_secondary_mirror",
        "status": "secondary_mirror",
    },
]


@dataclass
class Link:
    source_url: str
    url: str
    text: str
    depth: int


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        values = dict(attrs)
        self._href = values.get("href")
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split())))
            self._href = None
            self._text = []


def request(url: str, *, timeout: int = 45) -> tuple[bytes, dict[str, str], int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read(MAX_BINARY_BYTES + 1)
        if len(data) > MAX_BINARY_BYTES:
            raise RuntimeError(f"response exceeds {MAX_BINARY_BYTES} bytes")
        headers = {k.lower(): v for k, v in response.headers.items()}
        return data, headers, response.status, response.geturl()


def decode_html(data: bytes, headers: dict[str, str]) -> str:
    content_type = headers.get("content-type", "")
    charset_match = re.search(r"charset=([\w-]+)", content_type, re.I)
    candidates = [charset_match.group(1)] if charset_match else []
    candidates += ["utf-8", "gb18030", "gbk"]
    for encoding in candidates:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("utf-8", errors="replace")


def normalize(base: str, href: str) -> str | None:
    href = html.unescape(href.strip())
    if not href or href.startswith(("javascript:", "mailto:", "#")):
        return None
    url = urllib.parse.urljoin(base, href)
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.params, parsed.query, ""))


def extract_links(source_url: str, text: str, depth: int) -> list[Link]:
    parser = LinkParser()
    parser.feed(text)
    found: dict[str, Link] = {}
    for href, anchor in parser.links:
        url = normalize(source_url, href)
        if url:
            found[url] = Link(source_url, url, anchor, depth)
    for match in re.finditer(r"(?:https?://[^\s\"'<>]+|/main/att/download/[0-9a-f]{16,})", text, re.I):
        url = normalize(source_url, match.group(0).rstrip(".,);]"))
        if url and url not in found:
            found[url] = Link(source_url, url, "embedded-url", depth)
    return list(found.values())


def is_html(headers: dict[str, str], data: bytes, url: str) -> bool:
    ctype = headers.get("content-type", "").lower()
    return "text/html" in ctype or data.lstrip().lower().startswith((b"<!doctype html", b"<html")) or url.endswith("/")


def should_follow(link: Link, seed_hosts: set[str]) -> bool:
    parsed = urllib.parse.urlparse(link.url)
    if parsed.netloc not in seed_hosts:
        return False
    haystack = f"{link.text} {link.url}"
    return bool(RELEVANT.search(haystack) or DOWNLOAD_PATH.search(link.url) or LIKELY_BINARY.search(link.url))


def sanitize_filename(value: str) -> str:
    value = urllib.parse.unquote(value)
    value = re.sub(r"[<>:\\|?*\x00-\x1f]", "_", value)
    value = value.strip(" .")
    return value[:180] or "download"


def filename_from(headers: dict[str, str], final_url: str, data: bytes, index: int) -> str:
    disposition = headers.get("content-disposition", "")
    filename = None
    m = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I)
    if m:
        filename = urllib.parse.unquote(m.group(1))
    if not filename:
        m = re.search(r'filename="?([^";]+)', disposition, re.I)
        if m:
            filename = m.group(1)
    if not filename:
        filename = Path(urllib.parse.urlparse(final_url).path).name
    filename = sanitize_filename(filename or f"asset-{index:03d}")
    if "." not in filename:
        ctype = headers.get("content-type", "").split(";", 1)[0].strip()
        ext = mimetypes.guess_extension(ctype) or ""
        magic = data[:8]
        if data.startswith(b"%PDF-"):
            ext = ".pdf"
        elif magic.startswith(b"PK\x03\x04"):
            ext = ".zip"
        elif data.startswith(b"Rar!\x1a\x07"):
            ext = ".rar"
        elif data.startswith(b"MZ"):
            ext = ".exe"
        filename += ext
    return filename


def hash_record(data: bytes) -> dict[str, str | None]:
    sm3 = None
    try:
        sm3 = hashlib.new("sm3", data).hexdigest()
    except (ValueError, TypeError):
        pass
    return {"sha256": hashlib.sha256(data).hexdigest(), "sm3": sm3}


def list_archive(path: Path) -> dict:
    result: dict = {"kind": None, "members": [], "status": "NOT_ARCHIVE"}
    try:
        if zipfile.is_zipfile(path):
            result["kind"] = "zip"
            with zipfile.ZipFile(path) as z:
                result["members"] = [{"name": i.filename, "size": i.file_size, "compressed_size": i.compress_size} for i in z.infolist()]
            result["status"] = "LISTED"
            return result
        if shutil_which("7z"):
            proc = subprocess.run(["7z", "l", "-slt", str(path)], capture_output=True, text=True, errors="replace", timeout=90)
            if proc.returncode == 0 and "Path =" in proc.stdout:
                members = []
                for block in proc.stdout.split("\n\n"):
                    values = {}
                    for line in block.splitlines():
                        if " = " in line:
                            k, v = line.split(" = ", 1)
                            values[k.strip()] = v.strip()
                    if values.get("Path") and values.get("Folder") != "+" and values.get("Path") != str(path):
                        members.append({"name": values["Path"], "size": int(values.get("Size", "0") or 0)})
                if members:
                    result.update({"kind": "7z-supported", "members": members, "status": "LISTED"})
    except Exception as exc:
        result.update({"status": "ERROR", "error": str(exc)})
    return result


def shutil_which(name: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", type=Path, default=Path("build/regulatory-source-snapshot"))
    parser.add_argument("--evidence", type=Path, default=Path("evidence/regulatory/snapshots/cde-2026-v1.1"))
    args = parser.parse_args()
    args.build.mkdir(parents=True, exist_ok=True)
    page_dir = args.build / "pages"
    asset_dir = args.build / "assets"
    page_dir.mkdir(parents=True, exist_ok=True)
    asset_dir.mkdir(parents=True, exist_ok=True)

    seed_hosts = {urllib.parse.urlparse(item["url"]).netloc.lower() for item in SEEDS}
    queue = deque((item["url"], 0, item) for item in SEEDS)
    visited: set[str] = set()
    pages: list[dict] = []
    discovered: dict[str, Link] = {}
    failures: list[dict] = []

    while queue and len(pages) < MAX_HTML_PAGES:
        url, depth, seed_meta = queue.popleft()
        if url in visited:
            continue
        visited.add(url)
        try:
            data, headers, status, final_url = request(url)
        except Exception as exc:
            failures.append({"url": url, "phase": "page_fetch", "error": str(exc)})
            continue
        if not is_html(headers, data, final_url):
            discovered[final_url] = Link(url, final_url, seed_meta.get("role", "seed-binary"), depth)
            continue
        text = decode_html(data, headers)
        page_name = f"page-{len(pages)+1:03d}-{hashlib.sha256(final_url.encode()).hexdigest()[:12]}.html"
        (page_dir / page_name).write_text(text, encoding="utf-8", errors="replace")
        links = extract_links(final_url, text, depth + 1)
        pages.append({
            "requested_url": url,
            "final_url": final_url,
            "status": status,
            "content_type": headers.get("content-type"),
            "sha256": hashlib.sha256(data).hexdigest(),
            "saved_as": str((page_dir / page_name).relative_to(args.build)),
            "seed_role": seed_meta.get("role"),
            "links_found": len(links),
        })
        for link in links:
            haystack = f"{link.text} {link.url}"
            if RELEVANT.search(haystack) or DOWNLOAD_PATH.search(link.url) or LIKELY_BINARY.search(link.url):
                discovered[link.url] = link
            if depth < 2 and should_follow(link, seed_hosts) and link.url not in visited:
                queue.append((link.url, depth + 1, {"role": "crawled", "authority": seed_meta.get("authority")}))

    for item in SECONDARY_MIRRORS:
        discovered[item["url"]] = Link("secondary-mirror-list", item["url"], item["role"], 0)

    assets: list[dict] = []
    candidates = sorted(discovered.values(), key=lambda item: item.url)
    for index, link in enumerate(candidates, 1):
        if not (DOWNLOAD_PATH.search(link.url) or LIKELY_BINARY.search(link.url)):
            continue
        try:
            data, headers, status, final_url = request(link.url, timeout=120)
            if is_html(headers, data, final_url):
                assets.append({
                    "source_url": link.source_url,
                    "requested_url": link.url,
                    "final_url": final_url,
                    "anchor_text": link.text,
                    "download_status": "HTML_NOT_BINARY",
                    "http_status": status,
                    "content_type": headers.get("content-type"),
                    "size": len(data),
                    **hash_record(data),
                })
                continue
            filename = filename_from(headers, final_url, data, index)
            destination = asset_dir / f"{index:03d}-{filename}"
            destination.write_bytes(data)
            archive = list_archive(destination)
            assets.append({
                "source_url": link.source_url,
                "requested_url": link.url,
                "final_url": final_url,
                "anchor_text": link.text,
                "download_status": "SUCCESS",
                "http_status": status,
                "content_type": headers.get("content-type"),
                "content_disposition": headers.get("content-disposition"),
                "size": len(data),
                "saved_as": str(destination.relative_to(args.build)),
                **hash_record(data),
                "archive": archive,
            })
        except Exception as exc:
            failures.append({"url": link.url, "source_url": link.source_url, "phase": "asset_fetch", "error": str(exc)})

    relevant_links = [asdict(link) for link in candidates]
    manifest = {
        "schema_version": "0.2.0",
        "generated_at_epoch": int(time.time()),
        "generator": "tools/regulatory/fetch_cde_sources.py",
        "policy": {
            "authority_order": ["CDE/NMPA effective official files", "ICH base specification", "secondary mirror"],
            "binary_storage": "Actions artifact; only metadata and hashes are committed",
            "limitations": "Dynamic CDE downloads and desktop software may require manual browser retrieval. A failed automated download is not evidence that the asset does not exist.",
        },
        "seeds": SEEDS,
        "secondary_mirrors": SECONDARY_MIRRORS,
        "summary": {
            "html_pages_fetched": len(pages),
            "relevant_links_discovered": len(relevant_links),
            "binary_downloads_successful": sum(a.get("download_status") == "SUCCESS" for a in assets),
            "binary_candidates_not_downloaded": sum(a.get("download_status") != "SUCCESS" for a in assets),
            "failures": len(failures),
        },
        "pages": pages,
        "links": relevant_links,
        "assets": assets,
        "failures": failures,
    }
    args.evidence.mkdir(parents=True, exist_ok=True)
    (args.evidence / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    unresolved = [f for f in failures]
    unresolved += [{"url": a["requested_url"], "phase": "asset_fetch", "status": a["download_status"]} for a in assets if a.get("download_status") != "SUCCESS"]
    (args.evidence / "unresolved.json").write_text(json.dumps({"count": len(unresolved), "items": unresolved}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme = f"""# CDE/ICH regulatory source snapshot\n\nGenerated by `tools/regulatory/fetch_cde_sources.py`.\n\n- HTML pages fetched: {len(pages)}\n- Relevant links discovered: {len(relevant_links)}\n- Binary downloads successful: {manifest['summary']['binary_downloads_successful']}\n- Failed or unresolved items: {len(unresolved)}\n\nThe committed manifest records URLs, redirects, HTTP metadata, sizes and hashes. Downloaded binaries are uploaded as a GitHub Actions artifact rather than committed to the source tree. Secondary mirrors are explicitly labelled and never override an effective CDE source.\n"""
    (args.evidence / "README.md").write_text(readme, encoding="utf-8")
    print(json.dumps(manifest["summary"], ensure_ascii=False))
    return 0 if pages else 2


if __name__ == "__main__":
    raise SystemExit(main())
