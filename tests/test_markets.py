from __future__ import annotations

import json
import os
import socket
import unittest
import urllib.error
from unittest.mock import patch

from leadfinder.markets import fetch_comtrade_markets


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class MarketsTests(unittest.TestCase):
    def test_fetch_comtrade_markets_uses_current_api_and_sorts_imports(self) -> None:
        payload = {
            "data": [
                {"reporterDesc": "Germany", "primaryValue": 20},
                {"reporterDesc": "USA", "primaryValue": 50},
            ]
        }
        captured_urls: list[str] = []

        def fake_urlopen(request, timeout=12.0):
            captured_urls.append(request.full_url)
            return FakeResponse(payload)

        with patch("urllib.request.urlopen", fake_urlopen):
            markets = fetch_comtrade_markets("701919", 2024)

        self.assertEqual([market["country_region"] for market in markets], ["USA", "Germany"])
        self.assertIn("/data/v1/get/C/A/HS?", captured_urls[0])
        self.assertIn("cmdCode=701919", captured_urls[0])
        self.assertIn("flowCode=M", captured_urls[0])
        self.assertNotIn("reporterCode=", captured_urls[0])

    def test_fetch_comtrade_markets_retries_secondary_key_on_401(self) -> None:
        payload = {"data": [{"reporterDesc": "USA", "primaryValue": 50}]}
        seen_keys: list[str] = []

        def fake_urlopen(request, timeout=12.0):
            key = request.get_header("Ocp-apim-subscription-key")
            seen_keys.append(key or "")
            if key == "primary-key":
                raise urllib.error.HTTPError(request.full_url, 401, "Access Denied", {}, None)
            return FakeResponse(payload)

        original_primary = os.environ.get("COMTRADE_API_KEY")
        original_secondary = os.environ.get("COMTRADE_API_KEY_SECONDARY")
        os.environ["COMTRADE_API_KEY"] = "primary-key"
        os.environ["COMTRADE_API_KEY_SECONDARY"] = "secondary-key"
        try:
            with patch("urllib.request.urlopen", fake_urlopen):
                markets = fetch_comtrade_markets("701919", 2024)
        finally:
            if original_primary is None:
                os.environ.pop("COMTRADE_API_KEY", None)
            else:
                os.environ["COMTRADE_API_KEY"] = original_primary
            if original_secondary is None:
                os.environ.pop("COMTRADE_API_KEY_SECONDARY", None)
            else:
                os.environ["COMTRADE_API_KEY_SECONDARY"] = original_secondary

        self.assertEqual(seen_keys, ["primary-key", "secondary-key"])
        self.assertEqual(markets[0]["country_region"], "USA")

    def test_fetch_comtrade_markets_retries_transient_urlerror_once(self) -> None:
        payload = {"data": [{"reporterDesc": "USA", "primaryValue": 50}]}
        calls = {"count": 0}

        def fake_urlopen(request, timeout=12.0):
            calls["count"] += 1
            if calls["count"] == 1:
                raise urllib.error.URLError(socket.gaierror("temporary failure"))
            return FakeResponse(payload)

        with patch("urllib.request.urlopen", fake_urlopen):
            markets = fetch_comtrade_markets("701919", 2024)

        self.assertEqual(calls["count"], 2)
        self.assertEqual(markets[0]["country_region"], "USA")


if __name__ == "__main__":
    unittest.main()
