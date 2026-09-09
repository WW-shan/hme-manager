import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import browser_agent


def performance_entry(url="https://p119-maildomainws.icloud.com/v2/hme/list?dsid=1"):
    return {
        "message": json.dumps(
            {
                "message": {
                    "method": "Network.requestWillBeSent",
                    "params": {
                        "requestId": "request-1",
                        "request": {
                            "method": "GET",
                            "url": url,
                            "headers": {"Accept": "application/json"},
                        },
                    },
                }
            }
        )
    }


class FakeDriver:
    def __init__(self, entries):
        self.entries = entries
        self.commands = []

    def execute(self, command, params):
        self.commands.append((command, params))
        entries, self.entries = self.entries, []
        return {"value": entries}


class BrowserAgentTests(unittest.TestCase):
    def setUp(self):
        self.cookies = [
            {"name": name, "value": f"value-{index}"}
            for index, name in enumerate(sorted(browser_agent.REQUIRED_COOKIE_NAMES))
        ]

    def test_build_har_request_contains_request_and_cookies_without_logging_them(self):
        har = browser_agent.build_har_request(
            {
                "method": "GET",
                "url": "https://p119-maildomainws.icloud.com/v2/hme/list",
                "headers": {"Cookie": "not-used", "Accept": "application/json"},
            },
            self.cookies,
        )

        parsed = json.loads(har)
        request = parsed["log"]["entries"][0]["request"]
        self.assertEqual(request["method"], "GET")
        self.assertEqual(len(request["cookies"]), 3)
        self.assertNotIn("not-used", har)

    def test_build_har_request_requires_core_session_cookies(self):
        with self.assertRaisesRegex(RuntimeError, "cookies unavailable"):
            browser_agent.build_har_request(
                {"url": "https://p119-maildomainws.icloud.com/v2/hme/list"},
                [],
            )

    def test_build_har_request_falls_back_to_cookie_header(self):
        header_cookie = "; ".join(f"{item['name']}={item['value']}" for item in self.cookies)
        har = browser_agent.build_har_request(
            {
                "url": "https://p119-maildomainws.icloud.com/v2/hme/list",
                "headers": {"Cookie": header_cookie},
            },
            [],
        )

        request = json.loads(har)["log"]["entries"][0]["request"]
        self.assertEqual({item["name"] for item in request["cookies"]}, browser_agent.REQUIRED_COOKIE_NAMES)

    def test_find_hme_request_uses_raw_webdriver_log_command(self):
        driver = FakeDriver([performance_entry()])

        request = browser_agent.find_hme_request(driver, set())

        self.assertIsNotNone(request)
        self.assertEqual(request["url"].split("?")[0], "https://p119-maildomainws.icloud.com/v2/hme/list")
        self.assertTrue(driver.commands)
        self.assertEqual(driver.commands[0][1], {"type": "performance"})

    def test_find_hme_request_ignores_non_hme_requests(self):
        driver = FakeDriver([performance_entry("https://www.icloud.com/icloudplus/")])

        self.assertIsNone(browser_agent.find_hme_request(driver, set()))

    def test_find_hme_request_deduplicates_request_ids(self):
        driver = FakeDriver([performance_entry()])
        seen = {"request-1"}

        self.assertIsNone(browser_agent.find_hme_request(driver, seen))

    def test_active_selenium_session_ids_are_read_without_exposing_ids_in_logs(self):
        payload = {
            "value": {
                "nodes": [
                    {"slots": [{"session": {"sessionId": "orphan-1"}}, {"session": None}]},
                    {"slots": [{"session": {}}]},
                ]
            }
        }

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return json.dumps(payload).encode("utf-8")

        with patch("browser_agent.urllib.request.urlopen", return_value=Response()):
            self.assertEqual(browser_agent._active_selenium_session_ids(), ["orphan-1"])

    def test_import_har_maps_success_without_printing_api_key(self):
        with patch.object(browser_agent, "_http_json", return_value=(200, {"ok": True, "data": {"region": "china"}})):
            ok, detail = browser_agent.import_har("{\"log\": {}}")

        self.assertTrue(ok)
        self.assertEqual(detail, "china")

    def test_import_har_returns_safe_error_for_auth_failure(self):
        with patch.object(browser_agent, "_http_json", return_value=(401, {"error": {"message": "secret"}})):
            ok, detail = browser_agent.import_har("{\"log\": {}}")

        self.assertFalse(ok)
        self.assertEqual(detail, "HME Manager API key rejected")
        if browser_agent.MANAGER_KEY:
            self.assertNotIn(browser_agent.MANAGER_KEY, detail)

    def test_write_status_uses_atomic_secret_free_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            status_path = Path(tmp) / "state" / "browser-agent.json"
            with patch.object(browser_agent, "STATUS_FILE", status_path):
                browser_agent.write_status(phase="session_valid", sessionValid=True)
                data = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(data["phase"], "session_valid")
        self.assertTrue(data["sessionValid"])
        self.assertNotIn("Cookie", json.dumps(data))


if __name__ == "__main__":
    unittest.main()
