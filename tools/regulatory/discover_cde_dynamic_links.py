from __future__ import annotations

import argparse
import hashlib
import json
import os
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
    if os.environ.get("EZCTD_BROWSER_HEADLESS", "0") == "1":
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1600,1400")
    options.add_argument("--lang=zh-CN,zh,en-US,en")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--start-maximized")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option("useAutomationExtension", False)
    options.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(90)
    driver.execute_cdp_cmd("Network.enable", {})
    driver.execute_cdp_cmd("Emulation.setTimezoneOverride", {"timezoneId": "Asia/Shanghai"})
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {
            "source": """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN','zh','en-US','en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            window.chrome = window.chrome || {runtime: {}};
            """
        },
    )
    return driver


def drain_network(driver: webdriver.Chrome) -> tuple[list[str], list[dict[str, Any]]]:
    urls: set[str] = set()
    responses: list[dict[str, Any]] = []
    for entry in driver.get_log("performance"):
        try:
            message = json.loads(entry["message"])["message"]
            method = message.get("method")
            params = message.get("params", {})
            if method == "Network.responseReceived":
                response = params.get("response", {})
                url = response.get("url")
                if url:
                    urls.add(url)
                item: dict[str, Any] = {
                    "request_id": params.get("requestId"),
                    "url": url,
                    "status": response.get("status"),
                    "status_text": response.get("statusText"),
                    "mime_type": response.get("mimeType"),
                    "remote_ip": response.get("remoteIPAddress"),
                    "from_disk_cache": response.get("fromDiskCache"),
                    "from_service_worker": response.get("fromServiceWorker"),
                    "headers": response.get("headers", {}),
                }
                request_id = item.get("request_id")
                if request_id and response.get("status", 0) >= 400:
                    try:
                        body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
                        item["body_excerpt"] = body.get("body", "")[:4000]
                        item["body_base64"] = bool(body.get("base64Encoded"))
                    except Exception as exc:
                        item["body_error"] = f"{type(exc).__name__}: {exc}"
                responses.append(item)
            elif method == "Network.requestWillBeSent":
                request = params.get("request", {})
                if request.get("url"):
                    urls.add(request["url"])
        except Exception:
            continue
    return sorted(urls), responses


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
        "network_responses": [],
        "download_candidates": [],
        "browser_console": [],
        "cookies": [],
        "attempts": [],
        "error": None,
    }
    stem = safe_filename(source_id)
    try:
        final_body = ""
        final_html = ""
        for attempt in range(1, 4):
            driver.get(url)
            WebDriverWait(driver, 45).until(lambda d: d.execute_script("return document.readyState") == "complete")
            for _ in range(6):
                time.sleep(3)
                final_body = driver.find_element(By.TAG_NAME, "body").text if driver.find_elements(By.TAG_NAME, "body") else ""
                final_html = driver.page_source
                if any(token in final_body for token in ["相关附件", "常用下载", "eCTD技术规范", "受控词汇"]):
                    break
            network_urls, network_responses = drain_network(driver)
            record["attempts"].append(
                {
                    "attempt": attempt,
                    "final_url": driver.current_url,
                    "title": driver.title,
                    "body_text_length": len(final_body),
                    "html_length": len(final_html),
                    "network_urls": network_urls,
                    "network_responses": network_responses,
                    "cookies": driver.get_cookies(),
                }
            )
            if len(final_body) > 100 or "相关附件" in final_body:
                break
            # Warm the origin and obtain a fresh protection cookie before retrying.
            driver.get("https://www.cde.org.cn/")
            time.sleep(6)
        html = final_html or driver.page_source
        body = final_body
        anchors = driver.execute_script(
            "return Array.from(document.querySelectorAll('a')).map(a => ({href: a.href || '', text: (a.innerText || a.textContent || '').trim(), title: a.title || '', download: a.download || ''}));"
        )
        resources = driver.execute_script(
            "return performance.getEntriesByType('resource').map(r => ({name: r.name, initiatorType: r.initiatorType}));"
        )
        network_urls, network_responses = drain_network(driver)
        for item in resources:
            if item.get("name"):
                network_urls.append(item["name"])
        network_urls = sorted(set(network_urls))
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
                "status": "SUCCESS_WITH_CONTENT" if len(body) > 100 else "SUCCESS_BLANK_AFTER_PROTECTION_CHALLENGE",
                "final_url": driver.current_url,
                "title": driver.title,
                "body_text_length": len(body),
                "body_text_excerpt": body[:12000],
                "html_sha256": sha256_bytes(html.encode("utf-8")),
                "anchors": anchors,
                "network_urls": network_urls,
                "network_responses": network_responses,
                "download_candidates": sorted(all_candidates.values(), key=lambda item: item["url"]),
                "browser_console": driver.get_log("browser"),
                "cookies": driver.get_cookies(),
                "capabilities": {
                    "browser_name": driver.capabilities.get("browserName"),
                    "browser_version": driver.capabilities.get("browserVersion"),
                    "platform": driver.capabilities.get("platformName"),
                },
            }
        )
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
        # Establish an origin session before the two target pages.
        try:
            driver.get("https://www.cde.org.cn/")
            time.sleep(8)
            drain_network(driver)
        except Exception:
            pass
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
        "schema_version": "0.2.0",
        "generator": "tools/regulatory/discover_cde_dynamic_links.py",
        "pages": records,
        "download_candidates": sorted(candidates.values(), key=lambda item: item["url"]),
        "summary": {
            "pages": len(records),
            "pages_with_content": sum(item["status"] == "SUCCESS_WITH_CONTENT" for item in records),
            "blank_after_challenge": sum(item["status"] == "SUCCESS_BLANK_AFTER_PROTECTION_CHALLENGE" for item in records),
            "download_candidates": len(candidates),
            "v4_named_candidates": sum("v4" in (item.get("text", "") + item["url"]).lower() for item in candidates.values()),
        },
    }
    (args.output / "dynamic-link-discovery.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    # Blank output is a recorded protection-layer result, not permission to fabricate URLs.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
