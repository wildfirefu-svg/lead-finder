from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import urllib.error

from .stability import call_with_limited_retry

FALLBACK_MARKETS = [
    ("USA", 0),
    ("Germany", 0),
    ("Japan", 0),
    ("India", 0),
    ("Brazil", 0),
]


def fetch_comtrade_markets(hs_code: str, year: int, timeout: float = 12.0) -> list[dict]:
    params = {
        "period": str(year),
        "partnerCode": "0",
        "partner2Code": "0",
        "cmdCode": hs_code,
        "flowCode": "M",
        "motCode": "0",
        "customsCode": "C00",
        "includeDesc": "true",
        "maxrecords": "500",
    }
    url = "https://comtradeapi.un.org/data/v1/get/C/A/HS?" + urllib.parse.urlencode(params)
    payload = _fetch_comtrade_payload(url, timeout)

    rows = payload.get("data") or payload.get("dataset") or []
    markets = []
    for row in rows:
        country = row.get("reporterDesc") or row.get("reporter") or row.get("reporterISO") or ""
        value = row.get("primaryValue") or row.get("TradeValue") or row.get("tradeValue") or 0
        if country:
            markets.append(
                {
                    "hs_code": hs_code,
                    "year": year,
                    "country_region": str(country),
                    "import_value_usd": float(value or 0),
                    "source_name": "UN Comtrade",
                }
            )
    return sorted(markets, key=lambda item: item["import_value_usd"], reverse=True)


def _fetch_comtrade_payload(url: str, timeout: float) -> dict:
    keys = _comtrade_subscription_keys()
    last_error: Exception | None = None
    for key in keys or [""]:
        headers = {"User-Agent": "LeadFinder/0.1"}
        if key:
            headers["Ocp-Apim-Subscription-Key"] = key
        request = urllib.request.Request(url, headers=headers)
        try:
            return call_with_limited_retry(
                lambda: _read_json_response(request, timeout),
                retries=1,
            )
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code in {401, 403} and key and key != keys[-1]:
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError("UN Comtrade returned no response")


def _comtrade_subscription_keys() -> list[str]:
    keys = [
        os.getenv("COMTRADE_API_KEY", "").strip(),
        os.getenv("COMTRADE_API_KEY_SECONDARY", "").strip(),
    ]
    return list(dict.fromkeys(key for key in keys if key))


def _read_json_response(request, timeout: float) -> dict:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fallback_markets(hs_code: str, year: int) -> list[dict]:
    return [
        {
            "hs_code": hs_code,
            "year": year,
            "country_region": country,
            "import_value_usd": value,
            "source_name": "Manual fallback",
        }
        for country, value in FALLBACK_MARKETS
    ]
