from __future__ import annotations

from .evidence import evidence_json, score_reason_text

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

    additions: list[dict] = []
    penalties: list[dict] = []

    def add(points: int, reason: str, terms: list[str]) -> int:
        if points and terms:
            additions.append({"points": points, "reason": reason, "terms": list(dict.fromkeys(terms))[:8]})
        return points

    def subtract(points: int, reason: str, terms: list[str]) -> int:
        if points and terms:
            penalties.append({"points": -points, "reason": reason, "terms": list(dict.fromkeys(terms))[:8]})
        return points

    product_fit = "Both"
    if yarn_hits and not fabric_hits:
        product_fit = "Fiberglass Yarn"
    elif fabric_hits and not yarn_hits:
        product_fit = "Fiberglass Fabric"

    score = 0
    score += add(min(len(general_hits), 5) * 8, "general fiberglass terms", general_hits)
    score += add(min(len(yarn_hits), 5) * 12, "yarn terms", yarn_hits)
    score += add(min(len(fabric_hits), 5) * 12, "fabric terms", fabric_hits)
    if lead.get("email"):
        score += add(14, "email present", [str(lead.get("email"))])
    if lead.get("website"):
        score += add(8, "company website", [str(lead.get("website"))])
    if lead.get("company_name"):
        score += add(6, "company name", [str(lead.get("company_name"))])
    if source_type == "bill of lading":
        score += add(18, "bill of lading buyer evidence", ["bill of lading"])
    if source_type == "saas contact":
        score += add(10, "SaaS contact source", [str(lead.get("source_name", "SaaS Contact") or "SaaS Contact")])
    score += add(min(len(buyer_hits), 4) * 7, "buyer terms", buyer_hits)
    score += add(min(len(downstream_hits), 3) * 10, "downstream application", downstream_hits)
    score += add(min(len(company_evidence_hits), 3) * 4, "company page evidence", company_evidence_hits)
    score -= subtract(min(len(negative_hits), 3) * 15, "negative terms", negative_hits)
    if is_directory_source:
        score -= subtract(35, "directory or marketplace source", [source_location])
    if mismatch_hits:
        score -= subtract(45, "target-country mismatch", mismatch_hits)
    score = max(0, min(100, score))

    matched = yarn_hits + fabric_hits + general_hits + buyer_hits + downstream_hits + company_evidence_hits
    evidence = {
        "additions": additions,
        "penalties": penalties,
        "matched_terms": list(dict.fromkeys(matched))[:12],
    }
    fit_reason = score_reason_text(evidence)

    return {
        "match_score": score,
        "product_fit": product_fit,
        "fit_reason": fit_reason,
        "score_evidence": evidence_json(evidence),
    }
