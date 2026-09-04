from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

PORTAL = "https://www.cde.org.cn/ectd/index"
LEGACY_PATH = Path(__file__).with_name("acquire_validator_from_portal.py")
ASSETS = [
    {
        "role": "validator_software_v1_1_0",
        "label": "eCTD验证软件",
        "control": "downloadFiles(4)",
        "relative_url": "/ectd/guideDownLoads/eCTDYZV1.1.0.zip?name=eCTD验证软件V1.1.0.zip",
        "expected_kinds": {"zip", "rar", "7z", "pe", "msi"},
        "minimum_size": 100_000,
    },
    {
        "role": "validator_manual_v1_1_0",
        "label": "eCTD验证软件操作手册",
        "control": "downloadFiles(5)",
        "relative_url": "/ectd/guideDownLoads/eCTDYZSCV1.1.0.pdf?name=eCTD验证软件操作手册V1.1.0.pdf",
        "expected_kinds": {"pdf"},
        "minimum_size": 25_000,
    },
]


def load_legacy():
    spec = importlib.util.spec_from_file_location("ezctd_validator_acquisition_legacy", LEGACY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper module: {LEGACY_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def browser_options(download_dir: Path) -> Options:
    options = Options()
    if os.environ.get("EZCTD_BROWSER_HEADLESS", "0") == "1":
        options.add_argument("--headless=new")
    for value in (
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--window-size=1600,1200",
        "--lang=zh-CN",
        "--disable-blink-features=AutomationControlled",
        "--ignore-certificate-errors",
    ):
        options.add_argument(value)
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    )
    options.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(download_dir.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "plugins.always_open_pdf_externally": True,
        },
    )
    return options


def browser_session(driver: webdriver.Chrome) -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": driver.execute_script("return navigator.userAgent"),
            "Referer": PORTAL,
            "Accept": "*/*",
        }
    )
    for cookie in driver.get_cookies():
        session.cookies.set(
            cookie["name"], cookie["value"], domain=cookie.get("domain"), path=cookie.get("path", "/")
        )
    return session


def filename_from_response(response: requests.Response, fallback_url: str) -> str:
    disposition = response.headers.get("content-disposition", "")
    match = re.search(r"filename\*=UTF-8''([^;]+)", disposition, flags=re.I)
    if not match:
        match = re.search(r'filename="?([^";]+)', disposition, flags=re.I)
    if match:
        value = urllib.parse.unquote(match.group(1))
    else:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(fallback_url).query)
        value = query.get("name", [Path(urllib.parse.urlparse(response.url).path).name])[0]
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# CDE eCTD validation software V1.1.0 — portal acquisition v3",
        "",
        f"- Status: **{payload['status']}**",
        f"- Portal: {payload['portal']}",
        f"- Common JavaScript: `{payload.get('common_js', {}).get('url')}`",
        f"- Common JavaScript SHA-256: `{payload.get('common_js', {}).get('sha256')}`",
        "- Validator executed: **false**",
        "- Official black-box observations: **0**",
        "",
        "## Root-cause correction",
        "",
        "`downloadFiles(4/5)` opens a LayUI attachment dialog. It does not initiate the file transfer. The v2 collector waited for a download that could never start and therefore returned `candidates=[]`. V3 verifies the exact direct URLs inside the currently served official `common.js`, then downloads those bytes with the same browser session.",
        "",
        "| Role | Official control | Kind | Bytes | SHA-256 |",
        "|---|---|---:|---:|---|",
    ]
    for item in payload.get("records", []):
        lines.append(
            f"| `{item['role']}` | `{item['portal_control']}` | {item['kind']} | "
            f"{item['size']} | `{item['sha256']}` |"
        )
    lines += [
        "",
        "## Boundary",
        "",
        "This evidence proves official-portal provenance and byte-valid acquisition only. Static identity inspection and controlled execution remain separate gates; no CDE compatibility claim is made here.",
        "",
    ]
    if payload.get("errors"):
        lines += ["## Errors", ""] + [f"- {error}" for error in payload["errors"]] + [""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--build", type=Path, default=Path("build/official-validator-acquisition-v3")
    )
    parser.add_argument(
        "--evidence", type=Path, default=Path("evidence/regulatory/snapshots/cde-validator-v1.1.0")
    )
    args = parser.parse_args()
    raw_dir = args.build / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    args.evidence.mkdir(parents=True, exist_ok=True)

    legacy = load_legacy()
    payload: dict[str, Any] = {
        "schema_version": "0.3.0",
        "status": "FAILED",
        "portal": PORTAL,
        "method": "official_control_plus_current_same_origin_javascript",
        "software_executed": False,
        "official_black_box_observations": 0,
        "records": [],
        "errors": [],
    }
    driver: webdriver.Chrome | None = None
    try:
        driver = webdriver.Chrome(options=browser_options(raw_dir))
        driver.set_page_load_timeout(90)
        driver.get(PORTAL)
        WebDriverWait(driver, 60).until(
            lambda d: d.execute_script("return document.readyState") in {"interactive", "complete"}
        )
        WebDriverWait(driver, 60).until(
            lambda d: "eCTD验证软件" in (d.execute_script("return document.body.innerText") or "")
        )
        driver.save_screenshot(str(args.build / "portal.png"))
        (args.build / "portal.html").write_text(driver.page_source, encoding="utf-8")

        controls = []
        for asset in ASSETS:
            selector = f'[onclick="{asset["control"]}"]'
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            if len(elements) != 1:
                raise RuntimeError(f"expected exactly one official control {selector}; found {len(elements)}")
            controls.append(
                {
                    "role": asset["role"],
                    "selector": selector,
                    "outer_html": elements[0].get_attribute("outerHTML"),
                    "text": elements[0].text,
                }
            )
        payload["portal_controls"] = controls

        function_source = driver.execute_script(
            "return window.downloadFiles ? window.downloadFiles.toString() : null"
        )
        if not function_source:
            raise RuntimeError("window.downloadFiles is unavailable")
        (args.build / "downloadFiles.js").write_text(function_source, encoding="utf-8")
        payload["download_files_function_sha256"] = sha256_bytes(function_source.encode("utf-8"))

        script_urls = driver.execute_script(
            "return Array.from(document.scripts).map(s => s.src).filter(Boolean)"
        )
        common_candidates = [url for url in script_urls if "/ectd/js/common.js" in url]
        if len(common_candidates) != 1:
            raise RuntimeError(f"expected one current common.js; found {common_candidates}")
        common_url = common_candidates[0]
        session = browser_session(driver)
        common_response = session.get(common_url, timeout=120, allow_redirects=True)
        common_response.raise_for_status()
        common_bytes = common_response.content
        common_text = common_bytes.decode("utf-8", errors="replace")
        (args.build / "common.js").write_bytes(common_bytes)
        payload["common_js"] = {
            "url": common_url,
            "final_url": common_response.url,
            "status": common_response.status_code,
            "content_type": common_response.headers.get("content-type"),
            "etag": common_response.headers.get("etag"),
            "last_modified": common_response.headers.get("last-modified"),
            "size": len(common_bytes),
            "sha256": sha256_bytes(common_bytes),
        }

        combined_source = function_source + "\n" + common_text
        for asset in ASSETS:
            if asset["relative_url"] not in combined_source:
                raise RuntimeError(
                    f"current official JavaScript does not contain expected URL for {asset['role']}"
                )
            url = urllib.parse.urljoin(PORTAL, asset["relative_url"])
            response = session.get(url, timeout=300, allow_redirects=True)
            response.raise_for_status()
            filename = filename_from_response(response, url)
            path = raw_dir / filename
            path.write_bytes(response.content)
            detected = legacy.kind(path)
            if detected not in asset["expected_kinds"]:
                raise RuntimeError(
                    f"{asset['role']} returned kind={detected}, expected={sorted(asset['expected_kinds'])}"
                )
            if path.stat().st_size <= asset["minimum_size"]:
                raise RuntimeError(
                    f"{asset['role']} is unexpectedly small: {path.stat().st_size} bytes"
                )
            record = {
                "role": asset["role"],
                "portal_label": asset["label"],
                "portal_control": asset["control"],
                "discovered_in_current_official_javascript": True,
                "url": url,
                "final_url": response.url,
                "http_status": response.status_code,
                "content_type": response.headers.get("content-type"),
                "content_disposition": response.headers.get("content-disposition"),
                "file_name": filename,
                "kind": detected,
                "size": path.stat().st_size,
                "sha256": legacy.sha(path, "sha256"),
                "sm3": legacy.sha(path, "sm3"),
            }
            if detected in {"zip", "rar", "7z", "pe", "msi"}:
                record["archive"] = legacy.archive_inventory(path, args.build)
            if detected == "pdf":
                record["pdf"] = legacy.pdf_metadata(path, args.build)
            payload["records"].append(record)

        payload["status"] = "COMPLETE_OFFICIAL_PORTAL_ACQUISITION"
    except Exception as exc:
        payload["errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception as exc:
                payload["errors"].append(f"driver.quit: {type(exc).__name__}: {exc}")
        write_json(args.build / "acquisition.json", payload)
        write_json(args.evidence / "official-portal-acquisition.json", payload)
        (args.evidence / "README.md").write_text(render_markdown(payload), encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["status"] == "COMPLETE_OFFICIAL_PORTAL_ACQUISITION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
