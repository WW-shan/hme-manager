"""Keep an iCloud Web session imported through a visible remote browser.

The browser is deliberately user-assisted: the account owner completes Apple
login and any 2FA/CAPTCHA in the noVNC window.  This process only captures the
resulting HME network request and sends a short-lived import payload to the
local HME Manager API; it never receives an Apple password or automates a
security challenge.

The module uses only the standard library at import time.  Selenium is loaded
inside ``create_driver`` so the API image and the unit-test suite remain
dependency-free; the browser image installs it separately.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping


HME_REQUEST_MARKER = "/v2/hme/list"
REQUIRED_COOKIE_NAMES = {
    "X-APPLE-DS-WEB-SESSION-TOKEN",
    "X-APPLE-WEBAUTH-USER",
    "X-APPLE-WEBAUTH-TOKEN",
}
DEFAULT_ICLOUD_URL = "https://www.icloud.com/icloudplus/"


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default)) or str(default)))
    except (TypeError, ValueError):
        return default


MANAGER_URL = str(os.getenv("HME_MANAGER_URL", "http://hme-api:8000") or "").strip().rstrip("/")
MANAGER_KEY = str(os.getenv("HME_MANAGER_API_KEY", "") or "").strip()
SELENIUM_URL = str(os.getenv("SELENIUM_URL", "http://hme-browser:4444") or "").strip().rstrip("/")
ICLOUD_URL = str(os.getenv("ICLOUD_WEB_URL", DEFAULT_ICLOUD_URL) or DEFAULT_ICLOUD_URL).strip()
CHECK_INTERVAL = _env_int("HME_BROWSER_CHECK_INTERVAL", 60, 30)
CAPTURE_TIMEOUT = _env_int("HME_BROWSER_CAPTURE_TIMEOUT", 600, 60)
PROFILE_DIR = str(os.getenv("HME_BROWSER_PROFILE_DIR", "/home/seluser/chrome-profile") or "").strip()
STATUS_FILE = Path(
    os.getenv("HME_BROWSER_STATUS_FILE", "/data/state/browser-agent.json")
)


def _safe_message(value: Any, fallback: str = "request failed") -> str:
    """Return a short diagnostic without ever echoing credential material."""
    text = str(value or fallback)
    sensitive_markers = (
        MANAGER_KEY,
        "X-APPLE-DS-WEB-SESSION-TOKEN",
        "X-APPLE-WEBAUTH-USER",
        "X-APPLE-WEBAUTH-TOKEN",
        "Cookie",
        "Authorization",
    )
    for marker in sensitive_markers:
        if marker:
            text = text.replace(marker, "[redacted]")
    return " ".join(text.split())[:300]


def _safe_optional_message(value: Any) -> str | None:
    return None if value is None else _safe_message(value)


def _manager_headers(content_type: bool = False) -> dict[str, str]:
    headers = {"Accept": "application/json", "X-API-Key": MANAGER_KEY}
    if content_type:
        headers["Content-Type"] = "application/json"
    return headers


def _http_json(
    method: str,
    url: str,
    payload: Mapping[str, Any] | None = None,
    timeout: float = 30,
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        headers=_manager_headers(payload is not None),
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            parsed = json.loads(raw) if raw else {}
            return int(response.status), parsed if isinstance(parsed, dict) else {}
    except urllib.error.HTTPError as exc:
        # Do not include the response body in an exception.  It can contain
        # provider diagnostics and is not needed by the retry loop.
        try:
            raw = exc.read(4096).decode("utf-8", "replace")
            parsed = json.loads(raw) if raw else {}
        except (OSError, ValueError):
            parsed = {}
        return int(exc.code), parsed if isinstance(parsed, dict) else {}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(_safe_message(exc, "HME Manager connection failed")) from exc
    except ValueError as exc:
        raise RuntimeError("HME Manager returned invalid JSON") from exc


def _active_selenium_session_ids() -> list[str]:
    """Find sessions left behind if the agent container was restarted."""
    request = urllib.request.Request(f"{SELENIUM_URL}/status", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except (OSError, ValueError, urllib.error.URLError):
        return []
    ids: list[str] = []
    value = payload.get("value") if isinstance(payload, Mapping) else None
    nodes = value.get("nodes") if isinstance(value, Mapping) else None
    if not isinstance(nodes, list):
        return ids
    for node in nodes:
        slots = node.get("slots") if isinstance(node, Mapping) else None
        if not isinstance(slots, list):
            continue
        for slot in slots:
            session = slot.get("session") if isinstance(slot, Mapping) else None
            session_id = session.get("sessionId") if isinstance(session, Mapping) else None
            if session_id:
                ids.append(str(session_id))
    return ids


def _close_selenium_session(session_id: str) -> None:
    request = urllib.request.Request(
        f"{SELENIUM_URL}/session/{session_id}",
        headers={"Accept": "application/json"},
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            return
    except (OSError, urllib.error.HTTPError, urllib.error.URLError):
        return


def _close_orphaned_selenium_sessions() -> None:
    # The browser service is dedicated to this agent.  Removing a stale Grid
    # session on startup prevents a crashed agent from blocking the next one
    # for the full Selenium session timeout.
    for session_id in _active_selenium_session_ids():
        _close_selenium_session(session_id)


def _api_error(status: int, payload: Mapping[str, Any] | None = None) -> str:
    if status in (401, 403):
        return "HME Manager API key rejected"
    if status == 409:
        return "HME Manager iCloud session is not ready"
    if status == 429:
        return "HME Manager is rate-limited"
    error = payload.get("error") if isinstance(payload, Mapping) else None
    if isinstance(error, Mapping):
        detail = error.get("code") or error.get("message")
        if detail:
            return _safe_message(detail)
    return f"HME Manager request failed (HTTP {status})"


def manager_status() -> dict[str, Any]:
    status, payload = _http_json("GET", f"{MANAGER_URL}/v1/session/status", timeout=20)
    if status < 200 or status >= 300 or payload.get("ok") is False:
        raise RuntimeError(_api_error(status, payload))
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def manager_refresh() -> dict[str, Any]:
    status, payload = _http_json("POST", f"{MANAGER_URL}/v1/session/refresh", payload={}, timeout=60)
    if status < 200 or status >= 300 or payload.get("ok") is False:
        raise RuntimeError(_api_error(status, payload))
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def import_har(har_text: str) -> tuple[bool, str]:
    status, payload = _http_json(
        "POST",
        f"{MANAGER_URL}/v1/session/import",
        payload={"curl_text": har_text},
        timeout=30,
    )
    if 200 <= status < 300 and payload.get("ok") is True:
        data = payload.get("data")
        region = data.get("region") if isinstance(data, Mapping) else None
        return True, str(region or "unknown")
    return False, _api_error(status, payload)


def _load_status() -> dict[str, Any]:
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_status(**updates: Any) -> None:
    """Write a non-secret status snapshot atomically for the HME UI."""
    current = _load_status()
    current.update(updates)
    current["updatedAt"] = time.time()
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="browser-agent-", suffix=".tmp", dir=STATUS_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(current, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, STATUS_FILE)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _all_cookies(driver: Any) -> list[dict[str, Any]]:
    try:
        result = driver.execute_cdp_cmd("Network.getAllCookies", {})
    except Exception:
        return []
    cookies = result.get("cookies") if isinstance(result, Mapping) else None
    return cookies if isinstance(cookies, list) else []


def build_har_request(request: Mapping[str, Any], cookies: list[Mapping[str, Any]]) -> str:
    """Convert a performance-log request plus CDP cookies into a HAR JSON."""
    headers = request.get("headers") if isinstance(request.get("headers"), Mapping) else {}
    header_items = [
        {"name": str(name), "value": str(value)}
        for name, value in headers.items()
        if str(name).lower() not in {"host", "content-length", "cookie"}
    ]
    cookie_items = [
        {"name": str(item.get("name")), "value": str(item.get("value") or "")}
        for item in cookies
        if isinstance(item, Mapping) and item.get("name")
    ]
    cookie_names = {item["name"] for item in cookie_items}
    missing = sorted(REQUIRED_COOKIE_NAMES - cookie_names)
    if missing:
        raise RuntimeError("browser session cookies unavailable")
    header_items.append({
        "name": "Cookie",
        "value": "; ".join(f"{item['name']}={item['value']}" for item in cookie_items),
    })
    har_request: dict[str, Any] = {
        "method": str(request.get("method") or "GET"),
        "url": str(request.get("url") or ""),
        "headers": header_items,
        "cookies": cookie_items,
    }
    post_data = request.get("postData")
    if post_data:
        har_request["postData"] = {"text": str(post_data)}
    return json.dumps(
        {"log": {"version": "1.2", "entries": [{"request": har_request}]}},
        ensure_ascii=False,
    )


def _performance_entries(driver: Any) -> list[Mapping[str, Any]]:
    """Read Chrome performance logs on Selenium 4.49+ and older releases.

    Selenium removed the convenience ``get_log`` method from the Python
    Remote WebDriver while the underlying WebDriver command still exists.
    Calling the command directly keeps this compatible with both versions.
    """
    command = "getLog"
    try:
        from selenium.webdriver.remote.command import Command

        command = Command.GET_LOG
    except Exception:
        pass
    try:
        result = driver.execute(command, {"type": "performance"})
        entries = result.get("value") if isinstance(result, Mapping) else None
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, Mapping)]
    except Exception:
        pass
    getter = getattr(driver, "get_log", None)
    if callable(getter):
        try:
            entries = getter("performance")
            return [entry for entry in entries if isinstance(entry, Mapping)]
        except Exception:
            return []
    return []


def find_hme_request(driver: Any, seen_request_ids: set[str] | None = None) -> dict[str, Any] | None:
    seen_request_ids = seen_request_ids if seen_request_ids is not None else set()
    for entry in _performance_entries(driver):
        try:
            outer = json.loads(str(entry.get("message") or ""))
            message = outer.get("message") if isinstance(outer, Mapping) else None
            if not isinstance(message, Mapping) or message.get("method") != "Network.requestWillBeSent":
                continue
            params = message.get("params")
            request = params.get("request") if isinstance(params, Mapping) else None
            if not isinstance(request, Mapping):
                continue
            url = str(request.get("url") or "")
            if HME_REQUEST_MARKER not in url or "maildomainws.icloud" not in url:
                continue
            request_id = str(params.get("requestId") or "") if isinstance(params, Mapping) else ""
            if request_id and request_id in seen_request_ids:
                continue
            if request_id:
                seen_request_ids.add(request_id)
            return dict(request)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return None


def create_driver() -> Any:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    _close_orphaned_selenium_sessions()
    options = Options()
    options.page_load_strategy = "eager"
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1440,1000")
    options.add_argument("--no-first-run")
    if PROFILE_DIR:
        options.add_argument(f"--user-data-dir={PROFILE_DIR}")
    driver = webdriver.Remote(command_executor=SELENIUM_URL, options=options)
    driver.set_page_load_timeout(120)
    driver.execute_cdp_cmd("Network.enable", {})
    return driver


def _heartbeat(driver: Any) -> None:
    try:
        driver.execute_script("return document.readyState")
    except Exception as exc:
        raise RuntimeError("browser session is no longer available") from exc


def capture_and_import(driver: Any, navigate: bool = True) -> tuple[bool, str]:
    if navigate:
        write_status(phase="opening_icloud", lastError=None)
        driver.get(ICLOUD_URL)
    print("[hme-browser-agent] 请在 noVNC 页面完成 iCloud 登录/2FA，并打开 Hide My Email", flush=True)
    write_status(phase="waiting_for_login_or_hme", lastError=None)
    deadline = time.time() + CAPTURE_TIMEOUT
    seen_request_ids: set[str] = set()
    while time.time() < deadline:
        request = find_hme_request(driver, seen_request_ids)
        if request:
            try:
                har_text = build_har_request(request, _all_cookies(driver))
            except RuntimeError as exc:
                write_status(phase="waiting_for_session_cookies", lastError=_safe_message(exc))
                time.sleep(2)
                continue
            ok, detail = import_har(har_text)
            if ok:
                write_status(
                    phase="imported",
                    lastImportAt=time.time(),
                    lastError=None,
                    region=detail,
                )
                print(f"[hme-browser-agent] Session 已自动导入（region={detail}）", flush=True)
                return True, detail
            write_status(phase="import_rejected", lastError=detail)
            print(f"[hme-browser-agent] Session 导入失败：{detail}", flush=True)
        time.sleep(1)
    write_status(phase="capture_timeout", lastError="等待 iCloud HME 请求超时")
    return False, "capture timeout"


def run() -> None:
    if not MANAGER_URL or not MANAGER_KEY:
        raise SystemExit("HME_MANAGER_URL and HME_MANAGER_API_KEY are required")
    driver = None
    browser_initialized = False
    last_import_at = 0.0
    last_log = ""
    try:
        while True:
            if driver is None:
                try:
                    write_status(phase="starting_browser", lastError=None)
                    driver = create_driver()
                    browser_initialized = False
                    print("[hme-browser-agent] 服务器浏览器已启动，noVNC 入口可用于登录 iCloud", flush=True)
                except Exception as exc:
                    message = _safe_message(exc, "无法连接 Selenium 浏览器")
                    if message != last_log:
                        print(f"[hme-browser-agent] 浏览器启动等待中：{message}", flush=True)
                        last_log = message
                    write_status(phase="browser_unavailable", lastError=message)
                    time.sleep(15)
                    continue

            try:
                if not browser_initialized:
                    write_status(phase="opening_icloud", lastError=None)
                    driver.get(ICLOUD_URL)
                    browser_initialized = True
                    print("[hme-browser-agent] noVNC 浏览器页面已打开，可直接登录 iCloud", flush=True)
                status = manager_status()
                valid = status.get("sessionValid") is True and status.get("needsReauth") is not True
                write_status(
                    phase="session_valid" if valid else "session_needs_login",
                    sessionValid=valid,
                    needsReauth=bool(status.get("needsReauth")),
                    lastError=_safe_optional_message(status.get("lastError")),
                )

                if not valid:
                    # Import immediately after expiry, then give the manager a
                    # short window to validate it before capturing again.
                    if last_import_at and time.time() - last_import_at < 180:
                        try:
                            refreshed = manager_refresh()
                            valid = refreshed.get("sessionValid") is True and refreshed.get("needsReauth") is not True
                            write_status(
                                phase="session_valid" if valid else "session_needs_login",
                                sessionValid=valid,
                                needsReauth=bool(refreshed.get("needsReauth")),
                                lastError=_safe_optional_message(refreshed.get("lastError")),
                            )
                        except Exception as exc:
                            write_status(phase="validating_import", lastError=_safe_message(exc))
                    if not valid and (not last_import_at or time.time() - last_import_at >= 180):
                        imported, _detail = capture_and_import(driver, navigate=True)
                        if imported:
                            last_import_at = time.time()
                            try:
                                manager_refresh()
                            except Exception as exc:
                                write_status(phase="imported_validating", lastError=_safe_message(exc))

                _heartbeat(driver)
                time.sleep(CHECK_INTERVAL)
            except Exception as exc:
                message = _safe_message(exc, "browser agent loop failed")
                write_status(phase="retrying", lastError=message)
                if message != last_log:
                    print(f"[hme-browser-agent] 等待恢复：{message}", flush=True)
                    last_log = message
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = None
                browser_initialized = False
                time.sleep(10)
    finally:
        if driver is not None:
            driver.quit()


if __name__ == "__main__":
    run()
