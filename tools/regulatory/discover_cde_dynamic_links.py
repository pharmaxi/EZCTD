from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

PAGES = [
    {
        "source_id": "CDE-ECTD-COLUMN",
        "url": "https://www.cde.org.cn/ectd/index",
    },
    {
        "source_id": "CDE-CN-V4-DRAFT-NOTICE",
        "url": "https://www.cde.org.cn/main/news/viewInfoCommon/7898f68946d8e8e44d074657c7112002",
    },
]

DOWNLOAD_HINT = re.compile(
    r"(?:/main/att/download/|/ectd/guideDownLoads/|download|\.pdf(?:$|\?)|\.zip(?:$|\?)|\.rar(?:$|\?)|\.exe(?:$|\?)|\.msi(?:$|\?)|\.xlsx(?:$|\?)|\.docx(?:$|\?))",
    re.I,
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "page"


def build_driver() -> webdriver.Chrome:
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1600,1400")
    options.add_argument("--lang=zh-CN")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(90)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"},
    )
    return driver


def collect_page(driver: webdriver.Chrome, source_id: str, url: str, output: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "source_id": source_id,
        "requested_url": url,
        "status": "STARTED",
        "final_url": None,
        "title": None,
        "body_text_length": 0,
        "html_sha256": None,
        "anchors": [],
        "network_urls": [],
        "download_candidates": [],
        "browser_console": [],
        "error": None,
    }
    try:
        driver.get(url)
        WebDriverWait(driver, 45).until(lambda d: d.execute_script("return document.readyState") == "complete")
        # CDE may first render a dynamic protection page; allow its script to settle.
        for _ in range(4):
            time.sleep(3)
            body = driver.find_element(By.TAG_NAME, "body").text if driver.find_elements(By.TAG_NAME, "body") else ""
            if any(token in body for token in ["相关附件", "常用下载", "eCTD技术规范", "受控词汇"]):
                break
        html = driver.page_source
        body = driver.find_element(By.TAG_NAME, "body").text if driver.find_elements(By.TAG_NAME, "body") else ""
        anchors = driver.execute_script(
            "return Array.from(document.querySelectorAll('a')).map(a => ({href: a.href || '', text: (a.innerText || a.textContent || '').trim(), title: a.title || '', download: a.download || ''}));"
        )
        resources = driver.execute_script(
            "return performance.getEntriesByType('resource').map(r => ({name: r.name, initiatorType: r.initiatorType}));"
        )
        network_urls: set[str] = set()
        for entry in driver.get_log("performance"):
            try:
                message = json.loads(entry["message"])["message"]
                params = message.get("params", {})
                response = params.get("response", {})
                request = params.get("request", {})
                candidate = response.get("url") or request.get("url")
                if candidate:
                    network_urls.add(candidate)
            except Exception:
                continue
        for item in resources:
            if item.get("name"):
                network_urls.add(item["name"])
        all_candidates: dict[str, dict[str, Any]] = {}
        for anchor in anchors:
            href = anchor.get("href", "")
            if href and DOWNLOAD_HINT.search(href + " " + anchor.get("text", "")):
                all_candidates[href] = {"url": href, "text": anchor.get("text", ""), "source": "anchor"}
        for candidate in network_urls:
            if DOWNLOAD_HINT.search(candidate):
                all_candidates.setdefault(candidate, {"url": candidate, "text": "", "source": "network"})
        record.update(
            {
                "status": "SUCCESS",
                "final_url": driver.current_url,
                "title": driver.title,
                "body_text_length": len(body),
                "body_text_excerpt": body[:12000],
                "html_sha256": sha256_bytes(html.encode("utf-8")),
                "anchors": anchors,
                "network_urls": sorted(network_urls),
                "download_candidates": sorted(all_candidates.values(), key=lambda item: item["url"]),
                "browser_console": driver.get_log("browser"),
            }
        )
        stem = safe_filename(source_id)
        (output / f"{stem}.rendered.html").write_text(html, encoding="utf-8")
        (output / f"{stem}.body.txt").write_text(body, encoding="utf-8")
        driver.save_screenshot(str(output / f"{stem}.png"))
    except Exception as exc:
        record.update({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"})
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("build/official-source-deep-dive/browser-discovery"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    driver = build_driver()
    records: list[dict[str, Any]] = []
    try:
        for item in PAGES:
            records.append(collect_page(driver, item["source_id"], item["url"], args.output))
    finally:
        driver.quit()

    candidates: dict[str, dict[str, Any]] = {}
    for record in records:
        for candidate in record.get("download_candidates", []):
            value = {**candidate, "source_id": record["source_id"], "source_url": record["final_url"] or record["requested_url"]}
            candidates[candidate["url"]] = value
    payload = {
        "schema_version": "0.1.0",
        "generator": "tools/regulatory/discover_cde_dynamic_links.py",
        "pages": records,
        "download_candidates": sorted(candidates.values(), key=lambda item: item["url"]),
        "summary": {
            "pages": len(records),
            "successful_pages": sum(item["status"] == "SUCCESS" for item in records),
            "download_candidates": len(candidates),
            "v4_named_candidates": sum("v4" in (item.get("text", "") + item["url"]).lower() for item in candidates.values()),
        },
    }
    (args.output / "dynamic-link-discovery.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    # Do not fail merely because the protection layer hid links; preserve evidence for the next loop.
    return 0 if payload["summary"]["successful_pages"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
