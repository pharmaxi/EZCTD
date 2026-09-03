from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

PORTAL = "https://www.cde.org.cn/ectd/index"
ACTIONS = [
    {
        "role": "validator_software_v1_1_0",
        "label": "eCTD验证软件",
        "onclick": "downloadFiles(4)",
        "expected_kinds": {"zip", "rar", "7z", "pe", "msi"},
    },
    {
        "role": "validator_manual_v1_1_0",
        "label": "eCTD验证软件操作手册",
        "onclick": "downloadFiles(5)",
        "expected_kinds": {"pdf"},
    },
]


def options(download_dir: Path) -> Options:
    opts = Options()
    if os.environ.get("EZCTD_BROWSER_HEADLESS", "0") == "1":
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1600,1200")
    opts.add_argument("--lang=zh-CN")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    )
    opts.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(download_dir.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,
            "safebrowsing.enabled": True,
        },
    )
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    return opts


def sha(path: Path, algorithm: str) -> str | None:
    try:
        h = hashlib.new(algorithm)
    except ValueError:
        return None
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def kind(path: Path) -> str:
    data = path.read_bytes()[:16]
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        return "zip"
    if data.startswith(b"Rar!\x1a\x07"):
        return "rar"
    if data.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "7z"
    if data.startswith(b"MZ"):
        return "pe"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "msi"
    return "unknown"


def safe_name(value: str, fallback: str) -> str:
    value = urllib.parse.unquote(value)
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return value[:180] or fallback


def performance_urls(driver: webdriver.Chrome) -> list[dict[str, Any]]:
    events = []
    for entry in driver.get_log("performance"):
        try:
            msg = json.loads(entry["message"])["message"]
        except Exception:
            continue
        method = msg.get("method")
        params = msg.get("params", {})
        if method == "Network.requestWillBeSent":
            req = params.get("request", {})
            url = req.get("url")
            if url:
                events.append({"method": method, "url": url, "mime_type": None})
        elif method == "Network.responseReceived":
            response = params.get("response", {})
            url = response.get("url")
            if url:
                events.append(
                    {
                        "method": method,
                        "url": url,
                        "mime_type": response.get("mimeType"),
                        "status": response.get("status"),
                    }
                )
    return events


def wait_for_new_file(directory: Path, before: set[Path], timeout: int = 150) -> Path | None:
    deadline = time.time() + timeout
    last: tuple[Path, int] | None = None
    stable = 0
    while time.time() < deadline:
        candidates = [
            p
            for p in directory.iterdir()
            if p.is_file() and p not in before and not p.name.endswith((".crdownload", ".tmp", ".part"))
        ]
        if candidates:
            newest = max(candidates, key=lambda p: p.stat().st_mtime_ns)
            current = (newest, newest.stat().st_size)
            if current == last and current[1] > 0:
                stable += 1
                if stable >= 3:
                    return newest
            else:
                last = current
                stable = 0
        time.sleep(1)
    return None


def session_from_driver(driver: webdriver.Chrome) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": driver.execute_script("return navigator.userAgent"),
            "Referer": PORTAL,
            "Accept": "*/*",
        }
    )
    for cookie in driver.get_cookies():
        session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"), path=cookie.get("path", "/"))
    return session


def candidate_urls(events: list[dict[str, Any]], handles: list[str], driver: webdriver.Chrome) -> list[str]:
    found: list[str] = []
    for event in events:
        url = event.get("url", "")
        if re.search(r"/ectd/guideDownLoads/|/main/att/download/|\.(?:pdf|zip|rar|7z|exe|msi)(?:$|\?)", url, re.I):
            found.append(url)
    current = driver.current_window_handle
    for handle in handles:
        try:
            driver.switch_to.window(handle)
            url = driver.current_url
            if url and url not in {"about:blank", PORTAL}:
                found.append(url)
        except Exception:
            continue
    try:
        driver.switch_to.window(current)
    except Exception:
        pass
    return list(dict.fromkeys(found))


def fetch_candidate(driver: webdriver.Chrome, urls: list[str], output_dir: Path, role: str) -> tuple[Path | None, list[dict[str, Any]]]:
    session = session_from_driver(driver)
    attempts = []
    for index, url in enumerate(urls, 1):
        try:
            response = session.get(url, allow_redirects=True, timeout=180)
            item = {
                "url": url,
                "final_url": response.url,
                "status": response.status_code,
                "content_type": response.headers.get("content-type"),
                "content_disposition": response.headers.get("content-disposition"),
                "size": len(response.content),
            }
            attempts.append(item)
            if response.status_code != 200 or not response.content:
                continue
            disposition = response.headers.get("content-disposition", "")
            match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, re.I)
            if not match:
                match = re.search(r'filename="?([^";]+)', disposition, re.I)
            filename = safe_name(
                match.group(1) if match else Path(urllib.parse.urlparse(response.url).path).name,
                f"{role}-{index}",
            )
            path = output_dir / filename
            path.write_bytes(response.content)
            if kind(path) != "unknown":
                return path, attempts
        except Exception as exc:
            attempts.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
    return None, attempts


def archive_inventory(path: Path, output_dir: Path) -> dict[str, Any]:
    result = {"status": "NOT_ARCHIVE", "members": [], "extracted_files": []}
    extract_dir = output_dir / f"extract-{sha(path, 'sha256')[:16]}"
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for info in archive.infolist():
                    target = (extract_dir / info.filename).resolve()
                    if extract_dir.resolve() not in target.parents and target != extract_dir.resolve():
                        raise RuntimeError(f"unsafe archive path: {info.filename}")
                result["members"] = [
                    {"name": info.filename, "size": info.file_size, "compressed_size": info.compress_size}
                    for info in archive.infolist()
                ]
                archive.extractall(extract_dir)
        else:
            seven = shutil.which("7z") or shutil.which("7zz")
            if not seven:
                return {"status": "TOOL_MISSING", "members": [], "extracted_files": []}
            listing = subprocess.run(
                [seven, "l", "-slt", str(path)],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=180,
            )
            if listing.returncode != 0:
                return {"status": "LIST_FAILED", "error": (listing.stderr or listing.stdout)[-2000:], "members": []}
            members = []
            current: dict[str, str] = {}
            for line in listing.stdout.splitlines() + [""]:
                if not line.strip():
                    if current.get("Path") and current.get("Path") not in {str(path), path.name} and current.get("Folder") != "+":
                        members.append(
                            {
                                "name": current["Path"],
                                "size": int(current.get("Size", "0") or 0),
                                "compressed_size": int(current.get("Packed Size", "0") or 0),
                            }
                        )
                    current = {}
                elif " = " in line:
                    key, value = line.split(" = ", 1)
                    current[key.strip()] = value.strip()
            result["members"] = members
            extraction = subprocess.run(
                [seven, "x", "-y", f"-o{extract_dir}", str(path)],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=300,
            )
            if extraction.returncode != 0:
                result.update({"status": "EXTRACT_FAILED", "error": (extraction.stderr or extraction.stdout)[-2000:]})
                return result
        extracted = []
        for member in sorted(p for p in extract_dir.rglob("*") if p.is_file()):
            extracted.append(
                {
                    "relative_path": member.relative_to(extract_dir).as_posix(),
                    "size": member.stat().st_size,
                    "kind": kind(member),
                    "sha256": sha(member, "sha256"),
                }
            )
        result.update({"status": "EXTRACTED_FOR_STATIC_INSPECTION", "extracted_files": extracted})
    except Exception as exc:
        result.update({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
    return result


def pdf_metadata(path: Path, output_dir: Path) -> dict[str, Any]:
    result = {"status": "NOT_RUN", "pages": None, "text_file": None}
    if not shutil.which("pdfinfo") or not shutil.which("pdftotext"):
        return {"status": "TOOLS_MISSING", "pages": None}
    info = subprocess.run(["pdfinfo", str(path)], capture_output=True, text=True, errors="replace", timeout=120)
    metadata = {}
    for line in info.stdout.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip()] = value.strip()
    text_path = output_dir / "validator-manual.txt"
    text = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", str(path), str(text_path)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=180,
    )
    result.update(
        {
            "status": "SUCCESS" if info.returncode == 0 and text.returncode == 0 else "PARTIAL",
            "pages": int(metadata["Pages"]) if metadata.get("Pages", "").isdigit() else None,
            "metadata": metadata,
            "text_file": text_path.name if text_path.exists() else None,
        }
    )
    return result


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# CDE eCTD validation software V1.1.0 — official portal acquisition",
        "",
        "> Static acquisition and inspection only. No installer, executable, DLL or script was launched. Role evidence comes from the rendered CDE portal labels and exact `downloadFiles(4/5)` controls.",
        "",
        f"- Portal: {payload['portal']}",
        f"- Status: **{payload['status']}**",
        "",
        "| Role | Portal label | Kind | Bytes | SHA-256 |",
        "|---|---|---:|---:|---|",
    ]
    for record in payload["records"]:
        lines.append(
            f"| `{record['role']}` | {record['portal_label']} | {record.get('kind')} | "
            f"{record.get('size')} | `{record.get('sha256')}` |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "- These assets are confirmed as the files reached from the current official eCTD portal controls, not from a secondary mirror.",
        "- Product version and signer identity are not inferred from the portal label alone. The software archive must undergo Windows Authenticode and file-version inspection.",
        "- Successful static inspection does not mean the program has been executed or the 26-rule black-box calibration has started.",
        "- Raw assets remain in a GitHub Actions artifact; only provenance, hashes, archive inventory and static metadata are committed.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build",
        type=Path,
        default=Path("build/official-source-deep-dive/validator-assets"),
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("evidence/regulatory/snapshots/cde-validator-v1.1.0"),
    )
    args = parser.parse_args()
    args.build.mkdir(parents=True, exist_ok=True)
    args.evidence.mkdir(parents=True, exist_ok=True)
    raw_dir = args.build / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    driver = webdriver.Chrome(options=options(raw_dir))
    records = []
    try:
        driver.set_page_load_timeout(90)
        driver.execute_cdp_cmd("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(raw_dir.resolve())})
        driver.get(PORTAL)
        WebDriverWait(driver, 60).until(
            lambda d: d.execute_script("return document.readyState") in {"interactive", "complete"}
        )
        time.sleep(10)
        body = driver.execute_script("return document.body ? document.body.innerText : ''") or ""
        if "eCTD验证软件" not in body:
            driver.refresh()
            WebDriverWait(driver, 60).until(
                lambda d: d.execute_script("return document.readyState") in {"interactive", "complete"}
            )
            time.sleep(10)
            body = driver.execute_script("return document.body ? document.body.innerText : ''") or ""
        if "eCTD验证软件" not in body:
            raise RuntimeError("official portal did not render the expected download controls")

        function_sources = {
            "downloadFiles": driver.execute_script(
                "return window.downloadFiles ? window.downloadFiles.toString() : null"
            ),
            "downloadFile": driver.execute_script(
                "return window.downloadFile ? window.downloadFile.toString() : null"
            ),
        }
        (args.build / "function-sources.json").write_text(
            json.dumps(function_sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        driver.save_screenshot(str(args.build / "portal.png"))

        for action in ACTIONS:
            selector = f'[onclick="{action["onclick"]}"]'
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if not elements:
                raise RuntimeError(f"portal control not found: {selector}")
            element = elements[0]
            before = set(raw_dir.iterdir())
            handles_before = set(driver.window_handles)
            _ = driver.get_log("performance")
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
            driver.execute_script("arguments[0].click();", element)
            downloaded = wait_for_new_file(raw_dir, before, timeout=150)
            time.sleep(3)
            events = performance_urls(driver)
            handles_after = driver.window_handles
            urls = candidate_urls(events, handles_after, driver)
            request_attempts = []
            if downloaded is None:
                downloaded, request_attempts = fetch_candidate(driver, urls, raw_dir, action["role"])
            if downloaded is None:
                raise RuntimeError(
                    f"no byte-valid asset acquired for {action['role']}; candidates={urls[-20:]}"
                )
            detected = kind(downloaded)
            if detected not in action["expected_kinds"]:
                raise RuntimeError(
                    f"{action['role']} kind mismatch: {detected}, file={downloaded.name}, candidates={urls[-20:]}"
                )
            record = {
                "role": action["role"],
                "portal_label": action["label"],
                "portal_onclick": action["onclick"],
                "portal_url": PORTAL,
                "download_method": "chrome_download" if not request_attempts else "browser_session_request",
                "file_name": downloaded.name,
                "size": downloaded.stat().st_size,
                "kind": detected,
                "sha256": sha(downloaded, "sha256"),
                "sm3": sha(downloaded, "sm3"),
                "candidate_urls": urls,
                "request_attempts": request_attempts,
                "new_window_count": len(set(handles_after) - handles_before),
            }
            if detected in {"zip", "rar", "7z", "pe", "msi"}:
                record["archive"] = archive_inventory(downloaded, args.build)
            if detected == "pdf":
                record["pdf"] = pdf_metadata(downloaded, args.build)
            records.append(record)
            for handle in list(driver.window_handles):
                if handle != driver.window_handles[0]:
                    try:
                        driver.switch_to.window(handle)
                        driver.close()
                    except Exception:
                        pass
            driver.switch_to.window(driver.window_handles[0])

    finally:
        driver.quit()

    payload = {
        "schema_version": "0.2.0",
        "status": "COMPLETE_OFFICIAL_PORTAL_ACQUISITION" if len(records) == 2 else "INCOMPLETE",
        "portal": PORTAL,
        "controls": {
            "validator": "downloadFiles(4)",
            "manual": "downloadFiles(5)",
        },
        "safety_scope": "Browser-triggered download followed by hashes, archive listing and PDF metadata only. No executable content was launched.",
        "records": records,
    }
    (args.evidence / "official-portal-acquisition.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (args.evidence / "README.md").write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "roles": [r["role"] for r in records]}, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "COMPLETE_OFFICIAL_PORTAL_ACQUISITION" else 2


if __name__ == "__main__":
    raise SystemExit(main())
