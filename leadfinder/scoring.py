from __future__ import annotations

YARN_TERMS = [
    "fiberglass yarn",
    "glass fiber yarn",
    "glass fibre yarn",
    "e-glass yarn",
    "fiberglass roving",
    "glass fiber roving",
    "direct roving",
    "assembled roving",
    "pultrusion",
    "custom pultrusions",
    "pultruded profiles",
    "filament winding",
    "frp pipe",
    "frp rebar",
    "fiberglass rebar",
    "frp grating",
    "fiberglass reinforced plastic",
]

FABRIC_TERMS = [
    "fiberglass fabric",
    "glass fiber fabric",
    "glass fibre fabric",
    "fiberglass cloth",
    "woven roving",
    "mesh fabric",
    "composite fabric",
    "fireproof fabric",
    "insulation fabric",
    "boat building",
    "wind blade",
]

GENERAL_TERMS = [
    "fiberglass",
    "fibreglass",
    "glass fiber",
    "glass fibre",
    "e-glass",
    "composite",
    "frp",
    "insulation",
]

NEGATIVE_TERMS = [
    "news",
    "wikipedia",
    "research paper",
    "job opening",
    "stock photo",
    "dictionary",
    "directory",
    "marketplace",
    "yellow pages",
    "import data",
    "export data",
    "trade data",
    "press release",
    "market report",
    "market research",
    "pdf",
    "lecture notes",
    "school of",
    "university",
    "technical document",
    "research center",
    "government",
    "nasa",
    "ntrs",
    "facebook",
    "linkedin",
    "instagram",
    "pinterest",
    "youtube",
    "market overview",
    "market size",
    "top 10",
    "top ten",
    "carbon fiber suppliers",
    "exhibitor list",
    "interactive map",
    "china wholesale",
    "from china",
    "factories",
    "factory direct",
    "made in china",
]

BUYER_TERMS = [
    "importer",
    "buyer",
    "consignee",
    "distributor",
    "manufacturer",
    "pultrusion",
    "frp pipe",
    "shipment",
    "imported",
    "hs 7019",
]

DOWNSTREAM_TERMS = [
    "composites manufacturer",
    "composite manufacturer",
    "frp manufacturer",
    "pultrusion manufacturer",
    "fiberglass reinforced plastic",
    "filament winding",
    "molded fiberglass",
    "boat manufacturer",
    "marine composites",
    "automotive composites",
]

COMPANY_EVIDENCE_TERMS = [
    "about us",
    "our products",
    "contact us",
    "request a quote",
    "capabilities",
]

DIRECTORY_DOMAINS = [
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
]

COUNTRY_MISMATCH_TERMS = {
    "usa": ["china", "pune", "india", "pvt ltd", "guinea bissau"],
    "united states": ["china", "pune", "india", "pvt ltd", "guinea bissau"],
}


def _hits(text: str, terms: list[str]) -> list[str]:
    lowered = text.lower()
    return [term for term in terms if term in lowered]


def _has_domain(text: str, domains: list[str]) -> bool:
    lowered = text.lower()
    return any(domain in lowered for domain in domains)


def score_lead(lead: dict) -> dict:
    text = " ".join(
        str(lead.get(field, "") or "")
        for field in (
            "company_name",
            "industry",
            "product_fit",
            "fit_reason",
            "notes",
            "raw_text",
            "source_url",
            "website",
        )
    ).lower()

    yarn_hits = _hits(text, YARN_TERMS)
    fabric_hits = _hits(text, FABRIC_TERMS)
    general_hits = _hits(text, GENERAL_TERMS)
    negative_hits = _hits(text, NEGATIVE_TERMS)
    buyer_hits = _hits(text, BUYER_TERMS)
    downstream_hits = _hits(text, DOWNSTREAM_TERMS)
    company_evidence_hits = _hits(text, COMPANY_EVIDENCE_TERMS)
    source_type = str(lead.get("source_type", "") or "").lower()
    source_location = " ".join(str(lead.get(field, "") or "") for field in ("source_url", "website"))
    is_directory_source = source_type == "website" and _has_domain(source_location, DIRECTORY_DOMAINS)
    country = str(lead.get("country_region", "") or "").lower()
    mismatch_hits = _hits(text, COUNTRY_MISMATCH_TERMS.get(country, [])) if source_type == "website" else []

    product_fit = "Both"
    if yarn_hits and not fabric_hits:
        product_fit = "Fiberglass Yarn"
    elif fabric_hits and not yarn_hits:
        product_fit = "Fiberglass Fabric"

    score = 0
    score += min(len(general_hits), 5) * 8
    score += min(len(yarn_hits), 5) * 12
    score += min(len(fabric_hits), 5) * 12
    if lead.get("email"):
        score += 14
    if lead.get("website"):
        score += 8
    if lead.get("company_name"):
        score += 6
    if source_type == "bill of lading":
        score += 18
    if source_type == "saas contact":
        score += 10
    score += min(len(buyer_hits), 4) * 7
    score += min(len(downstream_hits), 3) * 10
    score += min(len(company_evidence_hits), 3) * 4
    score -= min(len(negative_hits), 3) * 15
    if is_directory_source:
        score -= 35
    if mismatch_hits:
        score -= 45
    score = max(0, min(100, score))

    matched = yarn_hits + fabric_hits + general_hits + buyer_hits + downstream_hits + company_evidence_hits
    if matched:
        fit_reason = "Matched keywords: " + ", ".join(dict.fromkeys(matched[:8]))
    else:
        fit_reason = "No fiberglass keywords found yet; review manually."
    if is_directory_source:
        fit_reason = f"{fit_reason} Penalized: directory or marketplace source."
    if mismatch_hits:
        fit_reason = f"{fit_reason} Penalized: target-country mismatch."

    return {
        "match_score": score,
        "product_fit": product_fit,
        "fit_reason": fit_reason,
    }
