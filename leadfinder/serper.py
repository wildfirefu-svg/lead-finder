from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .enrich import normalize_domain, normalize_url

SERPER_URL = "https://google.serper.dev/search"

QUERY_EXCLUSIONS = (
    "-site:zauba.com -site:thomasnet.com -site:exporthub.com "
    "-site:seair.co.in -site:volza.com -site:tradeindia.com "
    "-site:alibaba.com -site:made-in-china.com -site:globalsources.com "
    "-site:facebook.com -site:linkedin.com -site:openpr.com "
    "-site:instagram.com -site:pinterest.com -site:youtube.com "
    "-site:prnewswire.com -site:globenewswire.com -site:indexbox.io "
    "-site:justdial.com -site:jec-world.events -site:researchandmarkets.com "
    "-site:tradekey.com -site:kenresearch.com -site:marketreportanalytics.com "
    "-site:marketresearchfuture.com -site:marketresearch.com -site:datainsightsreports.com -filetype:pdf"
    " -site:compositesworld.com -site:scribd.com -site:marketresearch.biz -site:nasa.gov -site:okorder.com"
)

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

YARN_QUERIES = [
    '"fiberglass roving" "pultrusion" "capabilities" {country}',
    '"fiberglass roving" "filament winding" "capabilities" {country}',
    '"fiberglass roving" "FRP" "contact us" {country}',
    '"fiberglass roving" "custom pultrusions" {country}',
]

FABRIC_QUERIES = [
    '"fiberglass fabric" importer {country}',
    '"woven roving" buyer {country}',
    '"fiberglass cloth" distributor {country}',
    '"insulation" manufacturer {country} fiberglass fabric',
]

LOCAL_YARN_QUERIES = {
    "canada": [
        'site:.ca "FRP grating" "contact"',
        'site:.ca "fiberglass rebar"',
        'site:.ca "pultrusion" "FRP"',
        '"fiberglass reinforced plastic" Canada "contact us"',
        '"fiberglass rebar" Canada "contact us"',
        '"fiberglass roving" "Ontario" "composites"',
    ],
    "usa": [
        '"fiberglass roving" "United States" "pultrusion"',
        '"fiberglass roving" "FRP" "Wisconsin"',
        '"fiberglass roving" "FRP" "Texas"',
    ],
    "united states": [
        '"fiberglass roving" "United States" "pultrusion"',
        '"fiberglass roving" "FRP" "Wisconsin"',
        '"fiberglass roving" "FRP" "Texas"',
    ],
    "mexico": [
        'site:.mx "fibra de vidrio" "pultrusion"',
        '"fibra de vidrio" "FRP" Mexico',
        '"fiberglass roving" Mexico composites',
    ],
    "germany": [
        'site:.de "glasfaser roving" "pultrusion"',
        'site:.de "GFK" "profile"',
        '"GFK" "Roving" Deutschland',
        '"glasfaser" "FRP" Germany',
    ],
    "france": [
        'site:.fr "fibre de verre" "pultrusion"',
        'site:.fr "composite" "profilé"',
        '"fibre de verre" "composites" France',
        '"roving fibre de verre" France',
    ],
    "united kingdom": [
        'site:.uk "fibreglass roving" "pultrusion"',
        '"fibreglass" "FRP" UK',
        '"fiberglass roving" "United Kingdom" composites',
    ],
    "italy": [
        'site:.it "fibra di vetro" "pultrusione"',
        '"fibra di vetro" "compositi" Italy',
        '"fiberglass roving" Italy composites',
    ],
    "spain": [
        'site:.es "fibra de vidrio" "pultrusion"',
        '"fibra de vidrio" "composites" Spain',
        '"fiberglass roving" Spain composites',
    ],
    "netherlands": [
        'site:.nl "glasvezel" "pultrusie"',
        '"fiberglass roving" Netherlands composites',
    ],
    "poland": [
        'site:.pl "włókno szklane" "kompozyty"',
        '"fiberglass roving" Poland composites',
    ],
    "vietnam": [
        '"fiberglass roving" Vietnam "FRP"',
        '"composite" "fiberglass" Vietnam manufacturer',
    ],
    "thailand": [
        '"fiberglass roving" Thailand "FRP"',
        '"composite" "fiberglass" Thailand manufacturer',
    ],
    "indonesia": [
        '"fiberglass roving" Indonesia "FRP"',
        '"composite" "fiberglass" Indonesia manufacturer',
    ],
    "malaysia": [
        '"fiberglass roving" Malaysia "FRP"',
        '"composite" "fiberglass" Malaysia manufacturer',
    ],
    "philippines": [
        '"fiberglass roving" Philippines "FRP"',
        '"composite" "fiberglass" Philippines manufacturer',
    ],
    "singapore": [
        '"fiberglass roving" Singapore "FRP"',
        '"composite" "fiberglass" Singapore distributor',
    ],
    "india": [
        'site:.in "fiberglass roving" "pultrusion"',
        'site:.in "FRP grating" "contact"',
        '"fiberglass rebar" India',
        '"fiberglass roving" India "FRP"',
        '"composite" "fiberglass" India manufacturer',
    ],
    "united arab emirates": [
        '"fiberglass roving" UAE "FRP"',
        '"composite" "fiberglass" Dubai',
    ],
    "saudi arabia": [
        '"fiberglass roving" Saudi Arabia "FRP"',
        '"composite" "fiberglass" Saudi',
    ],
    "turkey": [
        'site:.tr "cam elyaf" "kompozit"',
        '"fiberglass roving" Turkey "FRP"',
    ],
    "japan": [
        'site:.jp "ガラス繊維" "FRP"',
        '"fiberglass roving" Japan composites',
    ],
    "south korea": [
        'site:.kr "glass fiber" "FRP"',
        '"fiberglass roving" Korea composites',
    ],
    "brazil": [
        'site:.br "fibra de vidro" "pultrusão"',
        '"fiberglass roving" Brazil "FRP"',
    ],
    "morocco": [
        'site:.ma "fibre de verre" "composite"',
        'site:.ma "PRV" "fibre de verre"',
        '"fibre de verre" "Maroc" "composite"',
        '"polyester" "fibre de verre" Maroc',
    ],
    "south africa": [
        '"fiberglass roving" "South Africa" "FRP"',
        '"composite" "fiberglass" "South Africa"',
    ],
}

LOCAL_FABRIC_QUERIES = {
    "canada": [
        'site:.ca "fiberglass fabric" composites',
        '"fiberglass cloth" Canada distributor',
    ],
    "germany": [
        'site:.de "glasfasergewebe" "GFK"',
        '"fiberglass fabric" Germany composites',
    ],
    "france": [
        'site:.fr "tissu fibre de verre"',
        '"fiberglass fabric" France composites',
    ],
    "india": [
        'site:.in "fiberglass fabric" composites',
        '"woven roving" India buyer',
    ],
}


def build_queries(country: str, product: str = "both") -> list[str]:
    product_key = product.lower().replace("_", "-")
    country_key = country.lower().strip()
    templates: list[str] = []
    if product_key in {"yarn", "fiberglass-yarn", "both"}:
        templates.extend(LOCAL_YARN_QUERIES.get(country_key, []))
        templates.extend(YARN_QUERIES)
    if product_key in {"fabric", "fiberglass-fabric", "both"}:
        templates.extend(LOCAL_FABRIC_QUERIES.get(country_key, []))
        templates.extend(FABRIC_QUERIES)
    queries = [f"{template.format(country=country)} {QUERY_EXCLUSIONS}" for template in templates]
    return list(dict.fromkeys(queries))


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
