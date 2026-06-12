from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .enrich import normalize_domain, normalize_url
from .query_catalog import QUERY_EXCLUSIONS, build_query_specs

SERPER_URL = "https://google.serper.dev/search"

EXCLUDED_DISCOVERY_DOMAINS = {
    "zauba.com",
    "thomasnet.com",
    "exporthub.com",
    "seair.co.in",
    "volza.com",
    "tradeindia.com",
    "alibaba.com",
    "made-in-china.com",
    "globalsources.com",
    "facebook.com",
    "linkedin.com",
    "instagram.com",
    "pinterest.com",
    "youtube.com",
    "openpr.com",
    "prnewswire.com",
    "globenewswire.com",
    "einnews.com",
    "marketsandmarkets.com",
    "indexbox.io",
    "justdial.com",
    "jec-world.events",
    "researchandmarkets.com",
    "tradekey.com",
    "kenresearch.com",
    "marketreportanalytics.com",
    "marketresearchfuture.com",
    "marketresearch.com",
    "datainsightsreports.com",
    "compositesworld.com",
    "scribd.com",
    "marketresearch.biz",
    "nasa.gov",
    "okorder.com",
}

EXCLUDED_DISCOVERY_EXTENSIONS = {".pdf", ".doc", ".docx", ".ppt", ".pptx"}



def build_queries(country: str, product: str = "all", hs_code: str = "7019") -> list[str]:
    product_key = str(product or "all").strip().lower().replace("-", "_")
    selected_product = product
    if hs_code == "7019" and product_key == "yarn":
        selected_product = "roving"
    return [spec["query"] for spec in build_query_specs(country, hs_code, selected_product)]


def is_excluded_discovery_domain(domain: str) -> bool:
    cleaned = domain.lower().removeprefix("www.")
    return any(cleaned == excluded or cleaned.endswith(f".{excluded}") for excluded in EXCLUDED_DISCOVERY_DOMAINS)


def is_excluded_discovery_url(url: str) -> bool:
    path = urllib.parse.urlparse(normalize_url(url)).path.lower()
    return any(path.endswith(extension) for extension in EXCLUDED_DISCOVERY_EXTENSIONS)


class SerperClient:
    def __init__(self, api_key: str, endpoint: str = SERPER_URL, timeout: float = 12.0):
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = timeout

    def search(self, query: str, num: int = 10) -> dict:
        if not self.api_key:
            raise RuntimeError("SERPER_API_KEY is required for live discovery.")
        payload = json.dumps({"q": query, "num": max(1, min(int(num), 100))}).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json",
                "User-Agent": "LeadFinder/0.1",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def results_to_leads(payload: dict, country: str, query: str) -> list[dict]:
    leads = []
    for result in payload.get("organic", []) or []:
        link = result.get("link") or result.get("url") or ""
        if not link:
            continue
        domain = normalize_domain(link)
        if is_excluded_discovery_domain(domain) or is_excluded_discovery_url(link):
            continue
        title = result.get("title") or ""
        snippet = result.get("snippet") or ""
        leads.append(
            {
                "source_type": "Website",
                "source_name": f"Serper: {query}",
                "company_name": title[:160],
                "country_region": country,
                "market_region": country,
                "website": normalize_url(link),
                "source_url": normalize_url(link),
                "contact_name": "",
                "email": "",
                "industry": "",
                "product_fit": "Both",
                "fit_reason": "",
                "match_score": 0,
                "status": "Discovered",
                "notes": snippet,
                "raw_text": f"{title} {snippet}".strip(),
            }
        )
    return leads
