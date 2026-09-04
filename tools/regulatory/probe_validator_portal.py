from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

PORTAL = "https://www.cde.org.cn/ectd/index"
TARGETS = [
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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_kind(path: Path) -> str:
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


def chrome_options(download_dir: Path) -> Options:
    opts = Options()
    if os.environ.get("EZCTD_BROWSER_HEADLESS", "0") == "1":
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1800,1400")
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


def json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
        session.cookies.set(
            cookie["name"],
            cookie["value"],
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )
    return session


def drain_logs(driver: webdriver.Chrome) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {"performance": [], "browser": []}
    for log_type in ("performance", "browser"):
        try:
            entries = driver.get_log(log_type)
        except Exception as exc:  # pragma: no cover - browser dependent
            result[log_type].append({"error": f"{type(exc).__name__}: {exc}"})
            continue
        for entry in entries:
            if log_type == "performance":
                try:
                    message = json.loads(entry.get("message", "{}"))["message"]
                    method = message.get("method")
                    params = message.get("params", {})
                    compact: dict[str, Any] = {
                        "method": method,
                        "timestamp": entry.get("timestamp"),
                    }
                    if method == "Network.requestWillBeSent":
                        request = params.get("request", {})
                        compact.update(
                            {
                                "url": request.get("url"),
                                "http_method": request.get("method"),
                                "resource_type": params.get("type"),
                            }
                        )
                    elif method == "Network.responseReceived":
                        response = params.get("response", {})
                        compact.update(
                            {
                                "url": response.get("url"),
                                "status": response.get("status"),
                                "mime_type": response.get("mimeType"),
                                "resource_type": params.get("type"),
                            }
                        )
                    elif method in {"Page.downloadWillBegin", "Page.downloadProgress"}:
                        compact.update(params)
                    else:
                        continue
                    result[log_type].append(compact)
                except Exception:
                    result[log_type].append(entry)
            else:
                result[log_type].append(entry)
    return result


def install_hooks(driver: webdriver.Chrome) -> None:
    driver.execute_script(
        r"""
        (() => {
          if (window.__ezctdProbeInstalled) return;
          window.__ezctdProbeInstalled = true;
          window.__ezctdProbe = {
            events: [],
            mutations: [],
            startedAt: new Date().toISOString()
          };
          const push = (type, data) => {
            try {
              window.__ezctdProbe.events.push({
                at: new Date().toISOString(),
                type,
                data: JSON.parse(JSON.stringify(data ?? null))
              });
            } catch (_) {
              window.__ezctdProbe.events.push({at: new Date().toISOString(), type, data: String(data)});
            }
          };

          const originalOpen = window.open;
          window.open = function(...args) {
            push('window.open', args);
            return originalOpen.apply(this, args);
          };

          if (window.fetch) {
            const originalFetch = window.fetch;
            window.fetch = function(...args) {
              push('fetch', args.map(v => typeof v === 'string' ? v : String(v)));
              return originalFetch.apply(this, args);
            };
          }

          const originalXhrOpen = XMLHttpRequest.prototype.open;
          XMLHttpRequest.prototype.open = function(method, url, ...rest) {
            this.__ezctdProbeRequest = {method, url};
            push('xhr.open', {method, url});
            return originalXhrOpen.call(this, method, url, ...rest);
          };
          const originalXhrSend = XMLHttpRequest.prototype.send;
          XMLHttpRequest.prototype.send = function(body) {
            push('xhr.send', this.__ezctdProbeRequest || null);
            return originalXhrSend.call(this, body);
          };

          const originalAnchorClick = HTMLAnchorElement.prototype.click;
          HTMLAnchorElement.prototype.click = function(...args) {
            push('anchor.click', {
              text: (this.innerText || this.textContent || '').trim(),
              href: this.href,
              download: this.download,
              onclick: this.getAttribute('onclick')
            });
            return originalAnchorClick.apply(this, args);
          };

          const originalSubmit = HTMLFormElement.prototype.submit;
          HTMLFormElement.prototype.submit = function(...args) {
            push('form.submit', {action: this.action, method: this.method});
            return originalSubmit.apply(this, args);
          };

          const wrapNamedFunction = (name) => {
            const original = window[name];
            if (typeof original !== 'function' || original.__ezctdWrapped) return;
            const wrapped = function(...args) {
              push(`call:${name}`, args);
              return original.apply(this, args);
            };
            wrapped.__ezctdWrapped = true;
            wrapped.__ezctdOriginal = original;
            window[name] = wrapped;
          };
          wrapNamedFunction('downloadFile');
          wrapNamedFunction('downloadFiles');

          const observer = new MutationObserver(records => {
            for (const record of records) {
              const added = [...record.addedNodes].slice(0, 20).map(node => {
                if (!(node instanceof Element)) return {nodeType: node.nodeType, text: String(node.textContent || '').slice(0, 300)};
                return {
                  tag: node.tagName,
                  id: node.id || null,
                  className: String(node.className || '').slice(0, 200),
                  text: String(node.innerText || node.textContent || '').trim().slice(0, 500),
                  html: node.outerHTML.slice(0, 1500)
                };
              });
              if (added.length) {
                window.__ezctdProbe.mutations.push({
                  at: new Date().toISOString(),
                  target: record.target instanceof Element ? record.target.tagName : String(record.target),
                  added
                });
              }
            }
          });
          observer.observe(document.documentElement, {childList: true, subtree: true});
        })();
        """
    )


def collect_controls(driver: webdriver.Chrome) -> list[dict[str, Any]]:
    return driver.execute_script(
        r"""
        const selectors = 'a,button,input,[role="button"],[onclick],.layui-layer,.layui-layer-content';
        return [...document.querySelectorAll(selectors)].map((el, index) => {
          const style = getComputedStyle(el);
          const rect = el.getBoundingClientRect();
          const visible = style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          return {
            index,
            tag: el.tagName,
            id: el.id || null,
            className: String(el.className || '').slice(0, 300),
            text: String(el.innerText || el.value || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 500),
            href: el.href || null,
            download: el.download || null,
            onclick: el.getAttribute('onclick'),
            visible,
            rect: {x: rect.x, y: rect.y, width: rect.width, height: rect.height}
          };
        }).filter(item => item.visible || item.onclick || item.href);
        """
    )


def snapshot(driver: webdriver.Chrome, output_dir: Path, name: str) -> dict[str, Any]:
    html = driver.execute_script("return document.documentElement.outerHTML") or ""
    body = driver.execute_script("return document.body ? document.body.innerText : ''") or ""
    (output_dir / f"{name}.html").write_text(html, encoding="utf-8")
    (output_dir / f"{name}.body.txt").write_text(body, encoding="utf-8")
    driver.save_screenshot(str(output_dir / f"{name}.png"))
    controls = collect_controls(driver)
    json_write(output_dir / f"{name}.controls.json", controls)
    return {
        "url": driver.current_url,
        "title": driver.title,
        "body_length": len(body),
        "html_length": len(html),
        "control_count": len(controls),
        "visible_download_controls": [
            item
            for item in controls
            if re.search(r"下载|验证软件|V1\.?1|1\.1", item.get("text") or "", re.I)
            or re.search(r"download|\.pdf|\.zip|\.rar|\.7z|\.exe|\.msi", (item.get("onclick") or "") + " " + (item.get("href") or ""), re.I)
        ],
    }


def fetch_page_scripts(driver: webdriver.Chrome, output_dir: Path) -> list[dict[str, Any]]:
    session = session_from_driver(driver)
    sources: list[str] = driver.execute_script(
        "return [...document.scripts].map(s => s.src).filter(Boolean)"
    )
    records = []
    scripts_dir = output_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for index, source in enumerate(dict.fromkeys(sources), 1):
        record: dict[str, Any] = {"url": source}
        try:
            response = session.get(source, timeout=90, allow_redirects=True)
            data = response.content
            name = Path(urllib.parse.urlparse(response.url).path).name or f"script-{index}.js"
            name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
            path = scripts_dir / f"{index:02d}-{name}"
            path.write_bytes(data)
            text = data.decode("utf-8", errors="replace")
            record.update(
                {
                    "final_url": response.url,
                    "status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "size": len(data),
                    "sha256": sha256_bytes(data),
                    "saved_as": path.relative_to(output_dir).as_posix(),
                    "contains_downloadFiles": "downloadFiles" in text,
                    "contains_downloadFile": "downloadFile" in text,
                    "download_related_excerpt": [
                        line[:1000]
                        for line in text.splitlines()
                        if re.search(r"downloadFiles|downloadFile|guideDownLoads|att/download", line, re.I)
                    ][:80],
                }
            )
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
        records.append(record)
    json_write(output_dir / "script-fetch.json", records)
    return records


def wait_for_new_download(directory: Path, before: set[Path], timeout_seconds: int = 35) -> Path | None:
    deadline = time.time() + timeout_seconds
    last_state: tuple[str, int] | None = None
    stable_ticks = 0
    while time.time() < deadline:
        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file()
            and path not in before
            and not path.name.endswith((".crdownload", ".tmp", ".part"))
        ]
        if candidates:
            newest = max(candidates, key=lambda p: p.stat().st_mtime_ns)
            state = (newest.name, newest.stat().st_size)
            if state == last_state and state[1] > 0:
                stable_ticks += 1
                if stable_ticks >= 2:
                    return newest
            else:
                last_state = state
                stable_ticks = 0
        time.sleep(1)
    return None


def candidate_nested_controls(controls: list[dict[str, Any]], role: str) -> list[dict[str, Any]]:
    selected = []
    for item in controls:
        if not item.get("visible"):
            continue
        text = item.get("text") or ""
        onclick = item.get("onclick") or ""
        href = item.get("href") or ""
        haystack = f"{text} {onclick} {href}"
        if role == "validator_software_v1_1_0":
            if "PDF文件批量电子签章" in haystack or "操作手册" in haystack:
                continue
            if re.search(r"eCTD.*验证|验证软件|V?1[._]?1(?:[._]?0)?|downloadFile|\.(?:zip|rar|7z|exe|msi)", haystack, re.I):
                selected.append(item)
        else:
            if "PDF文件批量电子签章" in haystack:
                continue
            if re.search(r"eCTD.*手册|验证软件操作手册|V?1[._]?1(?:[._]?0)?|downloadFile|\.pdf", haystack, re.I):
                selected.append(item)
    return selected


def click_control_by_index(driver: webdriver.Chrome, index: int) -> None:
    driver.execute_script(
        r"""
        const selectors = 'a,button,input,[role="button"],[onclick],.layui-layer,.layui-layer-content';
        const elements = [...document.querySelectorAll(selectors)];
        const element = elements[arguments[0]];
        if (!element) throw new Error(`control index not found: ${arguments[0]}`);
        element.scrollIntoView({block:'center'});
        element.click();
        """,
        index,
    )


def main() -> int:
    output_dir = Path(os.environ.get("EZCTD_PROBE_OUTPUT", "build/validator-portal-probe"))
    output_dir.mkdir(parents=True, exist_ok=True)
    download_dir = output_dir / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "schema_version": "0.1.0",
        "portal": PORTAL,
        "status": "STARTED",
        "software_executed": False,
        "official_black_box_observations": 0,
        "targets": [],
        "errors": [],
    }

    driver = webdriver.Chrome(options=chrome_options(download_dir))
    try:
        driver.set_page_load_timeout(90)
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd(
            "Browser.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": str(download_dir.resolve()),
                "eventsEnabled": True,
            },
        )
        driver.get(PORTAL)
        WebDriverWait(driver, 60).until(
            lambda d: d.execute_script("return document.readyState") in {"interactive", "complete"}
        )
        time.sleep(10)
        install_hooks(driver)

        report["initial_snapshot"] = snapshot(driver, output_dir, "00-initial")
        report["function_sources"] = driver.execute_script(
            r"""
            const names = Object.getOwnPropertyNames(window).filter(name => /download/i.test(name)).sort();
            const values = {};
            for (const name of names) {
              try {
                const value = window[name];
                values[name] = typeof value === 'function' ? value.toString() : String(value);
              } catch (error) {
                values[name] = `ERROR: ${error}`;
              }
            }
            return values;
            """
        )
        json_write(output_dir / "function-sources.json", report["function_sources"])
        report["script_fetch"] = fetch_page_scripts(driver, output_dir)
        report["initial_logs"] = drain_logs(driver)

        for target_index, target in enumerate(TARGETS, 1):
            target_report: dict[str, Any] = {
                "role": target["role"],
                "label": target["label"],
                "onclick": target["onclick"],
                "status": "NOT_STARTED",
                "nested_candidates": [],
            }
            report["targets"].append(target_report)
            try:
                selector = f'[onclick="{target["onclick"]}"]'
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if not elements:
                    raise RuntimeError(f"top-level portal control not found: {selector}")

                drain_logs(driver)
                before_files = set(download_dir.iterdir())
                element = elements[0]
                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
                driver.execute_script("arguments[0].click();", element)
                time.sleep(4)

                target_report["after_top_level_snapshot"] = snapshot(
                    driver, output_dir, f"{target_index:02d}-{target['role']}-after-top"
                )
                target_report["after_top_level_hooks"] = driver.execute_script(
                    "return window.__ezctdProbe"
                )
                target_report["after_top_level_logs"] = drain_logs(driver)

                downloaded = wait_for_new_download(download_dir, before_files, timeout_seconds=8)
                if downloaded is None:
                    controls = collect_controls(driver)
                    nested = candidate_nested_controls(controls, target["role"])
                    target_report["nested_candidates"] = nested
                    json_write(
                        output_dir / f"{target_index:02d}-{target['role']}-nested-candidates.json",
                        nested,
                    )
                    # Prefer a newly rendered, concrete download control. Avoid re-clicking the original top-level control.
                    concrete = [
                        item
                        for item in nested
                        if item.get("onclick") != target["onclick"]
                        and (
                            re.search(r"downloadFile|\.pdf|\.zip|\.rar|\.7z|\.exe|\.msi", (item.get("onclick") or "") + " " + (item.get("href") or ""), re.I)
                            or re.search(r"V?1[._]?1(?:[._]?0)?", item.get("text") or "", re.I)
                        )
                    ]
                    if concrete:
                        chosen = concrete[0]
                        target_report["chosen_nested_control"] = chosen
                        before_files = set(download_dir.iterdir())
                        click_control_by_index(driver, int(chosen["index"]))
                        time.sleep(3)
                        target_report["after_nested_snapshot"] = snapshot(
                            driver, output_dir, f"{target_index:02d}-{target['role']}-after-nested"
                        )
                        target_report["after_nested_hooks"] = driver.execute_script(
                            "return window.__ezctdProbe"
                        )
                        target_report["after_nested_logs"] = drain_logs(driver)
                        downloaded = wait_for_new_download(download_dir, before_files, timeout_seconds=35)

                if downloaded is None:
                    target_report["status"] = "NO_FILE_DOWNLOADED_DIAGNOSTICS_CAPTURED"
                    continue

                detected = detect_kind(downloaded)
                target_report.update(
                    {
                        "status": "DOWNLOADED",
                        "file_name": downloaded.name,
                        "size": downloaded.stat().st_size,
                        "kind": detected,
                        "sha256": sha256_file(downloaded),
                        "expected_kind_match": detected in target["expected_kinds"],
                    }
                )
            except Exception as exc:
                target_report["status"] = "ERROR"
                target_report["error"] = f"{type(exc).__name__}: {exc}"
                report["errors"].append(
                    {"role": target["role"], "error": target_report["error"]}
                )
            finally:
                # Close modal layers between probes so controls do not contaminate the next target.
                try:
                    driver.execute_script(
                        "if (window.layer && layer.closeAll) { layer.closeAll(); }"
                    )
                    time.sleep(1)
                except Exception:
                    pass

        report["final_hooks"] = driver.execute_script("return window.__ezctdProbe")
        report["final_logs"] = drain_logs(driver)
        report["final_snapshot"] = snapshot(driver, output_dir, "99-final")
    except Exception as exc:
        report["errors"].append({"stage": "top_level", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        try:
            report["browser_current_url"] = driver.current_url
        except Exception:
            pass
        driver.quit()

    downloaded_targets = [item for item in report["targets"] if item.get("status") == "DOWNLOADED"]
    report["status"] = (
        "COMPLETE_DOWNLOAD_DISCOVERY"
        if len(downloaded_targets) == len(TARGETS)
        else "DIAGNOSTIC_CAPTURE_COMPLETE"
    )
    report["downloaded_target_count"] = len(downloaded_targets)
    json_write(output_dir / "probe-report.json", report)

    summary_lines = [
        "# CDE validator portal diagnostic probe",
        "",
        f"- Status: **{report['status']}**",
        f"- Downloaded targets: {report['downloaded_target_count']}/{len(TARGETS)}",
        "- Official validator executed: no",
        "- Official black-box observations: 0",
        "",
        "| Role | Result | File | Kind | SHA-256 |",
        "|---|---|---|---|---|",
    ]
    for item in report["targets"]:
        summary_lines.append(
            f"| `{item['role']}` | {item.get('status')} | {item.get('file_name', '')} | "
            f"{item.get('kind', '')} | `{item.get('sha256', '')}` |"
        )
    summary_lines += [
        "",
        "This probe records function sources, loaded JavaScript, DOM controls, modal mutations, browser/network logs, screenshots and downloaded bytes. It does not run any downloaded executable.",
        "",
    ]
    (output_dir / "README.md").write_text("\n".join(summary_lines), encoding="utf-8")
    print(json.dumps({"status": report["status"], "downloaded": len(downloaded_targets)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
